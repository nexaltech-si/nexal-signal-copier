"""
Protected trade-mirroring feed for MT5 EAs on OTHER accounts (`GET /api/ea/signals`).

LEGACY: this is the open-only feed used by NexalSignalMirrorEA v1.x. EA v2+
reads the live trade-copier snapshot instead (src/api/ea_mirror_router.py),
which also copies SL/TP changes, partial closes, closes and cancellations.
Kept so v1 terminals keep working until they're upgraded.

WHAT THIS IS FOR
-----------------
Your primary account trades through the MetaAPI cloud SDK
(src/integrations/metaapi/trader.py), driven by trading_service.py's own
risk assessment and (optionally) Telegram manual approval. That pipeline is
completely unaffected by this router — it only ever reads from the DB.

This endpoint exists so OTHER MT5 accounts/terminals (different brokers,
different balances — "mirror" accounts) can independently open the same
trades your primary account already opened, each sizing its own position
from its own equity. It is consumed by mt5/EA/NexalSignalMirrorEA.mq5, which
DOES place real orders — unlike the old read-only viewer this replaces.

WHY A TRADE ROW (not a Signal), AND WHICH STATES
------------------------------------------------------------------
A Signal can sit in PENDING / VALIDATED / AWAITING_APPROVAL for a long time,
or end in REJECTED / EXPIRED — none of that should ever reach a mirror
account. The one and only place a Trade row gets created is inside
trading_service._execute_approved_trade() / ._execute(), which runs on BOTH
the no-approval-required path AND the post-Telegram-approval path (see
src/integrations/telegram/approval_commands.py). So "this Trade exists" is
already proof the signal cleared approval (or never needed it).

We emit the Trade's own `status` (see database_service — the actual strings
are PENDING/RUNNING/CANCELLED/CLOSED; the Prisma schema's status comment is
stale) and let the mirror EA decide what to do with each:

  PENDING  — the master placed a limit/stop that has NOT filled yet. The
             mirror should place the SAME order at the same price, so each
             account fills on its own broker's terms. Emitting only RUNNING
             (as v2 did) forced the mirror to wait for the master's fill and
             then MARKET-enter — a different, later price every time.
  RUNNING  — the master's order is filled and live. If the mirror already
             placed this trade's PENDING order it just lets that fill; if it
             never saw a PENDING (a straight market order, or the EA started
             mid-life) it opens at market, subject to a staleness cutoff.
  CANCELLED/CLOSED — terminal. Emitted for a short recent window so the mirror
             can cancel its own still-unfilled pending order (a cancelled
             master limit must not later fill as an orphan mirror trade). A
             mirror position that already filled is left alone — it manages
             its own exit (see below).

ONE ROW PER TRADE, GROUPED BY signalId
----------------------------------------
A signal with multiple take-profit legs or scale-in entries produces multiple
Trade rows (tpLevel / entryLeg), each already sized and priced independently
by the server. Emitting one feed row per Trade — using that Trade's own
entryPrice/stopLoss/takeProfit, not the raw Signal fields — lets a mirror EA
open exactly the same order structure the master has, using the actual values
sent to the broker (post risk-assessment, post any brain adjustment).

Each row also carries its `signalId`, because those N legs are ONE signal's
risk split across N positions — the master sized a single risk budget and
distributed the lots across the legs (see mt5rest_provider._execute_multi_tp_trade).
A mirror EA MUST group rows by signalId and likewise size ONE risk budget
across the legs; sizing each leg at full risk would multiply a 10-leg signal's
risk 10x on the mirror account. The per-leg `lotSize` field carries the
master's own distribution so the mirror can split its budget in the same
proportions.

NO CLOSE DIRECTIVE FOR FILLED POSITIONS, BY DESIGN
------------------------------------------------------
A CANCELLED/CLOSED row tells the mirror to cancel a still-UNFILLED pending
order only. It is never a directive to close a mirror position that already
filled: each mirror account manages its own exit via the SL/TP it set at
open. Different broker, different spread, different fill — force-syncing
closes across accounts would be approximate at best and is not what this
does. Once past its brief terminal window a closed trade simply drops out.

WHY PIPE-DELIMITED, NOT JSON
-----------------------------
MQL5 has no native JSON parser. Same wire-format approach as the sibling
forex-analytics-platform project's /signals/ea feed.

AUTH
----
Same X-EA-Key / EA_API_KEY pattern as before: constant-time comparison,
fails closed (503) if EA_API_KEY is not configured. This router is not
meant to be reachable from the internet directly — see
dashboard/src/app/api/ea/signals/route.ts, which is the actual public,
internet-facing entry point. It authenticates each request against a
per-customer key stored (hashed) in the dashboard's own database — see
dashboard/src/lib/apiKeys.ts — and only then calls this router using this
process's EA_API_KEY, which a customer's key never grants direct access to.
"""

