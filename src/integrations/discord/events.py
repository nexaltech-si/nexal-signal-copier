"""
Discord messages in the shape the message pipeline already understands.

MessageHandler was written against Telethon events (event.message.text / .id /
.chat_id / .reply_to / .download_media, event.get_chat()). Rather than a second
pipeline, a Discord message is wrapped so it reads like one. Two differences are
bridged here:

- Text: signal bots usually post embeds (empty content, the trade in the embed's
  title / description / fields), so embeds are flattened into the text.
- Ids: a Discord message id is a 64-bit snowflake, the database stores 32-bit
  message ids. Each message gets a small local id (see store.py); the adapter
  carries that one.
"""
from types import SimpleNamespace
from typing import Awaitable, Callable, List, Optional

MAX_IMAGE_BYTES = 10 * 1024 * 1024
_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")


def _embed_text(embed) -> str:
    parts: List[str] = []
    author = getattr(getattr(embed, "author", None), "name", None)
    for value in (author, getattr(embed, "title", None), getattr(embed, "description", None)):
        if value:
            parts.append(str(value))
    for field in getattr(embed, "fields", None) or []:
        name, value = getattr(field, "name", None), getattr(field, "value", None)
        if name and value:
            parts.append(f"{name}: {value}")
        elif name or value:
            parts.append(str(name or value))
    footer = getattr(getattr(embed, "footer", None), "text", None)
    if footer:
        parts.append(str(footer))
    return "\n".join(parts)


def message_text(message) -> str:
    """Everything readable in the message: its text, forwarded text and embeds."""
    parts: List[str] = []
    content = getattr(message, "clean_content", None) or getattr(message, "content", None) or ""
    if content.strip():
        parts.append(content.strip())
    # A forwarded message carries its text in a snapshot, with empty content
    for snapshot in getattr(message, "message_snapshots", None) or []:
        text = (getattr(snapshot, "content", None) or "").strip()
        if text:
            parts.append(text)
    for embed in getattr(message, "embeds", None) or []:
        # Link previews (type "link"/"video"/...) repeat a web page, not the author's words
        if getattr(embed, "type", "rich") not in ("rich", None):
            continue
        text = _embed_text(embed).strip()
        if text:
            parts.append(text)
    return "\n".join(parts)


def _is_image(attachment) -> bool:
    content_type = (getattr(attachment, "content_type", None) or "").lower()
    if content_type:
        return content_type.startswith("image/")
    return (getattr(attachment, "filename", None) or "").lower().endswith(_IMAGE_EXTENSIONS)


def image_sources(message) -> list:
    """Every image of the message: attachment objects and embed image URLs."""
    found = [
        attachment for attachment in getattr(message, "attachments", None) or []
        if _is_image(attachment) and (getattr(attachment, "size", 0) or 0) <= MAX_IMAGE_BYTES
    ]
    for embed in getattr(message, "embeds", None) or []:
        # proxy_url: Discord's own copy. The original address is whatever the author
        # typed and is never fetched (see DiscordListener._fetch_image).
        url = getattr(getattr(embed, "image", None), "proxy_url", None)
        if not url and getattr(embed, "type", None) == "image":
            url = getattr(getattr(embed, "thumbnail", None), "proxy_url", None)
        if url:
            found.append(url)
    return found


def image_source(message):
    """The first image of the message, or None."""
    images = image_sources(message)
    return images[0] if images else None


def chat_title(message) -> str:
    channel = getattr(message, "channel", None)
    guild = getattr(message, "guild", None) or getattr(channel, "guild", None)
    name = getattr(channel, "name", None) or str(getattr(channel, "id", "?"))
    return f"{guild.name} #{name}" if guild is not None and getattr(guild, "name", None) else f"#{name}"


class _ImageMarker:
    """Stands in for Telethon's media object: truthy, and none of its media types."""
    photo = None
    document = None


_HAS_IMAGE = _ImageMarker()


class DiscordMessageAdapter:
    """One Discord message, read through the attribute names of a Telethon message."""

    grouped_id = None   # several images arrive in ONE message (see DiscordPipeline), not as an album
    fwd_from = None
    from_id = None

    def __init__(self, message, local_id: int, reply_to_local_id: Optional[int],
                 fetch_url: Callable[[str], Awaitable[Optional[bytes]]], title: str = "", own_user_id=None):
        self._message = message
        self._fetch_url = fetch_url
        self._images = image_sources(message)
        self._image = self._images[0] if self._images else None
        self._chat = SimpleNamespace(id=message.channel.id, title=title)
        # What the catch-up scan reads: has media / sent by us / a service notice
        self.media = _HAS_IMAGE if self._images else None
        self.out = own_user_id is not None and message.author.id == own_user_id
        kind = getattr(getattr(message, "type", None), "name", "default")
        self.action = None if kind in ("default", "reply") else kind
        self.id = local_id
        self.chat_id = message.channel.id
        self.text = message_text(message)
        self.date = message.created_at
        self.edit_date = getattr(message, "edited_at", None)
        self.sender_id = message.author.id
        self.sender = SimpleNamespace(
            username=getattr(message.author, "name", None),
            first_name=getattr(message.author, "display_name", None),
        )
        self.reply_to = SimpleNamespace(reply_to_msg_id=reply_to_local_id) if reply_to_local_id is not None else None
        self.photo = self._image is not None

    @property
    def image_count(self) -> int:
        return len(self._images)

    @property
    def message(self) -> str:
        """Telethon's raw-text attribute; the simulators read it."""
        return self.text

    async def get_chat(self):
        return self._chat

    async def _download(self, image) -> Optional[bytes]:
        if isinstance(image, str):
            return await self._fetch_url(image)
        return await image.read()

    async def download_media(self, _file=bytes) -> Optional[bytes]:
        return await self._download(self._image) if self._image is not None else None

    async def download_all(self) -> List[bytes]:
        images = []
        for image in self._images:
            try:
                data = await self._download(image)
            except Exception:
                data = None
            if data:
                images.append(data)
        return images


class DiscordEvent:
    """A new or edited Discord message as a Telethon-style event."""

    def __init__(self, adapter: DiscordMessageAdapter):
        self.message = adapter
        self.chat_id = adapter.chat_id
        self.get_chat = adapter.get_chat


class DiscordDeletedEvent:
    def __init__(self, chat_id: int, deleted_ids: List[int]):
        self.chat_id = chat_id
        self.deleted_ids = deleted_ids
