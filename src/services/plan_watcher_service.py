"""
Plan Watcher Service
Monitors active TradePlans and triggers trade execution when price enters an
entry zone (auto-execute) or when the dashboard requests manual execution.

Called via plan_watcher_service.tick() inside the position monitor loop every
3 seconds. Fully isolated — any exception is caught internally so the position
monitor is never affected.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from config.settings import settings
from src.services.market_hours_service import market_hours_service

logger = logging.getLogger(__name__)


class PlanWatcherService:

    def __init__(self):
        # In-memory cache: plan_id → plan DB object
        self._active_plans: Dict[str, object] = {}

    # ------------------------------------------------------------------
    # Startup / teardown
    # ------------------------------------------------------------------

    async def startup_load(self) -> None:
        """Load all in-flight plans from DB on bot start/restart."""
        try:
            from src.core.database_service import db_service
            plans = await db_service.db.tradeplan.find_many(
                where={"status": {"in": ["WATCHING", "PRIMARY_ACTIVE", "FALLBACK_WATCHING"]}},
                include={"signal": True},
            )
            self._active_plans = {p.id: p for p in plans}
            logger.info(f"📋 Plan watcher: resumed {len(plans)} active plan(s) from DB")
        except Exception as e:
            logger.error(f"PlanWatcher startup_load error: {e}", exc_info=True)

    async def add_plan(self, plan) -> None:
        """Register a newly created plan into the in-memory cache."""
        self._active_plans[plan.id] = plan

    def remove_plan(self, plan_id: str) -> None:
        self._active_plans.pop(plan_id, None)

    # ------------------------------------------------------------------
    # Main tick — called from position_monitor_service every 3s
    # ------------------------------------------------------------------

    async def tick(self) -> None:
        """Process all active plans. Never raises — exceptions are caught."""
        if not settings.plan_watcher_enabled:
            return
        if not self._active_plans:
            return

        for plan_id, plan in list(self._active_plans.items()):
            try:
                await self._process_plan(plan)
            except Exception as e:
                logger.error(f"PlanWatcher error for plan {plan_id}: {e}", exc_info=True)

    # ------------------------------------------------------------------
    # Per-plan state machine
    # ------------------------------------------------------------------

    async def _process_plan(self, plan) -> None:
        from src.core.database_service import db_service

        # Reload fresh state from DB (catches manual execute requests etc.)
        fresh = await db_service.db.tradeplan.find_unique(
            where={"id": plan.id},
            include={"signal": True},
        )
        if not fresh or fresh.status not in ("WATCHING", "PRIMARY_ACTIVE", "FALLBACK_WATCHING"):
            self.remove_plan(plan.id)
            return

        # 1. Manual execute request from dashboard (highest priority)
        if fresh.manualExecuteRequested and fresh.manualExecuteLeg:
            await self._execute_leg(fresh, fresh.manualExecuteLeg)
            await db_service.db.tradeplan.update(
                where={"id": plan.id},
                data={"manualExecuteRequested": False, "manualExecuteLeg": None},
            )
            return

        # 2. Expiry check
        expires = fresh.expiresAt
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires:
            await self._expire_plan(fresh)
            return

        # 3. Skip zone check when market is closed — don't expire, just wait
        if not market_hours_service.is_market_open(fresh.symbol):
            return

        # 4. State machine
        if fresh.status == "WATCHING":
            await self._check_primary_zone(fresh)
        elif fresh.status == "PRIMARY_ACTIVE":
            await self._check_primary_stopped_out(fresh)  # triggers FALLBACK_WATCHING if SL hit
        elif fresh.status == "FALLBACK_WATCHING":
            await self._check_fallback_zone(fresh)

        # Refresh in-memory cache entry
        self._active_plans[plan.id] = fresh

    # ------------------------------------------------------------------
    # Zone checks
    # ------------------------------------------------------------------

    async def _check_primary_zone(self, plan) -> None:
        # Never auto-execute without a stop loss — SL is required for risk management
        if not plan.primarySl or plan.primarySl == 0:
            return  # No SL — requires manual approval with SL set

        # plan.autoExecute already IS settings.plan_auto_execute's value, baked in by
        # plan_filter_service.validate_and_register() at creation time — it is the
        # per-plan override the schema/settings comments describe, not an independent
        # flag. ORing the *live* global setting back in here was the bug: a plan
        # created while the global toggle was off (autoExecute=False, "wait for
        # manual") would silently start auto-firing the moment someone later flipped
        # the global toggle on, even though this specific plan was never re-approved.
        if not plan.autoExecute:
            return  # Wait for manual Execute button

        price = await self._get_price(plan.symbol, plan.orderType)
        if price is None:
            return

        in_zone = plan.primaryEntryMin <= price <= plan.primaryEntryMax
        if in_zone:
            logger.info(
                f"📋 Plan {plan.id}: price {price} entered primary zone "
                f"{plan.primaryEntryMin}–{plan.primaryEntryMax} — executing"
            )
            await self._execute_leg(plan, "primary")

    async def _check_fallback_zone(self, plan) -> None:
        if not plan.fallbackEntryMin or not plan.fallbackEntryMax:
            return

        # Never auto-execute without a stop loss
        fallback_sl = getattr(plan, 'fallbackSl', None) or 0
        if not fallback_sl:
            return  # No fallback SL — requires manual approval

        # See the matching comment in _check_primary_zone — same fix, same reason.
        if not plan.autoExecute:
            return

        price = await self._get_price(plan.symbol, plan.orderType)
        if price is None:
            return

        in_zone = plan.fallbackEntryMin <= price <= plan.fallbackEntryMax
        if in_zone:
            logger.info(
                f"📋 Plan {plan.id}: price {price} entered fallback zone "
                f"{plan.fallbackEntryMin}–{plan.fallbackEntryMax} — executing"
            )
            await self._execute_leg(plan, "fallback")

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def _execute_leg(self, plan, leg: str) -> None:
        """Build a TradingSignal from the plan leg and push it through trading_service._execute()."""
        from src.core.database_service import db_service
        from src.integrations.telegram.unified_sender import notification_sender
        from src.models.signal import TradingSignal
        from src.models.enums import SignalAction, OrderType, SignalStatus
        from src.services.trading_service import trading_service
        from src.services.magic_number_service import magic_number_service

        is_primary = leg == "primary"
        entry_min = plan.primaryEntryMin if is_primary else (plan.fallbackEntryMin or 0)
        entry_max = plan.primaryEntryMax if is_primary else (plan.fallbackEntryMax or 0)
        sl = plan.primarySl if is_primary else (plan.fallbackSl or 0)
        tps_raw = plan.primaryTps if is_primary else (plan.fallbackTps or "[]")

        # Hard safety net: refuse execution without SL regardless of how we got here
        if not sl or sl == 0:
            logger.warning(
                f"❌ Plan {plan.id}: {leg} leg has no SL — auto-execution blocked. "
                "Set a stop loss before executing this plan."
            )
            return

        try:
            tps = json.loads(tps_raw)
        except Exception:
            tps = []

        # Use fallbackOrderType when executing fallback leg (may differ from primary direction)
        if is_primary:
            ot_str = plan.orderType.upper()
        else:
            ot_str = (getattr(plan, 'fallbackOrderType', None) or plan.orderType).upper()
        order_type = OrderType.BUY if ot_str == "BUY" else OrderType.SELL

        signal = TradingSignal(
            symbol=plan.symbol,
            action=SignalAction.OPEN,
            order_type=order_type,
            entry_price=(entry_min + entry_max) / 2,
            entry_range_min=entry_min,
            entry_range_max=entry_max,
            stop_loss=sl,
            take_profit=tps,
            channel_id=plan.signal.channelId if plan.signal else "",
            channel_name=plan.signal.channelName if plan.signal else None,
            message_id=plan.signal.messageId if plan.signal else 0,
            raw_message=plan.signal.rawMessage if plan.signal else "",
            signal_id=plan.signalId,
            status=SignalStatus.VALIDATED,
            confidence=1.0,
        )

        try:
            magic = magic_number_service.generate_magic_number(signal.message_id)
            risk_assessment = await trading_service._assess_risk(signal)
            result = await trading_service._execute(signal, risk_assessment, magic)

            trade_id = result.trade_id if result and result.success else None
            new_status = "PRIMARY_ACTIVE" if is_primary else "FALLBACK_ACTIVE"
            update_data = {"status": new_status}
            if trade_id:
                if is_primary:
                    update_data["primaryTradeId"] = trade_id
                else:
                    update_data["fallbackTradeId"] = trade_id

            await db_service.db.tradeplan.update(where={"id": plan.id}, data=update_data)

            label = "primary" if is_primary else "fallback"
            await notification_sender.send_message(
                f"✅ Plan {label} entry executed — {plan.symbol} {plan.orderType} "
                f"@ {signal.entry_price:.5g}",
                category='trade_plans'
            )

            if new_status in ("PRIMARY_ACTIVE",):
                # Keep in watcher to detect SL hit → fallback transition
                plan.status = new_status
                if trade_id and is_primary:
                    plan.primaryTradeId = trade_id
            else:
                # Fallback executed — plan is fully active, no more watching needed
                self.remove_plan(plan.id)

        except Exception as e:
            logger.error(f"PlanWatcher execute_leg error for plan {plan.id}: {e}", exc_info=True)
            try:
                await notification_sender.send_message(
                    f"❌ Plan execution failed for {plan.symbol}: {e}",
                    category='trade_plans'
                )
            except Exception as _exc:
                logger.debug(f"Suppressed exception: {_exc!r}")

    async def _check_primary_stopped_out(self, plan) -> None:
        """Check if the primary trade was stopped out — if so, activate fallback watching."""
        if not plan.primaryTradeId:
            return

        from src.core.database_service import db_service
        from src.integrations.telegram.unified_sender import notification_sender

        try:
            trade = await db_service.db.trade.find_unique(
                where={"id": plan.primaryTradeId}
            )
            if not trade or trade.status != "CLOSED":
                return

            # Detect SL close vs TP close using close price proximity to SL
            pip = 0.1 if "XAU" in plan.symbol or "XAG" in plan.symbol else 0.0001
            tolerance = 5 * pip
            close_price = trade.closePrice or 0.0
            is_buy = plan.orderType.upper() == "BUY"

            stopped_out = (
                (is_buy and close_price <= plan.primarySl + tolerance) or
                (not is_buy and close_price >= plan.primarySl - tolerance)
            )

            if stopped_out and plan.fallbackEntryMin:
                await db_service.db.tradeplan.update(
                    where={"id": plan.id},
                    data={"status": "FALLBACK_WATCHING"},
                )
                plan.status = "FALLBACK_WATCHING"
                await notification_sender.send_message(
                    f"🔄 Primary stopped out. Watching fallback zone "
                    f"{plan.fallbackEntryMin}–{plan.fallbackEntryMax}",
                    category='trade_plans'
                )
            else:
                # TP hit — plan complete
                await self._expire_plan(plan, reason="completed_via_tp")
        except Exception as e:
            logger.error(f"Error checking primary stop-out for plan {plan.id}: {e}")

    async def _expire_plan(self, plan, reason: str = "expired") -> None:
        from src.core.database_service import db_service
        from src.integrations.telegram.unified_sender import notification_sender

        try:
            new_status = "EXPIRED" if reason != "completed_via_tp" else "EXPIRED"
            await db_service.db.tradeplan.update(
                where={"id": plan.id},
                data={"status": new_status},
            )
            self.remove_plan(plan.id)

            if reason == "expired":
                await notification_sender.send_message(
                    f"⏰ Plan for {plan.symbol} expired — entry zone never reached",
                    category='trade_plans'
                )
        except Exception as e:
            logger.error(f"Error expiring plan {plan.id}: {e}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _get_price(self, symbol: str, order_type: str) -> Optional[float]:
        try:
            from src.services.trading_service import trading_service
            data = await trading_service.trading_provider.get_symbol_price(symbol)
            if not data:
                return None
            return data.get("ask") if order_type.upper() == "BUY" else data.get("bid")
        except Exception as e:
            logger.warning(f"PlanWatcher: could not get price for {symbol}: {e}")
            return None


plan_watcher_service = PlanWatcherService()
