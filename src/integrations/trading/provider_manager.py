"""
Provider manager: one shared, hot-switchable trading provider.

Every service obtains the provider through ``create_trading_provider()``, which returns
``provider_manager.proxy`` - a thin object that forwards attribute access to whichever provider is
currently active. Switching the active provider (MetaAPI <-> MT5 REST) therefore takes effect for
every service at once, with no restart.

MetaAPI and MT5 REST are DIFFERENT broker accounts, and exactly one is active at a time: there is no
automatic fallback between them. A switch is therefore refused while any bot trade is still open or
pending (broker side or in the database) - those trades live on the old account and could not be
managed from the new one.

Switch flow (``switch``): build + initialize the new provider FIRST, verify it can read the account,
then swap atomically and disconnect the old one. If anything fails the old provider stays active.
"""
import asyncio
import time
from typing import Awaitable, Callable, List, Optional

from loguru import logger
from src.utils.tasks import spawn

from config import settings
from src.utils.audit import audit

VALID_PROVIDERS = ("metaapi", "mt5rest")
INIT_TIMEOUT_SECONDS = 180
OLD_DISCONNECT_DELAY_SECONDS = 5
# Retrying credentials that failed to apply (e.g. a rotated key the broker side doesn't know yet)
CREDENTIAL_RETRY_INTERVAL_SECONDS = 20
CREDENTIAL_RETRY_WINDOW_SECONDS = 600


class ProviderSwitchBlocked(Exception):
    """Switch refused because bot-managed positions/orders are open."""


def normalize_provider_name(name: Optional[str]) -> str:
    n = (name or "").lower().strip()
    return n if n in VALID_PROVIDERS else "metaapi"


def _build(name: str):
    if name == "mt5rest":
        from src.integrations.trading.mt5rest_provider import MT5RestProvider
        return MT5RestProvider()
    from src.integrations.metaapi.trader import MetaAPITrader
    return MetaAPITrader()


class ProviderProxy:
    """Forwards everything to the manager's current provider (survives switches)."""

    __slots__ = ("_manager",)

    def __init__(self, manager: "ProviderManager"):
        object.__setattr__(self, "_manager", manager)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return getattr(self._manager.active, name)

    def __setattr__(self, name, value):
        setattr(self._manager.active, name, value)

    def __repr__(self):
        return f"<ProviderProxy -> {self._manager.active_name}>"


SwitchHook = Callable[[str, str, Optional[float]], Awaitable[None]]


