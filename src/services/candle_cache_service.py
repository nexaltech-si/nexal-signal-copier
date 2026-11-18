"""
Redis-based candle caching service for market data
Reduces API calls and improves performance
"""
import json
import asyncio
from typing import Optional, List, Dict
from loguru import logger

try:
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning("redis package not available - candle caching disabled")


class CandleCacheService:
    """Manages Redis caching for historical candle data"""
    
    def __init__(self, redis_url: str = "redis://trading-redis:6379"):
        self.redis_url = redis_url
        self.redis_client: Optional[aioredis.Redis] = None
        self._is_connected = False
        self._connection_lock = asyncio.Lock()
        
        # Cache TTL settings (in seconds)
        # Balanced for performance vs freshness - shorter TTL for active trading timeframes
        self.cache_ttl = {
            '1m': 30,      # 1 minute candles: cache for 30 seconds (very active)
            '5m': 120,     # 5 minute candles: cache for 2 minutes
            '15m': 300,    # 15 minute candles: cache for 5 minutes (dashboard charts)
            '30m': 600,    # 30 minute candles: cache for 10 minutes
            '1h': 600,     # 1 hour candles: cache for 10 minutes (trading analysis)
            '4h': 1800,    # 4 hour candles: cache for 30 minutes
            '1d': 3600,    # Daily candles: cache for 1 hour
            '1w': 7200,    # Weekly candles: cache for 2 hours
            '1M': 14400,   # Monthly candles: cache for 4 hours
        }
    
    async def connect(self) -> bool:
        """Connect to Redis server"""
        if not REDIS_AVAILABLE:
            logger.warning("Redis not available - caching disabled")
            return False
        
        if self._is_connected and self.redis_client:
            return True
        
        async with self._connection_lock:
            if self._is_connected and self.redis_client:
                return True
            
            try:
                self.redis_client = await aioredis.from_url(
                    self.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5
                )
                
                # Test connection
                await self.redis_client.ping()
                self._is_connected = True
                logger.success("✅ Candle cache service connected to Redis")
                return True
                
            except Exception as e:
                logger.warning(f"⚠️ Failed to connect to Redis for candle caching: {e}")
                self._is_connected = False
                self.redis_client = None
                return False
    
    async def disconnect(self):
        """Disconnect from Redis"""
        if self.redis_client:
            try:
                await self.redis_client.close()
                logger.info("Candle cache service disconnected from Redis")
            except Exception as e:
                logger.warning(f"Error disconnecting from Redis: {e}")
            finally:
                self.redis_client = None
                self._is_connected = False
    
    def _generate_cache_key(self, symbol: str, timeframe: str, limit: int) -> str:
        """Generate Redis cache key for candle data"""
        return f"candles:{symbol}:{timeframe}:{limit}"
    
    async def get_cached_candles(
        self,
        symbol: str,
        timeframe: str,
        limit: int
    ) -> Optional[List[Dict]]:
        """
        Retrieve cached candle data from Redis
        
        Args:
            symbol: Trading symbol
            timeframe: Candle timeframe (e.g., '1h', '15m')
            limit: Number of candles
            
        Returns:
            List of candle dicts or None if not cached
        """
        if not self._is_connected or not self.redis_client:
            return None
        
        try:
            cache_key = self._generate_cache_key(symbol, timeframe, limit)
            cached_data = await self.redis_client.get(cache_key)
            
            if cached_data:
                candles = json.loads(cached_data)
                logger.debug(f"📊 Cache HIT for {cache_key} ({len(candles)} candles)")
                return candles
            
            logger.debug(f"📊 Cache MISS for {cache_key}")
            return None
            
        except Exception as e:
            logger.warning(f"Error reading from candle cache: {e}")
            return None
    
    async def cache_candles(
        self,
        symbol: str,
        timeframe: str,
        limit: int,
        candles: List[Dict]
    ) -> bool:
        """
        Store candle data in Redis cache
        
        Args:
            symbol: Trading symbol
            timeframe: Candle timeframe
            limit: Number of candles
            candles: List of candle dicts to cache
            
        Returns:
            True if cached successfully, False otherwise
        """
        if not self._is_connected or not self.redis_client:
            return False
        
        try:
            cache_key = self._generate_cache_key(symbol, timeframe, limit)
            ttl = self.cache_ttl.get(timeframe, 600)  # Default 10 minutes
            
            # Serialize candles to JSON
            candles_json = json.dumps(candles)
            
            # Store in Redis with TTL
            await self.redis_client.setex(cache_key, ttl, candles_json)
            
            logger.debug(f"📊 Cached {len(candles)} candles for {cache_key} (TTL: {ttl}s)")
            return True
            
        except Exception as e:
            logger.warning(f"Error writing to candle cache: {e}")
            return False
    
    async def invalidate_cache(self, symbol: str, timeframe: str = None):
        """
        Invalidate cached candles for a symbol
        
        Args:
            symbol: Trading symbol
            timeframe: Optional specific timeframe to invalidate (invalidates all if None)
        """
        if not self._is_connected or not self.redis_client:
            return
        
        try:
            if timeframe:
                # Invalidate specific timeframe
                pattern = f"candles:{symbol}:{timeframe}:*"
            else:
                # Invalidate all timeframes for symbol
                pattern = f"candles:{symbol}:*"
            
            # Find and delete matching keys
            cursor = 0
            deleted_count = 0
            while True:
                cursor, keys = await self.redis_client.scan(cursor, match=pattern, count=100)
                if keys:
                    deleted_count += await self.redis_client.delete(*keys)
                if cursor == 0:
                    break
            
            if deleted_count > 0:
                logger.info(f"🗑️ Invalidated {deleted_count} cached candle entries for {symbol}")
                
        except Exception as e:
            logger.warning(f"Error invalidating candle cache: {e}")
    
    async def get_cache_stats(self) -> Dict:
        """Get cache statistics"""
        if not self._is_connected or not self.redis_client:
            return {"connected": False}
        
        try:
            info = await self.redis_client.info("stats")
            
            # Count candle cache keys
            cursor = 0
            key_count = 0
            while True:
                cursor, keys = await self.redis_client.scan(cursor, match="candles:*", count=100)
                key_count += len(keys)
                if cursor == 0:
                    break
            
            return {
                "connected": True,
                "total_candle_keys": key_count,
                "keyspace_hits": info.get("keyspace_hits", 0),
                "keyspace_misses": info.get("keyspace_misses", 0),
            }
            
        except Exception as e:
            logger.warning(f"Error getting cache stats: {e}")
            return {"connected": True, "error": str(e)}


# Global singleton instance
_candle_cache_service: Optional[CandleCacheService] = None


async def get_candle_cache_service(redis_url: str = None) -> CandleCacheService:
    """Get or create the global candle cache service instance"""
    global _candle_cache_service
    
    if _candle_cache_service is None:
        if redis_url is None:
            # Try to get from environment or use default
            import os
            redis_url = os.getenv("REDIS_URL", "redis://trading-redis:6379")
        
        _candle_cache_service = CandleCacheService(redis_url)
        await _candle_cache_service.connect()
    
    return _candle_cache_service