import logging
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import PlainTextResponse

from config import settings

logger = logging.getLogger(__name__)

ea_signals_router = APIRouter(prefix="/api/ea", tags=["ea-signals"])

# Wire-format version. Bump only on a breaking layout change; the EA rejects
# any version it doesn't recognize rather than risk misparsing field offsets.
#
# v3: added a `state` field (PENDING/RUNNING/CANCELLED/CLOSED) and a `signalId`
#     field as the last two columns, and the feed now emits PENDING orders and
#     recently-terminal ones (not just RUNNING) so a mirror EA can place the
#     same limit order, dedup by trade id, cancel its own pending order when the
#     master cancels, and — via signalId — GROUP the legs of one signal so it
#     sizes ONE risk budget across them instead of full risk per leg. Also fixed
#     the direction field to carry the order direction (BUY/SELL, from
#     Trade.orderType) rather than the signal action ("OPEN").
EA_FEED_VERSION = 3

SEP = "|"
NULL = "-"

# Field count of an "S" record — kept in one place so the router and the docs
# above always agree with FillTrade()'s expectations in the EA.
SIG_FIELDS = 16

# Trade states the mirror feed cares about.
#   OPEN_STATES     — the master currently has this order live (unfilled
#                     PENDING limit/stop, or a filled RUNNING position). Always
#                     emitted, regardless of age, so long-open trades stay
#                     visible for the whole time the master holds them.
#   TERMINAL_STATES — the order is done. Emitted only for a short recent window
#                     (updatedAt >= since) so a mirror EA can react once — e.g.
#                     cancel a still-pending mirror order when the master's
#                     PENDING was CANCELLED, or clean up when it CLOSED before
#                     the mirror's limit ever filled. After the window they
#                     simply drop out.
OPEN_STATES = ("PENDING", "RUNNING")
TERMINAL_STATES = ("CANCELLED", "CLOSED")


async def require_ea_key(x_ea_key: Optional[str] = Header(None, alias="X-EA-Key")) -> None:
    """Authenticate the EA feed. Fail closed if EA_API_KEY is unset."""
    if not settings.ea_api_key:
        logger.error("EA feed requested but EA_API_KEY is not configured — refusing")
        raise HTTPException(
            status_code=503,
            detail="EA feed disabled: EA_API_KEY is not configured on the server",
        )
    if not x_ea_key or not secrets.compare_digest(x_ea_key, settings.ea_api_key):
        raise HTTPException(status_code=403, detail="Valid X-EA-Key header required")


def _fmt(value, dp: int = 5) -> str:
    """Render a value for the wire, collapsing None/NaN to the NULL sentinel."""
    if value is None:
        return NULL
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        if isinstance(value, float):
            if value != value or value in (float("inf"), float("-inf")):
                return NULL
            return f"{value:.{dp}f}"
        return str(value)
    text = str(value).replace(SEP, "/").replace("\n", " ").replace("\r", " ").strip()
    return text or NULL


