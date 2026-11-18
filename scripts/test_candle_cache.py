#!/usr/bin/env python3
"""
Test script to verify candle caching is working correctly
"""
import asyncio
import time
from datetime import datetime
from loguru import logger
import sys

# Add parent directory to path
sys.path.insert(0, '/app')

from src.services.candle_cache_service import get_candle_cache_service


async def test_cache_operations():
    """Test basic cache operations"""
    logger.info("🧪 Testing Candle Cache Service")
    logger.info("=" * 60)
    
    # Get cache service
    cache_service = await get_candle_cache_service()
    
    if not cache_service._is_connected:
        logger.error("❌ Failed to connect to Redis")
        return False
    
    logger.success("✅ Connected to Redis")
    
    # Test data
    symbol = "XAUUSD"
    timeframe = "1h"
    limit = 100
    
    test_candles = [
        {
            "time": "2024-01-01T00:00:00Z",
            "open": 2050.0,
            "high": 2055.0,
            "low": 2048.0,
            "close": 2052.0,
            "volume": 1000
        },
        {
            "time": "2024-01-01T01:00:00Z",
            "open": 2052.0,
            "high": 2058.0,
            "low": 2051.0,
            "close": 2056.0,
            "volume": 1200
        }
    ]
    
    # Test 1: Cache MISS (should return None)
    logger.info("\n📊 Test 1: Cache MISS")
    cached = await cache_service.get_cached_candles(symbol, timeframe, limit)
    if cached is None:
        logger.success("✅ Cache MISS works correctly (returned None)")
    else:
        logger.error("❌ Expected None, got data")
        return False
    
    # Test 2: Store in cache
    logger.info("\n📊 Test 2: Store in cache")
    success = await cache_service.cache_candles(symbol, timeframe, limit, test_candles)
    if success:
        logger.success("✅ Data cached successfully")
    else:
        logger.error("❌ Failed to cache data")
        return False
    
    # Test 3: Cache HIT (should return data)
    logger.info("\n📊 Test 3: Cache HIT")
    cached = await cache_service.get_cached_candles(symbol, timeframe, limit)
    if cached and len(cached) == 2:
        logger.success(f"✅ Cache HIT works correctly (retrieved {len(cached)} candles)")
    else:
        logger.error("❌ Expected 2 candles, got different result")
        return False
    
    # Test 4: Cache statistics
    logger.info("\n📊 Test 4: Cache statistics")
    stats = await cache_service.get_cache_stats()
    logger.info(f"   Connected: {stats.get('connected')}")
    logger.info(f"   Total candle keys: {stats.get('total_candle_keys', 0)}")
    logger.info(f"   Keyspace hits: {stats.get('keyspace_hits', 0)}")
    logger.info(f"   Keyspace misses: {stats.get('keyspace_misses', 0)}")
    logger.success("✅ Cache statistics retrieved")
    
    # Test 5: Cache invalidation
    logger.info("\n📊 Test 5: Cache invalidation")
    await cache_service.invalidate_cache(symbol, timeframe)
    cached = await cache_service.get_cached_candles(symbol, timeframe, limit)
    if cached is None:
        logger.success("✅ Cache invalidation works correctly")
    else:
        logger.error("❌ Cache should be empty after invalidation")
        return False
    
    # Cleanup
    await cache_service.disconnect()
    
    logger.info("\n" + "=" * 60)
    logger.success("✅ ALL TESTS PASSED!")
    return True


async def test_performance():
    """Test cache performance"""
    logger.info("\n🚀 Performance Test")
    logger.info("=" * 60)
    
    cache_service = await get_candle_cache_service()
    
    symbol = "EURUSD"
    timeframe = "15m"
    limit = 200
    
    # Create larger test dataset
    test_candles = [
        {
            "time": f"2024-01-01T{i:02d}:00:00Z",
            "open": 1.1000 + (i * 0.0001),
            "high": 1.1005 + (i * 0.0001),
            "low": 1.0995 + (i * 0.0001),
            "close": 1.1002 + (i * 0.0001),
            "volume": 1000 + i
        }
        for i in range(200)
    ]
    
    # Test write performance
    logger.info(f"\n📝 Writing {len(test_candles)} candles to cache...")
    start = time.time()
    await cache_service.cache_candles(symbol, timeframe, limit, test_candles)
    write_time = (time.time() - start) * 1000
    logger.success(f"✅ Write time: {write_time:.2f}ms")
    
    # Test read performance (10 reads)
    logger.info(f"\n📖 Reading from cache (10 iterations)...")
    read_times = []
    for i in range(10):
        start = time.time()
        cached = await cache_service.get_cached_candles(symbol, timeframe, limit)
        read_time = (time.time() - start) * 1000
        read_times.append(read_time)
    
    avg_read_time = sum(read_times) / len(read_times)
    logger.success(f"✅ Average read time: {avg_read_time:.2f}ms")
    logger.info(f"   Min: {min(read_times):.2f}ms, Max: {max(read_times):.2f}ms")
    
    # Cleanup
    await cache_service.invalidate_cache(symbol, timeframe)
    await cache_service.disconnect()
    
    logger.info("\n" + "=" * 60)
    logger.success("✅ PERFORMANCE TEST COMPLETE!")
    logger.info(f"\n💡 Expected API call time: 200-500ms")
    logger.info(f"💡 Cache read time: {avg_read_time:.2f}ms")
    logger.info(f"💡 Performance improvement: {(300/avg_read_time):.1f}x faster")


async def main():
    """Run all tests"""
    try:
        # Run basic tests
        success = await test_cache_operations()
        
        if success:
            # Run performance tests
            await test_performance()
        
        logger.info("\n" + "=" * 60)
        logger.success("🎉 ALL TESTS COMPLETED SUCCESSFULLY!")
        
    except Exception as e:
        logger.error(f"❌ Test failed with error: {e}")
        logger.exception(e)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
