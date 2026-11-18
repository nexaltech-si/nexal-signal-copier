"""
Telegram Browser Service
Provides read-only access to Telegram dialogs and messages for the dashboard browser.
Uses the shared Telethon client — never creates a new session.
"""
import asyncio
import re
from io import BytesIO
from typing import Optional
from telethon import TelegramClient
from telethon.extensions import html as tl_html
from telethon.extensions import markdown as tl_md
from telethon.tl.types import Channel, Chat, User, MessageMediaPhoto, MessageMediaDocument
from loguru import logger


_ZERO_WIDTH = re.compile('[\u200b\u200c\u200d\u200e\u200f\u2060\ufeff\ufe0f]')


SAFE_IMAGE_MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/gif", "image/webp"})


class TelegramBrowserService:
    def __init__(self):
        self.client: Optional[TelegramClient] = None
        self._initialized = False

    async def initialize(self, shared_client: TelegramClient):
        if self._initialized:
            return
        self.client = shared_client
        self._initialized = True
        logger.success("✅ Telegram browser service initialized with shared client")

    def _clean_text(self, text: str) -> str:
        if not text:
            return ""
        return _ZERO_WIDTH.sub('', text).strip()

    def _format_html(self, text: str, entities) -> str:
        """Convert Telethon message text + entities to safe HTML.

        When no entities are present (e.g. bot sent raw markdown text without
        parse_mode), fall back to Telethon's markdown parser so **bold**,
        __italic__, and `code` markers are still rendered as HTML.
        """
        raw = text or ''
        try:
            if entities:
                html = tl_html.unparse(raw, entities)
            else:
                # Fallback: parse Telegram markdown syntax (**bold**, __italic__, `code`)
                try:
                    parsed_text, parsed_entities = tl_md.parse(raw)
                    html = tl_html.unparse(parsed_text, parsed_entities) if parsed_entities else raw
                except Exception:
                    html = raw
            return _ZERO_WIDTH.sub('', html)
        except Exception:
            return _ZERO_WIDTH.sub('', raw)

    def _dialog_type(self, entity) -> str:
        if isinstance(entity, Channel):
            if entity.broadcast:
                return "channel"
            return "supergroup" if entity.megagroup else "group"
        if isinstance(entity, Chat):
            return "group"
        return "user"

    def _sender_name(self, message) -> Optional[str]:
        if message.post_author:
            return message.post_author
        try:
            s = message.sender
            if s and hasattr(s, 'title'):
                return s.title
            if s:
                first = getattr(s, 'first_name', '') or ''
                last = getattr(s, 'last_name', '') or ''
                return (first + ' ' + last).strip() or None
        except Exception as _exc:
            logger.debug(f"Suppressed exception: {_exc!r}")
        return None

    def _media_type(self, message) -> Optional[str]:
        if not message.media:
            return None
        if isinstance(message.media, MessageMediaPhoto):
            return "photo"
        if isinstance(message.media, MessageMediaDocument):
            doc = message.media.document
            if doc:
                mime = getattr(doc, 'mime_type', '') or ''
                if mime.startswith('image/'):
                    return "image"
                if mime.startswith('video/'):
                    return "video"
                return "document"
        return "other"

    async def get_dialogs(self, limit: int = 200) -> list[dict]:
        if not self._initialized or not self.client:
            return []
        try:
            dialogs = await asyncio.wait_for(
                self.client.get_dialogs(limit=limit),
                timeout=10,
            )
            result = []
            for d in dialogs:
                entity = d.entity
                if isinstance(entity, User):
                    continue
                last_date = None
                if d.message and d.message.date:
                    last_date = d.message.date.isoformat()
                last_preview = None
                if d.message:
                    last_preview = self._clean_text(d.message.text or "")[:80] or None
                result.append({
                    "id": str(d.id),
                    "title": getattr(entity, 'title', str(d.id)),
                    "username": getattr(entity, 'username', None),
                    "type": self._dialog_type(entity),
                    "unread_count": d.unread_count,
                    "last_message_date": last_date,
                    "last_preview": last_preview,
                })
            return result
        except Exception as e:
            logger.warning(f"⚠️ Browser get_dialogs failed: {e}")
            return []

    async def get_messages(self, channel_id: int, limit: int = 50) -> list[dict]:
        if not self._initialized or not self.client:
            return []
        try:
            messages = await asyncio.wait_for(
                self.client.get_messages(channel_id, limit=limit),
                timeout=10,
            )

            # Pre-build album groups (same grouped_id = one Telegram album)
            group_map: dict[int, list] = {}
            for m in messages:
                gid = getattr(m, 'grouped_id', None)
                if gid:
                    group_map.setdefault(gid, []).append(m)

            # Collect unique reply_to_msg_ids for batch-fetching
            reply_ids: list[int] = []
            for m in messages:
                rt = getattr(m, 'reply_to', None)
                rid = getattr(rt, 'reply_to_msg_id', None) if rt else None
                if rid and rid not in reply_ids:
                    reply_ids.append(rid)

            # Batch-fetch all replied-to messages in one call
            replied_map: dict[int, dict] = {}
            if reply_ids:
                try:
                    replied_msgs = await asyncio.wait_for(
                        self.client.get_messages(channel_id, ids=reply_ids),
                        timeout=10,
                    )
                    items = replied_msgs if isinstance(replied_msgs, list) else [replied_msgs]
                    for rm in items:
                        if rm is None:
                            continue
                        replied_map[rm.id] = {
                            "id": rm.id,
                            "text": self._clean_text(rm.text or "")[:120] or None,
                            "sender_name": self._sender_name(rm),
                            "has_media": rm.media is not None,
                            "media_type": self._media_type(rm),
                        }
                except Exception as e:
                    logger.debug(f"Browser batch-fetch replies failed: {e}")

            result = []
            seen_groups: set[int] = set()

            for m in messages:
                gid = getattr(m, 'grouped_id', None)
                rt = getattr(m, 'reply_to', None)
                reply_to_id = getattr(rt, 'reply_to_msg_id', None) if rt else None
                reply_to = replied_map.get(reply_to_id) if reply_to_id else None

                if gid:
                    # Album: emit once, combining all photos into one bubble
                    if gid in seen_groups:
                        continue
                    seen_groups.add(gid)
                    group = group_map[gid]
                    # Use the caption from whichever member has text
                    cap_msg = next((gm for gm in group if gm.text), None)
                    caption = cap_msg.text if cap_msg else ""
                    cap_entities = cap_msg.entities if cap_msg else None
                    rep = group[0]
                    media_ids = [gm.id for gm in group if gm.media]
                    mt = "photo_group" if len(media_ids) > 1 else (self._media_type(rep) or "photo")
                    result.append({
                        "id": rep.id,
                        "text": caption,
                        "clean_text": self._clean_text(caption),
                        "html_text": self._format_html(caption, cap_entities),
                        "date": rep.date.isoformat() if rep.date else None,
                        "sender_id": str(rep.sender_id) if rep.sender_id else None,
                        "sender_name": self._sender_name(rep),
                        "has_media": bool(media_ids),
                        "media_type": mt,
                        "media_ids": media_ids,
                        "reply_to": reply_to,
                    })
                else:
                    # Single message
                    raw_text = m.text or ""
                    result.append({
                        "id": m.id,
                        "text": raw_text,
                        "clean_text": self._clean_text(raw_text),
                        "html_text": self._format_html(raw_text, m.entities),
                        "date": m.date.isoformat() if m.date else None,
                        "sender_id": str(m.sender_id) if m.sender_id else None,
                        "sender_name": self._sender_name(m),
                        "has_media": m.media is not None,
                        "media_type": self._media_type(m),
                        "media_ids": [m.id] if m.media else [],
                        "reply_to": reply_to,
                    })

            return result
        except Exception as e:
            logger.warning(f"⚠️ Browser get_messages({channel_id}) failed: {e}")
            return []

    async def get_message_media(self, channel_id: int, message_id: int) -> tuple[bytes | None, str]:
        if not self._initialized or not self.client:
            return None, "image/jpeg"
        try:
            message = await asyncio.wait_for(
                self.client.get_messages(channel_id, ids=message_id),
                timeout=10,
            )
            if not message or not message.media:
                return None, "image/jpeg"
            if not isinstance(message.media, (MessageMediaPhoto, MessageMediaDocument)):
                return None, "image/jpeg"

            content_type = "image/jpeg"
            if isinstance(message.media, MessageMediaDocument):
                doc = message.media.document
                mime = getattr(doc, 'mime_type', '') or '' if doc else ''
                # Raster only: image/svg+xml from a channel would be served on the
                # dashboard origin and run script (audit finding M-08).
                if mime.lower() not in SAFE_IMAGE_MIME_TYPES:
                    return None, "image/jpeg"
                content_type = mime.lower()

            buf = BytesIO()
            await asyncio.wait_for(
                self.client.download_media(message, file=buf),
                timeout=30,
            )
            buf.seek(0)
            return buf.read(), content_type
        except Exception as e:
            logger.warning(f"⚠️ Browser get_message_media({channel_id}, {message_id}) failed: {e}")
            return None, "image/jpeg"

    async def get_channel_photo(self, channel_id: int) -> tuple[bytes | None, str]:
        if not self._initialized or not self.client:
            return None, "image/jpeg"
        try:
            entity = await asyncio.wait_for(
                self.client.get_entity(channel_id),
                timeout=10,
            )
            buf = BytesIO()
            result = await asyncio.wait_for(
                self.client.download_profile_photo(entity, file=buf),
                timeout=15,
            )
            if result is None:
                return None, "image/jpeg"
            buf.seek(0)
            data = buf.read()
            return (data, "image/jpeg") if data else (None, "image/jpeg")
        except Exception as e:
            logger.debug(f"Browser get_channel_photo({channel_id}) failed: {e}")
            return None, "image/jpeg"


telegram_browser_service = TelegramBrowserService()
