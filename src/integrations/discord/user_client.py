"""
The bot's side of the "own account" worker (user_worker.py).

DiscordUserClient offers the part of discord.Client that DiscordListener uses
(start / close, guilds and their text channels, channel history, and the
message / edit / delete callbacks), backed by the worker process. Messages
arrive as JSON and are rebuilt into objects with the attribute names the
adapter in events.py reads, so the listener and everything after it are the same
in both modes.
"""
import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Optional

from loguru import logger

WORKER_SCRIPT = Path(__file__).with_name("user_worker.py")
# Built into the bot image (Dockerfile). Only the location of an interpreter, not a setting.
WORKER_PYTHON = os.environ.get("DISCORD_USER_PYTHON", "/opt/discord-user/bin/python")
HISTORY_TIMEOUT_S = 30
PIPE_LIMIT = 32 * 1024 * 1024   # one line can carry the channel list of every server


class UserLoginFailure(Exception):
    """Discord rejected the account token."""


class UserModeUnavailable(Exception):
    """The worker cannot run in this image."""


def _when(value) -> Optional[datetime]:
    return datetime.fromisoformat(value) if value else None


class _Channel:
    def __init__(self, client, guild, data: dict):
        self._client = client
        self.guild = guild
        self.id = int(data["id"])
        self.name = data["name"]
        self.position = data.get("position", 0)
        self.category = (SimpleNamespace(name=data["category"], position=data.get("category_position", 0))
                         if data.get("category") else None)
        self._readable = bool(data.get("readable", True))

    def permissions_for(self, _member):
        return SimpleNamespace(view_channel=self._readable, read_message_history=self._readable)

    def history(self, limit=1, after=None, before=None, oldest_first=False):
        return self._client._history(self, limit, getattr(after, "id", None), oldest_first,
                                     getattr(before, "id", None))


class _Guild:
    me = None

    def __init__(self, client, data: dict):
        self.id = int(data["id"])
        self.name = data["name"]
        self.icon = SimpleNamespace(url=data["icon"]) if data.get("icon") else None
        self.text_channels = [_Channel(client, self, c) for c in data.get("channels", [])]


