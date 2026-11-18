#!/usr/bin/env python3
"""
Redis MT5 Data Publisher
Fetches tick data from MT5 REST API and publishes to Redis channels.
"""
import asyncio
import aiohttp
import json
import os
import time
import logging
from typing import Optional

import redis

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
MT5_REST_API_URL = os.environ.get('MT5_REST_API_URL', 'http://mt5:5001')
MT5_REST_API_KEY = os.environ.get('MT5_REST_API_KEY', '')
REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379')
SYMBOLS = os.environ.get('MT5_SYMBOLS', 'XAUUSD,EURUSD,GBPUSD').split(',')
UPDATE_INTERVAL = float(os.environ.get('MT5_UPDATE_INTERVAL', '0.5'))


class MT5RedisPublisher:
    """Publishes MT5 tick data to Redis."""
    
    def __init__(self):
        self.redis_client: Optional[redis.Redis] = None
        self.session: Optional[aiohttp.ClientSession] = None
        self.running = False
        
    async def connect_redis(self):
        """Connect to Redis."""
        try:
            self.redis_client = redis.from_url(REDIS_URL, decode_responses=True)
            self.redis_client.ping()
            logger.info(f"Connected to Redis: {REDIS_URL}")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise
    
    async def connect_mt5(self):
        """Create HTTP session for MT5 REST API."""
        self.session = aiohttp.ClientSession()
        logger.info(f"MT5 REST API session created: {MT5_REST_API_URL}")
    
    async def fetch_tick(self, symbol: str) -> Optional[dict]:
        """Fetch tick data from MT5 REST API."""
        try:
            headers = {'Content-Type': 'application/json'}
            if MT5_REST_API_KEY:
                headers['X-API-Key'] = MT5_REST_API_KEY
            
            url = f"{MT5_REST_API_URL.rstrip('/')}/symbol_tick?symbol={symbol}"
            async with self.session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    return data
                else:
                    logger.warning(f"Failed to fetch tick for {symbol}: HTTP {response.status}")
                    return None
        except Exception as e:
            logger.error(f"Error fetching tick for {symbol}: {e}")
            return None
    
    async def publish_tick(self, symbol: str, tick_data: dict):
        """Publish tick data to Redis channel."""
        try:
            channel = f"ticks:{symbol}"
            message = json.dumps(tick_data)
            self.redis_client.publish(channel, message)
            logger.debug(f"Published tick to {channel}: {tick_data}")
        except Exception as e:
            logger.error(f"Error publishing tick for {symbol}: {e}")
    
    async def fetch_and_publish(self, symbol: str):
        """Fetch and publish tick for a symbol."""
        tick_data = await self.fetch_tick(symbol)
        if tick_data:
            await self.publish_tick(symbol, tick_data)
    
    async def run(self):
        """Main loop to fetch and publish ticks."""
        self.running = True
        
        while self.running:
            try:
                # Fetch ticks for all symbols in parallel
                tasks = [self.fetch_and_publish(symbol) for symbol in SYMBOLS]
                await asyncio.gather(*tasks)
                
                # Wait before next update
                await asyncio.sleep(UPDATE_INTERVAL)
                
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                await asyncio.sleep(1)
    
    async def stop(self):
        """Stop the publisher."""
        self.running = False
        if self.session:
            await self.session.close()
        if self.redis_client:
            self.redis_client.close()
        logger.info("Publisher stopped")


async def main():
    """Main entry point."""
    publisher = MT5RedisPublisher()
    
    try:
        await publisher.connect_redis()
        await publisher.connect_mt5()
        logger.info(f"Starting publisher for symbols: {SYMBOLS}")
        await publisher.run()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        await publisher.stop()


if __name__ == '__main__':
    asyncio.run(main())
