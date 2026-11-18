"""
Catch-up after downtime.

Telegram only pushes live updates, so anything posted while the bot was offline (restart, crash,
network drop, lost update) is silently missed. This service:

  * remembers the last message the bot finished handling per monitored channel (ChannelCursor),
  * after startup, and periodically, fetches what is newer than that cursor,
  * replays messages that are still fresh (within MAX_SIGNAL_AGE_MINUTES) through the normal pipeline,
  * NEVER auto-trades older signals - they are reported as expired in one Telegram digest,
  * offers missed management commands ("close all", replies to a trade...) with Apply / Skip buttons,
    so an old command is only executed after you confirm it.

The first time a channel is seen no history is processed: the cursor is simply set to the newest message.
"""
import asyncio
import time
import uuid
from datetime import datetime, timezone
from html import escape
from types import SimpleNamespace
from typing import Awaitable, Callable, Dict, List, Optional

from loguru import logger

from config import settings
from src.core.database_service import db_service
from src.utils.audit import audit
from src.utils.tasks import spawn

CURSOR_FLUSH_SECONDS = 10.0
MAX_COMMAND_BUTTONS = 5
COMMAND_TTL_MINUTES = 60


class MissedCommand:
    def __init__(self, item_id: str, channel: str, text: str, age_minutes: int, run: Callable[[], Awaitable]):
        self.item_id, self.channel, self.text, self.age_minutes, self.run = item_id, channel, text, age_minutes, run
        self.created = time.monotonic()

    def expired(self) -> bool:
        return time.monotonic() - self.created > COMMAND_TTL_MINUTES * 60


