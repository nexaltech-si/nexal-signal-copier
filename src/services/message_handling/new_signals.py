"""
New signals: extraction result to the trading pipeline, including multi-signal
posts split into one signal per trade.

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


class NewSignalMixin:
    """Hand new signals (and multi-signal posts) to the pipeline."""

    async def _handle_new_signal(
        self,
        event,
        message_id: MessageIdentifier,
        content: str,
        signal_callback,
        image_data: Optional[bytes] = None
    ) -> bool:
        """Handle new trading signal"""
        # Text pre-filter (free, runs before any AI call):
        # - Has text → filter regardless of image presence (catches "50 pips reached" captions)
        # - Image only (no text) → cannot pre-filter, pass through to vision AI
        has_text = len(content.strip()) >= 10
        if has_text and not signal_service.is_potential_signal(content, has_image=bool(image_data)):
            logger.debug("Message doesn't appear to be a trading signal")
            return False
        if not image_data and not has_text:
            logger.debug("Message has no text and no image — skipping")
            return False

        # Get chat info for logging
        # ALWAYS use numeric chat ID for consistency with replies
        channel_id = str(message_id.chat_id)
        try:
            chat = await event.get_chat()
            channel_name = getattr(chat, 'title', getattr(chat, 'first_name', 'Unknown'))
        except Exception:
            channel_name = "Unknown"
        
        # Get actual message date for age validation
        message_date = getattr(event.message, 'date', None)
        # Extract signal(s): a text post holding several independent trades yields one signal per trade
        t_extract = time.monotonic()
        signals = await signal_service.extract_signals(
            message_text=content,
            channel_id=channel_id,
            message_id=message_id.message_id,
            channel_name=channel_name,
            image_data=image_data,
            message_date=message_date
        )
        self._split_posts.note_extraction(
            message_id.chat_id, message_id.message_id, extracted=bool(signals),
            rejection=getattr(signal_service, 'last_rejection_reason', None),
        )
        extract_ms = int((time.monotonic() - t_extract) * 1000)
        logger.info(f"⏱️ Signal extraction: {extract_ms}ms (method={getattr(signal_service.processor, 'last_extraction_method', '?')})")

        if not signals:
            logger.debug("No signal extracted")
            return False

        if len(signals) > 1:
            await self._announce_multi_signal(message_id, signals)

        for index, signal in enumerate(signals):
            # Only the FIRST trade keeps the post's own message id. The database holds one signal per
            # (channel, message id), and the magic number derives from it, so every further trade of the
            # same post gets its own synthetic id (negative, so it can never collide with a real message).
            if index == 0:
                signal.telegram_message_id = message_id
            else:
                from src.utils.split_ids import split_message_id
                synthetic = split_message_id(message_id.message_id, index)
                from src.models.message import MessageIdentifier
                signal.telegram_message_id = MessageIdentifier(
                    chat_id=str(message_id.chat_id), message_id=synthetic,
                    message_hash=f"{message_id.message_hash}-split{index}",
                    timestamp=message_id.timestamp,
                )
                signal.message_id = synthetic
            await self._deliver_signal(signal, channel_id, signal_callback, split=len(signals) > 1)
        return True

    async def _deliver_signal(self, signal, channel_id: str, signal_callback, split: bool = False) -> None:
        """Hand one extracted signal to the trading pipeline. One failing trade must not drop its siblings."""
        has_multiple_tps = (
            signal.take_profit and
            isinstance(signal.take_profit, list) and
            len(signal.take_profit) > 1
        )
        if has_multiple_tps:
            logger.info(f"🎯 Multi-TP signal detected: {len(signal.take_profit)} levels")

        signal_action = signal.action if hasattr(signal, 'action') else signal.signal_type
        logger.success(f"✅ Trading signal detected: {signal_action} {signal.symbol}")

        # Update per-channel context with extracted signal info
        self._update_channel_context(
            channel_id, 'SIGNAL_EXTRACTED',
            symbol=signal.symbol if hasattr(signal, 'symbol') else None,
            action=signal_action.value if hasattr(signal_action, 'value') else str(signal_action),
        )
        try:
            await signal_callback(signal)
        except Exception as e:
            if not split:
                raise
            logger.error(f"❌ Trade {signal.symbol} of a multi-signal post failed: {e}")
            logger.exception(e)

    async def _announce_multi_signal(self, message_id: MessageIdentifier, signals: list) -> None:
        """One Telegram note so the user knows a single post became several independent trades."""
        try:
            from src.integrations.telegram.unified_sender import notification_sender
            lines = []
            for i, sg in enumerate(signals, 1):
                action = getattr(getattr(sg, 'action', None), 'value', getattr(sg, 'action', ''))
                lines.append(f"{i}. <b>{sg.symbol or '?'}</b> {action} — entry {sg.entry_price}, SL {sg.stop_loss}")
            await notification_sender.send_message(
                f"🧩 <b>{len(signals)} trades in one post</b> (message {message_id.message_id})\n" + "\n".join(lines)
                + "\n<i>Each is risk-checked and approved on its own. A reply to the post manages all of them.</i>",
                category='signal_received',
            )
        except Exception as e:
            logger.debug(f"Could not announce multi-signal post: {e}")
