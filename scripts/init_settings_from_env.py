#!/usr/bin/env python3
"""
Initialize settings from .env file to database
This script reads environment variables and initializes them in the database.

Run once, automatically, when the database is created (scripts/init_database.sh).
After that the database is the source of truth and settings are changed in the
dashboard; running this again by hand overwrites them with the values in .env.
"""
import asyncio
import os
import sys
from dotenv import load_dotenv
from loguru import logger

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import directly to avoid triggering src/__init__.py imports
from src.core.prisma_client import prisma_client
from src.services.settings_service import get_settings_service

# Load environment variables
load_dotenv()

# Map environment variable names to setting keys
ENV_TO_SETTING_MAP = {
    # Credentials (stored encrypted in DB; bot loads them at startup instead of .env)
    "METAAPI_TOKEN":                    "METAAPI_TOKEN",
    "METAAPI_ACCOUNT_ID":               "METAAPI_ACCOUNT_ID",
    "MT5_REST_API_KEY":                 "MT5_REST_API_KEY",
    "OPENAI_API_KEY":                   "OPENAI_API_KEY",
    "DEEPSEEK_API_KEY":                 "DEEPSEEK_API_KEY",
    "TELEGRAM_BOT_TOKEN":               "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHANNEL_ID":              "TELEGRAM_CHANNEL_ID",
    "TELEGRAM_NOTIFICATION_CHAT_ID":    "TELEGRAM_NOTIFICATION_CHAT_ID",

    # Risk Management
    "MAX_RISK_PER_TRADE_PERCENT": "MAX_RISK_PER_TRADE_PERCENT",
    "MAX_OPEN_POSITIONS": "MAX_OPEN_POSITIONS",
    "DEFAULT_STOP_LOSS_PIPS": "DEFAULT_STOP_LOSS_PIPS",
    "DEFAULT_TAKE_PROFIT_PIPS": "DEFAULT_TAKE_PROFIT_PIPS",
    "RISK_REWARD_RATIO": "RISK_REWARD_RATIO",
    "SPREAD_ADJUSTMENT_MULTIPLIER": "SPREAD_ADJUSTMENT_MULTIPLIER",
    "ENABLE_EQUITY_PROTECTION": "ENABLE_EQUITY_PROTECTION",
    "DAILY_DRAWDOWN_LIMIT_PERCENT": "DAILY_DRAWDOWN_LIMIT_PERCENT",
    "OVERALL_DRAWDOWN_LIMIT_PERCENT": "OVERALL_DRAWDOWN_LIMIT_PERCENT",
    "ENABLE_DRAWDOWN_MONITORING": "ENABLE_DRAWDOWN_MONITORING",
    
    # Trading
    "MIN_LOT_SIZE": "MIN_LOT_SIZE",
    "MAX_LOT_SIZE": "MAX_LOT_SIZE",
    "SLIPPAGE_PIPS": "SLIPPAGE_PIPS",
    "MAX_SIGNAL_AGE_MINUTES": "MAX_SIGNAL_AGE_MINUTES",
    "ENABLE_INSTANT_EXECUTION": "ENABLE_INSTANT_EXECUTION",
    "INSTANT_EXECUTION_CHANNELS": "INSTANT_EXECUTION_CHANNELS",
    "INSTANT_EXECUTION_KEYWORDS": "INSTANT_EXECUTION_KEYWORDS",
    "INSTANT_EXECUTION_MAX_DEVIATION_PIPS": "INSTANT_EXECUTION_MAX_DEVIATION_PIPS",
    "INSTANT_ONE_LEG_MAX_TP1_PROGRESS": "INSTANT_ONE_LEG_MAX_TP1_PROGRESS",
    "INSTANT_TEMP_SL_PIPS": "INSTANT_TEMP_SL_PIPS",
    "INSTANT_FIRST_ENTRY_RISK_SHARE": "INSTANT_FIRST_ENTRY_RISK_SHARE",
    "SIGNAL_CONTINUITY_WINDOW_MINUTES": "SIGNAL_CONTINUITY_WINDOW_MINUTES",
    "SAME_LEVEL_TOLERANCE_PIPS": "SAME_LEVEL_TOLERANCE_PIPS",
    
    # Auto TP
    "ENABLE_AUTO_TAKE_PROFIT": "ENABLE_AUTO_TAKE_PROFIT",
    "AUTO_TP_CALCULATION_METHOD": "AUTO_TP_CALCULATION_METHOD",
    "AUTO_TP_PIPS": "AUTO_TP_PIPS",
    "AUTO_TP_RISK_REWARD": "AUTO_TP_RISK_REWARD",
    
    # Trailing Stop
    "ENABLE_TRAILING_STOP": "ENABLE_TRAILING_STOP",
    "TRAILING_STOP_CALCULATION_METHOD": "TRAILING_STOP_CALCULATION_METHOD",
    "TRAILING_STOP_DISTANCE_PIPS": "TRAILING_STOP_DISTANCE_PIPS",
    "TRAILING_STOP_DISTANCE_RR": "TRAILING_STOP_DISTANCE_RR",
    "TRAILING_ACTIVATION_METHOD": "TRAILING_ACTIVATION_METHOD",
    "TRAILING_ACTIVATION_PROFIT_PIPS": "TRAILING_ACTIVATION_PROFIT_PIPS",
    "TRAILING_ACTIVATION_PROFIT_RR": "TRAILING_ACTIVATION_PROFIT_RR",
    
    # Auto Partial
    "ENABLE_AUTO_PARTIAL": "ENABLE_AUTO_PARTIAL",
    "AUTO_PARTIAL_CALCULATION_METHOD": "AUTO_PARTIAL_CALCULATION_METHOD",
    "AUTO_PARTIAL_TRIGGER_PIPS": "AUTO_PARTIAL_TRIGGER_PIPS",
    "AUTO_PARTIAL_TRIGGER_RR": "AUTO_PARTIAL_TRIGGER_RR",
    "AUTO_PARTIAL_CLOSE_PERCENT": "AUTO_PARTIAL_CLOSE_PERCENT",

    # Runner
    "ENABLE_RUNNER_SPLIT": "ENABLE_RUNNER_SPLIT",
    "RUNNER_SHARE_PERCENT": "RUNNER_SHARE_PERCENT",
    
    # Breakeven
    "ENABLE_BREAKEVEN_MOVE": "ENABLE_BREAKEVEN_MOVE",
    "BREAKEVEN_TRIGGER_METHOD": "BREAKEVEN_TRIGGER_METHOD",
    "BREAKEVEN_TRIGGER_PIPS": "BREAKEVEN_TRIGGER_PIPS",
    "BREAKEVEN_BUFFER_PIPS": "BREAKEVEN_BUFFER_PIPS",
    
    # Position Monitoring
    "POSITION_MONITOR_INTERVAL_SECONDS": "POSITION_MONITOR_INTERVAL_SECONDS",
    "ENABLE_POSITION_MONITORING": "ENABLE_POSITION_MONITORING",
    
    # Trading Brain
    "ENABLE_TRADING_BRAIN": "ENABLE_TRADING_BRAIN",
    "BRAIN_BASE_URL": "BRAIN_BASE_URL",
    "BRAIN_API_KEY": "BRAIN_API_KEY",
    "BRAIN_MODEL": "BRAIN_MODEL",
    "BRAIN_TEMPERATURE": "BRAIN_TEMPERATURE",
    "BRAIN_MAX_HISTORY_MESSAGES": "BRAIN_MAX_HISTORY_MESSAGES",
    "BRAIN_POSITION_REVIEW_INTERVAL": "BRAIN_POSITION_REVIEW_INTERVAL",

    # AI Features
    "ENABLE_AI_MARKET_ANALYSIS": "ENABLE_AI_MARKET_ANALYSIS",
    "AI_ANALYSIS_CHECK_INTERVAL": "AI_ANALYSIS_CHECK_INTERVAL",
    "ENABLE_AI_BREAKEVEN_TRIGGERS": "ENABLE_AI_BREAKEVEN_TRIGGERS",
    "ENABLE_AI_TP_ADJUSTMENT": "ENABLE_AI_TP_ADJUSTMENT",
    "ENABLE_AI_POSITION_REDUCTION": "ENABLE_AI_POSITION_REDUCTION",
    "AI_ANALYSIS_CONFIDENCE_THRESHOLD": "AI_ANALYSIS_CONFIDENCE_THRESHOLD",
    "AI_AUTO_VERIFICATION_ENABLED": "AI_AUTO_VERIFICATION_ENABLED",
    
    # AI Provider Configuration (keys already listed under Credentials above)
    "OPENAI_MODEL": "OPENAI_MODEL",
    "DEEPSEEK_API_URL": "DEEPSEEK_API_URL",
    "DEEPSEEK_MODEL": "DEEPSEEK_MODEL",
    "OLLAMA_URL": "OLLAMA_URL",
    "OLLAMA_MODEL": "OLLAMA_MODEL",
    "PRIMARY_AI_PROVIDER": "PRIMARY_AI_PROVIDER",
    "FALLBACK_AI_PROVIDERS": "FALLBACK_AI_PROVIDERS",
    
    # Approval
    "REQUIRE_MANUAL_APPROVAL": "REQUIRE_MANUAL_APPROVAL",
    "APPROVAL_REQUIRED_CHANNELS": "APPROVAL_REQUIRED_CHANNELS",
    "APPROVAL_CHANNEL_ID": "APPROVAL_CHANNEL_ID",
    "APPROVAL_TIMEOUT_MINUTES": "APPROVAL_TIMEOUT_MINUTES",
    
    # News
    "NEWS_ENABLE_FILTER": "NEWS_ENABLE_FILTER",
    "NEWS_MINUTES_BEFORE": "NEWS_MINUTES_BEFORE",
    "NEWS_MINUTES_AFTER": "NEWS_MINUTES_AFTER",
    "NEWS_IMPORTANT_IMPACTS": "NEWS_IMPORTANT_IMPACTS",
    "NEWS_TARGET_CURRENCIES": "NEWS_TARGET_CURRENCIES",
    "NEWS_VERBOSE_LOGGING": "NEWS_VERBOSE_LOGGING",
    "NEWS_ENABLE_NOTIFICATIONS": "NEWS_ENABLE_NOTIFICATIONS",
    "NEWS_NOTIFICATION_MINUTES_BEFORE": "NEWS_NOTIFICATION_MINUTES_BEFORE",
    "NEWS_API_URL": "NEWS_API_URL",
    "NEWS_POST_ENABLED": "NEWS_POST_ENABLED",
    "NEWS_POST_CHANNEL_ID": "NEWS_POST_CHANNEL_ID",
    "NEWS_POST_IMPACTS": "NEWS_POST_IMPACTS",
    "NEWS_POST_CURRENCIES": "NEWS_POST_CURRENCIES",
    "NEWS_POST_MINUTES_BEFORE": "NEWS_POST_MINUTES_BEFORE",
    
    # Telegram
    "TELEGRAM_CHANNEL_ID": "TELEGRAM_CHANNEL_ID",
    "TELEGRAM_NOTIFICATION_CHAT_ID": "TELEGRAM_NOTIFICATION_CHAT_ID",
    
    # Signal Validator
    "ENABLE_SIGNAL_VALIDATOR": "ENABLE_SIGNAL_VALIDATOR",
    "SIGNAL_VALIDATOR_URL": "SIGNAL_VALIDATOR_URL",
    "SIGNAL_VALIDATOR_TIMEOUT_SECONDS": "SIGNAL_VALIDATOR_TIMEOUT_SECONDS",
    "SIGNAL_VALIDATOR_EXECUTION_POLICY": "SIGNAL_VALIDATOR_EXECUTION_POLICY",
    
    # General Settings
    "LOG_LEVEL": "LOG_LEVEL",
    "LOG_FILE_LEVEL": "LOG_FILE_LEVEL",
    "LOG_FILE_DEBUG": "LOG_FILE_DEBUG",
    "DRY_RUN": "DRY_RUN",
    "TIMEZONE": "TIMEZONE",
    
    # Trading Provider
    "TRADING_PROVIDER": "TRADING_PROVIDER",
    "MT5_REST_API_URL": "MT5_REST_API_URL",
    "MT5_WS_PORT": "MT5_WS_PORT",
    "MT5_WS_HOST": "MT5_WS_HOST",
    "MT5_SYMBOL_SUFFIX": "MT5_SYMBOL_SUFFIX",
}