class CatchUpService:
    def __init__(self, missed: Optional[Dict[str, MissedCommand]] = None):
        self._cursors: Dict[str, tuple] = {}      # channel -> (message_id, message_at) not yet persisted
        self._persisted: Dict[str, int] = {}      # channel -> id already written
        self._flush_task: Optional[asyncio.Task] = None
        self._periodic_task: Optional[asyncio.Task] = None
        # Another source (Discord) runs its own instance but shares this dict, so the
        # Apply / Skip buttons find a missed command whichever source it came from.
        self._missed: Dict[str, MissedCommand] = {} if missed is None else missed
        self._running_catchup = asyncio.Lock()

    # ── cursor bookkeeping ───────────────────────────────────────────────

    def note_processed(self, chat_id, message_id: int, message_at: Optional[datetime] = None) -> None:
        """Called after a message has been handled (successfully or not): the cursor only moves forward."""
        key = str(chat_id)
        cur = self._cursors.get(key)
        if cur is None or int(message_id) > cur[0]:
            self._cursors[key] = (int(message_id), message_at)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return  # no loop (script/test): the next flush() persists it
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = spawn(self._flush_soon(), name="catchup_cursor_flush")

    async def _flush_soon(self) -> None:
        await asyncio.sleep(CURSOR_FLUSH_SECONDS)
        await self.flush()

    async def flush(self) -> None:
        """Persist cursors that advanced since the last flush."""
        for key, (mid, at) in list(self._cursors.items()):
            if self._persisted.get(key, 0) >= mid:
                continue
            await db_service.set_channel_cursor(key, mid, at)
            self._persisted[key] = mid

    async def _cursor(self, key: str) -> Optional[int]:
        pending = self._cursors.get(key)
        stored = await db_service.get_channel_cursor(key)
        candidates = [x for x in (stored, pending[0] if pending else None) if x is not None]
        return max(candidates) if candidates else None

    # ── scanning ─────────────────────────────────────────────────────────

    async def run(self, client, entities, signal_callback, spawn_ordered, handler) -> dict:
        """
        One catch-up pass over all monitored channels. `spawn_ordered(chat_id, make_coro)` schedules
        a handler in channel order; `handler` is the message handler (process_message, dedupe set).
        Returns a summary dict (also used by tests).
        """
        if not getattr(settings, "catchup_enabled", True):
            return {"skipped": "disabled"}
        if self._running_catchup.locked():
            return {"skipped": "already running"}
        async with self._running_catchup:
            summary = {"replayed": 0, "expired_signals": 0, "commands": 0, "other": 0, "channels": 0}
            digest_lines: List[str] = []
            await self.flush()
            for entity in entities:
                try:
                    await self._scan_channel(client, entity, signal_callback, spawn_ordered, handler, summary, digest_lines)
                except Exception as e:
                    logger.warning(f"Catch-up failed for {getattr(entity, 'id', '?')}: {e}")
                    audit("WARNING", f"Catch-up failed for channel {getattr(entity, 'id', '?')}: {str(e)[:150]}", "MEDIUM",
                          module="catchup")
            if digest_lines:
                await self._send_digest(digest_lines, summary)
            logger.info(f"📬 Catch-up done: {summary}")
            return summary

    async def _scan_channel(self, client, entity, signal_callback, spawn_ordered, handler, summary, digest_lines):
        key = self._peer_key(entity)
        title = getattr(entity, "title", None) or getattr(entity, "first_name", None) or key
        cursor = await self._cursor(key)
        cap = max(1, int(getattr(settings, "catchup_max_messages", 50)))

        if cursor is None:
            # first sight of this channel: no history replay, just remember where we are
            newest = None
            async for m in client.iter_messages(entity, limit=1):
                newest = m
            if newest is not None:
                self.note_processed(key, newest.id, newest.date)
            return

        fetched = []
        async for m in client.iter_messages(entity, min_id=cursor, limit=cap + 1):   # newest first
            fetched.append(m)
        if not fetched:
            return
        overflow = len(fetched) > cap
        fetched = list(reversed(fetched[:cap]))                                        # oldest -> newest
        summary["channels"] += 1

        max_age = float(getattr(settings, "max_signal_age_minutes", 5))
        now = datetime.now(timezone.utc)
        channel_lines: List[str] = []
        for m in fetched:
            mid = m.id
            text = (getattr(m, "text", None) or "").strip()
            has_media = bool(getattr(m, "media", None))
            if getattr(m, "out", False) or getattr(m, "action", None) is not None or not (text or has_media):
                self.note_processed(key, mid, m.date)
                continue
            if f"{key}:{mid}" in handler.processed_message_ids:
                continue                                                               # live path already got it
            age_min = (now - m.date).total_seconds() / 60 if m.date else 9999

            event = SimpleNamespace(message=m, chat_id=m.chat_id, get_chat=m.get_chat)
            if age_min <= max_age:
                summary["replayed"] += 1
                spawn_ordered(m.chat_id, self._replay(handler, event, signal_callback, key, m))
                continue

            kind = self._classify(handler, m, text, bool(has_media))
            preview = escape(text[:110] + ("…" if len(text) > 110 else "")) or "(image)"
            when = f"{int(age_min)} min ago" if age_min < 120 else f"{age_min / 60:.1f} h ago"
            if kind == "command":
                summary["commands"] += 1
                item_id = uuid.uuid4().hex[:12]
                self._missed[item_id] = MissedCommand(
                    item_id, str(title), text, int(age_min),
                    self._replay(handler, event, signal_callback, key, m),
                )
                channel_lines.append(f"• <b>command</b> ({when}): {preview}  — see buttons below")
            elif kind == "signal":
                summary["expired_signals"] += 1
                channel_lines.append(f"• <b>expired signal</b> ({when}): {preview}")
            else:
                summary["other"] += 1
            self.note_processed(key, mid, m.date)

        if channel_lines or overflow:
            extra = " (more older messages were not checked)" if overflow else ""
            digest_lines.append(f"📡 <b>{escape(str(title))}</b>{extra}\n" + "\n".join(channel_lines[:8]))

    @staticmethod
    def _peer_key(entity) -> str:
        """The id form Telegram messages carry in message.chat_id (channels: -100…)."""
        try:
            from telethon import utils
            return str(utils.get_peer_id(entity))
        except Exception:
            return str(entity.id)

    @staticmethod
    def _classify(handler, m, text: str, has_media: bool) -> str:
        """command | signal | other - cheap, no AI."""
        from src.services.signal_service import signal_service
        is_reply = getattr(m, "reply_to", None) is not None
        if text and (is_reply or handler._is_plain_command(text)) and len(text) >= 3:
            return "command"
        if signal_service.is_potential_signal(text, has_image=has_media):
            return "signal"
        return "other"

    def _replay(self, handler, event, signal_callback, key, m):
        async def go():
            try:
                await handler.process_message(event, signal_callback)
            finally:
                self.note_processed(key, m.id, m.date)
        return go

    # ── Telegram interaction ─────────────────────────────────────────────

    async def _send_digest(self, lines: List[str], summary: dict) -> None:
        from src.integrations.telegram.unified_sender import notification_sender
        head = (f"📬 <b>Missed while offline</b>\n"
                f"{summary['replayed']} fresh message(s) processed now · {summary['expired_signals']} expired signal(s) "
                f"(not traded) · {summary['commands']} command(s) waiting for you\n\n")
        await notification_sender.send_message(head + "\n\n".join(lines)[:3500])   # unfiltered: missed trades matter
        audit("WARNING", "Missed messages detected after downtime", "MEDIUM", dict(summary), module="catchup")
        for item in list(self._missed.values())[:MAX_COMMAND_BUTTONS]:
            await notification_sender.notify_missed_command(item.item_id, item.channel, item.text, item.age_minutes)

    async def apply(self, item_id: str) -> tuple:
        item = self._missed.pop(item_id, None)
        if item is None or item.expired():
            return False, "That missed command is no longer available (already handled or expired)."
        try:
            await item.run()
            return True, f"Applied: {escape(item.text[:80])}"
        except Exception as e:
            logger.error(f"Missed command failed: {e}")
            return False, f"It didn't go through: {escape(str(e)[:120])}"

    def skip(self, item_id: str) -> bool:
        return self._missed.pop(item_id, None) is not None

    # ── lifecycle ────────────────────────────────────────────────────────

    def start_periodic(self, client, entities_getter, signal_callback, spawn_ordered, handler) -> None:
        minutes = float(getattr(settings, "catchup_interval_minutes", 10) or 0)
        if minutes <= 0 or (self._periodic_task and not self._periodic_task.done()):
            return

        async def loop():
            while True:
                await asyncio.sleep(minutes * 60)
                try:
                    await self.run(client, entities_getter(), signal_callback, spawn_ordered, handler)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.warning(f"Periodic catch-up failed: {e}")

        self._periodic_task = spawn(loop(), name="catchup_periodic")

    async def stop(self) -> None:
        if self._periodic_task:
            self._periodic_task.cancel()
        await self.flush()


catchup_service = CatchUpService()