def _trade_line(trade, now: datetime) -> str:
    """Render one Trade as a pipe-delimited mirror directive."""
    signal = trade.signal
    pair = (trade.symbol or "").upper()
    dp = 3 if ("JPY" in pair or pair.startswith("XA")) else 5

    # Order DIRECTION (BUY/SELL) — NOT trade.action, which holds the signal
    # action ("OPEN"/"CLOSE"/...). The mirror EA opens BUY vs SELL off this
    # field, so it must be the real direction: Trade.orderType, set from the
    # signal's order_type at trade creation. Fall back to the signal's own
    # orderType, then BUY, so a legacy row without orderType still resolves.
    direction = (
        getattr(trade, "orderType", None)
        or (getattr(signal, "orderType", None) if signal else None)
        or "BUY"
    )
    direction = str(direction).upper()

    # Reference time: when it filled (RUNNING) or when the order was placed
    # (PENDING). Used only for the RUNNING market-open staleness cutoff on the
    # EA side; a PENDING order sits at a fixed price so its age is not a reason
    # to skip it.
    ref_at = trade.executedAt or trade.createdAt
    # Computed server-side (UTC-to-UTC) rather than left for the EA to derive
    # from a timestamp string: an MT5 terminal's clock is broker/server time,
    # often several hours off UTC with no reliable offset to query, so any
    # client-side "how old is this" math would be guessing at that offset.
    age_minutes = (now - ref_at).total_seconds() / 60.0 if ref_at else None

    return SEP.join([
        "S",                                                  # 0  record type
        _fmt(trade.id),                                       # 1  trade id (EA dedup key)
        _fmt(pair),                                            # 2  symbol
        _fmt(direction),                                       # 3  BUY / SELL (order direction)
        _fmt(trade.entryPrice, dp),                             # 4  entry (fill price, or pending order price)
        _fmt(trade.stopLoss, dp),                               # 5  stop loss
        _fmt(trade.takeProfit, dp),                             # 6  take profit (this leg)
        _fmt(trade.lotSize, 2),                                 # 7  master's own lot size (informational)
        _fmt(signal.confidence if signal else None, 2),         # 8  extraction confidence 0..1
        _fmt(signal.channelName if signal else None),           # 9  source Telegram channel
        _fmt(ref_at.strftime("%Y-%m-%dT%H:%M:%SZ") if ref_at else None),  # 10 filled/placed (UTC)
        _fmt(trade.tpLevel),                                    # 11 TP leg number, if multi-TP
        _fmt(trade.entryLeg),                                   # 12 scale-in leg number, if any
        _fmt(age_minutes, 1),                                   # 13 minutes since fill/placement (server-computed)
        _fmt(trade.status),                                     # 14 state: PENDING/RUNNING/CANCELLED/CLOSED
        _fmt(trade.signalId),                                   # 15 signal id — legs of one signal share it
    ])


@ea_signals_router.get("/signals", response_class=PlainTextResponse, dependencies=[Depends(require_ea_key)])
async def get_ea_signals(
    hours: int = Query(default=24, ge=1, le=168, description="Look back this many hours (by fill time)."),
    limit: int = Query(default=100, ge=1, le=500, description="Max trades to return."),
) -> str:
    """
    Pipe-delimited mirror-execution feed for MT5 EAs on other accounts.

    Layout — line 1 is a header, then one line per master trade:
        V|<version>|<utc_now>|<count>
        S|id|symbol|direction|entry|sl|tp|lotSize|confidence|channel|
          filledAt|tpLevel|entryLeg|ageMinutes|state|signalId
        E                           (end-of-feed marker)

    Each row is either an OPEN order on the primary account (PENDING, i.e. an
    unfilled limit/stop; or RUNNING, i.e. a filled position) or a recently
    TERMINAL one (CANCELLED/CLOSED, within the lookback window). Every row that
    ever appears cleared approval — a Trade row only exists post
    _execute_approved_trade(). The `state` field tells the mirror EA whether to
    place a limit (PENDING), open on sight / let its own limit fill (RUNNING),
    or cancel its still-pending mirror order (CANCELLED/CLOSED). `hours` bounds
    only the terminal rows; open orders are always included regardless of age.
    """
    try:
        from datetime import timedelta

        from src.core.database_service import db_service

        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        trades = await db_service.db.trade.find_many(
            where={
                "OR": [
                    # Live orders — always visible while the master holds them.
                    {"status": {"in": list(OPEN_STATES)}},
                    # Recently finished — visible briefly so the EA can react once.
                    {"status": {"in": list(TERMINAL_STATES)}, "updatedAt": {"gte": since}},
                ]
            },
            include={"signal": True},
            order={"createdAt": "desc"},
            take=limit,
        )

        now = datetime.now(timezone.utc)
        lines = [
            SEP.join(["V", str(EA_FEED_VERSION), now.strftime("%Y-%m-%dT%H:%M:%SZ"), str(len(trades))]),
        ]
        lines += [_trade_line(t, now) for t in trades]
        lines.append("E")
        return "\n".join(lines)

    except Exception as exc:
        logger.error("EA mirror feed generation failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
