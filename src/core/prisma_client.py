"""
Prisma Database Client
Centralized database access with proper connection management
"""
from prisma import Prisma
from loguru import logger
from typing import Optional
import asyncio


class PrismaClient:
    """
    Singleton Prisma client for database operations
    Handles connection lifecycle and provides access to database
    """
    
    _instance: Optional['PrismaClient'] = None
    _client: Optional[Prisma] = None
    _initialized: bool = False
    _reconnect_attempts: int = 0
    _max_reconnect_attempts: int = 3
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    async def initialize(self):
        """Initialize Prisma client and connect to database"""
        if self._initialized:
            logger.warning("Prisma client already initialized")
            return
        
        try:
            logger.info("💾 Initializing Prisma database client...")
            
            self._client = Prisma()
            await self._client.connect()

            # Enable WAL mode for better concurrent read/write performance.
            # WAL allows readers and the writer to proceed without blocking each other,
            # which is essential when the position monitor (3 s loop), trading bot, and
            # dashboard all access the same SQLite file simultaneously.
            try:
                await self._client.query_raw("PRAGMA journal_mode=WAL")
                await self._client.query_raw("PRAGMA busy_timeout=30000")
                await self._client.query_raw("PRAGMA synchronous=NORMAL")
                logger.info("✅ SQLite WAL mode enabled")
            except Exception as _wal_err:
                logger.warning(f"⚠️ Could not enable WAL mode: {_wal_err}")

            self._initialized = True
            self._reconnect_attempts = 0
            logger.success("✅ Prisma database connected")
            
        except RuntimeError as e:
            if "event loop" in str(e):
                # Already initialized in different event loop
                logger.warning("⚠️ Prisma client already initialized in different event loop, using existing connection")
                self._initialized = True
            else:
                logger.error(f"❌ Failed to initialize Prisma: {str(e)}")
                raise
        except Exception as e:
            logger.error(f"❌ Failed to initialize Prisma: {str(e)}")
            raise
    
    async def disconnect(self):
        """Disconnect from database"""
        if self._client and self._initialized:
            try:
                await self._client.disconnect()
                self._initialized = False
                logger.info("💾 Prisma database disconnected")
            except Exception as e:
                logger.error(f"❌ Error disconnecting Prisma: {str(e)}")
    
    async def ensure_connected(self) -> bool:
        """
        Ensure database is connected, attempt reconnection if not
        Returns True if connected, False otherwise
        """
        if self._initialized and self._client:
            try:
                # Test connection with a simple query
                await self._client.query_raw("SELECT 1")
                self._reconnect_attempts = 0  # Reset counter on successful connection
                return True
            except Exception as e:
                logger.warning(f"⚠️ Database connection test failed: {str(e)}")
                self._initialized = False
        
        # Attempt to reconnect
        if self._reconnect_attempts < self._max_reconnect_attempts:
            self._reconnect_attempts += 1
            logger.info(f"🔄 Attempting to reconnect to database (attempt {self._reconnect_attempts}/{self._max_reconnect_attempts})...")
            
            try:
                if self._client:
                    try:
                        await self._client.disconnect()
                    except Exception as _exc:
                        logger.debug(f"Suppressed exception: {_exc!r}")
                
                self._client = Prisma()
                await self._client.connect()
                self._initialized = True
                self._reconnect_attempts = 0
                logger.success("✅ Database reconnected successfully")
                return True
                
            except Exception as e:
                logger.error(f"❌ Reconnection attempt {self._reconnect_attempts} failed: {str(e)}")
                
                # Wait before next attempt
                if self._reconnect_attempts < self._max_reconnect_attempts:
                    await asyncio.sleep(2 ** self._reconnect_attempts)  # Exponential backoff
                
                return False
        else:
            logger.error(f"❌ Max reconnection attempts ({self._max_reconnect_attempts}) reached")
            return False
    
    @property
    def client(self) -> Prisma:
        """Get Prisma client instance"""
        if not self._initialized or not self._client:
            raise RuntimeError("Prisma client not initialized. Call initialize() first.")
        return self._client
    
    @property
    def is_connected(self) -> bool:
        """Check if database is connected"""
        return self._initialized and self._client is not None


# Singleton instance
prisma_client = PrismaClient()
