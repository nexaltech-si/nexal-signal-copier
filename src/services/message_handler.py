"""
Enhanced Message Handler Service
Handles Telegram messages with intelligent deduplication, reply detection, and multi-TP support
"""
import re
import time
import asyncio
from collections import OrderedDict
from typing import Optional, Dict, List
from datetime import datetime, timezone
from loguru import logger
from src.utils.tasks import spawn
from src.utils.split_ids import real_message_id

from src.models import TradingSignal, SignalAction, OrderType, SignalStatus
from src.models.message import MessageIdentifier
from src.services.trade_mapper import trade_mapper
from src.services.signal_service import signal_service
from src.services.reply_handler_service import reply_handler_service
from ai.message_guards import bare_tp_level, offers_partial_profit
from src.services.spread_adjustment_service import spread_adjustment_service
from src.services.channel_behavior_service import channel_behavior_service
from src.services.trade_context_manager import trade_context_manager
from src.services.split_post import SplitPostTracker
from src.services.action_results import partial_failures, failure_block, log_partial_failure
from src.core.database_service import db_service
from src.integrations.trading.provider_factory import create_trading_provider

# Method groups split out of this class (see each module's docstring)
from src.services.message_handling.plain_commands import PlainCommandMixin
from src.services.message_handling.albums import AlbumMixin
from src.services.message_handling.reply_signals import ReplySignalMixin
from src.services.message_handling.new_signals import NewSignalMixin
from src.services.message_handling.trade_updates import TradeUpdateMixin
from src.services.message_handling.signal_edits import SignalEditMixin


