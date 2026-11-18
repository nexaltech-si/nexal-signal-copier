"""
Trading Service
Orchestrates the complete trading workflow
"""
import asyncio
import copy
import math
import time as _time
from types import SimpleNamespace
from typing import Optional
from datetime import datetime, timezone, timedelta
from loguru import logger
from src.utils.tasks import spawn

from src.models import TradingSignal, TradeResult, RiskAssessment, SignalAction, OrderType, AccountInfo
from src.models.message import MessageIdentifier
from src.integrations.trading.provider_factory import create_trading_provider
from src.integrations.telegram.unified_sender import notification_sender
from src.services.action_results import failure_block, log_partial_failure
from src.services.risk_service import risk_manager
from src.services.trade_mapper import trade_mapper
from src.services.magic_number_service import magic_number_service
from src.services.drawdown_protection_service import drawdown_protection_service
from src.services.signal_validator_service import signal_validator_service, SignalValidationResult
from src.core.database_service import db_service
from config import settings

# Signals of the channel (same symbol, explicit SL) whose widest SL sets the
# temporary SL of an instant entry posted without one.
TEMP_SL_HISTORY = 10

# Lazy import to avoid circular dependency
news_trading_service = None


def _get_news_services():
    global news_trading_service
    if news_trading_service is None:
        from src.services.news_service import news_trading_service as nts
        news_trading_service = nts
    return news_trading_service


