"""
Trade updates: management messages for a running signal routed to the reply
handler, with the fallbacks around it.

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


class TradeUpdateMixin:
    """Route trade-management messages for running signals."""

    async def _handle_trade_update(
        self,
        event,
        message_id: MessageIdentifier,
        content: str,
        signal_callback=None,
        image_data: Optional[bytes] = None,
    ):
        """Handle trade update/modification"""
        
        # Track message pattern for learning (async, non-blocking)
        try:
            message_type = "REPLY" if self._is_reply(event) else "UPDATE"
            # Extract symbol and action from content if possible
            symbol = None
            action = None
            if "close" in content.lower():
                action = "CLOSE"
            elif "modify" in content.lower() or "move" in content.lower():
                action = "MODIFY"
            
            # Track pattern asynchronously (don't await to avoid blocking)
            spawn(
                channel_behavior_service.track_message_pattern(
                    channel_id=str(message_id.chat_id),
                    message_text=content,
                    message_type=message_type,
                    symbol=symbol,
                    action=action
                )
            )
        except Exception as e:
            logger.debug(f"Could not track message pattern: {e}")

        # The owner's per-channel rules (dashboard → Channel Rules)
        matched_rule = await channel_behavior_service.match_rule(str(message_id.chat_id), content)
        if matched_rule and matched_rule['actionType'] == 'IGNORE':
            logger.info(f"🔇 Ignoring message due to channel rule: {matched_rule['ruleName']}")
            await channel_behavior_service.record_success(matched_rule['id'])
            if self._is_reply(event):
                # Shows up in the dashboard's Channel Rules activity feed
                reply_id = await db_service.create_signal_reply(
                    chat_id=str(message_id.chat_id),
                    reply_message_id=message_id.message_id,
                    reply_to_message_id=event.message.reply_to.reply_to_msg_id,
                    reply_text=content,
                )
                if reply_id:
                    await db_service.update_signal_reply_action(
                        reply_id=reply_id,
                        action_taken=False,
                        action_type="RULE_IGNORED",
                        action_success=True,
                        action_result=f"Ignored by channel rule '{matched_rule['ruleName']}'",
                        action_details={"channel_rule": {
                            "id": matched_rule['id'], "name": matched_rule['ruleName'],
                            "actionType": 'IGNORE', "aiAction": None, "followed": True,
                        }},
                    )
            return

        # Check if this is a reply (with reply_to_msg_id)
        if self._is_reply(event):
            reply_to_msg_id = event.message.reply_to.reply_to_msg_id
            chat_id = str(message_id.chat_id)

            # Extract user info if available
            user_id = None
            username = None
            try:
                if hasattr(event.message, 'sender_id') and event.message.sender_id:
                    user_id = str(event.message.sender_id)
                if hasattr(event.message, 'sender') and event.message.sender:
                    sender = event.message.sender
                    if hasattr(sender, 'username') and sender.username:
                        username = sender.username
                    elif hasattr(sender, 'first_name') and sender.first_name:
                        username = sender.first_name
            except Exception as e:
                logger.debug(f"Could not extract user info: {e}")
            
            logger.info(f"🔄 Processing reply to message {reply_to_msg_id}")

            # Try to get channel name from Telegram event
            channel_name = None
            try:
                chat = await event.get_chat()
                channel_name = getattr(chat, 'title', None) or getattr(chat, 'first_name', None)
            except Exception as _exc:
                logger.debug(f"Suppressed exception: {_exc!r}")

            # Use reply handler service to process the command
            result = await reply_handler_service.handle_reply(
                reply_to_message_id=reply_to_msg_id,
                chat_id=chat_id,
                command=content,
                reply_message_id=message_id.message_id,
                user_id=user_id,
                username=username,
                channel_name=channel_name,
                image_data=image_data,
                channel_rule=matched_rule,
            )

            # Build rich context line for all notifications
            def _reply_context() -> str:
                parts = []
                ch = result.get('channel_name') or channel_name
                sym = result.get('symbol')
                if ch:
                    parts.append(f"📡 <b>Channel:</b> {ch}")
                if sym:
                    parts.append(f"📊 <b>Symbol:</b> {sym}")
                if username:
                    parts.append(f"👤 <b>By:</b> @{username}")
                parts.append(f"💬 <b>Cmd:</b> {content}")
                if matched_rule:
                    parts.append(f"📐 <b>Rule:</b> {matched_rule['ruleName']}")
                return "\n".join(parts)

            if result.get('success'):
                if result.get('ignored'):
                    logger.debug("💬 Reply ignored by AI (not a command)")
                    # A fresh entry posted as a reply ("Re-enter sell 4125 SL 4145") while the
                    # original trade is still open — hand it to the new-signal extractor.
                    if self._looks_like_entry_with_levels(content):
                        if await self._try_signal_from_reply(event, message_id, reply_to_msg_id, content, signal_callback, image_data):
                            return
                else:
                    failures = partial_failures(result)
                    if failures:
                        log_partial_failure(failures, f"Reply command '{content}'")
                    else:
                        logger.success(f"✅ {result.get('message')}")
                    try:
                        from src.integrations.telegram.unified_sender import notification_sender
                        if failures:
                            msg = (f"⚠️ <b>Command Partly Executed</b>\n\n{_reply_context()}\n\n"
                                   f"{result.get('message', '')}{failure_block(failures)}")
                        else:
                            msg = f"✅ <b>Command Executed</b>\n\n{_reply_context()}"
                        await notification_sender.send_message(msg, category='command_response')
                    except Exception as e:
                        logger.warning(f"Could not send confirmation: {str(e)}")
            else:
                # Extract error from 'error' key or first item in 'errors' list
                error_msg = result.get('error')
                if not error_msg and result.get('errors'):
                    error_msg = result.get('errors')[0]
                if not error_msg:
                    error_msg = 'Unknown error'

                # Downgrade "no active trades" to warning (expected when replying to closed trades)
                if 'No active positions or pending orders found' in error_msg:
                    logger.warning(f"⚠️ Reply to closed trade: {error_msg}")
                    # "Reenter" replies re-open the original trade (typical after SL hit)
                    if await self._try_reenter_from_reply(event, message_id, reply_to_msg_id, content, signal_callback, image_data):
                        return
                    # The reply may carry a brand-new signal (providers often post fresh
                    # entries as replies to their old signals) — try full extraction
                    if await self._try_signal_from_reply(event, message_id, reply_to_msg_id, content, signal_callback, image_data):
                        return
                    # Suppressed: no Telegram notification for missing-trade replies (reduces noise)
                # Downgrade "could not understand" to info (likely informational messages)
                elif 'Could not understand command' in error_msg:
                    logger.info(f"💬 Unrecognized message (likely info/commentary): {error_msg}")
                    if await self._try_reenter_from_reply(event, message_id, reply_to_msg_id, content, signal_callback, image_data):
                        return
                    if await self._try_signal_from_reply(event, message_id, reply_to_msg_id, content, signal_callback, image_data):
                        return
                    # Suppressed: no Telegram notification for unrecognized messages (reduces noise)
                else:
                    logger.error(f"❌ Reply handler failed: {error_msg}")
                    # Send error to notification channel only for real failures
                    try:
                        from src.integrations.telegram.unified_sender import notification_sender
                        suggestion = result.get('suggestion', '')
                        response = (
                            f"❌ <b>Command Failed</b>\n\n"
                            f"{_reply_context()}\n\n"
                            f"⚠️ {error_msg}"
                        )
                        if suggestion:
                            response += f"\n\n💡 {suggestion}"
                        await notification_sender.send_message(response, category='command_response')
                    except Exception as e:
                        logger.warning(f"Could not send error message: {str(e)}")
            
            return
        
        # Not a direct reply - try to find related trade by content and execute command
        # Extract signal to understand the command
        message_date = getattr(event.message, 'date', None)
        signal = await signal_service.extract_signal(
            message_text=content,
            channel_id=str(message_id.chat_id),
            message_id=message_id.message_id,
            message_date=message_date
        )
        
        if not signal:
            logger.warning("⚠️ Could not extract signal from update message")
            return
        
        # Handle CLOSE action specifically
        if signal.action == SignalAction.CLOSE and signal.symbol:
            logger.info(f"🔴 Executing CLOSE command for {signal.symbol} in channel {signal.channel_id}")
            
            # Get all open positions for this symbol FROM THIS CHANNEL ONLY
            from src.integrations.trading.provider_factory import create_trading_provider
            trading_provider = create_trading_provider()
            
            try:
                # Find trades for this symbol in this specific channel
                positions = await db_service.get_open_positions_by_symbol(
                    symbol=signal.symbol,
                    channel_id=signal.channel_id
                )
                
                if not positions:
                    logger.warning(f"⚠️ No open positions found for {signal.symbol} in channel {signal.channel_id}")
                    return
                
                # SAFETY CHECK: If multiple positions found but it's NOT a reply, 
                # we must be sure the user wants to close ALL, otherwise it's ambiguous and dangerous.
                msg_content_upper = content.upper()
                is_global_close = self._is_global_close(content)
                
                if len(positions) > 1 and not is_global_close:
                    logger.warning(f"⚠️ AMBIGUOUS CLOSE: {len(positions)} positions found for {signal.symbol} but 'ALL' keyword missing and not a reply.")
                    # Notify user about the ambiguity
                    try:
                        from src.integrations.telegram.unified_sender import notification_sender
                        await notification_sender.send_notification(
                            f"⚠️ <b>Ambiguous Close</b>\n\n"
                            f"📊 <b>{signal.symbol}</b> — {len(positions)} active trades found.\n\n"
                            f"<b>To close the right one:</b>\n"
                            f"1. Reply directly to the signal message.\n"
                            f"2. Or type: <code>Close ALL {signal.symbol}</code>",
                            category='command_response'
                        )
                    except Exception as e:
                        logger.warning(f"Could not send ambiguity notification: {str(e)}")
                    return
                
                closed_count = 0
                already_closed_count = 0
                
                if is_global_close:
                    logger.info(f"🔴 Global close confirmed for {len(positions)} positions of {signal.symbol}")
                elif len(positions) == 1:
                    logger.info(f"🔴 targeted close for single position of {signal.symbol}")

                
                for position in positions:
                    try:
                        position_id = position.get('position_id')
                        order_id = position.get('order_id')
                        trade_id = position.get('trade_id')
                        signal_id = position.get('signal_id')
                        trade_status = position.get('status')
                        
                        # Handle active positions
                        if position_id:
                            logger.info(f"🔴 Closing position {position_id} for {signal.symbol} (channel: {signal.channel_id})")
                            try:
                                # Fetch current position data from MetaAPI BEFORE closing
                                current_price = None
                                profit_pips = None
                                total_profit = 0
                                try:
                                    metaapi_positions = await trading_provider.get_open_positions()
                                    live_position = next((p for p in metaapi_positions if p.get('id') == position_id), None)
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
                                
                                await trading_provider.close_position(position_id)
                                
                                # Update trade with closure data including profit/loss
                                await db_service.update_trade_closure(
                                    trade_id=trade_id,
                                    close_price=current_price,
                                    profit_loss=total_profit,
                                    profit_loss_pips=profit_pips
                                )
                                
                                # Log action with live data
                                await db_service.create_trade_action(
                                    trade_id=trade_id,
                                    action_type='CLOSE',
                                    success=True,
                                    current_price=current_price,
                                    profit_pips=profit_pips,
                                    triggered_by='content_detection',
                                    trigger_source=f"message_{message_id.message_id}",
                                    details=f"Position closed via content-based close detection (channel-specific): {content[:100]}. Profit: ${total_profit:.2f}" + (f" ({profit_pips:+.1f} pips)" if profit_pips else "")
                                )
                                
                                closed_count += 1
                            except Exception as pos_error:
                                error_msg = str(pos_error)
                                # Check if position was already closed
                                if 'not found' in error_msg.lower() or 'ERR_TRADE_POSITION_NOT_FOUND' in error_msg:
                                    logger.warning(f"⚠️ Position {position_id} already closed (not found on broker)")
                                    # Update database to reflect it's closed (without profit/loss data since position not found)
                                    await db_service.update_trade_closure(
                                        trade_id=trade_id,
                                        close_price=None,
                                        profit_loss=None,
                                        profit_loss_pips=None
                                    )
                                    
                                    # Log the closure
                                    await db_service.log_trade_action(
                                        trade_id=trade_id,
                                        action_type='CLOSE',
                                        success=True,
                                        triggered_by='content_detection',
                                        trigger_source=f'message_{message_id.message_id}_already_closed',
                                        details='Position already closed externally - not found on broker'
                                    )
                                    already_closed_count += 1
                                else:
                                    logger.error(f"❌ Failed to close position {position_id}: {error_msg}")
                                    raise
                        
                        # Handle pending orders
                        elif order_id:
                            logger.info(f"🔴 Cancelling pending order {order_id} for {signal.symbol} (channel: {signal.channel_id})")
                            try:
                                await trading_provider.cancel_order(order_id)
                                
                                # Update trade status in database
                                await db_service.update_trade_field(trade_id, 'status', 'CANCELLED')
                                await db_service.update_trade_field(trade_id, 'closedAt', datetime.now())
                                
                                # Update signal status
                                if signal_id:
                                    try:
                                        await db_service.update_signal_status_from_trades(signal_id)
                                    except Exception as e:
                                        logger.debug(f"Signal status update failed ({signal_id[:8]}...): {e}")
                                
                                # Log action
                                await db_service.create_trade_action(
                                    trade_id=trade_id,
                                    action_type='CANCEL',
                                    success=True,
                                    triggered_by='content_detection',
                                    trigger_source=f"message_{message_id.message_id}",
                                    details=f"Pending order cancelled via content-based close detection: {content[:100]}"
                                )
                                
                                closed_count += 1
                            except Exception as ord_error:
                                error_msg = str(ord_error)
                                # Check if order was already cancelled or filled
                                if 'not found' in error_msg.lower() or 'ERR_TRADE_ORDER_NOT_FOUND' in error_msg:
                                    logger.warning(f"⚠️ Order {order_id} no longer pending (already filled/cancelled)")
                                    # Check if it became a position or was cancelled
                                    if trade_status == 'EXECUTED':
                                        logger.info(f"   ℹ️ Order {order_id} was filled - now a position")
                                    else:
                                        await db_service.update_trade_field(trade_id, 'status', 'CANCELLED')
                                        await db_service.update_trade_field(trade_id, 'closedAt', datetime.now())
                                        
                                        # Update signal status
                                        if signal_id:
                                            try:
                                                await db_service.update_signal_status_from_trades(signal_id)
                                            except Exception as e:
                                                logger.debug(f"Signal status update failed ({signal_id[:8]}...): {e}")
                                        
                                        # Log the cancellation
                                        await db_service.log_trade_action(
                                            trade_id=trade_id,
                                            action_type='CANCEL',
                                            success=True,
                                            triggered_by='content_detection',
                                            trigger_source=f'message_{message_id.message_id}_already_cancelled',
                                            details='Pending order already cancelled externally - not found on broker'
                                        )
                                    already_closed_count += 1
                                else:
                                    logger.error(f"❌ Failed to cancel order {order_id}: {error_msg}")
                                    raise
                        else:
                            logger.warning(f"⚠️ Trade {trade_id} has neither position_id nor order_id — skipping")
                    except Exception as e:
                        logger.error(f"❌ Unexpected error processing trade {trade_id}: {str(e)}")
                
                # Update signal status if all trades are now closed
                if closed_count > 0 or already_closed_count > 0:
                    logger.success(f"✅ Closed {closed_count} position(s) for {signal.symbol} via content detection")
                    if already_closed_count > 0:
                        logger.info(f"   ℹ️ {already_closed_count} position(s) were already closed")
                    
                    # Find and update the signal status
                    signals_for_symbol = await db_service.db.signal.find_many(
                        where={
                            "symbol": signal.symbol,
                            "channelId": signal.channel_id,
                            "status": "EXECUTED"
                        },
                        order={"createdAt": "desc"}
                    )
                    
                    # Mark signals as CLOSED
                    for sig in signals_for_symbol:
                        # Check if all trades for this signal are closed
                        sig_trades = await db_service.db.trade.find_many(
                            where={"signalId": sig.id}
                        )
                        all_closed = all(
                            t.status in ['CLOSED', 'CANCELLED', 'FAILED']
                            for t in sig_trades
                        )
                        if all_closed:
                            await db_service.db.signal.update(
                                where={"id": sig.id},
                                data={"status": "CLOSED"}
                            )
                            logger.debug(f"   📝 Updated signal {sig.id[:8]}... status to CLOSED")
                else:
                    logger.warning(f"⚠️ No positions were successfully closed for {signal.symbol}")
                
            except Exception as e:
                logger.error(f"❌ Error executing close command: {str(e)}")
                logger.exception(e)
            
            return
        
        # For non-CLOSE actions, just log as before
        trade_record = trade_mapper.find_trade_by_message(message_id)
        
        # If not found by message ID, try to find by symbol in recent trades
        if not trade_record and signal.symbol:
            trade_record = trade_mapper.find_recent_trade_by_symbol(signal.symbol)
        
        if trade_record:
            logger.info(f"📝 Found related trade: {trade_record['symbol']}")
            # Add this message as related to the trade
            trade_mapper.add_related_message(trade_record, message_id)
            logger.info("Trade update logged (content-based detection)")
        else:
            logger.warning("⚠️ No related trade found for update message")
            logger.debug(f"   Content: {content[:100]}...")
