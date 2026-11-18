"""
Copy Master Service

Mirrors the FAP EA v1.10+ InpCopyMaster logic in Python:
  - The master MT5 account is the source of truth.
  - While the master has NO running position for a symbol, this account holds nothing.
  - The moment the master position is RUNNING, this account enters AT MARKET using
    the master's real SL/TP (never a limit order at the signal's entry price).
  - Pending copy intents are held in memory and retried every poll_interval_seconds.

Usage in mt5rest_provider.py:
  from src.services.copy_master_service import copy_master_service

  state, pos = await copy_master_service.master_live_state(symbol, direction)
  if state == "RUNNING":
      # enter at market with pos["sl"] / pos["tp"]
  else:
      await copy_master_service.register_intent(key, signal, risk_assessment)
"""

import asyncio
from datetime import datetime
from typing import Dict, Optional, Tuple

import aiohttp
from loguru import logger

from config import settings

# Returned states (mirrors mt5_book.py in the FAP platform)
RUNNING  = "RUNNING"   # master has an open position for this symbol+direction
PENDING  = "PENDING"   # master has a pending order but no position yet
NONE     = "NONE"      # master holds nothing
UNKNOWN  = "UNKNOWN"   # master MT5 API did not answer

_COPY_MIN_REMAINING_RR = 0.8   # mirrors FAP EA COPY_MIN_REMAINING_RR
_BOOK_TTL = 3.0                # seconds to cache the master book


class _MasterBook:
    """Thin client that fetches the master account's live MT5 book."""

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._cache: Optional[dict] = None
        self._cache_at: float = 0.0

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        key = settings.mt5_master_api_key or settings.mt5_rest_api_key
        if key:
            h["X-API-Key"] = key
        return h

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=5),
            )
        return self._session

    async def fetch(self) -> Optional[dict]:
        """Return {"positions": [...], "orders": [...]} from the master, or None."""
        # Fall back to the app's own MT5 REST URL when no separate master URL is set.
        base = (settings.mt5_master_api_url or settings.mt5_rest_api_url).rstrip("/")
        if not base:
            return None

        now = datetime.now().timestamp()
        if self._cache is not None and (now - self._cache_at) < _BOOK_TTL:
            return self._cache

        try:
            session = await self._ensure_session()
            headers = self._headers()
            async with session.get(f"{base}/get_positions", headers=headers) as r1, \
                       session.get(f"{base}/get_orders", headers=headers)   as r2:
                if r1.status != 200 or r2.status != 200:
                    logger.warning("copy_master: master MT5 HTTP %s/%s", r1.status, r2.status)
                    return None
                positions = await r1.json()
                orders    = await r2.json()
        except Exception as exc:
            logger.warning("copy_master: master book fetch failed (%s)", exc)
            return None

        if isinstance(positions, dict):
            positions = positions.get("positions", [])
        if isinstance(orders, dict):
            orders = orders.get("orders", [])

        book = {"positions": positions or [], "orders": orders or []}
        self._cache    = book
        self._cache_at = datetime.now().timestamp()
        return book

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()


