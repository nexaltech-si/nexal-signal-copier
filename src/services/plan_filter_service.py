"""
Plan Filter Service
Validates a plan signal before it enters the watcher.
Three sequential gates: duplicate guard → market hours → lot size feasibility.
A failure at any gate sets status=FILTERED and notifies the user.
"""
import base64
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Tuple

from config.settings import settings
from src.models.signal import TradingSignal
from src.services.market_hours_service import market_hours_service

logger = logging.getLogger(__name__)


class PlanFilterService:

    async def request_plan_approval(self, signal: TradingSignal) -> None:
        """
        Queue a plan signal for manual approval before registering to the watcher.
        Called when approval is required (global switch, per-channel, or image-approval setting).
        On approval, trading_service._execute_approved_trade() detects is_plan and routes here.
        """
        from src.services.approval_queue import approval_queue
        from src.integrations.telegram.unified_sender import notification_sender
        from src.models.trade import RiskAssessment

        dummy_risk = RiskAssessment(
            approved=True,
            calculated_lot_size=0.0,
            risk_percent=0.0,
            risk_amount=0.0,
            stop_loss_pips=0.0,
            take_profit_pips=0.0,
            risk_reward_ratio=0.0,
            warnings=["📋 Plan signal — lot size calculated when entry zone is triggered"],
        )

        signal_id = await approval_queue.add_signal(signal, dummy_risk)
        await notification_sender.notify_approval_request(
            signal, dummy_risk, signal_id,
            settings.approval_timeout_minutes * 60,
        )
        logger.info(f"⏸️ Plan signal queued for approval: {signal_id}")

    async def validate_and_register(self, signal: TradingSignal, approved: bool = False) -> None:
        """
        Entry point called as an asyncio background task from signal_service.
        Saves the Signal record, runs all filter gates, and — on pass —
        creates the TradePlan row and hands off to the watcher.

        approved=True when a human already approved this plan in the approval queue.
        """
        from src.core.database_service import db_service
        from src.integrations.telegram.unified_sender import notification_sender
        from src.services.plan_watcher_service import plan_watcher_service

        plan_raw = signal.plan_data or {}
        primary = plan_raw.get("primary", {})
        fallback = plan_raw.get("fallback")

        symbol = signal.symbol or ""
        order_type = signal.order_type.value if signal.order_type else "BUY"
        # Use "or 0" rather than .get(key, 0) — the key is often present with an
        # explicit None value (e.g. no SL on a plan), and .get()'s default only
        # applies when the key is missing entirely.
        entry_min = float(primary.get("entry_min") or 0)
        entry_max = float(primary.get("entry_max") or 0)
        primary_sl = float(primary.get("stop_loss") or 0)
        primary_tps = json.dumps(primary.get("take_profits", []))
        primary_sl_condition = primary.get("sl_condition")

        # Gate 1: Duplicate guard — use channelId+messageId (signal_id may be None)
        try:
            existing_signal = await db_service.db.signal.find_first(
                where={
                    "channelId": str(signal.channel_id or ""),
                    "messageId": signal.message_id or 0,
                    "isPlan": True,
                },
                include={"tradePlan": True},
            )
            if existing_signal and getattr(existing_signal, "tradePlan", None):
                logger.info(
                    f"📋 Plan duplicate — already registered for "
                    f"message {signal.channel_id}:{signal.message_id}"
                )
                return
        except Exception as e:
            logger.error(f"Plan duplicate check error: {e}")

        # Always save the Signal record with isPlan=true for history/audit
        signal_db_id = await self._save_plan_signal(signal, db_service)
        if not signal_db_id:
            logger.error("Failed to save plan signal to DB — aborting plan registration")
            return

        # Gate 2: Market hours
        _gap_block = settings.plan_gap_risk_block
        _gap_block = _gap_block if isinstance(_gap_block, bool) else str(_gap_block).lower() in ('true', '1', 'yes')
        if _gap_block:
            if not market_hours_service.is_market_open(symbol):
                await self._filter(
                    signal_db_id, "market_closed_gap_risk",
                    f"⚠️ Plan for {symbol} rejected — market is closed (gap risk). Re-send when market opens.",
                    notification_sender, db_service,
                )
                return

            # Check if price has already blown past the zone (skip when zone is unknown)
            ok, current_price = await self._get_current_price(symbol)
            if ok and entry_min > 0 and entry_max > 0 and market_hours_service.price_already_past_zone(
                current_price, order_type, entry_min, entry_max
            ):
                await self._filter(
                    signal_db_id, "price_already_past_entry",
                    f"⚠️ Plan for {symbol} rejected — price ({current_price}) already past entry zone "
                    f"{entry_min}–{entry_max}.",
                    notification_sender, db_service,
                )
                return

        # Gate 3: Lot size feasibility — skip when no SL is available
        if primary_sl > 0:
            lot_ok, lot_reason = await self._check_lot_feasibility(
                symbol, entry_min, entry_max, primary_sl
            )
            if not lot_ok:
                await self._filter(
                    signal_db_id, f"invalid_lot_size: {lot_reason}",
                    f"⚠️ Plan for {symbol} rejected — {lot_reason}.",
                    notification_sender, db_service,
                )
                return

        # All gates passed — create TradePlan row
        expires_at = datetime.now(timezone.utc) + timedelta(hours=int(settings.plan_expiry_hours))

        fallback_data: dict = {}
        if fallback:
            fallback_ot = str(fallback.get("order_type", order_type)).upper()
            if fallback_ot not in ("BUY", "SELL"):
                fallback_ot = order_type
            fallback_data = {
                "fallbackOrderType": fallback_ot,
                "fallbackEntryMin": float(fallback.get("entry_min") or 0),
                "fallbackEntryMax": float(fallback.get("entry_max") or 0),
                "fallbackSl": float(fallback.get("stop_loss") or 0),
                "fallbackTps": json.dumps(fallback.get("take_profits", [])),
            }

        # Plans without SL must never auto-execute — the trader must add SL before approving.
        # Plans use the same approval rules as direct signals (execution_policy), but
        # instead of the 15-minute queue they wait for a manual trigger on the dashboard.
        has_sl = primary_sl > 0
        _raw = settings.plan_auto_execute
        _auto_bool = _raw if isinstance(_raw, bool) else str(_raw).lower() in ('true', '1', 'yes')
        manual_reason = None
        if not approved:
            from src.services.execution_policy import approval_decision
            decision = approval_decision(signal)
            if decision.required:
                manual_reason = decision.reason
                logger.info(f"⏸️ Plan {symbol} needs a manual trigger: {manual_reason}")
        auto_execute = bool(_auto_bool) and has_sl and manual_reason is None

        try:
            plan = await db_service.db.tradeplan.create(
                data={
                    "signalId": signal_db_id,
                    "symbol": symbol,
                    "orderType": order_type,
                    "primaryEntryMin": entry_min,
                    "primaryEntryMax": entry_max,
                    "primarySl": primary_sl,
                    "primarySlCondition": primary_sl_condition,
                    "primaryTps": primary_tps,
                    "status": "WATCHING",
                    "autoExecute": auto_execute,
                    "expiresAt": expires_at,
                    **fallback_data,
                }
            )

            fallback_info = (
                f" | Fallback: {fallback_data.get('fallbackEntryMin')}–{fallback_data.get('fallbackEntryMax')}"
                if fallback_data else ""
            )
            sl_warning = " | ⚠️ NO SL — manual approval required before execution" if not has_sl else ""
            if has_sl and manual_reason:
                sl_warning = f" | ⏸️ Manual trigger required — {manual_reason}"
            # One level, not a zone ("if price breaks above 3960 we buy"): price passes a
            # single level between two checks, so the watcher will not enter it by itself.
            if entry_min == entry_max:
                sl_warning += (f" | ℹ️ Breakout level {entry_min}, not a zone — kept as a plan; "
                               f"execute it by hand when the level breaks")
            await notification_sender.send_message(
                f"📋 Plan registered: {symbol} {order_type} "
                f"| Watching {entry_min}–{entry_max}"
                f"{fallback_info}"
                f"{sl_warning} "
                f"| Expires {settings.plan_expiry_hours}h",
                category='trade_plans'
            )

            await plan_watcher_service.add_plan(plan)
            logger.info(f"✅ Trade plan registered: {plan.id} for {symbol} {order_type}")

        except Exception as e:
            logger.error(f"Failed to create TradePlan in DB: {e}", exc_info=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _save_plan_signal(self, signal: TradingSignal, db_service) -> str | None:
        """Persist the Signal with isPlan=true. Returns the DB signal id."""
        import json as _json
        try:
            import hashlib
            msg_hash = hashlib.md5(
                f"{signal.channel_id}:{signal.message_id}".encode()
            , usedforsecurity=False).hexdigest()

            record = await db_service.db.signal.upsert(
                where={"channelId_messageId": {
                    "channelId": str(signal.channel_id or ""),
                    "messageId": signal.message_id or 0,
                }},
                data={
                    "create": {
                        "action": signal.action.value if signal.action else "OPEN",
                        "orderType": signal.order_type.value if signal.order_type else "BUY",
                        "symbol": signal.symbol or "",
                        "entryPrice": signal.entry_price,
                        "stopLoss": signal.stop_loss,
                        "takeProfit": _json.dumps(signal.take_profit or []),
                        "confidence": signal.confidence,
                        "channelId": str(signal.channel_id or ""),
                        "channelName": signal.channel_name,
                        "messageId": signal.message_id or 0,
                        "rawMessage": signal.raw_message or "",
                        "messageHash": msg_hash,
                        "imageData": (
                            base64.b64encode(signal.image_data).decode("utf-8")
                            if isinstance(signal.image_data, bytes) else signal.image_data
                        ),
                        "status": "VALIDATED",
                        "isPlan": True,
                        "planData": _json.dumps(signal.plan_data or {}),
                    },
                    "update": {
                        "symbol": signal.symbol or "",
                        "isPlan": True,
                        "planData": _json.dumps(signal.plan_data or {}),
                    },
                },
            )
            return record.id
        except Exception as e:
            logger.error(f"Error saving plan signal: {e}", exc_info=True)
            return None

    async def _get_current_price(self, symbol: str) -> Tuple[bool, float]:
        try:
            from src.services.trading_service import trading_service
            provider = trading_service.trading_provider
            price_data = await provider.get_current_price(symbol)
            price = float(price_data) if price_data else 0.0
            return (price > 0, price)
        except Exception as e:
            logger.warning(f"Could not fetch current price for {symbol}: {e}")
            return False, 0.0

    async def _check_lot_feasibility(
        self, symbol: str, entry_min: float, entry_max: float, sl: float
    ) -> Tuple[bool, str]:
        try:
            from src.services.trading_service import trading_service
            from ai.position_sizer import position_sizer

            provider = trading_service.trading_provider
            account = await provider.get_account_info()
            equity = account.equity if account else 10_000.0

            entry_mid = (entry_min + entry_max) / 2
            sl_distance = abs(entry_mid - sl)
            if sl_distance == 0:
                return False, "SL distance is zero — cannot calculate lot size"

            # Use the existing position sizer with a minimal signal dict
            result = await position_sizer.calculate_optimal_lot_size(
                signal={"entry_price": entry_mid, "stop_loss": sl, "symbol": symbol},
                market_analysis={},
                account_equity=equity,
            )
            lot = result.get("lot_size", 0)

            spec = await provider.get_symbol_specification(symbol)
            vol_min = spec.get("volumeMin", 0.01)
            vol_max = spec.get("volumeMax", 100.0)

            if lot < vol_min:
                return False, f"calculated lot {lot:.3f} is below broker minimum {vol_min}"
            if lot > vol_max:
                return False, f"calculated lot {lot:.3f} exceeds broker maximum {vol_max}"

            return True, ""
        except Exception as e:
            logger.warning(f"Lot feasibility check failed for {symbol}: {e}")
            # Soft-fail: allow the plan through if we can't check
            return True, ""

    async def _filter(
        self,
        signal_db_id: str,
        reason: str,
        user_message: str,
        notification_sender,
        db_service,
    ) -> None:
        logger.info(f"📋 Plan filtered: {reason}")
        try:
            await db_service.db.tradeplan.upsert(
                where={"signalId": signal_db_id},
                data={
                    "create": {
                        "signalId": signal_db_id,
                        "symbol": "",
                        "orderType": "BUY",
                        "primaryEntryMin": 0,
                        "primaryEntryMax": 0,
                        "primarySl": 0,
                        "primaryTps": "[]",
                        "status": "FILTERED",
                        "filterReason": reason,
                        "expiresAt": datetime.now(timezone.utc),
                    },
                    "update": {
                        "status": "FILTERED",
                        "filterReason": reason,
                    },
                },
            )
        except Exception as e:
            logger.error(f"Failed to save FILTERED plan: {e}")
        try:
            await notification_sender.send_message(user_message, category='signal_rejected')
        except Exception as _exc:
            logger.debug(f"Suppressed exception: {_exc!r}")


plan_filter_service = PlanFilterService()
