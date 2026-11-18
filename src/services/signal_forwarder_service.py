"""
Signal Forwarder Service
Forwards executed signals to a configurable Telegram channel and replies
to that post for every subsequent position action (partial, breakeven,
trailing SL, brain actions, close).
"""
from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone
from typing import Dict, List, Optional
from loguru import logger


def _fmt(value, decimals: int = 5) -> str:
    """Format a numeric value dropping trailing zeros."""
    if value is None:
        return "—"
    try:
        f = float(value)
        formatted = f"{f:.{decimals}f}".rstrip("0").rstrip(".")
        if "." not in formatted:
            formatted += ".0"
        return formatted
    except (TypeError, ValueError):
        return str(value)


def _pick(*options: str, mood: str = "neutral") -> str:
    """Pick a phrase matching the desired mood.

    Each option can be prefixed with a mood tag like 'win:', 'loss:',
    'neutral:', 'excited:'.  Options without a prefix are treated as
    matching any mood.  Falls back to any option if no mood match.
    """
    if not options:
        return ""
    mood_prefix = mood + ":"
    tagged = [o for o in options if isinstance(o, str) and o.startswith(mood_prefix)]
    pool = [o[len(mood_prefix):] for o in tagged] if tagged else list(options)
    # Strip any mood prefix from raw options so they render clean
    clean = [o.split(":", 1)[1] if ":" in str(o) and str(o).split(":", 1)[0] in
             ("win", "loss", "neutral", "excited") else str(o) for o in pool]
    return random.choice(clean)


