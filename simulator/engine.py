"""
TradingSimulator Engine — replays historical Telegram messages through the full
live-system pipeline, processing messages oldest-first so that position tracking,
reply context, and command resolution all match live-bot behaviour.

Message routing order (mirrors MessageHandler.process_message exactly):
  1. Download image bytes
  2. Direct reply → _handle_reply  (same as live _handle_trade_update)
  3. Plain-text command (Layer 0+1, zero AI) → record command
  4. Cheap pre-filter
  5. AI intent classification
  6. NOT_TRADING  → skip (even with image)
  7. STATUS + no image → skip
  8. COMMAND → command processor
  9. SIGNAL / STATUS+image → full AI/pattern/vision extraction
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

from telethon import TelegramClient
from telethon.tl.types import (
    Message,
    MessageMediaPhoto,
    MessageMediaDocument,
    MessageMediaWebPage,
)

from src.models.signal import TradingSignal
from src.models.enums import SignalAction

from simulator.models import SimulatedTrade, SimulationResults

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, SimulatedTrade], Awaitable[None]]

VISION_RATE_LIMIT_PER_SEC = 20


class _AsyncRateLimiter:
    """Throttles calls to at most `rate` per second (sliding 1s window).

    Some vision providers reject bursts above ~20 req/s; the simulator can
    replay hundreds of image messages much faster than live traffic ever
    would, so calls are paced here rather than in production code.
    """

    def __init__(self, rate: int):
        self.rate = rate
        self._timestamps: List[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            self._timestamps = [t for t in self._timestamps if now - t < 1.0]
            if len(self._timestamps) >= self.rate:
                wait = 1.0 - (now - self._timestamps[0])
                if wait > 0:
                    await asyncio.sleep(wait)
                now = time.monotonic()
                self._timestamps = [t for t in self._timestamps if now - t < 1.0]
            self._timestamps.append(now)


# ══════════════════════════════════════════════════════════════════════════════
# SYMBOL HELPERS
# ══════════════════════════════════════════════════════════════════════════════

_SYMBOL_MAP: Dict[str, str] = {
    "GOLD": "XAUUSD", "XAU": "XAUUSD",
    "SILVER": "XAGUSD", "XAG": "XAGUSD",
    "EUR": "EURUSD", "EUR/USD": "EURUSD",
    "GBP": "GBPUSD", "GBP/USD": "GBPUSD", "CABLE": "GBPUSD",
    "GJ": "GBPJPY", "GBPJPY": "GBPJPY",
    "USDJPY": "USDJPY", "USD/JPY": "USDJPY", "JPY": "USDJPY",
    "AUD": "AUDUSD", "AUD/USD": "AUDUSD",
    "NZD": "NZDUSD", "NZD/USD": "NZDUSD",
    "USDCAD": "USDCAD", "USD/CAD": "USDCAD",
    "USDCHF": "USDCHF", "USD/CHF": "USDCHF",
    "BTC": "BTCUSD", "BITCOIN": "BTCUSD",
    "ETH": "ETHUSD", "ETHEREUM": "ETHUSD",
    "US30": "US30", "DOW": "US30",
    "NAS100": "NAS100", "NASDAQ": "NAS100",
    "US500": "US500", "SPX": "US500", "SP500": "US500",
    "GER30": "GER30", "DAX": "GER30",
    "OIL": "USOIL", "CRUDE": "USOIL", "WTI": "USOIL",
    "BRENT": "UKOIL",
}

_SORTED_SYMBOL_KEYS = sorted(_SYMBOL_MAP.keys(), key=len, reverse=True)


def _normalize_symbol(symbol: str) -> str:
    if not symbol:
        return symbol
    s = symbol.upper().strip()
    s = re.sub(r"[\.\s]*\b(PRO|CASH|ECN|PLUS|MICRO|MINI|STD)\b", "", s)
    s = s.rstrip("+").lstrip("#@")
    return _SYMBOL_MAP.get(s, s)


def _extract_symbol_from_text(text: str) -> Optional[str]:
    upper = text.upper()
    for key in _SORTED_SYMBOL_KEYS:
        if re.search(r'\b' + re.escape(key) + r'\b', upper):
            return _SYMBOL_MAP[key]
    return None


# ══════════════════════════════════════════════════════════════════════════════
# IMAGE DETECTION (mirrors live message_handler image logic)
# ══════════════════════════════════════════════════════════════════════════════

def _detect_image(msg: Message) -> bool:
    """True if the message carries a photo or image document."""
    if getattr(msg, 'photo', None):
        return True
    media = getattr(msg, 'media', None)
    if media is None:
        return False
    if isinstance(media, MessageMediaPhoto):
        return True
    if isinstance(media, MessageMediaDocument):
        mime = getattr(getattr(media, 'document', None), 'mime_type', '') or ''
        return mime.startswith('image/')
    if isinstance(media, MessageMediaWebPage):
        wp = getattr(media, 'webpage', None)
        return bool(getattr(wp, 'photo', None) if wp else None)
    return False


# ══════════════════════════════════════════════════════════════════════════════
# PRE-FILTER + PLAIN-TEXT COMMANDS — delegate to the LIVE implementations.
# These used to be hand-maintained copies and drifted (the copy dropped image
# posts with keyword-less captions that live sends to vision, and lacked live's
# leg-scoped "close 4020" patterns).
# ══════════════════════════════════════════════════════════════════════════════

def _is_potential_signal(text: str, has_image: bool = False) -> bool:
    from src.services.signal_service import signal_service
    return signal_service.is_potential_signal(text, has_image=has_image)


def _live_message_handler():
    # Only class-level patterns are used by these two methods — no __init__ needed.
    from src.services.message_handler import MessageHandler
    return MessageHandler.__new__(MessageHandler)


def _is_plain_command(text: str) -> bool:
    return _live_message_handler()._is_plain_command(text)


def _parse_plain_command(text: str) -> Optional[Dict]:
    return _live_message_handler()._parse_plain_command(text)


# ══════════════════════════════════════════════════════════════════════════════
# ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class TradingSimulator:
    """
    Replays historical Telegram messages through the complete live pipeline.

    Messages are always processed **oldest-first** so that:
    - Position tracking is correct (open before close)
    - Reply context points to already-processed signals
    - Plain-text commands resolve against the right open position

    Shared-client mode: pass `telegram_client` to reuse the already-authenticated
    TelethonListener client.  Without it the engine authenticates its own session.
    """

    def __init__(
        self,
        *,
        telegram_client: Optional[TelegramClient] = None,
        message_fetcher=None,
        api_id: Optional[int] = None,
        api_hash: Optional[str] = None,
        phone: Optional[str] = None,
        session_name: str = "simulator",
        enable_brain: bool = False,
        results_dir: str = "simulator/results",
    ):
        # message_fetcher(channel_id, start, end, limit) -> messages oldest first, in the
        # Telegram message shape: another source (Discord) instead of a Telegram client.
        self._message_fetcher = message_fetcher
        self._shared_client = telegram_client is not None or message_fetcher is not None
        self.client: Optional[TelegramClient] = telegram_client

        self._api_id = api_id
        self._api_hash = api_hash
        self._phone = phone
        self._session_name = session_name

        self.enable_brain = enable_brain
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)

        # Pipeline components (lazy-initialized by initialize())
        self.processor = None
        self.context_manager = None
        self.command_processor = None
        self.brain = None

        # Simulated open-position tracker for context resolution
        self._positions: List[Dict] = []

        # Candle-driven account book for replaying replies through the live
        # ReplyHandlerService (see simulator/reply_replay.py)
        self.reply_book = None
        self._candle_provider = None

        self._cancelled = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def initialize(self, config) -> None:
        if not self._shared_client:
            if not (self._api_id and self._api_hash and self._phone):
                raise ValueError(
                    "api_id, api_hash, and phone are required when not sharing a client."
                )
            self.client = TelegramClient(
                self._session_name, self._api_id, self._api_hash
            )
            await self.client.start(phone=self._phone)
            logger.info("Simulator: own Telegram client connected")
        else:
            logger.info("Simulator: using shared Telegram client")

        from ai.integrated_processor import IntegratedProcessor
        self.processor = IntegratedProcessor(config)
        self._throttle_vision_calls(self.processor.image_extractor)

        from src.services.trade_context_manager import TradeContextManager
        self.context_manager = TradeContextManager(ai_client=self.processor.client)

        from ai.trade_command_processor import TradeCommandProcessor
        self.command_processor = TradeCommandProcessor(config)

        # Read-only price source for the reply book (M1 candles)
        try:
            from src.integrations.trading.provider_factory import create_trading_provider
            self._candle_provider = create_trading_provider()
        except Exception as exc:
            logger.warning(f"Simulator: no candle provider ({exc}) — replies replay without prices")

        if self.enable_brain:
            from ai.trading_brain import TradingBrain
            self.brain = TradingBrain(config)
            self.brain.start_session(account_info=None)
            logger.info("Simulator: TradingBrain enabled")

    async def close(self) -> None:
        if not self._shared_client and self.client:
            await self.client.disconnect()
            logger.info("Simulator: own Telegram client disconnected")

    def cancel(self) -> None:
        self._cancelled = True

    @staticmethod
    def _throttle_vision_calls(image_extractor) -> None:
        """Cap vision API calls to VISION_RATE_LIMIT_PER_SEC for this run.

        Replaying historical messages can fire vision requests far faster
        than live Telegram traffic ever would; some providers 429 above
        ~20 req/s. Wrap the one instance's bound method — production code
        (ai/image_signal_extractor.py) is untouched.
        """
        limiter = _AsyncRateLimiter(VISION_RATE_LIMIT_PER_SEC)
        original = image_extractor.process_message_with_image

        async def _throttled(*args, **kwargs):
            await limiter.acquire()
            return await original(*args, **kwargs)

        image_extractor.process_message_with_image = _throttled

    # ── Message fetching ──────────────────────────────────────────────────────

    async def fetch_messages(
        self,
        channel_id: int,
        start_date: datetime,
        end_date: datetime,
        limit: int = 1000,
    ) -> Tuple[List[Message], Dict[int, Message]]:
        """
        Fetch messages in the date range and return them **oldest-first** together
        with an index dict {message_id: Message} for reply-context look-ups.

        Includes messages with text, images, or both.  Pure non-media, non-text
        messages (service messages, stickers, etc.) are excluded.
        """
        if start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=timezone.utc)
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)

        if self._message_fetcher is not None:
            fetched = list(await self._message_fetcher(channel_id, start_date, end_date, limit))
            logger.info(f"Fetched {len(fetched)} messages from channel {channel_id} — processing oldest-first")
            return fetched, {m.id: m for m in fetched}

        messages: List[Message] = []
        msg_index: Dict[int, Message] = {}
        scanned = 0

        # iter_messages returns newest → oldest
        async for msg in self.client.iter_messages(channel_id, limit=limit):
            scanned += 1
            if msg.date < start_date:
                break
            if msg.date > end_date:
                continue

            has_text = bool(getattr(msg, 'message', None) and msg.message.strip())
            has_img  = _detect_image(msg)
            has_any_media = bool(getattr(msg, 'media', None))

            if not has_text and not has_img and not has_any_media:
                continue  # service messages, stickers, etc.

            messages.append(msg)
            msg_index[msg.id] = msg

        # Reverse so we process oldest → newest (correct context order)
        messages.reverse()

        logger.info(
            f"Fetched {len(messages)} messages (scanned {scanned}) "
            f"from channel {channel_id} — processing oldest-first"
        )
        return messages, msg_index

    # ── Single-message pipeline ───────────────────────────────────────────────

    async def process_message(
        self,
        message: Message,
        msg_index: Optional[Dict[int, Message]] = None,
    ) -> SimulatedTrade:
        """
        Run one message through the full live pipeline.

        Routing order matches MessageHandler.process_message:
          reply → plain command → pre-filter → AI intent →
          NOT_TRADING → STATUS(no img) → COMMAND → extraction
        """
        has_image = _detect_image(message)
        text = getattr(message, 'message', '') or ""

        # Detect reply
        reply_to = getattr(message, 'reply_to', None)
        is_reply = reply_to is not None and hasattr(reply_to, 'reply_to_msg_id')
        reply_to_msg_id: Optional[int] = reply_to.reply_to_msg_id if is_reply else None

        trade = SimulatedTrade(
            message_id=message.id,
            timestamp=message.date,
            original_message=text,
            has_image=has_image,
            is_reply=is_reply,
            reply_to_message_id=reply_to_msg_id,
        )

        try:
            # Step 1 — download image bytes
            image_data: Optional[bytes] = None
            if has_image:
                try:
                    image_data = await message.download_media(bytes)
                except Exception as exc:
                    logger.warning(f"Image download failed for msg {message.id}: {exc}")

            parts = getattr(self, '_album_parts', {}).get(message.id)
            if parts:
                images = [image_data] if image_data else []
                for part in parts:
                    if _detect_image(part):
                        try:
                            b = await part.download_media(bytes)
                            if b:
                                images.append(b)
                        except Exception as exc:
                            logger.warning(f"Album part download failed for msg {part.id}: {exc}")
                if images:
                    has_image = True
                    trade.has_image = True
                    image_data = images if len(images) > 1 else images[0]

            has_text  = len(text.strip()) >= 5
            has_text10 = len(text.strip()) >= 10  # threshold for AI calls

            # ── Step 1b: split post — same decision as live MessageHandler ─
            text_post = None
            split_posts = getattr(self, 'split_posts', None)
            if split_posts is not None:
                from src.services.split_post import SplitPostTracker
                chat = getattr(self, '_channel_id', 'simulator')
                sender = getattr(message, 'sender_id', None)
                if SplitPostTracker.is_companion_candidate(text, has_image, getattr(message, 'grouped_id', None), is_reply):
                    post = split_posts.companion_for(chat, sender, message.date)
                    if post:
                        await self._split_post_image(trade, post, image_data)
                        return trade
                elif text.strip() and not has_image and not is_reply:
                    text_post = split_posts.start_text(chat, sender, message.id, text, message.date)

            # ── Step 2: direct reply → trade-update routing ───────────────
            if is_reply:
                if self.reply_book is not None:
                    await self._replay_reply(trade, text, image_data, reply_to_msg_id, message.date)
                else:
                    await self._handle_reply(trade, text, image_data, reply_to_msg_id)
                return trade

            # ── Steps 3-6 mirror MessageHandler.process_message for non-replies ──
            # Plain-command keywords only ROUTE the message as a command; the reply
            # AI decides the action (live no longer executes keyword parses).
            plain_cmd = has_text and _is_plain_command(text)
            if not has_image and not has_text:
                trade.extraction_method = "prefiltered"
                trade.extraction_error = "no text and no image"
                return trade

            intent = "COMMAND" if plain_cmd else "SIGNAL"
            intent_source = "plain_command" if plain_cmd else "default"
            if has_text10 and not plain_cmd:
                try:
                    intent = await self.processor.classify_message_intent(text)
                    intent_source = "ai"
                except Exception as exc:
                    logger.warning(f"Intent classification failed: {exc}")
                    intent_source = "keyword_fallback"
                    cmd_kw = [
                        "close", "exit", "modify", "move sl", "breakeven",
                        "cancel", "set be", "update sl", "update tp",
                    ]
                    if any(kw in text.lower() for kw in cmd_kw):
                        intent = "COMMAND"

            trade.intent = intent
            trade.intent_source = intent_source

            # NOT_TRADING → skip, unless a chart is attached: live tries vision and
            # sends anything it finds to manual approval
            if intent == "NOT_TRADING" and not has_image:
                trade.extraction_method = "skipped_not_trading"
                trade.extraction_error = "AI classified as NOT_TRADING — no extraction"
                return trade

            # COMMAND / STATUS while a trade is active → live handles it like a reply
            # to the channel's latest active signal (reply AI + live state)
            target = self.reply_book.latest_active(message.date, text) if self.reply_book is not None else None
            if intent in ("COMMAND", "STATUS") and target is not None:
                await self._replay_reply(trade, text, image_data, target, message.date, standalone=True)
                return trade

            if intent == "COMMAND":
                await self._handle_command(trade, text)  # no active trade: nothing to manage
                return trade

            # STATUS → skip, image or not (a status caption's chart is a results
            # screenshot, not a new setup)
            if intent == "STATUS":
                trade.extraction_method = "skipped_status"
                trade.extraction_error = "AI classified as STATUS — ignored"
                return trade

            # Live _handle_new_signal pre-filter (only on the new-signal path)
            if has_text10 and not _is_potential_signal(text, has_image=has_image):
                trade.extraction_method = "prefiltered"
                trade.extraction_error = "pre-filter: no trading keywords or price numbers"
                return trade

            # SIGNAL or STATUS+image → full extraction
            # NOTE: pass raw text (possibly empty) — never a placeholder string.
            # IntegratedProcessor checks `len(message.strip()) >= 3` to decide
            # has_text; a placeholder like "[Image only]" would satisfy that
            # check and wrongly route through TEXT-FIRST AI classification
            # instead of straight to vision, silently killing image extraction.
            signal = await self.processor.process_message(
                text,
                image_data=image_data,
            )
            if text_post is not None:
                split_posts.note_extraction(
                    text_post.chat, message.id, extracted=bool(signal),
                    rejection=getattr(self.processor, "rejection_reason", None),
                )

            if not signal:
                trade.extraction_method = "failed"
                trade.extraction_error = (
                    getattr(self.processor, "rejection_reason", None)
                    or "no signal extracted"
                )
                return trade

            signal.raw_message = text
            if signal.symbol:
                signal.symbol = _normalize_symbol(signal.symbol)

            method = getattr(self.processor, "last_extraction_method", "ai")

            # Context resolution for CLOSE/MODIFY without symbol
            if (
                not signal.symbol
                and signal.action in (
                    SignalAction.CLOSE, SignalAction.MODIFY, SignalAction.PARTIAL_CLOSE
                )
            ):
                resolved = await self._resolve_context(signal, text)
                if resolved:
                    trade.context_resolved = True
                    trade.context_resolution_method = "ai"

            # Update conversation history
            self.context_manager.add_to_conversation_history(
                "simulator_channel",
                text,
                {
                    "action": signal.action.value if signal.action else None,
                    "symbol": signal.symbol,
                    "entry": signal.entry_price,
                },
            )

            self._populate_trade(trade, signal, method)
            self._track_position(signal, message.date)
            if self.reply_book is not None:
                await self.reply_book.register(message.id, signal, message.date)

            if self.enable_brain and self.brain and trade.extraction_method != "failed":
                await self._brain_review(trade, signal)

        except Exception as exc:
            trade.extraction_method = "failed"
            trade.processing_error = str(exc)
            logger.error(f"Error processing message {message.id}: {exc}")

        return trade

    # ── Reply routing (mirrors live _handle_trade_update, without broker calls) ──

    async def _split_post_image(self, trade: SimulatedTrade, post, image_data: Optional[bytes]) -> None:
        """Caption-less chart right after a text post — mirrors MessageHandler._handle_split_post_image."""
        trade.intent = "SPLIT_POST"
        if post.extracted:
            trade.extraction_method = "split_post_attached"
            trade.extraction_error = f"chart attached to the signal from text #{post.message_id}"
            return
        if post.needs_image and not post.fused:
            post.fused = True
            signal = await self.processor.process_message(post.text, image_data=image_data)
            if signal and signal.action == SignalAction.OPEN:
                if signal.symbol:
                    signal.symbol = _normalize_symbol(signal.symbol)
                self._populate_trade(trade, signal, getattr(self.processor, "last_extraction_method", "fused"))
                trade.intent = "SIGNAL"
                if self.reply_book is not None:
                    await self.reply_book.register(trade.message_id, signal, trade.timestamp)
            else:
                trade.extraction_method = "failed"
                trade.extraction_error = (getattr(self.processor, "rejection_reason", None)
                                          or f"text #{post.message_id} + chart: no signal")
            return
        trade.extraction_method = "split_post_ignored"
        trade.extraction_error = f"chart belongs to non-signal text #{post.message_id}"

    async def _replay_reply(
        self,
        trade: SimulatedTrade,
        text: str,
        image_data: Optional[bytes],
        reply_to_msg_id: Optional[int],
        ts: datetime,
        standalone: bool = False,
    ) -> None:
        """
        Live routing for a direct reply: MessageHandler._handle_trade_update →
        ReplyHandlerService.handle_reply, then the fresh-signal fallback. Runs the
        real handler and reply AI against the candle-driven book.

        standalone=True: a non-reply command/status aimed at the channel's latest
        active signal (MessageHandler._handle_standalone_management) — no
        fresh-signal fallback, as live.
        """
        from simulator.reply_replay import replay_reply
        out = await replay_reply(
            self.reply_book, self.command_processor, self.context_manager,
            reply_to=reply_to_msg_id, text=text, ts=ts,
            channel_id=getattr(self, '_channel_id', 'simulator'), image_data=image_data,
        )
        res = out['result']
        trade.reply_state = out['state_before']
        trade.reply_ai_action = out['ai_action']
        trade.reply_broker_calls = out['broker_calls']
        trade.reply_state_after = out['state_after']
        trade.reply_result = res.get('message') or res.get('error') or res.get('reason')
        trade.command_action = out['ai_action']
        trade.command_value = out['ai_value']
        trade.command_percentage = out['ai_percentage']
        trade.intent = "COMMAND" if out['ai_action'] else "STATUS"
        trade.intent_source = "standalone_ai" if standalone else "reply_ai"
        trade.extraction_method = "command" if out['ai_action'] else "skipped_status"
        if standalone:
            trade.reply_to_message_id = reply_to_msg_id  # the signal it was applied to
            return

        # Live fallback: a reply to a finished/unknown trade, or one carrying a fresh
        # entry with levels, goes to full signal extraction.
        err = res.get('error') or ''
        from src.services.message_handler import MessageHandler
        fresh = (
            ('No active positions or pending orders found' in err or 'Could not understand' in err)
            or (res.get('ignored') and MessageHandler._looks_like_entry_with_levels(text))
        )
        if fresh and (len(text.strip()) >= 10 or image_data):
            signal = await self.processor.process_message(text, image_data=image_data)
            if signal and signal.action == SignalAction.OPEN:
                if signal.symbol:
                    signal.symbol = _normalize_symbol(signal.symbol)
                self._populate_trade(trade, signal, getattr(self.processor, "last_extraction_method", "ai"))
                trade.intent = "SIGNAL"
                await self.reply_book.register(trade.message_id, signal, ts)

    async def _handle_reply(
        self,
        trade: SimulatedTrade,
        text: str,
        image_data: Optional[bytes],
        reply_to_msg_id: Optional[int],
    ) -> None:
        """
        Handle a message that is a Telegram reply.

        Live pipeline: direct replies are ALWAYS routed as trade updates.
        Here we do the same classification and recording — no broker calls.
        """
        has_text  = len(text.strip()) >= 5
        has_text10 = len(text.strip()) >= 10

        # Layer 0+1: plain command even inside a reply
        if has_text and _is_plain_command(text):
            parsed = _parse_plain_command(text)
            if parsed:
                trade.intent = "COMMAND"
                trade.intent_source = "plain_command"
                trade.extraction_method = "command"
                trade.command_action = parsed['action']
                trade.command_value = parsed.get('value')
                trade.command_percentage = parsed.get('percentage')
                return

        # AI classification for the reply
        intent = "STATUS"       # default — most replies are status updates
        intent_source = "default"

        if has_text10:
            try:
                intent = await self.processor.classify_message_intent(text)
                intent_source = "ai"
            except Exception:
                intent = "STATUS"
        elif not has_text and image_data:
            # Image-only reply — could be a new chart/signal
            intent = "SIGNAL"
            intent_source = "default"

        trade.intent = intent
        trade.intent_source = intent_source

        if intent == "COMMAND":
            await self._handle_command(trade, text)

        elif intent in ("STATUS", "NOT_TRADING"):
            trade.extraction_method = "skipped_status"
            trade.extraction_error = f"Reply: AI classified as {intent}"

        elif intent == "SIGNAL":
            # Some providers post new signals as replies to their previous signals
            if has_text10 or image_data:
                signal = await self.processor.process_message(
                    text,  # raw text (possibly empty) — never a placeholder
                    image_data=image_data,
                )
                if signal:
                    if signal.symbol:
                        signal.symbol = _normalize_symbol(signal.symbol)
                    method = getattr(self.processor, "last_extraction_method", "ai")
                    self._populate_trade(trade, signal, method)
                    self._track_position(signal, trade.timestamp)
                else:
                    trade.extraction_method = "failed"
                    trade.extraction_error = (
                        getattr(self.processor, "rejection_reason", None)
                        or "Reply signal extraction failed"
                    )
            else:
                trade.extraction_method = "prefiltered"
                trade.extraction_error = "Reply: insufficient content for extraction"

    # ── Command handling ──────────────────────────────────────────────────────

    async def _handle_command(self, trade: SimulatedTrade, text: str) -> None:
        """Route to AI command processor, fall back to signal extraction."""
        try:
            symbol_ctx = _extract_symbol_from_text(text)
            command = await self.command_processor.process_command(
                text, symbol_context=symbol_ctx
            )
            if command:
                trade.command_action = command.action
                trade.command_value = command.value
                trade.command_percentage = command.percentage
                trade.extraction_method = "command"
                if command.action in ("close", "close_all") and symbol_ctx:
                    self._close_position(symbol_ctx)
            else:
                # AI couldn't parse it as a command — try signal extraction
                signal = await self.processor.process_message(text)
                if signal:
                    self._populate_trade(
                        trade, signal,
                        getattr(self.processor, "last_extraction_method", "ai"),
                    )
        except Exception as exc:
            trade.extraction_method = "failed"
            trade.extraction_error = f"command processing failed: {exc}"

    # ── Context resolution ────────────────────────────────────────────────────

    async def _resolve_context(self, signal: TradingSignal, text: str) -> bool:
        """Use in-memory position list as context for symbol resolution."""
        original = self.context_manager._get_open_positions

        async def _mock(*_a, **_kw):
            return self._positions

        self.context_manager._get_open_positions = _mock
        try:
            signal.raw_message = text
            resolved = await self.context_manager.resolve_symbol_from_context(
                signal, "simulator_channel"
            )
            if resolved.symbol:
                signal.symbol = resolved.symbol
                return True
            return False
        finally:
            self.context_manager._get_open_positions = original

    # ── Trade field population ────────────────────────────────────────────────

    def _populate_trade(
        self, trade: SimulatedTrade, signal: TradingSignal, method: str
    ) -> None:
        trade.extraction_method = method
        raw = json.dumps(
            {
                "action": signal.action.value if signal.action else None,
                "symbol": signal.symbol,
                "entry_price": signal.entry_price,
                "stop_loss": signal.stop_loss,
                "take_profit": signal.take_profit,
            },
            indent=2,
        )

        if method in ("ai", "image_vision", "fused"):
            trade.ai_extracted = True
            trade.image_extracted = method in ("image_vision", "fused")
            trade.ai_action = signal.action.value if signal.action else None
            trade.ai_order_type = signal.order_type.value if signal.order_type else None
            trade.ai_symbol = signal.symbol
            trade.ai_entry = signal.entry_price
            trade.ai_sl = signal.stop_loss
            trade.ai_tp = signal.take_profit
            trade.ai_confidence = getattr(signal, "confidence", None)
            trade.ai_raw_response = raw
        else:
            trade.pattern_extracted = True
            trade.pattern_action = signal.action.value if signal.action else None
            trade.pattern_order_type = signal.order_type.value if signal.order_type else None
            trade.pattern_symbol = signal.symbol
            trade.pattern_entry = signal.entry_price
            trade.pattern_sl = signal.stop_loss
            trade.pattern_tp = signal.take_profit
            trade.pattern_raw_response = raw

        trade.is_plan = bool(getattr(signal, "is_plan", False))
        if trade.is_plan:
            trade.plan_symbol = signal.symbol

        meta = getattr(signal, "metadata", None) or {}
        trade.is_reenter      = meta.get("is_reenter", False)
        trade.is_risky        = meta.get("is_risky", False)
        trade.is_limit_order  = meta.get("is_limit_order", False)
        trade.is_stop_order   = meta.get("is_stop_order", False)
        trade.is_breakeven    = meta.get("is_breakeven", False)
        trade.risk_level      = meta.get("risk_level", "normal")
        trade.special_instructions = meta.get("special_instructions", [])

    # ── Position tracking ─────────────────────────────────────────────────────

    def _track_position(self, signal: TradingSignal, ts: datetime) -> None:
        if signal.action == SignalAction.OPEN and signal.symbol:
            self._positions.append(
                {
                    "symbol": signal.symbol,
                    "action": signal.action.value,
                    "order_type": (
                        signal.order_type.value if signal.order_type else "BUY"
                    ),
                    "entry_price": signal.entry_price,
                    "stop_loss": signal.stop_loss,
                    "take_profit": signal.take_profit,
                    "opened_at": ts,
                    "position_id": f"sim_{len(self._positions) + 1}",
                    "lot_size": signal.lot_size or 0.01,
                    "magic_number": 999999,
                }
            )
        elif signal.action in (
            SignalAction.CLOSE, SignalAction.PARTIAL_CLOSE
        ) and signal.symbol:
            for pos in self._positions[:]:
                if pos["symbol"] == signal.symbol:
                    self._positions.remove(pos)
                    if signal.action == SignalAction.CLOSE:
                        break

    def _close_position(self, symbol: str) -> None:
        for pos in self._positions[:]:
            if pos["symbol"] == symbol:
                self._positions.remove(pos)
                break

    # ── Brain review ──────────────────────────────────────────────────────────

    async def _brain_review(
        self, trade: SimulatedTrade, signal: TradingSignal
    ) -> None:
        try:
            decision = await self.brain.review_signal(signal)
            trade.brain_reviewed = True
            trade.brain_verdict = decision.verdict
            trade.brain_reason = (decision.reason or "")[:200]
        except Exception as exc:
            logger.warning(f"Brain review failed: {exc}")

    # ── Full simulation run ───────────────────────────────────────────────────

    async def run(
        self,
        channel_id: int,
        channel_name: str,
        start_date: datetime,
        end_date: datetime,
        limit: int = 1000,
        on_progress: Optional[ProgressCallback] = None,
    ) -> SimulationResults:
        self._cancelled = False
        self._positions = []
        from simulator.reply_replay import SimBook
        self.reply_book = SimBook(self._candle_provider, start_date)
        self._channel_id = str(channel_id)
        from src.services.split_post import SplitPostTracker
        self.split_posts = SplitPostTracker()

        messages, msg_index = await self.fetch_messages(
            channel_id, start_date, end_date, limit
        )
        total = len(messages)

        results = SimulationResults(
            channel_id=channel_id,
            channel_name=channel_name,
            start_date=start_date,
            end_date=end_date,
            total_messages=total,
        )

        # Albums: live buffers every part of a grouped post and processes it ONCE
        # (caption + all images). Mirror that: the captioned part (or the first)
        # carries the other parts' images; the rest are recorded as album parts.
        self._album_parts: Dict[int, List] = {}
        album_skip: Dict[int, int] = {}
        groups: Dict[int, List] = {}
        for m in messages:
            gid = getattr(m, 'grouped_id', None)
            if gid:
                groups.setdefault(gid, []).append(m)
        for parts in groups.values():
            if len(parts) < 2:
                continue
            primary = next((m for m in parts if (getattr(m, 'message', '') or '').strip()), parts[0])
            self._album_parts[primary.id] = [m for m in parts if m is not primary]
            for m in parts:
                if m is not primary:
                    album_skip[m.id] = primary.id

        for idx, msg in enumerate(messages, 1):
            if self._cancelled:
                logger.info("Simulator: cancelled by user")
                break

            if msg.id in album_skip:
                trade = SimulatedTrade(
                    message_id=msg.id, timestamp=msg.date,
                    original_message=getattr(msg, 'message', '') or '',
                    has_image=_detect_image(msg),
                    intent="ALBUM_PART", extraction_method="album_part",
                    extraction_error=f"part of album #{album_skip[msg.id]} — processed with it",
                )
                results.trades.append(trade)
                _aggregate(results, trade)
                if on_progress:
                    await on_progress(idx, total, trade)
                continue

            trade = await self.process_message(msg, msg_index=msg_index)
            results.trades.append(trade)
            _aggregate(results, trade)

            if on_progress:
                await on_progress(idx, total, trade)

        _finalise(results)
        self._save(results)
        return results

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save(self, results: SimulationResults) -> Path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = re.sub(r"[^\w\-]", "_", results.channel_name)
        path = self.results_dir / f"{safe_name}_{ts}.json"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(results.to_dict(), fh, indent=2, ensure_ascii=False)
        logger.info(f"Simulator results saved → {path}")
        return path


# ══════════════════════════════════════════════════════════════════════════════
# STATISTICS HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _aggregate(results: SimulationResults, trade: SimulatedTrade) -> None:
    from src.models.enums import SignalAction as SA

    # Reply messages
    if trade.is_reply:
        results.reply_messages += 1

    # Plain-command (Layer 0+1) tally
    if trade.intent_source == "plain_command":
        results.plain_command_count += 1

    # Intent distribution
    intent_map = {
        "SIGNAL":      "intent_signal_count",
        "COMMAND":     "intent_command_count",
        "STATUS":      "intent_status_count",
        "NOT_TRADING": "intent_non_trading_count",
    }
    if trade.intent in intent_map:
        attr = intent_map[trade.intent]
        setattr(results, attr, getattr(results, attr) + 1)

    if trade.intent_source == "ai":
        results.intent_ai_classified += 1
    elif trade.intent_source == "keyword_fallback":
        results.intent_keyword_fallback += 1

    # Extraction method
    m = trade.extraction_method or ""
    if m == "prefiltered":  # status / not-trading skips have their own intent counts
        results.prefiltered_count += 1
    elif m == "image_vision":
        results.image_extracted_count += 1
        _tally_action(results, trade.ai_action)
        _tally_symbol(results, trade.ai_symbol)
    elif m == "fused":
        results.fused_extracted_count += 1
        _tally_action(results, trade.ai_action)
        _tally_symbol(results, trade.ai_symbol)
    elif trade.ai_extracted:
        results.ai_extracted_count += 1
        _tally_action(results, trade.ai_action)
        _tally_symbol(results, trade.ai_symbol)
    elif trade.pattern_extracted:
        results.pattern_extracted_count += 1
        _tally_action(results, trade.pattern_action)
        _tally_symbol(results, trade.pattern_symbol)
    elif m == "command":
        results.commands_processed += 1
        _tally_command(results, trade)
    elif m == "failed" or trade.processing_error:
        results.failed_extraction_count += 1
        err_key = (trade.extraction_error or trade.processing_error or "unknown")[:100]
        results.common_errors[err_key] = results.common_errors.get(err_key, 0) + 1

    # Image stats
    if trade.has_image:
        results.messages_with_images += 1
        if trade.image_extracted:
            results.images_processed += 1

    # Signal flags
    if trade.is_plan:       results.plan_signals += 1
    if trade.is_reenter:    results.reenter_commands += 1
    if trade.is_risky:      results.risky_trades += 1
    if trade.is_limit_order: results.limit_orders += 1
    if trade.is_stop_order:  results.stop_orders += 1
    if trade.is_breakeven:   results.breakeven_commands += 1

    # Context resolution
    if trade.context_resolved:
        results.context_resolved_count += 1
        if trade.context_resolution_method == "ai":
            results.ai_context_resolved += 1
        else:
            results.db_context_resolved += 1

    # Brain
    if trade.brain_reviewed:
        results.brain_reviewed_count += 1
        if trade.brain_verdict == "APPROVE":    results.brain_approved += 1
        elif trade.brain_verdict == "REJECT":   results.brain_rejected += 1
        elif trade.brain_verdict == "MODIFY":   results.brain_modified += 1


def _tally_action(results: SimulationResults, action: Optional[str]) -> None:
    from src.models.enums import SignalAction as SA
    map_ = {
        SA.OPEN.value:          "open_signals",
        SA.CLOSE.value:         "close_signals",
        SA.MODIFY.value:        "modify_signals",
        SA.PARTIAL_CLOSE.value: "partial_close_signals",
        "CANCEL":               "cancel_signals",
    }
    if action in map_:
        attr = map_[action]
        setattr(results, attr, getattr(results, attr) + 1)


def _tally_symbol(results: SimulationResults, symbol: Optional[str]) -> None:
    if symbol:
        results.symbol_distribution[symbol] = (
            results.symbol_distribution.get(symbol, 0) + 1
        )


def _tally_command(results: SimulationResults, trade: SimulatedTrade) -> None:
    map_ = {
        "close":         "commands_close",
        "close_all":     "commands_close",
        "partial_close": "commands_partial_close",
        "modify_sl":     "commands_modify_sl",
        "modify_tp":     "commands_modify_tp",
        "breakeven":     "commands_breakeven",
        "cancel_orders": "commands_cancel",
        # extras tracked but no separate counter — they fall into commands_processed
    }
    if trade.command_action in map_:
        attr = map_[trade.command_action]
        setattr(results, attr, getattr(results, attr) + 1)


def _finalise(results: SimulationResults) -> None:
    n = results.total_messages
    if n > 0:
        results.ai_accuracy      = round(results.ai_extracted_count / n * 100, 2)
        results.pattern_accuracy = round(results.pattern_extracted_count / n * 100, 2)
