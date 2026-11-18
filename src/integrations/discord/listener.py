"""
Discord listener: a second signal source next to Telegram.

A Discord bot (token set in the dashboard) connects to the gateway and receives
the messages of every server it was invited to. Only the channels chosen in the
dashboard — a separate selection per server — are handed to the same message
pipeline Telegram uses (signals, replies, edits, deletions).

Everything is configured from the dashboard and applied live:
  DISCORD_ENABLED / DISCORD_BOT_TOKEN  -> settings table (token encrypted)
  monitored channels                   -> discord_channels table
"""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Awaitable, Callable, Dict, List, Optional
from urllib.parse import urlparse

from loguru import logger

from config import settings
from src.integrations.discord.events import (
    MAX_IMAGE_BYTES,
    DiscordDeletedEvent,
    DiscordEvent,
    DiscordMessageAdapter,
    chat_title,
)
from src.integrations.discord.store import discord_store
from src.utils.audit import audit
from src.utils.tasks import spawn

# View Channels + Read Message History: all the bot ever needs (it never writes).
INVITE_PERMISSIONS = 1024 + 65536
RETRY_SECONDS = 30
# Embed images are fetched only through Discord's own media proxy, never from the
# address a message author put in the embed (that could point inside our network).
_MEDIA_HOST_SUFFIXES = (".discordapp.net", ".discordapp.com", ".discord.com")

ACCOUNT_BOT = "bot"
ACCOUNT_USER = "user"   # the owner's personal account, through the worker process (user_client.py)

STATE_DISABLED = "disabled"
STATE_NO_TOKEN = "no_token"
STATE_CONNECTING = "connecting"
STATE_LIVE = "live"
STATE_ERROR = "error"


DISCORD_EPOCH_MS = 1420070400000


def snowflake_at(moment: datetime) -> int:
    """The smallest Discord id a message posted at `moment` can have."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return max(0, int(moment.timestamp() * 1000) - DISCORD_EPOCH_MS) << 22


def _type_name(message) -> str:
    kind = getattr(message, "type", None)
    return getattr(kind, "name", None) or str(kind)


class DiscordPipeline:
    """The message handler as Discord uses it. Identical to Telegram's except for one
    shape difference: Telegram delivers a multi-photo post as an album of separate
    messages, Discord as one message with several attachments. Such a message goes
    straight to the handler's album step, with all its images."""

    def __init__(self, handler_getter):
        self._handler = handler_getter

    def __getattr__(self, name):            # processed_message_ids, _is_plain_command, ...
        return getattr(self._handler(), name)

    async def process_message(self, event, signal_callback) -> bool:
        handler = self._handler()
        message = event.message
        if getattr(message, "image_count", 0) < 2:
            return await handler.process_message(event, signal_callback)
        from src.models.message import MessageIdentifier
        ident = MessageIdentifier.from_telegram_event(event)
        if ident.get_key() in handler.processed_message_ids:
            return False
        images = await message.download_all()
        if len(images) < 2:
            return await handler.process_message(event, signal_callback)
        handler.processed_message_ids.add(ident.get_key())
        await handler._process_album(
            {"event": event, "message_id": ident, "content": message.text or "", "images": images},
            signal_callback,
        )
        return True


class DiscordHistory:
    """Channel history in the form the catch-up service reads Telegram's
    (client.iter_messages(entity, min_id=, limit=), newest first)."""

    def __init__(self, listener):
        self._listener = listener

    async def iter_messages(self, entity, min_id=None, limit=1):
        import discord

        listener = self._listener
        client = listener.client
        channel = client.get_channel(entity.id) if client is not None and listener.state == STATE_LIVE else None
        if channel is None:
            return
        after = None
        if min_id is not None:
            snowflake = await listener.store.snowflake_for(min_id)
            if snowflake is None:
                return
            after = discord.Object(id=snowflake)
        newest_first = [m async for m in channel.history(limit=limit, after=after, oldest_first=False)]
        events = [await listener._event_for(m) for m in reversed(newest_first)]   # local ids in posting order
        for event in reversed(events):
            if min_id is None or event.message.id > min_id:
                yield event.message


