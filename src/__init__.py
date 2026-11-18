"""
Source Package
Exports for backwards compatibility - imports from new organized structure
"""

# Models
from src.models import (
    TradingSignal,
    SignalAction,
    SignalType,
    SignalStatus,
    OrderType,
    AccountInfo,
    TradeResult,
    RiskAssessment,
)

# Services (backwards compatibility aliases)
# NOTE: signal_service is imported lazily to avoid initialization before settings are loaded
# It's imported where needed after settings.reload_from_db() is called
from src.services.trading_service import trading_service
from src.services.risk_service import risk_manager

# Integrations
from src.integrations.telegram.listener import TelethonListener
from src.integrations.telegram.sender import notification_sender

# Core - Legacy SQLAlchemy database removed, now using Prisma
# from src.core.database import database

__all__ = [
    # Models
    'TradingSignal',
    'SignalAction',
    'SignalType',
    'SignalStatus',
    'OrderType',
    'AccountInfo',
    'TradeResult',
    'RiskAssessment',
    # Services
    'signal_service',
    'trading_service',
    'risk_manager',
    # Integrations
    'TelethonListener',
    'notification_sender',
]
