"""
Live trade-copier snapshot for MT5 EAs on OTHER accounts (`GET /api/ea/mirror`).

WHAT THIS IS FOR
-----------------
The older /api/ea/signals feed (ea_signals_router.py) is built from the bot's
own Trade rows and only ever drives OPENS on a mirror account: once a mirror
position fills it is left to its own SL/TP. This endpoint instead publishes
the master account's LIVE MT5 state — every open position and pending order,
read straight from the broker — so a mirror EA (mt5/EA/NexalSignalMirrorEA.mq5
v2+) can reconcile against it and do exactly what the master does:

  - a master position/order that the mirror lacks      -> open / place it
  - master SL/TP moved (breakeven, trailing, manual)   -> modify the mirror's
  - master volume reduced (partial close)              -> close the same share
  - master position/order gone (closed, cancelled)     -> close / cancel it

That includes trades opened or managed BY HAND on the master terminal, not
only those the bot placed — the snapshot is whatever MT5 shows.

WHY THE SNAPSHOT IS STRICT
---------------------------
A copier treats "ticket missing from the snapshot" as "master closed it". An
empty or partial list caused by a bridge hiccup would therefore close every
mirror position. So this endpoint never degrades: provider.fetch_mirror_snapshot()
raises unless the bridge reports the terminal connected AND an empty position
list is corroborated by zero margin / zero floating P/L, and any failure is a
503 — which the EA treats as "no information", never as "flat". The EA adds a
second guard of its own (a ticket must be missing from N consecutive
snapshots before it closes anything).

ONE BRIDGE READ FOR ALL MIRRORS
--------------------------------
Mirrors poll every few seconds. The snapshot (or the failure) is cached for
_SNAPSHOT_TTL seconds behind a lock, so N mirror accounts cost one round of
bridge calls per TTL rather than N.

AGES
----
MT5 position times are broker server time (often UTC+2/+3, shifting with DST)
with no reliable offset to query, so they are not used. A position's age comes
from its Trade row's fill time when the bot placed it, else from when this
process first saw the ticket. Tickets already open when this process started
have an UNKNOWN age (emitted as "-"); the EA does not market-open those, so a
backend restart can never make an hours-old position look brand new.

WIRE FORMAT (pipe-delimited — MQL5 has no JSON parser), version 4:
    V|4|utc_now|masterLogin|balance|equity|positionCount|orderCount
    P|ticket|symbol|side|volume|openPrice|sl|tp|ageMin|magic|tradeId|signalId|rawSymbol|channel
    O|ticket|symbol|type|volume|price|sl|tp|ageMin|magic|tradeId|signalId|rawSymbol|channel
    E
`symbol` is the master's symbol with its broker affixes stripped (EURUSD.r ->
EURUSD); `rawSymbol` is the exact master name. `side` is BUY/SELL; `type` is
BUY_LIMIT/SELL_LIMIT/BUY_STOP/SELL_STOP. `tradeId`/`signalId` link the ticket to
the bot's Trade row when there is one ("-" for manual trades) — signalId lets
the EA budget one risk across a multi-TP signal's legs. A ticket with no Trade
row takes its signalId from a live ticket with the same magic.

AUTH: same X-EA-Key / EA_API_KEY as the signals feed. Reached from the internet
only through dashboard/src/app/api/ea/mirror/route.ts (per-customer keys).
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse

from src.api.ea_signals_router import SEP, _fmt, require_ea_key

logger = logging.getLogger(__name__)

ea_mirror_router = APIRouter(prefix="/api/ea", tags=["ea-mirror"])

# Bump only on a breaking layout change; the EA refuses any version it doesn't
# know rather than misread field offsets.
EA_MIRROR_VERSION = 4

ROW_FIELDS = 15  # P and O rows — keep in sync with ROW_FIELDS in the EA

_SNAPSHOT_TTL = 1.5
_ORDER_TYPES = ("BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP", "BUY_STOP_LIMIT", "SELL_STOP_LIMIT")

_lock = asyncio.Lock()
_cache: Optional[Tuple[float, Optional[dict], Optional[str]]] = None  # (at, snapshot, error)
_provider = None
# ("P"|"O", ticket) -> first time this process saw it; None = already open at startup.
_first_seen: Dict[Tuple[str, str], Optional[datetime]] = {}
_baseline_taken = False


def base_symbol(raw: str) -> str:
    """Strip broker affixes: leading non-alphanumerics, then the leading run of
    uppercase letters/digits. EURUSD.r / EURUSDm / EURUSD+ / #US30 -> EURUSD /
    EURUSD / EURUSD / US30. All-lowercase names fall back to upper-casing."""
    s = (raw or "").strip()
    i = 0
    while i < len(s) and not s[i].isalnum():
        i += 1
    j = i
    while j < len(s) and (s[j].isdigit() or (s[j].isalpha() and s[j].isupper())):
        j += 1
    return s[i:j] or s.upper()


def _get_provider():
    global _provider
    if _provider is None:
        from src.integrations.trading.provider_factory import create_trading_provider

        _provider = create_trading_provider()
    return _provider


def _age_minutes(kind: str, ticket: str, trade, now: datetime) -> Optional[float]:
    ref = None
    if trade is not None:
        ref = (trade.executedAt or trade.createdAt) if kind == "P" else trade.createdAt
    if ref is None:
        key = (kind, ticket)
        if key not in _first_seen:
            _first_seen[key] = now if _baseline_taken else None
        ref = _first_seen[key]
    if ref is None:
        return None
    return max(0.0, (now - ref).total_seconds() / 60.0)


async def _build_snapshot() -> dict:
    global _baseline_taken
    raw = await _get_provider().fetch_mirror_snapshot()
    now = datetime.now(timezone.utc)

    positions = raw["positions"]
    orders = [o for o in raw["orders"] if o["type"].replace("ORDER_TYPE_", "") in _ORDER_TYPES]

    tickets = [p["id"] for p in positions] + [o["id"] for o in orders]
    by_ticket = {}
    if tickets:
        from src.core.database_service import db_service

        trades = await db_service.db.trade.find_many(
            where={"OR": [{"positionId": {"in": tickets}}, {"orderId": {"in": tickets}}]},
            include={"signal": True},
            order={"createdAt": "asc"},
        )
        # Ascending, so the newest row for a ticket wins.
        for t in trades:
            for key in (t.positionId, t.orderId):
                if key:
                    by_ticket[str(key)] = t

    # A bot-opened ticket with no Trade row of its own still carries its signal's
    # magic. Link it through a live sibling with the same magic so the EA budgets it
    # inside that signal; unlinked, it is sized like a hand-opened trade at a full
    # risk budget. A magic shared by two live signals (channels can reuse a message
    # id) is ambiguous and links nothing.
    by_magic, clash = {}, set()
    for item in positions + orders:
        t, magic = by_ticket.get(item["id"]), item.get("magic")
        if t is None or not magic:
            continue
        if magic in by_magic and by_magic[magic].signalId != t.signalId:
            clash.add(magic)
        by_magic.setdefault(magic, t)
    for magic in clash:
        del by_magic[magic]

    def link(item):
        t = by_ticket.get(item["id"])
        s = t or by_magic.get(item.get("magic"))
        return {
            "tradeId": t.id if t else None,
            "signalId": s.signalId if s else None,
            "channel": (s.signal.channelName if s and s.signal else None),
        }

    out_positions = []
    for p in positions:
        trade = by_ticket.get(p["id"])
        init_sl = (trade.stopLoss if trade and trade.stopLoss else p.get("stopLoss"))
        out_positions.append({
            "ticket": p["id"],
            "symbol": base_symbol(p["symbol"]),
            "rawSymbol": p["symbol"],
            "side": "BUY" if p["type"] == "POSITION_TYPE_BUY" else "SELL",
            "volume": p["volume"],
            "openPrice": p["openPrice"],
            "currentPrice": p.get("currentPrice"),
            "sl": p.get("stopLoss"),
            "tp": p.get("takeProfit"),
            "initSl": init_sl,
            "profit": p.get("profit"),
            "magic": p.get("magic"),
            "comment": p.get("comment"),
            "ageMinutes": _age_minutes("P", p["id"], trade, now),
            **link(p),
        })

    out_orders = []
    for o in orders:
        trade = by_ticket.get(o["id"])
        init_sl = (trade.stopLoss if trade and trade.stopLoss else o.get("stopLoss"))
        out_orders.append({
            "ticket": o["id"],
            "symbol": base_symbol(o["symbol"]),
            "rawSymbol": o["symbol"],
            "type": o["type"].replace("ORDER_TYPE_", ""),
            "volume": o["volume"],
            "price": o["openPrice"],
            "sl": o.get("stopLoss"),
            "tp": o.get("takeProfit"),
            "initSl": init_sl,
            "magic": o.get("magic"),
            "comment": o.get("comment"),
            "ageMinutes": _age_minutes("O", o["id"], trade, now),
            **link(o),
        })

    live = {("P", p["id"]) for p in positions} | {("O", o["id"]) for o in orders}
    for key in [k for k in _first_seen if k not in live]:
        del _first_seen[key]
    _baseline_taken = True

    acct = raw["account"]
    return {
        "version": EA_MIRROR_VERSION,
        "generatedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "master": {
            "login": str(acct.get("login")),
            "server": acct.get("server"),
            "company": acct.get("company"),
            "currency": acct.get("currency"),
            "leverage": acct.get("leverage"),
            "balance": acct.get("balance"),
            "equity": acct.get("equity"),
            "margin": acct.get("margin"),
            "freeMargin": acct.get("margin_free"),
            "profit": acct.get("profit"),
        },
        "positions": out_positions,
        "orders": out_orders,
    }


async def get_snapshot() -> dict:
    """Cached strict snapshot. Raises HTTPException(503) if it can't be trusted."""
    global _cache
    async with _lock:
        if _cache is None or time.monotonic() - _cache[0] >= _SNAPSHOT_TTL:
            try:
                _cache = (time.monotonic(), await _build_snapshot(), None)
            except NotImplementedError as exc:
                _cache = (time.monotonic(), None, str(exc))
            except Exception as exc:
                logger.warning("EA mirror snapshot unavailable: %s", exc)
                _cache = (time.monotonic(), None, f"master snapshot unavailable: {exc}")
        _, snapshot, error = _cache
    if snapshot is None:
        raise HTTPException(status_code=503, detail=error)
    return snapshot


