"""
Replies that are really new trades: "re-enter" replies to a closed signal and
fresh entries posted as replies, plus flagging unclear replies for review.

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


class ReplySignalMixin:
    """Turn re-entry replies and entries posted as replies into signals."""

    @staticmethod
    def _looks_like_entry_with_levels(text: str) -> bool:
        """Direction + a price + a stop level: worth a full signal extraction."""
        t = text.lower()
        return bool(
            re.search(r'\b(buy|sell|long|short|re-?enter|re-?entry)\b', t)
            and re.search(r'\b(sl|stop\s*loss|stop)\b', t)
            and re.search(r'\b\d{3,6}(?:\.\d+)?\b', t)
        )

    async def _try_reenter_from_reply(
        self,
        event,
        message_id: MessageIdentifier,
        reply_to_msg_id: int,
        content: str,
        signal_callback,
        image_data: Optional[bytes] = None,
    ) -> bool:
        """
        Handle "reenter" replies: re-open the ORIGINAL signal's trade — same symbol
        and direction, market entry, original SL/TP — unless the reply text states
        new values (e.g. "reenter, SL 4150 TP 4180"). The rebuilt signal goes through
        the normal pipeline (risk sizing, SL-side validation, approval rules).
        """
        if not signal_callback or not content or not self._REENTER_RE.search(content):
            return False

        # Look up the original signal this reply points to
        orig_identifier = MessageIdentifier(
            chat_id=message_id.chat_id,
            message_id=reply_to_msg_id,
            message_hash="",
            timestamp=datetime.now(),
        )
        orig = await db_service.find_signal_by_message(orig_identifier)
        if not orig or not getattr(orig, 'symbol', None):
            logger.info("🔁 Reenter requested but original signal not found — trying full extraction instead")
            return False
        orig_action = str(getattr(orig, 'action', '') or '').upper()
        if orig_action and orig_action != 'OPEN':
            return False
        ot = str(getattr(orig, 'orderType', '') or '').upper()
        order_type = OrderType.BUY if ot == 'BUY' else (OrderType.SELL if ot == 'SELL' else None)
        if order_type is None:
            return False

        # SL/TP from the original signal, overridable by explicit values in the reply
        stop_loss = getattr(orig, 'stopLoss', None)
        take_profits: list = []
        raw_tp = getattr(orig, 'takeProfit', None)
        if raw_tp:
            try:
                import json
                parsed = json.loads(raw_tp) if isinstance(raw_tp, str) else raw_tp
                if isinstance(parsed, list):
                    take_profits = [float(x) for x in parsed if x is not None]
            except Exception as _exc:
                logger.debug(f"Suppressed exception: {_exc!r}")

        sl_override = re.search(r'\bsl\b\s*[:@]?\s*(\d+(?:\.\d+)?)', content, re.IGNORECASE)
        if sl_override:
            stop_loss = float(sl_override.group(1))
        tp_overrides = re.findall(r'\btp\d?\b\s*[:@]?\s*(\d+(?:\.\d+)?)', content, re.IGNORECASE)
        if tp_overrides:
            take_profits = [float(x) for x in tp_overrides]
        entry_override = re.search(r'(?:\bentry\b|\bat\b|@)\s*:?\s*(\d{2,6}(?:\.\d+)?)', content, re.IGNORECASE)
        entry_price = float(entry_override.group(1)) if entry_override else None

        if not stop_loss:
            logger.warning("🔁 Reenter: original signal has no SL and the reply provides none — skipping for safety")
            return False

        channel_id = str(message_id.chat_id)
        try:
            chat = await event.get_chat()
            channel_name = getattr(chat, 'title', getattr(chat, 'first_name', 'Unknown'))
        except Exception:
            channel_name = "Unknown"

        # A market reentry (no entry price) is an instant entry where the channel allows it
        from src.services.execution_policy import instant_execution_allowed
        instant = entry_price is None and instant_execution_allowed(channel_id)[0]

        signal = TradingSignal(
            symbol=orig.symbol,
            action=SignalAction.OPEN,
            order_type=order_type,
            entry_price=entry_price,  # None → market execution
            stop_loss=float(stop_loss),
            take_profit=take_profits,
            raw_message=content,
            confidence=0.9,
            channel_id=channel_id,
            channel_name=channel_name,
            message_id=message_id.message_id,
            instant_execution=instant,
            image_data=image_data,
        )
        message_date = getattr(event.message, 'date', None)
        if message_date:
            signal.timestamp = message_date
        signal.status = SignalStatus.VALIDATED
        signal.telegram_message_id = message_id

        logger.success(
            f"🔁 REENTER: re-opening {order_type.value} {orig.symbol} from original signal "
            f"(entry: {entry_price or 'MARKET'}, SL: {stop_loss}, TPs: {take_profits})"
        )
        await signal_callback(signal)
        return True

    async def _try_signal_from_reply(
        self,
        event,
        message_id: MessageIdentifier,
        reply_to_msg_id: int,
        content: str,
        signal_callback,
        image_data: Optional[bytes] = None,
    ) -> bool:
        """
        A reply that isn't a recognized trade command may be a brand-new signal
        (providers often post fresh entries as replies to old messages). Run full
        extraction; only OPEN signals proceed — anything command-like was already
        attempted by the reply handler.

        Guarded against the reply actually being commentary/instructions about the
        ORIGINAL signal (e.g. "you can close the signal now") which the command
        parser failed to recognize — that must never be reinterpreted as a fresh
        trade to open. When the reply resolves to an original signal, we refuse to
        treat it as new unless it clearly introduces different price levels.
        """
        if not signal_callback:
            return False
        has_text = len((content or '').strip()) >= 10
        if not has_text and not image_data:
            return False
        if has_text and not signal_service.is_potential_signal(content, has_image=bool(image_data)):
            return False

        orig = None
        try:
            orig_identifier = MessageIdentifier(
                chat_id=message_id.chat_id,
                message_id=reply_to_msg_id,
                message_hash="",
                timestamp=datetime.now(),
            )
            orig = await db_service.find_signal_by_message(orig_identifier)
        except Exception as e:
            logger.debug(f"Could not resolve original signal for reply guard: {e}")

        if orig and getattr(orig, 'symbol', None):
            if has_text and self._is_explicit_close_command(content):
                logger.info(
                    f"🛑 Reply guard: reply to {orig.symbol} reads as close/invalidate "
                    f"language, not a new signal — refusing to reinterpret as OPEN"
                )
                await self._flag_reply_for_manual_review(orig, content)
                return False

        channel_id = str(message_id.chat_id)
        try:
            chat = await event.get_chat()
            channel_name = getattr(chat, 'title', getattr(chat, 'first_name', 'Unknown'))
        except Exception:
            channel_name = "Unknown"
        message_date = getattr(event.message, 'date', None)

        signal = await signal_service.extract_signal(
            message_text=content,
            channel_id=channel_id,
            message_id=message_id.message_id,
            channel_name=channel_name,
            image_data=image_data,
            message_date=message_date,
            context_symbol=getattr(orig, 'symbol', None) if orig else None,
        )
        # Note: plan signals are registered inside extract_signal and return None here
        if not signal:
            return False
        if signal.action != SignalAction.OPEN:
            logger.debug("Reply fallback: extracted non-OPEN action — already handled as command, ignoring")
            return False

        # Safety net: if this reply resolves to the same symbol as the signal it
        # replied to, and doesn't introduce any price level the original didn't
        # already have, it's almost certainly commentary about that original signal
        # (e.g. naming its setup while discussing it) rather than a genuinely new
        # trade — the extraction just mislabeled it as OPEN.
        def _differs(a: Optional[float], b: Optional[float]) -> bool:
            if a is None or b is None:
                return a is not None
            return abs(a - b) / max(abs(a), abs(b), 1e-9) > 0.0005

        if orig and getattr(orig, 'symbol', None) == signal.symbol:
            orig_entry = getattr(orig, 'entryPrice', None)
            orig_sl = getattr(orig, 'stopLoss', None)
            introduces_new_price = (
                _differs(signal.entry_price, orig_entry)
                or _differs(signal.stop_loss, orig_sl)
                or bool(signal.take_profit)
            )
            if not introduces_new_price:
                logger.info(
                    f"🛑 Reply guard: reply extraction matched {signal.symbol} from the "
                    f"replied-to signal with no new price levels — treating as commentary, "
                    f"not a new trade"
                )
                await self._flag_reply_for_manual_review(orig, content)
                return False

        signal.telegram_message_id = message_id
        logger.success(f"✅ NEW signal detected inside a reply: {signal.action} {signal.symbol}")
        await signal_callback(signal)
        return True

    async def _flag_reply_for_manual_review(self, orig, content: str) -> None:
        """Surface a reply the automation refused to act on, instead of failing silently."""
        try:
            from src.integrations.telegram.unified_sender import notification_sender
            symbol = getattr(orig, 'symbol', '?')
            msg = (
                f"⚠️ <b>Reply Needs Manual Review</b>\n"
                f"📊 <b>Symbol:</b> {symbol}\n"
                f"💬 <b>Reply:</b> {content[:300]}\n"
                f"Couldn't confidently parse this as a command, and it looks like it "
                f"refers to the existing signal rather than a new one — no action taken."
            )
            await notification_sender.send_message(msg, category='reply_unclear')
        except Exception as e:
            logger.warning(f"Could not send reply-review notification: {str(e)}")
