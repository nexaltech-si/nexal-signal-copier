"""
Discord listener, driven from the dashboard's Discord page: bot token and on/off
switch (settings table, token encrypted), the servers the bot is in, and which
channels of each server are listened to (discord_channels table). Changes apply
to the running listener immediately — no restart, nothing in the environment.
"""
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel

from src.integrations.discord.listener import discord_listener
from src.utils.audit import audit

discord_router = APIRouter(prefix="/api/discord", tags=["discord"])


class DiscordConfigRequest(BaseModel):
    enabled: Optional[bool] = None
    token: Optional[str] = None  # bot token; "" removes the stored token
    accountType: Optional[str] = None  # "bot" | "user"
    userToken: Optional[str] = None  # token of the owner's own account; "" removes it


class GuildChannelsRequest(BaseModel):
    channelIds: List[str]


def _services():
    from src.api import api_server
    return api_server.get_settings_service_instance(), api_server._settings_config


async def _forget_channels(channel_ids) -> None:
    """A channel that is no longer listened to also leaves the per-channel settings
    (same as removing a Telegram channel)."""
    gone = {str(c) for c in channel_ids}
    if not gone:
        return
    try:
        settings_service, settings_config = _services()
        for key in ("INSTANT_EXECUTION_CHANNELS", "APPROVAL_REQUIRED_CHANNELS"):
            current = await settings_service.get_setting(key, default=[]) or []
            if isinstance(current, str):
                current = [c.strip() for c in current.split(",") if c.strip()]
            kept = [c for c in current if str(c).strip() not in gone]
            if kept != current:
                await settings_service.set_setting(key, kept)
        if settings_config is not None:
            await settings_config.reload_from_db()
    except Exception as e:
        logger.warning(f"🎮 Discord: could not clean channels {sorted(gone)} from instant-execution/approval settings: {e}")


@discord_router.get("/status")
async def discord_status():
    return discord_listener.status()


@discord_router.put("/config")
async def update_discord_config(request: DiscordConfigRequest):
    """Save the token and/or the on/off switch and reconnect with them."""
    settings_service, settings_config = _services()
    if request.token is not None:
        token = request.token.strip()
        if token and (len(token) < 50 or any(c.isspace() for c in token)):
            raise HTTPException(status_code=400, detail="That does not look like a Discord bot token")
        if not await settings_service.set_setting("DISCORD_BOT_TOKEN", token):
            raise HTTPException(status_code=500, detail="DISCORD_BOT_TOKEN setting is missing — restart the bot once")
        audit("AUDIT", "Discord bot token " + ("changed" if token else "removed"), "MEDIUM", module="discord")
    if request.userToken is not None:
        user_token = request.userToken.strip().strip('"')
        if user_token and (len(user_token) < 50 or any(c.isspace() for c in user_token)):
            raise HTTPException(status_code=400, detail="That does not look like a Discord account token")
        if not await settings_service.set_setting("DISCORD_USER_TOKEN", user_token):
            raise HTTPException(status_code=500, detail="DISCORD_USER_TOKEN setting is missing — restart the bot once")
        audit("AUDIT", "Discord account token " + ("changed" if user_token else "removed"), "MEDIUM", module="discord")
    if request.accountType is not None:
        account_type = request.accountType.strip().lower()
        if account_type not in ("bot", "user"):
            raise HTTPException(status_code=400, detail="accountType must be 'bot' or 'user'")
        if not await settings_service.set_setting("DISCORD_ACCOUNT_TYPE", account_type):
            raise HTTPException(status_code=500, detail="DISCORD_ACCOUNT_TYPE setting is missing — restart the bot once")
        audit("AUDIT", f"Discord is now read with: {account_type}", "MEDIUM", module="discord")
    if request.enabled is not None:
        if not await settings_service.set_setting("DISCORD_ENABLED", request.enabled):
            raise HTTPException(status_code=500, detail="DISCORD_ENABLED setting is missing — restart the bot once")
    if settings_config is not None:
        await settings_config.reload_from_db()
    await discord_listener.apply_settings()
    return discord_listener.status()


@discord_router.post("/reconnect")
async def reconnect_discord():
    """Drop the connection and connect again (after fixing the intent or permissions)."""
    await discord_listener.stop()
    await discord_listener.apply_settings()
    return discord_listener.status()


@discord_router.get("/guilds")
async def discord_guilds():
    return {"state": discord_listener.state, "guilds": discord_listener.guilds()}


@discord_router.put("/guilds/{guild_id}/channels")
async def set_guild_channels(guild_id: str, request: GuildChannelsRequest):
    """Replace the monitored channels of one server."""
    wanted = list(dict.fromkeys(c.strip() for c in request.channelIds if c.strip()))
    resolved = discord_listener.channel_names(guild_id, wanted)
    if resolved is None:
        raise HTTPException(status_code=409, detail="The Discord bot is not connected to that server")
    unknown = set(wanted) - {c["id"] for c in resolved["channels"]}
    if unknown:
        raise HTTPException(status_code=400, detail=f"Not a text channel of this server: {', '.join(sorted(unknown))}")
    before = {c["channelId"] for c in await discord_listener.store.monitored_channels() if c["guildId"] == guild_id}
    await discord_listener.store.set_guild_channels(guild_id, resolved["name"], resolved["channels"])
    count = await discord_listener.refresh_channels()
    await _forget_channels(before - set(wanted))
    logger.info(f"🎮 Discord: {resolved['name']} now has {len(wanted)} monitored channel(s) ({count} in total)")
    audit("AUDIT", f"Discord channels of {resolved['name']} changed", "LOW",
          {"channels": [c["name"] for c in resolved["channels"]]}, module="discord")
    return {"success": True, "monitored": len(wanted), "total": count}


@discord_router.delete("/channels/{channel_id}")
async def remove_discord_channel(channel_id: str):
    """Stop listening to one channel (also works for a server the bot has left)."""
    if not await discord_listener.store.remove_channel(channel_id):
        raise HTTPException(status_code=404, detail="Channel is not monitored")
    await _forget_channels([channel_id])
    return {"success": True, "total": await discord_listener.refresh_channels()}
