"""
Edited signal messages: re-extract and apply the changed levels to the
signal's orders.

Part of MessageHandler (src/services/message_handler.py); methods were moved here verbatim.
Module-level names are this module's own imports: to patch one in a test,
patch it here, not in message_handler.py.
"""
import re
import time
import asyncio
from typing import Optional, Dict, List
from datetime import datetime
from loguru import logger
from src.utils.tasks import spawn
from src.utils.split_ids import real_message_id
from src.models import TradingSignal, SignalAction, OrderType, SignalStatus
from src.models.message import MessageIdentifier
from src.services.trade_mapper import trade_mapper
from src.services.signal_service import signal_service
from src.services.reply_handler_service import reply_handler_service
from src.services.spread_adjustment_service import spread_adjustment_service
from src.services.channel_behavior_service import channel_behavior_service
from src.services.trade_context_manager import trade_context_manager
from src.services.split_post import SplitPostTracker
from src.services.action_results import partial_failures, failure_block, log_partial_failure
from src.core.database_service import db_service
from src.integrations.trading.provider_factory import create_trading_provider


class SignalEditMixin:
    """Apply edits of signal messages to their orders."""

    async def _handle_signal_edit(self, old_signal, new_signal, message_id: MessageIdentifier):
        """
        Handle edited signal message - update SL/TP on existing orders
        
        Args:
            old_signal: Existing signal from database
            new_signal: New signal extracted from edited message
            message_id: Message identifier
        """
        try:
            from src.integrations.trading.provider_factory import create_trading_provider
            trading_provider = create_trading_provider()
            
            logger.info("🔄 Comparing signals for changes...")
            
            # Get all trades for this signal
            trades = await db_service.db.trade.find_many(
                where={"signalId": old_signal.id}
            )
            
            if not trades:
                logger.warning("No trades found for this signal")
                return
            
            logger.info(f"Found {len(trades)} trade(s) to potentially update")
            
            # Check what changed
            sl_changed = False
            tp_changed = False
            close_requested = False
            
            old_sl = old_signal.stopLoss
            new_sl = new_signal.stop_loss
            old_tp = old_signal.takeProfit
            new_tp = new_signal.take_profit
            
            # Detect changes
            if new_sl and old_sl and abs(new_sl - old_sl) > 0.00001:
                sl_changed = True
                logger.info(f"🔴 SL changed: {old_sl} → {new_sl}")
            
            if new_tp and old_tp:
                # Handle both single and multi-TP
                old_tp_str = str(old_tp)
                new_tp_str = str(new_tp) if isinstance(new_tp, (int, float)) else str(new_tp)
                if old_tp_str != new_tp_str:
                    tp_changed = True
                    logger.info(f"🟢 TP changed: {old_tp} → {new_tp}")
            
            # Check if message contains an explicit close command (word-boundary
            # match with candle/entry-context suppression — a substring check here
            # once closed positions on "if price closes below 4420")
            edited_text = new_signal.raw_message if hasattr(new_signal, 'raw_message') else ""
            if self._is_explicit_close_command(edited_text):
                close_requested = True
                logger.info("🔴 Close detected in edited message")
            
            # Apply changes to all trades
            updated_count = 0
            closed_count = 0
            
            for trade in trades:
                try:
                    position_id = trade.positionId
                    
                    if not position_id:
                        logger.debug(f"Trade {trade.id} has no position ID, skipping")
                        continue
                    
                    if close_requested:
                        # Close the position
                        logger.info(f"🔴 Closing position {position_id}")
                        
                        # Fetch current position data BEFORE closing
                        current_price = None
                        profit_pips = None
                        total_profit = 0
                        try:
                            provider_positions = await self.trading_provider.get_open_positions(use_cache=False)
                            live_position = next((p for p in provider_positions if p.get('id') == position_id), None)
                            if live_position:
                                current_price = live_position.get('currentPrice')
                                # CRITICAL: 'profit' already includes unrealizedProfit
                                total_profit = live_position.get('profit', 0)
                                
                                # Calculate pips
                                open_price = live_position.get('openPrice')
                                if current_price and open_price:
                                    symbol = live_position.get('symbol')
                                    from src.utils.pip_utils import get_pip_size
                                    pip_value = get_pip_size(symbol)
                                    price_diff = current_price - open_price
                                    if live_position.get('type') == 'POSITION_TYPE_SELL':
                                        price_diff = -price_diff
                                    profit_pips = price_diff / pip_value
                        except Exception as fetch_error:
                            logger.debug(f"Could not fetch live position data: {fetch_error}")
                        
                        await self.trading_provider.close_position(position_id)
                        
                        # Update trade with closure data including profit/loss
                        await db_service.update_trade_closure(
                            trade_id=trade.id,
                            close_price=current_price,
                            profit_loss=total_profit,
                            profit_loss_pips=profit_pips
                        )
                        
                        # Log action with live data
                        await db_service.create_trade_action(
                            trade_id=trade.id,
                            action_type='CLOSE',
                            success=True,
                            current_price=current_price,
                            profit_pips=profit_pips,
                            triggered_by='message_edit',
                            trigger_source=f"edited_message_{message_id.message_id}",
                            details=f"Position closed via edited message. Profit: ${total_profit:.2f}" + (f" ({profit_pips:+.1f} pips)" if profit_pips else "")
                        )
                        
                        closed_count += 1
                        
                    elif sl_changed or tp_changed:
                        # Check BOTH pending orders and open positions to determine what this is
                        pending_orders = await trading_provider.get_all_pending_orders(use_cache=False)
                        pending_orders = pending_orders or []
                        open_positions = await trading_provider.get_open_positions(use_cache=False)
                        open_positions = open_positions or []
                        
                        logger.debug(f"Checking position {position_id} - found {len(pending_orders)} pending orders and {len(open_positions)} open positions")
                        
                        pending_order = next((o for o in pending_orders if str(o.get('id')) == str(position_id)), None)
                        open_position = next((p for p in open_positions if str(p.get('id')) == str(position_id)), None)
                        
                        if pending_order:
                            # For pending orders, modify SL/TP directly
                            logger.info(f"📝 Modifying pending order {position_id}")
                            
                            # Get order's entry price (required by MT5 for modification)
                            order_price = pending_order.get('openPrice')

                            # Determine new SL/TP (always use current values to avoid removing them)
                            final_sl = new_sl if sl_changed else pending_order.get('stopLoss')
                            final_tp = new_tp if tp_changed else pending_order.get('takeProfit')

                            # Apply spread adjustment to the new SL. This mirrors the
                            # open-position branch below — without it, an edited SL on a
                            # PENDING order goes to the broker raw, risking immediate
                            # stop-out on spread once the order fills. adjust_sl_for_position
                            # can't be used here (it searches open positions only), so
                            # resolve symbol+direction from the pending order itself.
                            if sl_changed and final_sl:
                                _order_is_buy = 'BUY' in (pending_order.get('type') or '')
                                _adjusted_sl = await spread_adjustment_service.adjust_sl_for_spread(
                                    pending_order.get('symbol'),
                                    final_sl,
                                    _order_is_buy
                                )
                                if _adjusted_sl != final_sl:
                                    logger.info(f"📊 Pending order SL adjusted for spread: {final_sl:.5f} → {_adjusted_sl:.5f}")
                                    final_sl = _adjusted_sl

                            if sl_changed:
                                logger.info(f"   New SL: {final_sl}")
                            if tp_changed:
                                logger.info(f"   New TP: {final_tp}")
                            
                            try:
                                # Check if provider supports modify_order
                                if hasattr(trading_provider, 'modify_order'):
                                    # Use modify_order endpoint (MT5 requires price to be sent)
                                    # IMPORTANT: Always send both SL and TP, otherwise MT5 will remove the one not sent
                                    await trading_provider.modify_order(
                                        position_id,
                                        stop_loss=final_sl,
                                        take_profit=final_tp,
                                        price=order_price  # Required by MT5 even when only modifying SL/TP
                                    )
                                    
                                    logger.success(f"✅ Pending order {position_id} modified")
                                    
                                    # Update database with new SL/TP
                                    if sl_changed:
                                        await db_service.update_trade_field(trade.id, 'stopLoss', final_sl)
                                    if tp_changed:
                                        await db_service.update_trade_field(trade.id, 'takeProfit', final_tp)
                                    
                                    # Log action with formatted details
                                    details_parts = []
                                    if sl_changed:
                                        details_parts.append(f"SL: {old_sl:.5f}→{final_sl:.5f}")
                                    if tp_changed:
                                        details_parts.append(f"TP: {old_tp}→{final_tp}")
                                    details = "Pending order modified - " + ", ".join(details_parts)
                                    
                                    await db_service.create_trade_action(
                                        trade_id=trade.id,
                                        action_type='MODIFY_SL' if sl_changed else 'MODIFY_TP',
                                        success=True,
                                        old_stop_loss=old_sl if sl_changed else None,
                                        new_stop_loss=final_sl if sl_changed else None,
                                        old_take_profit=float(old_tp) if tp_changed and old_tp else None,
                                        new_take_profit=float(final_tp) if tp_changed and final_tp else None,
                                        triggered_by='message_edit',
                                        trigger_source=f"edited_message_{message_id.message_id}",
                                        details=details
                                    )
                                    
                                    updated_count += 1
                                else:
                                    logger.warning(f"⚠️ Order modification not supported for {type(trading_provider).__name__}")
                                    continue
                                    
                            except Exception as order_error:
                                logger.error(f"❌ Failed to modify pending order: {order_error}")
                                continue
                        
                        elif open_position:
                            # This is an open position (not a pending order)
                            
                            # Modify the position (not a pending order)
                            current_sl = trade.stopLoss if not sl_changed else new_sl
                            current_tp = trade.takeProfit if not tp_changed else (
                                new_tp if isinstance(new_tp, (int, float)) else None
                            )

                            # Apply spread adjustment if SL changed. Use a per-position
                            # local (position_sl) rather than mutating the loop-shared
                            # new_sl — otherwise each successive position would re-adjust
                            # the already-adjusted value, compounding the offset.
                            position_sl = new_sl
                            if sl_changed:
                                adjusted_sl = await spread_adjustment_service.adjust_sl_for_position(
                                    position_id,
                                    new_sl
                                )
                                if adjusted_sl != new_sl:
                                    logger.info(f"📊 SL adjusted for spread: {new_sl:.5f} → {adjusted_sl:.5f}")
                                    position_sl = adjusted_sl

                            logger.info(f"✏️ Modifying position {position_id}")
                            if sl_changed:
                                logger.info(f"   New SL: {position_sl}")
                            if tp_changed:
                                logger.info(f"   New TP: {current_tp}")

                            try:
                                await trading_provider.modify_position(
                                    position_id,
                                    stop_loss=position_sl if sl_changed else current_sl,
                                    take_profit=current_tp
                                )

                                # Update database
                                if sl_changed:
                                    await db_service.update_trade_field(trade.id, 'stopLoss', position_sl)
                                if tp_changed and current_tp:
                                    await db_service.update_trade_field(trade.id, 'takeProfit', current_tp)
                            except ValueError as e:
                                logger.warning(f"⚠️ Cannot modify position {position_id}: {str(e)}")
                                continue

                            # Log action with formatted details
                            details_parts = []
                            if sl_changed:
                                details_parts.append(f"SL: {old_sl:.5f}→{position_sl:.5f}")
                            if tp_changed:
                                details_parts.append(f"TP: {old_tp}→{current_tp}")
                            details = "Position modified - " + ", ".join(details_parts)

                            await db_service.create_trade_action(
                                trade_id=trade.id,
                                action_type='MODIFY_SL' if sl_changed else 'MODIFY_TP',
                                success=True,
                                old_stop_loss=old_sl if sl_changed else None,
                                new_stop_loss=position_sl if sl_changed else None,
                                old_take_profit=float(old_tp) if tp_changed and old_tp else None,
                                new_take_profit=float(current_tp) if tp_changed and current_tp else None,
                                triggered_by='message_edit',
                                trigger_source=f"edited_message_{message_id.message_id}",
                                details=details
                            )
                            
                            updated_count += 1
                        
                        else:
                            # Not found in either pending orders or open positions
                            logger.warning(f"⚠️ Position {position_id} not found in {len(pending_orders)} pending orders or {len(open_positions)} open positions - may have been closed or is stale")
                            logger.debug(f"   Pending order IDs: {[str(o.get('id')) for o in pending_orders[:5]]}")
                            logger.debug(f"   Open position IDs: {[str(p.get('id')) for p in open_positions[:5]]}")
                            continue
                
                except Exception as e:
                    logger.error(f"Failed to update trade {trade.id}: {str(e)}")
                    continue
            
            # Update the signal in database with new values
            if sl_changed or tp_changed or close_requested:
                update_data = {}
                if sl_changed:
                    update_data['stopLoss'] = new_sl
                if tp_changed:
                    update_data['takeProfit'] = str(new_tp)
                
                if update_data:
                    await db_service.db.signal.update(
                        where={"id": old_signal.id},
                        data=update_data
                    )
            
            # Summary
            if close_requested:
                logger.success(f"✅ Closed {closed_count} position(s) via edited message")
            elif updated_count > 0:
                logger.success(f"✅ Updated {updated_count} position(s) via edited message")
            else:
                logger.info("No changes to apply")

            # Forward edit reply to signal channel
            if (sl_changed or tp_changed) and updated_count > 0:
                try:
                    from src.services.signal_forwarder_service import signal_forwarder_service
                    await signal_forwarder_service.reply_signal_edited(
                        old_signal.id, sl_changed, tp_changed, new_sl, new_tp
                    )
                except Exception as _exc:
                    logger.debug(f"Suppressed exception: {_exc!r}")
                
        except Exception as e:
            logger.error(f"❌ Error handling signal edit: {str(e)}")
            logger.exception(e)