class _BoundedSet:
    """Insertion-ordered set that evicts the oldest entries beyond `maxlen` (set-like: add / in / len)."""

    def __init__(self, maxlen: int):
        from collections import OrderedDict
        self._d = OrderedDict()
        self._max = maxlen

    def add(self, item):
        self._d[item] = None
        self._d.move_to_end(item)
        while len(self._d) > self._max:
            self._d.popitem(last=False)

    def __contains__(self, item):
        return item in self._d

    def __len__(self):
        return len(self._d)


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class MessageHandler(PlainCommandMixin, AlbumMixin, ReplySignalMixin, NewSignalMixin, TradeUpdateMixin, SignalEditMixin):
    """
    Smart message handler with:
    - Deduplication (prevents duplicate signal execution)
    - Reply detection (differentiates new signals from updates)
    - Performance report filtering
    - Multi-TP signal handling
    - Edit message support
    """
    
    def __init__(self):
        # Deduplication tracking
        self.recent_messages: Dict[str, datetime] = {}
        self.processed_message_ids = _BoundedSet(20000)  # was an unbounded set (slow memory leak)
        # Album (grouped media) buffering: one Telegram album arrives as N separate
        # events sharing grouped_id — collect them and process once, with all images
        self._album_buffers: Dict[tuple, dict] = {}
        self._album_settle_seconds = 2.0
        # chat_id -> (grouped_id, Event): an album is still being assembled/processed; later messages of the
        # same chat wait for it so they cannot overtake it (the album is flushed ~2 s after its first photo)
        self._album_open: Dict[str, tuple] = {}
        # Split posts: text, then its chart as separate caption-less photos (relay channels)
        self._split_posts = SplitPostTracker()
        self.dedup_window_seconds = 30
        # (chat, message) → (edit_date, (text, media id)) of the last edit seen; see _is_real_edit
        self._edit_seen: "OrderedDict[str, tuple]" = OrderedDict()
        self.bot_user_id = None  # Will be set during initialization
        self._trading_provider = None  # Lazy initialization
        
        # Per-channel conversational context for smarter AI routing
        # Format: {channel_id: {'last_signal': {...}, 'last_action': str, 'last_timestamp': datetime}}
        self._channel_context: Dict[str, dict] = {}
        
        logger.info("✅ Message handler initialized")
    
    @property
    def trading_provider(self):
        """Lazy initialization of trading provider"""
        if self._trading_provider is None:
            self._trading_provider = create_trading_provider()
        return self._trading_provider
    
    def set_bot_user_id(self, bot_user_id: int):
        """Set the bot's user ID to filter out its own messages"""
        self.bot_user_id = bot_user_id
        logger.info(f"🤖 Bot user ID set: {bot_user_id}")

    def _update_channel_context(self, channel_id: str, intent: str, 
                                  symbol: str = None, action: str = None):
        """Track per-channel conversational context for smarter AI routing."""
        ctx = self._channel_context.setdefault(str(channel_id), {})
        ctx['last_intent'] = intent
        ctx['last_timestamp'] = datetime.now()
        if symbol:
            ctx['last_symbol'] = symbol
        if action:
            ctx['last_action'] = action
        # Bound memory: keep only most recent 100 channels
        if len(self._channel_context) > 100:
            oldest = min(self._channel_context, 
                        key=lambda k: self._channel_context[k].get('last_timestamp', datetime.min))
            del self._channel_context[oldest]

    async def _download_message_image(self, event) -> Optional[bytes]:
        """Download the message's image (photo, image document, web preview), or None."""
        # Download image — handles direct messages, forwarded messages, and
        # image documents (Telegram sometimes sends photos as uncompressed documents)
        image_data = None
        if getattr(event.message, 'media', None):
            from telethon.tl.types import (
                MessageMediaPhoto, MessageMediaDocument, MessageMediaWebPage,
            )
            media = event.message.media
            media_type = type(media).__name__
            logger.debug(f"📎 Media type: {media_type}")
            try:
                if isinstance(media, MessageMediaPhoto):
                    image_data = await event.message.download_media(bytes)
                    logger.info(f"📸 Photo downloaded ({len(image_data)} bytes)")
                elif isinstance(media, MessageMediaDocument) and getattr(media, 'document', None):
                    mime = getattr(media.document, 'mime_type', '') or ''
                    if mime.startswith('image/'):
                        image_data = await event.message.download_media(bytes)
                        logger.info(f"📸 Image document downloaded ({len(image_data)} bytes)")
                    else:
                        logger.debug(f"📎 Document mime '{mime}' — not an image, skipping")
                elif isinstance(media, MessageMediaWebPage):
                    # Web preview may embed a photo
                    wp = getattr(media, 'webpage', None)
                    wp_photo = getattr(wp, 'photo', None) if wp else None
                    if wp_photo:
                        image_data = await event.message.download_media(bytes)
                        logger.info(f"📸 Webpage preview image downloaded ({len(image_data)} bytes)")
                else:
                    logger.debug(f"📎 Unhandled media type {media_type} — skipping image download")
            except Exception as _img_err:
                logger.warning(f"⚠️ Failed to download image (type={media_type}): {_img_err}")

        # Fallback: try event.message.photo shortcut (works for forwarded photos
        # from channels where media object may differ)
        if image_data is None and getattr(event.message, 'photo', None):
            try:
                image_data = await event.message.download_media(bytes)
                logger.info(f"📸 Photo downloaded via .photo shortcut ({len(image_data)} bytes)")
            except Exception as _img_err2:
                logger.warning(f"⚠️ Fallback photo download failed: {_img_err2}")
        return image_data

    async def process_message(
        self,
        event,
        signal_callback
    ) -> bool:
        """
        Process a Telegram message with smart filtering
        
        Args:
            event: Telethon message event
            signal_callback: Async callback to execute when signal is found
            
        Returns:
            True if message was processed, False if filtered out
        """
        text_post = None
        try:
            # Create message identifier
            message_id = MessageIdentifier.from_telegram_event(event)
            content = event.message.text or ""

            image_data = await self._download_message_image(event)

            logger.info(f"📩 Processing message {message_id.message_id} from chat {message_id.chat_id}")
            logger.debug(f"   Content: {content[:100]}...")
            
            # 0. Filter out messages from the bot itself
            sender_id = getattr(event.message, 'sender_id', None) or getattr(event.message, 'from_id', None)
            if sender_id:
                # Handle PeerUser object
                if hasattr(sender_id, 'user_id'):
                    sender_id = sender_id.user_id
                
                if self.bot_user_id and sender_id == self.bot_user_id:
                    logger.debug(f"🤖 Ignoring message from bot itself (sender_id: {sender_id})")
                    return False
            
            # 1. Check for duplicate message ID (prevents duplicate execution)
            message_key = message_id.get_key()
            if message_key in self.processed_message_ids:
                logger.warning("⚠️ Message already processed - ignoring duplicate")
                return False
            
            # Mark as processed
            self.processed_message_ids.add(message_key)

            # Do not overtake an album that is still being assembled / processed in this chat
            await self._wait_for_open_album(message_id.chat_id, getattr(event.message, 'grouped_id', None))

            # 1b. Split post: a bare chart right after a text post by the same sender
            # belongs to that post — never a separate signal (see split_post.py)
            msg_sender = getattr(event.message, 'sender_id', None)
            msg_date = getattr(event.message, 'date', None)
            is_reply_msg = self._is_reply(event)
            if SplitPostTracker.is_companion_candidate(content, bool(image_data), getattr(event.message, 'grouped_id', None), is_reply_msg):
                post = self._split_posts.companion_for(message_id.chat_id, msg_sender, msg_date)
                if post:
                    return await self._handle_split_post_image(event, message_id, image_data, signal_callback, post)
            elif content.strip() and not image_data and not is_reply_msg:
                text_post = self._split_posts.start_text(message_id.chat_id, msg_sender, message_id.message_id, content, msg_date)

            # 2a. Album (grouped media): buffer items and process once fully assembled.
            # Without this, each photo of a multi-image post is processed as a
            # separate image-only signal and the caption only reaches one of them.
            grouped_id = getattr(event.message, 'grouped_id', None)
            if grouped_id and image_data:
                return await self._buffer_album_item(
                    event, message_id, content, image_data, grouped_id, signal_callback
                )

            # 2. Check for duplicate content (deduplication window)
            logger.debug("Step 2: Checking for duplicate content...")
            if not self._is_reply(event):
                if self._is_duplicate_content(message_id, content):
                    return False
            else:
                logger.debug("Skipping duplicate check for reply message")
            
            # 3. Route message based on intent — AI-driven with keyword fallback
            is_direct_reply = self._is_reply(event)
            
            if is_direct_reply:
                # Direct Telegram replies are structural — always trade interactions
                logger.info("🔄 Direct reply detected — routing as trade update")
                await self._handle_trade_update(
                    event, message_id, content,
                    signal_callback=signal_callback, image_data=image_data,
                )
                return True
            
            # ── Plain-text command keywords: ROUTING only ──────────────
            # They used to execute directly (zero AI) and got it wrong: "Close half"
            # became a full close, "Close bottom hold upper" closed both legs. Now
            # they only mark the message as a command; the reply AI decides the
            # action with live account state (see _handle_standalone_management).
            plain_cmd = len(content.strip()) >= 5 and self._is_plain_command(content)
            if plain_cmd and not (reply_handler_service.ai_processor and reply_handler_service.ai_processor.ai_available()):
                parsed = self._parse_plain_command(content)
                if parsed:
                    logger.warning(f"⚡ No AI reachable — plain command parsed by keywords: {parsed.get('action')}")
                    self._update_channel_context(message_id.chat_id, 'COMMAND')
                    await self._handle_plain_command(
                        parsed=parsed,
                        channel_id=str(message_id.chat_id),
                        content=content,
                        message_id=message_id,
                        signal_callback=signal_callback,
                        image_data=image_data,
                    )
                    return True

            # ── Shorthand follow-ups ("B.E", "BE", "TP1", "SL") ──────────
            # Too short for the intent classifier below and far too short to be a new
            # signal: they used to default to SIGNAL and be dropped as "no text". With a
            # live trade in this channel they are that trade's management — the reply
            # AI decides with live state, exactly as for a reply.
            if (not plain_cmd and not image_data and 0 < len(content.strip()) < 10
                    and await self._latest_active_signal(str(message_id.chat_id), content)):
                logger.info(f"🔄 Short follow-up {content.strip()!r} — managing the channel's latest active signal")
                self._update_channel_context(message_id.chat_id, 'COMMAND')
                await self._handle_standalone_management(event, message_id, content, image_data)
                return True

            # ── "Tp1 : 3858" — a take-profit level and nothing else ─────
            # With a trade of this channel running it moves that trade's target. The
            # intent classifier is not asked: it could read it as a status or a signal.
            # The same for "Can booked some": half off the running trade.
            if (not plain_cmd and not image_data and (bare_tp_level(content) or offers_partial_profit(content))
                    and await self._latest_active_signal(str(message_id.chat_id), content)):
                logger.info(f"🔄 {content.strip()!r} — managing the channel's latest active signal")
                self._update_channel_context(message_id.chat_id, 'COMMAND')
                await self._handle_standalone_management(event, message_id, content, image_data)
                return True

            # ── AI Intent Classification (replaces keyword-based routing) ──
            intent = 'COMMAND' if plain_cmd else 'SIGNAL'  # default: new signal (fail-open)
            if len(content.strip()) >= 10 and not plain_cmd:
                try:
                    t_intent = time.monotonic()
                    intent = await signal_service.classify_intent(content)
                    elapsed = int((time.monotonic() - t_intent) * 1000)
                    logger.info(f"🤖 AI intent: {intent} ({elapsed}ms)")
                except Exception as e:
                    logger.warning(f"⚠️ AI intent classification failed ({e}) — falling back to keyword routing")
                    # Make it visible: previously only a log line, so an AI outage during routing was silent
                    from src.utils.audit import audit
                    audit("WARNING", f"AI intent classification failed in chat {message_id.chat_id}: {str(e)[:150]}",
                          "MEDIUM", module="message_handler")
                    spawn(signal_service._notify_extraction_failure(
                        message_text=content, channel_id=str(message_id.chat_id), channel_name=None,
                        message_id=message_id.message_id,
                        reason=f"AI intent classification failed ({str(e)[:120]}) - routed by keywords",
                        has_image=bool(image_data),
                    ), name="intent_failure_notify")
                    # Fall back to old keyword-based routing
                    if self._is_reply_or_update(event, content):
                        intent = 'COMMAND'
            
            if intent == 'COMMAND':
                logger.info("🔄 COMMAND (not a reply) — managing the channel's latest active signal")
                self._update_channel_context(message_id.chat_id, 'COMMAND')
                if await self._handle_standalone_management(event, message_id, content, image_data) is None:
                    # No active signal in this channel to manage — legacy content-based path
                    await self._handle_trade_update(
                        event, message_id, content,
                        signal_callback=signal_callback, image_data=image_data,
                    )
                return True

            if intent == 'STATUS' and await self._latest_active_signal(str(message_id.chat_id), content):
                # A standalone progress update ("120 pip", "Near TP") while a trade from
                # this channel is active: same handling as a reply — the AI decides with
                # live state (e.g. cancels pending orders the provider's move left behind).
                self._update_channel_context(message_id.chat_id, 'STATUS')
                await self._handle_standalone_management(event, message_id, content, image_data)
                return True

            if intent == 'STATUS':
                # A status caption's image is almost always a results/progress
                # screenshot of the trade being reported — the chart still shows the
                # original entry/SL/TP, so running vision on it re-opens that trade.
                logger.info(
                    f"💬 AI classified as STATUS update — ignoring"
                    f"{' (attached image not treated as a new setup)' if image_data else ''}"
                )
                self._update_channel_context(message_id.chat_id, 'STATUS')
                return False
            
            if intent == 'NOT_TRADING':
                self._update_channel_context(message_id.chat_id, 'NOT_TRADING')
                if image_data:
                    # Caption is non-trading commentary but a chart image is attached —
                    # the actual setup may be visual (e.g. annotated zones with "waiting
                    # confirmation" caption). Let the integrated processor's vision path
                    # decide; it already handles NOT_TRADING+image by skipping to vision.
                    logger.info("📸 NOT_TRADING text but image present — trying vision extraction")
                    return await self._handle_new_signal(
                        event, message_id, content, signal_callback, image_data=image_data
                    )
                logger.info("🚫 AI classified as NOT_TRADING — skipping (no image)")
                return False
            
            # intent == 'SIGNAL' — process as new signal
            logger.info("🆕 AI classified as SIGNAL — processing as new signal")
            self._update_channel_context(message_id.chat_id, 'SIGNAL')
            return await self._handle_new_signal(event, message_id, content, signal_callback, image_data=image_data)
            
        except Exception as e:
            logger.error(f"❌ Error processing message: {str(e)}")
            logger.exception(e)
            return False
        finally:
            if text_post is not None:
                SplitPostTracker.finish(text_post)

    async def _latest_active_signal(self, chat_id: str, content: str = ""):
        """Most recent still-active OPEN signal in this chat — preferring one whose symbol the text names."""
        try:
            where = {"channelId": chat_id, "action": "OPEN",
                     "status": {"in": db_service.ACTIVE_SIGNAL_STATUSES}}
            named = trade_context_manager._extract_symbol_from_message(content) if content else None
            if named:
                sig = await db_service.db.signal.find_first(where={**where, "symbol": named}, order={"createdAt": "desc"})
                if sig:
                    return sig
            return await db_service.db.signal.find_first(where=where, order={"createdAt": "desc"})
        except Exception as e:
            logger.debug(f"Could not look up active signal for {chat_id}: {e}")
            return None

    async def _handle_standalone_management(self, event, message_id: MessageIdentifier, content: str,
                                            image_data: Optional[bytes] = None):
        """
        A trade-management message that is NOT a Telegram reply ("Close bottom hold
        upper", "BUY not valid any more!", "Set B.E save profits"). Providers often post
        these standalone; they are handled exactly like a reply to the channel's latest
        active signal — reply AI + live account state + channel rules.
        Returns the handler result, or None when there is no active signal to manage.
        """
        chat_id = str(message_id.chat_id)
        target = await self._latest_active_signal(chat_id, content)
        if not target:
            return None
        matched_rule = await channel_behavior_service.match_rule(chat_id, content)
        if matched_rule and matched_rule['actionType'] == 'IGNORE':
            logger.info(f"🔇 Ignoring standalone message due to channel rule: {matched_rule['ruleName']}")
            await channel_behavior_service.record_success(matched_rule['id'])
            return {"success": True, "ignored": True, "reason": "channel_rule_ignore"}
        logger.info(f"🎯 Standalone message → managing signal #{target.messageId} ({target.symbol}, {target.status})")
        # The channel's other running signals on that instrument and side: a close that
        # picks entries ("close your bad entry, hold the good one") chooses among theirs too.
        try:
            same_side = await db_service.db.signal.find_many(
                where={"channelId": chat_id, "action": "OPEN", "id": {"not": target.id},
                       "symbol": target.symbol, "orderType": target.orderType,
                       "status": {"in": db_service.ACTIVE_SIGNAL_STATUSES}},
                order={"createdAt": "desc"})
        except Exception as e:
            logger.warning(f"⚠️ Could not look up the channel's other running {target.symbol} signals: {e}")
            same_side = []
        result = await reply_handler_service.handle_reply(
            reply_to_message_id=real_message_id(target.messageId),
            chat_id=chat_id,
            command=content,
            reply_message_id=message_id.message_id,
            command_timestamp=getattr(event.message, 'date', None),
            channel_name=getattr(target, 'channelName', None),
            image_data=image_data,
            channel_rule=matched_rule,
            related_message_ids=[real_message_id(s.messageId) for s in same_side],
        )
        # "Close ALL gold trades": every running setup of this channel on that
        # instrument, not only the latest one. A plain post has no reply target, so
        # the handler above managed the most recent signal — with a SELL and a BUY
        # both running, the older one stayed open (scripted history, 2026-11-13).
        if (result.get('success') and not result.get('ignored')
                and self._is_global_close(content) and self._is_explicit_close_command(content)):
            named = trade_context_manager._extract_symbol_from_message(content)
            where = {"channelId": chat_id, "action": "OPEN", "id": {"not": target.id},
                     "status": {"in": db_service.ACTIVE_SIGNAL_STATUSES}}
            if named:
                where["symbol"] = named
            try:
                others = await db_service.db.signal.find_many(where=where, order={"createdAt": "desc"})
            except Exception as e:
                logger.warning(f"⚠️ Could not look up the channel's other running signals for a close-all: {e}")
                others = []
            for other in others:
                logger.info(f"🎯 Close-all → also managing signal #{other.messageId} ({other.symbol}, {other.status})")
                extra = await reply_handler_service.handle_reply(
                    reply_to_message_id=real_message_id(other.messageId), chat_id=chat_id, command=content,
                    reply_message_id=message_id.message_id,
                    command_timestamp=getattr(event.message, 'date', None),
                    channel_name=getattr(other, 'channelName', None), channel_rule=matched_rule,
                )
                if extra.get('success') and not extra.get('ignored'):
                    result['message'] = f"{result.get('message', '')} + #{other.messageId}: {extra.get('message', '')}"

        failures = partial_failures(result)
        if result.get('ignored'):
            logger.info("💬 Standalone message: AI decided no action")
        elif failures:
            log_partial_failure(failures, f"Standalone message on {target.symbol}")
            try:
                from src.integrations.telegram.unified_sender import notification_sender
                await notification_sender.send_message(
                    f"⚠️ <b>Command Partly Executed</b>\n\n📊 <b>Symbol:</b> {target.symbol}\n"
                    f"{result.get('message', '')}{failure_block(failures)}",
                    category='command_response')
            except Exception as e:
                logger.warning(f"Could not send partial-failure notification: {e}")
        elif result.get('success'):
            logger.success(f"✅ Standalone message executed: {result.get('message')}")
        else:
            logger.warning(f"⚠️ Standalone message not executed: {result.get('error')}")
        return result

    async def _handle_split_post_image(self, event, message_id: MessageIdentifier, image_data: bytes,
                                       signal_callback, post) -> bool:
        """A caption-less chart that belongs to the text post just before it."""
        try:
            # The text's AI extraction takes a few seconds — wait for its outcome
            await asyncio.wait_for(post.done.wait(), timeout=90)
        except asyncio.TimeoutError:
            logger.warning(f"🖇️ Split post: text #{post.message_id} still processing after 90s — using what is known")
        if post.extracted:
            try:
                sig = await db_service.db.signal.find_first(
                    where={"channelId": str(message_id.chat_id), "messageId": post.message_id}
                )
                if sig:
                    await db_service.merge_signal_supplementary_info(sig.id, image_data=image_data)
            except Exception as e:
                logger.debug(f"Split post: could not attach chart to signal: {e}")
            logger.info(f"🖇️ Split post: chart #{message_id.message_id} attached to signal from text #{post.message_id}")
            return True
        if post.needs_image and not post.fused:
            post.fused = True  # only the first chart re-runs extraction
            logger.info(f"🖇️ Split post: text #{post.message_id} lacked levels — extracting text + chart #{message_id.message_id} together")
            return await self._handle_new_signal(event, message_id, post.text, signal_callback, image_data=image_data)
        logger.info(f"🖇️ Split post: chart #{message_id.message_id} belongs to non-signal text #{post.message_id} — ignored")
        return False

    async def process_edited_message(
        self,
        event,
        signal_callback
    ) -> bool:
        """
        Process edited Telegram message
        Detects changes in SL/TP and updates existing orders
        """
        try:
            message_id = MessageIdentifier.from_telegram_event(event)
            content = event.message.text or ""

            # The signal this message belongs to (follows continuation links, so an
            # edit of a follow-up / repost reaches the original setup)
            from src.services.signal_continuity import signal_continuity
            existing_signal, _magic = await signal_continuity.resolve_group(message_id.chat_id, message_id.message_id)

            if not self._is_real_edit(event, message_id, content, existing_signal):
                return False

            image_data = await self._download_message_image(event)
            logger.info(f"✏️ Processing edited message {message_id.message_id}")

            if existing_signal:
                logger.info(f"📝 Found existing signal for edited message: {existing_signal.symbol}")
                
                # Extract the NEW signal from edited message
                message_date = getattr(event.message, 'date', None)
                new_signal = await signal_service.extract_signal(
                    message_text=content,
                    channel_id=str(message_id.chat_id),
                    message_id=message_id.message_id,
                    image_data=image_data,
                    message_date=message_date
                )
                
                # The channel replaced the signal's text with a cancellation ("❌ CANCELLED —
                # setup no longer valid, do not enter"). That is its word on this trade:
                # handled like a reply to the signal — pending orders are cancelled, and
                # the reply AI decides about anything already filled. Before, such an
                # edit left the pending orders waiting (scripted history, 2026-11-13).
                still_open_signal = bool(new_signal and new_signal.action == SignalAction.OPEN
                                         and (new_signal.stop_loss or new_signal.entry_price))
                if (self._reads_as_cancellation(content) and not still_open_signal
                        and existing_signal.status in db_service.ACTIVE_SIGNAL_STATUSES):
                    logger.info(f"🛑 Edited into a cancellation — managing signal #{existing_signal.messageId}")
                    result = await reply_handler_service.handle_reply(
                        reply_to_message_id=real_message_id(existing_signal.messageId),
                        chat_id=str(message_id.chat_id), command=content,
                        reply_message_id=message_id.message_id,
                        command_timestamp=getattr(event.message, 'date', None),
                        channel_name=getattr(existing_signal, 'channelName', None),
                    )
                    if not (result.get('success') and not result.get('ignored')):
                        # the reply AI did not act: at least nothing new may fill
                        from src.services.signal_continuity import signal_continuity as _sc
                        await _sc.on_messages_deleted(str(message_id.chat_id), [int(existing_signal.messageId)])
                    return True

                if new_signal:
                    if (new_signal.action == SignalAction.OPEN
                            and not self._is_explicit_close_command(content)):
                        # Same update path as a follow-up / repost: SL/TP moved, removed
                        # levels cancelled, missing levels placed within the remaining risk
                        await signal_continuity.apply_update(existing_signal, new_signal, message_id, source="edit")
                    else:
                        await self._handle_signal_edit(existing_signal, new_signal, message_id)
                    return True
                else:
                    logger.warning("Could not extract signal from edited message")
                    return False
            else:
                logger.info("No existing signal - processing edited message as new signal")
                # Check for duplicates before processing
                message_key = message_id.get_key()
                if message_key in self.processed_message_ids:
                    logger.warning("Edited message already processed - ignoring")
                    return False
                
                self.processed_message_ids.add(message_key)
                return await self._handle_new_signal(event, message_id, content, signal_callback, image_data=image_data)
                
        except Exception as e:
            logger.error(f"❌ Error processing edited message: {str(e)}")
            logger.exception(e)
            return False
    
    _CANCEL_RE = re.compile(
        r"\b(?:cancel(?:led|ed|s)?|invalid(?:ated)?|void(?:ed)?|scrap(?:ped)?|"
        r"do\s*n[o']?t\s+(?:enter|take)|no\s+longer\s+valid|not\s+valid(?:\s+any\s*more)?|"
        r"ignore\s+(?:this|the)\s+(?:signal|setup|trade)|delete(?:d)?\s+(?:this|the)\s+(?:signal|setup))\b",
        re.IGNORECASE)

    @classmethod
    def _reads_as_cancellation(cls, text: str) -> bool:
        """The channel is calling a setup off (not a level change, not a status update)."""
        return bool(cls._CANCEL_RE.search(text or ""))

    def _is_real_edit(self, event, message_id: MessageIdentifier, content: str, existing_signal) -> bool:
        """
        Telegram delivers reaction, view-count and reply-count changes on channel posts
        as message-edit updates, so MessageEdited fires many times for a post nobody
        edited. Only a changed text is an edit: re-extracting and re-applying an
        unchanged signal re-sizes, re-places and re-modifies a setup that is running.
        """
        edit_date = getattr(event.message, 'edit_date', None)
        if not edit_date:
            logger.debug(f"✏️ Message {message_id.message_id}: update without edit_date (reactions/views) — ignored")
            return False
        key = message_id.get_key()
        text = content.strip()
        media = getattr(event.message, 'media', None)
        media_id = getattr(getattr(media, 'photo', None) or getattr(media, 'document', None), 'id', None)
        seen = self._edit_seen.get(key)
        if seen is not None:
            if seen[0] == edit_date or seen[1] == (text, media_id):
                logger.info(f"✏️ Message {message_id.message_id}: content unchanged since the last edit — ignored")
                return False
        elif existing_signal is not None:
            # After a restart: an edit older than the signal was already in the text we
            # processed; otherwise compare with the texts the signal was built from
            created = getattr(existing_signal, 'createdAt', None)
            if created is not None and _as_utc(edit_date) <= _as_utc(created):
                self._remember_edit(key, edit_date, (text, media_id))
                return False
            raw = getattr(existing_signal, "rawMessage", None) or ""
            parts = [raw.split("\n--- ")[0]] + [p.split("---\n", 1)[-1] for p in raw.split("\n--- ")[1:]]
            if text and text in {p.strip() for p in parts}:
                logger.info(f"✏️ Message {message_id.message_id}: text matches the running signal — ignored")
                self._remember_edit(key, edit_date, (text, media_id))
                return False
        self._remember_edit(key, edit_date, (text, media_id))
        return True

    def _remember_edit(self, key: str, edit_date, fingerprint: tuple) -> None:
        self._edit_seen[key] = (edit_date, fingerprint)
        self._edit_seen.move_to_end(key)
        while len(self._edit_seen) > 5000:
            self._edit_seen.popitem(last=False)

    def _is_duplicate_content(self, message_id: MessageIdentifier, content: str) -> bool:
        """Check if message content was recently processed"""
        message_hash = f"{message_id.chat_id}:{hash(content)}"
        current_time = datetime.now()
        
        # Clean up old entries
        self.recent_messages = {
            k: v for k, v in self.recent_messages.items()
            if (current_time - v).total_seconds() < self.dedup_window_seconds
        }
        
        # Check for duplicate
        if message_hash in self.recent_messages:
            time_since = (current_time - self.recent_messages[message_hash]).total_seconds()
            logger.warning(f"⚠️ Duplicate content detected ({time_since:.1f}s ago) - ignoring")
            return True
        
        # Mark as seen
        self.recent_messages[message_hash] = current_time
        return False
    
    def _is_reply(self, event) -> bool:
        """Check if message is a reply to another message"""
        has_reply_to = hasattr(event.message, 'reply_to')
        is_reply = has_reply_to and event.message.reply_to is not None
        
        if is_reply:
            reply_to_msg_id = event.message.reply_to.reply_to_msg_id if hasattr(event.message.reply_to, 'reply_to_msg_id') else None
            logger.info(f"🔗 REPLY DETECTED: Message is replying to message ID {reply_to_msg_id}")
        else:
            logger.debug(f"Not a reply - has_reply_to: {has_reply_to}, reply_to: {getattr(event.message, 'reply_to', None)}")
        
        return is_reply
    
    def _is_reply_or_update(self, event, content: str) -> bool:
        """Check if message is a reply or trade update"""
        # Direct reply check
        if self._is_reply(event):
            logger.info("✅ Message identified as REPLY - will handle as trade update")
            return True
        
        # Content-based update detection
        content_lower = content.lower()
        update_keywords = [
            'close', 'closed', 'closing', 'tp hit', 'sl hit', 'modify', 'update', 'partial',
            'take profit', 'stop loss', 'exit', 'exited', 'exiting', 'secure', 'lock',
            'move sl', 'breakeven', 'trailing', 'manual close', 'manually closed'
        ]

        def _keyword_matches(keyword: str, text: str) -> bool:
            if ' ' in keyword:
                return keyword in text
            return bool(re.search(r'\b' + re.escape(keyword) + r'\b', text))

        matched_keyword = next((k for k in update_keywords if _keyword_matches(k, content_lower)), None)

        if matched_keyword:
            # Suppress false positives where "close" appears in candle/price context
            # e.g. "if 4 M15 candles close below 4420" or "price closes above resistance"
            if matched_keyword in ('close', 'closed', 'closing'):
                candle_close_patterns = [
                    r'candles?\s+close[sd]?\b',     # "candle closes", "candles close"
                    r'\bclose[sd]?\s+(below|above|under|over)\b',  # "closes below 4420"
                    r'\bm\d+\s+close\b',             # "M15 close", "H4 close"
                    r'\bprice\s+close[sd]?\b',        # "price closes"
                    # "if/when/once price closes 4420" — conditional candle talk only.
                    # NOT bare "close 4020", which is an imperative leg-scoped close.
                    r'\b(?:if|when|once|after)\b[^.]*\bclose[sd]\s+\d+',
                ]
                is_candle_context = any(re.search(p, content_lower) for p in candle_close_patterns)

                # Also suppress if the message has clear new-trade entry markers
                entry_markers = [
                    r'\bentry\s+zone\b', r'\bentry\b.*\d{3,}', r'\bbuy\s+zone\b',
                    r'\bsell\s+zone\b', r'\bstop\s+loss\b.*\d{3,}', r'\btake\s+profit\b.*\d{3,}',
                    r'\bre-?entry\b', r'\bfallback\b',
                ]
                has_entry_markers = sum(1 for p in entry_markers if re.search(p, content_lower)) >= 2

                if is_candle_context or has_entry_markers:
                    logger.debug(f"Suppressing '{matched_keyword}' keyword — candle/entry context detected")
                    return False

            logger.debug(f"Message contains update keyword: '{matched_keyword}'")
            return True

        return False

    # ── Plain-Text Command Detection (Layer 0 + Layer 1, ZERO AI) ──────────

    _COMMAND_KEYWORDS_RE = re.compile(
        r'\b(?:close|closing|modify|update|partial|exit|exited|secure|lock|'
        r'move\s+sl|move\s+tp|breakeven|break\s+even|trailing|'
        r'set\s+(?:be|sl|tp|breakeven)|cancel|reduce|add\s+to)\b',
        re.IGNORECASE,
    )

    _AMBIGUOUS_CLOSE_RE = re.compile(
        r'\b(?:half|halve|halves|quarter|third|part|partial|partially|some|except|but|keep|leave|hold|only|'
        r'bottom|top|upper|lower|first|last|one\s+of|rest|remaining)\b'
    )

    _PARSE_PATTERNS = [
        # "close gold", "close EURUSD", "close all", "close it"
        (r'\bclose\s+(?:all|everything|both|full|global)\b', 'close_all', None),
        # Leg-scoped close: "close 4020", "close the 4020 entry", "close 4020 hold 4030".
        # MUST precede the greedy "close <word>" pattern below, which would otherwise
        # swallow "4020 hold 4030 play safe" into a single unusable capture group.
        (r'\bclose\s+(?:the\s+)?(\d+(?:\.\d+)?)\b(?!\s*%)', 'close_by_entry', 1),
        (r'\bclose\s+(?:the\s+)?(\w+(?:\s*\w+)*?)(?:\s+(?:trade|position))?\s*$', 'close', 1),
        (r'^close\s*$', 'close', None),
        # "set BE", "set breakeven", "move to BE", "move to breakeven"
        (r'\b(?:set|move)\s+(?:to\s+)?(?:be|breakeven|break\s+even)\b', 'breakeven', None),
        # "set SL to 1.2000", "move SL to 1.2000", "modify sl 1.2000", "sl to 1.2000"
        (r'\b(?:set|move|modify|put)\s+(?:the\s+)?(?:sl|stop\s*(?:loss)?)\s+(?:to\s+)?([\d.]+)', 'modify_sl', 1),
        (r'\b(?:set|move|modify|put)\s+(?:the\s+)?(?:tp|take\s*profit|target)\s+(?:to\s+)?([\d.]+)', 'modify_tp', 1),
        # "take 50%", "partial 50", "close 50%", "take 50% of gold"
        (r'\b(?:take|partial|close)\s+(\d+)\s*%', 'partial_close', 1),
        # "lock profit", "lock 20 pips"
        (r'\block\s+(?:in\s+)?(?:profit|gains)\b', 'lock_profit', None),
        (r'\block\s+(\d+)\s*(?:pips?)?\b', 'lock_profit', 1),
        # "cancel orders", "cancel all orders"
        (r'\bcancel\s+(?:all\s+)?(?:pending\s+)?orders?\b', 'cancel_orders', None),
    ]

    # ── Plain-Text Command Handler ─────────────────────────────────────────

    _REENTER_RE = re.compile(
        r'\b(re-?enter(?:ed|ing)?|re-?entry|enter again|back in|going back in)\b',
        re.IGNORECASE,
    )

    async def process_deleted_messages(self, event) -> None:
        """Channel deleted message(s): pending orders of a deleted signal are cancelled."""
        try:
            chat_id = getattr(event, 'chat_id', None)
            ids = list(getattr(event, 'deleted_ids', None) or [])
            if not ids:
                return
            if chat_id is None:
                logger.debug(f"🗑️ Deleted messages {ids} without chat id (non-channel) — ignored")
                return
            from src.services.signal_continuity import signal_continuity
            await signal_continuity.on_messages_deleted(str(chat_id), ids)
        except Exception as e:
            logger.error(f"❌ Error processing deleted messages: {e}")


# Singleton instance
message_handler = MessageHandler()