class CopyMasterService:
    """
    Holds pending copy intents and drives them to execution once the master
    account has a running position for the matching symbol + direction.

    Intent key: "<symbol>:<direction>" e.g. "XAUUSD:SELL"
    """

    def __init__(self):
        self._book  = _MasterBook()
        self._intents: Dict[str, dict] = {}  # key -> intent payload
        self._task: Optional[asyncio.Task] = None
        self._poll_interval = 10  # seconds, matches typical EA poll

    # ── Public API ────────────────────────────────────────────────────────

    async def master_live_state(
        self, symbol: str, direction: str
    ) -> Tuple[str, Optional[dict]]:
        """
        (state, position_or_None) for this symbol+direction from the master.

        state is RUNNING / PENDING / NONE / UNKNOWN.
        position_or_None carries {"sl", "tp", "price_open", ...} when RUNNING.
        """
        effective_url = settings.mt5_master_api_url or settings.mt5_rest_api_url
        if not settings.copy_master_mode or not effective_url:
            return NONE, None

        book = await self._book.fetch()
        if book is None:
            return UNKNOWN, None

        sym_upper = symbol.upper()
        dir_upper = direction.upper()
        # direction in MT5 positions: type 0 = BUY, 1 = SELL
        want_buy = dir_upper in ("BUY", "LONG")

        def _match_symbol(master_sym: str, query_sym: str) -> bool:
            m = master_sym.upper()
            q = query_sym.upper()
            return m == q or m.startswith(q) or q.startswith(m)

        for pos in book["positions"]:
            pos_sym = str(pos.get("symbol", "")).upper()
            pos_type = int(pos.get("type", -1))
            pos_is_buy = (pos_type == 0)
            if _match_symbol(pos_sym, sym_upper) and pos_is_buy == want_buy:
                return RUNNING, pos

        for ord_ in book["orders"]:
            ord_sym  = str(ord_.get("symbol", "")).upper()
            ord_type = int(ord_.get("type", -1))
            # types 0/2/4 are buy-side; 1/3/5 are sell-side
            ord_is_buy = ord_type in (0, 2, 4)
            if _match_symbol(ord_sym, sym_upper) and ord_is_buy == want_buy:
                return PENDING, None

        return NONE, None

    async def register_intent(self, key: str, payload: dict) -> None:
        """
        Store a pending copy intent.  The background loop will execute it once
        the master account has a running position for the signal.

        payload must contain:
          symbol, direction, stop_loss, take_profit (list), lot_size,
          magic_number, channel_id, signal_id
          and an "execute_fn" callable: async fn(market_sl, market_tp) -> TradeResult
        """
        if key not in self._intents:
            logger.info("copy_master: queued pending intent %s", key)
        self._intents[key] = payload

    def cancel_intent(self, key: str) -> None:
        self._intents.pop(key, None)

    def pending_keys(self):
        return list(self._intents.keys())

    # ── Background loop ───────────────────────────────────────────────────

    async def start(self):
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="copy_master_loop")
            logger.info("copy_master: background loop started (poll=%ds)", self._poll_interval)

    async def stop(self):
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._book.close()
        logger.info("copy_master: stopped")

    async def _loop(self):
        while True:
            await asyncio.sleep(self._poll_interval)
            if not self._intents:
                continue
            if not settings.copy_master_mode:
                continue
            await self._fire_ready_intents()

    async def _fire_ready_intents(self):
        for key, intent in list(self._intents.items()):
            try:
                symbol    = intent["symbol"]
                direction = intent["direction"]
                state, pos = await self.master_live_state(symbol, direction)

                if state == UNKNOWN:
                    logger.debug("copy_master: %s — master unreachable, waiting", key)
                    continue

                if state in (NONE, PENDING):
                    logger.debug("copy_master: %s — master %s, holding", key, state)
                    continue

                # Master is RUNNING — extract its real SL/TP
                master_sl = float(pos.get("sl") or 0) or intent.get("stop_loss")
                master_tp_raw = pos.get("tp") or 0
                master_tp = float(master_tp_raw) if master_tp_raw else None

                execute_fn = intent.get("execute_fn")
                if execute_fn is None:
                    logger.warning("copy_master: %s has no execute_fn, dropping", key)
                    del self._intents[key]
                    continue

                logger.info("copy_master: %s — master RUNNING, entering at market sl=%s tp=%s",
                            key, master_sl, master_tp)
                result = await execute_fn(master_sl, master_tp)

                if result and result.success:
                    logger.success("copy_master: %s executed — ticket %s", key, result.position_id)
                    del self._intents[key]
                else:
                    err = result.error_message if result else "unknown"
                    retries = intent.get("retries", 0) + 1
                    intent["retries"] = retries
                    if retries >= 5:
                        logger.error("copy_master: %s execution failed 5 times (%s), dropping intent", key, err)
                        del self._intents[key]
                    else:
                        logger.warning("copy_master: %s execution failed (%s), will retry (attempt %d/5)",
                                       key, err, retries)

            except Exception as exc:
                logger.error("copy_master: error processing intent %s: %s", key, exc)


copy_master_service = CopyMasterService()
