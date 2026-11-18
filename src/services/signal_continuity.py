"""
Signal continuity — one channel setup is one signal, however many messages it takes.

Channels often spread a setup over several messages or correct it later:

  • split      "SELL GOLD NOW"  …then…  "SELL GOLD 4115 SL 4125 TP 4100/4090"
  • repost     the signal is deleted and sent again with changed levels
  • edit       the original message is edited (MessageEdited)
  • same post  the identical setup is posted twice (chart, then text recap)

Each of these is an UPDATE of the existing signal, never a second trade:

  1. the new SL / TPs are applied to the orders already placed (an SL already at
     break-even or better is never loosened),
  2. pending orders at levels the new message no longer lists are cancelled,
  3. the signal's risk budget (one Max Risk Per Trade for the whole setup) is
     re-measured against the new SL, and only what is left is placed as new orders
     through the normal pipeline (news, drawdown, brain, approval …). An instant
     entry that the real SL puts over the budget is partially closed back within
     it; with a scale-in the instant entry stands for the level nearest its fill,
     and what is left goes to the other levels. Once the setup has orders, the
     rest is never chased at market by the instant rule,
  4. the new message is linked to the original (MessageMapping CONTINUATION), so
     replies to either message reach every order of the setup.

Independent of continuity, a NEW signal never adds orders at a level where the same
channel already has same-direction orders running, unless all of them are at
break-even (filter_same_level).

A deleted signal that is not reposted gets its pending orders cancelled; open
positions keep running with their SL/TP.

Group identity is the magic number of the original message: every order of the
setup (first entry, top-ups) carries it.

The two time-limited registries — instant entries awaiting their follow-up and
deleted signals awaiting a repost — are kept in memory for fast lookups and
written through to continuity_marks, so a restart (deploy, crash) inside the
window neither opens a duplicate trade nor loses the "no follow-up" alert
(restore(), called before the Telegram listener starts).
"""
import asyncio
import json
import math
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from loguru import logger

from config import settings
from src.models import TradingSignal, OrderType
from src.utils.pip_utils import get_pip_size
from src.utils.tasks import spawn


# ── pure helpers (unit-tested) ────────────────────────────────────────────────

def planned_levels(signal) -> List[float]:
    """Entry levels a signal asks for; [] for a pure market entry."""
    legs = signal.discrete_entry_prices() if hasattr(signal, 'discrete_entry_prices') else None
    if legs:
        return [float(x) for x in legs]
    lo, hi = getattr(signal, 'entry_range_min', None), getattr(signal, 'entry_range_max', None)
    if lo and hi:
        return sorted({float(lo), float(hi)})
    return [float(signal.entry_price)] if getattr(signal, 'entry_price', None) else []


def is_protected(is_buy: bool, open_price: float, stop_loss: Optional[float]) -> bool:
    """SL at break-even or better (trailed into profit) — this position risks nothing."""
    if not stop_loss or not open_price:
        return False
    return stop_loss >= open_price if is_buy else stop_loss <= open_price


def order_risk(is_buy: bool, open_price: float, stop_loss: Optional[float], volume: float,
               pip_multiplier: float, pip_value: float) -> Optional[float]:
    """Money lost if SL is hit (0 when protected); None when there is no SL (unbounded)."""
    if not stop_loss:
        return None
    adverse = (open_price - stop_loss) if is_buy else (stop_loss - open_price)
    return max(adverse, 0.0) * pip_multiplier * pip_value * volume


def assign_tps(orders: List[dict], new_tps: List[float], is_buy: bool, tolerance: float) -> Dict[str, float]:
    """
    Map the new TP list onto existing orders. Orders at the same entry level are
    one TP ladder: ranked by their current TP (nearest first) they get TP1, TP2, …;
    extra orders keep the last new TP.
    """
    tps = sorted([float(t) for t in new_tps if t], reverse=not is_buy)
    if not tps:
        return {}
    groups: List[List[dict]] = []
    for o in sorted(orders, key=lambda o: o['openPrice']):
        if groups and abs(groups[-1][0]['openPrice'] - o['openPrice']) <= tolerance:
            groups[-1].append(o)
        else:
            groups.append([o])
    out: Dict[str, float] = {}
    for group in groups:
        entry = group[0]['openPrice']
        ranked = sorted(group, key=lambda o: abs((o.get('takeProfit') or entry) - entry) or math.inf)
        for i, o in enumerate(ranked):
            out[o['id']] = tps[min(i, len(tps) - 1)]
    return out


def level_conflicts(level: float, live: List[dict], is_buy: bool, tolerance: float) -> List[dict]:
    """Live orders at this level that block a new order there (pending, or open and not at BE)."""
    return [
        o for o in live
        if abs(o['openPrice'] - level) <= tolerance
        and (o.get('pending') or not is_protected(is_buy, o['openPrice'], o.get('stopLoss')))
    ]


def levels_after_instant_entry(levels: List[float], entry_prices: List[float]) -> List[float]:
    """
    Levels a follow-up still places after the instant entry. With a scale-in
    ("@ 4122, MORE SELL @ 4132") the instant entry IS the level nearest its fill —
    the rest of the budget belongs to the other levels, not a second order there.
    A single level keeps it: the rest of the budget goes in at that level.
    """
    if len(levels) < 2 or not entry_prices:
        return levels
    filled = sum(entry_prices) / len(entry_prices)
    nearest = min(levels, key=lambda lv: abs(lv - filled))
    return [lv for lv in levels if lv != nearest]


