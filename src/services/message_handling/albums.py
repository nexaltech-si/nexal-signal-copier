"""
Telegram albums (several photos sent as one post): buffer the items, wait for
the album to settle, process it once, and hold later messages until it is done.

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


class AlbumMixin:
    """Buffer and process Telegram albums in order."""

    async def _wait_for_open_album(self, chat_id, grouped_id) -> None:
        """Block until an earlier album of this chat has been fully processed (items of that album pass)."""
        entry = self._album_open.get(str(chat_id))
        if entry is None:
            return
        open_group, event = entry
        if grouped_id is not None and grouped_id == open_group:
            return                                   # another photo of the same album
        try:
            await asyncio.wait_for(event.wait(), timeout=self._album_settle_seconds + 60)
        except asyncio.TimeoutError:
            logger.warning(f"⏰ Album in chat {chat_id} did not finish in time - continuing without waiting")

    async def _buffer_album_item(
        self,
        event,
        message_id: MessageIdentifier,
        content: str,
        image_data: bytes,
        grouped_id,
        signal_callback,
    ) -> bool:
        """
        Collect one item of a Telegram album (grouped media). Telethon delivers each
        photo as a separate event; the caption arrives on only one of them. We buffer
        all items and process the album once no new item has arrived for
        _album_settle_seconds.
        """
        key = (message_id.chat_id, grouped_id)
        buf = self._album_buffers.get(key)
        if buf is None:
            previous = self._album_open.get(str(message_id.chat_id))
            if previous and previous[0] != grouped_id:
                previous[1].set()                               # an older album is superseded: never strand its waiters
            self._album_open[str(message_id.chat_id)] = (grouped_id, asyncio.Event())
            buf = {
                'event': event,
                'message_id': message_id,
                'content': '',
                'images': [],
                'task': None,
            }
            self._album_buffers[key] = buf

        if content and not buf['content']:
            # The captioned item is the album's "anchor" — replies map to its message ID
            buf['content'] = content
            buf['event'] = event
            buf['message_id'] = message_id
        buf['images'].append(image_data)
        logger.info(f"🖼️ Album item buffered ({len(buf['images'])} so far, grouped_id={grouped_id})")

        # Debounce: (re)start the settle timer on each new item
        if buf['task']:
            buf['task'].cancel()
        buf['task'] = asyncio.create_task(self._flush_album(key, signal_callback))
        return True

    async def _flush_album(self, key, signal_callback):
        """Process a fully assembled album as ONE message with ALL its images."""
        try:
            await asyncio.sleep(self._album_settle_seconds)
        except asyncio.CancelledError:
            return  # superseded by a newer item

        buf = self._album_buffers.pop(key, None)
        if not buf:
            return
        try:
            await self._process_album(buf, signal_callback)
        finally:
            entry = self._album_open.get(str(key[0]))
            if entry and entry[0] == key[1]:                    # only OUR marker (a newer album may have replaced it)
                self._album_open.pop(str(key[0]), None)
                entry[1].set()                                  # release the messages queued behind this album

    async def _process_album(self, buf, signal_callback):
        event = buf['event']
        message_id = buf['message_id']
        content = buf['content']
        images = buf['images']
        logger.info(f"🖼️ Album assembled: {len(images)} image(s), caption: {'yes' if content else 'no'}")

        try:
            first_image = images[0] if images else None
            if self._is_reply(event):
                logger.info("🔄 Album is a reply — routing as trade update")
                await self._handle_trade_update(
                    event, message_id, content,
                    signal_callback=signal_callback,
                    image_data=first_image,
                )
                return
            # Same routing as a single message: a management caption ("+190 pips
            # running — Set B.E save your profits") goes to the reply AI for the
            # channel's latest active signal; a status caption is not a new setup.
            if content.strip():
                intent = 'COMMAND' if self._is_plain_command(content) else (
                    await signal_service.classify_intent(content) if len(content.strip()) >= 10 else 'SIGNAL'
                )
                if intent in ('COMMAND', 'STATUS'):
                    result = await self._handle_standalone_management(event, message_id, content, first_image)
                    if result is None and intent == 'COMMAND':
                        await self._handle_trade_update(
                            event, message_id, content,
                            signal_callback=signal_callback, image_data=first_image,
                        )
                    return
            await self._handle_new_signal(
                event, message_id, content, signal_callback,
                image_data=images if images else None,
            )
        except Exception as e:
            logger.error(f"❌ Error processing album: {e}")
            logger.exception(e)