class SignalForwarderService:
    """
    Posts executed signals to a forward channel and sends replies for
    every action taken on that position.
    """

    # Minimum seconds between trailing-SL messages for the same signal
    TRAILING_SL_COOLDOWN_SECONDS: int = 300  # 5 minutes

    # Sliding-window debounce: each new reply resets this timer so that
    # actions that arrive in quick succession (e.g. auto-partial then
    # auto-BE a couple of seconds later) are batched into one message.
    DEBOUNCE_SECONDS: float = 3.0

    def __init__(self):
        self._trailing_sl_last_sent: Dict[str, datetime] = {}
        self._background_tasks: set = set()
        # Each entry: {'type': str|None, 'text': str, 'data': dict}
        self._pending_items: Dict[str, List[dict]] = {}
        self._pending_action_types: Dict[str, set] = {}
        self._debounce_tasks: Dict[str, asyncio.Task] = {}
        # Bumped on every new reply so stale debounce tasks exit silently.
        self._debounce_versions: Dict[str, int] = {}

    # ------------------------------------------------------------------ #
    #  Public API — initial post                                           #
    # ------------------------------------------------------------------ #

    async def forward_signal(self, signal, risk_assessment, trade_result) -> None:
        """Called right after a trade is executed. Posts the signal card (non-blocking)."""
        signal_id = getattr(signal, 'signal_id', None)
        task = asyncio.create_task(
            self._do_forward_signal(signal_id, signal, risk_assessment, trade_result)
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _do_forward_signal(self, signal_id: Optional[str], signal, risk_assessment, trade_result) -> None:
        try:
            if not await self._is_enabled():
                return
            parent_id = getattr(signal, 'continuation_of', None)
            if parent_id:
                await self._thread_top_up(signal_id, parent_id, signal)
                return
            channel_id = await self._channel_id()
            if not channel_id:
                return
            bot_sender = self._get_bot_sender()
            if not bot_sender:
                return

            text = self._build_signal_text(signal, risk_assessment, trade_result)
            msg_id = await bot_sender.send_direct_message_and_get_id(text, channel_id)

            if msg_id and signal_id:
                await self._store_forwarded_msg_id(signal_id, msg_id)
                logger.info(f"📡 Signal forwarded to channel {channel_id}, msg_id={msg_id}")
            elif msg_id and not signal_id:
                logger.warning(f"⚠️ Signal forwarded (msg_id={msg_id}) but signal_id not set — forwardedMsgId not saved")
        except Exception as e:
            logger.debug(f"Signal forwarder background task error: {e}")

    async def _thread_top_up(self, signal_id: Optional[str], parent_id: str, signal) -> None:
        """The rest of a running signal (split / repost / edit): no card of its own.
        Its record shares the original post, so its fills and closes reply there too,
        and the post gets one reply with the levels that were added."""
        parent_msg_id = await self._get_forwarded_msg_id(parent_id)
        if not parent_msg_id:
            return
        if signal_id:
            await self._store_forwarded_msg_id(signal_id, parent_msg_id)
        legs = signal.discrete_entry_prices() if hasattr(signal, "discrete_entry_prices") else None
        prices = legs or ([signal.entry_price] if signal.entry_price else [])
        entry = " + ".join(f"<code>{_fmt(p)}</code>" for p in prices) or "market"
        tps = " / ".join(f"<code>{_fmt(t)}</code>" for t in (signal.take_profit or [])) or "—"
        text = _pick(
            f"adding the rest at {entry} — SL <code>{_fmt(signal.stop_loss)}</code>, TP {tps}",
            f"rest of it goes in at {entry}, SL <code>{_fmt(signal.stop_loss)}</code>, TP {tps}",
            f"more at {entry} — stop <code>{_fmt(signal.stop_loss)}</code>, targets {tps}",
        )
        await self.reply_action(parent_id, text, action_type="top_up")

    # ------------------------------------------------------------------ #
    #  Public API — typed reply helpers                                    #
    # ------------------------------------------------------------------ #

    async def reply_position_opened(
        self, signal_id: Optional[str], symbol: str, price, trade_id: Optional[str] = None
    ) -> None:
        price_str = f"<code>{_fmt(price)}</code>" if price else "—"
        text = _pick(
            f"filled at {price_str}, in on <b>{symbol}</b> 👀",
            f"in at {price_str} — <b>{symbol}</b>, let's see it",
            f"<b>{symbol}</b> filled at {price_str}, we're live ✅",
            f"got {price_str} on <b>{symbol}</b>, running now",
            f"<b>{symbol}</b> entry at {price_str}, watching",
            f"and we're in — <b>{symbol}</b> at {price_str}",
            f"<b>{symbol}</b> done at {price_str}, let it play",
            f"in on <b>{symbol}</b> {price_str}, let's go",
        )
        await self.reply_action(signal_id, text, action_type="position_opened", trade_id=trade_id)

    async def reply_partial_close(
        self, signal_id: Optional[str], pct: float, lots: float, price, pips: float,
        trade_id: Optional[str] = None,
    ) -> None:
        price_str = f"<code>{_fmt(price)}</code>" if price else "—"
        pips_str = f"{pips:+.1f} pips" if pips else ""
        detail = f" — {pips_str}" if pips_str else ""
        text = _pick(
            f"took {pct:.0f}% off at {price_str}{detail}, rest runs ✅",
            f"{pct:.0f}% out at {price_str}{detail}, letting the rest breathe",
            f"closed {pct:.0f}% at {price_str}{detail}, still in",
            f"banked {pct:.0f}%{detail}, running on house money 🔒",
            f"{pct:.0f}% off at {price_str}{detail}, free roll from here",
            f"took some off — {pct:.0f}% at {price_str}{detail}",
            f"secured {pct:.0f}%{detail}, rest keeps going",
            f"locked {pct:.0f}%{detail}, letting the runner work 📈",
        )
        await self.reply_action(
            signal_id, text, action_type="partial_close",
            _data={'pct': pct, 'lots': lots, 'price': price, 'pips': pips},
            trade_id=trade_id,
        )

    async def reply_breakeven(
        self, signal_id: Optional[str], new_sl, trade_id: Optional[str] = None
    ) -> None:
        sl_str = f"<code>{_fmt(new_sl)}</code>"
        text = _pick(
            f"stop to entry at {sl_str}, free trade now 🛡",
            f"pulled stop to {sl_str}, can't lose on this one",
            f"SL now at {sl_str}, no more risk here",
            f"breakeven at {sl_str}, worst case we scratch",
            f"stop at entry {sl_str}, running free",
            f"SL to BE {sl_str}, protected ✅",
        )
        await self.reply_action(
            signal_id, text, action_type="breakeven",
            _data={'new_sl': new_sl},
            trade_id=trade_id,
        )

    async def reply_trailing_sl(
        self, signal_id: Optional[str], new_sl, trade_id: Optional[str] = None
    ) -> None:
        if not signal_id:
            return
        # Cooldown key is per-trade so sibling positions on the same signal
        # don't suppress each other's trailing updates.
        cooldown_key = f"{signal_id}:{trade_id}" if trade_id else signal_id
        now = datetime.now(timezone.utc)
        last = self._trailing_sl_last_sent.get(cooldown_key)
        if last and (now - last).total_seconds() < self.TRAILING_SL_COOLDOWN_SECONDS:
            return
        self._trailing_sl_last_sent[cooldown_key] = now
        sl_str = f"<code>{_fmt(new_sl)}</code>"
        text = _pick(
            f"trail up to {sl_str}, locking in 📈",
            f"trailing — floor at {sl_str} now",
            f"tightened trail, stop at {sl_str}",
            f"moved stop up to {sl_str}",
            f"protecting gains, trail at {sl_str} 🔒",
            f"trailing {sl_str}, trade working well",
            f"stop {sl_str} — keep trailing",
            f"locking it in, stop now {sl_str}",
        )
        await self.reply_action(signal_id, text, action_type="trailing_sl", trade_id=trade_id)

    async def reply_auto_tp(
        self, signal_id: Optional[str], tp, trade_id: Optional[str] = None
    ) -> None:
        tp_str = f"<code>{_fmt(tp)}</code>"
        text = _pick(
            f"TP set at {tp_str}, let's see it",
            f"target at {tp_str}",
            f"going for {tp_str} here",
            f"added TP at {tp_str}",
        )
        await self.reply_action(signal_id, text, action_type="auto_tp", trade_id=trade_id)

    async def reply_brain_sl(
        self, signal_id: Optional[str], new_sl, reason: str, trade_id: Optional[str] = None
    ) -> None:
        sl_str = f"<code>{_fmt(new_sl)}</code>"
        text = _pick(
            f"moving stop to {sl_str} — {reason}",
            f"SL to {sl_str} — {reason}",
            f"adjusted stop to {sl_str}, {reason}",
            f"stop now {sl_str} — {reason}",
            f"new SL {sl_str} — {reason}",
        )
        await self.reply_action(signal_id, text, action_type="brain_sl", trade_id=trade_id)

    async def reply_brain_tp(
        self, signal_id: Optional[str], new_tp, reason: str, trade_id: Optional[str] = None
    ) -> None:
        tp_str = f"<code>{_fmt(new_tp)}</code>"
        text = _pick(
            f"TP to {tp_str} — {reason}",
            f"new target {tp_str} — {reason}",
            f"moved TP to {tp_str} — {reason}",
            f"target now at {tp_str} — {reason}",
            f"going for {tp_str} instead — {reason}",
        )
        await self.reply_action(signal_id, text, action_type="brain_tp", trade_id=trade_id)

    async def reply_brain_partial(
        self, signal_id: Optional[str], pct: float, lots: float, reason: str,
        trade_id: Optional[str] = None,
    ) -> None:
        text = _pick(
            f"taking {pct:.0f}% off — {reason}",
            f"closed {pct:.0f}% — {reason}",
            f"out with {pct:.0f}% — {reason}",
            f"banked {pct:.0f}% — {reason}",
            f"{pct:.0f}% secured, rest runs — {reason}",
        )
        await self.reply_action(signal_id, text, action_type="brain_partial", trade_id=trade_id)

    async def reply_brain_close(
        self, signal_id: Optional[str], reason: str, trade_id: Optional[str] = None
    ) -> None:
        text = _pick(
            f"closed it — {reason}",
            f"out — {reason}",
            f"exited — {reason}",
            f"got out — {reason}",
            f"done here — {reason}",
        )
        await self.reply_action(signal_id, text, action_type="brain_close", trade_id=trade_id)

    async def reply_closed(
        self,
        signal_id: Optional[str],
        price,
        pips: Optional[float],
        reason: str = "manual",
        trade_id: Optional[str] = None,
    ) -> None:
        price_str = f"<code>{_fmt(price)}</code>" if price else "—"
        pips_str = f"{pips:+.1f} pips" if pips is not None else ""
        p = pips_str

        if not price:
            # No close price (e.g. state recovery after a restart found the trade gone
            # with no deal history): "closed at —" says nothing — report the pips only,
            # or stay silent when there is nothing to report.
            if not p:
                logger.info(f"[Forwarder] Close of signal {signal_id} has no price or pips — not announced")
                return
            label = {"tp": "TP hit", "sl": "SL hit", "be": "out at breakeven",
                     "trailing": "trail hit"}.get(reason, "closed")
            await self.reply_action(signal_id, f"{label} — {p}", action_type="closed", trade_id=trade_id)
            return

        if reason == "tp":
            text = _pick(
                f"TP hit at {price_str} — {p} done" if p else f"TP hit at {price_str}, done",
                f"nailed the target at {price_str}" + (f", {p}" if p else "") + " 🎯",
                f"target hit at {price_str}" + (f" — {p}" if p else "") + ", clean",
                f"out at {price_str}" + (f" for {p}" if p else "") + ", TP filled",
                f"that's the TP — {price_str}" + (f", {p}" if p else "") + " ✅",
                f"booked at {price_str}" + (f" — {p}" if p else "") + ", closed",
                f"and TP — {price_str}" + (f", {p}" if p else "") + ", bagged it",
                f"{price_str}" + (f", {p}" if p else "") + " TP done, good trade",
            )
        elif reason == "be":
            text = _pick(
                f"BE tagged at {price_str}" + (f" ({p})" if p else "") + ", walked away flat",
                f"scratched at {price_str}" + (f" ({p})" if p else "") + ", no damage",
                f"stopped at breakeven {price_str}" + (f" — {p}" if p else "") + ", on to the next",
                f"out at entry {price_str}" + (f" ({p})" if p else "") + ", no harm done",
                f"BE at {price_str}" + (f" — {p}" if p else "") + ", protected it",
                f"closed at BE {price_str}" + (f" ({p})" if p else "") + ", flat",
                f"{price_str}" + (f" ({p})" if p else "") + " — BE, not today",
            )
        elif reason == "trailing":
            text = _pick(
                f"trail caught it at {price_str}" + (f" — {p}" if p else ""),
                f"trail hit at {price_str}" + (f", {p}" if p else "") + ", locked in",
                f"stopped out in profit at {price_str}" + (f" — {p}" if p else ""),
                f"trailing stop triggered at {price_str}" + (f", {p}" if p else "") + ", took what it gave",
                f"trail locked it at {price_str}" + (f" for {p}" if p else "") + " 📈",
                f"runner stopped at {price_str}" + (f" — {p}" if p else "") + ", trail did its job",
            )
        elif reason == "sl":
            text = _pick(
                f"SL hit at {price_str}" + (f" — {p}" if p else "") + ", next one",
                f"stopped out at {price_str}" + (f" ({p})" if p else "") + ", part of the game",
                f"took the stop at {price_str}" + (f" — {p}" if p else ""),
                f"out at stop {price_str}" + (f" — {p}" if p else "") + ", market said no",
                f"stopped at {price_str}" + (f" ({p})" if p else "") + ", cut it and move on",
                f"{price_str}" + (f" — {p}" if p else "") + ", took the L, on to the next",
            )
        else:
            text = _pick(
                f"closed at {price_str}" + (f" — {p}" if p else ""),
                f"out at {price_str}" + (f" ({p})" if p else "") + ", done",
                f"got out at {price_str}" + (f" — {p}" if p else ""),
                f"flat at {price_str}" + (f" ({p})" if p else ""),
            )
        await self.reply_action(signal_id, text, action_type="closed", trade_id=trade_id)

    async def reply_leg_closed(
        self,
        signal_id: Optional[str],
        price,
        pips: Optional[float],
        reason: str,
        open_count: int,
        trade_id: Optional[str] = None,
    ) -> None:
        """One entry of a multi-entry signal closed while others are still open."""
        what = {"tp": "TP hit", "sl": "stopped out", "be": "out at breakeven",
                "trailing": "trail hit"}.get(reason, "closed")
        at = f" at <code>{_fmt(price)}</code>" if price else ""
        p = f" ({pips:+.1f} pips)" if pips is not None else ""
        rest = "1 entry still running" if open_count == 1 else f"{open_count} entries still running"
        text = _pick(
            f"one entry {what}{at}{p} — {rest}",
            f"{what} on one entry{at}{p}, {rest}",
        )
        await self.reply_action(signal_id, text, action_type="leg_closed", trade_id=trade_id)

    async def reply_rr_milestone(
        self, signal_id: Optional[str], milestone: int, profit_pips: float,
        trade_id: Optional[str] = None,
    ) -> None:
        pips_str = f"{profit_pips:+.1f} pips"
        text = _pick(
            f"1:{milestone}R hit, up <code>{pips_str}</code> 🔥",
            f"<code>{pips_str}</code>, that's 1:{milestone}R ✅",
            f"1:{milestone}R locked, running <code>{pips_str}</code>",
            f"<code>{pips_str}</code> — 1:{milestone}R reached",
            f"<code>{pips_str}</code>, 1:{milestone}R in the bag 🎯",
            f"1:{milestone}R done, <code>{pips_str}</code> in profit 💰",
        )
        await self.reply_action(signal_id, text, action_type=f"rr_milestone_{milestone}", trade_id=trade_id)

    async def reply_be_reminder(
        self, signal_id: Optional[str], entry_price, trade_id: Optional[str] = None
    ) -> None:
        """Warn user to manually move SL to breakeven after partial, if auto-BE is off."""
        entry_str = f"<code>{_fmt(entry_price)}</code>" if entry_price else "entry"
        text = _pick(
            f"partial locked in but stop's still at original — move it to {entry_str}, worst case we scratch",
            f"took my cut, now slide that stop to {entry_str} so the rest runs free",
            f"partial off — drag stop to {entry_str}, no reason to give it back",
            f"profits secured, stop needs moving to {entry_str}, then it's a free roll",
        )
        await self.reply_action(
            signal_id, text, action_type="be_reminder",
            _data={'entry_price': entry_price},
            trade_id=trade_id,
        )

    async def reply_signal_edited(
        self,
        signal_id: Optional[str],
        sl_changed: bool,
        tp_changed: bool,
        new_sl=None,
        new_tp=None,
        trade_id: Optional[str] = None,
    ) -> None:
        if not sl_changed and not tp_changed:
            return

        # Build per-field first-person phrases
        if sl_changed and tp_changed and new_sl is not None and new_tp is not None:
            sl_str = f"<code>{_fmt(new_sl)}</code>"
            tp_str = f"<code>{_fmt(new_tp)}</code>"
            text = _pick(
                f"SL → {sl_str}, TP → {tp_str}",
                f"adjusted — SL {sl_str} / TP {tp_str}",
                f"new levels: SL {sl_str}, TP {tp_str}",
            )
        elif sl_changed and new_sl is not None:
            sl_str = f"<code>{_fmt(new_sl)}</code>"
            text = _pick(
                f"SL to {sl_str}",
                f"moved stop to {sl_str}",
                f"stop now {sl_str}",
            )
        elif tp_changed and new_tp is not None:
            tp_str = f"<code>{_fmt(new_tp)}</code>"
            text = _pick(
                f"TP to {tp_str}",
                f"moved target to {tp_str}",
                f"target now {tp_str}",
            )
        else:
            return

        await self.reply_action(signal_id, text, action_type="signal_edited", trade_id=trade_id)

    # ------------------------------------------------------------------ #
    #  Low-level reply accumulator                                         #
    # ------------------------------------------------------------------ #

    async def reply_action(
        self,
        signal_id: Optional[str],
        text: str,
        action_type: Optional[str] = None,
        _data: Optional[dict] = None,
        trade_id: Optional[str] = None,
    ) -> None:
        """Accumulate actions and send them as one consolidated reply.

        Uses a sliding-window debounce: every new reply resets the timer so
        that actions fired in the same monitor cycle (e.g. auto-partial then
        auto-BE a couple of seconds later) are batched into a single message.

        action_type deduplicates same-type events within the debounce window
        at SIGNAL level. A signal can have several sibling positions sharing
        the same magic number/signalId (multi-TP split), and each one fires
        its own event — three positions taking an auto-partial produce three
        identical 'partial_close' events. Only the first is forwarded; the
        rest are dropped so the channel reads as one voice per signal.

        This is a messaging-layer collapse only. Every position still gets
        its own broker action (partial, BE, trailing) — we just stop
        announcing the same thing N times.
        """
        if not signal_id:
            return

        if signal_id not in self._pending_items:
            self._pending_items[signal_id] = []
            self._pending_action_types[signal_id] = set()

        # Dedup at signal level: the first event of a given type wins, any
        # sibling position firing the same action in this window is dropped.
        if action_type:
            if action_type in self._pending_action_types[signal_id]:
                logger.debug(
                    f"[Forwarder] Suppressed duplicate '{action_type}' for signal "
                    f"{signal_id} (trade {trade_id}) — already queued this window"
                )
                return
            self._pending_action_types[signal_id].add(action_type)

        self._pending_items[signal_id].append({
            'type': action_type,
            'text': text,
            'data': _data or {},
            'trade_id': trade_id,
        })

        # Sliding window: bump version so the previous debounce task exits
        # without sending, then start a fresh DEBOUNCE_SECONDS countdown.
        version = self._debounce_versions.get(signal_id, 0) + 1
        self._debounce_versions[signal_id] = version
        task = asyncio.create_task(self._debounce_reply(signal_id, version))
        self._debounce_tasks[signal_id] = task
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _debounce_reply(self, signal_id: str, version: int) -> None:
        await asyncio.sleep(self.DEBOUNCE_SECONDS)

        # A newer reply reset the window — this task is stale, exit silently.
        if self._debounce_versions.get(signal_id) != version:
            return

        items = self._pending_items.pop(signal_id, [])
        self._pending_action_types.pop(signal_id, None)
        self._debounce_versions.pop(signal_id, None)
        if not items:
            return

        unified_text = self._build_combined_message(items)
        await self._do_reply_action(signal_id, unified_text)

    # ------------------------------------------------------------------ #
    #  Combined-message builder                                            #
    # ------------------------------------------------------------------ #

    def _build_combined_message(self, items: List[dict]) -> str:
        """
        Turn a batch of pending actions into one coherent human-readable
        message.

        Signal-level dedup in reply_action() guarantees at most one item per
        action_type here, so the whole batch describes one signal's distinct
        actions and is merged as a single unit — no per-trade grouping. This
        also lets a 'closed' event (which arrives without a trade_id) merge
        with a same-signal partial or BE from the same window.
        """
        if len(items) == 1:
            return items[0]['text']

        return self._build_single_trade_message(items)

    def _build_single_trade_message(self, items: List[dict]) -> str:
        """Combine one signal's distinct actions into one message."""
        if len(items) == 1:
            return items[0]['text']

        types = {item['type'] for item in items if item['type']}
        by_type = {item['type']: item for item in items if item['type']}

        # ── partial_close + breakeven ────────────────────────────────────
        # Most common combo: auto-partial fires, then auto-BE fires seconds
        # later after the broker API call completes.
        if 'partial_close' in types and 'breakeven' in types:
            pc = by_type['partial_close']['data']
            be = by_type['breakeven']['data']
            pct = pc.get('pct', 0)
            price = pc.get('price')
            pips = pc.get('pips')
            new_sl = be.get('new_sl')

            price_str = f"<code>{_fmt(price)}</code>" if price else "—"
            pips_str = f"{pips:+.1f} pips" if pips else ""
            sl_str = f"<code>{_fmt(new_sl)}</code>"
            detail = f" ({pips_str})" if pips_str else ""

            combined = _pick(
                f"took {pct:.0f}% off at {price_str}{detail}, stop to {sl_str} — free now",
                f"{pct:.0f}% out{detail}, SL at entry {sl_str}, no more risk",
                f"partial at {price_str}{detail}, stop now {sl_str}, can't lose",
                f"banked {pct:.0f}%{detail}, dragged stop to {sl_str}, house money",
                f"{pct:.0f}% secured{detail}, BE at {sl_str}, free roll",
                f"took {pct:.0f}% at {price_str}{detail}, stop to entry {sl_str}, worst case scratch",
                f"{pct:.0f}% off{detail}, stop at {sl_str}, just upside now",
                f"{pct:.0f}% booked{detail}, SL to {sl_str}, zero risk from here",
            )

            remaining = [it for it in items if it['type'] not in ('partial_close', 'breakeven')]
            if remaining:
                return combined + "\n" + "\n".join(it['text'] for it in remaining)
            return combined

        # ── partial_close + be_reminder ──────────────────────────────────
        # Auto-BE is off: bot took the partial but user must move SL manually.
        if 'partial_close' in types and 'be_reminder' in types:
            pc = by_type['partial_close']['data']
            br = by_type['be_reminder']['data']
            pct = pc.get('pct', 0)
            price = pc.get('price')
            pips = pc.get('pips')
            entry = br.get('entry_price')

            price_str = f"<code>{_fmt(price)}</code>" if price else "—"
            pips_str = f"{pips:+.1f} pips" if pips else ""
            entry_str = f"<code>{_fmt(entry)}</code>" if entry else "entry"
            detail = f" ({pips_str})" if pips_str else ""

            combined = _pick(
                f"took {pct:.0f}% off at {price_str}{detail} — slide that stop to {entry_str}, worst case we scratch",
                f"{pct:.0f}% banked{detail} — move stop to {entry_str} so the rest runs free",
                f"partial at {price_str}{detail}, stop needs moving — {entry_str}, then it's a free roll",
                f"{pct:.0f}% locked in{detail}, shift stop to {entry_str}, protect the runner",
                f"good, {pct:.0f}% off{detail} — now drag that stop to {entry_str}",
            )

            remaining = [it for it in items if it['type'] not in ('partial_close', 'be_reminder')]
            if remaining:
                return combined + "\n" + "\n".join(it['text'] for it in remaining)
            return combined

        # ── Default: join the pre-formatted texts ────────────────────────
        # For any other combination, output each line separately.
        return "\n".join(item['text'] for item in items)

    async def _do_reply_action(self, signal_id: str, text: str) -> None:
        try:
            if not await self._is_enabled():
                return
            channel_id = await self._channel_id()
            if not channel_id:
                return
            forwarded_msg_id = await self._get_forwarded_msg_id(signal_id)
            if not forwarded_msg_id:
                return
            bot_sender = self._get_bot_sender()
            if not bot_sender:
                return
            await bot_sender.send_reply(text, channel_id, forwarded_msg_id)
        except Exception as e:
            logger.debug(f"Signal forwarder reply background task error: {e}")

    # ------------------------------------------------------------------ #
    #  Signal card builder                                                 #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_order_type(signal) -> tuple:
        """Return (direction, order_label, order_emoji) from signal metadata.

        Uses signal.signal_type first (e.g. BUY_LIMIT, SELL_STOP) which has
        the full picture, then falls back to signal.order_type + signal_type
        heuristics.
        """
        # Primary source: signal_type enum (BUY_LIMIT, SELL_STOP, BUY, SELL, CLOSE)
        st = getattr(signal, "signal_type", None)
        st_val = str(getattr(st, "value", st) or "").upper().replace("-", "_")

        # Secondary source: order_type enum (BUY or SELL only — direction)
        ot = getattr(signal, "order_type", None)
        ot_val = str(getattr(ot, "value", ot) or "").upper()

        # Derive direction
        if "BUY" in st_val or ot_val == "BUY":
            direction = "Buy"
        elif "SELL" in st_val or ot_val == "SELL":
            direction = "Sell"
        else:
            direction = st_val.capitalize() if st_val else "Buy"

        # Derive execution type
        if "LIMIT" in st_val:
            order_label, order_emoji = "Limit Order", "📋"
        elif "STOP" in st_val:
            order_label, order_emoji = "Stop Order", "🔔"
        else:
            order_label, order_emoji = "Instant Execution", "⚡"

        return direction, order_label, order_emoji

    def _build_signal_text(self, signal, risk_assessment, trade_result) -> str:
        from src.integrations.telegram.bot_sender import escape_html

        symbol = escape_html(str(signal.symbol or "?"))
        direction, order_label, order_emoji = self._parse_order_type(signal)
        is_buy = direction == "Buy"
        direction_emoji = "📈" if is_buy else "📉"

        # ── Order type with clear emoji ──────────────────────────────────
        order_badge = f"{order_emoji} <b>{order_label}</b>"

        # ── Entry — scale-in legs, single price, or range ───────────────
        legs = signal.discrete_entry_prices() if hasattr(signal, "discrete_entry_prices") else None
        range_min = getattr(signal, "entry_range_min", None)
        range_max = getattr(signal, "entry_range_max", None)
        has_range = bool(range_min and range_max)
        if legs:
            entry = "  +  ".join(f"<code>{_fmt(p)}</code>" for p in legs)
            entry += f"  <i>({len(legs)}-leg scale-in)</i>"
        elif has_range:
            entry = f"<code>{_fmt(range_max)}</code> – <code>{_fmt(range_min)}</code>"
        else:
            entry = f"<code>{_fmt(signal.entry_price)}</code>"

        sl = _fmt(signal.stop_loss)
        sl_pips_raw = getattr(risk_assessment, "stop_loss_pips", None)
        sl_pips = f" (-{_fmt(sl_pips_raw, 1)}p)" if sl_pips_raw else ""

        tp_list = []
        if signal.take_profit:
            import json
            try:
                tp_list = json.loads(signal.take_profit) if isinstance(signal.take_profit, str) else list(signal.take_profit)
            except Exception as _exc:
                logger.debug(f"Suppressed exception: {_exc!r}")

        if len(tp_list) > 1:
            tp_parts = []
            for i, tp in enumerate(tp_list):
                tp_parts.append(f"TP{i+1} <code>{_fmt(tp)}</code>")
            tp_line = "  |  ".join(tp_parts)
        elif tp_list:
            tp_display = _fmt(tp_list[0])
            tp_pips_raw = getattr(risk_assessment, "take_profit_pips", None)
            tp_pips = f" (+{_fmt(tp_pips_raw, 1)}p)" if tp_pips_raw else ""
            tp_line = f"<code>{tp_display}</code>{tp_pips}"
        else:
            tp_line = "—"

        rr_raw = getattr(risk_assessment, "risk_reward_ratio", None)
        risk_pct_raw = getattr(risk_assessment, "risk_percent", None)

        footer_parts = []
        if rr_raw:
            footer_parts.append(f"RR 1:{_fmt(rr_raw, 1)}")
        if risk_pct_raw:
            footer_parts.append(f"risk {_fmt(risk_pct_raw, 2)}%")
        footer = "  ·  ".join(footer_parts) if footer_parts else ""

        range_note = "spread across range" if has_range else ""

        opening = _pick(
            f"{direction_emoji} <b>{direction} {symbol}</b>",
            f"{direction_emoji} <b>{symbol} {direction}</b>",
            f"{direction_emoji} <b>{direction}</b> on <b>{symbol}</b>",
        )

        lines = [opening, order_badge, ""]
        lines.append(f"💰 Entry: {entry}")
        if range_note:
            lines.append(f"<i>{range_note}</i>")
        lines.append(f"🛑 SL: <code>{sl}</code>{sl_pips}")
        lines.append(f"🎯 TP: {tp_line}")
        if footer:
            lines.append("")
            lines.append(f"📊 {footer}")

        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    async def _is_enabled(self) -> bool:
        try:
            from src.services.settings_service import settings_service
            if settings_service is None:
                return False
            val = await settings_service.get_setting("SIGNAL_FORWARD_ENABLED", False)
            if isinstance(val, bool):
                return val
            return str(val).lower() in ("true", "1", "yes")
        except Exception:
            return False

    async def _channel_id(self) -> Optional[str]:
        try:
            from src.services.settings_service import settings_service
            if settings_service is None:
                return None
            val = await settings_service.get_setting("SIGNAL_FORWARD_CHANNEL_ID", "")
            return str(val).strip() if val else None
        except Exception:
            return None

    def _get_bot_sender(self):
        try:
            from src.integrations.telegram.unified_sender import notification_sender
            bot_sender = getattr(notification_sender, "bot_sender", None)
            if bot_sender and getattr(bot_sender, "bot", None):
                return bot_sender
            logger.warning("⚠️ Signal forwarder: bot_sender not available")
            return None
        except Exception as e:
            logger.warning(f"⚠️ Signal forwarder: could not get bot_sender: {e}")
            return None

    async def _store_forwarded_msg_id(self, signal_id: str, msg_id: int) -> None:
        try:
            from src.core.database_service import db_service
            await db_service.db.signal.update(
                where={"id": signal_id},
                data={"forwardedMsgId": msg_id},
            )
        except Exception as e:
            logger.warning(f"⚠️ Could not store forwardedMsgId for {signal_id[:8]}: {e}")

    async def _get_forwarded_msg_id(self, signal_id: str) -> Optional[int]:
        try:
            from src.core.database_service import db_service
            sig = await db_service.db.signal.find_unique(where={"id": signal_id})
            if sig:
                return getattr(sig, "forwardedMsgId", None)
            return None
        except Exception as e:
            logger.debug(f"Could not get forwardedMsgId for {signal_id[:8]}: {e}")
            return None


# Module-level singleton
signal_forwarder_service = SignalForwarderService()