class DiscordUserClient:
    application_id = None   # no invite link: the account is already a member

    def __init__(self, listener):
        self._listener = listener
        self._process: Optional[asyncio.subprocess.Process] = None
        self._closed = False
        self._requests: Dict[int, asyncio.Future] = {}
        self._next_request = 0
        self.user = None
        self.guilds: List[_Guild] = []
        self._channels: Dict[int, _Channel] = {}

    # ------------------------------------------------------------ discord.Client surface

    def is_closed(self) -> bool:
        return self._closed

    def get_channel(self, channel_id: int):
        return self._channels.get(int(channel_id))

    def get_guild(self, guild_id: int):
        return next((g for g in self.guilds if g.id == int(guild_id)), None)

    async def start(self, token: str) -> None:
        """Run the worker until close(). Raises when it fails or exits by itself."""
        if not Path(WORKER_PYTHON).exists():
            raise UserModeUnavailable(
                "Own-account mode is not installed in this bot image — rebuild the bot container")
        self._process = await asyncio.create_subprocess_exec(
            WORKER_PYTHON, str(WORKER_SCRIPT),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            limit=PIPE_LIMIT,
        )
        self._send({"token": token})
        errors: List[str] = []
        drain = asyncio.ensure_future(self._drain_stderr(errors))
        fatal: Optional[dict] = None
        try:
            while True:
                line = await self._process.stdout.readline()
                if not line:
                    break
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get("t") == "fatal":
                    fatal = event
                    break
                try:
                    await self._dispatch(event)
                except Exception as e:
                    logger.error(f"🎮 Discord (own account): could not handle a worker event: {e}")
        finally:
            await self._terminate()
            drain.cancel()
            for future in self._requests.values():
                if not future.done():
                    future.set_result([])
            self._requests.clear()
        if self._closed and fatal is None:
            return
        if fatal and fatal.get("code") == "login_failed":
            raise UserLoginFailure(fatal.get("error") or "login failed")
        if fatal and fatal.get("code") == "not_installed":
            raise UserModeUnavailable("Own-account mode is not installed in this bot image — rebuild the bot container")
        detail = (fatal or {}).get("error") or (errors[-1] if errors else "the worker stopped")
        raise ConnectionError(detail)

    async def close(self) -> None:
        self._closed = True
        await self._terminate()

    # ------------------------------------------------------------ worker plumbing

    def _send(self, obj) -> None:
        process = self._process
        if process is None or process.stdin is None or process.stdin.is_closing():
            return
        process.stdin.write((json.dumps(obj, separators=(",", ":")) + "\n").encode())

    async def _terminate(self) -> None:
        process = self._process
        if process is None or process.returncode is not None:
            return
        try:
            if process.stdin is not None and not process.stdin.is_closing():
                process.stdin.close()             # the worker stops when its stdin ends
            await asyncio.wait_for(process.wait(), timeout=5)
        except (asyncio.TimeoutError, ProcessLookupError, ConnectionError):
            try:
                process.kill()
                await process.wait()
            except ProcessLookupError:
                pass

    async def _drain_stderr(self, errors: List[str]) -> None:
        while True:
            line = await self._process.stderr.readline()
            if not line:
                return
            text = line.decode(errors="replace").rstrip()
            if text:
                errors.append(text[:300])
                del errors[:-20]
                logger.debug(f"🎮 discord worker: {text[:300]}")

    def watch(self, channel_ids) -> None:
        """Tell the worker which channels to forward (everything else stays in the worker)."""
        self._send({"cmd": "watch", "channels": [str(c) for c in channel_ids]})

    def _set_guilds(self, guilds: list) -> None:
        self.guilds = [_Guild(self, g) for g in guilds]
        self._channels = {c.id: c for g in self.guilds for c in g.text_channels}

    async def _dispatch(self, event: dict) -> None:
        kind = event.get("t")
        listener = self._listener
        if kind == "ready":
            user = event["user"]
            self.user = _User(int(user["id"]), user["name"])
            self._set_guilds(event.get("guilds", []))
            self.watch(listener.monitored_ids())
            await listener._on_ready(self)
        elif kind == "guilds":
            self._set_guilds(event.get("guilds", []))
        elif kind == "message":
            listener.handle_message(self._message(event["m"]))
        elif kind == "edit":
            message = self._message(event["m"])
            listener.handle_raw_edit(SimpleNamespace(
                channel_id=message.channel.id, message_id=message.id, message=message,
                data={"edited_timestamp": event["m"].get("edited_at") or "edited"},
            ))
        elif kind == "delete":
            listener.handle_raw_delete(int(event["channel_id"]), [int(i) for i in event.get("ids", [])])
        elif kind == "history":
            future = self._requests.pop(event.get("req"), None)
            if future is not None and not future.done():
                future.set_result(event.get("messages", []))

    async def _history(self, channel, limit, after_id, oldest_first, before_id=None):
        self._next_request += 1
        request = self._next_request
        future = asyncio.get_running_loop().create_future()
        self._requests[request] = future
        self._send({"cmd": "history", "req": request, "channel_id": str(channel.id),
                    "after": str(after_id) if after_id else None,
                    "before": str(before_id) if before_id else None, "limit": limit})
        try:
            raw = await asyncio.wait_for(future, HISTORY_TIMEOUT_S)
        except asyncio.TimeoutError:
            self._requests.pop(request, None)
            raw = []
        messages = [self._message(m) for m in raw]          # newest first, as requested from Discord
        for message in (reversed(messages) if oldest_first else messages):
            yield message

    # ------------------------------------------------------------ JSON -> message objects

    def _message(self, data: dict):
        channel = self._channels.get(int(data["channel_id"]))
        if channel is None:   # not in the last snapshot (just created): enough for ids and the title
            guild = SimpleNamespace(id=int(data["guild_id"] or 0), name=data.get("guild_name"))
            channel = SimpleNamespace(id=int(data["channel_id"]), name=data.get("channel_name"), guild=guild)
        author = data.get("author") or {}
        reference = data.get("reference")
        fetch = self._listener._fetch_image

        def attachment(item):
            async def read():
                return await fetch(item["url"])
            return SimpleNamespace(url=item["url"], content_type=item.get("content_type"),
                                   filename=item.get("filename"), size=item.get("size") or 0, read=read)

        def embed(item):
            return SimpleNamespace(
                type=item.get("type") or "rich",
                author=SimpleNamespace(name=item.get("author")),
                title=item.get("title"),
                description=item.get("description"),
                fields=[SimpleNamespace(name=f.get("name"), value=f.get("value")) for f in item.get("fields") or []],
                footer=SimpleNamespace(text=item.get("footer")),
                image=SimpleNamespace(proxy_url=item.get("image")),
                thumbnail=SimpleNamespace(proxy_url=item.get("thumbnail")),
            )

        return SimpleNamespace(
            id=int(data["id"]),
            channel=channel,
            guild=channel.guild,
            content=data.get("content") or "",
            clean_content=data.get("content") or "",
            type=SimpleNamespace(name=data.get("type") or "default"),
            author=SimpleNamespace(id=int(author.get("id") or 0), name=author.get("name"),
                                   display_name=author.get("display_name")),
            reference=SimpleNamespace(
                message_id=int(reference["message_id"]),
                channel_id=int(reference["channel_id"]) if reference.get("channel_id") else None,
            ) if reference else None,
            embeds=[embed(e) for e in data.get("embeds") or []],
            attachments=[attachment(a) for a in data.get("attachments") or []],
            created_at=_when(data.get("created_at")),
            edited_at=_when(data.get("edited_at")),
            message_snapshots=[SimpleNamespace(content=text) for text in data.get("snapshots") or []],
        )


class _User:
    def __init__(self, user_id: int, name: str):
        self.id = user_id
        self.name = name

    def __str__(self) -> str:
        return self.name