class TradingService:
    """
    Orchestrates the complete signal processing pipeline:
     1.  /pause guard
     2.  MODIFY / CLOSE routing
     3.  Field validation
     4.  Message age check      (instant signals included — a stale "NOW" is still stale)
     4.5 Continuity             follow-up / repost / same post → update the running signal
     5.  Signal-received notification
     6.  Async news filter
     7.  Drawdown protection    (hard block — before the brain so no LLM call is spent)
     7.5 Same-level rule        no new orders where this channel already runs (unless at BE)
     8.  Account info fetch
     8.5 Temporary SL           instant entry posted without SL
     9.  Trading Brain review   ← LLM APPROVE / REJECT / MODIFY
    10.  Risk assessment        (+ the signal's risk budget for temp-SL entries / top-ups)
    11.  Persist signal + risk to DB
    12.  External signal validator (optional)
    13.  Manual approval or direct execution — priority in execution_policy

    Hard blocks run cheapest-first; the approval decision comes last so a human is
    only asked about a signal that already passed every automatic check.
    """

    def __init__(self, trading_provider=None):
        self._trading_provider = trading_provider
        logger.info(f"🔧 TradingService initialized with {settings.provider_label}")

    def set_trading_provider(self, provider):
        """Inject the initialized trading provider (called after provider connects)."""
        self._trading_provider = provider
        logger.info(f"🔧 TradingService: trading provider set ({settings.provider_label})")

    @property
    def trading_provider(self):
        if self._trading_provider is None:
            self._trading_provider = create_trading_provider()
        return self._trading_provider

    # ── Main pipeline ────────────────────────────────────────────────────────

    async def process_signal(self, signal: TradingSignal) -> None:
        """Process a trading signal through the complete workflow."""
        symbol = signal.symbol or "?"
        t_pipeline = _time.monotonic()
        logger.info(f"\n{'='*60}")
        logger.info(f"🎯 PROCESSING SIGNAL: {signal.action} {symbol}")
        if getattr(signal, 'instant_execution', False):
            logger.info("🚀 Instant entry: fills at market within the deviation cap")
        logger.info(f"{'='*60}")

        # ── 1. Respect /pause ────────────────────────────────────────
        try:
            from src.services.approval_queue import approval_queue as _aq
            if _aq.paused:
                logger.info(f"⏸️ Signal processing paused — skipping {symbol}")
                return
        except Exception as e:
            logger.warning(f"⚠️ Pause guard check failed: {e}")

        try:
            # ── 2. MODIFY / CLOSE routing ────────────────────────────
            if signal.action in [SignalAction.MODIFY, SignalAction.CLOSE, SignalAction.PARTIAL_CLOSE]:
                await self._handle_management_signal(signal)
                return

            # ── 3. Only OPEN signals past this point ─────────────────
            if signal.action != SignalAction.OPEN:
                logger.warning(f"⚠️ Unknown signal action: {signal.action} — skipping")
                return

            if not signal.symbol or signal.order_type is None:
                logger.warning("⚠️ Signal missing symbol or order_type — skipping")
                return

            is_top_up = bool(getattr(signal, 'continuation_of', None))
            # Placed by hand from the dashboard: the owner chose this trade, so the
            # automatic flow's judgement (age, continuity, brain, approval) is skipped.
            manual = getattr(signal, 'manual_placement', False) is True
            original_signal = signal

            # ── 4. Message age validation ────────────────────────────
            # A top-up of a running signal is current by definition (an edited
            # message keeps its original date), so only new messages are aged.
            is_valid, age_reason = (True, None) if is_top_up or manual else self._validate_message_age(signal)
            if not is_valid:
                logger.warning(f"⏰ Signal rejected (age): {age_reason}")
                await notification_sender.notify_signal_rejected(signal, age_reason)
                msg_id = getattr(signal, 'telegram_message_id', None) or self._create_dummy_message_id(signal)
                sig_id = await db_service.save_signal(signal, msg_id)
                await db_service.update_signal_risk_assessment(
                    sig_id,
                    self._rejection_assessment(age_reason, ["Message too old — likely bot restart or history scan"])
                )
                return

            # ── 4.4 Same message already executed ────────────────────
            # The in-memory "processed" set is empty after a restart and the catch-up
            # cursor is saved with a delay, so a message executed just before a crash
            # or deploy can be replayed. A message whose signal already placed orders
            # is never executed a second time.
            if not is_top_up and not manual and await self._already_executed(signal):
                logger.warning(f"🔁 {symbol}: message {signal.message_id} already executed — not trading it again")
                await notification_sender.send_message(
                    f"🔁 <b>{symbol}</b>: this channel message was already executed — not opened a second time",
                    category='signal_rejected')
                return

            # ── 4.5 Continuity: follow-up / repost of a running signal ──
            # A split signal ("SELL GOLD NOW" then the full levels), a deleted-and-
            # reposted signal or the same setup posted twice updates the existing
            # signal instead of opening a second trade (see signal_continuity).
            if not is_top_up and not manual:
                from src.services.signal_continuity import signal_continuity
                try:
                    parent, why = await signal_continuity.find_parent(signal)
                except Exception as e:
                    logger.error(f"⚠️ Continuity lookup failed — treating as a new signal: {e}")
                    parent, why = None, None
                if parent:
                    logger.info(f"🔗 {symbol}: {why} — updating signal {parent.id[:8]} instead of a new trade")
                    if signal.image_data:
                        await db_service.merge_signal_supplementary_info(parent.id, image_data=signal.image_data)
                    await signal_continuity.apply_update(
                        parent, signal, getattr(signal, 'telegram_message_id', None), source=why)
                    return

            # ── 5. Signal received notification ──────────────────────
            # A top-up was already announced by the continuity notice — it is the
            # rest of the running signal, not a new one.
            if not is_top_up:
                await notification_sender.notify_signal_received(signal)

            # ── 6. Async news filter ─────────────────────────────────
            logger.info("🔍 Step 1: Checking news trading blocks...")
            blocked, news_reason = await self._check_news_filter(signal)
            if blocked:
                logger.warning(f"📰 Signal blocked by news: {news_reason}")
                # Send Telegram notification so the user knows why the trade was blocked
                try:
                    news_notification = (
                        f"📰 <b>Trade Blocked by News Filter</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"<b>Symbol:</b> {symbol}\n"
                        f"<b>Action:</b> {signal.order_type.value if signal.order_type else 'OPEN'}\n"
                        f"<b>Entry:</b> {signal.entry_price or 'N/A'}\n"
                        f"<b>Reason:</b> {news_reason}\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"⏳ Trading will resume after the news window passes"
                    )
                    await notification_sender.send_message(news_notification, category='signal_rejected')
                except Exception as e:
                    logger.warning(f"⚠️ Could not send news-block notification: {e}")
                await self._record_rejection(
                    signal, f"News Block: {news_reason}", [f"High-impact news for {symbol}"])
                from ai.trading_brain import trading_brain
                trading_brain.notify_trade_rejected(signal, news_reason)
                return
            logger.info("✅ News check passed")

            # ── 7. Drawdown protection ───────────────────────────────
            logger.info("🔍 Step 2: Checking drawdown protection...")
            dd_reason = await self._drawdown_block_reason()
            if dd_reason:
                await notification_sender.notify_signal_rejected(
                    signal, f"Trading paused due to drawdown breach. {dd_reason}"
                )
                await self._record_rejection(
                    signal, f"Drawdown Pause: {dd_reason}",
                    ["Trading paused — daily drawdown limit breached", "Will resume on new trading day"])
                return

            # ── 7.5 Same-level rule ──────────────────────────────────
            # Never add orders at a level where this channel already has same-direction
            # orders running, unless all of them are at break-even.
            from src.services.signal_continuity import signal_continuity
            try:
                signal, same_level_reason = await signal_continuity.filter_same_level(signal)
            except Exception as e:
                logger.error(f"⚠️ Same-level check failed — continuing without it: {e}")
                same_level_reason = None
            if signal is None:
                reason = f"Duplicate level: {same_level_reason}"
                logger.warning(f"🧱 {symbol}: {reason}")
                return await self._reject_early(original_signal, reason, ["Same-level rule (orders not at break-even)"])

            # ── 8. Account info ──────────────────────────────────────
            logger.info("🔍 Step 3: Fetching account information...")
            account_info = await self._get_account_info()

            # ── 8.5 Instant entry without SL → temporary SL ─────────
            if signal.instant_execution and not signal.stop_loss and not signal.is_plan:
                await self._apply_temp_stop_loss(signal, account_info)

            # ── 9. Trading Brain review ──────────────────────────────
            if manual:
                logger.info("🧠 Step 4: Trading Brain skipped — placed by hand")
            else:
                logger.info("🧠 Step 4: Trading Brain review...")
                signal = await self._brain_review(signal, account_info)
                if signal is None:
                    # Brain rejected — _brain_review already notified + saved decision
                    return

            # ── 10. Risk assessment ───────────────────────────────────
            logger.info("🔍 Step 5: Performing risk assessment...")
            risk_assessment = await risk_manager.assess_risk(signal, account_info)
            if signal.risk_budget_amount is not None:
                risk_assessment = await self._apply_risk_budget(signal, risk_assessment)
            risk_assessment = await self._apply_symbol_total_risk_cap(signal, account_info, risk_assessment)
            logger.info(f"✅ Risk assessment: {'APPROVED' if risk_assessment.approved else 'REJECTED'}")

            # ── 11. Persist signal + risk to DB ──────────────────────
            # A top-up is the rest of a running signal: its orders are recorded on
            # that signal, never as a second one (2026-11-12: a follow-up showed up
            # as two signals — the parent and a copy holding the added orders).
            if is_top_up:
                signal_id = signal.continuation_of
            else:
                msg_id = getattr(signal, 'telegram_message_id', None) or self._create_dummy_message_id(signal)
                signal_id = await db_service.save_signal(signal, msg_id)
                await db_service.update_signal_risk_assessment(signal_id, risk_assessment)

            # High-risk override: if the ONLY problem is that risk exceeds the
            # configured maximum, don't auto-reject — offer it for manual approval
            # with a prominent disclaimer (when ALLOW_HIGH_RISK_OVERRIDE is on).
            high_risk_override = False
            # Structural failures (no valid lot size could be computed — e.g. SL on
            # the wrong side, no price data, max positions reached) always block,
            # regardless of REQUIRE_RISK_VALIDATION: there's nothing safe to execute.
            # The bypass only applies to soft, sizing-succeeded rejections (risk %
            # too high, poor R:R) where calculated_lot_size is a real, usable value.
            if (
                not risk_assessment.approved
                and not settings.require_risk_validation
                and (risk_assessment.calculated_lot_size or 0) > 0
            ):
                logger.warning(
                    f"⚠️ Risk assessment would REJECT {symbol} ({risk_assessment.reason}) but "
                    f"REQUIRE_RISK_VALIDATION is off — executing anyway with computed sizing "
                    f"({risk_assessment.calculated_lot_size} lots)"
                )
            elif not risk_assessment.approved:
                if getattr(risk_assessment, 'risk_limit_exceeded', False) and settings.allow_high_risk_override:
                    logger.warning(
                        f"⚠️ {risk_assessment.reason} — high-risk override enabled, "
                        f"requesting manual confirmation instead of rejecting"
                    )
                    high_risk_override = True
                else:
                    await self._handle_rejected_signal(signal, risk_assessment)
                    return

            # ── 12. External signal validator (optional) ─────────────
            logger.info("🔍 Step 6: External signal validation...")
            validation_result = await self._validate_signal(signal)
            if validation_result and getattr(validation_result, 'blocked_by_policy', False):
                block_reason = getattr(validation_result, 'block_reason', 'Blocked by validator policy')
                logger.error(f"🚫 Signal blocked by validator: {block_reason}")
                await notification_sender.notify_signal_rejected(signal, block_reason)
                if not is_top_up:   # the running signal keeps its own status
                    await db_service.update_signal_risk_assessment(
                        signal_id,
                        self._rejection_assessment(
                            block_reason,
                            [f"Signal Validator verdict: {getattr(validation_result, 'verdict', 'INVALID')}"]
                        )
                    )
                return
            if validation_result and not getattr(validation_result, 'is_unavailable', False):
                logger.info(f"✅ Signal Validator: {getattr(validation_result, 'verdict', 'OK')}")

            # ── 13. Manual approval or direct execution ───────────────
            logger.info("🔍 Step 7: Processing trade decision...")
            if self._requires_manual_approval(signal, high_risk_override, getattr(risk_assessment, 'sizing_estimated', False)):
                if is_top_up:
                    # The approval queue tracks a request by its own record (its status
                    # must not touch the running signal); removed once it is executed.
                    msg_id = getattr(signal, 'telegram_message_id', None) or self._create_dummy_message_id(signal)
                    signal_id = await db_service.save_signal(signal, msg_id)
                    await db_service.update_signal_risk_assessment(signal_id, risk_assessment)
                await self._request_manual_approval(signal, risk_assessment, signal_id, validation_result)
            else:
                await self._execute_approved_trade(signal, risk_assessment, signal_id, validation_result)

            pipeline_ms = int((_time.monotonic() - t_pipeline) * 1000)
            logger.info(f"⏱️ Pipeline total: {pipeline_ms}ms ({pipeline_ms/1000:.1f}s)")
            logger.info(f"{'='*60}\n")

        except Exception as e:
            logger.error(f"❌ Error processing signal {symbol}: {e}")
            logger.exception(e)
            try:
                await notification_sender.notify_error("signal_processing", str(e))
            except Exception as notify_err:
                logger.warning(f"⚠️ Could not send error notification: {notify_err}")

    # ── Public helper ────────────────────────────────────────────────────────

    async def get_account_info(self):
        """Fetch live account info from the trading provider."""
        return await self._get_account_info()

    # ── Internal pipeline steps ──────────────────────────────────────────────

    async def _handle_management_signal(self, signal: TradingSignal):
        """Route MODIFY / CLOSE / PARTIAL_CLOSE to the appropriate handler."""
        logger.info(f"🔍 Validating {signal.action.value} signal — checking for existing trades...")
        open_positions = await db_service.get_open_positions_by_symbol(
            symbol=signal.symbol,
            channel_id=signal.channel_id
        )

        if not open_positions:
            rejection_reason = f"No open trades found for {signal.symbol} in channel {signal.channel_id}"
            logger.error(f"🚫 {signal.action.value} signal rejected: {rejection_reason}")
            # Suppressed Telegram notification — reduces noise for missing-trade rejections
            msg_id = getattr(signal, 'telegram_message_id', None) or self._create_dummy_message_id(signal)
            sig_id = await db_service.save_signal(signal, msg_id)
            await db_service.update_signal_risk_assessment(
                sig_id,
                self._rejection_assessment(
                    rejection_reason,
                    [f"{signal.action.value} signal requires an existing open trade"]
                )
            )
        else:
            logger.success(f"✅ Found {len(open_positions)} open trade(s) for {signal.symbol}")
            # MODIFY/CLOSE are handled upstream by message_handler.py
            logger.warning(f"⚠️ {signal.action.value} signals are handled in message_handler, not here")

    async def _handle_close_signal(self, signal: TradingSignal):
        """Handle a bare CLOSE signal — delegates to reply handler by symbol."""
        try:
            if signal.symbol and signal.channel_id:
                positions = await self.trading_provider.get_positions_by_symbol(signal.symbol)
                if positions:
                    logger.info(f"🔒 Closing {len(positions)} position(s) for {signal.symbol}")
        except Exception as e:
            logger.error(f"❌ Handle close signal failed: {e}")

    async def _get_account_info(self):
        """Fetch live account info; return dummy values on failure."""
        if settings.dry_run or settings.skip_metaapi:
            logger.info("🧪 DRY RUN / SKIP MODE: Using mock account info")
            from src.models.account import AccountInfo
            return AccountInfo(balance=10000.0, equity=10000.0, margin=0.0, free_margin=10000.0, open_positions=0)
        try:
            # Fresh, not the provider's cached copy (60 s on MT5 REST): the count of
            # open setups in it decides Max Open Positions, and signals arriving
            # within that minute all saw the old count and went through.
            return await self.trading_provider.get_account_info(use_cache=False)
        except Exception as e:
            logger.warning(f"Could not fetch account info: {e}")
            from src.models import AccountInfo
            return AccountInfo(balance=10000.0, equity=10000.0, margin=0.0, free_margin=10000.0, open_positions=0)

    async def _check_news_filter(self, signal: TradingSignal):
        """Check if trading is blocked by the economic calendar (async)."""
        try:
            nts = _get_news_services()
            # is_trading_blocked_by_news is synchronous and returns (blocked, reason).
            # (The old code called a non-existent check_news_for_symbol via hasattr,
            #  which silently disabled the news filter entirely.)
            if nts and hasattr(nts, 'is_trading_blocked_by_news'):
                blocked, reason = nts.is_trading_blocked_by_news(signal.symbol)
                return blocked, reason
        except Exception as e:
            logger.debug(f"News filter check failed: {e}")
        return False, ""

    async def _get_news_events_for_brain(self, signal: TradingSignal) -> list:
        """Fetch upcoming news events to give the brain context."""
        try:
            nts = _get_news_services()
            if nts and hasattr(nts, 'get_upcoming_events_for_symbol'):
                return await nts.get_upcoming_events_for_symbol(signal.symbol) or []
        except Exception as e:
            logger.debug(f"Could not fetch news events for brain: {e}")
        return []

    async def _brain_review(self, signal: TradingSignal, account_info) -> Optional[TradingSignal]:
        """
        Submit signal to the Trading Brain for review.
        Returns the (possibly modified) signal, or None if the brain rejects it.
        """
        from ai.trading_brain import trading_brain
        if not trading_brain.enabled:
            logger.info(f"🧠 Brain DISABLED — skipping review for {signal.symbol}")
            return signal

        try:
            import time
            t0 = time.monotonic()
            news_events = await self._get_news_events_for_brain(signal)
            decision = await trading_brain.review_signal(signal, account_info, news_events)
            elapsed_ms = int((time.monotonic() - t0) * 1000)

            # Persist brain decision (fire-and-forget)
            try:
                input_data = {
                    "symbol": signal.symbol,
                    "order_type": getattr(getattr(signal, 'order_type', None), 'value', None),
                    "entry_price": signal.entry_price,
                    "stop_loss": signal.stop_loss,
                    "take_profit": signal.take_profit,
                    "lot_size": signal.lot_size,
                    "channel": signal.channel_name,
                }
                output_data = None
                if decision.verdict == 'MODIFY':
                    output_data = {
                        "modified_entry": decision.modified_entry,
                        "modified_sl": decision.modified_sl,
                        "modified_tp": decision.modified_tp,
                        "modified_lot": decision.modified_lot,
                    }
                spawn(db_service.save_brain_signal_decision(
                    symbol=signal.symbol,
                    verdict=decision.verdict,
                    reason=decision.reason,
                    input_data=input_data,
                    output_data=output_data,
                    signal_id=getattr(signal, 'signal_id', None),
                    execution_ms=elapsed_ms,
                ))
            except Exception as _e:
                logger.debug(f"Brain decision persist skipped: {_e}")

            if decision.verdict == 'REJECT':
                if not settings.require_risk_validation:
                    logger.warning(
                        f"🧠 Brain would REJECT {signal.symbol} ({decision.reason}) but "
                        f"REQUIRE_RISK_VALIDATION is off — executing anyway"
                    )
                    await notification_sender.send_message(
                        f"🧠 <b>Brain flagged {signal.symbol}</b> but validation is disabled — trading anyway:\n{decision.reason}",
                        category='brain_decision'
                    )
                    return signal
                logger.warning(f"🧠 Brain REJECTED {signal.symbol}: {decision.reason}")
                await notification_sender.notify_signal_rejected(
                    signal, f"🧠 Brain: {decision.reason}"
                )
                trading_brain.notify_trade_rejected(signal, decision.reason)
                return None

            if decision.verdict == 'MODIFY':
                logger.info(f"🧠 Brain MODIFIED {signal.symbol}: {decision.reason}")
                signal = self._apply_brain_modifications(signal, decision)
                await notification_sender.send_message(
                    f"🧠 <b>Brain modified signal</b> ({signal.symbol}):\n{decision.reason}",
                    category='brain_decision'
                )

            if getattr(decision, 'force_approval', False):
                logger.info(f"🧠 Brain unavailable — forcing manual approval for {signal.symbol}")
                setattr(signal, 'force_manual_approval', True)

        except Exception as e:
            logger.error(f"❌ Brain review exception: {e}")
            # Don't block execution — fall through to APPROVE on error

        return signal

    def _apply_brain_modifications(self, signal: TradingSignal, decision) -> TradingSignal:
        """Apply MODIFY parameters from a BrainDecision onto the signal."""
        from dataclasses import replace as dc_replace
        try:
            kwargs = {}
            if decision.modified_entry is not None:
                kwargs['entry_price'] = decision.modified_entry
            if decision.modified_sl is not None:
                kwargs['stop_loss'] = decision.modified_sl
            if decision.modified_tp is not None:
                kwargs['take_profit'] = decision.modified_tp
                if decision.modified_tp:
                    kwargs['take_profit_levels'] = decision.modified_tp
            if decision.modified_lot is not None:
                kwargs['lot_size'] = decision.modified_lot
            if kwargs:
                signal = dc_replace(signal, **kwargs)
        except Exception as e:
            logger.warning(f"⚠️ Could not apply brain modifications: {e}")
        return signal

    async def _validate_signal(self, signal: TradingSignal) -> Optional[SignalValidationResult]:
        """Optional external signal validation. Returns None when disabled or unavailable."""
        if not settings.enable_signal_validator:
            return None
        try:
            return await signal_validator_service.validate(signal)
        except Exception as e:
            logger.debug(f"Signal validation skipped: {e}")
        return None

    @staticmethod
    async def _already_executed(signal: TradingSignal) -> bool:
        """This channel message already has a signal with orders placed (any not failed)."""
        if not signal.channel_id or not signal.message_id or int(signal.message_id) <= 0:
            return False
        try:
            existing = await db_service.db.signal.find_first(
                where={"channelId": str(signal.channel_id), "messageId": int(signal.message_id)})
            if not existing:
                return False
            placed = await db_service.db.trade.count(
                where={"signalId": existing.id, "status": {"notIn": ["FAILED"]}})
            return placed > 0
        except Exception as e:
            logger.warning(f"⚠️ Already-executed check failed — continuing: {e}")
            return False

    async def _reject_early(self, signal: TradingSignal, reason: str, warnings: list) -> None:
        """Notify + record a signal rejected before risk assessment."""
        await notification_sender.notify_signal_rejected(signal, reason)
        await self._record_rejection(signal, reason, warnings)

    async def _record_rejection(self, signal: TradingSignal, reason: str, warnings: list) -> None:
        """Save a rejected signal. A rejected top-up leaves no record: it is part of
        the running signal, which keeps its own status."""
        if getattr(signal, 'continuation_of', None):
            return
        msg_id = getattr(signal, 'telegram_message_id', None) or self._create_dummy_message_id(signal)
        sig_id = await db_service.save_signal(signal, msg_id)
        await db_service.update_signal_risk_assessment(sig_id, self._rejection_assessment(reason, warnings))

    async def _apply_temp_stop_loss(self, signal: TradingSignal, account_info) -> None:
        """
        "SELL GOLD NOW" without SL: protect it with a temporary SL beyond the entry
        (the worse of the stated entry and the live price) and size it on
        INSTANT_FIRST_ENTRY_RISK_SHARE of the risk budget. The follow-up message
        replaces the SL and tops up within the remaining budget (signal_continuity).

        The SL is as wide as the widest SL the channel used on this symbol in its
        last TEMP_SL_HISTORY signals, never tighter than INSTANT_TEMP_SL_PIPS. Sized
        on a tighter SL than the real one, the share grows when the real SL arrives:
        #34809 entered on 100 pips, the real SL was 235 — the first entry then used
        104% of the budget and the scale-in leg got nothing.
        """
        is_buy = signal.order_type == OrderType.BUY
        price = await risk_manager._fetch_current_price(signal.symbol, signal.signal_type)
        pip_size = 1.0 / await risk_manager._get_pip_multiplier(signal.symbol)
        distance = max(float(settings.instant_temp_sl_pips) * pip_size, await self._recent_sl_distance(signal))
        ref = min(price, signal.entry_price or price) if is_buy else max(price, signal.entry_price or price)
        signal.stop_loss = round(ref - distance if is_buy else ref + distance, 5)
        signal.temp_stop_loss = True
        share = max(min(float(settings.instant_first_entry_risk_share), 100.0), 1.0) / 100.0
        signal.risk_budget_amount = account_info.balance * settings.max_risk_per_trade_percent / 100.0 * share
        logger.warning(
            f"🛡️ {signal.symbol}: instant entry without SL — temporary SL {signal.stop_loss} "
            f"({distance / pip_size:.0f} pips), using {share:.0%} of the risk budget"
        )

    @staticmethod
    async def _recent_sl_distance(signal: TradingSignal) -> float:
        """Widest entry-to-SL distance in the channel's recent signals on this symbol; 0 if none."""
        if not signal.channel_id:
            return 0.0
        try:
            rows = await db_service.db.signal.find_many(
                where={"channelId": str(signal.channel_id), "symbol": signal.symbol,
                       "entryPrice": {"not": None}, "stopLoss": {"not": None}},
                order={"createdAt": "desc"}, take=TEMP_SL_HISTORY,
            )
        except Exception as e:
            logger.warning(f"⚠️ {signal.symbol}: no SL history for the temporary SL, using the setting: {e}")
            return 0.0
        return max((abs(r.entryPrice - r.stopLoss) for r in rows), default=0.0)

    async def _apply_risk_budget(self, signal: TradingSignal, ra: RiskAssessment) -> RiskAssessment:
        """Scale the lot down so this order set risks at most signal.risk_budget_amount."""
        import math
        budget = float(signal.risk_budget_amount or 0)
        if ra.calculated_lot_size <= 0 or ra.risk_amount <= 0:
            return ra
        if not ra.approved and not ra.risk_limit_exceeded:
            return ra
        if ra.risk_amount <= budget:
            return ra
        try:
            spec = await self.trading_provider.get_symbol_specification(signal.symbol)
            step, vmin = spec.get('volumeStep', 0.01) or 0.01, spec.get('volumeMin', settings.min_lot_size)
        except Exception:
            step, vmin = 0.01, settings.min_lot_size
        vmin = max(vmin, settings.min_lot_size)
        lot = round(math.floor(ra.calculated_lot_size * budget / ra.risk_amount / step + 1e-9) * step, 2)
        if lot < vmin:
            ra.approved, ra.risk_limit_exceeded = False, False
            ra.reason = (f"Remaining risk budget {budget:.2f} is below the minimum lot "
                         f"(full size {ra.calculated_lot_size} lots risks {ra.risk_amount:.2f})")
            return ra
        ratio = lot / ra.calculated_lot_size
        logger.info(f"💰 Risk budget {budget:.2f}: lot {ra.calculated_lot_size} → {lot}")
        ra.warnings.append(f"Sized to the signal's risk budget: {ra.calculated_lot_size} → {lot} lots")
        ra.calculated_lot_size = lot
        ra.risk_amount *= ratio
        ra.risk_percent *= ratio
        ra.approved, ra.risk_limit_exceeded, ra.reason = True, False, None
        return ra

    async def _apply_symbol_total_risk_cap(
        self, signal: TradingSignal, account_info: AccountInfo, ra: RiskAssessment
    ) -> RiskAssessment:
        """Ensure total open risk on this symbol does not exceed max_total_risk_per_symbol_percent."""
        import math
        cap_pct = float(getattr(settings, 'max_total_risk_per_symbol_percent', 0.0) or 0.0)
        if cap_pct <= 0 or not ra.approved or ra.calculated_lot_size <= 0:
            return ra

        max_risk_amount = account_info.balance * cap_pct / 100.0
        provider = self.trading_provider
        if not provider or not provider.is_connected:
            return ra

        # Provider-neutral reads. This used get_positions() / get_orders(), which the
        # MT5 REST provider does not have: the error was logged at debug level and the
        # cap was skipped on every signal (simulated 2026-11-12: 1.76% on a 1.5% cap).
        try:
            wanted = str(signal.symbol or "").upper()

            def same_symbol(o: dict) -> bool:        # broker names may carry a suffix (XAUUSD.fx)
                return str(o.get('symbol') or "").upper().startswith(wanted)
            positions = [p for p in await provider.get_open_positions(use_cache=False) or [] if same_symbol(p)]
            orders = [o for o in await provider.get_all_pending_orders(use_cache=False) or [] if same_symbol(o)]
        except Exception as e:
            logger.warning(f"⚠️ {signal.symbol}: symbol risk cap ({cap_pct}%) not checked — "
                           f"could not read open orders: {e}")
            return ra

        is_buy = signal.order_type == OrderType.BUY
        pip_mult = await risk_manager._get_pip_multiplier(signal.symbol)
        pip_val = await risk_manager._get_pip_value(signal.symbol)

        from src.services.signal_continuity import order_risk
        current_risk = 0.0
        for p in (positions or []):
            sl = p.get('stopLoss') or p.get('sl')
            vol = float(p.get('volume') or p.get('currentVolume') or 0.0)
            op = float(p.get('openPrice') or p.get('price') or 0.0)
            p_buy = 'BUY' in str(p.get('type', '')).upper()
            if p_buy == is_buy:
                r = order_risk(is_buy, op, sl, vol, pip_mult, pip_val)
                if r is not None:
                    current_risk += r

        for o in (orders or []):
            sl = o.get('stopLoss') or o.get('sl')
            vol = float(o.get('volume') or o.get('currentVolume') or 0.0)
            op = float(o.get('openPrice') or o.get('price') or 0.0)
            o_buy = 'BUY' in str(o.get('type', '')).upper()
            if o_buy == is_buy:
                r = order_risk(is_buy, op, sl, vol, pip_mult, pip_val)
                if r is not None:
                    current_risk += r

        remaining_risk = max(0.0, max_risk_amount - current_risk)
        if current_risk >= max_risk_amount:
            ra.approved = False
            ra.reason = f"Symbol {signal.symbol} risk cap ({cap_pct}%) reached: active risk ${current_risk:.2f} >= max ${max_risk_amount:.2f}"
            logger.warning(f"🛡️ {ra.reason}")
            ra.warnings.append(ra.reason)
            return ra

        if ra.risk_amount > remaining_risk:
            try:
                spec = await provider.get_symbol_specification(signal.symbol)
                step, vmin = spec.get('volumeStep', 0.01) or 0.01, spec.get('volumeMin', settings.min_lot_size)
            except Exception:
                step, vmin = 0.01, settings.min_lot_size
            vmin = max(vmin, settings.min_lot_size)

            scaled_lot = round(math.floor(ra.calculated_lot_size * remaining_risk / ra.risk_amount / step + 1e-9) * step, 2)
            if scaled_lot < vmin:
                ra.approved = False
                ra.reason = f"Available symbol risk (${remaining_risk:.2f}) below minimum lot size"
                logger.warning(f"🛡️ {ra.reason}")
                return ra

            ratio = scaled_lot / ra.calculated_lot_size
            logger.info(f"🛡️ Sizing down {signal.symbol} to fit symbol cap ({cap_pct}%): lot {ra.calculated_lot_size} → {scaled_lot}")
            ra.warnings.append(f"Sized to symbol risk cap ({cap_pct}%): lot {ra.calculated_lot_size} → {scaled_lot}")
            ra.calculated_lot_size = scaled_lot
            ra.risk_amount *= ratio
            ra.risk_percent *= ratio

        return ra

    def _requires_manual_approval(self, signal: TradingSignal, high_risk_override: bool = False,
                                  estimated_sizing: bool = False) -> bool:
        """Approval decision — see execution_policy for the priority order."""
        from src.services.execution_policy import approval_decision
        decision = approval_decision(signal, high_risk_override, estimated_sizing)
        logger.info(f"{'⏸️ Approval required' if decision.required else '✅ Auto-executing'}: {decision.reason}")
        return decision.required

    async def _drawdown_block_reason(self) -> Optional[str]:
        """Reason trading is paused by drawdown protection, or None when trading is allowed."""
        if not settings.enable_equity_protection:
            return None
        can_trade, dd_reason = await drawdown_protection_service.is_trading_allowed()
        if can_trade:
            logger.info("✅ Drawdown check passed")
            return None
        logger.error(f"🚫 Drawdown protection blocked trade: {dd_reason}")
        return dd_reason or "drawdown limit breached"

    async def execute_after_approval(
        self,
        signal: TradingSignal,
        risk_assessment: RiskAssessment,
        signal_id: str,
    ) -> None:
        """
        Place a signal a human just approved. Drawdown protection is re-checked first:
        the limit may have been breached while the signal sat in the queue.
        """
        if not getattr(signal, 'is_plan', False):
            dd_reason = await self._drawdown_block_reason()
            if dd_reason:
                await db_service.update_signal_status(signal_id, "REJECTED")
                await notification_sender.notify_signal_rejected(
                    signal, f"Approved, but trading is paused by drawdown protection. {dd_reason}"
                )
                return
        await self._execute_approved_trade(signal, risk_assessment, signal_id)

    async def _request_manual_approval(
        self,
        signal: TradingSignal,
        risk_assessment: RiskAssessment,
        signal_id: str,
        validation_result: Optional[SignalValidationResult] = None,
    ) -> None:
        """Queue signal for manual approval and persist AWAITING_APPROVAL status."""
        logger.info("⏸️ MANUAL APPROVAL REQUIRED")
        logger.info("   Signal will wait for /execute command")
        logger.info(f"   Timeout: {settings.approval_timeout_minutes} minutes")

        from src.services.approval_queue import approval_queue
        pending = await approval_queue.add_pending_signal(signal_id, signal, risk_assessment)

        await db_service.update_signal_status(signal_id, "AWAITING_APPROVAL")

        await notification_sender.notify_approval_request(
            signal,
            risk_assessment,
            signal_id,
            pending.get_remaining_seconds(),
            validation_result=validation_result,
        )
        logger.success(f"✅ Approval request sent (Signal ID: {signal_id[:8]}...)")

    async def _execute_approved_trade(
        self,
        signal: TradingSignal,
        risk_assessment: RiskAssessment,
        signal_id: str,
        validation_result: Optional[SignalValidationResult] = None,
    ) -> None:
        """Execute an approved trade, record in DB, and send notifications."""
        from ai.trading_brain import trading_brain

        # Approved plan signals go to the plan watcher, not direct execution
        if getattr(signal, 'is_plan', False) and getattr(signal, 'plan_data', None):
            logger.info("📋 Approved plan — forwarding to plan watcher")
            from src.services.plan_filter_service import plan_filter_service
            await plan_filter_service.validate_and_register(signal, approved=True)
            return

        if getattr(signal, 'instant_execution', False):
            logger.info("🚀 Executing instant entry (market within the deviation cap)...")
        else:
            logger.info("✅ Risk assessment passed. Executing trade...")

        if risk_assessment.warnings:
            logger.warning(f"⚠️ Risk warnings for {signal.symbol}: {' | '.join(risk_assessment.warnings)}")

        # A top-up's orders belong to the running signal. An approved top-up came
        # with a record of its own for the approval queue — drop it.
        parent_id = getattr(signal, 'continuation_of', None)
        if parent_id and signal_id != parent_id:
            try:
                await db_service.db.signal.delete(where={"id": signal_id})
            except Exception as e:
                logger.warning(f"⚠️ Could not remove the top-up's approval record {signal_id[:8]}: {e}")
            signal_id = parent_id

        # Generate magic number from message ID for tracking
        magic_number = None
        message_id = getattr(signal, 'telegram_message_id', None)
        if getattr(signal, 'magic_override', None):
            # Top-up of a running signal: share the original orders' magic so every
            # order of the setup is one group (replies, edits, deletes reach all).
            magic_number = signal.magic_override
            logger.info(f"🔢 Magic number (continuation): {magic_number}")
        elif message_id and hasattr(message_id, 'message_id'):
            magic_number = magic_number_service.generate_magic_number(message_id.message_id)
            logger.info(f"🔢 Magic number: {magic_number}")

        runner_lots = 0.0
        placed_assessment = risk_assessment      # what the TP part is placed and recorded with

        # Dry run / skip provider mode
        if settings.dry_run or settings.skip_metaapi:
            logger.info(f"🧪 DRY RUN / SKIP MODE: Simulating trade execution (lot={risk_assessment.calculated_lot_size})")
            trade_result = TradeResult(
                success=True,
                position_id="DRY_RUN_" + signal_id[:8],
                entry_price=signal.entry_price or 0.0,
            )
        elif self.trading_provider.is_connected:
            # Runner: part of the lots goes in without a TP (placed after the TP part).
            runner_lots = await self._runner_lots(signal, risk_assessment, magic_number)
            if runner_lots:
                placed_assessment = copy.copy(risk_assessment)
                placed_assessment.calculated_lot_size = round(risk_assessment.calculated_lot_size - runner_lots, 2)
            signal.lot_size = placed_assessment.calculated_lot_size or risk_assessment.calculated_lot_size
            if placed_assessment.calculated_lot_size > 0:
                trade_result = await self.trading_provider.execute_trade(signal, placed_assessment, magic_number)
            else:
                trade_result = None      # a top-up that is all runner: placed below
        else:
            logger.warning("⚠️ Trading provider not connected — signal logged only")
            trade_result = TradeResult(
                success=False,
                error_message="Trading provider not connected — signal detection only mode",
            )

        trade_ids, individual_results = [], []
        if trade_result is not None:
            individual_results = (trade_result.broker_response or {}).get('individual_results') or []
            trade_ids = await self._record_orders(signal_id, signal, placed_assessment, trade_result, magic_number)

        # Runner: the rest of the lots, same entry and SL, no TP.
        runner_note = None
        if runner_lots and (trade_result is None or trade_result.success):
            runner_ids, runner_note, runner_result = await self._place_runner(
                signal, risk_assessment, runner_lots, signal_id, magic_number, trade_result)
            trade_ids += runner_ids
            if trade_result is None:
                trade_result = runner_result
                if not runner_result.success:
                    runner_note = None           # reported as the failed trade below

        # Message mapping
        if message_id and magic_number:
            mapping_type = "CONTINUATION" if parent_id else ("NEW_SIGNAL" if trade_result.success else "FAILED_SIGNAL")
            await db_service.create_message_mapping(
                message_id=message_id,
                signal_id=parent_id or signal_id,
                trade_ids=trade_ids,
                magic_number=magic_number,
                mapping_type=mapping_type,
            )

        # Notifications and brain feedback
        if trade_result.success:
            logger.success(f"✅ Trade executed! Position: {trade_result.position_id} Magic: {magic_number}")

            # A new signal states the channel's current stop and targets: its older
            # setups in the same direction that are still running take them over.
            if not parent_id and not getattr(signal, 'manual_placement', False):
                try:
                    from src.services.signal_continuity import signal_continuity
                    await signal_continuity.carry_levels_to_older_signals(signal)
                except Exception as e:
                    logger.error(f"⚠️ Could not carry the new levels to the channel's older setups: {e}")

            if message_id:
                trade_mapper.register_trade(
                    message_id=message_id,
                    symbol=signal.symbol,
                    position_id=trade_result.position_id,
                    order_id=trade_result.order_id,
                )

            await notification_sender.notify_trade_executed(
                signal, risk_assessment, trade_result, validation_result=validation_result
            )
            # Some orders of a multi-TP / scale-in set were rejected: the position is
            # smaller than planned (or a TP level is missing) — say so.
            failed_orders = [str(r.get('error')) for r in individual_results
                             if isinstance(r, dict) and r.get('error')]
            if failed_orders:
                log_partial_failure(failed_orders, f"{signal.symbol} order placement")
                await notification_sender.send_message(
                    f"⚠️ <b>{signal.symbol}</b>: only {len(individual_results) - len(failed_orders)} of "
                    f"{len(individual_results)} orders were placed{failure_block(failed_orders)}",
                    category='position_management',
                )
            if runner_note:
                await notification_sender.send_message(
                    f"<b>{signal.symbol}</b> {runner_note}", category='position_management')
            if getattr(signal, 'temp_stop_loss', False):
                from src.services.signal_continuity import signal_continuity
                signal_continuity.mark_awaiting_levels(signal_id, signal.symbol)
                await notification_sender.send_message(
                    f"🛡️ <b>{signal.symbol}</b> entered on a temporary SL {signal.stop_loss}. "
                    f"The follow-up message with the real SL/TP will update it and add the rest "
                    f"within the remaining risk.",
                    category='position_management',
                )
            trading_brain.notify_trade_executed(signal, trade_result)

            try:
                from src.services.signal_forwarder_service import signal_forwarder_service
                signal.signal_id = signal_id
                await signal_forwarder_service.forward_signal(signal, risk_assessment, trade_result)
            except Exception as _fwd_err:
                logger.debug(f"Signal forwarder skipped: {_fwd_err}")
        else:
            logger.error(f"❌ Trade execution failed: {trade_result.error_message}")
            await notification_sender.notify_trade_failed(signal, trade_result.error_message)
            trading_brain.notify_trade_rejected(signal, f"Execution failed: {trade_result.error_message}")

    async def _record_orders(self, signal_id: str, signal: TradingSignal, risk_assessment: RiskAssessment,
                             trade_result: TradeResult, magic_number: Optional[int],
                             runner: bool = False) -> list:
        """One trade row per order the provider placed; returns the trade ids."""
        # Multi-order recording — one DB row per placed order. Driven by the broker's
        # individual_results so it correctly covers BOTH multi-TP and multi-entry
        # (scale-in) trades, including a multi-entry signal with a single TP.
        broker_resp = trade_result.broker_response or {}
        individual_results = broker_resp.get('individual_results') or []
        is_multi_order = bool(individual_results)

        trade_ids = []

        async def mark_runner(trade_id: str) -> None:
            # No TP on purpose: the monitor's auto take profit must not add one.
            if runner:
                await db_service.update_trade_field(trade_id, 'autoTpEnabled', False)

        if is_multi_order:
            order_count = len(individual_results)
            for i, res_i in enumerate(individual_results):
                # Each order carries its own leg/TP tags from the provider (default to
                # leg 1 / positional TP for legacy multi-TP results without tags).
                tp_level = None if runner else res_i.get('tpLevel', i + 1)
                entry_leg = res_i.get('entryLeg', 1)
                leg_entry_price = res_i.get('entryPrice')
                order_failed = 'error' in res_i
                position_id = None if order_failed else res_i.get('positionId')

                trade_id = await db_service.create_trade(
                    signal_id=signal_id,
                    signal=signal,
                    risk_assessment=risk_assessment,
                    is_multi_tp=True,
                    tp_level=tp_level,
                    entry_leg=entry_leg,
                    magic_number=magic_number,
                )
                await mark_runner(trade_id)

                if position_id:
                    await db_service.update_trade_field(trade_id, 'positionId', position_id)
                # create_trade stores the signal's total lots on every row; a pending
                # order kept that until it filled (sync corrects positions only).
                if res_i.get('lotSize'):
                    await db_service.update_trade_field(trade_id, 'lotSize', res_i['lotSize'])

                if order_failed:
                    order_result = TradeResult(success=False, error_message=res_i['error'])
                    await db_service.update_trade_execution(trade_id, order_result)
                else:
                    order_result = TradeResult(
                        success=True,
                        position_id=res_i.get('positionId'),
                        order_id=res_i.get('orderId'),
                        entry_price=leg_entry_price or trade_result.entry_price,
                        broker_response=res_i,
                    )
                    await db_service.update_trade_execution(trade_id, order_result)

                trade_ids.append(trade_id)

                if magic_number and position_id:
                    magic_number_service.register_order(
                        magic_number, position_id=position_id, order_id=None, symbol=signal.symbol
                    )

            success_count = broker_resp.get('success_count', 0)
            legs = signal.discrete_entry_prices() if hasattr(signal, 'discrete_entry_prices') else None
            kind = f"{len(legs)}-leg scale-in" if legs else "multi-TP"
            logger.info(f"📝 {order_count} {kind} trade records created ({success_count}/{order_count} successful, magic={magic_number})")
            await db_service.update_signal_status_from_trades(signal_id)

        else:
            trade_id = await db_service.create_trade(
                signal_id=signal_id,
                signal=signal,
                risk_assessment=risk_assessment,
                magic_number=magic_number,
            )
            await mark_runner(trade_id)
            await db_service.update_trade_execution(trade_id, trade_result)
            trade_ids.append(trade_id)
            await db_service.update_signal_status_from_trades(signal_id)

            if magic_number and trade_result.success:
                magic_number_service.register_order(
                    magic_number,
                    position_id=trade_result.position_id,
                    order_id=trade_result.order_id,
                    symbol=signal.symbol,
                )
            logger.info(f"📝 Trade logged (ID: {trade_id[:8]}..., Success: {trade_result.success})")
        return trade_ids

    @staticmethod
    def runner_split(total_lots: float, share_percent: float, step: float, volume_min: float,
                     placed_tp: float = 0.0, placed_runner: float = 0.0) -> float:
        """
        Lots of these orders placed without a TP, in whole volume steps.

        A new signal: the share of its lots; 0 when either part would fall below the
        broker minimum — too small to split, all lots stay on the TPs.

        A top-up of a running setup (placed_tp / placed_runner = what it already
        holds): the share is measured over the whole setup. An instant entry is one
        position on a TP and often most of the risk, so the added orders carry the
        runner — all of them when the setup's share is larger than they are.
        """
        step, volume_min = step or 0.01, volume_min or 0.01
        share = min(max(float(share_percent or 0), 0.0), 100.0) / 100.0
        setup = total_lots + placed_tp + placed_runner
        target = math.floor(setup * share / step + 1e-9) * step - placed_runner
        runner = round(min(max(target, 0.0), total_lots), 2)
        rest = round(total_lots - runner, 2)
        if 0 < rest < volume_min - 1e-9:
            # what is left for the TPs cannot be placed: give it to the side that can take it
            runner = round(total_lots, 2) if placed_tp > 0 else 0.0
            rest = round(total_lots - runner, 2)
        if runner < volume_min - 1e-9 or (rest <= 0 and placed_tp <= 0):
            return 0.0
        return runner

    async def _runner_lots(self, signal: TradingSignal, risk_assessment: RiskAssessment,
                           magic_number: Optional[int]) -> float:
        """Lots of this signal that go in as a runner (0 = none). See ENABLE_RUNNER_SPLIT."""
        if not getattr(settings, 'enable_runner_split', False) or not magic_number:
            return 0.0
        if not signal.stop_loss or not [t for t in (signal.take_profit or []) if t]:
            return 0.0
        if getattr(signal, 'temp_stop_loss', False):
            return 0.0      # one position on guessed levels; the follow-up's orders are split
        if settings.copy_master_mode:
            return 0.0      # orders wait for the master's fill — nothing to take the TP off
        try:
            spec = await self.trading_provider.get_symbol_specification(signal.symbol)
            step, vmin = spec.get('volumeStep', 0.01) or 0.01, spec.get('volumeMin', 0.01) or 0.01
        except Exception:
            step, vmin = 0.01, 0.01
        vmin = max(vmin, settings.min_lot_size)
        placed_tp, placed_runner = getattr(signal, 'runner_setup', None) or (0.0, 0.0)
        lots = self.runner_split(risk_assessment.calculated_lot_size,
                                 getattr(settings, 'runner_share_percent', 50.0), step, vmin,
                                 placed_tp, placed_runner)
        if lots:
            logger.info(f"🏃 Runner: {lots} of {risk_assessment.calculated_lot_size} lots go in without TP")
        else:
            logger.info(f"🏃 Runner: {risk_assessment.calculated_lot_size} lots are too small to split — all on the TPs")
        return lots

    @staticmethod
    def _tickets(result: Optional[TradeResult]) -> set:
        """Broker tickets of the orders one execute_trade call placed."""
        if result is None:
            return set()
        placed = (result.broker_response or {}).get('individual_results') or [
            {'positionId': result.position_id, 'orderId': result.order_id}]
        return {str(r.get(k)) for r in placed if isinstance(r, dict) and not r.get('error')
                for k in ('positionId', 'orderId') if r.get(k)}

    async def _place_runner(self, signal: TradingSignal, risk_assessment: RiskAssessment, runner_lots: float,
                            signal_id: str, magic_number: int, tp_part: Optional[TradeResult] = None) -> tuple:
        """
        Place the runner part of a signal: same entry and SL, no take profit.
        It goes through the provider like any order — with the furthest TP, which is
        taken off right after — so entry handling (limit / market / scale-in legs) is
        the same as for the TP part, and a runner whose TP could not be removed is
        still protected by that TP. Returns (trade ids, note for the owner, result).
        """
        from src.services.signal_continuity import signal_continuity, clone_signal
        is_buy = signal.order_type == OrderType.BUY
        furthest = (max if is_buy else min)(t for t in signal.take_profit if t)
        runner = clone_signal(signal, take_profit=[furthest], take_profit_levels=[furthest])
        assessment = copy.copy(risk_assessment)
        assessment.calculated_lot_size = runner_lots
        runner.lot_size = runner_lots
        # An instant ("NOW") signal: the runner enters the way the TP orders did. With
        # only the furthest TP it would pass the chase checks they failed and go in at
        # market while they wait as limits (simulated 2026-11-12).
        tp_tickets = self._tickets(tp_part)
        if tp_tickets and getattr(runner, 'instant_execution', False):
            placed = [o for o in await signal_continuity._live_orders({magic_number}, is_buy)
                      if str(o['id']) in tp_tickets]
            if not placed or any(o['pending'] for o in placed):
                runner.instant_execution = False
        try:
            result = await self.trading_provider.execute_trade(runner, assessment, magic_number)
        except Exception as e:
            result = TradeResult(success=False, error_message=str(e))
        if not result.success:
            logger.error(f"🏃 Runner for {signal.symbol} not placed: {result.error_message}")
            return [], f"⚠️ runner ({runner_lots} lots without TP) was not placed: {result.error_message}", result

        trade_ids = await self._record_orders(
            signal_id, clone_signal(runner, take_profit=[], take_profit_levels=[]), assessment, result,
            magic_number, runner=True)

        tickets = self._tickets(result)
        cleared, failed = 0, []
        for attempt in range(3):
            live = [o for o in await signal_continuity._live_orders({magic_number}, is_buy)
                    if str(o['id']) in tickets]
            if live or attempt == 2:
                break
            await asyncio.sleep(1.0)        # the terminal has not reported the new orders yet
        for o in live:
            try:
                await self.trading_provider.remove_take_profit(
                    o['id'], o.get('stopLoss') or runner.stop_loss, pending=o['pending'], price=o['openPrice'])
                cleared += 1
            except Exception as e:
                failed.append(str(e))
                logger.error(f"🏃 Runner {o['id']}: could not remove its TP: {e}")
        if cleared and not failed:
            return trade_ids, (f"🏃 runner: {runner_lots} lots without TP, SL {runner.stop_loss} — "
                               f"closed by the SL or the channel's messages"), result
        return trade_ids, (f"⚠️ runner ({runner_lots} lots): its TP could not be removed on "
                           f"{len(tickets) - cleared} order(s) — they keep TP {furthest}. Remove it by hand."), result

    async def _assess_risk(self, signal: TradingSignal) -> RiskAssessment:
        """Fetch account info and run risk assessment for a single signal.

        Used by the plan watcher to size a plan leg before execution.
        """
        account_info = await self._get_account_info()
        return await risk_manager.assess_risk(signal, account_info)

    async def _execute(
        self,
        signal: TradingSignal,
        risk_assessment: RiskAssessment,
        magic_number: Optional[int] = None,
    ) -> SimpleNamespace:
        """Execute a trade leg (used by the plan watcher) and record it in the DB.

        Returns a lightweight result exposing ``.success`` and ``.trade_id`` (the
        created trade record). Caller handles user-facing notifications.
        """
        signal_id = signal.signal_id

        # Dry run / skip provider mode
        if settings.dry_run or settings.skip_metaapi:
            logger.info(
                f"🧪 DRY RUN / SKIP MODE: Simulating plan execution (lot={risk_assessment.calculated_lot_size})"
            )
            trade_result = TradeResult(
                success=True,
                position_id="DRY_RUN_" + (signal_id or "PLAN")[:8],
                entry_price=signal.entry_price or 0.0,
            )
        elif self.trading_provider.is_connected:
            signal.lot_size = risk_assessment.calculated_lot_size
            trade_result = await self.trading_provider.execute_trade(signal, risk_assessment, magic_number)
        else:
            logger.warning("⚠️ Trading provider not connected — plan leg not executed")
            trade_result = TradeResult(
                success=False,
                error_message="Trading provider not connected",
            )

        trade_id = await db_service.create_trade(
            signal_id=signal_id,
            signal=signal,
            risk_assessment=risk_assessment,
            magic_number=magic_number,
        )
        await db_service.update_trade_execution(trade_id, trade_result)
        await db_service.update_signal_status_from_trades(signal_id)

        if magic_number and trade_result.success:
            magic_number_service.register_order(
                magic_number,
                position_id=trade_result.position_id,
                order_id=trade_result.order_id,
                symbol=signal.symbol,
            )

        logger.info(f"📝 Plan trade logged (ID: {trade_id[:8]}..., Success: {trade_result.success})")

        return SimpleNamespace(success=trade_result.success, trade_id=trade_id, trade_result=trade_result)

    async def _handle_rejected_signal(self, signal: TradingSignal, risk_assessment: RiskAssessment) -> None:
        """Handle a risk-rejected signal — create mapping and notify."""
        logger.warning(f"❌ Signal rejected: {risk_assessment.reason}")

        message_id = getattr(signal, 'telegram_message_id', None)
        if message_id and not getattr(signal, 'continuation_of', None):
            try:
                signal_record = await db_service.find_signal_by_message(message_id)
                if signal_record:
                    await db_service.create_message_mapping(
                        message_id=message_id,
                        signal_id=signal_record.id,
                        trade_ids=[],
                        magic_number=None,
                        mapping_type="REJECTED_SIGNAL",
                    )
            except Exception as e:
                logger.debug(f"Could not create mapping for rejected signal: {e}")

        await notification_sender.notify_signal_rejected(signal, risk_assessment.reason)

    # ── Utility helpers ──────────────────────────────────────────────────────

    def _validate_message_age(self, signal: TradingSignal) -> tuple[bool, Optional[str]]:
        """Return (True, None) if signal age is acceptable, (False, reason) otherwise."""
        if not getattr(signal, 'timestamp', None):
            logger.warning("⚠️ Signal has no timestamp — skipping age validation")
            return True, None

        signal_time = signal.timestamp
        if signal_time.tzinfo is None:
            signal_time = signal_time.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        age = now - signal_time
        max_age = timedelta(minutes=settings.max_signal_age_minutes)
        age_minutes = age.total_seconds() / 60

        if age > max_age:
            reason = (
                f"Signal is too old: {age_minutes:.1f} min "
                f"(max: {settings.max_signal_age_minutes} min)"
            )
            logger.error(f"🚫 {reason} | signal_time={signal_time} now={now}")
            return False, reason

        logger.info(f"✅ Signal age OK: {age_minutes:.1f} min old")
        return True, None

    def _create_dummy_message_id(self, signal: TradingSignal) -> MessageIdentifier:
        """Create a fallback MessageIdentifier for signals without Telegram context."""
        return MessageIdentifier(
            chat_id=getattr(signal, 'channel_id', 'unknown') or 'unknown',
            message_id=getattr(signal, 'message_id', 0) or 0,
            message_hash=str(hash(getattr(signal, 'raw_message', '') or '')),
            timestamp=datetime.now(timezone.utc),
        )

    @staticmethod
    def _rejection_assessment(reason: str, warnings: list) -> RiskAssessment:
        """Build a zero-value RiskAssessment for recording early rejections."""
        return RiskAssessment(
            approved=False,
            calculated_lot_size=0.0,
            risk_percent=0.0,
            risk_amount=0.0,
            stop_loss_pips=0.0,
            take_profit_pips=0.0,
            risk_reward_ratio=0.0,
            reason=reason,
            warnings=warnings,
        )


# Singleton instance
trading_service = TradingService()