class ProviderManager:
    def __init__(self):
        self.proxy = ProviderProxy(self)
        self._active = None
        self._active_name: Optional[str] = None
        self._lock = asyncio.Lock()
        self._hooks: List[SwitchHook] = []
        self._last_switch: Optional[dict] = None
        self._cred_retry_task: Optional[asyncio.Task] = None

    # ── accessors ────────────────────────────────────────────────────────

    @property
    def active(self):
        """Current provider; lazily builds an UNINITIALIZED one (legacy behaviour)."""
        if self._active is None:
            self._active_name = normalize_provider_name(settings.trading_provider)
            self._active = _build(self._active_name)
        return self._active

    @property
    def active_name(self) -> str:
        if self._active_name is None:
            _ = self.active
        return self._active_name

    def add_switch_hook(self, hook: SwitchHook):
        """hook(old_name, new_name, old_balance) runs after a successful switch (re-wire risk services etc.)."""
        self._hooks.append(hook)

    # ── lifecycle ────────────────────────────────────────────────────────

    async def start(self):
        """Initialize the configured provider (startup)."""
        provider = self.active
        await provider.initialize()
        return self.proxy

    async def stop(self):
        """Nothing to stop (kept for symmetry with start)."""
        return None

    # ── switching ────────────────────────────────────────────────────────

    async def _open_trade_items(self, provider) -> list:
        """Bot-managed trades/orders still open - on the broker AND in the database (a DB trade whose
        ticket is not on the new account would be wrongly marked closed by order sync)."""
        items = []
        try:
            for p in await provider.get_open_positions(use_cache=False) or []:
                if p.get("magic") or p.get("clientId"):
                    items.append(f"position {str(p.get('id'))[:10]}")
            for o in await provider.get_all_pending_orders(use_cache=False) or []:
                if o.get("magic") or o.get("clientId"):
                    items.append(f"order {str(o.get('id'))[:10]}")
        except Exception as e:
            logger.warning(f"Could not inspect open items before switch: {e}")
        try:
            from src.core.database_service import db_service
            rows = await db_service.db.trade.find_many(
                where={"status": {"notIn": ["CLOSED", "CANCELLED", "FAILED"]}}
            )
            known = {str(i).split()[-1] for i in items}
            for t in rows or []:
                ref = str(t.positionId or t.orderId or t.id)[:10]
                if ref not in known:
                    items.append(f"trade {ref}")
        except Exception as e:
            logger.warning(f"Could not check database trades before switch: {e}")
        return items

    async def switch(self, target: str, reason: str = "manual", rebuild: bool = False) -> dict:
        """
        Make `target` the active provider. `rebuild=True` re-creates the same provider type
        (used after its credentials/URL changed). Raises on failure with the old provider intact.
        """
        target = (target or "").lower().strip()
        if target not in VALID_PROVIDERS:
            raise ValueError(f"Unknown provider '{target}' (use: {', '.join(VALID_PROVIDERS)})")

        async with self._lock:
            old, old_name = self._active, self._active_name
            if old is not None and target == old_name and not rebuild and getattr(old, "is_connected", False):
                return {"changed": False, "active": old_name, "message": "already active"}

            old_balance = None
            if old is not None and target != old_name:
                open_items = await self._open_trade_items(old)
                if open_items:
                    raise ProviderSwitchBlocked(
                        f"{len(open_items)} bot trade(s)/order(s) are still open on {old_name} "
                        f"({', '.join(open_items[:5])}). MetaAPI and MT5 are different accounts, so they cannot be "
                        f"moved: close or cancel them first."
                    )
            if old is not None and getattr(old, "is_connected", False):
                try:
                    old_balance = (await asyncio.wait_for(old.get_account_info(use_cache=False), timeout=10)).balance
                except Exception:
                    old_balance = None

            logger.info(f"🔀 Switching trading provider: {old_name} → {target} ({reason})")
            new = _build(target)
            try:
                await asyncio.wait_for(new.initialize(), timeout=INIT_TIMEOUT_SECONDS)
                await asyncio.wait_for(new.get_account_info(use_cache=False), timeout=30)
            except Exception as e:
                try:
                    await new.disconnect()
                except Exception as _exc:
                    logger.debug(f"Suppressed exception: {_exc!r}")
                logger.error(f"❌ Provider switch to {target} failed, keeping {old_name}: {e}")
                audit("AUDIT", f"Provider switch to {target} FAILED, kept {old_name}", "HIGH",
                      {"error": str(e)[:300], "reason": reason}, module="provider_manager")
                raise

            self._active, self._active_name = new, target
            settings.trading_provider = target
            self._last_switch = {"from": old_name, "to": target, "reason": reason, "at": time.time()}
            await self._persist(target)
            await self._clear_caches()

            if old is not None:
                spawn(self._retire(old, old_name))

            for hook in list(self._hooks):
                try:
                    await hook(old_name or "", target, old_balance)
                except Exception as e:
                    logger.error(f"Provider switch hook failed: {e}")

            audit("AUDIT", f"Trading provider switched {old_name} -> {target}", "MEDIUM",
                  {"from": old_name, "to": target, "reason": reason}, module="provider_manager")
            logger.success(f"✅ Trading provider is now {target}")
            await self._notify(f"🔀 Trading provider switched: <b>{old_name}</b> → <b>{target}</b> ({reason})")
            return {"changed": True, "active": target, "from": old_name, "reason": reason}

    async def _retire(self, old, old_name):
        await asyncio.sleep(OLD_DISCONNECT_DELAY_SECONDS)  # let in-flight calls on the old provider finish
        try:
            await old.disconnect()
            logger.info(f"🔌 Old provider {old_name} disconnected")
        except Exception as e:
            logger.debug(f"Error disconnecting old provider {old_name}: {e}")

    async def _persist(self, target: str):
        svc = getattr(settings, "_db_settings_service", None)
        if svc is None:
            return
        try:
            await svc.set_setting("TRADING_PROVIDER", target)
        except Exception as e:
            logger.warning(f"Could not persist TRADING_PROVIDER={target}: {e}")

    @staticmethod
    async def _clear_caches():
        try:
            from src.services.position_cache import position_cache
            await position_cache.invalidate_positions()
            await position_cache.invalidate_orders()
        except Exception as e:
            logger.debug(f"Cache clear after switch failed: {e}")

    @staticmethod
    async def _notify(text: str):
        try:
            from src.integrations.telegram.unified_sender import notification_sender
            await notification_sender.send_message(text)
        except Exception as e:
            logger.debug(f"Provider notification failed: {e}")

    # ── settings hot-reload integration ──────────────────────────────────

    async def on_settings_reload(self, changed_keys: set):
        """Called by Settings.reload_from_db with the DB keys whose value just changed."""
        if self._active is None or not changed_keys:
            return
        wanted = normalize_provider_name(settings.trading_provider)
        try:
            if "TRADING_PROVIDER" in changed_keys and wanted != self._active_name:
                await self.switch(wanted, reason="settings change")
                return
        except Exception as e:
            # Revert so the next reload doesn't retry forever, and tell the user why
            settings.trading_provider = self._active_name
            await self._persist(self._active_name)
            await self._notify(f"⚠️ Provider switch to <b>{wanted}</b> failed - staying on "
                               f"<b>{self._active_name}</b>.\n{str(e)[:300]}")
            return

        cred_keys = {
            "metaapi": {"METAAPI_TOKEN", "METAAPI_ACCOUNT_ID"},
            "mt5rest": {"MT5_REST_API_URL", "MT5_REST_API_KEY"},
        }[self._active_name]
        try:
            if changed_keys & cred_keys:
                await self.switch(self._active_name, reason="credentials changed", rebuild=True)
            elif "METAAPI_USE_STREAMING" in changed_keys and hasattr(self._active, "apply_streaming_setting"):
                await self._active.apply_streaming_setting()
        except Exception as e:
            if changed_keys & cred_keys:
                # New credentials often can't work yet (e.g. a rotated MT5 key the bridge
                # hasn't loaded). The reload won't fire again for a value that is already
                # stored, so keep retrying instead of staying on the old key for good.
                self._schedule_credential_retry()
            await self._notify(f"⚠️ Reconnect after settings change failed - still on previous connection, "
                               f"retrying for {CREDENTIAL_RETRY_WINDOW_SECONDS // 60} min.\n{str(e)[:300]}")

    def _schedule_credential_retry(self):
        if self._cred_retry_task is not None and not self._cred_retry_task.done():
            return
        self._cred_retry_task = spawn(self._retry_credentials(), name="provider-credential-retry")

    async def _retry_credentials(self):
        deadline = time.monotonic() + CREDENTIAL_RETRY_WINDOW_SECONDS
        while time.monotonic() < deadline:
            await asyncio.sleep(CREDENTIAL_RETRY_INTERVAL_SECONDS)
            try:
                await self.switch(self._active_name, reason="credentials changed (retry)", rebuild=True)
                logger.success("✅ New provider credentials applied")
                return
            except Exception as e:
                logger.warning(f"⚠️ New provider credentials still not accepted, retrying: {str(e)[:200]}")
        await self._notify("⚠️ New trading-provider credentials were never accepted - still on the previous "
                           "connection. Check the key/URL, then save the setting again or restart the bot.")

    # ── status ───────────────────────────────────────────────────────────

    async def _is_healthy(self, provider) -> bool:
        try:
            if not getattr(provider, "is_connected", False):
                return False
            verify = getattr(provider, "_verify_connection", None)
            if verify is not None:
                return bool(await asyncio.wait_for(verify(), timeout=15))
            return True
        except Exception:
            return False

    async def status(self) -> dict:
        p = self._active
        info = {
            "active": self._active_name,
            "configured": normalize_provider_name(settings.trading_provider),
            "connected": bool(getattr(p, "is_connected", False)) if p else False,
            "healthy": await self._is_healthy(p) if p else False,
            "live_reads": bool(getattr(p, "live_reads", False)) if p else False,
            "last_switch": self._last_switch,
        }
        return info


provider_manager = ProviderManager()
