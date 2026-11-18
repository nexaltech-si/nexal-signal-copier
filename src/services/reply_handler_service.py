"""
Reply Handler Service
Handles Telegram message replies for order management
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

# Method groups split out of this class (see each module's docstring)
from src.services.reply_actions.detection import ReplyDetectionMixin
from src.services.reply_actions.modify_actions import ReplyModifyMixin
from src.services.reply_actions.close_actions import ReplyCloseMixin
from src.services.reply_actions.selective_close import ReplySelectiveCloseMixin

# Import AI command processor
try:
    from ai.trade_command_processor import TradeCommandProcessor, TradeCommand
    from config import settings
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False
    logger.warning("AI trade command processor not available")


# Sentinel: "use the live singleton" (None means "disabled" for the brain)
_LIVE = object()


class ReplyHandlerService(ReplyDetectionMixin, ReplyModifyMixin, ReplyCloseMixin, ReplySelectiveCloseMixin):
    """
    Service to handle Telegram message replies for order management
    Allows users to reply to signal messages to modify/close orders
    """
    
    def __init__(
        self,
        trading_provider=None,
        db=None,
        forwarder=None,
        brain=_LIVE,
        spread_adjustment=None,
        ai_processor=None,
        context_manager=None,
    ):
        """
        Initialize reply handler with AI command processor and context manager.

        Every outside dependency can be injected. Live code passes nothing and gets
        the real broker, database, Telegram forwarder and trading brain; the
        simulator passes in-memory fakes so it can run this exact code inside the
        live bot process without touching the account, the DB or Telegram.
        """
        self.trading_provider = trading_provider or create_trading_provider()
        self.db = db or db_service
        self._forwarder = forwarder
        self._brain = brain
        self.spread_adjustment = spread_adjustment or spread_adjustment_service
        self.context_manager = context_manager or trade_context_manager
        self.ai_processor = ai_processor
        if ai_processor is None and AI_AVAILABLE:
            try:
                self.ai_processor = TradeCommandProcessor(settings)
                logger.info("✅ AI command processor initialized")
            except Exception as e:
                logger.warning(f"Failed to init AI processor: {e}")
    
    @property
    def forwarder(self):
        if self._forwarder is None:
            from src.services.signal_forwarder_service import signal_forwarder_service
            return signal_forwarder_service
        return self._forwarder

    @property
    def brain(self):
        """None disables feeding replies to the trading brain."""
        if self._brain is _LIVE:
            from ai.trading_brain import trading_brain
            return trading_brain
        return self._brain

    def _filter_trades_by_timestamp(
        self, 
        positions: List[Dict], 
        orders: List[Dict], 
        command_timestamp: datetime
    ) -> tuple[List[Dict], List[Dict]]:
        """
        Filter positions and orders to only include those active when command was received
        """
        filtered_positions = []
        filtered_orders = []

        # Ensure command_timestamp is timezone-aware
        if command_timestamp.tzinfo is None:
            command_timestamp = command_timestamp.replace(tzinfo=timezone.utc)
        
        # Add generous grace period for MT5 server time mismatches (often hours)
        # If using MT5Rest, server time is unpredictable and often not UTC.
        # Since we use deterministic magic numbers, timestamp filtering is a secondary safety.
        from config import settings
        grace_seconds = 3600 * 3 if settings.trading_provider == 'mt5rest' else 5
        
        for pos in positions:
            try:
                # MT5Rest standardized openTime to datetime in recent provider update
                # Standardize pos_time
                pos_time = pos.get('openTime') or pos.get('time')
                
                if isinstance(pos_time, str):
                    try:
                        pos_time = datetime.fromisoformat(pos_time.replace('Z', '+00:00'))
                    except Exception:
                        logger.warning(f"Could not parse position time: {pos_time}")
                        continue
                elif isinstance(pos_time, (int, float)):
                    # Handle unix timestamp if passed from an older provider version
                    pos_time = datetime.fromtimestamp(pos_time, tz=timezone.utc)
                
                if not pos_time:
                    filtered_positions.append(pos)
                    continue

                if pos_time.tzinfo is None:
                    pos_time = pos_time.replace(tzinfo=timezone.utc)

                # Only include if position was opened before command (with grace period)
                if pos_time <= (command_timestamp + timedelta(seconds=grace_seconds)):
                    filtered_positions.append(pos)
                else:
                    logger.info(f"⏳ Excluding position {pos.get('id')} - opened after command ({pos_time} > {command_timestamp} + {grace_seconds}s)")
            except Exception as e:
                logger.error(f"Error filtering position {pos.get('id')} by timestamp: {e}")
                filtered_positions.append(pos) # Include on error for safety
        
        for order in orders:
            try:
                order_time = order.get('openTime') or order.get('time')
                if isinstance(order_time, str):
                    try:
                        order_time = datetime.fromisoformat(order_time.replace('Z', '+00:00'))
                    except Exception:
                        logger.warning(f"Could not parse order time: {order_time}")
                        continue
                elif isinstance(order_time, (int, float)):
                    order_time = datetime.fromtimestamp(order_time, tz=timezone.utc)

                if not order_time:
                    filtered_orders.append(order)
                    continue

                if order_time.tzinfo is None:
                    order_time = order_time.replace(tzinfo=timezone.utc)

                if order_time <= (command_timestamp + timedelta(seconds=grace_seconds)):
                    filtered_orders.append(order)
                else:
                    logger.info(f"⏳ Excluding order {order.get('id')} - created after command ({order_time} > {command_timestamp} + {grace_seconds}s)")
            except Exception as e:
                logger.error(f"Error filtering order {order.get('id')} by timestamp: {e}")
                filtered_orders.append(order)

        return filtered_positions, filtered_orders
    
    async def handle_reply(
        self,
        reply_to_message_id: int,
        chat_id: str,
        command: str,
        reply_message_id: Optional[int] = None,
        user_id: Optional[str] = None,
        username: Optional[str] = None,
        command_timestamp: Optional[datetime] = None,
        channel_name: Optional[str] = None,
        image_data: Optional[bytes] = None,
        channel_rule: Optional[Dict] = None,
        related_message_ids: Optional[List[int]] = None,
    ) -> Dict:
        """
        Handle a reply to a trading signal message

        Args:
            reply_to_message_id: The message ID being replied to
            chat_id: The chat ID
            command: The command from the reply (e.g., "close", "modify sl 1.2000")
            reply_message_id: The actual reply message ID (optional)
            user_id: Telegram user ID who sent the reply (optional)
            username: Telegram username who sent the reply (optional)
            command_timestamp: When the command message was sent (optional, defaults to now)
            channel_rule: The owner's channel rule this reply matched (optional) — given
                          to the AI as an instruction, run directly when no AI is reachable
            related_message_ids: For a command that is NOT a reply — the channel's other
                          running signals on the same instrument and side. Their open
                          entries take part in a close that picks entries ("close your
                          bad entry, hold the good one"); nothing else touches them.

        Returns:
            Dictionary with operation result
        """
        reply_record_id = None
        try:
            logger.info(f"📩 Handling reply to message {reply_to_message_id}: {command}")
            
            # Use provided timestamp or current time
            if not command_timestamp:
                command_timestamp = datetime.now(timezone.utc)
                logger.debug(f"⏱️ No command timestamp provided, using current time: {command_timestamp}")
            else:
                logger.debug(f"⏱️ Command timestamp: {command_timestamp}")
            
            # Generate magic number directly from message ID (it's deterministic!)
            magic_number = magic_number_service.generate_magic_number(reply_to_message_id)
            logger.info(f"🔢 Generated magic number from message ID: {magic_number}")
            
            # Find signal by message ID — a follow-up / repost message is linked to the
            # original setup (CONTINUATION), whose orders carry the original's magic
            signal_id = None
            symbol = None
            try:
                from src.services.signal_continuity import signal_continuity
                signal_record, group_magic = await signal_continuity.resolve_group(chat_id, reply_to_message_id)
                if group_magic and group_magic != magic_number:
                    logger.info(f"🔗 Reply target is linked to an earlier signal — using its magic {group_magic}")
                    magic_number = group_magic
                if signal_record:
                    signal_id = signal_record.id
                    symbol = signal_record.symbol
                    if not channel_name and getattr(signal_record, 'channelName', None):
                        channel_name = signal_record.channelName
            except Exception as e:
                logger.debug(f"Could not find signal for message {reply_to_message_id}: {e}")
            
            # Create signal reply record
            if reply_message_id:
                reply_record_id = await self.db.create_signal_reply(
                    chat_id=chat_id,
                    reply_message_id=reply_message_id,
                    reply_to_message_id=reply_to_message_id,
                    reply_text=command,
                    user_id=user_id,
                    username=username,
                    signal_id=signal_id,
                    magic_number=magic_number,
                    symbol=symbol,
                    command_timestamp=command_timestamp
                )
                logger.debug(f"💬 Created reply record {reply_record_id[:8] if reply_record_id else 'failed'}... at {command_timestamp.isoformat()}")
            
            # Query trading provider FIRST (fastest path - gets live broker data)
            logger.info(f"🔍 Querying {settings.provider_label} for positions/orders with magic {magic_number}...")
            metaapi_data = await self.trading_provider.get_all_trades_by_magic(magic_number)
            
            all_positions = list(metaapi_data.get('positions', []))
            all_orders = list(metaapi_data.get('orders', []))

            # A reply to a post that became SEVERAL trades (multi-signal post) manages all of them
            all_positions, all_orders = await self._merge_split_siblings(
                chat_id, reply_to_message_id, magic_number, all_positions, all_orders
            )
            
            logger.info(f"📊 Found {len(all_positions)} position(s) and {len(all_orders)} order(s) in {settings.provider_label}")
            
            # CRITICAL: Filter trades to only include those that were active when command was sent
            # This ensures we only manage trades from "message received" to "trade executed" timeframe
            positions, orders = self._filter_trades_by_timestamp(all_positions, all_orders, command_timestamp)
            
            # Track filtering statistics for database
            filtering_stats = {
                "command_timestamp": command_timestamp.isoformat(),
                "total_positions_found": len(all_positions),
                "total_orders_found": len(all_orders),
                "positions_after_filter": len(positions),
                "orders_after_filter": len(orders),
                "positions_filtered_out": len(all_positions) - len(positions),
                "orders_filtered_out": len(all_orders) - len(orders)
            }
            
            logger.info(f"✅ After timestamp filtering: {len(positions)} position(s) and {len(orders)} order(s)")

            # A command that is not a reply names no signal. One that picks entries
            # ("close your bad entry, hold the good one") means every open entry of the
            # channel on that instrument — with two SELL signals running, judging only the
            # latest one closed its single, good entry and left the bad one of the older
            # signal open (live channel, 2026-11-16).
            scope_positions, scope_magics = await self._related_open_positions(
                chat_id, related_message_ids, magic_number, positions, command_timestamp
            )
            
            db_trades_cache = None  # Cache for database trades if needed
            
            # If MetaAPI has nothing, use database as fallback
            if not positions and not orders:
                logger.info(f"💾 No positions/orders in {settings.provider_label}, checking database as fallback...")
                db_trades_cache = await self.db.get_trades_by_magic_number(magic_number)
                
                # Filter for non-closed trades
                active_db_trades = [
                    t for t in db_trades_cache 
                    if t.get('status') not in ['CLOSED', 'FAILED', 'CANCELLED']
                ] if db_trades_cache else []
                
                if active_db_trades:
                    pending_count = sum(1 for t in active_db_trades if t.get('status') == 'PENDING')
                    executed_count = sum(1 for t in active_db_trades if t.get('status') == 'EXECUTED')
                    logger.info(f"📋 Found {len(active_db_trades)} active trade(s) in database: {pending_count} PENDING, {executed_count} EXECUTED")
                
            # Prepare db_trades for operations (use cache if available)
            db_trades = db_trades_cache if db_trades_cache else []
            
            # 2.2 SYMBOL RESOLUTION & SIGNAL RECOVERY (if no trades found in broker)
            if not positions and not orders and not db_trades:
                logger.debug(f"🔍 No active trades, checking if signal {signal_id} can be managed...")
                # If we have a signal record, we can still process 'close' or 'cancel' to move it to a terminal state
                # even if it has no trades (e.g., if it was rejected or is still pending execution)
                if not signal_id:
                     # Nothing in MetaAPI and nothing active in database
                    logger.warning("⚠️ No active trades or signal found anywhere")
                    result = {
                        "success": False,
                        "error": f"No active positions or pending orders found for message {reply_to_message_id}",
                        "suggestion": "The trade may have already been closed, cancelled, or never executed. Check the signal's history.",
                        "timestamp_filtering": filtering_stats,
                        "channel_name": channel_name,
                        "symbol": symbol,
                    }
                    if reply_record_id:
                        await self._update_reply_record(reply_record_id, result, ai_parsed=False)
                    return result
            
            # AI-only processing - let AI decide if it's a command or status message
            # This ensures we never miss actual commands due to pattern matching errors
            if not self.ai_processor:
                error_msg = "AI command processor not available. Cannot process reply commands."
                logger.error(f"❌ {error_msg}")
                return {
                    "success": False,
                    "error": error_msg,
                    "suggestion": "Ensure AI API keys are configured in settings (OPENAI_API_KEY or DEEPSEEK_API_KEY)"
                }
            
            # Feed reply into the brain conversation so it maintains session context
            try:
                trading_brain = self.brain
                if trading_brain is not None and trading_brain.enabled:
                    context = f"Position context: {len(positions)} open, {len(orders)} pending orders"
                    await trading_brain.handle_reply(command, context=context, image_data=image_data)
            except Exception as _brain_err:
                logger.debug(f"Brain reply context update skipped: {_brain_err}")

            logger.info("🤖 Using AI to parse command")
            try:
                # Use context manager to resolve symbol from conversation context
                # First try to extract from message
                symbol_from_message = self.context_manager._extract_symbol_from_message(command)
                
                # If not found, get from positions
                symbol_context = symbol_from_message or (positions[0].get('symbol') if positions else None)
                
                # If still no symbol, try context manager for channel-based resolution
                if not symbol_context and signal_id:
                    symbol_context = await self.context_manager.resolve_symbol_for_command(
                        command_text=command,
                        action=None,  # Action is determined by AI processor
                        channel_id=chat_id
                    )
                
                # Update conversation history for future context resolution
                self.context_manager.add_to_conversation_history(
                    channel_id=chat_id,
                    message=command,
                    signal_info={"symbol": symbol_context} if symbol_context else None
                )

                # Build per-signal thread context so AI understands what already happened
                # on this specific signal before interpreting the current message.
                thread_context = await self._get_thread_context(
                    reply_to_message_id=reply_to_message_id,
                    chat_id=chat_id,
                    current_reply_message_id=reply_message_id
                )

                state_context = self._build_state_context(positions, orders)
                scope_context = self._build_scope_context(scope_positions)
                rule_context = channel_behavior_service.rule_guidance(channel_rule) if channel_rule else None
                full_context = "\n\n".join(c for c in (rule_context, state_context, scope_context, thread_context) if c)

                rule_kwargs = channel_behavior_service.rule_command_kwargs(channel_rule) if channel_rule else None
                if rule_kwargs and not self.ai_processor.ai_available():
                    logger.warning(f"⚠️ No AI provider reachable — running channel rule '{channel_rule['ruleName']}' directly: {rule_kwargs}")
                    ai_command = TradeCommand(**rule_kwargs)
                else:
                    ai_command = await self.ai_processor.process_command(command, symbol_context, full_context or None)

                rule_info = None
                if channel_rule:
                    expected = channel_behavior_service.expected_actions(channel_rule)
                    rule_info = {
                        "id": channel_rule['id'],
                        "name": channel_rule['ruleName'],
                        "actionType": channel_rule['actionType'],
                        "aiAction": ai_command.action if ai_command else None,
                        "followed": bool(ai_command) and (not expected or ai_command.action in expected),
                    }
                    if not rule_info["followed"]:
                        logger.warning(
                            f"⚠️ Channel rule '{channel_rule['ruleName']}' wanted {channel_rule['actionType']} "
                            f"but AI chose {rule_info['aiAction'] or 'no action'} (live state: "
                            f"{len(positions)} open, {len(orders)} pending)"
                        )

                if ai_command and scope_positions and ai_command.action in self._ENTRY_SELECTIVE_ACTIONS:
                    logger.info(
                        f"🎯 '{ai_command.action}' in a message that is not a reply — choosing among "
                        f"{len(positions) + len(scope_positions)} open entries of this channel "
                        f"({len(scope_positions)} from its other running signal(s))"
                    )
                    positions = positions + scope_positions
                    db_trades = list(db_trades or await self.db.get_trades_by_magic_number(magic_number) or [])
                    for other_magic in scope_magics:
                        db_trades += await self.db.get_trades_by_magic_number(other_magic) or []

                # Nothing is filled yet: profit-taking / BE / partial actions have no
                # position to act on and would leave stale pending orders behind.
                if ai_command and not positions and orders and ai_command.action in self._POSITION_ONLY_ACTIONS:
                    logger.info(
                        f"🔁 '{ai_command.action}' with 0 open positions and {len(orders)} pending order(s) "
                        f"— entry was missed, cancelling pending orders instead"
                    )
                    ai_command.action = 'cancel_orders'

                if not ai_command:
                    # AI determined this is not a command (likely a status message or commentary)
                    logger.info(f"💬 AI determined message is not a command: {command[:100]}")
                    
                    # CRITICAL: Check if this is a TP/profit status message with pending orders
                    # If signal provider reports profit/TP hit but user's orders are still PENDING,
                    # auto-cancel them because the setup already played out for the provider
                    # IMPORTANT: Only cancel orders for THIS SPECIFIC SIGNAL to avoid aggressive cancellation
                    if signal_id and orders and len(orders) > 0:
                        # Use AI to make the decision (more intelligent than pattern matching)
                        should_cancel = await self._ai_should_cancel_for_tp_hit(command, signal_id)
                        
                        if should_cancel:
                            # Filter orders to only those belonging to this signal
                            signal_orders = []
                            if not db_trades:
                                db_trades = await self.db.get_trades_by_magic_number(magic_number)
                            
                            # Get order IDs that belong to this signal
                            signal_order_ids = set()
                            for trade in db_trades:
                                if trade.get('signalId') == signal_id and trade.get('orderId'):
                                    signal_order_ids.add(trade.get('orderId'))
                            
                            # Filter orders to only those for this signal
                            signal_orders = [order for order in orders if order.get('id') in signal_order_ids]
                            
                            if signal_orders and len(signal_orders) > 0:
                                logger.info(f"📊 Status message mentions profit/TP hit and signal {signal_id[:8]}... has {len(signal_orders)} PENDING order(s)")
                                logger.info("🎯 Signal provider's trade already ran - auto-cancelling signal-specific pending orders")
                                
                                cancel_result = await self._cancel_pending_orders(
                                    signal_orders, 
                                    magic_number, 
                                    "Auto-cancel: Signal provider reported profit/TP (user orders never triggered)"
                                )
                                
                                if cancel_result.get('success'):
                                    result = {
                                        "success": True,
                                        "message": f"🎯 Signal provider's trade already in profit. {cancel_result.get('message')}",
                                        "auto_cancelled": True,
                                        "reason": "provider_profit_pending_orders",
                                        "cancelled_count": cancel_result.get('cancelled_count', 0)
                                    }
                                    
                                    # Update reply record
                                    if reply_record_id:
                                        await self.db.update_signal_reply_action(
                                            reply_id=reply_record_id,
                                            action_taken=True,
                                            action_type="AUTO_CANCEL_PENDING",
                                            action_success=True,
                                            action_result=result['message'],
                                            action_details={"channel_rule": rule_info} if rule_info else None,
                                            processed=True
                                        )
                                    
                                    return result
                            else:
                                logger.debug(f"📊 Profit mentioned but no pending orders found for signal {signal_id[:8]}... (other signals may have pending orders)")
                    
                    # Update reply record as ignored
                    if reply_record_id:
                        await self.db.update_signal_reply_action(
                            reply_id=reply_record_id,
                            action_taken=False,
                            action_type="STATUS_MESSAGE",
                            action_success=True,
                            action_result="AI determined: Not a command (status message or commentary)",
                            action_details={"channel_rule": rule_info} if rule_info else None,
                            processed=True
                        )
                    
                    return {
                        "success": True,
                        "message": "Message ignored (not a command)",
                        "ignored": True,
                        "reason": "ai_determined_status_message"
                    }
                
                logger.info(f"🤖 AI parsed action: {ai_command.action}")
                if ai_command.target:
                    logger.info(f"   Target: {ai_command.target}")
                if ai_command.value:
                    logger.info(f"   Value: {ai_command.value}")
                if ai_command.percentage:
                    logger.info(f"   Percentage: {ai_command.percentage}%")
                if ai_command.parameters:
                    logger.info(f"   Parameters: {ai_command.parameters}")
                
                # SMART AUTO-CANCEL: If TP has been hit and there are pending orders, auto-cancel them
                # This only triggers for REAL commands (not status messages), preventing false cancellations
                # IMPORTANT: Only cancel orders for THIS SPECIFIC SIGNAL to avoid aggressive cancellation
                if signal_id and orders and len(orders) > 0:
                    # Check if any TP has been hit for this signal's trades
                    tp_hit_in_db = await self._check_tp_hits(signal_id)
                    
                    if tp_hit_in_db:
                        # Filter orders to only those belonging to this signal
                        if not db_trades:
                            db_trades = await self.db.get_trades_by_magic_number(magic_number)
                        
                        # Get order IDs that belong to this signal
                        signal_order_ids = set()
                        for trade in db_trades:
                            if trade.get('signalId') == signal_id and trade.get('orderId'):
                                signal_order_ids.add(trade.get('orderId'))
                        
                        # Filter orders to only those for this signal
                        signal_orders = [order for order in orders if order.get('id') in signal_order_ids]
                        
                        if signal_orders and len(signal_orders) > 0:
                            logger.info(f"🎯 TP hit detected for signal {signal_id[:8]}... - auto-cancelling {len(signal_orders)} signal-specific pending order(s) before executing command")
                            cancel_result = await self._cancel_pending_orders(signal_orders, magic_number, f"Auto-cancel (TP hit detected, user command: {command[:30]})")
                            
                            if cancel_result.get('success'):
                                # Pending orders cancelled - now execute the original command on remaining positions
                                logger.info(f"✅ Auto-cancelled signal-specific pending orders, now executing original command: {ai_command.action}")
                                # Update orders list to remove cancelled ones
                                orders = [order for order in orders if order.get('id') not in signal_order_ids]
                        else:
                            logger.debug(f"🎯 TP hit detected but no pending orders found for signal {signal_id[:8]}... (other signals may have pending orders)")
                
                result = await self._execute_ai_command(ai_command, positions, orders, magic_number, command, db_trades)

                # Add timestamp filtering stats to result for database storage
                result['timestamp_filtering'] = filtering_stats
                result['symbol_context'] = symbol_context
                result['channel_name'] = channel_name
                result['symbol'] = result.get('symbol') or symbol
                
                # COMPOUND COMMAND HANDLING: Check if message contains BOTH partial close AND break even
                if ai_command.action == 'partial_close':
                    cmd_lower = command.lower()
                    from ai.message_guards import has_breakeven_wording
                    has_breakeven = has_breakeven_wording(command)
                    
                    if has_breakeven and result.get('success'):
                        logger.info("🔗 Compound command detected: partial close + break even. Executing break even now...")
                        
                        # Re-fetch positions after partial close (remaining positions)
                        remaining_positions = await self.trading_provider.get_all_trades_by_magic(magic_number)
                        remaining_pos = remaining_positions.get('positions', [])
                        
                        if remaining_pos:
                            be_result = await self._move_to_breakeven(remaining_pos, magic_number, None, orders)
                            
                            # Combine results
                            if be_result.get('success'):
                                result['message'] += f" + {be_result.get('message', 'Moved to breakeven')}"
                                result['compound_action'] = True
                                result['breakeven_executed'] = True
                                logger.success("✅ Compound command completed: partial close + break even")
                            else:
                                result['breakeven_warning'] = be_result.get('error', 'Failed to set break even')
                                logger.warning(f"⚠️ Partial close succeeded but break even failed: {be_result.get('error')}")
                        else:
                            result['breakeven_warning'] = "No remaining positions to set break even"
                            logger.warning("⚠️ No remaining positions after partial close to set break even")
                
                if rule_info:
                    result['channel_rule'] = rule_info
                    if rule_info['followed'] and result.get('success'):
                        await channel_behavior_service.record_success(rule_info['id'])

                # Update reply record with AI parsing
                if reply_record_id:
                    await self._update_reply_record(reply_record_id, result, ai_parsed=True)
                
                return result
                
            except Exception as e:
                logger.error(f"❌ AI processing failed: {e}")
                return {
                    "success": False,
                    "error": f"Failed to process command: {str(e)}",
                    "suggestion": "Check logs for details"
                }
            
        except Exception as e:
            logger.error(f"❌ Error handling reply: {str(e)}")
            
            # Update reply record with error
            if reply_record_id:
                try:
                    await self.db.update_signal_reply_action(
                        reply_id=reply_record_id,
                        action_taken=False,
                        processed=True,
                        processing_error=str(e)
                    )
                except Exception as update_error:
                    logger.debug(f"Could not update reply record: {update_error}")
            
            return {"success": False, "error": str(e)}
    
    _LOW_WORDS = {'bottom', 'lower', 'lowest', 'low', 'below', 'down'}
    _HIGH_WORDS = {'top', 'upper', 'higher', 'highest', 'high', 'above', 'up'}
    _ORDINALS = {'first': 0, '1st': 0, 'one': 0, 'second': 1, '2nd': 1, 'two': 1,
                 'third': 2, '3rd': 2, 'three': 2, 'last': -1, 'final': -1}

    @classmethod
    def _entry_for_ordinal(cls, positions: List[Dict], target: str,
                           other_levels: Optional[List[float]] = None) -> Optional[float]:
        """
        Resolve "first/second/last entry" to a fill price. Scale-in legs are laid
        against the trade direction (SELL @4120 then MORE @4130; BUY @4167 then
        MORE @4160), so the first entry is the lowest SELL / highest BUY price.

        other_levels: the setup's entries that are not open — legs already closed and
        legs still pending. They count when ranking: once the lower entry is closed,
        "close the lower entry, hold the upper" must not turn on the upper one, which
        is then the lowest that is left. The level returned may therefore be one with
        no open position.
        """
        word = str(target).strip().lower()
        fills = [p for p in positions if p.get('openPrice') is not None]
        if not fills:
            return None
        prices = [float(p['openPrice']) for p in fills]
        tolerance = cls._entry_match_tolerance(fills[0].get('symbol', ''), prices[0])
        for level in other_levels or []:
            if all(abs(float(level) - known) > tolerance for known in prices):
                prices.append(float(level))
        # Price-position words: "close bottom, hold upper" / "close the lower entry"
        if word in cls._LOW_WORDS:
            return min(prices)
        if word in cls._HIGH_WORDS:
            return max(prices)
        idx = cls._ORDINALS.get(word)
        if idx is None:
            return None
        is_sell = 'SELL' in str(fills[0].get('type', '')).upper()
        ordered = sorted(prices, reverse=not is_sell)
        if idx >= len(ordered) or idx < -len(ordered):
            return None
        return ordered[idx]

    @staticmethod
    def _levels_not_open(orders: List[Dict], db_trades: List[Dict]) -> List[float]:
        """Entry levels of the setup with no open position: pending orders and closed legs."""
        levels = [float(o['openPrice']) for o in orders or [] if o.get('openPrice') is not None]
        levels += [float(t['entryPrice']) for t in db_trades or []
                   if t.get('status') == 'CLOSED' and t.get('entryPrice') is not None]
        return levels

    # Closes that pick some entries and leave the rest: for a message that is not a
    # reply they choose among the channel's open entries on that instrument and side.
    _ENTRY_SELECTIVE_ACTIONS = {'close_worst', 'close_best', 'close_by_entry'}
    _HOLD_WORDS = re.compile(r'\b(?:hold|holding|keep|keeping)\b', re.IGNORECASE)
    _HOLD_VERBS = {'hold', 'holding', 'keep', 'keeping'}
    _CLOSE_VERBS = {'close', 'closing', 'closed', 'secure', 'exit', 'cut', 'book'}

    @classmethod
    def _side_to_close(cls, command: str) -> Optional[str]:
        """
        'lower' / 'upper' when the text closes one side by position and holds the
        other ("Down entry close upper entry hold", "Secure down entries hold upper"),
        None when it names a price or is not that clear. Each position word belongs
        to the verb it stands nearest to.
        """
        if not command or re.search(r'\d', command):
            return None
        words = re.findall(r'[a-z]+', command.lower())
        closes = [i for i, w in enumerate(words) if w in cls._CLOSE_VERBS]
        holds = [i for i, w in enumerate(words) if w in cls._HOLD_VERBS]
        if not closes or not holds:
            return None
        to_close, to_hold = set(), set()
        for i, w in enumerate(words):
            side = 'lower' if w in cls._LOW_WORDS else 'upper' if w in cls._HIGH_WORDS else None
            if not side:
                continue
            near_close, near_hold = min(abs(i - c) for c in closes), min(abs(i - h) for h in holds)
            if near_close < near_hold:
                to_close.add(side)
            elif near_hold < near_close:
                to_hold.add(side)
        if len(to_close) == 1 and not to_close & to_hold:
            return next(iter(to_close))
        if not to_close and len(to_hold) == 1:
            return 'lower' if to_hold == {'upper'} else 'upper'
        return None

    async def _related_open_positions(self, chat_id, related_message_ids, magic_number,
                                      positions, command_timestamp):
        """Open positions (and their magic numbers) of the channel's other running signals."""
        found, magics = [], []
        seen = {p.get('id') for p in positions}
        for other_id in related_message_ids or []:
            try:
                other_magic = magic_number_service.generate_magic_number(other_id)
                try:
                    from src.services.signal_continuity import signal_continuity
                    _, group_magic = await signal_continuity.resolve_group(chat_id, other_id)
                    other_magic = group_magic or other_magic
                except Exception as e:
                    logger.debug(f"Could not resolve the signal group of message {other_id}: {e}")
                if other_magic == magic_number or other_magic in magics:
                    continue
                trades = await self.trading_provider.get_all_trades_by_magic(other_magic)
                open_then, _ = self._filter_trades_by_timestamp(
                    list(trades.get('positions', [])), [], command_timestamp)
                fresh = [p for p in open_then if p.get('id') not in seen]
                if fresh:
                    found += fresh
                    magics.append(other_magic)
                    seen.update(p.get('id') for p in fresh)
            except Exception as e:
                logger.warning(f"⚠️ Could not read the positions of signal #{other_id} (continuing without them): {e}")
        return found, magics

    @staticmethod
    def _build_scope_context(scope_positions: List[Dict]) -> Optional[str]:
        """Tell the AI which other entries of this channel a non-reply message can mean."""
        if not scope_positions:
            return None
        lines = ["This message is not a reply to a signal. The channel has other running setups on the same "
                 "instrument and side:"]
        for p in scope_positions[:10]:
            lines.append(
                f"- OPEN {p.get('type', '')} {p.get('symbol', '')} entry {p.get('openPrice')} "
                f"now {p.get('currentPrice')} P/L {p.get('profit')}"
            )
        lines.append(
            "A close that picks entries (bad/good, worst/best, lower/upper, first/second, or a stated entry "
            "level) chooses among ALL open entries — those above and these. Every other action applies to "
            "the signal above only."
        )
        return "\n".join(lines)

    # Actions that need a FILLED position; with only pending orders they are a no-op.
    _POSITION_ONLY_ACTIONS = {'partial_close', 'close_best', 'close_worst', 'breakeven', 'lock_profit'}

    @staticmethod
    def _build_state_context(positions: List[Dict], orders: List[Dict]) -> str:
        """Describe the follower's live positions/orders for this signal so the AI decides on real state."""
        lines = [f"Live account state for this signal: {len(positions)} OPEN position(s), {len(orders)} PENDING order(s)."]
        for p in positions[:10]:
            lines.append(
                f"- OPEN {p.get('type', '')} {p.get('symbol', '')} entry {p.get('openPrice')} "
                f"now {p.get('currentPrice')} SL {p.get('stopLoss')} TP {p.get('takeProfit')} P/L {p.get('profit')}"
            )
        for o in orders[:10]:
            lines.append(
                f"- PENDING {o.get('type', '')} {o.get('symbol', '')} at {o.get('openPrice')} "
                f"(market now {o.get('currentPrice')})"
            )
        if not positions and orders:
            lines.append("Nothing is filled yet — the follower has NO open position on this signal.")
        return "\n".join(lines)

    async def _get_thread_context(
        self,
        reply_to_message_id: int,
        chat_id: str,
        current_reply_message_id: Optional[int],
    ) -> Optional[str]:
        """
        Return a brief chronological summary of previous replies on this signal thread.
        Passed to the AI so it can interpret ambiguous words like "done" in context.
        """
        try:
            where: Dict = {
                "replyToMessageId": reply_to_message_id,
                "chatId": chat_id,
                "processed": True,
            }
            if current_reply_message_id:
                where["NOT"] = {"replyMessageId": current_reply_message_id}

            previous = await self.db.db.signalreply.find_many(
                where=where,
                order={"createdAt": "asc"},
                take=6,
            )

            if not previous:
                return None

            lines = []
            for r in previous:
                text = (r.replyText or "")[:80].strip()
                if not text:
                    continue
                if r.actionTaken and r.actionType:
                    suffix = f" → executed: {r.actionType}"
                else:
                    suffix = " → no action (status)"
                lines.append(f'- "{text}"{suffix}')

            if not lines:
                return None

            return "Previous messages in this signal thread (oldest first):\n" + "\n".join(lines)

        except Exception as e:
            logger.debug(f"Could not load thread context: {e}")
            return None

    async def _update_reply_record(self, reply_id: str, result: Dict, ai_parsed: bool = False):
        """Update reply record with action results"""
        if not reply_id or not result:
            return
        
        try:
            # Determine action type from result
            action_type = None
            if 'action_type' in result:
                action_type = result['action_type']
            elif result.get('closed_count', 0) > 0 or result.get('cancelled_count', 0) > 0:
                action_type = "CLOSE"
            elif 'stop_loss' in result.get('message', '').lower():
                action_type = "MODIFY_SL"
            elif 'take profit' in result.get('message', '').lower():
                action_type = "MODIFY_TP"
            elif 'breakeven' in result.get('message', '').lower():
                action_type = "BREAKEVEN"
            elif 'partial' in result.get('message', '').lower():
                action_type = "PARTIAL_CLOSE"
            elif 'cancel' in result.get('message', '').lower():
                action_type = "CANCEL"
            
            # Extract affected trade IDs if available
            affected_trade_ids = None
            if 'affected_trade_ids' in result:
                affected_trade_ids = result['affected_trade_ids']
            
            await self.db.update_signal_reply_action(
                reply_id=reply_id,
                action_taken=result.get('success', False),
                action_type=action_type,
                action_success=result.get('success', False),
                action_result=result.get('message') or result.get('error'),
                action_details=result,
                affected_trade_ids=affected_trade_ids,
                positions_closed=result.get('closed_count', 0),
                orders_cancelled=result.get('cancelled_count', 0),
                processed=True,
                ai_parsed=ai_parsed
            )
        except Exception as e:
            logger.debug(f"Could not update reply record: {e}")
    
    async def _merge_split_siblings(self, chat_id, reply_to_message_id, magic_number, positions, orders):
        """Add the positions/orders of the other trades that came from the same multi-signal post."""
        try:
            for sibling in await self.db.get_split_siblings(chat_id, reply_to_message_id):
                sib_magic = magic_number_service.generate_magic_number(sibling.messageId)
                if sib_magic == magic_number:
                    continue
                extra = await self.trading_provider.get_all_trades_by_magic(sib_magic)
                seen_p = {p.get('id') for p in positions}
                seen_o = {o.get('id') for o in orders}
                positions = positions + [p for p in extra.get('positions', []) if p.get('id') not in seen_p]
                orders = orders + [o for o in extra.get('orders', []) if o.get('id') not in seen_o]
                logger.info(f"🧩 Reply also covers the sibling trade {sibling.symbol} of the same post")
        except Exception as e:
            logger.debug(f"Sibling lookup failed (continuing with the main trade only): {e}")
        return positions, orders

    async def _execute_ai_command(self, ai_command, positions: List[Dict], orders: List[Dict], magic_number: int, command: str, db_trades: List[Dict] = None) -> Dict:
        """Execute AI-parsed command"""
        action = ai_command.action
        
        if action == 'close_all':
            return await self._close_all_orders(positions, orders, magic_number, command, db_trades)
        elif action == 'close':
            return await self._close_all_orders(positions, orders, magic_number, command, db_trades)
        elif action == 'close_worst':
            count = ai_command.value
            command_for_log = f"close worst {count} entries" if count else "close worst entries"
            keep_one = bool(self._HOLD_WORDS.search(command or ''))
            if keep_one and len(positions) == 1:
                # "Close your bad entry, hold the good one" with one entry left: when the
                # others were closed at worse levels, this is the good one.
                if not db_trades:
                    db_trades = await self.db.get_trades_by_magic_number(magic_number) or []
                held = self._good_entry_left(positions[0], db_trades)
                if held:
                    return held
                if not orders and not self._levels_not_open([], db_trades):
                    # no second entry anywhere — closing this one would leave nothing to hold
                    fill = positions[0].get('openPrice')
                    logger.info(f"🤚 One entry open ({fill}) and no other level known — holding it")
                    return {"success": True, "ignored": True, "closed_count": 0, "reason": "single_entry_held",
                            "message": f"Only one entry is open (@ {fill}) — holding it"}
            return await self._close_worst_positions(positions, magic_number, command_for_log, count, db_trades,
                                                     keep_one=keep_one)
        elif action == 'close_best':
            count = ai_command.value
            command_for_log = f"close best {count} entries" if count else "close best entries"
            return await self._close_best_positions(positions, magic_number, command_for_log, count, db_trades)
        elif action == 'close_by_loss_threshold':
            threshold = ai_command.value
            command_for_log = f"close positions losing more than {threshold}%"
            return await self._close_positions_by_loss_threshold(positions, magic_number, command_for_log, threshold, db_trades)
        elif action == 'close_by_entry':
            entry, target = ai_command.value, ai_command.target
            # "Close the lower entry, hold the upper": the side is in the text. A price or
            # "first" the AI derived for it comes from the entries open NOW — once the
            # lower one is closed, that is the upper one.
            side = self._side_to_close(command)
            named_by_ai = entry if side else None
            if side:
                entry, target = None, side
            if entry is None and target:
                if not db_trades:
                    db_trades = await self.db.get_trades_by_magic_number(magic_number) or []
                others = self._levels_not_open(orders, db_trades)
                if named_by_ai:
                    # the level the AI took the side to mean — often the channel's own
                    # entry ("3864") that has no position any more
                    others.append(float(named_by_ai))
                entry = self._entry_for_ordinal(positions, target, others)
                fills = [float(p['openPrice']) for p in positions if p.get('openPrice') is not None]
                tolerance = self._entry_match_tolerance(positions[0].get('symbol', ''), fills[0]) if fills else 0.0
                others = [lv for lv in others if all(abs(lv - f) > tolerance for f in fills)]
                if side and len(fills) == 1 and not others:
                    # "Close the lower, hold the upper" with one entry open and no other
                    # level known: nothing tells which of the two it is, and closing it
                    # would leave nothing to hold (live channel, 2026-11-16 15:20).
                    logger.info(f"🤚 One entry open ({fills[0]}) and no other level known — holding it")
                    return {"success": True, "ignored": True, "closed_count": 0, "reason": "single_entry_held",
                            "message": f"Only one entry is open (@ {fills[0]:.6g}) — holding it"}
                if entry is not None and fills and all(
                        abs(f - entry) > self._entry_match_tolerance(positions[0].get('symbol', ''), entry)
                        for f in fills):
                    kept = ', '.join(f"{f:.6g}" for f in fills)
                    logger.info(f"🤚 The {target} entry ({entry}) has no open position — holding {kept}")
                    return {"success": True, "ignored": True, "closed_count": 0,
                            "reason": "entry_not_open",
                            "message": f"The {target} entry ({entry:.6g}) has no open position — "
                                       f"holding {len(fills)} leg(s) @ {kept}"}
            command_for_log = f"close position at entry {entry}"
            return await self._close_positions_by_entry(positions, magic_number, command_for_log, entry, db_trades)
        elif action == 'close_by_symbol':
            symbol = ai_command.target or (positions[0].get('symbol') if positions else None)
            command_for_log = f"close all {symbol} positions"
            result = await self._close_positions_by_symbol(positions, magic_number, command_for_log, symbol, db_trades)
            # Exiting the trade also drops this signal's unfilled legs on that symbol
            leftover = [o for o in (orders or []) if not symbol or str(o.get('symbol', '')).upper().startswith(str(symbol).upper()[:6])]
            if leftover:
                cancel = await self._cancel_pending_orders(leftover, magic_number, f"cancel pending {symbol} orders with close")
                result['message'] = f"{result.get('message') or result.get('error')} + cancelled {cancel.get('cancelled_count', 0)} pending order(s)"
                result['success'] = result.get('success') or cancel.get('success')
            return result
        elif action == 'close_by_time':
            minutes = ai_command.value
            command_for_log = f"close positions older than {minutes} minutes"
            return await self._close_positions_by_time(positions, magic_number, command_for_log, minutes, db_trades)
        elif action == 'partial_close':
            percentage = ai_command.percentage or 50.0
            # Reconstruct a command string for logging
            command_for_log = f"partial close {percentage}%"
            leave_min_lot = isinstance(ai_command.parameters, dict) and ai_command.parameters.get('min_lot') == 'leave'
            return await self._partial_close_by_percentage(positions, percentage, magic_number, command_for_log,
                                                           protect_kept=not leave_min_lot)
        elif action == 'modify_sl':
            return await self._modify_sl_to_price(positions, ai_command.value, magic_number, orders)
        elif action == 'modify_tp':
            tp_index = (ai_command.parameters or {}).get('tp_index') if isinstance(ai_command.parameters, dict) else None
            try:
                tp_index = int(tp_index) if tp_index else None
            except (TypeError, ValueError):
                tp_index = None
            return await self._modify_tp_to_price(positions, ai_command.value, magic_number, orders, tp_index)
        elif action == 'breakeven':
            return await self._move_to_breakeven(positions, magic_number, None, orders)
        elif action == 'lock_profit':
            pips = ai_command.value or 20
            command_for_log = f"lock profit +{pips} pips"
            return await self._lock_profit_by_pips(positions, pips, magic_number, command_for_log)
        elif action == 'cancel_orders':
            command_for_log = "cancel pending orders"
            if ai_command.value and orders:
                # "Cancel the 4130 order, keep the rest" — only the order at that level
                tol = self._entry_match_tolerance(orders[0].get('symbol', ''), ai_command.value)
                matched = [o for o in orders if o.get('openPrice') is not None
                           and abs(float(o['openPrice']) - float(ai_command.value)) <= tol]
                if not matched:
                    return {"success": False, "error": f"No pending order at {ai_command.value}"}
                return await self._cancel_pending_orders(matched, magic_number, f"cancel pending order at {ai_command.value}")
            return await self._cancel_pending_orders(orders, magic_number, command_for_log)
        elif action == 'add_position':
            lots = ai_command.value or 0.01
            return await self._add_to_position_lots(positions, lots, magic_number)
        else:
            return {"success": False, "error": f"Unknown AI action: {action}"}
    
    def _good_entry_left(self, position: Dict, db_trades: List[Dict]) -> Optional[Dict]:
        """
        The one open position is the best entry of its setup when every leg already
        closed was entered at a worse level (lower for a SELL, higher for a BUY).
        Returns the "nothing to do" result then, None otherwise.
        """
        fill = position.get('openPrice')
        closed = self._levels_not_open([], db_trades)
        if fill is None or not closed:
            return None
        fill = float(fill)
        tolerance = self._entry_match_tolerance(position.get('symbol', ''), fill)
        is_sell = 'SELL' in str(position.get('type', '')).upper()
        if not all((level < fill - tolerance) if is_sell else (level > fill + tolerance) for level in closed):
            return None
        logger.info(f"🤚 Only the best entry ({fill}) is still open — the worse one(s) are closed already")
        return {"success": True, "ignored": True, "closed_count": 0, "reason": "only_good_entry_left",
                "message": f"The worse entry is closed already — holding the entry @ {fill:.6g}"}

    @staticmethod
    def _entry_match_tolerance(symbol: str, price: float) -> float:
        """
        Price tolerance for matching a stated entry level to an actual fill.

        A quoted level like "4020" is the level the trader named, not the exact
        fill — slippage, spread and per-leg averaging move the real openPrice.
        Tolerance is scaled off the price magnitude so it works for gold (~4020),
        indices (~18000) and FX (~1.0850) without per-symbol tables.
        """
        if not price or price <= 0:
            return 0.0
        # 0.05% of price, i.e. ~2.0 on gold at 4020, ~0.0005 on EURUSD.
        return abs(price) * 0.0005

    async def _get_pip_value(self, symbol: str) -> float:
        """
        Get pip value for a symbol
        
        IMPORTANT: Pips vs Points for Standard Accounts
        - For most forex pairs: 1 pip = 0.0001 (4th decimal)
        - Points (pipettes): 1 point = 0.00001 (5th decimal)
        - For JPY pairs: 1 pip = 0.01 (2nd decimal)
        """
        from src.utils.pip_utils import get_pip_size
        return get_pip_size(symbol)


# Singleton instance
reply_handler_service = ReplyHandlerService()