def render_text(snap: dict) -> str:
    m = snap["master"]
    lines = [SEP.join([
        "V", str(EA_MIRROR_VERSION), snap["generatedAt"], _fmt(m["login"]),
        _fmt(m["balance"], 2), _fmt(m["equity"], 2),
        str(len(snap["positions"])), str(len(snap["orders"])),
    ])]
    for p in snap["positions"]:
        lines.append(SEP.join([
            "P", _fmt(p["ticket"]), _fmt(p["symbol"]), p["side"], _fmt(p["volume"], 3),
            _fmt(p["openPrice"], 6), _fmt(p["sl"], 6), _fmt(p["tp"], 6),
            _fmt(p["ageMinutes"], 1), _fmt(p["magic"]), _fmt(p["tradeId"]),
            _fmt(p["signalId"]), _fmt(p["rawSymbol"]), _fmt(p["channel"]),
            _fmt(p.get("initSl") or p.get("sl"), 6),
        ]))
    for o in snap["orders"]:
        lines.append(SEP.join([
            "O", _fmt(o["ticket"]), _fmt(o["symbol"]), o["type"], _fmt(o["volume"], 3),
            _fmt(o["price"], 6), _fmt(o["sl"], 6), _fmt(o["tp"], 6),
            _fmt(o["ageMinutes"], 1), _fmt(o["magic"]), _fmt(o["tradeId"]),
            _fmt(o["signalId"]), _fmt(o["rawSymbol"]), _fmt(o["channel"]),
            _fmt(o.get("initSl") or o.get("sl"), 6),
        ]))
    lines.append("E")
    return "\n".join(lines)


@ea_mirror_router.get("/mirror", response_class=PlainTextResponse, dependencies=[Depends(require_ea_key)])
async def get_ea_mirror() -> str:
    """Pipe-delimited live snapshot of the master account for the copier EA."""
    return render_text(await get_snapshot())


@ea_mirror_router.get("/mirror/state", dependencies=[Depends(require_ea_key)])
async def get_ea_mirror_state() -> JSONResponse:
    """Same snapshot as JSON, for the dashboard's Trade Copier page."""
    return JSONResponse(await get_snapshot())