async def main():
    """Initialize settings from .env file"""
    logger.info("🚀 Initializing settings from .env file to database...")
    
    # Initialize Prisma
    await prisma_client.initialize()
    
    # Get settings service
    encryption_key = os.getenv("SETTINGS_ENCRYPTION_KEY")
    settings_service = await get_settings_service(prisma_client.client, encryption_key=encryption_key)
    
    # Every setting the database seeds a default for can be given in .env: without this
    # import the database default would win (e.g. TRADING_PROVIDER=mt5rest in .env would be
    # ignored and the bot would try MetaAPI). ENV_TO_SETTING_MAP adds renamed/extra keys.
    # Left out: the Telegram account values (read from .env directly, see config/settings.py),
    # empty values and the placeholders of .env.example.
    from src.services.settings_service import SettingsService
    skip = {"TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_PHONE"}
    names = {**{key: key for key in SettingsService.DEFAULT_SETTINGS}, **ENV_TO_SETTING_MAP}
    env_settings = {}
    for env_var, setting_key in names.items():
        env_value = os.getenv(env_var)
        if env_var in skip or env_value is None:
            continue
        env_value = env_value.split("  #")[0].strip()          # inline comment kept by some loaders
        if not env_value or env_value.lower().startswith(("your_", "your-")):
            continue
        env_settings[setting_key] = env_value

    if not env_settings:
        logger.warning("⚠️ No matching environment variables found")
        return
    
    logger.info(f"📦 Found {len(env_settings)} settings in .env file")
    
    # Initialize from env
    updated_count = await settings_service.initialize_from_env(env_settings)
    
    logger.success(f"✅ Successfully initialized {updated_count} settings from .env file")
    
    # Disconnect
    await prisma_client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
