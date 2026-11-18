#!/usr/bin/env python3
"""
API Server for Dashboard
Provides secure settings endpoints using settings_service.py with proper encryption/decryption
"""
from typing import Any, Optional
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from loguru import logger
from dotenv import load_dotenv

from src.services.settings_service import ValueType, SettingCategory
from src.services.telegram_channel_service_prisma import telegram_channel_service_prisma
from src.api.internal_auth import install_internal_auth

load_dotenv()


# Pydantic models for API
class CreateSettingRequest(BaseModel):
    key: str
    value: str
    valueType: str
    category: str
    description: str
    isSecret: bool = False


class UpdateSettingRequest(BaseModel):
    value: Any


class AddChannelRequest(BaseModel):
    channel_id: str
    channel_title: str = None
    channel_username: str = None
    access_hash: str = None
    is_broadcast: bool = True
    is_megagroup: bool = False
    participants_count: int = None
    photo_url: str = None


class UpdateChannelStatusRequest(BaseModel):
    is_active: bool


# Global settings service instance (will be set by main.py)
_settings_service = None
_settings_config = None
_telethon_listener = None


def set_settings_service(settings_service):
    """Set the settings service instance (called by main.py)"""
    global _settings_service
    _settings_service = settings_service


def set_settings_config(settings_config):
    """Set the settings config object (called by main.py)"""
    global _settings_config
    _settings_config = settings_config


def set_telethon_listener(telethon_listener):
    """Set the running TelethonListener instance (called by main.py)"""
    global _telethon_listener
    _telethon_listener = telethon_listener


def get_settings_service_instance():
    """Get the settings service instance"""
    global _settings_service
    if _settings_service is None:
        raise RuntimeError("Settings service not initialized. Call set_settings_service first.")
    return _settings_service


app = FastAPI(
    title="Trading Bot API",
    description="Secure API for dashboard with proper encryption/decryption",
    version="1.0.0"
)

# No CORS middleware: only the dashboard's server side calls this API, never a
# browser. The previous allow_origins=["*"] + allow_credentials let any web page
# talk to it from a browser that could reach the port (audit finding H-05).
install_internal_auth(app)

from src.api.telegram_browser_router import telegram_browser_router
app.include_router(telegram_browser_router)

from src.api.orders_router import orders_router
app.include_router(orders_router)

from simulator.api import simulator_router
app.include_router(simulator_router)

from src.api.ea_signals_router import ea_signals_router
app.include_router(ea_signals_router)

from src.api.ea_mirror_router import ea_mirror_router
app.include_router(ea_mirror_router)

from src.api.gsquant_routes import gsquant_router
app.include_router(gsquant_router)

from src.api.notifications_router import notifications_router
app.include_router(notifications_router)

from src.api.logs_router import logs_router
app.include_router(logs_router)

from src.api.connections_router import connections_router
app.include_router(connections_router)

from src.api.telegram_auth_router import telegram_auth_router
app.include_router(telegram_auth_router)

from src.api.discord_router import discord_router
app.include_router(discord_router)


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


@app.get("/api/settings")
async def get_settings(category: str = None, decryptSecrets: bool = False):
    """
    Get all settings, optionally filtered by category
    
    Args:
        category: Optional category filter
        decryptSecrets: If true, return decrypted values for secret settings
    """
    try:
        settings_service = get_settings_service_instance()
        
        if category:
            category_enum = SettingCategory(category.upper())
            settings_metadata = await settings_service.get_settings_by_category(category_enum)
            
            # Convert to list format
            all_settings = []
            for key, value in settings_metadata.items():
                # Find the setting metadata
                metadata_list = await settings_service.get_all_settings_metadata(decrypt_secrets=decryptSecrets)
                metadata = next((s for s in metadata_list if s["key"] == key), None)
                if metadata:
                    all_settings.append(metadata)
            
            return {
                "grouped": False,
                "settings": all_settings
            }
        else:
            settings_metadata = await settings_service.get_all_settings_metadata(decrypt_secrets=decryptSecrets)
            
            # Group by category
            grouped = {}
            for setting in settings_metadata:
                cat = setting["category"]
                if cat not in grouped:
                    grouped[cat] = []
                grouped[cat].append(setting)
            
            return {
                "grouped": True,
                "categories": grouped,
                "all": settings_metadata
            }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error fetching settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/settings")