class DiscordListener:
    def __init__(self, store=discord_store):
        self.store = store
        self.signal_callback: Optional[Callable[..., Awaitable[None]]] = None
        self.client = None
        self.state = STATE_DISABLED
        self.error: Optional[str] = None
        self.account: Optional[dict] = None
        self.started_at: Optional[datetime] = None
        self.last_message_at: Optional[datetime] = None
        self.last_message_by_channel: Dict[int, datetime] = {}
        self._monitored: Dict[int, dict] = {}
        self._applied: Optional[tuple] = None
        self._run_task: Optional[asyncio.Task] = None
        self._lifecycle_lock = asyncio.Lock()
        self._chat_locks: Dict[int, asyncio.Lock] = {}
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._inflight: set = set()
        self._http = None
        self.pipeline = DiscordPipeline(self._message_handler)
        self.history = DiscordHistory(self)
        self._catchup = None

    @staticmethod
    def _message_handler():
        from src.services import message_handler
        return message_handler.message_handler

    @property
    def catchup(self):
        """Telegram's catch-up service, a second instance for Discord (own cursors,
        own schedule) sharing the list of missed commands awaiting Apply / Skip."""
        if self._catchup is None:
            from src.services.catchup_service import CatchUpService, catchup_service
            self._catchup = CatchUpService(missed=catchup_service._missed)
        return self._catchup

    # ------------------------------------------------------------ lifecycle

    def configure(self, signal_callback) -> None:
        self.signal_callback = signal_callback

    async def apply_settings(self) -> None:
        """Start, stop or reconnect so the listener matches the dashboard settings.
        Never raises: Discord is optional and must not take the bot down with it."""
        if self.signal_callback is None:
            return  # bot still starting; main.py calls this again once it is ready
        try:
            await self._apply_settings()
        except Exception as e:
            self.state = STATE_ERROR
            self.error = f"Could not start: {str(e)[:200]}"
            logger.error(f"🎮 Discord listener could not start: {e}")

    async def _apply_settings(self) -> None:
        async with self._lifecycle_lock:
            enabled = bool(getattr(settings, "discord_enabled", False))
            account_type = self.account_type()
            token = self._token(account_type)
            running = self._run_task is not None and not self._run_task.done()
            if (enabled, account_type, token) == self._applied and (running or not (enabled and token)):
                return
            await self._shutdown()
            self._applied = (enabled, account_type, token)
            self.error = None
            try:
                await self.refresh_channels()  # also while off: the dashboard still lists the selection
            except Exception as e:
                # e.g. the discord tables do not exist yet (migration not applied)
                self._monitored = {}
                logger.warning(f"🎮 Discord: could not load the channel selection: {e}")
            if not enabled:
                self.state = STATE_DISABLED
                logger.info("🎮 Discord listener is switched off")
                return
            if not token:
                self.state = STATE_NO_TOKEN
                logger.warning("🎮 Discord listener is on but no token is set (dashboard → Discord)")
                return
            self.state = STATE_CONNECTING
            self._run_task = spawn(self._run(token, account_type), name="discord_listener")

    @staticmethod
    def account_type() -> str:
        value = str(getattr(settings, "discord_account_type", "") or "").strip().lower()
        return ACCOUNT_USER if value == ACCOUNT_USER else ACCOUNT_BOT

    @staticmethod
    def _token(account_type: str) -> str:
        attr = "discord_user_token" if account_type == ACCOUNT_USER else "discord_bot_token"
        return (getattr(settings, attr, None) or "").strip()

    def monitored_ids(self) -> list:
        return list(self._monitored)

    async def stop(self) -> None:
        async with self._lifecycle_lock:
            await self._shutdown()
            self._applied = None
            self.state = STATE_DISABLED
            if self._catchup is not None:
                try:
                    await self._catchup.stop()   # persists the last message cursors
                except Exception as e:
                    logger.debug(f"Discord catch-up stop: {e}")

    async def _shutdown(self) -> None:
        task, client = self._run_task, self.client
        self._run_task = None
        self.client = None
        self.account = None
        if client is not None:
            try:
                await client.close()
            except Exception as e:
                logger.debug(f"Discord: close failed: {e}")
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        if self._http is not None:
            await self._http.close()
            self._http = None

    def _build_client(self, account_type: str = ACCOUNT_BOT):
        if account_type == ACCOUNT_USER:
            from src.integrations.discord.user_client import DiscordUserClient
            return DiscordUserClient(self)
        import discord

        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.message_content = True  # privileged: must be switched on in the Developer Portal
        client = discord.Client(intents=intents)
        listener = self

        @client.event
        async def on_ready():
            await listener._on_ready(client)

        @client.event
        async def on_message(message):
            listener.handle_message(message)

        @client.event
        async def on_raw_message_edit(payload):
            listener.handle_raw_edit(payload)

        @client.event
        async def on_raw_message_delete(payload):
            listener.handle_raw_delete(payload.channel_id, [payload.message_id])

        @client.event
        async def on_raw_bulk_message_delete(payload):
            listener.handle_raw_delete(payload.channel_id, list(payload.message_ids))

        return client

    async def _run(self, token: str, account_type: str = ACCOUNT_BOT) -> None:
        """Keep one connection alive. The client reconnects by itself after network
        drops; this loop only handles a connection that could not be made (or a worker
        process that stopped)."""
        while True:
            try:
                client = self._build_client(account_type)
            except ImportError:
                self._fail("discord.py is not installed in the bot image — rebuild the bot container")
                return
            self.client = client
            self.state = STATE_CONNECTING
            try:
                await client.start(token)
                return  # closed on purpose
            except asyncio.CancelledError:
                raise
            except Exception as e:
                fatal = self._fatal_reason(e, account_type)
                if fatal:
                    self._fail(fatal)
                    return
                self.state = STATE_ERROR
                self.error = f"Connection failed: {str(e)[:200]} — retrying every {RETRY_SECONDS}s"
                logger.error(f"🎮 Discord connection failed: {e}")
            finally:
                if not client.is_closed():
                    try:
                        await client.close()
                    except Exception as e:
                        logger.debug(f"Discord: close failed: {e}")
            await asyncio.sleep(RETRY_SECONDS)

    @staticmethod
    def _fatal_reason(error: Exception, account_type: str) -> Optional[str]:
        """A message for failures that retrying cannot fix; None for the ones it can."""
        if account_type == ACCOUNT_USER:
            from src.integrations.discord.user_client import UserLoginFailure, UserModeUnavailable
            if isinstance(error, UserLoginFailure):
                return ("Discord rejected the account token — it changes when you change your password or log "
                        "out everywhere. Copy the current one and save it again")
            if isinstance(error, UserModeUnavailable):
                return str(error)
            return None
        import discord
        if isinstance(error, discord.LoginFailure):
            return "Discord rejected the bot token — paste the current token from the Developer Portal (Bot → Reset Token)"
        if isinstance(error, discord.PrivilegedIntentsRequired):
            return ("Switch on “Message Content Intent” for the bot (Developer Portal → your app → Bot → "
                    "Privileged Gateway Intents), then press Reconnect")
        return None

    def _fail(self, message: str) -> None:
        self.state = STATE_ERROR
        self.error = message
        logger.error(f"🎮 Discord listener stopped: {message}")
        audit("ERROR", f"Discord listener stopped: {message}", "HIGH", module="discord_listener")

    async def _on_ready(self, client) -> None:
        if client is not self.client:
            return
        user = client.user
        self.account = {"id": str(user.id), "name": str(user)}
        self.state = STATE_LIVE
        self.error = None
        self.started_at = self.started_at or datetime.now(timezone.utc)
        logger.success(f"🎮 Discord connected as {user} — in {len(client.guilds)} server(s), "
                       f"listening to {len(self._monitored)} channel(s)")
        for channel_id, row in self._monitored.items():
            channel = client.get_channel(channel_id)
            if channel is not None:
                name, guild_name = channel.name, channel.guild.name
                if (name, guild_name) != (row.get("channelName"), row.get("guildName")):
                    row.update(channelName=name, guildName=guild_name)
                    await self.store.rename(str(channel_id), name, guild_name)
        self._start_catchup()

    def _catchup_entities(self) -> list:
        return [
            SimpleNamespace(id=channel_id, title=f"{row.get('guildName') or 'Discord'} #{row.get('channelName') or channel_id}")
            for channel_id, row in self._monitored.items()
        ]

    def _start_catchup(self) -> None:
        """Same as Telegram: fresh missed messages are processed, expired signals are
        reported in one digest, missed commands wait for Apply / Skip. Runs after every
        (re)connect and then periodically."""
        try:
            spawn(self.catchup.run(self.history, self._catchup_entities(), self.signal_callback,
                                   self._spawn_ordered, self.pipeline), name="discord_catchup")
            self.catchup.start_periodic(self.history, self._catchup_entities, self.signal_callback,
                                        self._spawn_ordered, self.pipeline)
        except Exception as e:
            logger.warning(f"🎮 Discord: could not start catch-up: {e}")

    # ------------------------------------------------------------ channels

    async def refresh_channels(self) -> int:
        """Reload the monitored channels from the database (after a dashboard change)."""
        rows = await self.store.monitored_channels()
        self._monitored = {int(r["channelId"]): r for r in rows}
        watch = getattr(self.client, "watch", None)   # own-account worker: forwards only these
        if watch is not None:
            watch(self.monitored_ids())
        return len(self._monitored)

    def _channel_problem(self, channel_id: int) -> Optional[str]:
        client = self.client
        if client is None or self.state != STATE_LIVE:
            return None
        channel = client.get_channel(channel_id)
        if channel is None:
            return "The bot cannot see this channel any more (removed from the server, or the channel was deleted)"
        perms = channel.permissions_for(channel.guild.me)
        who = "Your account" if self.account_type() == ACCOUNT_USER else "The bot's role"
        if not perms.view_channel:
            return f"{who} has no “View Channel” permission here"
        if not perms.read_message_history:
            return f"{who} has no “Read Message History” permission here"
        return None

    def guilds(self) -> List[dict]:
        """Servers the bot is in, with their text channels, for the dashboard picker."""
        client = self.client
        if client is None or self.state != STATE_LIVE:
            return []
        result = []
        for guild in sorted(client.guilds, key=lambda g: g.name.lower()):
            channels = []
            ordered = sorted(
                guild.text_channels,
                key=lambda c: (c.category.position if c.category else -1, c.position),
            )
            for channel in ordered:
                perms = channel.permissions_for(guild.me)
                channels.append({
                    "id": str(channel.id),
                    "name": channel.name,
                    "category": channel.category.name if channel.category else None,
                    "readable": bool(perms.view_channel and perms.read_message_history),
                    "monitored": channel.id in self._monitored,
                })
            result.append({
                "id": str(guild.id),
                "name": guild.name,
                "icon": guild.icon.url if guild.icon else None,
                "channels": channels,
            })
        return result

    def channel_names(self, guild_id: str, channel_ids: List[str]) -> Optional[dict]:
        """{"name": guild name, "channels": [{"id", "name"}]} for ids that belong to that
        server and are text channels; None when the bot is not in the server."""
        client = self.client
        guild = client.get_guild(int(guild_id)) if client is not None and guild_id.isdigit() else None
        if guild is None:
            return None
        by_id = {str(c.id): c for c in guild.text_channels}
        return {
            "name": guild.name,
            "channels": [{"id": cid, "name": by_id[cid].name} for cid in channel_ids if cid in by_id],
        }

    def invite_url(self) -> Optional[str]:
        app_id = getattr(self.client, "application_id", None) if self.client is not None else None
        if not app_id:
            return None
        return (f"https://discord.com/oauth2/authorize?client_id={app_id}"
                f"&scope=bot&permissions={INVITE_PERMISSIONS}")

    def status(self) -> dict:
        def iso(dt):
            return dt.astimezone(timezone.utc).isoformat() if dt else None

        client = self.client
        channels = []
        for channel_id, row in self._monitored.items():
            channels.append({
                "id": str(channel_id),
                "name": row.get("channelName"),
                "guildId": row.get("guildId"),
                "guildName": row.get("guildName"),
                "lastMessageAt": iso(self.last_message_by_channel.get(channel_id)),
                "problem": self._channel_problem(channel_id),
            })
        return {
            "enabled": bool(getattr(settings, "discord_enabled", False)),
            "accountType": self.account_type(),
            "tokenSet": bool(self._token(self.account_type())),
            "botTokenSet": bool(self._token(ACCOUNT_BOT)),
            "userTokenSet": bool(self._token(ACCOUNT_USER)),
            "state": self.state,
            "error": self.error,
            "account": self.account,
            "inviteUrl": self.invite_url(),
            "guildCount": len(client.guilds) if client is not None and self.state == STATE_LIVE else 0,
            "listeningSince": iso(self.started_at) if self.state == STATE_LIVE else None,
            "lastMessageAt": iso(self.last_message_at),
            "inflight": len(self._inflight),
            "channels": channels,
        }

    # ------------------------------------------------------------ message flow

    def _spawn_ordered(self, channel_id: int, make_coro) -> None:
        """Messages of one channel are handled strictly in arrival order (a signal and
        its reply seconds later must not race); different channels run in parallel."""
        task = asyncio.create_task(self._run_ordered(channel_id, make_coro))
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _run_ordered(self, channel_id: int, make_coro) -> None:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(max(1, int(getattr(settings, "message_processing_concurrency", 4))))
        lock = self._chat_locks.setdefault(channel_id, asyncio.Lock())
        async with lock:
            async with self._semaphore:
                try:
                    await make_coro()
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"❌ Discord message processing failed: {e}")
                    audit("ERROR", f"Discord message processing failed in channel {channel_id}: {str(e)[:200]}",
                          "HIGH", module="discord_listener")

    def _wanted(self, message) -> bool:
        if message.channel.id not in self._monitored:
            return False
        me = getattr(self.client, "user", None)
        if me is not None and message.author.id == me.id:
            return False
        # Joins, pins, boosts and other system notices are not posts
        return _type_name(message) in ("default", "reply")

    def handle_message(self, message) -> bool:
        """Gateway MESSAGE_CREATE. Returns whether the message was queued."""
        if not self._wanted(message):
            return False
        channel_id = message.channel.id
        now = datetime.now(timezone.utc)
        self.last_message_at = now
        self.last_message_by_channel[channel_id] = now
        logger.info(f"🔔 NEW DISCORD MESSAGE in {chat_title(message)} ({channel_id})")
        self._spawn_ordered(channel_id, lambda: self._process_new(message))
        return True

    async def _event_for(self, message) -> DiscordEvent:
        channel_id = message.channel.id
        local_id = await self.store.local_id(channel_id, message.id)
        reply_local_id = None
        reference = getattr(message, "reference", None)
        if _type_name(message) == "reply" and reference is not None and getattr(reference, "message_id", None):
            reply_local_id = await self.store.local_id(
                getattr(reference, "channel_id", None) or channel_id, reference.message_id
            )
        me = getattr(self.client, "user", None)
        adapter = DiscordMessageAdapter(message, local_id, reply_local_id, self._fetch_image,
                                        title=chat_title(message), own_user_id=getattr(me, "id", None))
        return DiscordEvent(adapter)

    async def _process_new(self, message) -> None:
        event = await self._event_for(message)
        try:
            await self.pipeline.process_message(event, self.signal_callback)
        finally:
            # Handled (or failed): the catch-up cursor moves past it, as for Telegram
            self.catchup.note_processed(event.chat_id, event.message.id, event.message.date)

    def handle_raw_edit(self, payload) -> bool:
        """Gateway MESSAGE_UPDATE. Discord also sends it when a link preview loads; only
        an update that carries an edit time is somebody changing the text."""
        if payload.channel_id not in self._monitored or not (payload.data or {}).get("edited_timestamp"):
            return False
        self._spawn_ordered(payload.channel_id, lambda: self._process_edit(payload))
        return True

    async def _process_edit(self, payload) -> None:
        from src.services.message_handler import message_handler
        if await self.store.known_local_id(payload.message_id) is None:
            return  # posted before this channel was monitored: nothing of ours to update
        message = getattr(payload, "message", None)
        if message is None:
            channel = self.client.get_channel(payload.channel_id) if self.client is not None else None
            if channel is None:
                return
            message = await channel.fetch_message(payload.message_id)
        if not self._wanted(message):
            return
        logger.info(f"✏️ DISCORD MESSAGE EDITED in {chat_title(message)}")
        event = await self._event_for(message)
        if event.message.edit_date is None:
            event.message.edit_date = datetime.now(timezone.utc)
        await message_handler.process_edited_message(event, self.signal_callback)

    def handle_raw_delete(self, channel_id: int, message_ids: List[int]) -> bool:
        if channel_id not in self._monitored or not message_ids:
            return False
        self._spawn_ordered(channel_id, lambda: self._process_delete(channel_id, message_ids))
        return True

    async def _process_delete(self, channel_id: int, message_ids: List[int]) -> None:
        from src.services.message_handler import message_handler
        known = await self.store.known_local_ids(message_ids)
        if not known:
            return
        logger.info(f"🗑️ DISCORD MESSAGE(S) DELETED in channel {channel_id}: {sorted(known.values())}")
        await message_handler.process_deleted_messages(DiscordDeletedEvent(channel_id, list(known.values())))

    # ------------------------------------------------------------ simulators

    def replay_channels(self) -> List[dict]:
        """The channels selected for listening, for the simulators' channel list — not
        every channel of every server, which would bury the list. `group` is the header
        they are shown under (server and category: two categories of one server often
        have channels with the same name)."""
        channels = []
        for guild in self.guilds():
            for channel in guild["channels"]:
                if not channel["monitored"]:
                    continue
                group = " · ".join(part for part in (guild["name"], channel["category"]) if part)
                channels.append({
                    "id": channel["id"],
                    "name": f"{group} #{channel['name']}",
                    "label": f"#{channel['name']}",
                    "group": group,
                })
        return channels

    async def replay_messages(self, channel_id, start: datetime, end: datetime, limit: int) -> list:
        """A channel's posts between `start` and `end` (the newest `limit` of them), oldest
        first, in the Telegram message shape the simulators read. Nothing is stored: ids
        are simply 1..n in posting order, which is all a replay needs."""
        import discord

        client = self.client
        if client is None or self.state != STATE_LIVE:
            raise RuntimeError("Discord is not connected — the replay reads the channel through that connection.")
        channel = client.get_channel(int(channel_id))
        if channel is None:
            raise RuntimeError("That Discord channel is not visible to the connected account.")
        raw = [m async for m in channel.history(
            limit=limit, before=discord.Object(id=snowflake_at(end)), after=discord.Object(id=snowflake_at(start)),
            oldest_first=False)]
        raw.reverse()
        ids = {m.id: index for index, m in enumerate(raw, 1)}
        me = getattr(client, "user", None)
        messages = []
        for message in raw:
            if _type_name(message) not in ("default", "reply"):
                continue
            reply_id = None
            reference = getattr(message, "reference", None)
            if _type_name(message) == "reply" and reference is not None and getattr(reference, "message_id", None):
                # a reply to a post from before the period still needs an id of its own
                reply_id = ids.setdefault(reference.message_id, len(ids) + 1)
            messages.append(DiscordMessageAdapter(message, ids[message.id], reply_id, self._fetch_image,
                                                  title=chat_title(message), own_user_id=getattr(me, "id", None)))
        return messages

    async def _fetch_image(self, url: str) -> Optional[bytes]:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not host.endswith(_MEDIA_HOST_SUFFIXES):
            logger.debug(f"Discord: embed image not on Discord's media hosts — skipped ({host})")
            return None
        import aiohttp

        if self._http is None:
            self._http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20), trust_env=True)
        async with self._http.get(url, allow_redirects=False) as response:
            if response.status != 200:
                return None
            data = bytearray()
            async for chunk in response.content.iter_chunked(64 * 1024):
                data.extend(chunk)
                if len(data) > MAX_IMAGE_BYTES:
                    return None
            return bytes(data)


discord_listener = DiscordListener()
