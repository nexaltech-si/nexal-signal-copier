"""
A simulated bot session for end-to-end scenarios.

Channel messages (post, reply, edit, delete) are built as Telethon events and
handed to the bot's real message handler — the calls the Telegram listener
makes. Everything behind it is the live code: intent classification, signal
extraction and reply parsing by the configured AI provider, continuity, risk,
the MT5 REST provider, order sync, the position monitor, a real database.

Replaced: Telegram (messages come from the scenario; the bot's notifications
are collected and printed) and the broker (simulator/fake_mt5_bridge.py).

Environment is prepared by `prepare_environment()`, which must run before any
bot module is imported. See scripts/simulate_full_flow.py for use.
"""
import asyncio
import os
import re
import sys
import traceback
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Callable, Dict, List, Optional

BRIDGE_PORT = int(os.environ.get("SIM_BRIDGE_PORT", "5055"))


def prepare_environment() -> None:
    for key, value in {
        "TELEGRAM_API_ID": "1", "TELEGRAM_API_HASH": "sim", "TELEGRAM_PHONE": "+10000000000",
        "PRIMARY_AI_PROVIDER": "deepseek", "FALLBACK_AI_PROVIDERS": "", "DEEPSEEK_MODEL": "deepseek-flash",
        "TRADING_PROVIDER": "mt5rest", "MT5_REST_API_URL": f"http://127.0.0.1:{BRIDGE_PORT}",
        "DRY_RUN": "false", "SKIP_METAAPI": "false",
    }.items():
        os.environ.setdefault(key, value)
    from loguru import logger
    logger.remove()
    logger.add(sys.stderr, level=os.environ.get("SIM_LOG_LEVEL", "CRITICAL"))
    if os.environ.get("SIM_LOG_FILE"):
        logger.add(os.environ["SIM_LOG_FILE"], level="DEBUG")


# What every scenario starts from. Automation that moves stops on its own is off,
# so a stop only moves when a channel message (or the scenario) says so; scenarios
# that test the automation switch it on.
BASELINE = dict(
    max_risk_per_trade_percent=1.0, enable_trading_brain=False, enable_equity_protection=False,
    require_manual_approval=False, enable_signal_validator=False, copy_master_mode=False,
    enable_instant_execution=True, min_lot_size=0.01, news_enable_filter=False,
    enable_runner_split=False, runner_share_percent=50.0,
    enable_auto_take_profit=True, enable_auto_partial=False, enable_trailing_stop=False,
    enable_breakeven_move=False, enable_ai_market_analysis=False,
    max_total_risk_per_symbol_percent=0.0, signal_continuity_window_minutes=30,
)


class Channel:
    """One Telegram channel: builds the events Telethon would deliver for it."""

    def __init__(self, session: "Session", chat_id: int, title: str):
        self.s, self.id, self.title = session, chat_id, title
        self.posts: Dict[int, dict] = {}

    def _event(self, msg_id: int, text: str, reply_to=None, edited: bool = False, date=None):
        now = datetime.now(timezone.utc)
        chat = SimpleNamespace(id=self.id, title=self.title, username=None)
        message = SimpleNamespace(
            id=msg_id, chat_id=self.id, text=text, message=text, raw_text=text,
            date=date or self.posts.get(msg_id, {}).get("date", now), edit_date=now if edited else None,
            sender_id=self.id, sender=chat, from_id=None, post=True, out=False,
            reply_to=SimpleNamespace(reply_to_msg_id=reply_to) if reply_to else None,
            media=None, photo=None, grouped_id=None, fwd_from=None, entities=None,
        )

        async def get_chat():
            return chat
        return SimpleNamespace(message=message, chat_id=self.id, get_chat=get_chat, chat=chat)

    async def post(self, text: str, reply_to: Optional[int] = None, date=None, msg_id: Optional[int] = None) -> int:
        """A new channel message; `reply_to` makes it a reply to that message."""
        msg_id = msg_id or self.s.next_message_id()
        self.posts[msg_id] = {"text": text, "date": date or datetime.now(timezone.utc)}
        shown = text.replace("\n", " / ")
        label = f"[{self.title}] #{msg_id}{f' ↩ #{reply_to}' if reply_to else ''}: \"{shown}\""
        await self.s.deliver(label, self.s.message_handler.process_message(
            self._event(msg_id, text, reply_to, date=date), self.s.trading_service.process_signal))
        return msg_id

    async def redeliver(self, msg_id: int) -> None:
        """The same message arriving again — what catch-up does after a restart."""
        text = self.posts[msg_id]["text"]
        shown = text.replace("\n", " / ")
        await self.s.deliver(f"[{self.title}] #{msg_id} delivered AGAIN (restart catch-up): \"{shown}\"",
                             self.s.message_handler.process_message(
                                 self._event(msg_id, text), self.s.trading_service.process_signal))

    async def edit(self, msg_id: int, text: str) -> None:
        self.posts[msg_id]["text"] = text
        shown = text.replace("\n", " / ")
        await self.s.deliver(f"[{self.title}] EDIT #{msg_id}: \"{shown}\"",
                             self.s.message_handler.process_edited_message(
                                 self._event(msg_id, text, edited=True), self.s.trading_service.process_signal))

    async def delete(self, msg_id: int) -> None:
        await self.s.deliver(f"[{self.title}] DELETE #{msg_id}", self.s.message_handler.process_deleted_messages(
            SimpleNamespace(chat_id=self.id, deleted_ids=[msg_id])))


