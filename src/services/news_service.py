"""
News Service - Singleton instances for news trading and analysis
"""
from loguru import logger
from src.services.news_trading_service import NewsTradingService
from src.services.news_utils import news_utils

# Singleton instances
news_trading_service: NewsTradingService = None


def cleanup_news_cache_on_startup(cache_file: str = "data/news_cache.json"):
    """Clean up old events from cache file on startup"""
    try:
        removed_count = news_utils.cleanup_old_cache_events(cache_file)
        if removed_count > 0:
            logger.info(f"🧹 Startup cleanup: Removed {removed_count} old events")
        else:
            logger.debug("No old events to clean on startup")
    except Exception as e:
        logger.warning(f"Could not clean cache on startup: {e}")


def initialize_news_services(notification_service=None):
    """
    Initialize news services
    
    Args:
        notification_service: Optional notification service for alerts
    """
    global news_trading_service
    
    
    # Clean up old events from cache file on startup
    cleanup_news_cache_on_startup()
    
    # Initialize news trading service (news monitoring and blocking)
    news_trading_service = NewsTradingService(notification_service=notification_service)


async def start_news_monitoring():
    """Start the news monitoring service"""
    try:
        if not news_trading_service:
            logger.error("News trading service not initialized")
            return
        
        logger.info("🚀 Starting news monitoring services...")
        
        # Start news trading service monitoring
        logger.info("🚦 Starting news trading filter monitoring...")
        result = await news_trading_service.start_monitoring()
        if result:
            logger.info("✅ News trading filter monitoring started")
        else:
            logger.warning("⚠️ News trading filter monitoring disabled or failed")
        
        logger.info("✅ News monitoring services started successfully")
        
    except Exception as e:
        logger.error(f"❌ Error starting news monitoring: {e}", exc_info=True)
        raise


async def stop_news_monitoring():
    """Stop the news monitoring service"""
    if news_trading_service:
        await news_trading_service.stop_monitoring()
