"""
Position data cache to reduce MetaAPI calls
Shares position data between multiple services
"""
import asyncio
from datetime import datetime
from typing import List, Dict, Optional
from loguru import logger


class PositionCache:
    """Cache for MetaAPI position and order data"""
    
    def __init__(self, cache_duration_seconds: int = 10):
        """
        Initialize position cache
        
        Args:
            cache_duration_seconds: How long to cache data (default: 10 seconds)
                                    Set to 0 to disable caching and always fetch fresh data
        """
        self.cache_duration = cache_duration_seconds
        self.positions_cache: List[Dict] = []
        self.positions_last_updated: Optional[datetime] = None
        self.orders_cache: Dict[int, List[Dict]] = {}  # magic_number -> orders
        self.orders_last_updated: Dict[int, datetime] = {}
        self.all_orders_cache: List[Dict] = []  # Cache for all pending orders
        self.all_orders_last_updated: Optional[datetime] = None
        self._lock = asyncio.Lock()
        
    def is_positions_cache_valid(self) -> bool:
        """Check if positions cache is still valid"""
        if not self.positions_last_updated:
            return False
        age = (datetime.now() - self.positions_last_updated).total_seconds()
        return age < self.cache_duration
        
    def is_orders_cache_valid(self, magic_number: int) -> bool:
        """Check if orders cache for a magic number is still valid"""
        if magic_number not in self.orders_last_updated:
            return False
        age = (datetime.now() - self.orders_last_updated[magic_number]).total_seconds()
        return age < self.cache_duration
        
    def is_all_orders_cache_valid(self) -> bool:
        """Check if all orders cache is still valid"""
        if not self.all_orders_last_updated:
            return False
        age = (datetime.now() - self.all_orders_last_updated).total_seconds()
        return age < self.cache_duration
        
    async def get_positions(self) -> Optional[List[Dict]]:
        """Get cached positions if valid"""
        async with self._lock:
            if self.is_positions_cache_valid():
                logger.debug(f"📦 Using cached positions ({len(self.positions_cache)} items)")
                return self.positions_cache.copy()
            return None
            
    async def set_positions(self, positions: List[Dict]):
        """Update positions cache"""
        async with self._lock:
            self.positions_cache = positions.copy() if positions else []
            self.positions_last_updated = datetime.now()
            logger.debug(f"💾 Cached {len(self.positions_cache)} position(s)")
            
    async def get_orders(self, magic_number: int) -> Optional[List[Dict]]:
        """Get cached orders for a magic number if valid"""
        async with self._lock:
            if self.is_orders_cache_valid(magic_number):
                orders = self.orders_cache.get(magic_number, [])
                logger.debug(f"📦 Using cached orders for magic {magic_number} ({len(orders)} items)")
                return orders.copy()
            return None
            
    async def set_orders(self, magic_number: int, orders: List[Dict]):
        """Update orders cache for a magic number"""
        async with self._lock:
            self.orders_cache[magic_number] = orders.copy() if orders else []
            self.orders_last_updated[magic_number] = datetime.now()
            logger.debug(f"💾 Cached {len(orders)} order(s) for magic {magic_number}")
            
    async def get_all_orders(self) -> Optional[List[Dict]]:
        """Get cached all orders if valid"""
        async with self._lock:
            if self.is_all_orders_cache_valid():
                logger.debug(f"📦 Using cached all orders ({len(self.all_orders_cache)} items)")
                return self.all_orders_cache.copy()
            return None
            
    async def set_all_orders(self, orders: List[Dict]):
        """Update all orders cache"""
        async with self._lock:
            self.all_orders_cache = orders.copy() if orders else []
            self.all_orders_last_updated = datetime.now()
            logger.debug(f"💾 Cached {len(orders)} pending order(s)")
            
    async def invalidate_positions(self):
        """Invalidate positions cache"""
        async with self._lock:
            self.positions_cache = []
            self.positions_last_updated = None
            logger.debug("🗑️ Invalidated positions cache")
            
    async def invalidate_orders(self, magic_number: Optional[int] = None):
        """Invalidate orders cache (all or specific magic number)"""
        async with self._lock:
            if magic_number:
                self.orders_cache.pop(magic_number, None)
                self.orders_last_updated.pop(magic_number, None)
                logger.debug(f"🗑️ Invalidated orders cache for magic {magic_number}")
            else:
                self.orders_cache = {}
                self.orders_last_updated = {}
                logger.debug("🗑️ Invalidated all orders cache")
            # Also invalidate all orders cache when any order changes
            self.all_orders_cache = []
            self.all_orders_last_updated = None
                
    async def invalidate_all(self):
        """Clear all caches"""
        async with self._lock:
            self.positions_cache = []
            self.positions_last_updated = None
            self.orders_cache = {}
            self.orders_last_updated = {}
            self.all_orders_cache = []
            self.all_orders_last_updated = None
            logger.debug("🗑️ Cleared all position caches")
            
    def get_cache_stats(self) -> Dict:
        """Get cache statistics"""
        positions_age = None
        if self.positions_last_updated:
            positions_age = (datetime.now() - self.positions_last_updated).total_seconds()
        
        all_orders_age = None
        if self.all_orders_last_updated:
            all_orders_age = (datetime.now() - self.all_orders_last_updated).total_seconds()
            
        return {
            "positions_count": len(self.positions_cache),
            "positions_age_seconds": positions_age,
            "positions_valid": self.is_positions_cache_valid(),
            "orders_magic_numbers": len(self.orders_cache),
            "all_orders_count": len(self.all_orders_cache),
            "all_orders_age_seconds": all_orders_age,
            "all_orders_valid": self.is_all_orders_cache_valid(),
            "cache_duration": self.cache_duration
        }


# Global position cache instance (10 second cache to reduce API calls)
# This reduces API calls by ~90% while keeping data fresh
position_cache = PositionCache(cache_duration_seconds=10)
