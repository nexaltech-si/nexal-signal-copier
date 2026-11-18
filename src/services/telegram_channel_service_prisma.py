"""
Telegram Channel Service (Prisma Version)
Manages a single Telegram session and provides channel management functionality
Uses Prisma for database operations
"""
import base64
from typing import List, Dict, Optional
from telethon import TelegramClient
from telethon.tl.types import Channel, Chat, User
from loguru import logger

from config import settings
from src.core.prisma_client import prisma_client


class TelegramChannelServicePrisma:
    """Service to manage Telegram channels using a shared Telegram client with Prisma database"""
    
    def __init__(self, shared_client: Optional[TelegramClient] = None):
        self.client: Optional[TelegramClient] = shared_client
        self._initialized = False
        self._owns_client = shared_client is None
        self._dialogs_cache: Dict[str, Channel] = {}  # Cache of channel_id -> Channel entity
        self._cache_loaded = False
        
    async def initialize(self, shared_client: Optional[TelegramClient] = None):
        """
        Initialize Telegram client
        
        Args:
            shared_client: Optional shared TelegramClient to reuse (recommended to avoid session locks)
        """
        if self._initialized:
            return
            
        try:
            logger.info("🔄 Initializing Telegram channel service (Prisma)...")
            
            # Use shared client if provided
            if shared_client:
                self.client = shared_client
                self._owns_client = False
                logger.info("   Using shared Telegram client (avoids session lock)")
            elif self.client:
                # Already have a client from constructor
                logger.info("   Using pre-configured Telegram client")
            else:
                # Create own client (not recommended - may cause session locks)
                logger.warning("   Creating new Telegram client - may cause session locks!")
                self.client = TelegramClient(
                    settings.telegram_session_name + "_channel_service",
                    settings.telegram_api_id,
                    settings.telegram_api_hash
                )
                self._owns_client = True
                # Connect using existing session (no interactive prompts)
                await self.client.connect()
                if not await self.client.is_user_authorized():
                    raise Exception("Telegram session not authorized - please authenticate using the simulator first")
            
            # Verify client is connected
            if not self.client:
                raise Exception("Telegram client is None - cannot initialize channel service")
            
            if not self.client.is_connected():
                logger.warning("⚠️ Telegram client not connected, attempting to connect...")
                await self.client.connect()
            
            me = await self.client.get_me()
            if not me:
                raise Exception("Failed to get user info from Telegram - client may not be authenticated")
                
            logger.success(f"✅ Telegram channel service initialized as: {me.first_name} (@{me.username or 'no username'})")
            
            self._initialized = True
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize Telegram service: {e}")
            raise
    
    async def ensure_initialized(self):
        """Ensure client is initialized before operations"""
        if not self._initialized:
            await self.initialize()
    
    async def load_dialogs_cache(self, force_reload: bool = False):
        """Load all dialogs into cache for fast lookups
        
        Args:
            force_reload: If True, clear existing cache and re-fetch from Telegram.
                          Use this when new channels have been joined since startup.
        """
        if self._cache_loaded and not force_reload:
            return
        
        if force_reload:
            logger.info("🔄 Force-reloading dialogs cache from Telegram...")
            self._dialogs_cache.clear()
            self._cache_loaded = False
            
        await self.ensure_initialized()
        
        try:
            logger.info("📦 Loading dialogs into cache...")
            count = 0
            
            async for dialog in self.client.iter_dialogs():
                entity = dialog.entity
                if isinstance(entity, Channel):
                    # Store with multiple ID formats for easy lookup
                    entity_id = str(entity.id)
                    entity_id_full = f"-100{entity.id}"
                    
                    self._dialogs_cache[entity_id] = entity
                    self._dialogs_cache[entity_id_full] = entity
                    count += 1
            
            self._cache_loaded = True
            logger.success(f"✅ Loaded {count} channels into cache")
            
        except Exception as e:
            logger.error(f"❌ Failed to load dialogs cache: {e}")
    
    async def _get_entity_safe(self, channel_id: str):
        """
        Safely get entity by ID from cache
        
        Args:
            channel_id: Channel ID (numeric string like "-1001234567890")
            
        Returns:
            Entity or None
        """
        await self.ensure_initialized()
        
        # Load cache if not loaded
        if not self._cache_loaded:
            await self.load_dialogs_cache()
        
        try:
            # Try direct lookup from cache
            entity = self._dialogs_cache.get(channel_id.strip())
            
            if entity:
                logger.debug(f"✅ Found channel in cache: {entity.title} (ID: {channel_id})")
                return entity
            
            # Try without -100 prefix
            if channel_id.startswith('-100'):
                alt_id = channel_id[4:]
                entity = self._dialogs_cache.get(alt_id)
                if entity:
                    logger.debug(f"✅ Found channel in cache (alt ID): {entity.title}")
                    return entity
            
            logger.debug(f"⚠️ Channel {channel_id} not in cache ({len(self._dialogs_cache)} entries)")
            return None
                
        except Exception as e:
            logger.error(f"❌ Could not get entity for {channel_id}: {e}")
            return None
    
    async def get_all_channels_from_cache(self) -> Dict:
        """
        Get all channels from cache (FAST - no Telegram API calls)
        Returns categorized results from the loaded cache
        """
        await self.ensure_initialized()

        # Load cache if not loaded
        if not self._cache_loaded:
            await self.load_dialogs_cache()

        try:
            logger.info(f"📦 Getting channels from cache ({len(self._dialogs_cache)} entries)...")

            channels = []
            supergroups = []
            seen_ids = set()  # Track seen IDs to avoid duplicates

            for channel_id, entity in self._dialogs_cache.items():
                # Skip if we've already processed this entity (cache has multiple IDs per entity)
                entity_id = str(entity.id)
                if entity_id in seen_ids:
                    continue
                seen_ids.add(entity_id)

                # Skip photo downloads here — they are serialized network calls
                # that make this endpoint extremely slow (seconds per channel).
                # Photos can be fetched on demand via /channels/{id}/photo.
                channel_data = {
                    'title': entity.title,
                    'username': entity.username,
                    'id': entity_id,
                    'access_hash': str(entity.access_hash) if entity.access_hash else None,
                    'megagroup': entity.megagroup,
                    'broadcast': entity.broadcast,
                    'participants_count': getattr(entity, 'participants_count', None),
                    'photo_url': None
                }

                if entity.broadcast:
                    channels.append(channel_data)
                else:
                    supergroups.append(channel_data)

            logger.success(f"✅ Loaded {len(channels)} channels and {len(supergroups)} supergroups from cache")
            
            return {
                'statistics': {
                    'total_dialogs': len(channels) + len(supergroups),
                    'channels': len(channels),
                    'supergroups': len(supergroups),
                    'groups': 0,
                    'private_chats': 0
                },
                'channels': channels,
                'supergroups': supergroups,
                'groups': [],  # We don't cache regular groups
                'private_chats': []
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting channels from cache: {e}")
            raise
    
    async def fetch_all_channels(self) -> Dict:
        """
        Fetch all channels, groups, and chats from Telegram (SLOW - makes Telegram API calls)
        Returns categorized results similar to the original script
        Use get_all_channels_from_cache() for faster results
        """
        await self.ensure_initialized()

        try:
            logger.info("📡 Fetching all dialogs from Telegram...")

            dialogs = await self.client.get_dialogs()
            logger.info(f"📊 Total dialogs found: {len(dialogs)}")

            channels = []
            supergroups = []
            groups = []
            private_chats = []

            for dialog in dialogs:
                entity = dialog.entity

                # Skip photo downloads — serialized network calls make this endpoint
                # very slow. Photos can be fetched individually on demand.
                if isinstance(entity, Channel):
                    channel_data = {
                        'title': entity.title,
                        'username': entity.username,
                        'id': str(entity.id),
                        'access_hash': str(entity.access_hash) if entity.access_hash else None,
                        'megagroup': entity.megagroup,
                        'broadcast': entity.broadcast,
                        'participants_count': getattr(entity, 'participants_count', None),
                        'photo_url': None
                    }

                    if entity.broadcast:
                        channels.append(channel_data)
                    else:
                        supergroups.append(channel_data)

                elif isinstance(entity, Chat):
                    groups.append({
                        'title': entity.title,
                        'username': None,
                        'id': str(entity.id),
                        'participants_count': getattr(entity, 'participants_count', None),
                        'photo_url': None
                    })

                elif isinstance(entity, User) and not entity.is_self:
                    private_chats.append({
                        'title': entity.first_name or 'Unknown',
                        'username': entity.username,
                        'id': str(entity.id),
                        'access_hash': str(entity.access_hash) if entity.access_hash else None,
                        'bot': entity.bot,
                        'photo_url': None
                    })
            
            result = {
                'statistics': {
                    'total_dialogs': len(dialogs),
                    'channels': len(channels),
                    'supergroups': len(supergroups),
                    'groups': len(groups),
                    'private_chats': len(private_chats)
                },
                'channels': channels,
                'supergroups': supergroups,
                'groups': groups,
                'private_chats': private_chats
            }
            
            logger.success(f"✅ Fetched {len(channels)} channels, {len(supergroups)} supergroups")
            return result
            
        except Exception as e:
            logger.error(f"❌ Failed to fetch channels: {e}")
            raise
    
    async def get_channel_photo(self, channel_id: str) -> Optional[str]:
        """
        Get channel photo as base64 encoded string
        
        Args:
            channel_id: Channel ID (can be username or numeric ID)
            
        Returns:
            Base64 encoded photo or None
        """
        await self.ensure_initialized()
        
        try:
            entity = await self._get_entity_safe(channel_id)
            
            if entity and hasattr(entity, 'photo') and entity.photo:
                try:
                    photo = await self.client.download_profile_photo(entity, bytes)
                    if photo:
                        logger.debug(f"✅ Downloaded photo for {channel_id}")
                        return base64.b64encode(photo).decode('utf-8')
                except RuntimeError as e:
                    if "event loop" in str(e):
                        # Event loop changed - skip photo download
                        logger.debug(f"⏭️ Skipping photo for {channel_id} (event loop changed)")
                        return None
                    else:
                        raise
            
            logger.debug(f"No photo available for {channel_id}")
            return None
            
        except Exception as e:
            logger.debug(f"Could not fetch photo for {channel_id}: {e}")
            return None
    
    async def get_channel_info(self, channel_id: str) -> Optional[Dict]:
        """
        Get detailed information about a specific channel
        
        Args:
            channel_id: Channel ID (can be username or numeric ID)
            
        Returns:
            Channel information dictionary or None
        """
        await self.ensure_initialized()
        
        try:
            entity = await self._get_entity_safe(channel_id)
            
            if entity and isinstance(entity, Channel):
                logger.debug(f"✅ Got channel info for {channel_id}: {entity.title}")
                return {
                    'title': entity.title,
                    'username': entity.username,
                    'id': str(entity.id),
                    'access_hash': str(entity.access_hash) if entity.access_hash else None,
                    'megagroup': entity.megagroup,
                    'broadcast': entity.broadcast,
                    'participants_count': getattr(entity, 'participants_count', None),
                    'description': entity.about if hasattr(entity, 'about') else None
                }
            
            logger.debug(f"No channel info found for {channel_id}")
            return None
            
        except Exception as e:
            logger.error(f"❌ Failed to get channel info for {channel_id}: {e}")
            return None
    
    async def get_monitored_channels(self) -> List[Dict]:
        """
        Get all monitored channels from database using Prisma
        
        Returns:
            List of monitored channel dictionaries
        """
        try:
            channels = await prisma_client.client.monitoredchannel.find_many(
                where={'isActive': True},
                order={'createdAt': 'desc'}
            )
            
            return [
                {
                    'id': channel.id,
                    'channel_id': channel.channelId,
                    'channel_title': channel.channelTitle,
                    'channel_username': channel.channelUsername,
                    'access_hash': channel.accessHash,
                    'is_broadcast': channel.isBroadcast,
                    'is_megagroup': channel.isMegagroup,
                    'participants_count': channel.participantsCount,
                    'photo_url': channel.photoUrl,
                    'is_active': channel.isActive,
                    'added_at': channel.createdAt.isoformat() if channel.createdAt else None,
                    'last_updated': channel.updatedAt.isoformat() if channel.updatedAt else None,
                }
                for channel in channels
            ]
            
        except Exception as e:
            logger.error(f"❌ Failed to get monitored channels: {e}")
            raise
    
    async def add_monitored_channel(self, channel_data: Dict) -> bool:
        """
        Add a channel to monitored list using Prisma
        
        Args:
            channel_data: Dictionary with channel information
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Check if channel already exists
            existing = await prisma_client.client.monitoredchannel.find_unique(
                where={'channelId': channel_data['channel_id']}
            )
            
            if existing:
                # Update existing channel
                await prisma_client.client.monitoredchannel.update(
                    where={'channelId': channel_data['channel_id']},
                    data={
                        'channelTitle': channel_data.get('channel_title'),
                        'channelUsername': channel_data.get('channel_username'),
                        'accessHash': channel_data.get('access_hash'),
                        'isBroadcast': channel_data.get('is_broadcast', True),
                        'isMegagroup': channel_data.get('is_megagroup', False),
                        'participantsCount': channel_data.get('participants_count'),
                        'photoUrl': channel_data.get('photo_url'),
                        'isActive': True,
                    }
                )
                logger.info(f"✅ Updated monitored channel: {channel_data.get('channel_title', channel_data['channel_id'])}")
            else:
                # Create new channel
                await prisma_client.client.monitoredchannel.create(
                    data={
                        'channelId': channel_data['channel_id'],
                        'channelTitle': channel_data.get('channel_title'),
                        'channelUsername': channel_data.get('channel_username'),
                        'accessHash': channel_data.get('access_hash'),
                        'isBroadcast': channel_data.get('is_broadcast', True),
                        'isMegagroup': channel_data.get('is_megagroup', False),
                        'participantsCount': channel_data.get('participants_count'),
                        'photoUrl': channel_data.get('photo_url'),
                        'isActive': True,
                    }
                )
                logger.info(f"✅ Added new monitored channel: {channel_data.get('channel_title', channel_data['channel_id'])}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to add monitored channel: {e}")
            return False
    
    async def remove_monitored_channel(self, channel_id: str) -> bool:
        """
        Remove a channel from monitored list (soft delete - sets isActive to False)
        
        Args:
            channel_id: Channel ID to remove
            
        Returns:
            True if successful, False otherwise
        """
        try:
            channel = await prisma_client.client.monitoredchannel.find_unique(
                where={'channelId': channel_id}
            )
            
            if channel:
                await prisma_client.client.monitoredchannel.update(
                    where={'channelId': channel_id},
                    data={'isActive': False}
                )
                logger.info(f"✅ Removed monitored channel: {channel.channelTitle}")
                return True
            else:
                logger.warning(f"⚠️ Channel {channel_id} not found in monitored list")
                return False
                
        except Exception as e:
            logger.error(f"❌ Failed to remove monitored channel: {e}")
            return False
    
    async def update_channel_status(self, channel_id: str, is_active: bool) -> bool:
        """
        Update channel monitoring status
        
        Args:
            channel_id: Channel ID
            is_active: New active status
            
        Returns:
            True if successful, False otherwise
        """
        try:
            channel = await prisma_client.client.monitoredchannel.find_unique(
                where={'channelId': channel_id}
            )
            
            if channel:
                await prisma_client.client.monitoredchannel.update(
                    where={'channelId': channel_id},
                    data={'isActive': is_active}
                )
                status = "enabled" if is_active else "disabled"
                logger.info(f"✅ Channel monitoring {status}: {channel.channelTitle}")
                return True
            else:
                logger.warning(f"⚠️ Channel {channel_id} not found")
                return False
                
        except Exception as e:
            logger.error(f"❌ Failed to update channel status: {e}")
            return False
    
    async def disconnect(self):
        """Disconnect Telegram client"""
        if self.client and self.client.is_connected():
            await self.client.disconnect()
            logger.info("🔌 Telegram client disconnected")
            self._initialized = False


# Global singleton instance
telegram_channel_service_prisma = TelegramChannelServicePrisma()
