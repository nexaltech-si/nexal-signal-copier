"""
Discord "own account" worker — a separate process.

Reads the channels a personal Discord account can see, for servers where a bot
cannot be added. It uses discord.py-self, which installs under the same package
name as discord.py (the bot library) and therefore lives in its own virtualenv
(/opt/discord-user in the bot image). The bot starts this file with that
interpreter and talks to it over pipes (see user_client.py):

  stdin   line 1: {"token": "..."}            (never argv / environment: not visible in `ps`)
          then:   {"cmd": "watch", "channels": [ids]}
                  {"cmd": "history", "req": n, "channel_id": id, "after": id|null, "before": id|null, "limit": n}
  stdout  one JSON object per line: ready / guilds / message / edit / delete / history / fatal

Only messages of watched channels leave this process. It never writes to Discord.
This file must not import anything from the bot: it runs outside its environment.
"""
import asyncio
import json
import sys


def emit(obj) -> None:
    sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def iso(dt):
    return dt.isoformat() if dt else None


def embed_dict(embed) -> dict:
    return {
        "type": getattr(embed, "type", "rich"),
        "author": getattr(getattr(embed, "author", None), "name", None),
        "title": embed.title,
        "description": embed.description,
        "fields": [{"name": f.name, "value": f.value} for f in embed.fields],
        "footer": getattr(getattr(embed, "footer", None), "text", None),
        "image": getattr(getattr(embed, "image", None), "proxy_url", None),
        "thumbnail": getattr(getattr(embed, "thumbnail", None), "proxy_url", None),
    }


def message_dict(message) -> dict:
    channel = message.channel
    guild = getattr(channel, "guild", None)
    reference = message.reference
    return {
        "id": str(message.id),
        "channel_id": str(channel.id),
        "channel_name": getattr(channel, "name", None),
        "guild_id": str(guild.id) if guild else None,
        "guild_name": guild.name if guild else None,
        "type": getattr(message.type, "name", str(message.type)),
        "content": message.clean_content or message.content or "",
        "author": {
            "id": str(message.author.id),
            "name": getattr(message.author, "name", None),
            "display_name": getattr(message.author, "display_name", None),
        },
        "created_at": iso(message.created_at),
        "edited_at": iso(message.edited_at),
        "reference": {
            "message_id": str(reference.message_id),
            "channel_id": str(reference.channel_id) if reference.channel_id else None,
        } if reference is not None and reference.message_id else None,
        "attachments": [
            {"url": a.url, "content_type": a.content_type, "filename": a.filename, "size": a.size}
            for a in message.attachments
        ],
        "embeds": [embed_dict(e) for e in message.embeds],
        "snapshots": [getattr(s, "content", "") or "" for s in getattr(message, "message_snapshots", None) or []],
    }


def guilds_snapshot(client) -> list:
    result = []
    for guild in client.guilds:
        me = guild.me
        channels = []
        for channel in guild.text_channels:
            readable = True
            if me is not None:
                perms = channel.permissions_for(me)
                readable = bool(perms.view_channel and perms.read_message_history)
            channels.append({
                "id": str(channel.id),
                "name": channel.name,
                "category": channel.category.name if channel.category else None,
                "category_position": channel.category.position if channel.category else -1,
                "position": channel.position,
                "readable": readable,
            })
        result.append({
            "id": str(guild.id),
            "name": guild.name,
            "icon": guild.icon.url if guild.icon else None,
            "channels": channels,
        })
    return result


async def main() -> None:
    try:
        import discord
    except ImportError as e:
        emit({"t": "fatal", "code": "not_installed", "error": str(e)})
        return

    first = sys.stdin.readline()
    try:
        token = json.loads(first)["token"]
    except Exception:
        emit({"t": "fatal", "code": "protocol", "error": "no token received"})
        return

    # chunk_guilds_at_startup: member lists are not needed and are slow on big servers.
    # guild_subscriptions: without it large servers deliver no message events.
    client = discord.Client(chunk_guilds_at_startup=False, guild_subscriptions=True)
    watched = set()
    snapshot_task = None

    def send_guilds_soon():
        nonlocal snapshot_task

        async def later():
            await asyncio.sleep(2)   # a burst of channel updates becomes one snapshot
            emit({"t": "guilds", "guilds": guilds_snapshot(client)})
        if snapshot_task is None or snapshot_task.done():
            snapshot_task = asyncio.ensure_future(later())

    @client.event
    async def on_ready():
        user = client.user
        emit({"t": "ready", "user": {"id": str(user.id), "name": str(user)}, "guilds": guilds_snapshot(client)})

    @client.event
    async def on_message(message):
        if message.channel.id in watched:
            emit({"t": "message", "m": message_dict(message)})

    @client.event
    async def on_raw_message_edit(payload):
        if payload.channel_id not in watched or not (payload.data or {}).get("edited_timestamp"):
            return
        message = getattr(payload, "message", None) or payload.cached_message
        if message is None or message.edited_at is None:
            channel = client.get_channel(payload.channel_id)
            if channel is None:
                return
            try:
                message = await channel.fetch_message(payload.message_id)
            except Exception:
                return
        emit({"t": "edit", "m": message_dict(message)})

    @client.event
    async def on_raw_message_delete(payload):
        if payload.channel_id in watched:
            emit({"t": "delete", "channel_id": str(payload.channel_id), "ids": [str(payload.message_id)]})

    @client.event
    async def on_raw_bulk_message_delete(payload):
        if payload.channel_id in watched:
            emit({"t": "delete", "channel_id": str(payload.channel_id), "ids": [str(i) for i in payload.message_ids]})

    for name in ("on_guild_join", "on_guild_remove", "on_guild_update", "on_guild_channel_create",
                 "on_guild_channel_delete", "on_guild_channel_update"):
        async def changed(*_args):
            send_guilds_soon()
        changed.__name__ = name
        client.event(changed)

    async def history(command):
        messages = []
        try:
            channel = client.get_channel(int(command["channel_id"]))
            if channel is not None:
                after = discord.Object(id=int(command["after"])) if command.get("after") else None
                before = discord.Object(id=int(command["before"])) if command.get("before") else None
                async for message in channel.history(limit=int(command.get("limit") or 1), after=after,
                                                     before=before, oldest_first=False):
                    messages.append(message_dict(message))
            emit({"t": "history", "req": command.get("req"), "messages": messages})
        except Exception as e:
            emit({"t": "history", "req": command.get("req"), "messages": [], "error": str(e)[:200]})

    async def commands():
        loop = asyncio.get_running_loop()
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:                      # the bot closed the pipe (or died): stop too
                await client.close()
                return
            try:
                command = json.loads(line)
            except ValueError:
                continue
            if command.get("cmd") == "watch":
                watched.clear()
                watched.update(int(c) for c in command.get("channels") or [])
            elif command.get("cmd") == "history":
                asyncio.ensure_future(history(command))

    reader = asyncio.ensure_future(commands())
    try:
        await client.start(token)
    except discord.LoginFailure as e:
        emit({"t": "fatal", "code": "login_failed", "error": str(e)[:200]})
    except Exception as e:
        emit({"t": "fatal", "code": "connection", "error": f"{type(e).__name__}: {str(e)[:200]}"})
    finally:
        reader.cancel()
        if not client.is_closed():
            await client.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
