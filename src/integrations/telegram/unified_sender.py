"""
Unified Notification Sender
Combines Bot API (preferred) and Telethon (fallback) for sending notifications
"""
from loguru import logger
from typing import Optional

from config import settings
from src.models import TradingSignal, TradeResult, RiskAssessment


class UnifiedNotificationSender:
    """
    Unified notification sender that uses Bot API when available,
    falls back to Telethon for compatibility
    """
    
    def __init__(self):
        self.bot_sender = None
        self.telethon_sender = None
        self._initialized = False
    
    async def initialize(self, telethon_client=None):
        """
        Initialize both senders
        
        Args:
            telethon_client: Optional Telethon client for fallback
        """
        # Initialize Bot API sender if not already done and token is configured
        if not self.bot_sender:
            logger.info("📢 Initializing Bot API sender...")
            try:
                # Use the singleton instance to avoid duplicate initialization
                from src.integrations.telegram.bot_sender import bot_sender
                
                if hasattr(settings, 'telegram_bot_token') and settings.telegram_bot_token:
                    success = await bot_sender.initialize()
                    
                    if success:
                        self.bot_sender = bot_sender
                        logger.success("✅ Bot API sender initialized (preferred)")
                    else:
                        logger.warning("⚠️ Bot API initialization failed, will use Telethon")
                        self.bot_sender = None
                else:
                    logger.info("💡 Bot API not configured, using Telethon only")
                    
            except Exception as e:
                logger.warning(f"⚠️ Could not initialize Bot API sender: {e}")
                self.bot_sender = None
        
        # Initialize Telethon sender if not already done or if client is provided
        if not self.telethon_sender:
            logger.info("📢 Initializing Telethon sender...")
            try:
                from src.integrations.telegram.sender import NotificationSender
                
                self.telethon_sender = NotificationSender()
                
                if telethon_client:
                    await self.telethon_sender.initialize(client=telethon_client)
                    logger.success("✅ Telethon sender initialized (fallback)")
                else:
                    logger.info("💡 Telethon sender pending client initialization")
                    
            except Exception as e:
                logger.error(f"❌ Could not initialize Telethon sender: {e}")
                self.telethon_sender = None
        elif telethon_client and self.telethon_sender:
            # Telethon sender exists but needs client initialization
            logger.info("📢 Adding Telethon client to existing sender...")
            try:
                await self.telethon_sender.initialize(client=telethon_client)
                logger.success("✅ Telethon sender now fully initialized")
            except Exception as e:
                logger.error(f"❌ Could not add Telethon client: {e}")
        
        self._initialized = True
        
        # Log which sender is active
        if self.bot_sender and self.telethon_sender and self.telethon_sender.client:
            logger.info("📢 Notification mode: Bot API (primary) + Telethon (fallback)")
        elif self.bot_sender:
            logger.info("📢 Notification mode: Bot API only")
        elif self.telethon_sender and self.telethon_sender.client:
            logger.info("📢 Notification mode: Telethon only")
        else:
            logger.warning("⚠️ No notification senders available!")
    
    async def _send_with_fallback(self, method_name: str, *args, category: Optional[str] = None, **kwargs):
        """
        Try to send with Bot API first, fallback to Telethon

        Args:
            method_name: Name of the method to call
            category: Notification category used to check the user's per-category
                filters. Falls back to METHOD_CATEGORY_MAP when omitted; untagged
                sends are always delivered.
            *args, **kwargs: Arguments to pass to the method
        """
        # User-configurable per-category filter (dashboard → Notifications tab)
        from src.services.notification_filter_service import should_send

        if not await should_send(method_name, category):
            logger.debug(f"🔇 Notification suppressed by filter: {method_name} (category={category})")
            return True

        # Mirror to the dashboard inbox, live stream and Web Push (fire-and-forget,
        # independent of whether Telegram delivery succeeds).
        from src.services.event_pusher import event_pusher

        event_pusher.push_from_sender(method_name, args, kwargs, category)

        logger.info(f"🔔 Attempting to send: {method_name}")
        logger.debug(f"   Bot sender available: {self.bot_sender is not None}")
        logger.debug(f"   Telethon sender available: {self.telethon_sender is not None}")
        if self.telethon_sender:
            logger.debug(f"   Telethon client connected: {self.telethon_sender.client and self.telethon_sender.client.is_connected()}")
        
        # Try Bot API first
        if self.bot_sender:
            try:
                logger.info(f"📤 Attempting {method_name} via Bot API...")
                method = getattr(self.bot_sender, method_name, None)
                if method:
                    result = await method(*args, **kwargs)
                    if result:  # Success
                        logger.success(f"✅ {method_name} sent successfully via Bot API")
                        return True
                    logger.warning("Bot API send returned False, trying Telethon...")
                else:
                    logger.debug(f"Method {method_name} not found in Bot API sender")
            except Exception as e:
                logger.warning(f"Bot API failed ({method_name}): {e}, trying Telethon...")
        else:
            logger.debug("No Bot API sender configured, using Telethon")
        
        # Fallback to Telethon
        if self.telethon_sender:
            try:
                logger.info(f"📤 Attempting {method_name} via Telethon...")
                logger.debug(f"   Client exists: {self.telethon_sender.client is not None}")
                if self.telethon_sender.client:
                    logger.debug(f"   Client is_connected: {self.telethon_sender.client.is_connected()}")
                
                method = getattr(self.telethon_sender, method_name, None)
                if method:
                    result = await method(*args, **kwargs)
                    if result:
                        logger.success(f"✅ {method_name} sent successfully via Telethon")
                    else:
                        logger.warning(f"⚠️ {method_name} returned False via Telethon")
                    return result
                else:
                    logger.error(f"❌ Method {method_name} not found in Telethon sender")
                    return False
            except Exception as e:
                logger.error(f"❌ Telethon failed ({method_name}): {e}")
                logger.exception(e)
                return False
        else:
            logger.error(f"⚠️ No sender available for {method_name}")
            return False
    
    async def send_message(self, message: str, parse_mode: str = "html", category: Optional[str] = None):
        """
        Send a text message.

        Args:
            category: Notification category id (see notification_filter_service).
                Omit only for messages that must never be filtered.
        """
        await self._send_with_fallback('send_message', message, parse_mode=parse_mode, category=category)
    
    async def notify_signal_received(self, signal: TradingSignal):
        """Notify when a new signal is received"""
        await self._send_with_fallback('notify_signal_received', signal)
    
    async def notify_signal_rejected(self, signal: TradingSignal, reason: str):
        """Notify when a signal is rejected by risk management"""
        await self._send_with_fallback('notify_signal_rejected', signal, reason)
    
    async def notify_trade_executed(
        self,
        signal: TradingSignal,
        risk_assessment: RiskAssessment,
        trade_result: TradeResult,
        validation_result=None
    ):
        """Notify when a trade is executed"""
        await self._send_with_fallback(
            'notify_trade_executed',
            signal,
            risk_assessment,
            trade_result,
            validation_result=validation_result
        )
    
    async def notify_trade_failed(self, signal: TradingSignal, error: str):
        """Notify when a trade execution fails"""
        await self._send_with_fallback('notify_trade_failed', signal, error)
    
    async def notify_position_closed(
        self,
        signal: TradingSignal,
        close_price: float,
        profit_loss: float,
        profit_loss_pips: float
    ):
        """Notify when a position is closed"""
        await self._send_with_fallback(
            'notify_position_closed',
            signal,
            close_price,
            profit_loss,
            profit_loss_pips
        )
    
    async def notify_daily_summary(self, stats: dict):
        """Send daily trading summary"""
        await self._send_with_fallback('notify_daily_summary', stats)
    
    async def notify_error(self, error_type: str, error_message: str):
        """Send error notification"""
        await self._send_with_fallback('notify_error', error_type, error_message)
    
    async def notify_bot_started(self):
        """Send notification when bot starts"""
        return await self._send_with_fallback('notify_bot_started')
    
    async def notify_bot_stopped(self):
        """Send notification when bot stops"""
        return await self._send_with_fallback('notify_bot_stopped')
    
    async def notify_risk_warning(self, warning: str):
        """Send risk management warning"""
        await self._send_with_fallback('notify_risk_warning', warning)
    
    async def notify_approval_request(
        self,
        signal: TradingSignal,
        risk_assessment: RiskAssessment,
        signal_id: str,
        timeout_seconds: int,
        validation_result=None
    ):
        """Send approval request to approval channel"""
        await self._send_with_fallback(
            'notify_approval_request',
            signal,
            risk_assessment,
            signal_id,
            timeout_seconds,
            validation_result=validation_result
        )
    
    async def send_symbol_picker(self, text: str, signal_id: str, symbols: list):
        """Ask the user which instrument a vision-extracted plan belongs to."""
        return await self._send_with_fallback('send_symbol_picker', text, signal_id, symbols)

    async def notify_approval_confirmed(
        self,
        signal: TradingSignal,
        risk_assessment: RiskAssessment
    ):
        """Notify that approval was confirmed and trade is executing"""
        await self._send_with_fallback(
            'notify_approval_confirmed',
            signal,
            risk_assessment
        )
    
    async def notify_approval_timeout(
        self,
        signal: TradingSignal,
        risk_assessment: RiskAssessment
    ):
        """Notify that signal timed out waiting for approval"""
        await self._send_with_fallback(
            'notify_approval_timeout',
            signal,
            risk_assessment
        )
    
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
        await self._send_with_fallback(
            'notify_brain_action_approval',
            action_id, symbol, action, reason,
            value=value, percentage=percentage,
        )

    async def notify_missed_command(self, item_id: str, channel: str, text: str, age_minutes: int):
        """Missed-while-offline command with Apply / Skip buttons."""
        await self._send_with_fallback('notify_missed_command', item_id, channel, text, age_minutes)

    # Alias for compatibility with old code
    async def send_notification(self, message: str, category: Optional[str] = None):
        """Alias for send_message (for backward compatibility)"""
        await self.send_message(message, category=category)

    async def send_to_chat(self, chat_id: str, message: str) -> bool:
        """Post plain text to one specific chat or channel (not the notification chat).

        Bot API first — it reports failure when the bot cannot post there — then
        the Telethon account. Not subject to the notification filters: this is a
        post for the channel's readers, not an alert for the owner.
        """
        chat_id = str(chat_id or '').strip()
        if not chat_id:
            return False
        if self.bot_sender:
            try:
                import html
                if await self.bot_sender.send_direct_message_and_get_id(html.escape(message, quote=False), chat_id):
                    return True
                logger.warning(f"Bot API could not post to {chat_id}, trying Telethon...")
            except Exception as e:
                logger.warning(f"Bot API failed posting to {chat_id}: {e}, trying Telethon...")
        client = getattr(self.telethon_sender, 'client', None)
        if client:
            try:
                target = int(chat_id) if chat_id.lstrip('-').isdigit() else chat_id
                await client.send_message(target, message, parse_mode=None)
                return True
            except Exception as e:
                logger.error(f"❌ Could not post to {chat_id}: {e}")
        return False

    async def _send_to_channels(self, message: str, category: Optional[str] = None):
        """Send message to notification channels (for news alerts)"""
        # News messages use markdown formatting (** for bold)
        # Convert markdown to plain text by removing formatting
        # This ensures compatibility with both bot and telethon senders
        plain_message = message.replace('**', '')
        await self.send_message(plain_message, category=category)


# Singleton instance
notification_sender = UnifiedNotificationSender()