class Session:
    def __init__(self, out=print, bridge=None):
        self.out = out
        self._bridge = bridge
        self.results: List[dict] = []
        self._scenario: Optional[dict] = None
        self._msg_id = 40000
        self._chat_id = -1001000000000
        self._notes: List[str] = []
        self._seen_log = 0

    # ── lifecycle ────────────────────────────────────────────────────────────
    async def start(self) -> None:
        from config import settings
        from simulator.fake_mt5_bridge import FakeMT5Bridge
        from src.core.prisma_client import prisma_client
        from src.core.database_service import db_service
        from src.integrations.telegram.unified_sender import notification_sender
        from src.integrations.trading.provider_manager import provider_manager
        from src.services.message_handler import message_handler
        from src.services.trading_service import trading_service
        from src.services.signal_continuity import signal_continuity
        from src.services.signal_service import signal_service
        from src.services.magic_number_service import magic_number_service
        from src.services.order_sync_service import order_sync_service
        from src.services.position_monitor_service import position_monitor_service
        from src.services.plan_watcher_service import plan_watcher_service

        self.settings_obj, self.db, self.prisma = settings, db_service, prisma_client
        self.message_handler, self.trading_service = message_handler, trading_service
        self.continuity, self.magic = signal_continuity, magic_number_service
        self.order_sync, self.monitor = order_sync_service, position_monitor_service
        self.plan_watcher = plan_watcher_service
        self.provider_manager = provider_manager

        self.bridge = self._bridge or FakeMT5Bridge()
        await self.bridge.start(BRIDGE_PORT)
        for key, value in BASELINE.items():
            setattr(settings, key, value)

        def note(text) -> None:
            self._notes.append(re.sub(r"<[^>]+>", "", str(text)).strip().replace("\n", " | "))

        async def send_message(message, *a, **k):
            note(message)

        def named(name):
            async def notify(*args, **kw):
                sig = next((a for a in args if hasattr(a, "symbol")), None)
                extra = next((a for a in args if isinstance(a, str)), "")
                what = name.replace("notify_", "").replace("_", " ")
                note(f"[{what}] {getattr(sig, 'symbol', '') or ''} "
                     f"{getattr(getattr(sig, 'order_type', None), 'value', '') or ''} {extra}".strip())
            return notify
        notification_sender.send_message = send_message
        for name in dir(notification_sender):
            if name.startswith("notify_"):
                setattr(notification_sender, name, named(name))

        await prisma_client.initialize()
        await provider_manager.start()
        self.provider = provider_manager.proxy
        trading_service.set_trading_provider(self.provider)
        signal_service.reinitialize()

    async def stop(self) -> None:
        await self.provider_manager.stop()
        if getattr(self.provider, "_session", None):
            await self.provider._session.close()
        await self.bridge.stop()
        await self.prisma.client.disconnect()

    # ── Telegram side ────────────────────────────────────────────────────────
    def next_message_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    def channel(self, title: str, chat_id: Optional[int] = None) -> Channel:
        """A channel for this session; `chat_id` replays a real one under its own id."""
        if chat_id is None:
            self._chat_id -= 1
            chat_id = self._chat_id
        return Channel(self, chat_id, title)

    # ── running things ───────────────────────────────────────────────────────
    async def sync(self) -> None:
        """One pass of what runs every few seconds live: order sync, then the position monitor."""
        self.provider._positions_cache = self.provider._orders_cache = None
        for _ in range(self.order_sync.CLOSE_GRACE_MISSES + 1):
            await self.order_sync.sync_all_active_orders()
        self.provider._positions_cache = None
        await self.monitor._check_all_positions()
        self.provider._positions_cache = self.provider._orders_cache = None
        await self.plan_watcher.tick()
        self.provider._positions_cache = self.provider._orders_cache = None

    def report(self) -> None:
        for line in self._notes:
            self.out(f"      bot: {line[:260]}")
        self._notes.clear()
        for line in self.bridge.log[self._seen_log:]:
            self.out(f"      broker ← {line}")
        self._seen_log = len(self.bridge.log)

    async def deliver(self, label: str, coro) -> None:
        self.out(f"   {label}")
        await coro
        await asyncio.sleep(0.3)
        await self.sync()
        self.report()

    async def tick(self, bid: float, symbol: str = "XAUUSD") -> None:
        events = self.bridge.tick(bid, symbol)
        self.out(f"   market: {symbol} bid {bid}" + "".join(f"\n      broker: {e}" for e in events))
        await self.sync()
        self.report()

    async def flatten(self) -> None:
        """End of a scenario: nothing left open at the broker, trade records brought up to date."""
        self.bridge.flatten()
        await self.sync()
        self._notes.clear()
        self._seen_log = len(self.bridge.log)

    async def restart(self) -> None:
        """What a bot restart loses and reloads: in-memory message / follow-up state."""
        self.out("   ── bot restarts ──")
        self.message_handler.processed_message_ids._d.clear()
        self.message_handler.recent_messages.clear()
        self.message_handler._edit_seen.clear()
        self.message_handler._channel_context.clear()
        self.continuity._awaiting.clear()
        self.continuity._deleted.clear()
        restored = await self.continuity.restore()
        self.out(f"      follow-up / repost marks restored from the database: {restored}")

    def set(self, **changes) -> None:
        """Change settings for the current scenario (restored to the baseline after it)."""
        for key, value in changes.items():
            setattr(self.settings_obj, key, value)

    # ── reading state ────────────────────────────────────────────────────────
    async def orders(self, msg_id: int) -> List[dict]:
        """Live orders of the setup that started with message `msg_id`, as the bot reads them."""
        magic = self.magic.generate_magic_number(msg_id)
        self.provider._positions_cache = self.provider._orders_cache = None
        both = await self.continuity._live_orders({magic}, True) + await self.continuity._live_orders({magic}, False)
        return sorted(both, key=lambda o: int(o["id"]))

    async def show(self, msg_id: int) -> List[dict]:
        orders = await self.orders(msg_id)
        for o in orders:
            side = "BUY " if "BUY" in o["type"] else "SELL"
            kind = "pending " if o["pending"] else "position"
            self.out(f"      {kind} #{o['id']} {o['symbol']} {side} {o['volume']:.2f} @ {o['openPrice']}  "
                     f"SL {o['stopLoss']}  TP {o['takeProfit'] or '—'}")
        if not orders:
            self.out("      (no open orders)")
        return orders

    async def record(self, channel: Channel, msg_id: int):
        sig = await self.db.db.signal.find_first(where={"channelId": str(channel.id), "messageId": msg_id},
                                                 include={"trades": True})
        return sig, (sig.trades if sig else [])

    async def signals(self, channel: Channel) -> list:
        return await self.db.db.signal.find_many(where={"channelId": str(channel.id)}, order={"createdAt": "asc"})

    def writes(self) -> int:
        return len(self.bridge.log)

    def since(self, mark: int) -> List[str]:
        return self.bridge.log[mark:]

    # ── results ──────────────────────────────────────────────────────────────
    def check(self, name: str, ok, detail: str = "") -> bool:
        ok = bool(ok)
        self._scenario["checks"].append((name, ok, detail))
        self.out(f"   {'PASS' if ok else 'FAIL'}  {name}{('  — ' + str(detail)) if detail else ''}")
        return ok

    def finding(self, text: str) -> None:
        """Behaviour worth a human decision: not a failed check, but not obviously right either."""
        self._scenario["findings"].append(text)
        self.out(f"   NOTE  {text}")

    async def run(self, name: str, scenario: Callable) -> None:
        self._scenario = {"name": name, "checks": [], "findings": [], "error": None}
        self.out(f"\n── {name} " + "─" * max(4, 76 - len(name)))
        try:
            await scenario(self)
        except Exception as e:
            self._scenario["error"] = f"{type(e).__name__}: {e}"
            self.out(f"   ERROR  scenario crashed: {type(e).__name__}: {e}")
            self.out("   " + traceback.format_exc().strip().splitlines()[-3].strip())
        try:
            await self.flatten()
        except Exception as e:
            self.out(f"   ERROR  could not flatten after the scenario: {e}")
        for key, value in BASELINE.items():
            setattr(self.settings_obj, key, value)
        self.results.append(self._scenario)

    def summary(self) -> int:
        self.out("\n" + "═" * 80)
        failed = 0
        for r in self.results:
            bad = [c for c in r["checks"] if not c[1]]
            state = "ERROR" if r["error"] else "FAIL " if bad else "PASS "
            failed += bool(bad or r["error"])
            self.out(f"{state} {r['name']}  ({len(r['checks']) - len(bad)}/{len(r['checks'])} checks)")
            for name, _, detail in bad:
                self.out(f"        ✗ {name}{('  — ' + str(detail)) if detail else ''}")
            if r["error"]:
                self.out(f"        ✗ {r['error']}")
            for f in r["findings"]:
                self.out(f"        • note: {f}")
        total = sum(len(r["checks"]) for r in self.results)
        passed = sum(1 for r in self.results for c in r["checks"] if c[1])
        self.out(f"\n{len(self.results) - failed} of {len(self.results)} scenarios passed, "
                 f"{passed} of {total} checks")
        return failed