def trim_volumes(positions: List[Tuple[float, float]], excess: float, step: float,
                 volume_min: float) -> List[float]:
    """
    Lots to close from each (volume, risk per lot) position so their risk drops by
    at least `excess`: whole volume steps, riskiest position first, none left below
    the broker minimum. 0 = leave it.
    """
    step = step or 0.01
    out = [0.0] * len(positions)
    for i in sorted(range(len(positions)), key=lambda i: -positions[i][1]):
        volume, per_lot = positions[i]
        if excess <= 1e-9 or per_lot <= 0:
            continue
        room = max(math.floor((volume - (volume_min or step)) / step + 1e-9), 0)
        n = min(math.ceil(excess / (per_lot * step) - 1e-9), room)
        out[i] = round(n * step, 8)
        excess -= n * step * per_lot
    return out


def _is_buy_type(order_type: str) -> bool:
    return 'BUY' in str(order_type or '').upper()


def clone_signal(signal: TradingSignal, **changes) -> TradingSignal:
    """dataclasses.replace that also keeps runtime attributes (telegram_message_id, metadata)."""
    out = replace(signal, **changes)
    field_names = set(type(signal).__dataclass_fields__)
    for k, v in vars(signal).items():
        if k not in field_names and k not in changes:
            setattr(out, k, v)
    return out


# ── service ───────────────────────────────────────────────────────────────────