async def create_setting(request: CreateSettingRequest):
    """
    Create a new setting in the database with proper encryption
    
    Args:
        request: Setting creation request
    """
    try:
        settings_service = get_settings_service_instance()
        
        # Convert string enums to actual enums
        value_type = ValueType(request.valueType.upper())
        category_enum = SettingCategory(request.category.upper())
        
        success = await settings_service.create_setting(
            key=request.key.upper().replace(" ", "_"),
            value=request.value,
            value_type=value_type,
            category=category_enum,
            description=request.description,
            is_secret=request.isSecret
        )
        
        if not success:
            raise HTTPException(status_code=409, detail=f"Setting '{request.key}' already exists or creation failed")
        
        return {"success": True, "message": f"Setting '{request.key}' created successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating setting: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/settings/{key}")
async def update_setting(key: str, request: UpdateSettingRequest):
    """
    Update an existing setting, encrypting it if it is a secret.
    The dashboard sends secret settings here instead of writing them to the database itself.
    """
    try:
        settings_service = get_settings_service_instance()
        if not await settings_service.set_setting(key, request.value):
            raise HTTPException(status_code=404, detail=f"Setting '{key}' not found")
        return {"success": True, "key": key}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating setting: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class ProviderSwitchRequest(BaseModel):
    provider: str


@app.get("/api/provider")
async def get_provider_status():
    """Active trading provider, its health, and failover configuration."""
    from src.integrations.trading.provider_manager import provider_manager
    return await provider_manager.status()


@app.post("/api/provider/switch")
async def switch_provider(request: ProviderSwitchRequest):
    """Hot-switch the trading provider (metaapi <-> mt5rest) without restarting."""
    from src.integrations.trading.provider_manager import provider_manager, ProviderSwitchBlocked
    try:
        return await provider_manager.switch(request.provider, reason="api")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ProviderSwitchBlocked as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error(f"Provider switch failed: {e}")
        raise HTTPException(status_code=502, detail=f"Switch failed, previous provider kept: {e}")


@app.post("/api/settings/reload")
async def reload_settings():
    """Reload settings from database and apply to bot"""
    try:
        settings_service = get_settings_service_instance()
        await settings_service.reload_cache()

        # Also reload the bot's settings object
        global _settings_config
        if _settings_config:
            await _settings_config.reload_from_db()

        # Reinitialize signal service so vision/AI provider changes take effect
        try:
            from src.services.signal_service import signal_service
            signal_service.reinitialize()
        except Exception as reinit_err:
            logger.warning(f"Could not reinitialize signal service: {reinit_err}")

        # Reload news trading service so news filter changes take effect
        try:
            from src.services.news_service import news_trading_service
            if news_trading_service:
                news_trading_service.reload_settings()
        except Exception as reinit_err:
            logger.warning(f"Could not reload news trading service: {reinit_err}")

        return {"success": True, "message": "Settings reloaded successfully"}
    except Exception as e:
        logger.error(f"Error reloading settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/settings/metadata")
