"""
Rate limit handling utilities for MetaAPI
Implements exponential backoff and retry logic
"""
import asyncio
from typing import Callable, Any
from functools import wraps
from loguru import logger


class RateLimitHandler:
    """Handles rate limiting with exponential backoff"""
    
    def __init__(self):
        self.is_rate_limited = False
        self.backoff_until = None
        self.consecutive_errors = 0
        
    def is_currently_limited(self) -> bool:
        """Check if we're currently in a rate limit backoff period"""
        if not self.is_rate_limited:
            return False
            
        import time
        if self.backoff_until and time.time() < self.backoff_until:
            return True
            
        # Backoff period is over
        self.is_rate_limited = False
        self.backoff_until = None
        self.consecutive_errors = 0
        return False
        
    def calculate_backoff_delay(self) -> int:
        """Calculate exponential backoff delay in seconds"""
        # Exponential backoff: 30s, 60s, 120s, 240s, 480s (max 8 minutes)
        base_delay = 30
        max_delay = 480
        delay = min(base_delay * (2 ** self.consecutive_errors), max_delay)
        return delay
        
    async def handle_rate_limit_error(self, error_msg: str):
        """Handle a rate limit error"""
        import time
        
        self.consecutive_errors += 1
        self.is_rate_limited = True
        
        delay = self.calculate_backoff_delay()
        self.backoff_until = time.time() + delay
        
        logger.warning(f"⏸️ Rate limit hit (error #{self.consecutive_errors})")
        logger.warning(f"⏳ Backing off for {delay}s before retrying...")
        logger.debug(f"Rate limit error: {error_msg}")
        
    def reset_backoff(self):
        """Reset backoff state after successful call"""
        if self.consecutive_errors > 0:
            logger.info(f"✅ Rate limit resolved after {self.consecutive_errors} error(s)")
        self.consecutive_errors = 0
        self.is_rate_limited = False
        self.backoff_until = None


# Global rate limit handler instance
rate_limit_handler = RateLimitHandler()


def is_rate_limit_error(error: Exception) -> bool:
    """Check if an error is a rate limit error"""
    error_str = str(error).lower()
    return any(keyword in error_str for keyword in [
        'rate limit',
        'cpu credits',
        'quota',
        'too many requests',
        '429'
    ])


def is_timeout_error(error: Exception) -> bool:
    """Check if an error is a timeout error"""
    error_str = str(error).lower()
    return any(keyword in error_str for keyword in [
        'timed out',
        'timeout',
        'connection timeout',
        'request timeout'
    ])


def with_rate_limit_handling(
    max_retries: int = 3,
    skip_on_rate_limit: bool = False
):
    """
    Decorator to handle rate limiting with exponential backoff
    
    Args:
        max_retries: Maximum number of retries
        skip_on_rate_limit: If True, return None on rate limit instead of retrying
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            # Check if we're in backoff period
            if rate_limit_handler.is_currently_limited():
                if skip_on_rate_limit:
                    logger.debug(f"⏭️ Skipping {func.__name__} - in rate limit backoff")
                    return None
                else:
                    # Wait for backoff period to end
                    import time
                    wait_time = max(0, rate_limit_handler.backoff_until - time.time())
                    if wait_time > 0:
                        logger.debug(f"⏳ Waiting {wait_time:.0f}s for backoff to end...")
                        await asyncio.sleep(wait_time)
            
            last_error = None
            for attempt in range(max_retries):
                try:
                    result = await func(*args, **kwargs)
                    
                    # Success - reset backoff
                    if attempt > 0 or rate_limit_handler.consecutive_errors > 0:
                        rate_limit_handler.reset_backoff()
                    
                    return result
                    
                except Exception as e:
                    last_error = e
                    
                    # Check if it's a rate limit error
                    if is_rate_limit_error(e):
                        await rate_limit_handler.handle_rate_limit_error(str(e))
                        
                        if skip_on_rate_limit:
                            logger.debug(f"⏭️ Skipping {func.__name__} due to rate limit")
                            return None
                        
                        # Wait for backoff delay before retry
                        if attempt < max_retries - 1:
                            delay = rate_limit_handler.calculate_backoff_delay()
                            logger.debug(f"⏳ Retry {attempt + 1}/{max_retries} after {delay}s...")
                            await asyncio.sleep(delay)
                    else:
                        # Not a rate limit error - raise immediately
                        raise
            
            # All retries exhausted
            logger.error(f"❌ {func.__name__} failed after {max_retries} attempts")
            raise last_error
            
        return wrapper
    return decorator
