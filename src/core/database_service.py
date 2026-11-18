"""
Database Service
High-level database operations using Prisma ORM
"""
from typing import Optional, List, Dict, Any, Union
from datetime import datetime, timezone
from loguru import logger
import json
import base64

from src.core.prisma_client import prisma_client
from src.models import TradingSignal, TradeResult, RiskAssessment
from src.models.message import MessageIdentifier


class DatabaseService:
    """Service layer for database operations"""
    
    def __init__(self):
        self.current_session_id: Optional[str] = None
    
    @property
    def db(self):
        """Get Prisma client"""
        return prisma_client.client
    
    # ==================== SESSION MANAGEMENT ====================
    
    async def start_trading_session(self, starting_balance: float) -> str:
        """Start a new trading session"""
        try:
            session = await self.db.tradingsession.create(
                data={
                    "startingBalance": starting_balance
                }
            )
            self.current_session_id = session.id
            logger.info(f"📊 Trading session started (ID: {session.id[:8]}...)")
            return session.id
        except Exception as e:
            logger.error(f"❌ Failed to start session: {str(e)}")
            raise
    
    async def end_trading_session(
        self,
        session_id: str,
        ending_balance: float,
        stats: Dict[str, Any]
    ):
        """End a trading session"""
        try:
            await self.db.tradingsession.update(
                where={"id": session_id},
                data={
                    "stoppedAt": datetime.now(timezone.utc),
                    "endingBalance": ending_balance,
                    "totalSignals": stats.get("total_signals", 0),
                    "signalsExecuted": stats.get("signals_executed", 0),
                    "signalsRejected": stats.get("signals_rejected", 0),
                    "totalProfitLoss": stats.get("total_profit_loss", 0.0)
                }
            )
            logger.info(f"📊 Trading session ended (ID: {session_id[:8]}...)")
        except Exception as e:
            logger.error(f"❌ Failed to end session: {str(e)}")
            raise
    
    # ==================== SIGNAL OPERATIONS ====================
    
    async def save_signal(
        self,
        signal: TradingSignal,
        message_id: MessageIdentifier
    ) -> str:
        """Save a trading signal"""
        try:
            # Check if signal already exists with this channelId and messageId
            logger.debug(f"🔍 Checking for existing signal: channelId={signal.channel_id}, messageId={message_id.message_id}")
            
            existing_signal = await self.db.signal.find_first(
                where={
                    "channelId": signal.channel_id,
                    "messageId": message_id.message_id
                }
            )
            
            if existing_signal:
                logger.warning(f"⚠️ Signal already exists! Returning existing signal ID: {existing_signal.id[:8]}...")
                logger.warning(f"   Existing signal created: {existing_signal.createdAt}")
                logger.warning(f"   Channel: {existing_signal.channelId}, Message: {existing_signal.messageId}")
                logger.warning("   This means the same Telegram message ID is being reused!")
                return existing_signal.id
            
            # Check by messageHash ONLY within a short time window (30 seconds)
            # This prevents duplicate processing during bot restarts, but allows
            # new signals with the same text to be created after the window expires.
            # Same channel only: two channels posting the same text (a provider's VIP
            # and mirror channel) are two signals. Without the channel the second one
            # was filed under the first channel's signal — its orders were placed, but
            # its channel had no signal of its own, so that channel's plain commands
            # ("Gold to breakeven") found nothing to manage (simulated 2026-11-12).
            if message_id.message_hash:
                from datetime import timedelta
                dedup_window = datetime.now(timezone.utc) - timedelta(seconds=30)
                
                hash_duplicate = await self.db.signal.find_first(
                    where={
                        "messageHash": message_id.message_hash,
                        "channelId": signal.channel_id,
                        "createdAt": {"gte": dedup_window}
                    }
                )
                if hash_duplicate:
                    logger.debug(f"💾 Signal with same hash exists within 30s window (ID: {hash_duplicate.id[:8]}...), returning existing ID")
                    return hash_duplicate.id
            
            # Encode image if present
            image_data_b64 = None
            raw_image = getattr(signal, 'image_data', None)
            if raw_image:
                image_data_b64 = base64.b64encode(raw_image).decode('utf-8')

            # Prepare signal data
            is_plan = getattr(signal, 'is_plan', False)
            plan_data_raw = getattr(signal, 'plan_data', None)
            signal_data = {
                "action": signal.action.value if hasattr(signal.action, 'value') else str(signal.action),
                "orderType": signal.order_type.value if hasattr(signal, 'order_type') and signal.order_type else "BUY",
                "symbol": signal.symbol,
                "entryPrice": signal.entry_price,
                "entryRangeMin": getattr(signal, 'entry_range_min', None),
                "entryRangeMax": getattr(signal, 'entry_range_max', None),
                "stopLoss": signal.stop_loss,
                "takeProfit": json.dumps(signal.take_profit) if signal.take_profit else None,
                "lotSize": signal.lot_size,
                "confidence": signal.confidence or 0.5,
                "channelId": signal.channel_id,
                "channelName": signal.channel_name,
                "messageId": message_id.message_id,
                "rawMessage": signal.raw_message or "",
                "messageHash": message_id.message_hash,
                "aiRawResponse": getattr(signal, 'ai_raw_response', None),
                "status": signal.status.value if hasattr(signal, 'status') else "PENDING",
                "sessionId": self.current_session_id,
                "imageData": image_data_b64,
                "isPlan": bool(is_plan),
                "planData": json.dumps(plan_data_raw) if plan_data_raw else None,
            }
            
            # Create signal record
            signal_record = await self.db.signal.create(data=signal_data)
            
            logger.success(f"💾 Signal saved (ID: {signal_record.id[:8]}...)")
            return signal_record.id
            
        except Exception as e:
            logger.error(f"❌ Failed to save signal: {str(e)}")
            raise
    
    async def update_signal_risk_assessment(
        self,
        signal_id: str,
        risk_assessment: RiskAssessment
    ):
        """Update signal with risk assessment results"""
        try:
            await self.db.signal.update(
                where={"id": signal_id},
                data={
                    "riskApproved": risk_assessment.approved,
                    "calculatedLotSize": risk_assessment.calculated_lot_size,
                    "riskPercent": risk_assessment.risk_percent,
                    "riskAmount": risk_assessment.risk_amount,
                    "stopLossPips": risk_assessment.stop_loss_pips,
                    "takeProfitPips": risk_assessment.take_profit_pips,
                    "riskRewardRatio": risk_assessment.risk_reward_ratio,
                    "riskWarnings": json.dumps(risk_assessment.warnings) if risk_assessment.warnings else None,
                    "rejectionReason": risk_assessment.reason,
                    "status": "REJECTED" if not risk_assessment.approved else "VALIDATED"
                }
            )
            logger.debug(f"💾 Risk assessment saved for signal {signal_id[:8]}...")
        except Exception as e:
            logger.error(f"❌ Failed to update risk assessment: {str(e)}")
            raise

    async def update_signal_status(
        self,
        signal_id: str,
        status: str,
        rejection_reason: Optional[str] = None
    ):
        """
        Update the status of a signal record.

        Valid statuses: PENDING, VALIDATED, PROCESSING, AWAITING_APPROVAL,
                        RUNNING, REJECTED, EXPIRED, FAILED, PARTIALLY_RUNNING
        """
        try:
            update_data: Dict[str, Any] = {"status": status}
            if rejection_reason is not None:
                update_data["rejectionReason"] = rejection_reason
            await self.db.signal.update(
                where={"id": signal_id},
                data=update_data
            )
            logger.debug(f"💾 Signal {signal_id[:8]}... status → {status}")
        except Exception as e:
            logger.error(f"❌ Failed to update signal status for {signal_id[:8]}...: {str(e)}")
    
    async def record_signal(
        self,
        signal: TradingSignal,
        risk_assessment: RiskAssessment,
        trade_result: TradeResult,
        message_id: Optional[MessageIdentifier] = None
    ):
        """
        Record a complete signal with risk assessment and trade result.
        This is a convenience method that orchestrates saving the signal,
        updating risk assessment, creating a trade record, and updating execution.

        Args:
            signal: TradingSignal to record
            risk_assessment: RiskAssessment for the signal
            trade_result: TradeResult from execution
            message_id: Optional MessageIdentifier for the signal
        """
        try:
            # Create a message_id if not provided
            if message_id is None:
                message_id = MessageIdentifier(
                    chat_id=signal.channel_id or "",
                    message_id=0,
                    message_hash=f"{signal.channel_id}:{signal.entry_price}:{signal.stop_loss}",
                    timestamp=datetime.now(timezone.utc)
                )

            # Save the signal
            signal_id = await self.save_signal(signal, message_id)

            # Update risk assessment
            await self.update_signal_risk_assessment(signal_id, risk_assessment)

            # Create trade record
            trade_id = await self.create_trade(
                signal_id=signal_id,
                signal=signal,
                risk_assessment=risk_assessment
            )

            # Update trade execution
            await self.update_trade_execution(trade_id, trade_result)

            logger.success(f"💾 Signal recorded completely (ID: {signal_id[:8]}..., Trade: {trade_id[:8]}...)")
            return signal_id, trade_id

        except Exception as e:
            logger.error(f"❌ Failed to record signal: {str(e)}")
            raise

    async def update_signal_status_from_trades(self, signal_id: str):
        """
        Update signal status based on the status of all associated trades.

        Trade status groups
        -------------------
        terminal_closed  : CLOSED
        terminal_done    : CANCELLED, FAILED
        active           : RUNNING, EXECUTED  (open position)
        in_flight        : EXECUTING, PROCESSING  (being placed)
        waiting          : PENDING  (not yet sent to broker)

        Signal status derivation (priority order)
        ------------------------------------------
        1. Signal is AWAITING_APPROVAL or VALIDATED → skip (not yet placed)
        2. All trades terminal (closed/cancelled/failed):
             - Any CLOSED exists              → CLOSED
             - All CANCELLED                  → CANCELLED
             - All FAILED                     → FAILED
             - Mix CANCELLED + FAILED         → FAILED
        3. Some trades active (RUNNING/RUNNING), some terminal:
             - Any CLOSED terminal exists     → PARTIALLY_CLOSED
             - None closed yet                → RUNNING
        4. All trades active                  → RUNNING
        5. Any in-flight (EXECUTING/PROCESSING) → PROCESSING
        6. Otherwise (all PENDING)            → PROCESSING
        """
        try:
            # Fetch current signal status first
            signal = await self.db.signal.find_unique(
                where={"id": signal_id},
                include={"trades": False},
            )
            if not signal:
                return

            # Hard-protected statuses — never auto-overwrite regardless of trades
            hard_protected = {"AWAITING_APPROVAL", "REJECTED", "EXPIRED"}
            if signal.status in hard_protected:
                logger.debug(
                    f"💾 Signal {signal_id[:8]}... status={signal.status} is protected — skipping"
                )
                return

            all_trades = await self.db.trade.find_many(
                where={"signalId": signal_id}
            )

            if not all_trades:
                # VALIDATED with no trades yet → keep as-is
                if signal.status == "VALIDATED":
                    logger.debug(f"💾 Signal {signal_id[:8]}... VALIDATED with no trades — keeping")
                    return
                logger.debug(f"💾 No trades found for signal {signal_id[:8]}...")
                return

            total_count = len(all_trades)

            closed_count    = sum(1 for t in all_trades if t.status == "CLOSED")
            cancelled_count = sum(1 for t in all_trades if t.status == "CANCELLED")
            failed_count    = sum(1 for t in all_trades if t.status == "FAILED")
            active_count    = sum(1 for t in all_trades if t.status in {"RUNNING", "EXECUTED"})
            inflight_count  = sum(1 for t in all_trades if t.status in {"EXECUTING", "PROCESSING"})
            # PENDING + any uncategorised
            terminal_count  = closed_count + cancelled_count + failed_count

            # --- Derive signal status ---
            if terminal_count == total_count:
                # Every trade has reached a terminal state
                if closed_count > 0:
                    signal_status = "CLOSED"
                elif cancelled_count == total_count:
                    signal_status = "CANCELLED"
                else:
                    signal_status = "FAILED"

            elif active_count > 0:
                # At least one position is currently open
                if closed_count > 0:
                    signal_status = "PARTIALLY_CLOSED"
                else:
                    signal_status = "RUNNING"

            elif inflight_count > 0:
                signal_status = "PROCESSING"

            else:
                signal_status = "PROCESSING"  # Pending / unknown in-flight

            # Only write if different to avoid unnecessary DB churn
            if signal.status != signal_status:
                await self.db.signal.update(
                    where={"id": signal_id},
                    data={"status": signal_status}
                )
                logger.debug(
                    f"💾 Signal {signal_id[:8]}... {signal.status} → {signal_status} "
                    f"({active_count} active, {closed_count} closed, "
                    f"{cancelled_count} cancelled, {failed_count} failed / {total_count})"
                )

        except Exception as e:
            logger.error(f"❌ Failed to update signal status from trades: {str(e)}")
    
    # ==================== TRADE OPERATIONS ====================
    
    async def create_trade(
        self,
        signal_id: str,
        signal: TradingSignal,
        risk_assessment: RiskAssessment,
        is_multi_tp: bool = False,
        tp_level: Optional[int] = None,
        entry_leg: Optional[int] = None,
        parent_trade_id: Optional[str] = None,
        magic_number: Optional[int] = None
    ) -> str:
        """Create a trade record"""
        try:
            from config import settings
            
            # Get TP value for this trade
            tp_value = None
            if signal.take_profit:
                if isinstance(signal.take_profit, list):
                    if tp_level and tp_level <= len(signal.take_profit):
                        tp_value = signal.take_profit[tp_level - 1]
                    else:
                        tp_value = signal.take_profit[0]
                else:
                    tp_value = signal.take_profit
            
            trade_data = {
                "signalId": signal_id,
                "symbol": signal.symbol,
                "action": signal.action.value if hasattr(signal.action, 'value') else str(signal.action),
                "lotSize": risk_assessment.calculated_lot_size,
                "entryPrice": signal.entry_price,
                "stopLoss": signal.stop_loss,
                "takeProfit": tp_value,
                "tpLevel": tp_level,
                "entryLeg": entry_leg,
                "magicNumber": magic_number,
                "provider": (settings.trading_provider or "").lower().strip() or None,
                "isMultiTp": is_multi_tp,
                "parentTradeId": parent_trade_id,
                "status": "PENDING",
                "sessionId": self.current_session_id,
                # Auto TP/Trailing SL/Partial settings
                "autoTpEnabled": settings.enable_auto_take_profit,
                "trailingStopEnabled": settings.enable_trailing_stop,
                "breakEvenEnabled": settings.enable_breakeven_move,
                "autoPartialEnabled": settings.enable_auto_partial,
                "originalStopLoss": signal.stop_loss,
                "originalTakeProfit": tp_value
            }
            
            trade = await self.db.trade.create(data=trade_data)
            
            logger.info(f"💾 Trade created (ID: {trade.id[:8]}...)")
            return trade.id
            
        except Exception as e:
            logger.error(f"❌ Failed to create trade: {str(e)}")
            raise
    
    async def trade_is_buy(self, trade) -> bool:
        """
        Direction of a trade. A trade created from a signal stores the signal's
        action ("OPEN"), not BUY / SELL — comparing it with 'BUY' treated every such
        trade as a SELL and reported a winning BUY with negative pips. The signal's
        order type is the direction; recovered trades carry BUY / SELL themselves.
        """
        action = str(getattr(trade, 'action', '') or '').upper()
        if action in ('BUY', 'SELL'):
            return action == 'BUY'
        try:
            signal_id = getattr(trade, 'signalId', None)
            signal = await self.db.signal.find_unique(where={"id": signal_id}) if signal_id else None
            return str(getattr(signal, 'orderType', '') or '').upper() == 'BUY'
        except Exception as e:
            logger.debug(f"Could not read the direction of trade {getattr(trade, 'id', '?')}: {e}")
            return False

    async def update_trade_execution(
        self,
        trade_id: str,
        trade_result: TradeResult
    ):
        """Update trade with execution results"""
        try:
            update_data = {
                "executedAt": trade_result.timestamp or datetime.now(timezone.utc),
            }
            
            if trade_result.success:
                update_data.update({
                    "positionId": trade_result.position_id,
                    "orderId": trade_result.order_id,
                    "entryPrice": trade_result.entry_price,
                    "brokerResponse": json.dumps(trade_result.broker_response) if trade_result.broker_response else None
                })
                
                # A deal ticket means the order filled. MT5 keeps the order's ticket
                # as the position's, so position == order no longer says "pending"
                # on its own — only without a deal.
                deal_id = None
                if trade_result.broker_response and isinstance(trade_result.broker_response, dict):
                    deal_id = trade_result.broker_response.get('dealId') or trade_result.broker_response.get('deal')
                    if str(deal_id or '').strip() in ('', '0', 'None'):
                        deal_id = None
                    if deal_id:
                        update_data["dealId"] = str(deal_id)

                if trade_result.position_id and trade_result.order_id:
                    if trade_result.position_id == trade_result.order_id and not deal_id:
                        update_data["status"] = "PENDING"  # Limit order placed but not filled
                        logger.info(f"⏳ Limit order placed but not filled yet (order_id={trade_result.order_id})")
                    else:
                        update_data["status"] = "RUNNING"  # Filled - live trade
                        logger.info(f"✅ Order filled and RUNNING (order_id={trade_result.order_id}, position_id={trade_result.position_id})")
                elif trade_result.position_id:
                    # Only position_id (no order_id) - market order or filled limit
                    update_data["status"] = "RUNNING"  # Live trade
                else:
                    # No IDs at all - keep as PENDING
                    update_data["status"] = "PENDING"
            else:
                update_data["status"] = "FAILED"
                update_data["executionError"] = trade_result.error_message
            
            await self.db.trade.update(
                where={"id": trade_id},
                data=update_data
            )
            
            # Update signal status based on ALL trades for this signal
            trade = await self.db.trade.find_unique(where={"id": trade_id})
            if trade and trade.signalId:
                await self.update_signal_status_from_trades(trade.signalId)
                # Forward "position opened" for instant MARKET fills (LIMIT fills
                # are handled by order_sync_service when the order later fills).
                if trade.status == "RUNNING":
                    try:
                        from src.services.signal_forwarder_service import signal_forwarder_service
                        price = trade_result.entry_price or getattr(trade, 'entryPrice', None)
                        await signal_forwarder_service.reply_position_opened(
                            trade.signalId, trade.symbol, price, trade_id=trade.id,
                        )
                    except Exception as _exc:
                        logger.debug(f"Suppressed exception: {_exc!r}")
            
            status = "✅" if trade_result.success else "❌"
            logger.info(f"{status} Trade execution updated (ID: {trade_id[:8]}...)")
            
        except Exception as e:
            logger.error(f"❌ Failed to update trade execution: {str(e)}")
            raise
    
    async def update_trade_closure(
        self,
        trade_id: str,
        close_price: Optional[float] = None,
        profit_loss: Optional[float] = None,
        profit_loss_pips: Optional[float] = None,
        broker_closure_reason: Optional[str] = None,
    ):
        """
        Update trade with closure data including profit/loss

        Args:
            trade_id: Trade ID to update
            close_price: Closing price of the position
            profit_loss: Profit/loss in account currency ($)
            profit_loss_pips: Profit/loss in pips
            broker_closure_reason: Authoritative reason from broker ('sl','tp','manual').
                                   When provided it takes priority over all heuristics.
        """
        try:
            update_data = {
                "status": "CLOSED",
                "closedAt": datetime.now(timezone.utc)
            }
            
            if close_price is not None:
                update_data["closePrice"] = close_price
            if profit_loss is not None:
                update_data["profitLoss"] = profit_loss
            if profit_loss_pips is not None:
                update_data["profitLossPips"] = profit_loss_pips
            
            await self.db.trade.update(
                where={"id": trade_id},
                data=update_data
            )
            
            # Update signal status based on ALL trades for this signal
            trade = await self.db.trade.find_unique(where={"id": trade_id})
            if trade and trade.signalId:
                await self.update_signal_status_from_trades(trade.signalId)

                # Forward close reply only when the signal itself is now fully CLOSED
                # (guards against firing once per trade when a signal has multiple trades)
                try:
                    signal = await self.db.signal.find_unique(where={"id": trade.signalId})
                    if signal and signal.status in ("CLOSED", "PARTIALLY_CLOSED"):
                        from src.services.signal_forwarder_service import signal_forwarder_service
                        # Use cached pips from live position tracking if not provided at closure
                        effective_pips = profit_loss_pips
                        if effective_pips is None:
                            effective_pips = getattr(trade, 'profitLossPips', None)
                        closure_reason = self._detect_closure_reason(trade, close_price, effective_pips, broker_closure_reason)
                        if signal.status == "CLOSED":
                            await signal_forwarder_service.reply_closed(
                                trade.signalId, close_price, effective_pips, closure_reason
                            )
                        else:
                            # One entry closed, others still open: say so — the channel
                            # must not read this as the whole signal being over.
                            siblings = await self.db.trade.find_many(where={"signalId": trade.signalId})
                            open_count = sum(1 for t in siblings if t.status in ("RUNNING", "EXECUTED"))
                            await signal_forwarder_service.reply_leg_closed(
                                trade.signalId, close_price, effective_pips, closure_reason,
                                open_count, trade_id=trade.id,
                            )
                except Exception as _exc:
                    logger.debug(f"Suppressed exception: {_exc!r}")

            logger.debug(f"💾 Trade {trade_id[:8]}... closed with P/L: ${profit_loss:.2f}" if profit_loss else f"💾 Trade {trade_id[:8]}... marked as closed")
            
        except Exception as e:
            logger.error(f"❌ Failed to update trade closure: {str(e)}")
            raise
    
    @staticmethod
    def _detect_closure_reason(trade, close_price, pips, broker_closure_reason: Optional[str] = None) -> str:
        """
        Returns one of: 'tp', 'sl', 'be', 'trailing', 'manual'
        based on trade flags and close price vs key levels.
        """
        take_profit  = getattr(trade, 'takeProfit', None)
        stop_loss    = getattr(trade, 'stopLoss', None)
        entry_price  = getattr(trade, 'entryPrice', None)
        be_activated = getattr(trade, 'breakEvenActivated', False)
        trailing_enabled = getattr(trade, 'trailingStopEnabled', False)
        symbol       = (getattr(trade, 'symbol', '') or '').upper()

        # -----------------------------------------------------------------
        # BE detection: must run BEFORE trusting the broker 'sl' reason.
        # MT5 reports a breakeven stop hit as DEAL_REASON_SL (code 4) —
        # it has no concept of "this SL was at entry".  We know better:
        # if BE was activated and the close price is within entry ± (buffer
        # + a small slippage margin), it is a BE exit, not a loss.
        # -----------------------------------------------------------------
        def _is_be_close() -> bool:
            if not be_activated:
                return False
            # Price-based check against entry (most reliable)
            if close_price and entry_price:
                try:
                    pip_val = 0.01 if 'JPY' in symbol else 0.0001
                    from config import settings
                    # Allow buffer + 3 extra pips for spread/slippage
                    tolerance = (settings.breakeven_buffer_pips + 3) * pip_val
                    if abs(float(close_price) - float(entry_price)) <= tolerance:
                        return True
                except Exception as _exc:
                    logger.debug(f"Suppressed exception: {_exc!r}")
            # Pips-based fallback (handles missing entry_price)
            if pips is not None and abs(pips) <= 5:
                return True
            return False

        # TP: broker confirmation is reliable — trust it first
        if broker_closure_reason == 'tp':
            return 'tp'

        # BE: check before accepting broker 'sl' (MT5 conflates the two)
        if _is_be_close():
            return 'be'

        # All other broker-supplied reasons are authoritative
        if broker_closure_reason in ('sl', 'be', 'trailing', 'manual'):
            return broker_closure_reason

        # --- Heuristics when broker gave no reason ---

        # TP: close price within 0.1% of take profit level
        if close_price and take_profit:
            try:
                if abs(float(close_price) - float(take_profit)) / (float(take_profit) or 1) < 0.001:
                    return 'tp'
            except (TypeError, ValueError):
                pass

        # Trailing: trailing was active and trade closed in profit
        if trailing_enabled and pips is not None and pips > 0:
            return 'trailing'

        # SL: close price within 0.1% of stop loss level
        if close_price and stop_loss:
            try:
                if abs(float(close_price) - float(stop_loss)) / (float(stop_loss) or 1) < 0.001:
                    return 'sl'
            except (TypeError, ValueError):
                pass

        # SL: closed in loss (pips-based fallback)
        if pips is not None and pips < 0:
            return 'sl'

        return 'manual'

    # ==================== MESSAGE MAPPING ====================
    
    async def create_or_update_message_mapping(
        self,
        chat_id: str,
        message_id: int,
        signal_id: Optional[str] = None,
        trade_ids: Optional[List[str]] = None,
        magic_number: Optional[int] = None,
        mapping_type: str = "NEW_SIGNAL",
        message_hash: Optional[str] = None,
        position_ids: Optional[List[str]] = None,
        order_ids: Optional[List[str]] = None
    ):
        """Create or update a message-to-trade mapping (alternative signature)"""
        # Convert to MessageIdentifier format
        msg_id = MessageIdentifier(
            chat_id=chat_id,
            message_id=message_id,
            message_hash=message_hash or f"{chat_id}:{message_id}",
            timestamp=datetime.now(timezone.utc)
        )
        # Note: position_ids and order_ids are accepted but not currently stored separately
        # They're tracked via trade_ids which link to the Trade records that contain position/order IDs
        return await self.create_message_mapping(
            message_id=msg_id,
            signal_id=signal_id,
            trade_ids=trade_ids,
            magic_number=magic_number,
            mapping_type=mapping_type
        )
    
    async def create_message_mapping(
        self,
        message_id: MessageIdentifier,
        signal_id: Optional[str] = None,
        trade_ids: Optional[List[str]] = None,
        magic_number: Optional[int] = None,
        mapping_type: str = "NEW_SIGNAL"
    ):
        """Create or update a message-to-trade mapping"""
        try:
            await self.db.messagemapping.upsert(
                where={
                    "chatId_messageId": {
                        "chatId": message_id.chat_id,
                        "messageId": message_id.message_id
                    }
                },
                data={
                    "create": {
                        "chatId": message_id.chat_id,
                        "messageId": message_id.message_id,
                        "messageHash": message_id.message_hash,
                        "signalId": signal_id,
                        "tradeIds": json.dumps(trade_ids) if trade_ids else None,
                        "magicNumber": magic_number,
                        "mappingType": mapping_type
                    },
                    "update": {
                        "messageHash": message_id.message_hash,
                        "signalId": signal_id,
                        "tradeIds": json.dumps(trade_ids) if trade_ids else None,
                        "magicNumber": magic_number,
                        "mappingType": mapping_type
                    }
                }
            )
            logger.debug(f"💾 Message mapping saved for {message_id.chat_id}:{message_id.message_id} (magic={magic_number})")
        except Exception as e:
            logger.error(f"❌ Failed to create/update message mapping: {str(e)}")
            # Don't raise - message mapping is optional
    
    async def find_signal_by_message(
        self,
        message_id: MessageIdentifier
    ) -> Optional[Any]:
        """Find signal by Telegram message"""
        try:
            return await self.db.signal.find_first(
                where={
                    "channelId": message_id.chat_id,
                    "messageId": message_id.message_id
                }
            )
        except Exception as e:
            logger.error(f"❌ Error finding signal by message: {str(e)}")
            return None
    
    # Statuses that mean "this signal is still relevant" — a fresh message that
    # continues one of these updates it instead of opening a second trade
    # (see src/services/signal_continuity.py).
    ACTIVE_SIGNAL_STATUSES = [
        "PENDING", "VALIDATED", "AWAITING_APPROVAL", "PROCESSING",
        "EXECUTED", "RUNNING", "PARTIALLY_RUNNING", "PARTIALLY_CLOSED",
    ]

    async def merge_signal_supplementary_info(
        self,
        signal_id: str,
        extra_raw_message: Optional[str] = None,
        image_data: Optional[bytes] = None,
    ) -> None:
        """
        Attach evidence from a follow-up message (that turned out to describe the
        same trade as an already-active signal) onto the existing signal record,
        instead of creating a duplicate signal.
        """
        try:
            update_data: Dict[str, Any] = {}
            if extra_raw_message:
                existing = await self.db.signal.find_unique(where={"id": signal_id})
                if existing:
                    current_raw = existing.rawMessage or ""
                    if extra_raw_message.strip() and extra_raw_message.strip() not in current_raw:
                        update_data["rawMessage"] = f"{current_raw}\n---\n{extra_raw_message}".strip()
                    if image_data and not existing.imageData:
                        update_data["imageData"] = base64.b64encode(image_data).decode('utf-8')
            elif image_data:
                existing = await self.db.signal.find_unique(where={"id": signal_id})
                if existing and not existing.imageData:
                    update_data["imageData"] = base64.b64encode(image_data).decode('utf-8')

            if update_data:
                await self.db.signal.update(where={"id": signal_id}, data=update_data)
                logger.info(f"🔗 Merged supplementary info into existing signal {signal_id[:8]}...")
        except Exception as e:
            logger.error(f"❌ Failed to merge supplementary info into signal {signal_id[:8]}...: {str(e)}")

    async def get_signal_by_id(self, signal_id: str) -> Optional[Dict[str, Any]]:
        """Get signal record as dict by signal ID"""
        try:
            signal = await self.db.signal.find_unique(
                where={"id": signal_id}
            )
            if signal:
                return signal.model_dump() if hasattr(signal, 'model_dump') else signal.__dict__
            return None
        except Exception as e:
            logger.debug(f"Could not find signal {signal_id[:8]}...: {str(e)}")
            return None
    
    async def find_trade_by_position(self, position_id: str) -> Optional[Any]:
        """Find trade by position ID"""
        try:
            return await self.db.trade.find_first(
                where={"positionId": position_id}
            )
        except Exception as e:
            logger.error(f"❌ Error finding trade by position: {str(e)}")
            return None
    
    async def get_trade_by_position_id(self, position_id: str) -> Optional[Dict[str, Any]]:
        """Get trade record as dict by position ID (dict variant of find_trade_by_position)"""
        trade = await self.find_trade_by_position(position_id)
        if trade:
            return trade.model_dump() if hasattr(trade, 'model_dump') else trade.__dict__
        return None
    
    async def get_trades_by_magic_number(self, magic_number: int) -> List[Dict[str, Any]]:
        """Get all trade records by magic number"""
        try:
            trades = await self.db.trade.find_many(
                where={"magicNumber": magic_number}
            )
            return [self._trade_to_dict(t) for t in trades]
        except Exception as e:
            logger.error(f"Error finding trades by magic number {magic_number}: {str(e)}")
            return []
    
    async def get_trades_by_signal_id(self, signal_id: str) -> List[Dict[str, Any]]:
        """
        Get all trade records for a specific signal (used for multi-TP signals)
        
        Args:
            signal_id: Signal ID to fetch trades for
            
        Returns:
            List of trade dictionaries
        """
        try:
            trades = await self.db.trade.find_many(
                where={"signalId": signal_id},
                order={"createdAt": "asc"}  # Order by creation time (TP1, TP2, TP3)
            )
            return [self._trade_to_dict(t) for t in trades]
        except Exception as e:
            logger.error(f"Error finding trades by signal ID {signal_id[:8]}...: {str(e)}")
            return []
    
    def _trade_to_dict(self, trade) -> Dict[str, Any]:
        """Convert trade object to dictionary"""
        try:
            if hasattr(trade, 'model_dump'):
                return trade.model_dump()
            elif hasattr(trade, '__dict__'):
                return trade.__dict__
            else:
                # Fallback: try to convert to dict
                return dict(trade)
        except Exception as e:
            logger.error(f"Error converting trade to dict: {str(e)}")
            return {}
    
    async def get_open_positions(self, channel_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get all currently open positions (trades with status RUNNING)
        
        Uses two-step query approach to avoid complex Prisma nested filters
        Also handles channel ID with/without -100 prefix
        
        Args:
            channel_id: Optional channel ID to filter positions by specific channel
        """
        try:
            # If channel filter is provided, use two-step query
            if channel_id:
                # Step 1: Find all signals for this channel (with prefix handling)
                channel_ids_to_try = [channel_id]
                
                if channel_id.startswith("-100"):
                    without_prefix = channel_id.replace("-100", "", 1)
                    channel_ids_to_try.append(without_prefix)
                else:
                    with_prefix = f"-100{channel_id}"
                    channel_ids_to_try.append(with_prefix)
                
                signals = await self.db.signal.find_many(
                    where={
                        "channelId": {"in": channel_ids_to_try},
                        "trades": {
                            "some": {  # Only signals with at least one open trade
                                "status": "RUNNING",
                                "closedAt": None
                            }
                        }
                    }
                )
                
                if not signals:
                    logger.debug(f"No signals found for channel {channel_id}")
                    return []
                
                signal_ids = [signal.id for signal in signals]
                
                # Step 2: Query trades for these signals
                trades = await self.db.trade.find_many(
                    where={
                        "signalId": {"in": signal_ids},
                        "status": "RUNNING",
                        "closedAt": None
                    },
                    include={"signal": True}
                )
            else:
                # No channel filter - simple query
                trades = await self.db.trade.find_many(
                    where={
                        "status": "RUNNING",
                        "closedAt": None
                    },
                    include={"signal": True}
                )
            
            
            positions = []
            for trade in trades:
                positions.append({
                    "trade_id": trade.id,
                    "signal_id": trade.signalId,
                    "symbol": trade.signal.symbol if trade.signal else None,
                    "action": trade.signal.action if trade.signal else None,
                    "order_type": trade.signal.orderType if trade.signal else None,
                    "entry_price": trade.entryPrice,
                    "stop_loss": trade.signal.stopLoss if trade.signal else None,
                    "take_profit": json.loads(trade.signal.takeProfit) if trade.signal and trade.signal.takeProfit else [],
                    "opened_at": trade.executedAt,
                    "position_id": trade.positionId,
                    "order_id": trade.orderId,
                    "status": trade.status,
                    "lot_size": trade.signal.lotSize if trade.signal else None,
                    "magic_number": trade.magicNumber
                })
            
            return positions
        except Exception as e:
            logger.error(f"Error fetching open positions: {str(e)}")
            return []
    
    async def get_open_positions_by_symbol(
        self, 
        symbol: str, 
        channel_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get open positions for a specific symbol, optionally filtered by channel
        
        Uses two-step query approach to avoid complex Prisma nested filters
        Also handles channel ID with/without -100 prefix
        
        Args:
            symbol: Trading symbol (e.g., "XAUUSD")
            channel_id: Optional channel ID to filter by specific channel
        
        Returns:
            List of open position dictionaries
        """
        try:
            # Step 1: Find signals matching symbol and channel
            signal_where = {"symbol": symbol}
            
            if channel_id:
                # Try both with and without -100 prefix
                channel_ids_to_try = [channel_id]
                
                # If starts with -100, also try without it
                if channel_id.startswith("-100"):
                    without_prefix = channel_id.replace("-100", "", 1)
                    channel_ids_to_try.append(without_prefix)
                # If doesn't start with -100, also try with it
                else:
                    with_prefix = f"-100{channel_id}"
                    channel_ids_to_try.append(with_prefix)
                
                logger.debug(f"Trying channel IDs: {channel_ids_to_try}")
                
                # Query with OR condition for channel IDs
                signal_where["channelId"] = {"in": channel_ids_to_try}
            
            # Add filter for signals with open trades
            signal_where["trades"] = {
                "some": {  # Only signals with at least one open trade
                    "status": "RUNNING",
                    "closedAt": None
                }
            }
            
            signals = await self.db.signal.find_many(where=signal_where)
            
            if not signals:
                logger.debug(f"No signals found for {symbol}{' in channel ' + channel_id if channel_id else ''}")
                return []
            
            # Extract signal IDs
            signal_ids = [signal.id for signal in signals]
            logger.debug(f"Found {len(signal_ids)} signal(s) for {symbol}")
            
            # Step 2: Query trades for these signals that are still open
            trades = await self.db.trade.find_many(
                where={
                    "signalId": {"in": signal_ids},
                    "status": "RUNNING",
                    "closedAt": None
                },
                include={"signal": True}
            )
            
            if not trades:
                logger.debug(f"No open trades found for {symbol}")
                return []
            
            # Build positions list
            positions = []
            for trade in trades:
                positions.append({
                    "trade_id": trade.id,
                    "signal_id": trade.signalId,
                    "symbol": trade.symbol,
                    "action": trade.action,
                    "entry_price": trade.entryPrice,
                    "entry_leg": getattr(trade, "entryLeg", None),
                    "stop_loss": trade.stopLoss,
                    "take_profit": trade.takeProfit,
                    "opened_at": trade.executedAt,
                    "position_id": trade.positionId,
                    "order_id": trade.orderId,
                    "status": trade.status,
                    "lot_size": trade.lotSize,
                    "magic_number": trade.magicNumber,
                    "channel_id": trade.signal.channelId if trade.signal else None
                })
            
            logger.debug(f"Found {len(positions)} open position(s) for {symbol}")
            return positions
            
        except Exception as e:
            logger.error(f"Error fetching open positions for {symbol}: {str(e)}")
            return []
    
    async def get_message_mapping_by_message_id(self, chat_id: str, message_id: int) -> Optional[Dict[str, Any]]:
        """Get message mapping by Telegram message ID"""
        try:
            mapping = await self.db.messagemapping.find_first(
                where={
                    "chatId": chat_id,
                    "messageId": message_id
                }
            )
            if mapping:
                return mapping.model_dump() if hasattr(mapping, 'model_dump') else mapping.__dict__
            return None
        except Exception as e:
            logger.error(f"Could not find message mapping for {chat_id}:{message_id}: {str(e)}")
            return None
    
    async def get_trades_by_message_id(self, chat_id: str, message_id: int) -> List[Dict[str, Any]]:
        """Get all trades associated with a Telegram message"""
        try:
            # First get the mapping
            mapping = await self.get_message_mapping_by_message_id(chat_id, message_id)
            
            if not mapping:
                return []
            
            # If we have a magic number, use it to fetch from MetaAPI
            if mapping.get('magicNumber'):
                trades = await self.get_trades_by_magic_number(mapping['magicNumber'])
                return trades
            
            # Otherwise try to use trade IDs from mapping
            if mapping.get('tradeIds'):
                trade_ids = json.loads(mapping['tradeIds']) if isinstance(mapping['tradeIds'], str) else mapping['tradeIds']
                trades = []
                for trade_id in trade_ids:
                    trade = await self.db.trade.find_unique(where={"id": trade_id})
                    if trade:
                        trades.append(trade.model_dump() if hasattr(trade, 'model_dump') else trade.__dict__)
                return trades
            
            return []
        except Exception as e:
            logger.error(f"Could not find trades for message {chat_id}:{message_id}: {str(e)}")
            return []
    
    async def update_trade_field(self, trade_id: str, field_name: str, value: Any):
        """Update a single field in a trade record"""
        try:
            # Validate and convert takeProfit field if needed
            if field_name == 'takeProfit' and value is not None:
                # Handle list objects directly (from MetaAPI multi-TP positions)
                if isinstance(value, list):
                    # Take the first non-None value from the list
                    value = next((tp for tp in value if tp is not None), None)
                    logger.debug(f"📊 Converted TP list to single value: {value}")
                # If it's a string, try to parse it
                elif isinstance(value, str):
                    try:
                        import json
                        # Try to parse as JSON list
                        parsed = json.loads(value)
                        if isinstance(parsed, list):
                            # Take the first non-None value from the list
                            value = next((tp for tp in parsed if tp is not None), None)
                        else:
                            # Try to convert directly to float
                            value = float(parsed) if parsed is not None else None
                    except (json.JSONDecodeError, ValueError):
                        # If parsing fails, try direct float conversion
                        try:
                            value = float(value)
                        except (ValueError, TypeError):
                            logger.warning(f"⚠️ Cannot convert takeProfit value to float: {value}")
                            value = None
            
            await self.db.trade.update(
                where={"id": trade_id},
                data={field_name: value}
            )
            logger.debug(f"💾 Updated trade {trade_id[:8]}... field '{field_name}'")
            
            # If status was updated, reconcile signal status
            if field_name == 'status':
                trade = await self.db.trade.find_unique(where={"id": trade_id})
                if trade and trade.signalId:
                    await self.update_signal_status_from_trades(trade.signalId)
        except Exception as e:
            logger.error(f"❌ Failed to update trade field '{field_name}' with value '{value}': {str(e)}")
            raise
    
    async def update_trade_fields(self, trade_id: str, updates: Dict[str, Any]):
        """
        Update multiple fields in a trade record at once (more efficient than individual updates)
        
        Args:
            trade_id: Trade ID to update
            updates: Dictionary of field names and values to update
        """
        try:
            if not updates:
                return
            
            # Validate and convert takeProfit field if needed
            if 'takeProfit' in updates and updates['takeProfit'] is not None:
                value = updates['takeProfit']
                # Handle list objects directly (from MetaAPI multi-TP positions)
                if isinstance(value, list):
                    # Take the first non-None value from the list
                    updates['takeProfit'] = next((tp for tp in value if tp is not None), None)
                    logger.debug(f"📊 Converted TP list {value} to single value: {updates['takeProfit']}")
                elif isinstance(value, str):
                    try:
                        # Try to parse as JSON list
                        parsed = json.loads(value)
                        if isinstance(parsed, list):
                            # Take the first non-None value from the list
                            updates['takeProfit'] = next((tp for tp in parsed if tp is not None), None)
                        else:
                            # Try to convert directly to float
                            updates['takeProfit'] = float(parsed) if parsed is not None else None
                    except (json.JSONDecodeError, ValueError):
                        # If parsing fails, try direct float conversion
                        try:
                            updates['takeProfit'] = float(value)
                        except (ValueError, TypeError):
                            logger.warning(f"⚠️ Cannot convert takeProfit value to float: {value}")
                            updates['takeProfit'] = None
            
            await self.db.trade.update(
                where={"id": trade_id},
                data=updates
            )
            logger.debug(f"💾 Batch updated trade {trade_id[:8]}... ({len(updates)} fields)")
            
            # If status was updated, reconcile signal status
            if 'status' in updates:
                trade = await self.db.trade.find_unique(where={"id": trade_id})
                if trade and trade.signalId:
                    await self.update_signal_status_from_trades(trade.signalId)
        except Exception as e:
            logger.error(f"❌ Failed to batch update trade {trade_id[:8]}...: {str(e)}")
            logger.error(f"   Fields attempted: {list(updates.keys())}")
            raise
    
    # ==================== TRADE ACTIONS ====================
    
    async def log_trade_action(
        self,
        trade_id: str,
        action_type: str,
        success: bool,
        details: Optional[Union[Dict[str, Any], str]] = None,
        old_sl: Optional[float] = None,
        new_sl: Optional[float] = None,
        old_tp: Optional[float] = None,
        new_tp: Optional[float] = None,
        triggered_by: str = "system",
        trigger_source: Optional[str] = None
    ):
        """Log a trade action"""
        try:
            # Handle both string and dict details
            details_str = None
            if details:
                if isinstance(details, str):
                    details_str = details
                else:
                    details_str = json.dumps(details)
            
            await self.db.tradeaction.create(
                data={
                    "tradeId": trade_id,
                    "actionType": action_type,
                    "success": success,
                    "details": details_str,
                    "oldStopLoss": old_sl,
                    "newStopLoss": new_sl,
                    "oldTakeProfit": old_tp,
                    "newTakeProfit": new_tp,
                    "triggeredBy": triggered_by,
                    "triggerSource": trigger_source
                }
            )
            logger.debug(f"💾 Trade action logged: {action_type} for trade {trade_id[:8]}...")
        except Exception as e:
            logger.error(f"❌ Failed to log trade action: {str(e)}")
            # Don't raise - logging is optional
    
    async def create_trade_action(
        self,
        trade_id: str,
        action_type: str,
        success: bool = True,
        old_stop_loss: Optional[float] = None,
        new_stop_loss: Optional[float] = None,
        old_take_profit: Optional[float] = None,
        new_take_profit: Optional[float] = None,
        current_price: Optional[float] = None,
        profit_pips: Optional[float] = None,
        triggered_by: str = "system",
        trigger_source: Optional[str] = None,
        details: Optional[str] = None
    ):
        """Create a trade action with flexible parameters"""
        try:
            await self.db.tradeaction.create(
                data={
                    "tradeId": trade_id,
                    "actionType": action_type,
                    "success": success,
                    "oldStopLoss": old_stop_loss,
                    "newStopLoss": new_stop_loss,
                    "oldTakeProfit": old_take_profit,
                    "newTakeProfit": new_take_profit,
                    "currentPrice": current_price,
                    "profitPips": profit_pips,
                    "triggeredBy": triggered_by,
                    "triggerSource": trigger_source,
                    "details": details
                }
            )
            logger.debug(f"💾 Trade action created: {action_type} for trade {trade_id[:8]}...")
        except Exception as e:
            logger.error(f"❌ Failed to create trade action: {str(e)}")
            # Don't raise - logging is optional
    
    # ==================== SIGNAL REPLIES ====================
    
    async def create_signal_reply(
        self,
        chat_id: str,
        reply_message_id: int,
        reply_to_message_id: int,
        reply_text: str,
        user_id: Optional[str] = None,
        username: Optional[str] = None,
        signal_id: Optional[str] = None,
        magic_number: Optional[int] = None,
        symbol: Optional[str] = None,
        command_timestamp: Optional[datetime] = None
    ) -> Optional[str]:
        """
        Create a new signal reply record
        
        Args:
            command_timestamp: When the command was received (uses createdAt if not provided)
        
        Returns:
            The created reply ID or None if failed
        """
        try:
            # Check if reply already exists (prevent duplicate processing)
            existing_reply = await self.db.signalreply.find_first(
                where={
                    "chatId": chat_id,
                    "replyMessageId": reply_message_id
                }
            )
            
            if existing_reply:
                logger.debug(f"💬 Signal reply already exists for chatId={chat_id}, replyMessageId={reply_message_id}, returning existing ID {existing_reply.id[:8]}...")
                return existing_reply.id
            
            # Build data dictionary
            data = {
                "chatId": chat_id,
                "replyMessageId": reply_message_id,
                "replyToMessageId": reply_to_message_id,
                "replyText": reply_text,
                "userId": user_id,
                "username": username,
                "signalId": signal_id,
                "magicNumber": magic_number,
                "symbol": symbol,
                "processed": False
            }
            
            # If command_timestamp is provided, use it for createdAt
            if command_timestamp:
                data["createdAt"] = command_timestamp
            
            reply = await self.db.signalreply.create(data=data)
            logger.debug(f"💬 Created signal reply record {reply.id[:8]}...")
            return reply.id
        except Exception as e:
            logger.error(f"❌ Failed to create signal reply: {str(e)}")
            return None
    
    async def update_signal_reply_action(
        self,
        reply_id: str,
        action_taken: bool,
        action_type: Optional[str] = None,
        action_success: bool = False,
        action_result: Optional[str] = None,
        action_details: Optional[Dict[str, Any]] = None,
        affected_trade_ids: Optional[List[str]] = None,
        positions_closed: int = 0,
        orders_cancelled: int = 0,
        processed: bool = True,
        processing_error: Optional[str] = None,
        ai_parsed: bool = False
    ):
        """
        Update signal reply with action results
        """
        try:
            update_data = {
                "processed": processed,
                "actionTaken": action_taken,
                "actionSuccess": action_success
            }
            
            if action_type:
                update_data["actionType"] = action_type
            if action_result:
                update_data["actionResult"] = action_result
            if action_details:
                update_data["actionDetails"] = json.dumps(action_details)
            if affected_trade_ids:
                update_data["affectedTradeIds"] = json.dumps(affected_trade_ids)
            if positions_closed > 0:
                update_data["positionsClosed"] = positions_closed
            if orders_cancelled > 0:
                update_data["ordersCancelled"] = orders_cancelled
            if processing_error:
                update_data["processingError"] = processing_error
            if ai_parsed:
                update_data["aiParsed"] = ai_parsed
            
            await self.db.signalreply.update(
                where={"id": reply_id},
                data=update_data
            )
            logger.debug(f"💬 Updated signal reply {reply_id[:8]}... with action results")
        except Exception as e:
            logger.error(f"❌ Failed to update signal reply: {str(e)}")
    
    async def get_signal_replies(
        self,
        signal_id: Optional[str] = None,
        magic_number: Optional[int] = None,
        reply_to_message_id: Optional[int] = None,
        limit: int = 50
    ) -> List[Dict]:
        """
        Get signal replies with optional filters
        """
        try:
            where = {}
            if signal_id:
                where["signalId"] = signal_id
            if magic_number:
                where["magicNumber"] = magic_number
            if reply_to_message_id:
                where["replyToMessageId"] = reply_to_message_id
            
            replies = await self.db.signalreply.find_many(
                where=where if where else None,
                order={"createdAt": "desc"},
                take=limit
            )
            
            return [
                {
                    'id': r.id,
                    'createdAt': r.createdAt,
                    'chatId': r.chatId,
                    'replyMessageId': r.replyMessageId,
                    'replyToMessageId': r.replyToMessageId,
                    'replyText': r.replyText,
                    'userId': r.userId,
                    'username': r.username,
                    'signalId': r.signalId,
                    'magicNumber': r.magicNumber,
                    'symbol': r.symbol,
                    'actionTaken': r.actionTaken,
                    'actionType': r.actionType,
                    'actionSuccess': r.actionSuccess,
                    'actionResult': r.actionResult,
                    'actionDetails': r.actionDetails,
                    'affectedTradeIds': r.affectedTradeIds,
                    'positionsClosed': r.positionsClosed,
                    'ordersCancelled': r.ordersCancelled,
                    'processed': r.processed,
                    'processingError': r.processingError,
                    'aiParsed': r.aiParsed
                }
                for r in replies
            ]
        except Exception as e:
            logger.error(f"❌ Failed to get signal replies: {str(e)}")
            return []
    
    # ==================== SYSTEM EVENTS ====================
    
    async def log_system_event(
        self,
        event_type: str,
        severity: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        module: Optional[str] = None,
        function: Optional[str] = None,
        stack_trace: Optional[str] = None
    ):
        """Log a system event"""
        try:
            await self.db.systemevent.create(
                data={
                    "eventType": event_type,
                    "severity": severity,
                    "message": message,
                    "details": json.dumps(details) if details else None,
                    "module": module,
                    "function": function,
                    "stackTrace": stack_trace
                }
            )
        except Exception as e:
            logger.error(f"❌ Failed to log system event: {str(e)}")
            # Don't raise - logging failures shouldn't stop execution

    async def get_split_siblings(self, channel_id: str, message_id: int):
        """Signals of the OTHER trades created from the same multi-signal post (synthetic message ids)."""
        from src.utils.split_ids import sibling_ids, is_split_id
        if int(message_id) <= 0 or is_split_id(message_id):
            return []
        try:
            return await self.db.signal.find_many(
                where={"channelId": str(channel_id), "messageId": {"in": sibling_ids(message_id)}}
            )
        except Exception as e:
            logger.debug(f"Could not look up split siblings of {message_id}: {e}")
            return []

    # ==================== CHANNEL CURSORS ====================

    async def get_channel_cursor(self, channel_id: str) -> Optional[int]:
        """Last handled Telegram message id for a channel (None if never recorded)."""
        try:
            row = await self.db.channelcursor.find_unique(where={"channelId": str(channel_id)})
            return int(row.lastMessageId) if row else None
        except Exception as e:
            logger.warning(f"Could not read channel cursor for {channel_id}: {e}")
            return None

    async def set_channel_cursor(self, channel_id: str, message_id: int, message_at=None) -> None:
        """Advance (never move backwards) the last handled message id for a channel."""
        try:
            existing = await self.db.channelcursor.find_unique(where={"channelId": str(channel_id)})
            if existing and int(existing.lastMessageId) >= int(message_id):
                return
            data = {"lastMessageId": int(message_id), "lastMessageAt": message_at}
            if existing:
                await self.db.channelcursor.update(where={"channelId": str(channel_id)}, data=data)
            else:
                await self.db.channelcursor.create(data={"channelId": str(channel_id), **data})
        except Exception as e:
            logger.warning(f"Could not save channel cursor for {channel_id}: {e}")

    # ==================== BRAIN DECISIONS ====================

    async def save_brain_signal_decision(
        self,
        symbol: str,
        verdict: str,
        reason: str,
        input_data: Dict[str, Any],
        output_data: Optional[Dict[str, Any]] = None,
        signal_id: Optional[str] = None,
        execution_ms: Optional[int] = None,
    ) -> Optional[str]:
        """Save a Brain signal-review decision to AIDecision. Returns decision_id."""
        try:
            # Map verdict → AIDecision.decision enum values
            decision_map = {"APPROVE": "APPROVED", "REJECT": "REJECTED", "MODIFY": "MODIFIED"}
            record = await self.db.aidecision.create(
                data={
                    "decisionType": "SIGNAL_REVIEW",
                    "decision": decision_map.get(verdict.upper(), verdict.upper()),
                    "confidence": 1.0,
                    "reason": reason[:500],
                    "inputData": json.dumps(input_data),
                    "outputData": json.dumps(output_data) if output_data else None,
                    "signalId": signal_id,
                    "symbol": symbol,
                    "executionTimeMs": execution_ms,
                }
            )
            logger.debug(f"🧠 Brain signal decision saved ({record.id[:8]}...)")
            return record.id
        except Exception as e:
            logger.error(f"❌ Failed to save brain signal decision: {e}")
            return None

    async def save_brain_position_action(
        self,
        symbol: str,
        action: str,
        reason: str,
        input_data: Dict[str, Any],
        output_data: Optional[Dict[str, Any]] = None,
        trade_id: Optional[str] = None,
        position_id: Optional[str] = None,
        outcome: str = "PENDING",
    ) -> Optional[str]:
        """Save a Brain position-review action to AIDecision. Returns decision_id."""
        try:
            record = await self.db.aidecision.create(
                data={
                    "decisionType": "POSITION_REVIEW",
                    "decision": action.upper(),
                    "confidence": 1.0,
                    "reason": reason[:500],
                    "inputData": json.dumps(input_data),
                    "outputData": json.dumps(output_data) if output_data else None,
                    "tradeId": trade_id,
                    "positionId": position_id,
                    "symbol": symbol,
                    "outcome": outcome,
                }
            )
            logger.debug(f"🧠 Brain position action saved ({record.id[:8]}...)")
            return record.id
        except Exception as e:
            logger.error(f"❌ Failed to save brain position action: {e}")
            return None

    async def update_brain_decision(
        self,
        decision_id: str,
        outcome: Optional[str] = None,
        profit_loss: Optional[float] = None,
        profit_loss_pips: Optional[float] = None,
        was_correct: Optional[bool] = None,
    ):
        """Update outcome fields on an AIDecision record."""
        try:
            data: Dict[str, Any] = {}
            if outcome is not None:
                data["outcome"] = outcome
            if profit_loss is not None:
                data["profitLoss"] = profit_loss
            if profit_loss_pips is not None:
                data["profitLossPips"] = profit_loss_pips
            if was_correct is not None:
                data["wasCorrect"] = was_correct
            if data:
                await self.db.aidecision.update(where={"id": decision_id}, data=data)
        except Exception as e:
            logger.error(f"❌ Failed to update brain decision {decision_id[:8]}...: {e}")


# Singleton instance
db_service = DatabaseService()
