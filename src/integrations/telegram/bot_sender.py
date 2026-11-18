"""
Telegram Bot API Sender
Uses python-telegram-bot library for official bot API
This works alongside Telethon (user client) for reading channels
"""
import asyncio
from telegram import Bot, ReplyParameters
from telegram.constants import ParseMode
from telegram.error import TelegramError
from loguru import logger

from config import settings


# Shared HTML escaping — single definition lives in src/utils/telegram_format.py
from src.utils.telegram_format import escape_html


class TelegramBotSender:
    """
    Send notifications using Telegram Bot API
    
    Requirements:
    - Bot token from @BotFather
    - Chat ID where to send messages
    
    Advantages over user client:
    - Official bot account (cleaner)
    - Better rate limits
    
    Rate limiting:
    - Max 30 messages per second per chat
    - Queue messages to avoid flood control
    - Persistent bot identity
    - No phone number required
    """
    
    def __init__(self, bot_token: str = None, chat_id: str = None):
        """
        Initialize bot sender
        
        Args:
            bot_token: Telegram bot token from @BotFather
            chat_id: Target chat ID for notifications
        """
        self.bot_token = bot_token or getattr(settings, 'telegram_bot_token', None)
        self.chat_id = chat_id or getattr(settings, 'telegram_notification_chat_id', None)
        self.bot = None
        
        # Rate limiting: Telegram allows 30 messages per second per chat
        # We'll be conservative and use 1 message per second to avoid issues
        self.message_queue = asyncio.Queue()
        self.last_message_time = 0
        self.min_message_interval = 1.0  # seconds between messages
        self.queue_processor_task = None
        
        if self.bot_token:
            self.bot = Bot(token=self.bot_token)
            logger.info("🤖 Telegram Bot API initialized")
        else:
            logger.warning("⚠️ TELEGRAM_BOT_TOKEN not configured - Bot API disabled")
    
    async def _process_message_queue(self):
        """Process queued messages with rate limiting"""
        import time
        
        while True:
            try:
                # Get next message from queue
                message_data = await self.message_queue.get()
                
                # Calculate time to wait
                current_time = time.time()
                time_since_last = current_time - self.last_message_time
                
                if time_since_last < self.min_message_interval:
                    wait_time = self.min_message_interval - time_since_last
                    logger.debug(f"⏱️ Rate limiting: waiting {wait_time:.2f}s before sending message")
                    await asyncio.sleep(wait_time)
                
                # Send the message, photo, or edit
                try:
                    action = message_data.pop('action', 'send')
                    async def send_or_edit(data, act):
                        d = dict(data)
                        if act == 'edit':
                            msg_id = d.pop('message_id')
                            await self.bot.edit_message_text(message_id=msg_id, **d)
                        elif act == 'photo':
                            await self.bot.send_photo(**d)
                        else:
                            await self.bot.send_message(**d)

                    await send_or_edit(message_data, action)
                    self.last_message_time = time.time()
                    if action == 'edit':
                        logger.debug(f"✅ Queued edit sent to {message_data.get('chat_id')}")
                    elif action == 'photo':
                        logger.debug(f"✅ Queued photo sent to {message_data.get('chat_id')}")
                    else:
                        logger.debug(f"✅ Queued message sent to {message_data.get('chat_id')}")
                except TelegramError as e:
                    if "Flood control exceeded" in str(e):
                        # Extract retry time and wait
                        retry_match = str(e).split("Retry in ")
                        if len(retry_match) > 1:
                            retry_seconds = int(retry_match[1].split()[0])
                            logger.warning(f"⚠️ Flood control hit, waiting {retry_seconds}s")
                            await asyncio.sleep(retry_seconds + 1)
                            # Retry the message
                            await send_or_edit(message_data, action)
                            self.last_message_time = time.time()
                        else:
                            logger.error(f"❌ Failed to send/edit queued message: {e}")
                    else:
                        logger.error(f"❌ Failed to send/edit queued message: {e}")
                
                self.message_queue.task_done()
                
            except asyncio.CancelledError:
                logger.info("Message queue processor cancelled")
                break
            except Exception as e:
                logger.error(f"❌ Error in message queue processor: {e}")
                await asyncio.sleep(1)
    
    async def initialize(self, timeout: int = 10):
        """Initialize and verify bot connection
        
        Args:
            timeout: Connection timeout in seconds (default: 10)
        """
        if not self.bot:
            logger.warning("⚠️ Bot not configured, skipping initialization")
            return False
        
        try:
            # Get bot info to verify token with timeout
            bot_info = await asyncio.wait_for(
                self.bot.get_me(),
                timeout=timeout
            )
            logger.success(f"✅ Bot connected: @{bot_info.username} ({bot_info.first_name})")
            
            if not self.chat_id:
                logger.warning("⚠️ TELEGRAM_NOTIFICATION_CHAT_ID not set")
                logger.info("💡 Bot is ready but needs chat_id to send messages")
                logger.info("💡 Get your chat ID from @userinfobot")
            
            # Start queue processor
            if not self.queue_processor_task:
                self.queue_processor_task = asyncio.create_task(self._process_message_queue())
                logger.info("✅ Message queue processor started")
            
            return True
        except asyncio.TimeoutError:
            logger.error(f"❌ Bot initialization failed: Connection timed out after {timeout}s")
            logger.info("💡 Check your internet connection or increase timeout")
            return False
        except TelegramError as e:
            logger.error(f"❌ Bot initialization failed: {e}")
            return False
    
    async def send_message(
        self,
        text: str,
        parse_mode: str = ParseMode.HTML,
        chat_id: str = None,
        disable_notification: bool = False
    ):
        """
        Send a text message (queued with rate limiting)
        
        Args:
            text: Message text
            parse_mode: Parse mode (HTML or Markdown)
            chat_id: Optional chat ID (defaults to configured notification chat)
            disable_notification: Send silently
        """
        if not self.bot:
            logger.warning("⚠️ Bot not initialized")
            return False
        
        # Use provided chat_id or fall back to default
        target_chat_id = chat_id or self.chat_id
        
        if not target_chat_id:
            logger.error("❌ No chat_id specified and no default configured")
            return False
        
        # Queue the message instead of sending directly
        message_data = {
            'chat_id': target_chat_id,
            'text': text,
            'parse_mode': parse_mode,
            'disable_notification': disable_notification
        }
        
        await self.message_queue.put(message_data)
        logger.debug(f"📥 Message queued for {target_chat_id} (queue size: {self.message_queue.qsize()})")
        return True

    async def send_direct_message_and_get_id(
        self,
        text: str,
        chat_id: str,
        parse_mode: str = ParseMode.HTML,
    ) -> int | None:
        """
        Send a message directly (bypasses queue) and return the Telegram message_id.
        Used when we need the message_id back (e.g. initial signal forward post).
        """
        if not self.bot:
            logger.warning("⚠️ Bot not initialized")
            return None
        try:
            msg = await self.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
            )
            logger.debug(f"📤 Direct message sent to {chat_id}, message_id={msg.message_id}")
            return msg.message_id
        except TelegramError as e:
            logger.error(f"❌ Failed to send direct message: {e}")
            return None

    async def send_reply(
        self,
        text: str,
        chat_id: str,
        reply_to_message_id: int,
        parse_mode: str = ParseMode.HTML,
    ):
        """
        Queue a reply to a specific message in a channel.
        Used to post position action updates under the original signal post.
        """
        if not self.bot:
            logger.warning("⚠️ Bot not initialized")
            return False
        message_data = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': parse_mode,
            'reply_parameters': ReplyParameters(message_id=reply_to_message_id),
        }
        await self.message_queue.put(message_data)
        logger.debug(f"📥 Reply queued for {chat_id} reply_to={reply_to_message_id}")
        return True

    async def edit_message(
        self,
        text: str,
        chat_id: str,
        message_id: int,
        parse_mode: str = ParseMode.HTML,
    ) -> bool:
        """
        Queue a message edit.
        """
        if not self.bot:
            logger.warning("⚠️ Bot not initialized")
            return False
        message_data = {
            'action': 'edit',
            'chat_id': chat_id,
            'message_id': message_id,
            'text': text,
            'parse_mode': parse_mode,
        }
        await self.message_queue.put(message_data)
        logger.debug(f"📥 Edit message queued for {chat_id} msg_id={message_id}")
        return True

    async def notify_trade_executed(
        self,
        signal,  # TradingSignal
        risk_assessment,  # RiskAssessment  
        trade_result,  # TradeResult
        validation_result=None
    ):
        """Notify when a trade is executed"""
        # Extract signal type
        signal_type = getattr(signal, 'signal_type', None) or getattr(signal, 'action', None)
        signal_type_str = signal_type.value if hasattr(signal_type, 'value') else str(signal_type)
        
        # Format entry - show range if available, otherwise single price
        has_range = (hasattr(signal, 'entry_range_min') and signal.entry_range_min and 
                    hasattr(signal, 'entry_range_max') and signal.entry_range_max)
        
        if has_range:
            entry_display = f"{signal.entry_range_max} - {signal.entry_range_min} (Range)"
        else:
            entry_display = f"{trade_result.entry_price:.5f}" if trade_result.entry_price else "Market"
        
        stop_loss = f"{signal.stop_loss:.5f}" if signal.stop_loss else "N/A"
        
        # Handle multi-TP (list) vs single TP (float)
        if signal.take_profit:
            if isinstance(signal.take_profit, list):
                take_profit = ", ".join([f"{tp:.5f}" for tp in signal.take_profit])
            else:
                take_profit = f"{signal.take_profit:.5f}"
        else:
            take_profit = "N/A"
            
        sl_pips = f"({risk_assessment.stop_loss_pips:.1f} pips)" if risk_assessment.stop_loss_pips else ""
        tp_pips = f"({risk_assessment.take_profit_pips:.1f} pips)" if risk_assessment.take_profit_pips else ""
        
        # Escape dynamic content
        safe_symbol = escape_html(signal.symbol)
        safe_position_id = escape_html(str(trade_result.position_id)) if trade_result.position_id else 'N/A'
        escape_html(str(trade_result.order_id)) if trade_result.order_id else 'N/A'
        
        # Format values with None handling
        risk_percent = f"{risk_assessment.risk_percent:.2f}%" if risk_assessment.risk_percent else "N/A"
        risk_reward = f"1:{risk_assessment.risk_reward_ratio:.2f}" if risk_assessment.risk_reward_ratio else "N/A"
        
        # Add range distribution info if applicable
        range_info = ""
        if has_range:
            num_tps = len(signal.take_profit) if signal.take_profit else 1
            range_info = f"\n<i>📍 {num_tps} order(s) distributed across entry range</i>\n"
        
        # Build Signal Validator block
        validator_line = ""
        if validation_result is not None:
            if validation_result.is_unavailable:
                validator_line = "\n━━━━━━━━━━━━━━━━━━━\n🔍 <b>Signal Validator:</b> ⚠️ Unavailable\n━━━━━━━━━━━━━━━━━━━"
            else:
                v_emoji = validation_result.verdict_emoji
                v_score = f"{validation_result.score:.0f}/100" if validation_result.score is not None else "N/A"
                v_type = validation_result.trade_type or "N/A"
                v_rr = f"{validation_result.rr_tp2:.1f}x" if validation_result.rr_tp2 is not None else "N/A"
                v_sl = f"{validation_result.sl_pips:.0f} pips" if validation_result.sl_pips is not None else "N/A"
                v_regime = escape_html(validation_result.regime_label or "N/A")
                validator_line = (
                    f"\n━━━━━━━━━━━━━━━━━━━"
                    f"\n🔍 <b>Signal Validator</b>"
                    f"\n<b>Verdict:</b> {v_emoji} {validation_result.verdict}  |  <b>Score:</b> {v_score}"
                    f"\n<b>Type:</b> {v_type}  |  <b>R:R TP2:</b> {v_rr}  |  <b>SL:</b> {v_sl}"
                    f"\n<b>Regime:</b> {v_regime}"
                )
                if validation_result.warnings:
                    safe_warns = escape_html("; ".join(validation_result.warnings))
                    validator_line += f"\n⚠️ <i>{safe_warns}</i>"
                if validation_result.issues:
                    safe_issues = escape_html("; ".join(validation_result.issues))
                    validator_line += f"\n❌ <i>{safe_issues}</i>"
                validator_line += "\n━━━━━━━━━━━━━━━━━━━"

        title = (f"➕ <b>{signal_type_str} {safe_symbol} added to the running signal</b>"
                 if getattr(signal, 'continuation_of', None)
                 else f"✅ <b>{signal_type_str} {safe_symbol} is live</b>")
        message = f"""
{title}

💰 Entry: <code>{entry_display}</code>{range_info}
🛑 SL: <code>{stop_loss}</code> {sl_pips}
🎯 TP: <code>{take_profit}</code> {tp_pips}
📊 Risk: <code>{risk_percent}</code>  |  R:R <code>{risk_reward}</code>
{validator_line}
<code>{safe_position_id}</code>
"""
        return await self.send_message(message)
    
    async def notify_signal_received(self, signal):
        """Notify when a new signal is received"""
        signal_type = getattr(signal, 'signal_type', None) or getattr(signal, 'action', None)
        signal_type_str = signal_type.value if hasattr(signal_type, 'value') else str(signal_type)
        
        # Display entry range if available, otherwise single entry price
        has_range = (hasattr(signal, 'entry_range_min') and signal.entry_range_min and 
                    hasattr(signal, 'entry_range_max') and signal.entry_range_max)
        if has_range:
            pass
        else:
            pass
        
        # Escape dynamic content
        safe_symbol = escape_html(signal.symbol)
        safe_channel = escape_html(str(getattr(signal, 'channel_name', None) or signal.channel_id))
        
        direction = getattr(signal, 'order_type', None)
        dir_str = direction.value if hasattr(direction, 'value') else str(direction or "")
        dir_emoji = "🟢" if dir_str.upper() == "BUY" else "🔴" if dir_str else ""
        
        message = (
            f"📡 {dir_emoji} {signal_type_str} <b>{safe_symbol}</b> "
            f"from {safe_channel} — checking it now..."
        )
        return await self.send_message(message)
    
    async def notify_signal_rejected(self, signal, reason: str):
        """Notify when a signal is rejected by risk management"""
        signal_type = getattr(signal, 'signal_type', None) or getattr(signal, 'action', None)
        signal_type_str = signal_type.value if hasattr(signal_type, 'value') else str(signal_type)
        
        # Escape dynamic content
        safe_symbol = escape_html(signal.symbol)
        safe_reason = escape_html(reason)
        
        direction = getattr(signal, 'order_type', None)
        dir_str = direction.value if hasattr(direction, 'value') else str(direction or "")
        dir_emoji = "🟢" if dir_str.upper() == "BUY" else "🔴" if dir_str else ""
        
        message = f"⏭️ {dir_emoji} Skipped {signal_type_str} <b>{safe_symbol}</b> — {safe_reason}"
        return await self.send_message(message)
    
    async def notify_trade_failed(self, signal, error: str):
        """Notify when a trade execution fails"""
        signal_type = getattr(signal, 'signal_type', None) or getattr(signal, 'action', None)
        signal_type_str = signal_type.value if hasattr(signal_type, 'value') else str(signal_type)
        
        # Escape dynamic content
        safe_symbol = escape_html(signal.symbol)
        safe_error = escape_html(error)
        
        direction = getattr(signal, 'order_type', None)
        dir_str = direction.value if hasattr(direction, 'value') else str(direction or "")
        dir_emoji = "🟢" if dir_str.upper() == "BUY" else "🔴" if dir_str else ""
        message = f"❌ {dir_emoji} Couldn't open {signal_type_str} <b>{safe_symbol}</b> — {safe_error}"
        return await self.send_message(message)
    
    async def notify_position_closed(
        self,
        signal,
        close_price: float,
        profit_loss: float,
        profit_loss_pips: float
    ):
        """Notify when a position is closed"""
        is_profit = profit_loss > 0
        emoji = "💰" if is_profit else "📉"
        
        # Escape dynamic content
        safe_symbol = escape_html(signal.symbol)
        
        entry_str = f"{signal.entry_price:.5f}" if signal.entry_price else "—"
        message = (
            f"{emoji} <b>{safe_symbol}</b> closed  <code>{profit_loss:+.2f}$</code>  ({profit_loss_pips:+.1f} pips)\n"
            f"<code>{entry_str}</code> → <code>{close_price:.5f}</code>"
        )
        return await self.send_message(message)
    
    async def notify_daily_summary(self, stats: dict):
        """Send daily trading summary"""
        pl = stats.get('total_pl', 0)
        pl_emoji = "📈" if pl >= 0 else "📉"
        message = f"""
{pl_emoji} <b>End of day</b>

{stats.get('executed', 0)} trades taken, {stats.get('rejected', 0)} skipped
P/L: <code>${pl:+.2f}</code>  |  Win rate: {stats.get('win_rate', 0):.0f}%
Best: <code>${stats.get('best_trade', 0):+.2f}</code>  |  Worst: <code>${stats.get('worst_trade', 0):+.2f}</code>

Balance: <code>${stats.get('start_balance', 0):.2f}</code> → <code>${stats.get('current_balance', 0):.2f}</code>  ({stats.get('daily_change_percent', 0):+.2f}%)
"""
        return await self.send_message(message)
    
    async def notify_error(self, error_type: str, error_message: str):
        """Send error notification"""
        # Escape dynamic content
        safe_error_type = escape_html(error_type)
        safe_error_message = escape_html(error_message)
        
        msg = f"🚨 <b>{safe_error_type}:</b> {safe_error_message}"
        return await self.send_message(msg)
    
    async def notify_bot_started(self):
        """Notify when bot starts"""
        from datetime import datetime
        return await self.send_message(
            f"🟢 <b>Bot started</b>\n"
            f"Monitoring channels for signals.\n"
            f"<i>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>"
        )
    
    async def notify_bot_stopped(self):
        """Notify when bot stops - sends directly (bypasses queue) to ensure delivery during shutdown"""
        if not self.bot:
            logger.warning("⚠️ Bot not initialized")
            return False

        target_chat_id = self.chat_id
        if not target_chat_id:
            logger.error("❌ No chat_id configured")
            return False

        import time
        try:
            await asyncio.wait_for(
                self.bot.send_message(
                    chat_id=target_chat_id,
                    text="🔴 <b>Bot stopped</b>",
                    parse_mode=ParseMode.HTML,
                ),
                timeout=8.0,
            )
            self.last_message_time = time.time()
            logger.debug("✅ Stop notification sent directly")
            return True
        except BaseException as e:
            logger.error(f"❌ Failed to send stop notification directly: {e}")
            return False
    
    async def notify_risk_warning(self, warning: str):
        """Send risk management warning"""
        # Escape dynamic content
        safe_warning = escape_html(warning)
        
        message = f"⚠️ Heads up — {safe_warning}"
        return await self.send_message(message)
    
    async def notify_approval_request(
        self,
        signal,
        risk_assessment,
        signal_id: str,
        timeout_seconds: int,
        validation_result=None
    ):
        """Send approval request to approval channel with inline buttons"""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        
        # Get target chat ID (approval channel or default notification channel)
        target_chat_id = getattr(settings, 'approval_channel_id', None) or self.chat_id
        
        if not target_chat_id:
            logger.error("❌ No approval channel configured")
            return False
        
        # Extract signal details
        symbol = escape_html(str(signal.symbol))
        action = getattr(signal, 'action', None)
        action_str = action.value if hasattr(action, 'value') else str(action)
        action_str = escape_html(action_str)

        # Direction: BUY or SELL
        order_type = getattr(signal, 'order_type', None)
        direction_str = order_type.value if hasattr(order_type, 'value') else (str(order_type) if order_type else None)

        # Order type: Market / Limit / Stop (derived from signal_type)
        signal_type = getattr(signal, 'signal_type', None)
        signal_type_val = signal_type.value if hasattr(signal_type, 'value') else (str(signal_type) if signal_type else "")
        if "LIMIT" in signal_type_val.upper():
            order_type_label = "LIMIT ORDER"
        elif "STOP" in signal_type_val.upper():
            order_type_label = "STOP ORDER"
        else:
            order_type_label = "MARKET ORDER"

        # Channel source
        channel_name = getattr(signal, 'channel_name', None) or getattr(signal, 'channel_id', None)
        channel_str = escape_html(str(channel_name)) if channel_name else "Unknown"

        # Display entry range if available, otherwise single entry price
        has_range = (hasattr(signal, 'entry_range_min') and signal.entry_range_min and
                    hasattr(signal, 'entry_range_max') and signal.entry_range_max)
        if has_range:
            entry = f"{signal.entry_range_max} - {signal.entry_range_min} (Range)"
        else:
            entry = signal.entry_price or "Market"

        sl = signal.stop_loss or "N/A"
        tp = signal.take_profit[0] if signal.take_profit else "N/A"

        risk_pct = risk_assessment.risk_percent
        rr_ratio = risk_assessment.risk_reward_ratio

        # Round up to show correct minutes (e.g., 237 seconds = 4 minutes, not 3)
        import math
        timeout_min = math.ceil(timeout_seconds / 60)

        # Add range distribution info if applicable
        range_info = ""
        if has_range:
            num_tps = len(signal.take_profit) if signal.take_profit else 1
            range_info = f"\n<i>📍 Will distribute {num_tps} order(s) across entry range</i>\n"

        # Build Signal Validator block
        validator_block = ""
        if validation_result is not None:
            if validation_result.is_unavailable:
                validator_block = "\n\u2501" * 1 + "\n🔍 <b>Signal Validator:</b> ⚠️ Unavailable\n"
            else:
                v_emoji = validation_result.verdict_emoji
                v_score = f"{validation_result.score:.0f}/100" if validation_result.score is not None else "N/A"
                v_type = validation_result.trade_type or "N/A"
                v_rr = f"{validation_result.rr_tp2:.1f}x" if validation_result.rr_tp2 is not None else "N/A"
                v_sl = f"{validation_result.sl_pips:.0f} pips" if validation_result.sl_pips is not None else "N/A"
                v_regime = escape_html(validation_result.regime_label or "N/A")
                validator_block = (
                    f"\n━━━━━━━━━━━━━━━━━━━"
                    f"\n🔍 <b>Signal Validator</b>"
                    f"\n<b>Verdict:</b> {v_emoji} {validation_result.verdict}  |  <b>Score:</b> {v_score}"
                    f"\n<b>Type:</b> {v_type}  |  <b>R:R TP2:</b> {v_rr}  |  <b>SL:</b> {v_sl}"
                    f"\n<b>Regime:</b> {v_regime}"
                )
                if validation_result.warnings:
                    safe_warns = escape_html("; ".join(validation_result.warnings))
                    validator_block += f"\n⚠️ <i>{safe_warns}</i>"
                if validation_result.issues:
                    safe_issues = escape_html("; ".join(validation_result.issues))
                    validator_block += f"\n❌ <i>{safe_issues}</i>"
                validator_block += "\n━━━━━━━━━━━━━━━━━━━"

        # Surface risk_assessment.warnings (e.g. "Auto-generated TP levels", "SL adjusted
        # for spread") — without this, synthesized/adjusted values look identical to
        # values the AI actually read off the chart, which is misleading for approval.
        warnings_block = ""
        if getattr(risk_assessment, 'warnings', None):
            safe_warnings = [escape_html(w) for w in risk_assessment.warnings]
            warnings_block = "\n" + "\n".join(f"⚠️ <i>{w}</i>" for w in safe_warnings)

        # High-risk override banner — this trade breaches the configured risk
        # limit and is only being offered because ALLOW_HIGH_RISK_OVERRIDE is on.
        # Make the extra risk impossible to miss before the user taps "Take it".
        high_risk_block = ""
        prompt_line = "Got a signal. Want me to take this?"
        if getattr(risk_assessment, 'risk_limit_exceeded', False):
            max_risk = getattr(settings, 'max_risk_per_trade_percent', 0)
            high_risk_block = (
                "🚨🚨🚨 <b>HIGH-RISK TRADE — READ BEFORE APPROVING</b> 🚨🚨🚨\n"
                "━━━━━━━━━━━━━━━━━━━\n"
                f"⚠️ This trade risks <b>{risk_pct:.2f}%</b> of your balance "
                f"(<b>${risk_assessment.risk_amount:,.2f}</b>).\n"
                f"⚠️ That is ABOVE your maximum of <b>{max_risk}%</b>.\n"
                f"⚠️ Lot size is already at the minimum — the risk cannot be reduced further.\n"
                "⚠️ Approving means you <b>accept the extra risk on purpose</b>.\n"
                "━━━━━━━━━━━━━━━━━━━\n"
            )
            prompt_line = "Over your risk limit — approve only if you accept it. Skip otherwise."

        direction_line = f" <b>{direction_str}</b>" if direction_str else ""
        message = f"""
{high_risk_block}{prompt_line}

{direction_line} <b>{symbol}</b>  —  {order_type_label}
from {channel_str}

Entry: <code>{entry}</code>{range_info}
SL: <code>{sl}</code>   TP: <code>{tp}</code>
Risk: {risk_pct:.1f}%  |  R:R {rr_ratio:.1f}
{warnings_block}
{validator_block}
<code>{signal_id[:16]}</code>  ·  expires in {timeout_min} min
"""

        # Create inline keyboard with approve/reject buttons
        approve_label = "Take it ✅"
        reject_label = "Pass ❌"
        if getattr(risk_assessment, 'risk_limit_exceeded', False):
            approve_label = "Accept high risk ⚠️"
            reject_label = "Skip ❌"
        keyboard = [
            [
                InlineKeyboardButton(approve_label, callback_data=f"approve:{signal_id}"),
                InlineKeyboardButton(reject_label, callback_data=f"reject:{signal_id}")
            ],
            [
                InlineKeyboardButton("See all pending 📋", callback_data="pending")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # When signal has an image AND the setting is enabled, send photo before the approval text.
        # (Telegram captions are limited to 1024 chars; approval messages can exceed that,
        #  so the image is sent as a standalone photo followed by the full text+buttons.)
        image_bytes = getattr(signal, 'image_data', None)
        if not image_bytes and signal_id:
            try:
                from src.core.database_service import db_service
                import base64
                db_sig = await db_service.db.signal.find_unique(
                    where={"id": signal_id},
                )
                if db_sig and getattr(db_sig, 'imageData', None):
                    image_bytes = base64.b64decode(db_sig.imageData)
                    logger.debug("📸 Signal image loaded from DB for approval notification")
            except Exception as _e:
                logger.debug(f"DB image fetch skipped: {_e}")
        send_image_enabled = getattr(settings, 'approval_send_image', True)
        if image_bytes and send_image_enabled:
            from io import BytesIO
            from telegram import InputFile
            photo_data = {
                'action': 'photo',
                'chat_id': target_chat_id,
                'photo': InputFile(BytesIO(image_bytes), filename='signal.jpg'),
            }
            await self.message_queue.put(photo_data)
            logger.debug(f"📥 Signal image queued for {target_chat_id}")

        # Always send the full approval text with buttons
        message_data = {
            'chat_id': target_chat_id,
            'text': message,
            'parse_mode': ParseMode.HTML,
            'reply_markup': reply_markup,
        }
        await self.message_queue.put(message_data)
        logger.debug(f"📥 Approval request queued for {target_chat_id}")
        return True
    
    async def notify_approval_confirmed(self, signal, risk_assessment):
        """Notify that approval was confirmed"""
        symbol = escape_html(str(signal.symbol))
        action = getattr(signal, 'action', None)
        action_str = action.value if hasattr(action, 'value') else str(action)
        action_str = escape_html(action_str)
        
        message = f"Got it — opening {action_str} <b>{symbol}</b> now."
        return await self.send_message(message)
    
    async def notify_brain_action_approval(
        self,
        action_id: str,
        symbol: str,
        action: str,
        reason: str,
        value=None,
        percentage=None,
    ):
        """Send brain position-action approval request with Approve/Reject buttons."""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        target_chat_id = getattr(settings, 'approval_channel_id', None) or self.chat_id
        if not target_chat_id:
            logger.error("❌ No approval channel configured for brain action")
            return False

        symbol_safe = escape_html(str(symbol))
        action_safe = escape_html(str(action))
        reason_safe = escape_html(str(reason))

        if action == "MODIFY_SL" and value is not None:
            action_text = f"move the SL to <code>{value}</code>"
        elif action == "MODIFY_TP" and value is not None:
            action_text = f"move the TP to <code>{value}</code>"
        elif action == "PARTIAL_CLOSE":
            pct = percentage or 50
            action_text = f"close {pct}% of the position"
        elif action == "CLOSE":
            action_text = "close the position"
        else:
            action_text = action_safe.lower()

        message = (
            f"🧠 <b>{symbol_safe}</b> — I want to {action_text}.\n\n"
            f"{reason_safe}\n\n"
            f"Your call — 5 min to decide.\n"
            f"<code>{action_id[:16]}</code>"
        )

        keyboard = [[
            InlineKeyboardButton("Do it ✅", callback_data=f"brain_action:approve:{action_id}"),
            InlineKeyboardButton("No ❌",    callback_data=f"brain_action:reject:{action_id}"),
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        message_data = {
            'chat_id': target_chat_id,
            'text': message,
            'parse_mode': ParseMode.HTML,
            'reply_markup': reply_markup,
        }
        await self.message_queue.put(message_data)
        return True

    async def notify_missed_command(self, item_id: str, channel: str, text: str, age_minutes: int):
        """A channel posted a management command while the bot was offline: Apply / Skip buttons."""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        target_chat_id = getattr(settings, 'approval_channel_id', None) or self.chat_id
        if not target_chat_id:
            logger.error("❌ No approval channel configured for missed-command request")
            return False

        when = f"{age_minutes} min ago" if age_minutes < 120 else f"{age_minutes / 60:.1f} h ago"
        message = (
            f"📬 <b>Missed command</b> from {escape_html(str(channel))} ({when})\n\n"
            f"<i>{escape_html(str(text)[:400])}</i>\n\n"
            f"The bot was offline when this was posted. Apply it now against the CURRENT state of your trades?\n"
            f"<code>{item_id}</code>"
        )
        keyboard = [[
            InlineKeyboardButton("Apply now ✅", callback_data=f"catchup:apply:{item_id}"),
            InlineKeyboardButton("Skip ❌", callback_data=f"catchup:skip:{item_id}"),
        ]]
        await self.message_queue.put({
            'chat_id': target_chat_id,
            'text': message,
            'parse_mode': ParseMode.HTML,
            'reply_markup': InlineKeyboardMarkup(keyboard),
        })
        return True

    async def send_symbol_picker(self, text: str, signal_id: str, symbols: list):
        """Ask the user which instrument a vision-extracted plan belongs to.

        `symbols` items are either plain tickers or {"symbol", "label"} dicts —
        the matcher uses the latter to show each candidate's live price. Anything
        not on the keyboard goes through the /symbol <TICKER> command instead.
        """
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        target_chat_id = getattr(settings, 'approval_channel_id', None) or self.chat_id
        if not target_chat_id:
            logger.error("❌ No chat configured for symbol clarification request")
            return False

        entries = []
        for item in (symbols or []):
            if isinstance(item, dict):
                sym = str(item.get('symbol') or '').strip()
                label = str(item.get('label') or sym).strip()
            else:
                sym = label = str(item).strip()
            if not sym:
                continue
            callback = f"symbol_pick:{signal_id}:{sym}"
            # Telegram hard-caps callback_data at 64 bytes — skip anything that
            # wouldn't survive the round trip rather than sending a broken button.
            if len(callback.encode('utf-8')) > 64:
                logger.warning(f"Skipping symbol button for {sym} — callback data too long")
                continue
            entries.append((label, callback))

        per_row = 2 if any(label != cb.rsplit(':', 1)[-1] for label, cb in entries) else 4
        rows = []
        row = []
        for label, callback in entries:
            row.append(InlineKeyboardButton(label, callback_data=callback))
            if len(row) == per_row:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        reply_markup = InlineKeyboardMarkup(rows) if rows else None

        message_data = {
            'chat_id': target_chat_id,
            'text': text,
            'parse_mode': ParseMode.HTML,
            'reply_markup': reply_markup,
        }
        await self.message_queue.put(message_data)
        return True

    async def notify_approval_timeout(self, signal, risk_assessment):
        """Notify that signal timed out"""
        symbol = escape_html(str(signal.symbol))
        action = getattr(signal, 'action', None)
        action_str = action.value if hasattr(action, 'value') else str(action)
        action_str = escape_html(action_str)
        
        message = f"⏰ No answer in time — skipped {action_str} <b>{symbol}</b>."
        return await self.send_message(message)
    
    # Alias for compatibility
    async def send_notification(self, message: str):
        """Alias for send_message (for backward compatibility)"""
        return await self.send_message(message)


# Singleton instance
bot_sender = TelegramBotSender()


# Example usage
if __name__ == "__main__":
    async def test():
        """Test bot sender"""
        # You can pass token and chat_id here or use .env
        sender = TelegramBotSender(
            bot_token="YOUR_BOT_TOKEN",  # Get from @BotFather
            chat_id="YOUR_CHAT_ID"       # Get from @userinfobot
        )
        
        # Initialize
        success = await sender.initialize()
        if not success:
            print("❌ Initialization failed")
            return
        
        # Send test message
        await sender.send_message("✅ Test message from python-telegram-bot!")
        
        # Send trade notification
        await sender.notify_trade_executed(
            symbol="XAUUSD",
            direction="BUY",
            entry=2645.50,
            lot_size=0.5
        )
    
    # Run test
    asyncio.run(test())