MARK_AWAITING = "AWAITING_LEVELS"
MARK_DELETED = "DELETED"


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class SignalContinuity:
    def __init__(self):
        self._awaiting: Dict[str, float] = {}               # signal id → monotonic deadline (temp SL)
        self._deleted: Dict[Tuple[str, int], Tuple[str, float]] = {}  # (chat, msg) → (signal id, monotonic)

    # ── settings ─────────────────────────────────────────────────────────────
    @staticmethod
    def window_seconds() -> float:
        return max(int(getattr(settings, 'signal_continuity_window_minutes', 30) or 0), 0) * 60.0

    @staticmethod
    def tolerance(symbol: Optional[str]) -> float:
        return float(getattr(settings, 'same_level_tolerance_pips', 20) or 0) * get_pip_size(symbol)

    # ── registry ─────────────────────────────────────────────────────────────
    def mark_awaiting_levels(self, signal_id: str, symbol: str) -> None:
        """A temporary-SL entry was placed; its follow-up message updates it."""
        window = self.window_seconds()
        self._awaiting[signal_id] = time.monotonic() + window
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        self._arm_expiry(signal_id, symbol, window)
        spawn(self._store_mark(MARK_AWAITING, signal_id, window, symbol=symbol), name="continuity-mark")

    def _arm_expiry(self, signal_id: str, symbol: str, delay: float) -> None:
        spawn(self._expire_awaiting(signal_id, symbol, delay), name="continuity-expiry")

    async def _expire_awaiting(self, signal_id: str, symbol: str, window: float) -> None:
        await asyncio.sleep(window)
        if self._awaiting.pop(signal_id, None) is not None:
            await self._forget(MARK_AWAITING, signal_id)
            await self._notify_no_follow_up(symbol)

    @staticmethod
    async def _notify_no_follow_up(symbol: str, while_offline: bool = False) -> None:
        from src.integrations.telegram.unified_sender import notification_sender
        when = " while the bot was offline" if while_offline else ""
        await notification_sender.send_message(
            f"⏳ <b>{symbol}</b>: no follow-up with the real SL/TP arrived{when} — the instant entry "
            f"keeps its temporary SL. Check it.",
            category='position_management',
        )

    # ── persistence (continuity_marks) ───────────────────────────────────────
    async def _store_mark(self, kind: str, signal_id: str, seconds: float, symbol: Optional[str] = None,
                          chat_id: Optional[str] = None, message_id: Optional[int] = None) -> None:
        from src.core.database_service import db_service
        now = datetime.now(timezone.utc)
        try:
            table = db_service.db.continuitymark
            await table.delete_many(where={"expiresAt": {"lt": now}})
            await table.create(data={
                "kind": kind, "signalId": signal_id, "symbol": symbol,
                "chatId": chat_id, "messageId": message_id,
                "expiresAt": now + timedelta(seconds=seconds),
            })
        except Exception as e:
            logger.warning(f"Continuity: could not persist {kind} mark for signal {signal_id[:8]} — "
                           f"kept in memory only, a restart would forget it: {e}")

    async def _forget(self, kind: str, signal_id: str) -> None:
        from src.core.database_service import db_service
        try:
            await db_service.db.continuitymark.delete_many(where={"kind": kind, "signalId": signal_id})
        except Exception as e:
            logger.warning(f"Continuity: could not clear {kind} mark for signal {signal_id[:8]}: {e}")

    async def restore(self) -> int:
        """Reload the marks that must survive a restart. Run before the Telegram listener
        starts so catch-up replays already see them. Returns how many were restored."""
        from src.core.database_service import db_service
        try:
            rows = await db_service.db.continuitymark.find_many()
        except Exception as e:
            logger.error(f"Continuity: could not restore marks — follow-ups/reposts of signals from "
                         f"before the restart will not be linked: {e}")
            return 0
        now_utc, now_mono = datetime.now(timezone.utc), time.monotonic()
        restored, expired = 0, []
        for r in rows:
            remaining = (_aware(r.expiresAt) - now_utc).total_seconds()
            if r.kind == MARK_AWAITING:
                if remaining > 0:
                    self._awaiting[r.signalId] = now_mono + remaining
                    self._arm_expiry(r.signalId, r.symbol or "", remaining)
                    restored += 1
                else:
                    expired.append(r.id)
                    await self._notify_no_follow_up(r.symbol or "", while_offline=True)
            elif r.kind == MARK_DELETED and r.chatId is not None and r.messageId is not None:
                if remaining > 0:
                    age = max((now_utc - _aware(r.createdAt)).total_seconds(), 0.0)
                    self._deleted[(r.chatId, int(r.messageId))] = (r.signalId, now_mono - age)
                    restored += 1
                else:
                    expired.append(r.id)
            else:
                expired.append(r.id)
        if expired:
            try:
                await db_service.db.continuitymark.delete_many(where={"id": {"in": expired}})
            except Exception as e:
                logger.warning(f"Continuity: could not prune expired marks: {e}")
        if restored:
            logger.info(f"🔗 Continuity: restored {restored} mark(s) from before the restart")
        return restored

    def _is_awaiting(self, signal_id: str) -> bool:
        deadline = self._awaiting.get(signal_id)
        return deadline is not None and deadline > time.monotonic()

    def _was_deleted(self, signal_id: str) -> bool:
        now, window = time.monotonic(), self.window_seconds()
        return any(sid == signal_id and now - t <= window for sid, t in self._deleted.values())

    # ── lookups ──────────────────────────────────────────────────────────────
    async def resolve_group(self, chat_id: str, message_id: int):
        """(parent Signal record, magic) a message belongs to — follows CONTINUATION links."""
        from src.core.database_service import db_service
        from src.services.magic_number_service import magic_number_service
        mapping = await db_service.get_message_mapping_by_message_id(str(chat_id), int(message_id))
        if mapping and mapping.get('mappingType') == 'CONTINUATION' and mapping.get('signalId'):
            parent = await db_service.db.signal.find_unique(where={"id": mapping['signalId']})
            if parent:
                magic = mapping.get('magicNumber') or magic_number_service.generate_magic_number(parent.messageId)
                return parent, magic
        parent = await db_service.db.signal.find_first(
            where={"channelId": str(chat_id), "messageId": int(message_id)})
        if not parent:
            return None, None
        return parent, magic_number_service.generate_magic_number(parent.messageId)

    @staticmethod
    def _provider():
        if settings.dry_run or settings.skip_metaapi:
            return None
        from src.services.trading_service import trading_service
        provider = trading_service.trading_provider
        return provider if getattr(provider, 'is_connected', False) else None

    async def _live_orders(self, magics: set, is_buy: bool) -> List[dict]:
        """Open positions + pending orders carrying one of these magic numbers, same direction."""
        provider = self._provider()
        if not provider or not magics:
            return []
        out = []
        for p in await provider.get_open_positions(use_cache=False) or []:
            if p.get('magic') in magics and _is_buy_type(p.get('type')) == is_buy:
                out.append({**p, 'pending': False})
        for o in await provider.get_all_pending_orders(use_cache=False) or []:
            if o.get('magic') in magics and _is_buy_type(o.get('type')) == is_buy:
                out.append({**o, 'pending': True})
        return out

    # ── matching ─────────────────────────────────────────────────────────────
    async def find_parent(self, signal: TradingSignal):
        """The active signal this new message continues, with the reason, or (None, None)."""
        if (getattr(signal, 'continuation_of', None) or not signal.channel_id or not signal.symbol
                or signal.order_type is None or signal.is_plan):
            return None, None
        from src.core.database_service import db_service
        from src.services.magic_number_service import magic_number_service
        since = datetime.now(timezone.utc) - timedelta(seconds=self.window_seconds())
        candidates = await db_service.db.signal.find_many(
            where={
                "channelId": str(signal.channel_id),
                "symbol": signal.symbol,
                "orderType": signal.order_type.value,
                "status": {"in": db_service.ACTIVE_SIGNAL_STATUSES},
                "createdAt": {"gte": since},
            },
            order={"createdAt": "desc"},
        )
        if not candidates:
            return None, None

        matching_candidates = [c for c in candidates if c.messageId != signal.message_id]
        if not matching_candidates:
            return None, None

        # Build metadata for candidates (including live MT5 open position state)
        is_buy = signal.order_type == OrderType.BUY
        cand_list = []
        for c in matching_candidates:
            magic = magic_number_service.generate_magic_number(c.messageId)
            live = await self._live_orders({magic}, is_buy)
            open_pos = [o for o in live if not o.get('pending')]
            open_price = open_pos[0]['openPrice'] if open_pos else None

            created_val = getattr(c, 'createdAt', None)
            if isinstance(created_val, datetime):
                created_dt = created_val
            elif isinstance(created_val, (int, float)):
                created_dt = datetime.fromtimestamp(created_val / 1000 if created_val > 1e11 else created_val, tz=timezone.utc)
            else:
                created_dt = datetime.now(timezone.utc)
            minutes_ago = (datetime.now(timezone.utc) - _aware(created_dt)).total_seconds() / 60.0

            cand_list.append({
                "id": c.id,
                "message_id": c.messageId,
                "symbol": c.symbol,
                "order_type": c.orderType,
                "entry": c.entryPrice or [c.entryRangeMin, c.entryRangeMax],
                "stop_loss": c.stopLoss,
                "take_profit": c.takeProfit,
                "raw_message": c.rawMessage or "",
                "minutes_ago": minutes_ago,
                "was_deleted": self._was_deleted(c.id),
                "is_awaiting_levels": self._is_awaiting(c.id),
                "has_open_position": bool(open_pos),
                "open_position_price": open_price,
                "_db_record": c,
            })

        # A signal the channel deleted and now posts again at the same entry is its
        # repost — decided here, not by the AI: asked the same question twice it called
        # one such repost a correction and the next a new trade, which then left the
        # positions on the deleted message's levels (scripted history, 2026-11-13).
        tol = self.tolerance(signal.symbol)
        new_levels = planned_levels(signal)
        for c_meta in cand_list:
            if not c_meta["was_deleted"]:
                continue
            c = c_meta["_db_record"]
            old_levels = [x for x in (c.entryRangeMin, c.entryRangeMax) if x] or ([c.entryPrice] if c.entryPrice else [])
            if c_meta["open_position_price"]:
                old_levels = old_levels + [c_meta["open_position_price"]]
            if not new_levels or not old_levels:
                return c, "repost of a deleted signal"
            lo, hi = min(old_levels) - tol, max(old_levels) + tol
            if any(lo <= lv <= hi for lv in new_levels):
                return c, "repost of a deleted signal"

        # Try AI classification with full historical context
        try:
            from src.services.signal_service import signal_service
            raw_text = signal.raw_message or ""
            ai_res = await signal_service.classify_signal_relationship(raw_text, cand_list)
            rel = ai_res.get("relationship", "UNKNOWN") if isinstance(ai_res, dict) else "UNKNOWN"
            matched_id = ai_res.get("parent_id") if isinstance(ai_res, dict) else None
            reason = ai_res.get("reason", "") if isinstance(ai_res, dict) else ""

            if rel == "NEW":
                logger.info(f"🆕 AI continuity: classified as NEW independent signal ({reason})")
                return None, None

            matched_c = next((c["_db_record"] for c in cand_list if c["id"] == matched_id), None)
            if not matched_c and cand_list:
                matched_c = cand_list[0]["_db_record"]

            if matched_c:
                if rel == "FOLLOW_UP":
                    return matched_c, "follow-up to an instant entry on a temporary SL"
                elif rel == "CORRECTION":
                    return matched_c, f"correction of signal ({reason})"
                elif rel == "DUPLICATE":
                    return matched_c, "same setup posted again"
        except Exception as e:
            logger.warning(f"⚠️ AI continuity classification failed ({e}) — falling back to deterministic rules")

        # Deterministic fallback rules:
        # If candidate already has an open filled position, a new signal with entries / NOW is a NEW trade!
        for c_meta in cand_list:
            c = c_meta["_db_record"]
            if c_meta["is_awaiting_levels"]:
                return c, "follow-up to an instant entry on a temporary SL"
            if c_meta["has_open_position"]:
                # A trade is already filled and running — do not merge into it
                continue
            if c_meta["was_deleted"]:
                return c, "repost of a deleted signal"
            old_levels = [x for x in (c.entryRangeMin, c.entryRangeMax) if x] or ([c.entryPrice] if c.entryPrice else [])
            if not new_levels or not old_levels:
                return c, "same setup posted again (market entry)"
            lo, hi = min(old_levels) - tol, max(old_levels) + tol
            if any(lo <= lv <= hi for lv in new_levels):
                return c, "same setup posted again"
        return None, None

    # ── update ───────────────────────────────────────────────────────────────
    async def apply_update(self, parent, new_signal: TradingSignal, message_id=None,
                           source: str = "follow-up") -> None:
        """Apply a follow-up / repost / edit to an existing signal (see module docstring)."""
        from src.core.database_service import db_service
        from src.integrations.telegram.unified_sender import notification_sender
        from src.services.magic_number_service import magic_number_service
        from src.services.risk_service import risk_manager
        from src.services.trading_service import trading_service

        group_parent, magic = await self.resolve_group(parent.channelId, parent.messageId)
        parent = group_parent or parent
        magic = magic or magic_number_service.generate_magic_number(parent.messageId)
        symbol = parent.symbol
        is_buy = parent.orderType == 'BUY'
        tol = self.tolerance(symbol)
        # An instant entry on a temporary SL was sized for that SL: its follow-up may
        # add the rest of the risk at the same level. Any other update only fills
        # levels the setup has no order at yet.
        instant_follow_up = self._awaiting.pop(parent.id, None) is not None
        if instant_follow_up:
            await self._forget(MARK_AWAITING, parent.id)
        logger.info(f"🔗 {source}: updating signal {parent.id[:8]} ({symbol} {parent.orderType}, magic {magic})")

        # Still waiting for approval → the queued version is stale; the new message
        # replaces it and is processed as the signal.
        if parent.status == "AWAITING_APPROVAL":
            from src.services.approval_queue import approval_queue
            approval_queue.reject_signal(parent.id, f"Replaced by {source}")
            await db_service.update_signal_status(parent.id, "REJECTED")
            await trading_service.process_signal(new_signal)
            return

        if message_id is not None and int(message_id.message_id) != int(parent.messageId):
            await db_service.create_message_mapping(
                message_id=message_id, signal_id=parent.id, magic_number=magic, mapping_type="CONTINUATION")

        provider = self._provider()
        live = await self._live_orders({magic}, is_buy)
        new_sl = new_signal.stop_loss
        new_tps = [t for t in (new_signal.take_profit or []) if t]
        levels = planned_levels(new_signal)
        changes: List[str] = []
        # The SL that goes on the orders carries the same spread allowance as when
        # they were placed. Without it every update — even an edit that only adds an
        # emoji — pulled the SL in by the spread (simulated 2026-11-12: 3962.3 → 3962.0).
        order_sl = new_sl
        if new_sl and provider:
            try:
                order_sl = await risk_manager._adjust_stop_loss_for_spread(
                    new_signal, new_signal.entry_price or 0.0, new_sl)
            except Exception as e:
                logger.warning(f"Continuity: SL spread allowance not applied: {e}")
        same = lambda a, b: abs((a or 0.0) - (b or 0.0)) < get_pip_size(symbol) * 0.05  # noqa: E731

        runners: set = set()
        if provider:
            # 1. pending orders at levels the new message no longer lists
            if levels:
                for o in [o for o in live if o['pending']]:
                    if not any(abs(o['openPrice'] - lv) <= tol for lv in levels):
                        try:
                            await provider.cancel_order(o['id'])
                            live.remove(o)
                            changes.append(f"cancelled pending {o['openPrice']} (level removed)")
                        except Exception as e:
                            logger.error(f"Continuity: cancel {o['id']} failed: {e}")
            # 2. SL / TP on what remains — a runner follows the SL and stays without TP
            runners = await self._runner_tickets(magic)
            tp_for = assign_tps([o for o in live if str(o['id']) not in runners], new_tps, is_buy, tol)
            for o in live:
                sl = o.get('stopLoss')
                if new_sl and not (not o['pending'] and is_protected(is_buy, o['openPrice'], sl)):
                    sl = order_sl
                tp = tp_for.get(o['id'], o.get('takeProfit'))
                if same(sl, o.get('stopLoss')) and same(tp, o.get('takeProfit')):
                    continue
                try:
                    if o['pending']:
                        await provider.modify_order(o['id'], stop_loss=sl, take_profit=tp, price=o['openPrice'])
                    else:
                        await provider.modify_position(o['id'], stop_loss=sl, take_profit=tp)
                    o['stopLoss'], o['takeProfit'] = sl, tp
                    changes.append(f"{'order' if o['pending'] else 'position'} {o['openPrice']}: SL {sl} TP {tp}")
                except Exception as e:
                    logger.error(f"Continuity: modify {o['id']} failed: {e}")

        # 3. the parent record shows the current levels
        update = {}
        if new_sl:
            update["stopLoss"] = new_sl
        if new_tps:
            update["takeProfit"] = json.dumps(new_tps)
        if new_signal.entry_price:
            update["entryPrice"] = new_signal.entry_price
        if new_signal.entry_range_min and new_signal.entry_range_max:
            update["entryRangeMin"], update["entryRangeMax"] = new_signal.entry_range_min, new_signal.entry_range_max
        raw = (new_signal.raw_message or "").strip()
        if raw and raw not in (parent.rawMessage or ""):
            update["rawMessage"] = f"{parent.rawMessage or ''}\n--- {source} ---\n{raw}".strip()
        if update:
            await db_service.db.signal.update(where={"id": parent.id}, data=update)

        # 4. one risk budget: re-measure what is placed, top up with what is left
        account = await trading_service._get_account_info()
        budget = account.balance * settings.max_risk_per_trade_percent / 100.0
        used = 0.0
        if live:
            pip_mult = await risk_manager._get_pip_multiplier(symbol)
            pip_value = await risk_manager._get_pip_value(symbol)
            if instant_follow_up and provider:
                changes += await self._trim_to_budget(provider, live, is_buy, budget, pip_mult, pip_value, symbol)
            for o in live:
                r = order_risk(is_buy, o['openPrice'], o.get('stopLoss'), o.get('volume') or 0, pip_mult, pip_value)
                used += budget if r is None else r
        remaining = budget - used
        logger.info(f"💰 Risk budget {budget:.2f}: placed orders risk {used:.2f}, remaining {remaining:.2f}")
        # Part of the setup already closed (TP hit, or the temporary SL hit): it has
        # played out — never re-enter it from a follow-up.
        closed = await self._closed_positions(parent, magic)
        # Levels that already have an order of this setup are not entered again —
        # re-sending the same setup must never double it.
        if instant_follow_up:
            new_levels = levels_after_instant_entry(levels, [o['openPrice'] for o in live if not o.get('pending')])
        else:
            new_levels = [lv for lv in levels if not any(abs(o['openPrice'] - lv) <= tol for o in live)]
        all_covered = not instant_follow_up and bool(live) and not new_levels

        summary = "\n".join(f"• {c}" for c in changes) or "• no changes to running orders"
        if closed:
            await notification_sender.send_message(
                f"🔗 <b>{symbol} {parent.orderType}</b> — {source} linked to the running signal\n{summary}\n"
                f"• no new orders: part of this setup already closed",
                category='position_management',
            )
        elif all_covered:
            await notification_sender.send_message(
                f"🔗 <b>{symbol} {parent.orderType}</b> — {source} linked to the running signal\n{summary}\n"
                f"• no new orders: every entry level already has orders of this setup",
                category='position_management',
            )
        elif remaining > budget * 0.10 and new_signal.stop_loss:
            level_changes = {}
            if new_levels != levels:
                level_changes = {"entries": new_levels if len(new_levels) > 1 else None,
                                 "entry_price": new_levels[0], "entry_range_min": None, "entry_range_max": None}
            # The setup already has orders, so its "NOW" has been acted on: the rest
            # waits at the channel's levels.
            has_filled = any(not o.get('pending') for o in live)
            placed_runner = sum(o.get('volume') or 0 for o in live if str(o['id']) in runners)
            placed_tp = sum(o.get('volume') or 0 for o in live) - placed_runner
            top_up = clone_signal(
                new_signal, continuation_of=parent.id, magic_override=magic,
                runner_setup=(round(placed_tp, 2), round(placed_runner, 2)),
                risk_budget_amount=remaining, temp_stop_loss=False,
                channel_id=parent.channelId, channel_name=parent.channelName,
                instant_execution=new_signal.instant_execution and not has_filled,
                **level_changes,
            )
            if message_id is not None and int(message_id.message_id) == int(parent.messageId):
                # An edit of the original message: its top-up gets its own message id,
                # so its mapping (and an approval record) never collides with the parent's.
                from src.models.message import MessageIdentifier
                top_up.telegram_message_id = MessageIdentifier(
                    chat_id=str(parent.channelId), message_id=-int(parent.messageId),
                    message_hash=f"edit-topup-{parent.id}", timestamp=datetime.now(timezone.utc))
                top_up.message_id = -int(parent.messageId)
            elif message_id is not None:
                top_up.telegram_message_id = message_id
            await notification_sender.send_message(
                f"🔗 <b>{symbol} {parent.orderType}</b> — {source} linked to the running signal\n{summary}\n"
                f"• placing the rest within the remaining risk ({remaining:.2f} of {budget:.2f})",
                category='position_management',
            )
            await trading_service.process_signal(top_up)
        else:
            await notification_sender.send_message(
                f"🔗 <b>{symbol} {parent.orderType}</b> — {source} linked to the running signal\n{summary}\n"
                f"• no new orders: the risk budget is already used ({used:.2f} of {budget:.2f})",
                category='position_management',
            )

    # ── a new signal carries the channel's current levels ────────────────────
    async def carry_levels_to_older_signals(self, signal: TradingSignal) -> List[str]:
        """
        A NEW signal of the same channel, instrument and direction states where the
        channel's stop and targets are NOW. The channel's older setups that are still
        running take them over (owner's rule, 2026-11-17).

        live channel, 2026-11-16: "SELL @ 3864 / 3876, SL 3887" was followed by
        "SELL @ 3872 / 3885, SL 3896" — "total we have 3 entries". The first setup
        kept SL 3887, was stopped at a 3888.87 high and missed the fall to 3841.

        - SL: every open position and pending order gets the new SL (with the usual
          spread allowance). A position whose SL is at break-even or better keeps it.
        - TPs: each leg gets the new target of its own number (TP1 → new TP1, …; the
          last new TP for higher numbers). A runner stays without a TP. A new target
          the price has already passed is not set — that leg keeps its TP.

        Returns the changes made, as text.
        """
        new_sl = signal.stop_loss
        new_tps = [float(t) for t in (signal.take_profit or []) if t]
        if (not signal.channel_id or not signal.symbol or signal.order_type is None
                or getattr(signal, 'is_plan', False) or not (new_sl or new_tps)):
            return []
        if getattr(signal, 'temp_stop_loss', False):
            return []          # an instant entry on a temporary SL: its levels are placeholders
        provider = self._provider()
        if not provider:
            return []
        from src.core.database_service import db_service
        from src.integrations.telegram.unified_sender import notification_sender
        from src.services.magic_number_service import magic_number_service

        is_buy = signal.order_type == OrderType.BUY
        symbol = signal.symbol
        own_magic = getattr(signal, 'magic_override', None) or (
            magic_number_service.generate_magic_number(signal.message_id) if signal.message_id else None)
        older = await db_service.db.signal.find_many(where={
            "channelId": str(signal.channel_id), "symbol": symbol, "orderType": signal.order_type.value,
            "action": "OPEN", "status": {"in": db_service.ACTIVE_SIGNAL_STATUSES},
        })
        by_magic: Dict[int, object] = {}
        own_ids = {signal.message_id, getattr(getattr(signal, 'telegram_message_id', None), 'message_id', None)}
        for record in older:
            if record.messageId in own_ids:
                continue
            _, magic = await self.resolve_group(record.channelId, record.messageId)
            magic = magic or magic_number_service.generate_magic_number(record.messageId)
            if magic != own_magic:
                by_magic.setdefault(magic, record)
        if not by_magic:
            return []

        # The SL as it stands on the new signal's own orders (spread allowance included),
        # so both setups share one stop. The signal's value alone may or may not carry
        # the allowance already; adjusting it again put the older setup 0.3 further out.
        order_sl = new_sl
        if new_sl and own_magic:
            placed = [o.get('stopLoss') for o in await self._live_orders({own_magic}, is_buy) if o.get('stopLoss')]
            if placed:
                order_sl = placed[0]
        tps = sorted(new_tps, reverse=not is_buy)                     # nearest target first
        price = None
        if tps:
            try:
                quote = await provider.get_symbol_price(symbol) or {}
                price = quote.get('ask' if is_buy else 'bid')         # where a position would close now
            except Exception as e:
                logger.warning(f"Continuity: no price for the TP check on {symbol}: {e}")
        same = lambda a, b: abs((a or 0.0) - (b or 0.0)) < get_pip_size(symbol) * 0.05  # noqa: E731

        changes: List[str] = []
        for magic, record in by_magic.items():
            live = await self._live_orders({magic}, is_buy)
            if not live:
                continue
            runners = await self._runner_tickets(magic)
            numbers = await self._tp_numbers(magic, live, is_buy)
            touched = False
            for o in live:
                sl = o.get('stopLoss')
                if new_sl and not (not o['pending'] and is_protected(is_buy, o['openPrice'], sl)):
                    sl = order_sl
                tp = o.get('takeProfit')
                number = numbers.get(str(o['id']))
                if tps and number and str(o['id']) not in runners:
                    wanted = tps[min(number, len(tps)) - 1]
                    passed = price is not None and (price >= wanted if is_buy else price <= wanted)
                    if not passed:
                        tp = wanted
                if same(sl, o.get('stopLoss')) and same(tp, o.get('takeProfit')):
                    continue
                try:
                    if o['pending']:
                        await provider.modify_order(o['id'], stop_loss=sl, take_profit=tp, price=o['openPrice'])
                    else:
                        await provider.modify_position(o['id'], stop_loss=sl, take_profit=tp)
                    changes.append(f"#{record.messageId} {'order' if o['pending'] else 'position'} "
                                   f"{o['openPrice']}: SL {o.get('stopLoss')} → {sl}, TP {o.get('takeProfit')} → {tp}")
                    touched = True
                except Exception as e:
                    logger.error(f"Continuity: carrying the new levels to {o['id']} failed: {e}")
            if touched:
                update = {}
                if new_sl:
                    update["stopLoss"] = new_sl
                if new_tps:
                    update["takeProfit"] = json.dumps(new_tps)
                try:
                    await db_service.db.signal.update(where={"id": record.id}, data=update)
                except Exception as e:
                    logger.warning(f"Continuity: signal {record.id[:8]} not updated with the new levels: {e}")
        if changes:
            logger.info(f"🔗 {symbol}: new signal #{signal.message_id} carried its SL/TPs to "
                        f"{len(changes)} order(s) of the channel's older running setup(s)")
            try:
                await notification_sender.send_message(
                    f"🔗 <b>{symbol} {signal.order_type.value}</b> — the channel's new signal sets the levels of "
                    f"its older running setup too\n" + "\n".join(f"• {c}" for c in changes),
                    category='position_management')
            except Exception as e:
                logger.warning(f"Could not send the levels-carried notification: {e}")
        return changes

    @staticmethod
    async def _tp_numbers(magic: int, live: List[dict], is_buy: bool) -> Dict[str, int]:
        """
        Which target (1, 2, …) each live order of a setup holds: as recorded when it
        was placed (Trade.tpLevel), else by ranking the setup's TP prices, nearest first.
        """
        from src.core.database_service import db_service
        numbers: Dict[str, int] = {}
        try:
            for tr in await db_service.db.trade.find_many(where={"magicNumber": magic}):
                level = getattr(tr, 'tpLevel', None)
                if level:
                    for ticket in (getattr(tr, 'positionId', None), getattr(tr, 'orderId', None)):
                        if ticket:
                            numbers[str(ticket)] = int(level)
        except Exception as e:
            logger.warning(f"Continuity: target numbers not read, ranking by price: {e}")
        levels = sorted({float(o['takeProfit']) for o in live if o.get('takeProfit')}, reverse=not is_buy)
        for o in live:
            if str(o['id']) not in numbers and o.get('takeProfit'):
                numbers[str(o['id'])] = levels.index(float(o['takeProfit'])) + 1
        return numbers

    @staticmethod
    async def _trim_to_budget(provider, live: List[dict], is_buy: bool, budget: float,
                              pip_mult: float, pip_value: float, symbol: str) -> List[str]:
        """
        The real SL is wider than the temporary one the instant entry was sized on:
        partially close the open positions so the setup stays within Max Risk Per
        Trade. Updates the volumes in `live`; returns what was done.
        """
        risk = {o['id']: order_risk(is_buy, o['openPrice'], o.get('stopLoss'), o.get('volume') or 0,
                                    pip_mult, pip_value) for o in live}
        if None in risk.values() or sum(risk.values()) <= budget:
            return []
        positions = [o for o in live if not o['pending'] and risk[o['id']] > 0 and o.get('volume')]
        try:
            spec = await provider.get_symbol_specification(symbol)
            step, vmin = spec.get('volumeStep', 0.01) or 0.01, spec.get('volumeMin', 0.01) or 0.01
        except Exception:
            step, vmin = 0.01, 0.01
        closes = trim_volumes([(o['volume'], risk[o['id']] / o['volume']) for o in positions],
                              sum(risk.values()) - budget, step, vmin)
        done = []
        for o, close in zip(positions, closes):
            if close <= 0:
                continue
            try:
                await provider.close_position(o['id'], volume=close)
                o['volume'] = round(o['volume'] - close, 8)
                done.append(f"position {o['openPrice']}: closed {close} lots — the real SL is wider "
                            f"than the temporary one, kept within the risk budget")
            except Exception as e:
                logger.error(f"Continuity: trimming {o['id']} by {close} lots failed: {e}")
        if done:
            logger.warning(f"✂️ {symbol}: instant entry over the risk budget at the real SL — " + "; ".join(done))
        return done

    @staticmethod
    async def _runner_tickets(magic: int) -> set:
        """Broker tickets of this setup's runner orders (placed without a TP on purpose)."""
        from src.core.database_service import db_service
        try:
            trades = await db_service.db.trade.find_many(where={"magicNumber": magic})
        except Exception as e:
            logger.warning(f"Continuity: could not look up runner orders — TPs go on every order: {e}")
            return set()
        return {str(t) for tr in trades
                if getattr(tr, 'originalTakeProfit', 0) is None and getattr(tr, 'autoTpEnabled', True) is False
                for t in (getattr(tr, 'positionId', None), getattr(tr, 'orderId', None)) if t}

    @staticmethod
    async def _closed_positions(parent, magic: int) -> int:
        """Positions of this setup that really opened and closed. The magic number is only
        the message id, so another channel's message with the same id shares it — count
        only trades of this channel's signals. Trades that never got a position
        (cancelled / failed / swept by sync) are not a played-out setup."""
        from src.core.database_service import db_service
        trades = await db_service.db.trade.find_many(where={"magicNumber": magic, "status": "CLOSED"})
        trades = [t for t in trades if getattr(t, 'positionId', None)]
        if not trades:
            return 0
        ours = await db_service.db.signal.find_many(where={
            "id": {"in": list({t.signalId for t in trades})}, "channelId": str(parent.channelId)})
        ours_ids = {s.id for s in ours}
        return sum(1 for t in trades if t.signalId in ours_ids)

    # ── same-level rule for new signals ──────────────────────────────────────
    async def filter_same_level(self, signal: TradingSignal) -> Tuple[Optional[TradingSignal], Optional[str]]:
        """
        Drop entry levels where the same channel already has same-direction orders that
        are not at break-even. Returns (signal to place, None) or (None, reason).

        Across signals, a running order of an older signal whose SL is clearly
        different from this one's is another setup, not this one re-sent: it does
        not block the level, its risk comes off this signal's budget instead.
        2026-11-03: a 0.01 reply-command add at 3914 (SL 3922) blocked the
        channel's new "SELL NOW @ 3914, SL 3928" as a duplicate.
        """
        if not signal.channel_id or not signal.symbol or signal.order_type is None:
            return signal, None
        from src.core.database_service import db_service
        from src.services.magic_number_service import magic_number_service
        is_buy = signal.order_type == OrderType.BUY
        across = getattr(settings, 'enable_same_level_filter_across_signals', False)
        if not across:
            # Same-level rule only blocks duplicate orders within the SAME signal group
            magics = set()
            override = getattr(signal, 'magic_override', None)
            if override or getattr(signal, 'continuation_of', None):
                if override:
                    magics.add(override)
            if not magics:
                return signal, None
        else:
            siblings = await db_service.db.signal.find_many(where={
                "channelId": str(signal.channel_id), "symbol": signal.symbol,
                "orderType": signal.order_type.value, "status": {"in": db_service.ACTIVE_SIGNAL_STATUSES},
            })
            magics = {magic_number_service.generate_magic_number(s.messageId) for s in siblings}
            magics.discard(getattr(signal, 'magic_override', None))
        live = await self._live_orders(magics, is_buy)
        if not live:
            return signal, None

        tol = self.tolerance(signal.symbol)
        charged: Dict[str, dict] = {}

        def blocking(conflicts: List[dict]) -> List[dict]:
            """The conflicts that block; other setups' orders are charged to the budget."""
            hard = [o for o in conflicts if not (across and signal.stop_loss and o.get('stopLoss')
                                                 and abs(o['stopLoss'] - signal.stop_loss) > tol)]
            if not hard:
                charged.update({o['id']: o for o in conflicts})
            return hard

        legs = signal.discrete_entry_prices() if hasattr(signal, 'discrete_entry_prices') else None
        if legs:
            kept = [lv for lv in legs if not blocking(level_conflicts(lv, live, is_buy, tol))]
            if not kept:
                return None, f"every entry level {legs} already has running orders from this channel (not at break-even)"
            if len(kept) < len(legs):
                logger.info(f"🧱 Same-level rule: dropped legs {sorted(set(legs) - set(kept))}")
                if len(kept) == 1:
                    signal = clone_signal(signal, entries=None, entry_price=kept[0])
                else:
                    signal = clone_signal(signal, entries=kept, entry_price=kept[0])
            return await self._charge_running_risk(signal, list(charged.values()), is_buy)
        if signal.entry_range_min and signal.entry_range_max:
            lo, hi = sorted((signal.entry_range_min, signal.entry_range_max))
            in_zone = [o for o in live if lo - tol <= o['openPrice'] <= hi + tol
                       and (o['pending'] or not is_protected(is_buy, o['openPrice'], o.get('stopLoss')))]
            if blocking(in_zone):
                return None, f"zone {lo}–{hi} already has running orders from this channel (not at break-even)"
            return await self._charge_running_risk(signal, list(charged.values()), is_buy)
        level = signal.entry_price
        if not level:
            provider = self._provider()
            px = await provider.get_symbol_price(signal.symbol) if provider else None
            level = (px or {}).get('ask' if is_buy else 'bid')
        if level and blocking(level_conflicts(level, live, is_buy, tol)):
            return None, f"level {level} already has running orders from this channel (not at break-even)"
        return await self._charge_running_risk(signal, list(charged.values()), is_buy)

    async def _charge_running_risk(self, signal: TradingSignal, orders: List[dict],
                                   is_buy: bool) -> Tuple[Optional[TradingSignal], Optional[str]]:
        """Take the risk of other setups' orders at this signal's levels off its budget."""
        if not orders:
            return signal, None
        from src.services.risk_service import risk_manager
        from src.services.trading_service import trading_service
        budget = signal.risk_budget_amount
        if budget is None:
            account = await trading_service._get_account_info()
            budget = account.balance * settings.max_risk_per_trade_percent / 100.0
        pip_mult = await risk_manager._get_pip_multiplier(signal.symbol)
        pip_value = await risk_manager._get_pip_value(signal.symbol)
        used = sum(order_risk(is_buy, o['openPrice'], o.get('stopLoss'), o.get('volume') or 0, pip_mult, pip_value) or 0.0
                   for o in orders)
        remaining = budget - used
        levels = sorted({o['openPrice'] for o in orders})
        if remaining <= budget * 0.10:
            return None, (f"orders of another signal at {levels} (different SL) already risk "
                          f"{used:.2f} of this signal's {budget:.2f} budget")
        logger.info(f"🧱 Same-level rule: orders of another signal at {levels} have a different SL — "
                    f"a new setup; their risk {used:.2f} comes off the budget ({remaining:.2f} of {budget:.2f} left)")
        return clone_signal(signal, risk_budget_amount=remaining), None

    # ── deletes ──────────────────────────────────────────────────────────────
    async def on_messages_deleted(self, chat_id: Optional[str], message_ids: List[int]) -> None:
        """Signal deleted: cancel its pending orders, keep open positions, remember it for a repost."""
        if not chat_id:
            return
        from src.integrations.telegram.unified_sender import notification_sender
        from src.core.database_service import db_service
        for mid in message_ids:
            parent, magic = await self.resolve_group(str(chat_id), int(mid))
            if not parent or parent.status not in db_service.ACTIVE_SIGNAL_STATUSES:
                continue
            self._deleted[(str(chat_id), int(mid))] = (parent.id, time.monotonic())
            await self._store_mark(MARK_DELETED, parent.id, self.window_seconds(), symbol=parent.symbol,
                                   chat_id=str(chat_id), message_id=int(mid))
            logger.info(f"🗑️ Signal message {mid} deleted — {parent.symbol} {parent.orderType} (magic {magic})")
            is_buy = parent.orderType == 'BUY'
            live = await self._live_orders({magic}, is_buy)
            provider = self._provider()
            cancelled = 0
            for o in [o for o in live if o['pending']]:
                try:
                    await provider.cancel_order(o['id'])
                    cancelled += 1
                except Exception as e:
                    logger.error(f"Delete: cancel {o['id']} failed: {e}")
            open_count = sum(1 for o in live if not o['pending'])
            await notification_sender.send_message(
                f"🗑️ <b>{parent.symbol} {parent.orderType}</b> signal was deleted by the channel\n"
                f"• cancelled {cancelled} pending order(s)\n"
                f"• kept {open_count} open position(s) with their SL/TP\n"
                f"• a repost within {int(self.window_seconds() // 60)} min updates this signal",
                category='order_cancelled',
            )


signal_continuity = SignalContinuity()
