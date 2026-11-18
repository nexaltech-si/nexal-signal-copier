"""
Services Package
Business logic layer for the trading bot
"""
# NOTE: signal_service is imported lazily to avoid initialization before settings are loaded
# It's imported where needed after settings.reload_from_db() is called
from .trading_service import trading_service
from .risk_service import risk_manager
from .notification_service import notification_sender
from .risk_management_service import risk_management_service
from .drawdown_protection_service import drawdown_protection_service
from .drawdown_monitor_service import drawdown_monitor_service
from .position_monitor_service import position_monitor_service
from .news_service import (
    news_trading_service,
    initialize_news_services,
    start_news_monitoring,
    stop_news_monitoring
)
from .health_check_service import health_check_service

__all__ = [
    'trading_service',
    'risk_manager',
    'notification_sender',
    'risk_management_service',
    'drawdown_protection_service',
    'drawdown_monitor_service',
    'position_monitor_service',
    'news_trading_service',
    'initialize_news_services',
    'start_news_monitoring',
    'stop_news_monitoring',
    'health_check_service',
]
