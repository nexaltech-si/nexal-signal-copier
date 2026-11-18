"""
Reply actions that close or cancel the whole setup: close all, cancel pending
orders, partial close by percentage.

Part of ReplyHandlerService (src/services/reply_handler_service.py); methods were moved here verbatim.
Module-level names are this module's own imports: to patch one in a test,
patch it here, not in reply_handler_service.py.
"""
from typing import Optional, Dict, List
from datetime import datetime, timezone, timedelta
import re
from loguru import logger
from src.integrations.trading.provider_factory import create_trading_provider
from src.services.magic_number_service import magic_number_service
from src.services.spread_adjustment_service import spread_adjustment_service
from src.core.database_service import db_service
from src.services.trade_context_manager import trade_context_manager
from src.services.channel_behavior_service import channel_behavior_service


class ReplyCloseMixin:
    """Close all, cancel pending orders, partial close."""

    async def _close_all_orders(self, positions: List[Dict], orders: List[Dict], magic_number: int, command: str, db_trades: List[Dict] = None, reply_record_id: Optional[str] = None) -> Dict:
        """Close all positions and cancel all pending orders (including DB-only pending trades)"""
        logger.info(f"🔴 Targeted Close: Magic {magic_number} | Positions: {len(positions)} | Orders: {len(orders)}")
        try:
            total_closed = 0
            total_cancelled = 0
            errors = []

            # Track what we successfully processed in the provider
            successfully_closed_ids = set()
            successfully_cancelled_ids = set()
            
            # CRITICAL: Track which TRADE IDs were processed (not order/position IDs)
            # This prevents marking all trades as closed when they share the same order ID
            processed_trade_ids = set()
            
            # Get fresh list of all IDs currently in broker for comparison
            # This helps decide if a "not found" error means it's already closed
            metaapi_data = await self.trading_provider.get_all_trades_by_magic(magic_number)
            live_position_ids = {p['id'] for p in metaapi_data.get('positions', [])}
            live_order_ids = {o['id'] for o in metaapi_data.get('orders', [])}
            
            # CRITICAL: Build mapping of order/position IDs to trade IDs
            # This handles legacy data where multiple trades share the same order ID
            order_id_to_trade_ids = {}
            position_id_to_trade_ids = {}
            db_pending_order_ids = set()
            
            if db_trades is None:
                db_trades = await self.db.get_trades_by_magic_number(magic_number)
            
            for trade in db_trades:
                trade_id = trade['id']
                ord_id = trade.get('orderId')
                pos_id = trade.get('positionId')
                
                if ord_id:
                    if ord_id not in order_id_to_trade_ids:
                        order_id_to_trade_ids[ord_id] = []
                    order_id_to_trade_ids[ord_id].append(trade_id)
                
                if pos_id:
                    if pos_id not in position_id_to_trade_ids:
                        position_id_to_trade_ids[pos_id] = []
                    position_id_to_trade_ids[pos_id].append(trade_id)
                
                if trade.get('status') == 'PENDING' and ord_id:
                    db_pending_order_ids.add(ord_id)
                    logger.debug(f"📋 Trade {trade_id[:8]}... is PENDING - will cancel order {ord_id}")
            
            # Close all positions (skip if they're actually pending orders)
            position_data_map = {}  # Store position data before closing
            for position in positions:
                try:
                    position_id = position.get('id')
                    
                    # Skip if this is actually a pending order (legacy data bug)
                    if position_id in db_pending_order_ids:
                        logger.debug(f"⏭️ Skipping position {position_id} - it's actually a pending order")
                        continue
                    
                    # Store position data before closing (for accurate closure logging)
                    position_data_map[position_id] = {
                        'current_price': position.get('currentPrice'),
                        'profit': position.get('profit', 0),
                        'symbol': position.get('symbol')
                    }
                    
                    await self.trading_provider.close_position(position_id)
                    total_closed += 1
                    successfully_closed_ids.add(position_id)
                    
                    # CRITICAL: Mark only ONE trade as processed for this position ID
                    # (handles legacy bug where multiple trades share same position ID)
                    if position_id in position_id_to_trade_ids:
                        # Mark the first trade as processed, skip the rest
                        first_trade_id = position_id_to_trade_ids[position_id][0]
                        processed_trade_ids.add(first_trade_id)
                        logger.success(f"✅ Closed position {position_id} (trade {first_trade_id[:8]}...)")
                        if len(position_id_to_trade_ids[position_id]) > 1:
                            logger.warning(f"⚠️ Position {position_id} shared by {len(position_id_to_trade_ids[position_id])} trades - only marking first as closed")
                    else:
                        logger.success(f"✅ Closed position {position_id}")
                except Exception as e:
                    error_msg = str(e)
                    if 'not found' in error_msg.lower() or 'ERR_TRADE_POSITION_NOT_FOUND' in error_msg:
                        logger.warning(f"⚠️ Position {position_id} already closed")
                        successfully_closed_ids.add(position_id)
                        # Still mark first trade as processed
                        if position_id in position_id_to_trade_ids:
                            first_trade_id = position_id_to_trade_ids[position_id][0]
                            processed_trade_ids.add(first_trade_id)
                    else:
                        errors.append(f"Failed to close position {position_id}: {error_msg}")
                        logger.error(errors[-1])
            
            # Cancel all pending orders (including those from db_pending_order_ids)
            all_order_ids = {o.get('id') for o in orders} | db_pending_order_ids
            for order_id in all_order_ids:
                try:
                    await self.trading_provider.cancel_order(order_id)
                    total_cancelled += 1
                    successfully_cancelled_ids.add(order_id)
                    
                    # CRITICAL: Mark only ONE trade as processed for this order ID
                    # (handles legacy bug where multiple trades share same order ID)
                    if order_id in order_id_to_trade_ids:
                        # Mark the first trade as processed, skip the rest
                        first_trade_id = order_id_to_trade_ids[order_id][0]
                        processed_trade_ids.add(first_trade_id)
                        logger.success(f"✅ Cancelled pending order {order_id} (trade {first_trade_id[:8]}...)")
                        if len(order_id_to_trade_ids[order_id]) > 1:
                            logger.warning(f"⚠️ Order {order_id} shared by {len(order_id_to_trade_ids[order_id])} trades - only marking first as cancelled")
                    else:
                        logger.success(f"✅ Cancelled pending order {order_id}")
                except Exception as e:
                    error_msg = str(e)
                    if 'not found' in error_msg.lower() or 'ERR_TRADE_ORDER_NOT_FOUND' in error_msg:
                        logger.warning(f"⚠️ Order {order_id} no longer pending")
                        successfully_cancelled_ids.add(order_id)
                        # Still mark first trade as processed
                        if order_id in order_id_to_trade_ids:
                            first_trade_id = order_id_to_trade_ids[order_id][0]
                            processed_trade_ids.add(first_trade_id)
                    else:
                        errors.append(f"Failed to cancel order {order_id}: {error_msg}")
                        logger.error(errors[-1])
            
            # Update database
            if db_trades is None:
                db_trades = await self.db.get_trades_by_magic_number(magic_number)
            
            affected_trade_ids = []
            
            for trade in db_trades:
                trade_id = trade['id']
                current_status = trade.get('status')
                
                if current_status in ['CLOSED', 'FAILED', 'CANCELLED']:
                    continue
                
                pos_id = trade.get('positionId')
                ord_id = trade.get('orderId')
                
                # CRITICAL: Only update if this specific trade was processed
                # This prevents marking all trades as closed when they share the same order/position ID
                should_update_db = False
                action_type = None
                
                if trade_id in processed_trade_ids:
                    # This specific trade was processed
                    should_update_db = True
                    action_type = 'CANCEL' if current_status == 'PENDING' else 'CLOSE'
                    logger.debug(f"✅ Trade {trade_id[:8]}... was processed - will update DB")
                elif current_status == 'PENDING':
                    # Check if order is gone from broker (external cancellation)
                    if ord_id and ord_id not in live_order_ids:
                        should_update_db = True
                        action_type = 'CANCEL'
                        logger.debug(f"📋 Trade {trade_id[:8]}... order {ord_id} not in broker - marking as cancelled")
                else:
                    # Check if position is gone from broker (external closure)
                    if pos_id and pos_id not in live_position_ids:
                        should_update_db = True
                        action_type = 'CLOSE'
                        logger.debug(f"📋 Trade {trade_id[:8]}... position {pos_id} not in broker - marking as closed")
                
                if should_update_db and action_type:
                    affected_trade_ids.append(trade_id)
                    
                    pos_data = position_data_map.get(pos_id, {})
                    current_price = pos_data.get('current_price')
                    profit = pos_data.get('profit', 0)
                    
                    if current_status == 'PENDING':
                        await self.db.update_trade_fields(trade_id, {
                            'status': 'CANCELLED',
                            'closedAt': datetime.now(timezone.utc)
                        })
                    else:
                        await self.db.update_trade_closure(
                            trade_id=trade_id,
                            close_price=current_price,
                            profit_loss=profit
                        )
                    
                    # Log action
                    await self.db.log_trade_action(
                        trade_id=trade_id,
                        action_type=action_type,
                        success=True,
                        triggered_by='telegram_reply',
                        trigger_source='user_command_close',
                        details=f'User reply: "{command}" - {action_type.lower()}led via reply command. Profit: ${profit:.2f}'
                    )
                else:
                    logger.warning(f"⚠️ Trade {trade_id[:8]} not updated in DB: Broker position {pos_id or ord_id} still active")
            
            # Build result message
            result_parts = []
            if total_closed > 0:
                result_parts.append(f"Closed {total_closed} position(s)")
            if total_cancelled > 0:
                result_parts.append(f"Cancelled {total_cancelled} pending order(s)")
            
            message = " and ".join(result_parts) if result_parts else "No active trades were found to close"
            if errors:
                message += f" (Note: {len(errors)} errors occurred)"
            
            # Update signal status
            # First, check if we have specific signal IDs from db_trades
            signal_ids = set()
            if db_trades:
                for trade in db_trades:
                    if trade.get('signalId'):
                        signal_ids.add(trade['signalId'])
            
            # If no trades but we have a signal_id for this message, include it
            # This handles 'closing' a signal that never had trades (e.g. rejected)
            if not signal_ids:
                # Need to find signal_id from magic number if not provided
                signal_mapping = await self.db.db.messagemapping.find_first(
                    where={"magicNumber": magic_number}
                )
                if signal_mapping and signal_mapping.signalId:
                    signal_ids.add(signal_mapping.signalId)
            
            for signal_id in signal_ids:
                # Re-evaluate status based on trades
                await self.db.update_signal_status_from_trades(signal_id)
                
                # If it's still not terminal (e.g. no trades ever existed), 
                # but we are in a 'close all' command, force it to CLOSED
                signal = await self.db.db.signal.find_unique(where={"id": signal_id})
                if signal and signal.status not in ['CLOSED', 'CANCELLED', 'FAILED']:
                    logger.info(f"📝 Forcing signal {signal_id[:8]}... to CLOSED via reply command")
                    await self.db.update_signal_status(signal_id, "CLOSED")
            
            success = total_closed > 0 or total_cancelled > 0 or (not live_position_ids and not live_order_ids)
            
            return {
                "success": success,
                "message": message,
                "error": None if success else (errors[0] if errors else message),
                "closed_count": total_closed,
                "cancelled_count": total_cancelled,
                "affected_trade_ids": affected_trade_ids,
                "errors": errors if errors else None
            }

            
        except Exception as e:
            logger.error(f"❌ Failed to close orders: {str(e)}")
            return {"success": False, "error": str(e)}

    async def _cancel_pending_orders(self, orders: List[Dict], magic_number: int, command: str, reply_record_id: Optional[str] = None) -> Dict:
        """Cancel all pending orders (including database-only PENDING trades)"""
        try:
            cancelled_count = 0
            errors = []
            
            # Cancel all pending orders from broker (MetaAPI)
            for order in orders:
                try:
                    order_id = order.get('id')
                    logger.info(f"❌ Cancelling pending order {order_id}")
                    
                    # Cancel order via MetaAPI
                    await self.trading_provider.cancel_order(order_id)
                    cancelled_count += 1
                    
                except Exception as e:
                    error_msg = str(e)
                    # Check if order was already cancelled or filled
                    if 'not found' in error_msg.lower() or 'ERR_TRADE_ORDER_NOT_FOUND' in error_msg:
                        logger.warning(f"⚠️ Order {order_id} no longer pending (already filled/cancelled)")
                    else:
                        errors.append(f"Failed to cancel order {order_id}: {error_msg}")
                        logger.error(errors[-1])
            
            # Update database - mark all PENDING trades as CANCELLED (including database-only trades)
            db_trades = await self.db.get_trades_by_magic_number(magic_number)
            db_cancelled_count = 0
            
            for trade in db_trades:
                if trade.get('status') == 'PENDING':
                    await self.db.update_trade_field(trade['id'], 'status', 'CANCELLED')
                    await self.db.update_trade_field(trade['id'], 'closedAt', datetime.now())
                    await self.db.log_trade_action(
                        trade_id=trade['id'],
                        action_type='CANCEL',
                        success=True,
                        triggered_by='telegram_reply',
                        trigger_source='user_command_cancel',
                        details=f'User reply: "{command}" - Cancelled pending order'
                    )
                    db_cancelled_count += 1
                    logger.info(f"💾 Cancelled PENDING trade {trade['id'][:8]}... in database")
            
            # Update signal status for all affected signals
            affected_signal_ids = set(trade.get('signalId') for trade in db_trades if trade.get('signalId'))
            for signal_id in affected_signal_ids:
                try:
                    await self.db.update_signal_status_from_trades(signal_id)
                    logger.debug(f"📝 Updated signal {signal_id[:8]}... status after cancellation")
                except Exception as e:
                    logger.debug(f"Signal status update failed ({signal_id[:8]}...): {e}")
                try:
                    import random as _rnd
                    signal_forwarder_service = self.forwarder
                    # Cancelling the leftover limit of a signal whose other entry is live
                    # (or already closed) must not read "not entering this one" — the
                    # channel would think the whole trade is off while a position runs.
                    siblings = [t for t in db_trades if t.get('signalId') == signal_id]
                    if any(t.get('status') in ('RUNNING', 'EXECUTED') for t in siblings):
                        _cancel_text = _rnd.choice([
                            "cancelled the remaining limit order — still running on the filled entry",
                            "pulled the unfilled limit, the open position stays on",
                            "leftover pending order removed — trade is still live",
                            "limit order cancelled, holding the running entry",
                        ])
                    elif any(t.get('status') == 'CLOSED' for t in siblings):
                        _cancel_text = _rnd.choice([
                            "removed the unfilled limit order, nothing left open on this one",
                            "leftover pending order cancelled — filled entry was already closed",
                        ])
                    else:
                        _cancel_text = _rnd.choice([
                            "order cancelled, not entering this one",
                            "cancelled — sitting this one out",
                            "pending order deleted, skipping this trade",
                            "called off — order cancelled",
                            "not taking this one, order removed",
                            "cancelled the pending order on this",
                            "out before we got in — order cancelled",
                        ])
                    await signal_forwarder_service.reply_action(signal_id, _cancel_text, action_type="pending_cancelled")
                except Exception as e:
                    logger.debug(f"Forwarder cancel reply failed ({signal_id[:8]}...): {e}")
            
            # Calculate total cancelled (broker cancelled count, or db cancelled count if broker had none)
            total_cancelled = max(cancelled_count, db_cancelled_count)
            
            if total_cancelled == 0:
                return {
                    "success": True,
                    "message": "No pending orders to cancel",
                    "cancelled_count": 0
                }
            
            success = total_cancelled > 0 or (not orders and db_cancelled_count == 0)
            
            return {
                "success": success,
                "message": f"Cancelled {total_cancelled} pending order(s)",
                "error": None if success else (errors[0] if errors else "Failed to cancel any pending orders"),
                "total_cancelled": total_cancelled,
                "cancelled_count": total_cancelled, # for backward compatibility
                "broker_cancelled": cancelled_count,
                "db_cancelled": db_cancelled_count,
                "errors": errors if errors else None
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to cancel orders: {str(e)}")
            return {"success": False, "error": str(e)}

    async def _partial_close_by_percentage(self, positions: List[Dict], percentage: float, magic_number: int, command: str = "partial close", protect_kept: bool = True) -> Dict:
        """
        Helper to close positions by percentage.

        protect_kept: a position too small to split is moved to break-even instead.
        False leaves it exactly as it is ("Can booked some" — an offer, not an order).
        """
        try:
            closed_count = 0
            errors = []
            kept_whole: List[Dict] = []      # too small to split: kept open, protected instead
            
            for position in positions:
                try:
                    position_id = position.get('id')
                    symbol = position.get('symbol')
                    
                    # Log position data for debugging
                    logger.debug(f"Position data for {position_id}: {position}")
                    
                    # MetaAPI uses 'volume' field for position size
                    current_volume = position.get('volume', 0)
                    
                    if current_volume == 0:
                        logger.warning(f"⚠️ Position {position_id} has zero volume! Available keys: {position.keys()}")
                        continue
                    
                    logger.info(f"📊 Position {position_id}: Current volume = {current_volume} lots")
                    
                    # Get symbol specification for proper validation
                    spec = await self.trading_provider.get_symbol_specification(symbol)
                    volume_step = spec.get('volumeStep', 0.01)
                    volume_min = spec.get('volumeMin', 0.01)
                    
                    # Calculate close volume
                    close_volume_raw = current_volume * (percentage / 100)
                    logger.debug(f"   Calculated close volume: {close_volume_raw} ({percentage}% of {current_volume})")
                    
                    # Round to broker's volume step for this symbol
                    close_volume = await self.trading_provider.round_lot_size(symbol, close_volume_raw)
                    logger.debug(f"   Rounded close volume: {close_volume} (step={volume_step})")
                    
                    # Count in whole volume steps, not float lots: 0.03 - 0.02 is
                    # 0.00999…, which failed the minimum-lot check although 0.01 is
                    # a valid remainder.
                    step = volume_step or 0.01
                    total_steps = round(current_volume / step)
                    close_steps = min(round(close_volume / step), total_steps)
                    min_steps = max(1, round(volume_min / step))
                    if 0 < total_steps - close_steps < min_steps:
                        # Leave the broker minimum open rather than refuse the partial close.
                        close_steps = total_steps - min_steps
                    close_volume = round(close_steps * step, 8)
                    remaining_volume = round((total_steps - close_steps) * step, 8)
                    logger.debug(f"   Remaining volume: {remaining_volume} lots")

                    # A partial close never closes a position whole. A position at the
                    # broker minimum (0.01) cannot be split: rounding the part to close up
                    # to the minimum took all of it, so "close half" closed 75% of a setup
                    # (scripted history, 2026-11-13). It stays open and is moved to
                    # break-even below instead.
                    if percentage < 100 and (close_steps >= total_steps or close_steps < min_steps):
                        logger.info(f"   Position {position_id}: {current_volume} lots cannot be split — kept open")
                        kept_whole.append(position)
                        continue

                    # Validate minimum lot sizes
                    if close_steps < min_steps:
                        error_msg = f"Position {position_id}: {current_volume} lots is too small to close {percentage}% - both parts must be at least {volume_min} lots"
                        errors.append(error_msg)
                        logger.warning(f"⚠️ {error_msg}")
                        continue
                    
                    if close_volume > 0:
                        logger.info(f"   Attempting to partially close {position_id}:")
                        logger.info(f"   - Symbol: {symbol}")
                        logger.info(f"   - Current volume: {current_volume} lots")
                        logger.info(f"   - Close volume: {close_volume} lots")
                        logger.info(f"   - Will remain: {remaining_volume} lots")
                        
                        await self.trading_provider.close_position(position_id, volume=close_volume)
                        closed_count += 1
                        logger.success(f"✅ Partially closed {position_id}: {close_volume} lots ({percentage}%)")
                        
                        # Log the partial close action to database
                        db_trades = await self.db.get_trades_by_magic_number(magic_number)
                        for trade in db_trades:
                            if trade.get('positionId') == position_id:
                                await self.db.log_trade_action(
                                    trade_id=trade['id'],
                                    action_type='PARTIAL_CLOSE',
                                    success=True,
                                    triggered_by='telegram_reply',
                                    trigger_source='user_command_partial_close',
                                    details=f'User reply: "{command}" - Partially closed {percentage}% ({close_volume} of {current_volume} lots). Remaining: {remaining_volume} lots'
                                )
                                logger.debug(f"💾 Logged PARTIAL_CLOSE action for trade {trade['id'][:8]}...")
                    
                except Exception as e:
                    errors.append(f"Failed to partially close {position_id}: {str(e)}")
                    logger.error(errors[-1])
            
            message = f"Partially closed {closed_count} position(s) by {percentage}%"
            protected = 0
            if kept_whole and not protect_kept:
                logger.info(f"   {len(kept_whole)} position(s) at the minimum lot left as they are")
                message += f"; {len(kept_whole)} position(s) at the minimum lot were not closed and stay as they are"
            elif kept_whole:
                try:
                    be = await self._move_to_breakeven(kept_whole, magic_number, None, [])
                    protected = 1 if isinstance(be, dict) and be.get('success') else 0
                    if not protected:
                        logger.info(f"   Break-even for the kept positions not applied: {be.get('error') if isinstance(be, dict) else be}")
                except Exception as e:
                    logger.warning(f"⚠️ Could not move the kept minimum-lot positions to break-even: {e}")
                message += (f"; {len(kept_whole)} position(s) at the minimum lot were not closed"
                            + (" — moved to break-even instead" if protected else " and stay as they are"))

            success = closed_count > 0 or bool(kept_whole) or not positions
            
            return {
                "success": success,
                "message": message,
                "kept_whole": len(kept_whole),
                "error": None if success else (errors[0] if errors else f"Failed to partially close any positions by {percentage}%"),
                "closed_count": closed_count,
                "percentage": percentage,
                "errors": errors if errors else None
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to partial close: {str(e)}")
            return {"success": False, "error": str(e)}
