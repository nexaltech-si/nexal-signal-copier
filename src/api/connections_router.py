"""
Live state for the dashboard's Connections page.

The dashboard checks MT5, the database, Redis and the copier EAs itself. This
covers what only the bot process knows: the Telegram listener (which configured
channels actually resolved, when each last delivered a message), the news filter
feed, and the health-check loop — plus the actions behind the page's buttons.
"""
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException

connections_router = APIRouter(prefix="/api/connections", tags=["connections"])

NEWS_CACHE_FILE = "data/news_cache.json"


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()  # naive = container-local time
    return dt.astimezone(timezone.utc).isoformat()


def _listener():
    from src.api.api_server import _telethon_listener
    return _telethon_listener


def _news_service():
    from src.services import news_service
    return news_service.news_trading_service


async def _telegram_status() -> dict:
    listener = _listener()
    if listener is None:
        return {"available": False, "reason": "Telegram listener not started"}

    client = listener.client
    connected = bool(client and client.is_connected())
    channels = []
    for entity in listener.monitored_entities:
        last = listener.last_message_by_chat.get(entity.id)
        channels.append({
            "id": str(entity.id),
            "title": getattr(entity, "title", None) or getattr(entity, "first_name", None) or str(entity.id),
            "username": getattr(entity, "username", None),
            "lastMessageAt": _iso(last),
        })

    return {
        "available": True,
        "connected": connected,
        "auth": listener.auth_status(),
        "listeningSince": _iso(listener.started_at),
        "configuredCount": len(listener.configured_channel_ids),
        "channels": channels,
        "unresolved": [{"id": cid, "error": err} for cid, err in listener.unresolved_channels.items()],
        "lastMessageAt": _iso(listener.last_message_at),
        "inflight": len(listener._inflight_tasks),
    }


def _discord_status() -> dict:
    try:
        from src.integrations.discord.listener import discord_listener
        return discord_listener.status()
    except Exception as e:  # optional source: never break the page for the other connections
        return {"enabled": False, "tokenSet": False, "state": "error", "error": str(e)[:200], "account": None,
                "inviteUrl": None, "guildCount": 0, "listeningSince": None, "lastMessageAt": None,
                "inflight": 0, "channels": []}


def _news_status() -> dict:
    svc = _news_service()
    if svc is None:
        return {"available": False, "reason": "News service not initialized"}
    status = svc.get_status()
    # svc.last_update is also set when the cache file is merely loaded at startup,
    # so the file's mtime is the honest "last fetched" time.
    try:
        fetched_at = datetime.fromtimestamp(os.path.getmtime(NEWS_CACHE_FILE), tz=timezone.utc)
    except OSError:
        fetched_at = None
    return {
        "available": True,
        "enabled": status.get("enabled"),
        "running": status.get("running"),
        "events": status.get("cache_size", 0),
        "activeBlocks": status.get("active_blocks", 0),
        "nextNews": status.get("next_news"),
        "fetchedAt": _iso(fetched_at),
        "stale": bool(svc.news_cache) and svc._is_cache_stale(),
        "currencies": sorted(status.get("target_currencies") or []),
        "impacts": status.get("important_impacts") or [],
    }


def _health_loop_status() -> dict:
    from src.services.health_check_service import health_check_service as hcs
    return {
        "running": hcs.running,
        "startedAt": _iso(hcs.start_time),
        "lastCheck": _iso(hcs.last_full_check),
        "intervalSeconds": hcs.check_interval,
        "components": {
            name: {"status": h.status, "message": h.message}
            for name, h in hcs.health_status.items()
        },
    }


@connections_router.get("/status")
async def connections_status():
    return {
        "telegram": await _telegram_status(),
        "discord": _discord_status(),
        "news": _news_status(),
        "health": _health_loop_status(),
        "serverTime": datetime.now(timezone.utc).isoformat(),
    }


@connections_router.post("/telegram/resync")
async def resync_telegram_channels():
    """Re-resolve the monitored channel list and apply it to the running listener."""
    listener = _listener()
    if listener is None:
        raise HTTPException(status_code=503, detail="Telegram listener not started")
    await listener.refresh_channels()
    return {
        "success": True,
        "listening": len(listener.monitored_entities),
        "unresolved": len(listener.unresolved_channels),
    }


@connections_router.post("/news/refresh")
async def refresh_news():
    svc = _news_service()
    if svc is None:
        raise HTTPException(status_code=503, detail="News service not initialized")
    ok = await svc.fetch_news(force_update=True)
    if not ok:
        raise HTTPException(status_code=502, detail="News API fetch failed — see bot logs")
    return {"success": True, "events": len(svc.news_cache)}


@connections_router.post("/health-check")
async def run_health_check():
    from src.services.health_check_service import health_check_service as hcs
    data = await hcs.run_all_checks()
    return {"success": True, "overall": data["overall_status"], "summary": data["summary"]}