async def get_settings_metadata():
    """Settings metadata (descriptions, categories, types) for the dashboard UI"""
    try:
        settings_service = get_settings_service_instance()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    try:
        return {"success": True, "metadata": await settings_service.get_all_settings_metadata()}
    except Exception as e:
        logger.error(f"Error fetching settings metadata: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# TELEGRAM CHANNEL MANAGEMENT ENDPOINTS
# ============================================================================

@app.get("/api/telegram/channels/all")
async def get_all_telegram_channels():
    """
    Get all channels from cache (fast!)
    Returns all channels and supergroups loaded at startup
    """
    try:
        # Use cached version for instant results
        result = await telegram_channel_service_prisma.get_all_channels_from_cache()
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        logger.error(f"Error fetching all channels: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/telegram/channels/refresh")
async def refresh_all_telegram_channels():
    """
    Force refresh all channels from Telegram (slow but gets latest data)
    Use this if you joined new channels and want to see them
    """
    try:
        # Force-reload the cache from Telegram (fresh data)
        await telegram_channel_service_prisma.load_dialogs_cache(force_reload=True)
        # Then return the fresh data
        result = await telegram_channel_service_prisma.get_all_channels_from_cache()
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        logger.error(f"Error refreshing channels: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/telegram/channels/monitored")
async def get_monitored_channels():
    """
    Get all monitored channels from database
    Returns only channels that are actively being monitored
    """
    try:
        channels = await telegram_channel_service_prisma.get_monitored_channels()
        return {
            "success": True,
            "data": channels,
            "count": len(channels)
        }
    except Exception as e:
        logger.error(f"Error fetching monitored channels: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def normalize_channel_id(channel_id: str) -> tuple[str, str]:
    """
    Normalize channel ID to handle both formats:
    - Full format: -1001234567890 (with -100 prefix)
    - Short format: 1234567890 (without -100 prefix)
    
    Returns: (full_id, short_id)
    """
    channel_id = channel_id.strip()
    
    # If it starts with -100, extract the short version
    if channel_id.startswith('-100'):
        short_id = channel_id[4:]  # Remove -100 prefix
        return (channel_id, short_id)
    # If it's negative but doesn't start with -100
    elif channel_id.startswith('-'):
        return (channel_id, channel_id[1:])
    # If it's positive, add -100 prefix
    else:
        full_id = f"-100{channel_id}"
        return (full_id, channel_id)


@app.get("/api/telegram/channels/by-ids")
async def get_channels_by_ids(ids: str):
    """
    Get channel details for multiple channel IDs
    Uses database cache first for speed, fetches from Telegram if needed
    
    Args:
        ids: Comma-separated channel IDs (e.g., "-1001234567890,-1009876543210")
    """
    try:
        from src.core.prisma_client import prisma_client
        
        channel_ids = [id.strip() for id in ids.split(',') if id.strip()]
        channels = []
        
        logger.info(f"📥 Fetching details for {len(channel_ids)} channel(s)")
        
        for channel_id in channel_ids:
            try:
                # Normalize channel ID
                full_id, short_id = normalize_channel_id(channel_id)
                
                # Try database first (fast!)
                db_channel = await prisma_client.client.monitoredchannel.find_first(
                    where={
                        'OR': [
                            {'channelId': full_id},
                            {'channelId': short_id},
                            {'channelId': channel_id}
                        ]
                    }
                )
                
                if db_channel:
                    # Use cached data from database
                    channels.append({
                        'id': db_channel.channelId,
                        'title': db_channel.channelTitle or f'Channel {channel_id}',
                        'username': db_channel.channelUsername,
                        'broadcast': db_channel.isBroadcast,
                        'megagroup': db_channel.isMegagroup,
                        'participants_count': db_channel.participantsCount,
                        'photo_url': db_channel.photoUrl
                    })
                    logger.debug(f"✅ Loaded from DB: {db_channel.channelTitle}")
                else:
                    # Not in database, fetch from Telegram and save
                    logger.info(f"📡 Fetching from Telegram: {channel_id}")
                    channel_info = await telegram_channel_service_prisma.get_channel_info(channel_id)
                    
                    if channel_info:
                        # Get photo
                        photo_url = None
                        try:
                            photo_base64 = await telegram_channel_service_prisma.get_channel_photo(channel_id)
                            if photo_base64:
                                photo_url = f"data:image/jpeg;base64,{photo_base64}"
                        except Exception as photo_error:
                            logger.debug(f"Could not fetch photo: {photo_error}")
                        
                        # Save to database for next time
                        try:
                            await prisma_client.client.monitoredchannel.upsert(
                                where={'channelId': channel_info['id']},
                                data={
                                    'create': {
                                        'channelId': channel_info['id'],
                                        'channelTitle': channel_info.get('title'),
                                        'channelUsername': channel_info.get('username'),
                                        'accessHash': channel_info.get('access_hash'),
                                        'isBroadcast': channel_info.get('broadcast', True),
                                        'isMegagroup': channel_info.get('megagroup', False),
                                        'participantsCount': channel_info.get('participants_count'),
                                        'photoUrl': photo_url,
                                        'isActive': False  # Not actively monitoring yet
                                    },
                                    'update': {
                                        'channelTitle': channel_info.get('title'),
                                        'channelUsername': channel_info.get('username'),
                                        'participantsCount': channel_info.get('participants_count'),
                                        'photoUrl': photo_url
                                    }
                                }
                            )
                            logger.debug(f"💾 Saved to DB: {channel_info.get('title')}")
                        except Exception as save_error:
                            logger.warning(f"Could not save to DB: {save_error}")
                        
                        channel_info['photo_url'] = photo_url
                        channels.append(channel_info)
                        logger.info(f"✅ Fetched: {channel_info.get('title')}")
                    else:
                        # Fallback to placeholder
                        logger.warning(f"⚠️ Channel {channel_id} not found")
                        channels.append({
                            'id': channel_id,
                            'title': f'Channel ID: {channel_id}',
                            'broadcast': True,
                            'megagroup': False,
                            'participants_count': None,
                            'photo_url': None
                        })
                    
            except Exception as e:
                logger.warning(f"Error fetching channel {channel_id}: {e}")
                channels.append({
                    'id': channel_id,
                    'title': f'Channel ID: {channel_id}',
                    'broadcast': True,
                    'megagroup': False,
                    'participants_count': None,
                    'photo_url': None
                })
        
        return {
            "success": True,
            "data": channels,
            "count": len(channels)
        }
    except Exception as e:
        logger.error(f"Error fetching channels by IDs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/telegram/channels/{channel_id}/info")
async def get_channel_info(channel_id: str):
    """
    Get detailed information about a specific channel
    
    Args:
        channel_id: Channel ID or username (e.g., @channelname or 1234567890)
    """
    try:
        info = await telegram_channel_service_prisma.get_channel_info(channel_id)
        if info:
            return {
                "success": True,
                "data": info
            }
        else:
            raise HTTPException(status_code=404, detail="Channel not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching channel info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/telegram/channels/{channel_id}/photo")
async def get_channel_photo(channel_id: str):
    """
    Get channel photo as base64 encoded string
    
    Args:
        channel_id: Channel ID or username
    """
    try:
        photo = await telegram_channel_service_prisma.get_channel_photo(channel_id)
        if photo:
            return {
                "success": True,
                "photo": photo
            }
        else:
            return {
                "success": True,
                "photo": None,
                "message": "No photo available"
            }
    except Exception as e:
        logger.error(f"Error fetching channel photo: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/telegram/channels/monitored")
async def add_monitored_channel(request: AddChannelRequest):
    """
    Add a channel to the monitored list
    
    Args:
        request: Channel data to add
    """
    try:
        channel_data = request.dict()
        success = await telegram_channel_service_prisma.add_monitored_channel(channel_data)
        
        if success:
            return {
                "success": True,
                "message": f"Channel {request.channel_title or request.channel_id} added to monitoring"
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to add channel")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding monitored channel: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/telegram/channels/monitored/{channel_id}")
async def remove_monitored_channel(channel_id: str):
    """Remove a channel, strip it from instant-execution/approval settings, and refresh the live listener."""
    try:
        success = await telegram_channel_service_prisma.remove_monitored_channel(channel_id)

        if not success:
            raise HTTPException(status_code=404, detail="Channel not found")

        try:
            # channelId is stored bare (str(entity.id)); the two settings below store
            # "-100"-prefixed peer IDs — match either form.
            bare_id = channel_id.lstrip('-').removeprefix('100')
            candidates = {channel_id, f"-100{bare_id}", f"-{bare_id}"}

            settings_service = get_settings_service_instance()
            for key in ("INSTANT_EXECUTION_CHANNELS", "APPROVAL_REQUIRED_CHANNELS"):
                current = await settings_service.get_setting(key, default=[])
                filtered = [ch for ch in current if str(ch).strip() not in candidates]
                if filtered != current:
                    await settings_service.set_setting(key, filtered)
            if _settings_config is not None:
                await _settings_config.reload_from_db()
        except Exception as e:
            logger.warning(f"⚠️ Could not clean up channel {channel_id} from instant-execution/approval settings: {e}")

        if _telethon_listener is not None:
            try:
                await _telethon_listener.refresh_channels()
            except Exception as e:
                logger.warning(f"⚠️ Could not refresh live listener after removing channel {channel_id}: {e}")
        else:
            logger.warning("⚠️ Telethon listener not registered with API server — restart required to apply")

        return {
            "success": True,
            "message": f"Channel {channel_id} removed from monitoring"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error removing monitored channel: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/api/telegram/channels/monitored/{channel_id}/status")
async def update_channel_status(channel_id: str, request: UpdateChannelStatusRequest):
    """
    Update channel monitoring status (enable/disable)
    
    Args:
        channel_id: Channel ID
        request: New status
    """
    try:
        success = await telegram_channel_service_prisma.update_channel_status(channel_id, request.is_active)
        
        if success:
            status = "enabled" if request.is_active else "disabled"
            return {
                "success": True,
                "message": f"Channel monitoring {status}"
            }
        else:
            raise HTTPException(status_code=404, detail="Channel not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating channel status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# AI Configuration endpoints
@app.get("/api/ai-config")
async def get_ai_config():
    """Get AI configuration from database"""
    try:
        from src.core.database_service import db_service
        
        config = await db_service.db.aiconfiguration.find_first()
        
        if not config:
            # Create default config if not exists
            config = await db_service.db.aiconfiguration.create(data={})
        
        # Convert to dict
        config_dict = {
            'id': str(config.id),
            'enablePositionSizing': config.enablePositionSizing,
            'baseRiskPercent': config.baseRiskPercent,
            'minLotSize': config.minLotSize,
            'maxLotSize': config.maxLotSize,
            'volatilityMultiplier': config.volatilityMultiplier,
        }
        
        return config_dict
    except Exception as e:
        logger.error(f"Error fetching AI config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/ai-config")
async def update_ai_config(request: dict):
    """Update AI configuration in database"""
    try:
        from src.core.database_service import db_service
        
        # Get existing config
        existing = await db_service.db.aiconfiguration.find_first()
        
        if not existing:
            raise HTTPException(status_code=404, detail="AI config not found")
        
        # Update only provided fields
        live_fields = {
            'enablePositionSizing', 'baseRiskPercent', 'minLotSize', 'maxLotSize', 'volatilityMultiplier'
        }
        update_data = {k: v for k, v in request.items() if k in live_fields}
        
        # Update config
        updated = await db_service.db.aiconfiguration.update(
            where={'id': existing.id},
            data=update_data
        )
        
        # Return updated config
        config_dict = {
            'id': str(updated.id),
            'enablePositionSizing': updated.enablePositionSizing,
            'baseRiskPercent': updated.baseRiskPercent,
            'minLotSize': updated.minLotSize,
            'maxLotSize': updated.maxLotSize,
            'volatilityMultiplier': updated.volatilityMultiplier,
        }
        
        return config_dict
        
    except Exception as e:
        logger.error(f"Error updating AI config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== AI Cost Tracking Endpoints ====================

@app.get("/api/ai-costs")
async def get_ai_costs(start: Optional[str] = None, end: Optional[str] = None):
    """Return local bot AI cost and token usage report, optionally filtered by date range."""
    from ai.cost_tracker import cost_tracker
    return cost_tracker.get_report(start_date=start, end_date=end)


@app.post("/api/ai-costs/reset")
async def reset_ai_costs():
    """Clear all locally tracked AI cost records."""
    from ai.cost_tracker import cost_tracker
    cost_tracker.reset()
    return {"status": "reset", "message": "AI cost records cleared"}


# ==================== Channel Rules: AI draft ====================

class GenerateRuleRequest(BaseModel):
    description: str


@app.post("/api/channel-behavior/generate-rule")
async def generate_channel_behavior_rule(request: GenerateRuleRequest):
    """Draft a channel rule from a plain-English description (explicit click only)"""
    from src.services.channel_rule_generator import channel_rule_generator

    if not channel_rule_generator.available():
        raise HTTPException(status_code=503, detail="No AI provider configured. Add an API key in Settings.")
    try:
        rule_config = await channel_rule_generator.generate_rule(request.description)
    except Exception as e:
        logger.error(f"Error generating channel behavior rule: {e}")
        raise HTTPException(status_code=502, detail=f"AI request failed: {e}")
    if not rule_config:
        raise HTTPException(status_code=422, detail="The AI answer was not a usable rule. Try rephrasing.")
    return {"success": True, "rule": rule_config}


# ---------------------------------------------------------------------------
# Trade Plan endpoints
# ---------------------------------------------------------------------------

@app.get("/api/plans")
async def get_plans(status: str = "", limit: int = 50):
    """List TradePlans, optionally filtered by status.

    When no explicit status filter is given, ALL active plans (WATCHING /
    PRIMARY_ACTIVE / FALLBACK_WATCHING / FALLBACK_ACTIVE) are always returned
    regardless of `limit`, then the remaining slots are filled with the newest
    inactive plans. This prevents a busy day of FILTERED/EXPIRED rows from
    pushing real active plans out of the response window (which made plans
    look "deleted" on the dashboard even though they still existed).
    """
    try:
        from src.core.database_service import db_service

        ACTIVE = ["WATCHING", "PRIMARY_ACTIVE", "FALLBACK_WATCHING", "FALLBACK_ACTIVE"]

        if status:
            plans = await db_service.db.tradeplan.find_many(
                where={"status": status},
                include={"signal": True},
                order={"createdAt": "desc"},
                take=limit,
            )
        else:
            # Always include every active plan, unbounded by `limit`.
            active_plans = await db_service.db.tradeplan.find_many(
                where={"status": {"in": ACTIVE}},
                include={"signal": True},
                order={"createdAt": "desc"},
            )
            # Fill any remaining slots with the newest inactive plans.
            remaining = max(0, limit - len(active_plans))
            inactive_plans = []
            if remaining:
                inactive_plans = await db_service.db.tradeplan.find_many(
                    where={"status": {"notIn": ACTIVE}},
                    include={"signal": True},
                    order={"createdAt": "desc"},
                    take=remaining,
                )
            plans = active_plans + inactive_plans
        # Strip raw imageData from signal to keep response size small
        results = []
        for p in plans:
            plan_dict = dict(p.__dict__)
            if p.signal:
                sig = dict(p.signal.__dict__)
                has_image = bool(sig.get("imageData"))
                sig.pop("imageData", None)
                sig["hasImage"] = has_image
                plan_dict["signal"] = sig
            results.append(plan_dict)
        return results
    except Exception as e:
        logger.error(f"Error fetching plans: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/plans/{plan_id}/execute")
async def execute_plan(plan_id: str, request: Request):
    """Queue a manual execute request for a plan leg (picked up by watcher within 3s)."""
    try:
        body = await request.json()
        leg = body.get("leg", "primary")
        if leg not in ("primary", "fallback"):
            raise HTTPException(status_code=400, detail="leg must be 'primary' or 'fallback'")

        from src.core.database_service import db_service
        plan = await db_service.db.tradeplan.find_unique(where={"id": plan_id})
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        if plan.status not in ("WATCHING", "FALLBACK_WATCHING"):
            raise HTTPException(
                status_code=400,
                detail=f"Plan cannot be executed in status '{plan.status}'"
            )

        # Require SL before execution — never trade without a stop loss
        is_primary = leg == "primary"
        sl = plan.primarySl if is_primary else (getattr(plan, "fallbackSl", None) or 0)
        if not sl or sl == 0:
            raise HTTPException(
                status_code=400,
                detail="Cannot execute: this plan has no stop loss set. Add an SL before executing."
            )

        await db_service.db.tradeplan.update(
            where={"id": plan_id},
            data={"manualExecuteRequested": True, "manualExecuteLeg": leg},
        )
        return {"queued": True, "leg": leg}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error queuing plan execute: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/api/plans/{plan_id}")
async def update_plan(plan_id: str, request: Request):
    """Update editable fields of a plan (SL, entry zones, TPs, fallback fields)."""
    import json as _json
    try:
        from src.core.database_service import db_service

        plan = await db_service.db.tradeplan.find_unique(where={"id": plan_id})
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")

        body = await request.json()
        update_data: dict = {}

        def _safe_float(v):
            try:
                return float(v) if v is not None and str(v).strip() != "" else None
            except (ValueError, TypeError):
                return None

        def _tps_to_json(v) -> str | None:
            if v is None:
                return None
            if isinstance(v, list):
                return _json.dumps([float(x) for x in v if x is not None])
            # comma-separated string from UI
            parts = [p.strip() for p in str(v).split(",") if p.strip()]
            nums = [float(p) for p in parts if p]
            return _json.dumps(nums) if nums else None

        float_fields = [
            "primaryEntryMin", "primaryEntryMax", "primarySl",
            "fallbackEntryMin", "fallbackEntryMax", "fallbackSl",
        ]
        for f in float_fields:
            if f in body:
                val = _safe_float(body[f])
                if val is not None:
                    update_data[f] = val

        for f in ("primaryTps", "fallbackTps"):
            if f in body:
                val = _tps_to_json(body[f])
                if val is not None:
                    update_data[f] = val

        if "primarySlCondition" in body:
            update_data["primarySlCondition"] = body["primarySlCondition"] or None

        if "fallbackOrderType" in body and body["fallbackOrderType"] in ("BUY", "SELL"):
            update_data["fallbackOrderType"] = body["fallbackOrderType"]

        if not update_data:
            raise HTTPException(status_code=400, detail="No valid fields to update")

        updated = await db_service.db.tradeplan.update(
            where={"id": plan_id},
            data=update_data,
            include={"signal": True},
        )
        return updated

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating plan {plan_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/plans/{plan_id}/cancel")
async def cancel_plan(plan_id: str):
    """Cancel a watching plan."""
    try:
        from src.core.database_service import db_service
        from src.services.plan_watcher_service import plan_watcher_service

        plan = await db_service.db.tradeplan.find_unique(where={"id": plan_id})
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")

        await db_service.db.tradeplan.update(
            where={"id": plan_id},
            data={"status": "CANCELLED"},
        )
        plan_watcher_service.remove_plan(plan_id)
        return {"cancelled": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling plan: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/plans/{plan_id}")
async def delete_plan(plan_id: str):
    """Hard-delete a single plan from the database."""
    try:
        from src.core.database_service import db_service
        from src.services.plan_watcher_service import plan_watcher_service

        plan = await db_service.db.tradeplan.find_unique(where={"id": plan_id})
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")

        plan_watcher_service.remove_plan(plan_id)
        await db_service.db.tradeplan.delete(where={"id": plan_id})
        return {"deleted": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting plan {plan_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/plans/bulk-delete")
async def bulk_delete_plans(request: Request):
    """Hard-delete multiple plans from the database."""
    try:
        from src.core.database_service import db_service
        from src.services.plan_watcher_service import plan_watcher_service

        body = await request.json()
        ids: list[str] = body.get("ids", [])
        if not ids:
            raise HTTPException(status_code=400, detail="No plan IDs provided")

        for plan_id in ids:
            plan_watcher_service.remove_plan(plan_id)

        result = await db_service.db.tradeplan.delete_many(
            where={"id": {"in": ids}}
        )
        return {"deleted": result.count}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error bulk-deleting plans: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# DRAWDOWN BREACH MANAGEMENT ENDPOINT
# ============================================================================

@app.post("/api/drawdown/reset")
async def reset_drawdown_breach():
    """
    Manually reset any active drawdown breach and resume trading.
    Useful when you want to override a breach on the same trading day
    without waiting for the daily auto-reset.
    """
    try:
        from src.services.drawdown_protection_service import drawdown_protection_service

        # Get current breach info before reset
        breach_info = await drawdown_protection_service.get_active_breach_info()

        if not breach_info:
            # Check if there are any active breaches that aren't tracked in-memory
            from src.core.database_service import db_service
            from config import settings
            provider = settings.trading_provider.lower().strip()
            account_id = settings.mt5_rest_api_url if provider == "mt5rest" else (settings.metaapi_account_id or "unknown")

            active_breach = await db_service.db.drawdownbreach.find_first(
                where={"accountId": account_id, "isActive": True},
                order={"createdAt": "desc"},
            )

            if active_breach:
                # Resolve it directly in DB
                from datetime import datetime as dt, timezone as tz
                await db_service.db.drawdownbreach.update(
                    where={"id": active_breach.id},
                    data={
                        "isActive": False,
                        "resolvedAt": dt.now(tz.utc),
                        "resolvedReason": "MANUAL_RESET",
                        "resumedAt": dt.now(tz.utc),
                    },
                )
                logger.warning(
                    f"⚠️  Orphaned active breach resolved manually: {active_breach.id} "
                    f"(Type: {active_breach.breachType}, DD: {active_breach.drawdownPercent:.2f}%)"
                )
                return {
                    "success": True,
                    "message": "Orphaned breach resolved. Trading can resume.",
                    "breach_id": active_breach.id,
                    "was_active": True,
                }
            else:
                return {
                    "success": True,
                    "message": "No active breach found. Trading is already allowed.",
                    "was_active": False,
                }

        # Resolve the in-memory breach
        success = await drawdown_protection_service.manual_resume_trading("MANUAL_RESET")

        if success:
            logger.warning(
                f"⚠️  Drawdown breach manually reset by dashboard user. "
                f"Breach ID: {breach_info.get('id')}, "
                f"Type: {breach_info.get('type')}, "
                f"DD: {breach_info.get('drawdown_percent', 0):.2f}%"
            )
            return {
                "success": True,
                "message": "Drawdown breach reset successfully. Trading has been resumed.",
                "breach_id": breach_info.get("id"),
                "breach_type": breach_info.get("type"),
                "was_active": True,
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to reset breach")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resetting drawdown breach: {e}")
        raise HTTPException(status_code=500, detail=str(e))
