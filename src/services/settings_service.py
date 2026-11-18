"""
Settings Service
Manages application configuration stored in database with .env fallback
"""
from typing import Any, Dict, List, Optional
from loguru import logger
from enum import Enum
import os
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from prisma import Prisma


class ValueType(str, Enum):
    STRING = "STRING"
    INT = "INT"
    FLOAT = "FLOAT"
    BOOL = "BOOL"
    JSON = "JSON"


class SettingCategory(str, Enum):
    TELEGRAM = "TELEGRAM"
    DISCORD = "DISCORD"
    TRADING = "TRADING"
    RISK_MANAGEMENT = "RISK_MANAGEMENT"
    AI = "AI"
    NEWS = "NEWS"
    MONITORING = "MONITORING"
    APPROVAL = "APPROVAL"
    DASHBOARD = "DASHBOARD"
    GENERAL = "GENERAL"


class SettingsService:
    """Service for managing application settings in database with encryption support"""

    # Settings that should be encrypted (API keys, tokens, passwords)
    ENCRYPTED_KEYS = {
        "TELEGRAM_API_ID",
        "TELEGRAM_API_HASH",
        "TELEGRAM_BOT_TOKEN",
        "DISCORD_BOT_TOKEN",
        "DISCORD_USER_TOKEN",
        "METAAPI_TOKEN",
        "MT5_REST_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "DEEPSEEK_API_KEY",
        "PERPLEXITY_API_KEY",
        "MINIMAX_API_KEY",
        "QWEN_API_KEY",
        "SIGNAL_VALIDATOR_API_KEY",
        "DASHBOARD_HASHED_PASSWORD",
        "BRAIN_API_KEY",
    }

    def __init__(self, db: Prisma, encryption_key: Optional[str] = None):
        self._db = db
        self._cache: Dict[str, Any] = {}
        self._cache_loaded = False
        self._metadata_cache: Optional[List[Dict[str, Any]]] = None
        self._metadata_cache_loaded = False
        self._fernet: Optional[Fernet] = None
        self._encryption_key = encryption_key
        
        if encryption_key:
            try:
                self._fernet = Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)
            except (ValueError, TypeError):
                # Not in Fernet's own format (e.g. `openssl rand -hex 32`, or any passphrase):
                # derive the key from it instead of refusing to start.
                self._fernet = self._fernet_from_passphrase(
                    encryption_key if isinstance(encryption_key, str) else encryption_key.decode())
        else:
            # Generate a key from a default password (in production, use a secure key)
            self._generate_default_key()

    @property
    def db(self) -> Prisma:
        """Always resolve through the prisma_client singleton so a reconnect
        (which swaps in a new Prisma() instance) is picked up immediately —
        caching the client at construction time would otherwise keep querying
        the old, disconnected instance after ensure_connected() reconnects."""
        from src.core.prisma_client import prisma_client
        if prisma_client.is_connected:
            return prisma_client.client
        return self._db

    @staticmethod
    def _fernet_from_passphrase(secret: str) -> Fernet:
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=b"trading-bot-salt", iterations=100000)
        return Fernet(base64.urlsafe_b64encode(kdf.derive(secret.encode())))

    def _generate_default_key(self):
        """Generate encryption key from environment or default"""
        # Use a secret from environment or generate one
        secret = os.getenv("SETTINGS_ENCRYPTION_KEY")
        if not secret:
            # No built-in fallback: a secret published with the source code would let
            # anyone decrypt the API keys and tokens stored in the settings table.
            raise RuntimeError(
                "SETTINGS_ENCRYPTION_KEY is not set. Generate one with\n"
                "  python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"\n"
                "and put it in .env (the bot and the dashboard must use the same value)."
            )
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"trading-bot-salt",
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(secret.encode()))
        self._fernet = Fernet(key)

    def _encrypt(self, value: str) -> str:
        """Encrypt a value"""
        if not self._fernet:
            return value
        try:
            encrypted = self._fernet.encrypt(value.encode())
            return base64.urlsafe_b64encode(encrypted).decode()
        except Exception as e:
            logger.warning(f"Failed to encrypt value: {e}")
            return value

    def _decrypt(self, encrypted_value: str) -> str:
        """Decrypt a value"""
        if not self._fernet:
            return encrypted_value
        if not encrypted_value:
            return encrypted_value
        # Try double-encoded format (current format: base64(fernet_token))
        try:
            encrypted = base64.urlsafe_b64decode(encrypted_value.encode())
            return self._fernet.decrypt(encrypted).decode()
        except Exception as _exc:
            logger.debug(f"Suppressed exception: {_exc!r}")
        # Fall back to raw Fernet token (values stored without extra base64 wrapping)
        try:
            return self._fernet.decrypt(encrypted_value.encode()).decode()
        except Exception as _exc:
            logger.debug(f"Suppressed exception: {_exc!r}")
        # Value is plain text (not encrypted) — return as-is
        return encrypted_value

    # Fernet tokens start with version byte 0x80 + timestamp: "gAAAAA" raw, "Z0FBQUFB" base64-wrapped
    _TOKEN_PREFIXES = ("gAAAAA", "Z0FBQUFB")

    async def encrypt_plaintext_secrets(self) -> List[str]:
        """Encrypt secret settings that were stored as plain text.

        The dashboard's PUT /api/settings/[key] wrote values straight to the
        database, so API keys saved from the config page ended up unencrypted.
        Values that already look like a Fernet token are never touched: with a
        wrong SETTINGS_ENCRYPTION_KEY they would fail to decrypt and get wrapped
        a second time.
        """
        encrypted = []
        for setting in await self.db.setting.find_many(where={"isSecret": True}):
            value = setting.value
            if not value or value.startswith(self._TOKEN_PREFIXES) or self._decrypt(value) != value:
                continue
            token = self._encrypt(value)
            if token == value or self._decrypt(token) != value:
                logger.warning(f"Could not encrypt plain-text secret '{setting.key}', left as is")
                continue
            await self.db.setting.update(where={"key": setting.key}, data={"value": token})
            encrypted.append(setting.key)
        if encrypted:
            logger.warning(f"🔐 Encrypted {len(encrypted)} secret setting(s) stored as plain text: {', '.join(encrypted)}")
        return encrypted

    # Default settings configuration (key, type, category, description, default value)
    DEFAULT_SETTINGS = {
        # Risk Management
        "MAX_RISK_PER_TRADE_PERCENT": (ValueType.FLOAT, SettingCategory.RISK_MANAGEMENT, "Maximum risk per trade as percentage of account balance", "2.0"),
        "MAX_OPEN_POSITIONS": (ValueType.INT, SettingCategory.RISK_MANAGEMENT, "Maximum number of open positions", "3"),
        "DEFAULT_STOP_LOSS_PIPS": (ValueType.INT, SettingCategory.RISK_MANAGEMENT, "Default stop loss in pips when not specified", "60"),
        "DEFAULT_TAKE_PROFIT_PIPS": (ValueType.INT, SettingCategory.RISK_MANAGEMENT, "Default take profit in pips when not specified", "40"),
        "RISK_REWARD_RATIO": (ValueType.FLOAT, SettingCategory.RISK_MANAGEMENT, "Default risk-to-reward ratio", "2.0"),
        "SPREAD_ADJUSTMENT_MULTIPLIER": (ValueType.FLOAT, SettingCategory.RISK_MANAGEMENT, "Multiplier for spread adjustment on stop loss", "1.0"),
        "ENABLE_EQUITY_PROTECTION": (ValueType.BOOL, SettingCategory.RISK_MANAGEMENT, "Enable MetaAPI equity protection for prop firm accounts", "true"),
        "DAILY_DRAWDOWN_LIMIT_PERCENT": (ValueType.FLOAT, SettingCategory.RISK_MANAGEMENT, "Daily drawdown limit percentage", "3.0"),
        "OVERALL_DRAWDOWN_LIMIT_PERCENT": (ValueType.FLOAT, SettingCategory.RISK_MANAGEMENT, "Overall drawdown limit percentage", "10.0"),
        "ENABLE_DRAWDOWN_MONITORING": (ValueType.BOOL, SettingCategory.RISK_MANAGEMENT, "Enable real-time drawdown monitoring", "true"),
        
        # Trading
        "MIN_LOT_SIZE": (ValueType.FLOAT, SettingCategory.TRADING, "Minimum lot size allowed", "0.01"),
        "MAX_LOT_SIZE": (ValueType.FLOAT, SettingCategory.TRADING, "Maximum lot size allowed", "1.0"),
        "SLIPPAGE_PIPS": (ValueType.INT, SettingCategory.TRADING, "Allowed slippage in pips", "3"),
        "MAX_SIGNAL_AGE_MINUTES": (ValueType.INT, SettingCategory.TRADING, "Reject signals older than X minutes", "5"),
        "ENABLE_INSTANT_EXECUTION": (ValueType.BOOL, SettingCategory.TRADING, "Enable instant market order execution", "true"),
        "INSTANT_EXECUTION_CHANNELS": (ValueType.JSON, SettingCategory.TRADING, "Channel IDs allowed for instant execution — Telegram and Discord (JSON array)", "[]"),
        "INSTANT_EXECUTION_KEYWORDS": (ValueType.JSON, SettingCategory.TRADING, "Keywords that trigger instant execution (JSON array)", '["now","instant","market","immediately","asap"]'),
        "INSTANT_TEMP_SL_PIPS": (ValueType.FLOAT, SettingCategory.TRADING, "Minimum temporary SL distance (pips) for an instant entry posted without SL, until the follow-up brings the real SL. Widened to the widest SL the channel used on the symbol in its last 10 signals", "100"),
        "INSTANT_FIRST_ENTRY_RISK_SHARE": (ValueType.FLOAT, SettingCategory.TRADING, "Percent of the signal's risk budget the temporary-SL entry (one position) may use; the rest is placed when the full signal arrives", "50"),
        "SIGNAL_CONTINUITY_WINDOW_MINUTES": (ValueType.INT, SettingCategory.TRADING, "A follow-up, repost or edit from the same channel within this many minutes updates the existing signal instead of opening a new one", "30"),
        "SAME_LEVEL_TOLERANCE_PIPS": (ValueType.FLOAT, SettingCategory.TRADING, "Orders closer than this many pips count as the same level (continuity matching and duplicate check)", "20"),
        "INSTANT_EXECUTION_MAX_DEVIATION_PIPS": (ValueType.FLOAT, SettingCategory.TRADING, "Instant signals fill at market only while price is within this many pips past the entry; otherwise they wait as a limit", "20"),
        "INSTANT_ONE_LEG_MAX_TP1_PROGRESS": (ValueType.FLOAT, SettingCategory.TRADING, "Beyond the max deviation, one order (the furthest TP) still fills at market with lots scaled to the same risk, while price has covered less than this percent of the way from the entry to TP1. 0 = off", "50"),
        
        # Auto TP
        "ENABLE_AUTO_TAKE_PROFIT": (ValueType.BOOL, SettingCategory.TRADING, "Enable automatic take profit", "true"),
        "AUTO_TP_CALCULATION_METHOD": (ValueType.STRING, SettingCategory.TRADING, "Auto TP calculation method: PIPS or RR", "RR"),
        "AUTO_TP_PIPS": (ValueType.INT, SettingCategory.TRADING, "Auto TP distance in pips (if method is PIPS)", "50"),
        "AUTO_TP_RISK_REWARD": (ValueType.FLOAT, SettingCategory.TRADING, "Auto TP risk-reward ratio (if method is RR)", "2.0"),
        
        # Trailing Stop
        "ENABLE_TRAILING_STOP": (ValueType.BOOL, SettingCategory.TRADING, "Enable trailing stop loss", "true"),
        "TRAILING_STOP_CALCULATION_METHOD": (ValueType.STRING, SettingCategory.TRADING, "Trailing stop calculation method: PIPS or RR", "PIPS"),
        "TRAILING_STOP_DISTANCE_PIPS": (ValueType.INT, SettingCategory.TRADING, "Trailing stop distance in pips", "15"),
        "TRAILING_STOP_DISTANCE_RR": (ValueType.FLOAT, SettingCategory.TRADING, "Trailing stop distance as RR ratio", "0.5"),
        "TRAILING_STOP_MIN_STEP_PIPS": (ValueType.FLOAT, SettingCategory.TRADING, "Only move the trailing SL when it improves by at least this many pips (reduces broker modifications)", "1.0"),
        "TRAILING_STOP_MIN_INTERVAL_SECONDS": (ValueType.INT, SettingCategory.TRADING, "Minimum seconds between trailing SL modifications per trade", "10"),
        "TRAILING_ACTIVATION_METHOD": (ValueType.STRING, SettingCategory.TRADING, "Trailing activation method: PROFIT_PIPS, PROFIT_RR, PARTIAL_TP", "PROFIT_PIPS"),
        "TRAILING_ACTIVATION_PROFIT_PIPS": (ValueType.INT, SettingCategory.TRADING, "Activate trailing after X pips profit", "20"),
        "TRAILING_ACTIVATION_PROFIT_RR": (ValueType.FLOAT, SettingCategory.TRADING, "Activate trailing after X:1 RR profit", "1.0"),
        
        # Auto Partial
        "ENABLE_AUTO_PARTIAL": (ValueType.BOOL, SettingCategory.TRADING, "Enable auto partial profit taking", "true"),
        "AUTO_PARTIAL_CALCULATION_METHOD": (ValueType.STRING, SettingCategory.TRADING, "Auto partial calculation method: PIPS or RR", "RR"),
        "AUTO_PARTIAL_TRIGGER_PIPS": (ValueType.INT, SettingCategory.TRADING, "Take partials after X pips profit", "30"),
        "AUTO_PARTIAL_TRIGGER_RR": (ValueType.FLOAT, SettingCategory.TRADING, "Take partials after X:1 RR profit", "1.5"),
        "AUTO_PARTIAL_CLOSE_PERCENT": (ValueType.FLOAT, SettingCategory.TRADING, "Close X% of position as partial", "50.0"),

        # Runner
        "ENABLE_RUNNER_SPLIT": (ValueType.BOOL, SettingCategory.TRADING, "Place part of every signal without a take profit (a runner): it keeps the signal's SL and is closed by the SL or by the channel's messages", "false"),
        "RUNNER_SHARE_PERCENT": (ValueType.FLOAT, SettingCategory.TRADING, "Percent of the signal's lots placed without a take profit; the rest goes to the signal's TPs", "50.0"),
        
        # Trade Plans
        "PLAN_WATCHER_ENABLED": (ValueType.BOOL, SettingCategory.TRADING, "Master switch for trade-plan zone watching (plans preserved in DB when off)", "true"),
        "PLAN_AUTO_EXECUTE": (ValueType.BOOL, SettingCategory.TRADING, "Global default for auto-executing plans when entry zone is reached (per-plan field overrides)", "false"),
        "PLAN_EXPIRY_HOURS": (ValueType.INT, SettingCategory.TRADING, "Auto-expire a plan if its entry zone is never reached within X hours", "72"),
        "PLAN_GAP_RISK_BLOCK": (ValueType.BOOL, SettingCategory.TRADING, "Filter plans received while market is closed/weekend", "true"),

        # Breakeven
        "ENABLE_BREAKEVEN_MOVE": (ValueType.BOOL, SettingCategory.TRADING, "Move SL to breakeven when profitable", "true"),
        "BREAKEVEN_TRIGGER_METHOD": (ValueType.STRING, SettingCategory.TRADING, "Breakeven trigger method: AFTER_PARTIAL, PROFIT_PIPS, or AFTER_SIBLING_TP_HIT", "AFTER_PARTIAL"),
        "BREAKEVEN_TRIGGER_PIPS": (ValueType.INT, SettingCategory.TRADING, "Move to breakeven after X pips profit", "15"),
        "BREAKEVEN_BUFFER_PIPS": (ValueType.INT, SettingCategory.TRADING, "Buffer pips above/below entry for breakeven", "2"),
        "BREAKEVEN_MIN_SIBLING_TP_HITS": (ValueType.INT, SettingCategory.TRADING, "For AFTER_SIBLING_TP_HIT: min number of sibling TPs that must hit before triggering BE (multi-TP signals)", "1"),
        
        # Position Monitoring
        "POSITION_MONITOR_INTERVAL_SECONDS": (ValueType.INT, SettingCategory.MONITORING, "How often to check positions in seconds", "3"),
        "ENABLE_POSITION_MONITORING": (ValueType.BOOL, SettingCategory.MONITORING, "Master switch for position monitoring", "true"),
        "MESSAGE_PROCESSING_CONCURRENCY": (ValueType.INT, SettingCategory.MONITORING, "Max Telegram messages processed in parallel during bursts (higher = faster under spam, more AI API load)", "4"),
        "ALLOW_MULTI_SIGNAL_POSTS": (ValueType.BOOL, SettingCategory.MONITORING, "A text post that contains several independent trades (each with its own entry and stop loss) is split by the AI into one signal per trade", "true"),
        "CATCHUP_ENABLED": (ValueType.BOOL, SettingCategory.MONITORING, "Detect Telegram messages posted while the bot was offline: process fresh ones, report expired signals, and ask before applying missed commands", "true"),
        "CATCHUP_MAX_MESSAGES": (ValueType.INT, SettingCategory.MONITORING, "Per channel, how many of the newest missed messages catch-up checks", "50"),
        "CATCHUP_INTERVAL_MINUTES": (ValueType.INT, SettingCategory.MONITORING, "Minutes between periodic checks for silently lost Telegram updates (0 = only at startup)", "10"),
        "ORDER_CLOSE_GRACE_MISSES": (ValueType.INT, SettingCategory.MONITORING, "Consecutive broker misses before a running position is marked closed (used when lifecycle API is unavailable)", "3"),
        "ORDER_CANCEL_GRACE_MISSES": (ValueType.INT, SettingCategory.MONITORING, "Consecutive broker misses before a pending order is marked cancelled (used when lifecycle API is unavailable)", "3"),
        "ORDER_STALE_PENDING_HOURS": (ValueType.INT, SettingCategory.MONITORING, "Hours before an unmatched PENDING trade is auto-cancelled", "4"),
        
        # Trading Brain
        "ENABLE_TRADING_BRAIN": (ValueType.BOOL, SettingCategory.AI, "Enable AI Trading Brain — conversational session that reviews every signal and manages positions", "true"),
        "BRAIN_BASE_URL": (ValueType.STRING, SettingCategory.AI, "Brain endpoint URL, e.g. http://hermes:8080/v1 (leave empty to use the configured AI provider)", ""),
        "BRAIN_API_KEY": (ValueType.STRING, SettingCategory.AI, "Brain API key (stored encrypted; leave empty to reuse provider key)", ""),
        "BRAIN_MODEL": (ValueType.STRING, SettingCategory.AI, "Brain model name (leave empty to use the active provider's model)", ""),
        "BRAIN_TEMPERATURE": (ValueType.FLOAT, SettingCategory.AI, "Brain response temperature — lower is more deterministic (0.0–1.0)", "0.3"),
        "BRAIN_MAX_HISTORY_MESSAGES": (ValueType.INT, SettingCategory.AI, "Max conversation messages kept in memory before oldest are trimmed", "60"),
        "BRAIN_POSITION_REVIEW_INTERVAL": (ValueType.INT, SettingCategory.MONITORING, "Seconds between brain position reviews per open trade", "30"),
        "BRAIN_ACTION_REQUIRE_APPROVAL": (ValueType.BOOL, SettingCategory.AI, "Require Telegram approval before the brain executes any position action (CLOSE, MODIFY_SL, etc.)", "true"),
        "BRAIN_ACTION_APPROVAL_TYPES": (ValueType.STRING, SettingCategory.AI, "Comma-separated action types that require approval — e.g. CLOSE,PARTIAL_CLOSE,MODIFY_SL,MODIFY_TP", "CLOSE,PARTIAL_CLOSE,MODIFY_SL,MODIFY_TP"),
        "BRAIN_UNAVAILABLE_ACTION": (ValueType.STRING, SettingCategory.AI, "What to do with signals when the brain is down or unconfigured: APPROVE (trade anyway), REJECT (block), APPROVAL (send to manual approval queue), or PIPELINE (use the rest of the configured pipeline as-is, exactly like the brain is disabled)", "APPROVE"),

        # AI Features
        "ENABLE_AI_MARKET_ANALYSIS": (ValueType.BOOL, SettingCategory.AI, "Enable AI-powered market analysis", "false"),
        "ENABLE_LLM_MARKET_ANALYSIS": (ValueType.BOOL, SettingCategory.AI, "Enable LLM-powered market analysis (uses AI provider credits)", "false"),
        "LLM_MARKET_ANALYSIS_INTERVAL": (ValueType.INT, SettingCategory.AI, "Minimum seconds between LLM market-analysis calls per symbol", "60"),
        "AI_ANALYSIS_CHECK_INTERVAL": (ValueType.INT, SettingCategory.AI, "Check market conditions every X seconds", "30"),
        "ENABLE_AI_BREAKEVEN_TRIGGERS": (ValueType.BOOL, SettingCategory.AI, "AI detects adverse trends for breakeven", "false"),
        "ENABLE_AI_TP_ADJUSTMENT": (ValueType.BOOL, SettingCategory.AI, "AI suggests TP adjustments", "false"),
        "ENABLE_AI_POSITION_REDUCTION": (ValueType.BOOL, SettingCategory.AI, "AI suggests partial closes in unfavorable conditions", "false"),
        "AI_ANALYSIS_CONFIDENCE_THRESHOLD": (ValueType.FLOAT, SettingCategory.AI, "Confidence level needed to act on AI recommendations (0.0-1.0)", "0.7"),
        "AI_AUTO_VERIFICATION_ENABLED": (ValueType.BOOL, SettingCategory.AI, "Enable AI auto-verification of signals", "false"),
        "ENABLE_AI_VISION": (ValueType.BOOL, SettingCategory.AI, "Master switch for AI-powered chart image analysis", "true"),

        # Vision Anti-Hallucination Filters
        "VISION_CAPTION_PREFILTER_ENABLED": (ValueType.BOOL, SettingCategory.AI, "Skip vision API call if caption contains trade result keywords — prevents false signals and saves API cost", "true"),
        "VISION_CAPTION_BLOCK_KEYWORDS": (ValueType.STRING, SettingCategory.AI, "Comma-separated keywords that flag an image as non-signal (result screenshot, open position, etc.)", "in profit,floating,closed,result,pips gained,balance,equity,trade history,win rate,drawdown,performance,tp hit,sl hit,hit tp,hit sl,be hit,profit taken,loss taken"),
        "VISION_CONFIDENCE_FILTER_ENABLED": (ValueType.BOOL, SettingCategory.AI, "Reject vision signals where the AI self-rates its own confidence below the minimum threshold", "true"),
        "VISION_MIN_CONFIDENCE": (ValueType.FLOAT, SettingCategory.AI, "Minimum AI self-confidence score (0.0–1.0) required to accept a vision-extracted signal", "0.75"),
        "VISION_TWO_STEP_CLASSIFY_ENABLED": (ValueType.BOOL, SettingCategory.AI, "Use a separate API call to classify the image type before extraction — more accurate but uses 2× API calls per image", "true"),
        "VISION_PRICE_SANITY_CHECK_ENABLED": (ValueType.BOOL, SettingCategory.AI, "Reject signals with entry/SL/TP prices outside known realistic ranges for that instrument", "true"),
        "VISION_PRICE_RANGES": (ValueType.JSON, SettingCategory.AI, "Per-symbol [min, max] price ranges for sanity validation — JSON object", '{\"XAUUSD\":[1000,5000],\"EURUSD\":[0.5,3.0],\"GBPUSD\":[0.5,3.0],\"USDJPY\":[50,250],\"BTCUSD\":[1000,500000],\"ETHUSD\":[100,50000],\"US30\":[15000,70000],\"NAS100\":[5000,30000],\"SPX500\":[1000,10000],\"GBPJPY\":[100,300],\"USDCAD\":[0.5,2.5],\"AUDUSD\":[0.3,1.5],\"NZDUSD\":[0.3,1.5],\"USDCHF\":[0.5,2.0],\"EURJPY\":[50,250],\"EURGBP\":[0.5,2.0]}'),
        "VISION_SL_DISTANCE_CHECK_ENABLED": (ValueType.BOOL, SettingCategory.AI, "Reject signals where the Stop Loss is unrealistically far from the entry price", "true"),
        "VISION_MAX_SL_DISTANCE_PERCENT": (ValueType.FLOAT, SettingCategory.AI, "Maximum allowed SL distance as % of entry price — signals with SL further than this are discarded", "10.0"),
        "VISION_SYMBOL_WHITELIST_ENABLED": (ValueType.BOOL, SettingCategory.AI, "Only accept signals for symbols in the allowed symbols list — off by default (accepts any symbol)", "false"),
        "VISION_ALLOWED_SYMBOLS": (ValueType.STRING, SettingCategory.AI, "Comma-separated list of allowed trading symbols when whitelist is enabled", "XAUUSD,EURUSD,GBPUSD,USDJPY,BTCUSD,ETHUSD,US30,NAS100,SPX500,GBPJPY,USDCAD,AUDUSD,NZDUSD,USDCHF,EURJPY,EURGBP"),
        "VISION_IMAGE_DIMENSION_FILTER_ENABLED": (ValueType.BOOL, SettingCategory.AI, "Skip vision analysis for decorative graphics (dividers, banners, tiny stickers) based on image dimensions", "true"),
        "VISION_MAX_IMAGE_ASPECT_RATIO": (ValueType.FLOAT, SettingCategory.AI, "Images wider/taller than this width:height ratio are treated as decorative and skipped", "3.5"),
        "VISION_MIN_IMAGE_HEIGHT": (ValueType.INT, SettingCategory.AI, "Images shorter than this many pixels are treated as decorative and skipped", "150"),

        # AI Provider Configuration
        "OPENAI_API_KEY": (ValueType.STRING, SettingCategory.AI, "OpenAI API key", ""),
        "OPENAI_MODEL": (ValueType.STRING, SettingCategory.AI, "OpenAI model name", "gpt-4-turbo-preview"),
        "OPENAI_VISION_MODEL": (ValueType.STRING, SettingCategory.AI, "OpenAI vision model for chart image analysis", "gpt-4o-mini"),
        "GEMINI_API_KEY": (ValueType.STRING, SettingCategory.AI, "Google Gemini API key (from aistudio.google.com)", ""),
        "GEMINI_MODEL": (ValueType.STRING, SettingCategory.AI, "Gemini model name for signal text analysis", "gemini-2.5-flash"),
        "GEMINI_VISION_MODEL": (ValueType.STRING, SettingCategory.AI, "Gemini vision model for chart image analysis", "gemini-2.5-flash"),
        "DEEPSEEK_API_KEY": (ValueType.STRING, SettingCategory.AI, "DeepSeek API key", ""),
        "DEEPSEEK_API_URL": (ValueType.STRING, SettingCategory.AI, "DeepSeek API URL", "https://api.deepseek.com/v1"),
        "DEEPSEEK_MODEL": (ValueType.STRING, SettingCategory.AI, "DeepSeek model name", "deepseek-v4-flash"),
        "DEEPSEEK_VISION_MODEL": (ValueType.STRING, SettingCategory.AI, "DeepSeek vision model for chart image analysis", "deepseek-vl2"),
        "PERPLEXITY_API_KEY": (ValueType.STRING, SettingCategory.AI, "Perplexity API key", ""),
        "PERPLEXITY_BASE_URL": (ValueType.STRING, SettingCategory.AI, "Perplexity API base URL", "https://api.perplexity.ai"),
        "PERPLEXITY_MODEL": (ValueType.STRING, SettingCategory.AI, "Perplexity model name", "sonar-pro"),
        "PERPLEXITY_VISION_MODEL": (ValueType.STRING, SettingCategory.AI, "Perplexity vision model for chart image analysis", "sonar-pro"),
        "OPENROUTER_API_KEY": (ValueType.STRING, SettingCategory.AI, "OpenRouter API key from openrouter.ai", ""),
        "OPENROUTER_BASE_URL": (ValueType.STRING, SettingCategory.AI, "OpenRouter API base URL", "https://openrouter.ai/api/v1"),
        "OPENROUTER_MODEL": (ValueType.STRING, SettingCategory.AI, "OpenRouter model for signal text analysis", "qwen/qwen2.5-vl-72b-instruct"),
        "OPENROUTER_VISION_MODEL": (ValueType.STRING, SettingCategory.AI, "OpenRouter model for chart image analysis", "qwen/qwen2.5-vl-72b-instruct"),
        "MINIMAX_API_KEY": (ValueType.STRING, SettingCategory.AI, "MiniMax API key from platform.minimaxi.com", ""),
        "MINIMAX_BASE_URL": (ValueType.STRING, SettingCategory.AI, "MiniMax API base URL", "https://api.minimax.io/v1"),
        "MINIMAX_MODEL": (ValueType.STRING, SettingCategory.AI, "MiniMax model for signal text analysis", "MiniMax-M2.7"),
        "MINIMAX_VISION_MODEL": (ValueType.STRING, SettingCategory.AI, "MiniMax vision model for chart image analysis", "MiniMax-VL-01"),
        "QWEN_API_KEY": (ValueType.STRING, SettingCategory.AI, "Qwen (Alibaba DashScope) API key", ""),
        "QWEN_BASE_URL": (ValueType.STRING, SettingCategory.AI, "Qwen API base URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
        "QWEN_MODEL": (ValueType.STRING, SettingCategory.AI, "Qwen model for signal text analysis", "qwen-plus"),
        "QWEN_VISION_MODEL": (ValueType.STRING, SettingCategory.AI, "Qwen vision model for chart image analysis", "qwen-vl-max"),
        "OLLAMA_URL": (ValueType.STRING, SettingCategory.AI, "Ollama API URL", "http://localhost:11434"),
        "OLLAMA_MODEL": (ValueType.STRING, SettingCategory.AI, "Ollama model name", "llama2"),
        "PRIMARY_AI_PROVIDER": (ValueType.STRING, SettingCategory.AI, "Primary AI provider: openai, deepseek, ollama, perplexity, openrouter, minimax, qwen", "openai"),
        "FALLBACK_AI_PROVIDERS": (ValueType.JSON, SettingCategory.AI, "Fallback AI providers (JSON array)", '["deepseek","ollama","perplexity"]'),
        "provider": (ValueType.STRING, SettingCategory.AI, "Vision AI provider: openai, gemini, perplexity, openrouter, minimax, or qwen", "openai"),
        
        # Approval
        "REQUIRE_MANUAL_APPROVAL": (ValueType.BOOL, SettingCategory.APPROVAL, "Require manual approval for all signals", "false"),
        "APPROVAL_REQUIRED_CHANNELS": (ValueType.JSON, SettingCategory.APPROVAL, "Channel IDs that require approval (JSON array)", "[]"),
        "APPROVAL_CHANNEL_ID": (ValueType.STRING, SettingCategory.APPROVAL, "Channel where approval requests are sent", ""),
        "APPROVAL_TIMEOUT_MINUTES": (ValueType.INT, SettingCategory.APPROVAL, "Auto-reject signals after X minutes without approval", "4"),
        "APPROVAL_SEND_IMAGE": (ValueType.BOOL, SettingCategory.APPROVAL, "Send signal image to approval channel before the approve/reject message", "true"),
        "REQUIRE_APPROVAL_FOR_IMAGES": (ValueType.BOOL, SettingCategory.APPROVAL, "Force manual approval for any signal containing an image, regardless of the global approval setting", "false"),
        "ALLOW_HIGH_RISK_OVERRIDE": (ValueType.BOOL, SettingCategory.APPROVAL, "When a signal exceeds MAX_RISK_PER_TRADE_PERCENT, ask for manual approval with a high-risk disclaimer instead of auto-rejecting it", "false"),
        "REQUIRE_APPROVAL_FOR_ESTIMATED_SIZING": (ValueType.BOOL, SettingCategory.APPROVAL, "When the lot size had to be computed from an estimated pip value (broker symbol data unavailable), ask for manual approval instead of trading it blindly", "true"),

        # News
        "NEWS_ENABLE_FILTER": (ValueType.BOOL, SettingCategory.NEWS, "Enable news-based trading blocks", "true"),
        "NEWS_MINUTES_BEFORE": (ValueType.INT, SettingCategory.NEWS, "Block trading X minutes before news", "10"),
        "NEWS_MINUTES_AFTER": (ValueType.INT, SettingCategory.NEWS, "Block trading X minutes after news", "5"),
        "NEWS_IMPORTANT_IMPACTS": (ValueType.JSON, SettingCategory.NEWS, "News impact levels to monitor (JSON array)", '["High","Medium"]'),
        "NEWS_TARGET_CURRENCIES": (ValueType.JSON, SettingCategory.NEWS, "Currencies to monitor (JSON array)", '["EUR","USD","CAD","JPY","GBP"]'),
        "NEWS_VERBOSE_LOGGING": (ValueType.BOOL, SettingCategory.NEWS, "Enable detailed news logs", "false"),
        "NEWS_ENABLE_NOTIFICATIONS": (ValueType.BOOL, SettingCategory.NEWS, "Send notifications for upcoming news", "true"),
        "NEWS_NOTIFICATION_MINUTES_BEFORE": (ValueType.INT, SettingCategory.NEWS, "Notify X minutes before news", "10"),
        "NEWS_POST_ENABLED": (ValueType.BOOL, SettingCategory.NEWS, "Post upcoming news to a Telegram channel", "false"),
        "NEWS_POST_CHANNEL_ID": (ValueType.STRING, SettingCategory.NEWS, "Channel the news posts go to", ""),
        "NEWS_POST_IMPACTS": (ValueType.JSON, SettingCategory.NEWS, "Impact levels that are posted (JSON array)", '["High"]'),
        "NEWS_POST_CURRENCIES": (ValueType.JSON, SettingCategory.NEWS, "Currencies whose news is posted (JSON array)", '["USD"]'),
        "NEWS_POST_MINUTES_BEFORE": (ValueType.INT, SettingCategory.NEWS, "Post X minutes before the event", "30"),
        "NEWS_API_URL": (ValueType.STRING, SettingCategory.NEWS, "News API URL", "https://nfs.faireconomy.media/ff_calendar_thisweek.json"),
        
        # Telegram Channels
        "TELEGRAM_CHANNEL_ID": (ValueType.JSON, SettingCategory.TELEGRAM, "Channels to monitor (JSON array)", "[]"),
        "TELEGRAM_NOTIFICATION_CHAT_ID": (ValueType.STRING, SettingCategory.TELEGRAM, "Chat ID for notifications", ""),
        "SIGNAL_FORWARD_CHANNEL_ID": (ValueType.STRING, SettingCategory.TELEGRAM, "Channel ID to forward executed signals to", ""),
        "SIGNAL_FORWARD_ENABLED": (ValueType.BOOL, SettingCategory.TELEGRAM, "Enable signal forwarding to channel", "false"),
        "PROCESS_FORWARDED_SIGNALS": (ValueType.BOOL, SettingCategory.TELEGRAM, "Process signals forwarded from monitored channels into other chats", "false"),
        "BOT_ALLOWED_USER_IDS": (ValueType.JSON, SettingCategory.TELEGRAM, "Telegram user IDs allowed to use bot commands (leave empty to allow all users in the approval channel)", "[]"),
        
        # Notification Filters — which categories reach TELEGRAM_NOTIFICATION_CHAT_ID.
        # Labels/descriptions live in src/services/notification_filter_service.py.
        "NOTIFY_ENABLED": (ValueType.BOOL, SettingCategory.TELEGRAM, "Master switch for the notification channel — turn off to silence every filterable notification", "true"),
        "NOTIFY_SIGNAL_RECEIVED": (ValueType.BOOL, SettingCategory.TELEGRAM, "Notify when a new signal is detected in a monitored channel", "true"),
        "NOTIFY_SIGNAL_REJECTED": (ValueType.BOOL, SettingCategory.TELEGRAM, "Notify when a signal is rejected or filtered (risk, news, drawdown, validator, Brain)", "true"),
        "NOTIFY_SIGNAL_PARSE_FAILED": (ValueType.BOOL, SettingCategory.TELEGRAM, "Notify when the AI could not extract a valid signal from a message or chart", "true"),
        "NOTIFY_BRAIN_DECISIONS": (ValueType.BOOL, SettingCategory.TELEGRAM, "Notify when the Trading Brain modifies a signal before execution", "true"),
        "NOTIFY_TRADE_EXECUTED": (ValueType.BOOL, SettingCategory.TELEGRAM, "Notify when a trade is opened", "true"),
        "NOTIFY_TRADE_FAILED": (ValueType.BOOL, SettingCategory.TELEGRAM, "Notify when trade execution fails (broker rejection, connection failure)", "true"),
        "NOTIFY_TRADE_CLOSED": (ValueType.BOOL, SettingCategory.TELEGRAM, "Notify when a position closes, with final profit/loss", "true"),
        "NOTIFY_ORDER_CANCELLED": (ValueType.BOOL, SettingCategory.TELEGRAM, "Notify when a pending order is cancelled or expires without filling", "true"),
        "NOTIFY_RR_MILESTONES": (ValueType.BOOL, SettingCategory.TELEGRAM, "Notify when a position reaches 1:1 or 1:2 risk-to-reward", "true"),
        "NOTIFY_POSITION_MANAGEMENT": (ValueType.BOOL, SettingCategory.TELEGRAM, "Notify on SL/TP moves, partial closes, breakeven and trailing stop updates", "true"),
        "NOTIFY_APPROVAL_OUTCOMES": (ValueType.BOOL, SettingCategory.TELEGRAM, "Notify when an approval request times out or is rejected (approval prompts themselves are always sent)", "true"),
        "NOTIFY_TRADE_PLANS": (ValueType.BOOL, SettingCategory.TELEGRAM, "Notify on trade plan updates (registered, executed, expired, fallback)", "true"),
        "NOTIFY_COMMAND_RESPONSES": (ValueType.BOOL, SettingCategory.TELEGRAM, "Notify with confirmations and errors for manual commands you send the bot", "true"),
        "NOTIFY_AI_ANALYSIS": (ValueType.BOOL, SettingCategory.TELEGRAM, "Notify with periodic AI market analysis and recommendations", "true"),
        "NOTIFY_ERRORS": (ValueType.BOOL, SettingCategory.TELEGRAM, "Notify on internal errors, connection/API failures and service-unavailable warnings", "true"),
        "NOTIFY_RISK_ALERTS": (ValueType.BOOL, SettingCategory.TELEGRAM, "Notify on drawdown limit breaches and risk-management warnings", "true"),
        "NOTIFY_BOT_LIFECYCLE": (ValueType.BOOL, SettingCategory.TELEGRAM, "Notify when the bot starts up and shuts down", "true"),

        # Signal Validator
        "ENABLE_SIGNAL_VALIDATOR": (ValueType.BOOL, SettingCategory.GENERAL, "Enable external signal validation", "false"),
        "SIGNAL_VALIDATOR_URL": (ValueType.STRING, SettingCategory.GENERAL, "Signal validator API URL (your own validator service)", "http://signal-validator:8000"),
        "SIGNAL_VALIDATOR_API_KEY": (ValueType.STRING, SettingCategory.GENERAL, "API key for signal validator service (sent as X-API-Key header)", ""),
        "SIGNAL_VALIDATOR_TIMEOUT_SECONDS": (ValueType.INT, SettingCategory.GENERAL, "Signal validator timeout in seconds", "5"),
        "SIGNAL_VALIDATOR_EXECUTION_POLICY": (ValueType.STRING, SettingCategory.GENERAL, "Signal validator execution policy: ALL, VALID_WARN, VALID_ONLY", "VALID_WARN"),

        # MetaAPI
        "METAAPI_TOKEN": (ValueType.STRING, SettingCategory.GENERAL, "MetaAPI cloud authentication token", ""),
        "METAAPI_ACCOUNT_ID": (ValueType.STRING, SettingCategory.GENERAL, "MetaAPI trading account identifier", ""),

        # General Settings
        "LOG_LEVEL": (ValueType.STRING, SettingCategory.GENERAL, "Terminal output level: DEBUG, INFO, WARNING, ERROR", "INFO"),
        "LOG_FILE_LEVEL": (ValueType.STRING, SettingCategory.GENERAL, "File output level (optional)", ""),
        "LOG_FILE_DEBUG": (ValueType.BOOL, SettingCategory.GENERAL, "Force DEBUG level in log files", "false"),
        "DRY_RUN": (ValueType.BOOL, SettingCategory.GENERAL, "Run in dry-run mode (no actual trades)", "false"),
        "TIMEZONE": (ValueType.STRING, SettingCategory.GENERAL, "System timezone", "UTC"),
        "SKIP_METAAPI": (ValueType.BOOL, SettingCategory.GENERAL, "Turns ALL trading off (MetaAPI and MT5 REST): signals are detected and recorded as dry-run trades only. Needs a bot restart", "false"),

        # Trading Provider
        "TRADING_PROVIDER": (ValueType.STRING, SettingCategory.GENERAL, "Trading provider: metaapi or mt5rest", "metaapi"),
        "MT5_REST_API_URL": (ValueType.STRING, SettingCategory.GENERAL, "MT5 REST API URL", "http://mt5:5001"),
        "NEWS_UPDATE_INTERVAL_HOURS": (ValueType.INT, SettingCategory.GENERAL, "Hours between news calendar refreshes", "24"),
        "POSITION_MONITOR_STARTUP_DELAY_SECONDS": (ValueType.INT, SettingCategory.GENERAL, "Delay before the first position-monitor check (0 = none)", "0"),
        "METAAPI_USE_STREAMING": (ValueType.BOOL, SettingCategory.GENERAL, "MetaAPI: use a streaming connection for live position/order/account reads (no API-call limits)", "true"),
        "MT5_SYMBOL_SUFFIX": (ValueType.STRING, SettingCategory.GENERAL, "Broker symbol suffix (e.g., .fx)", ""),
        # Telegram account the bot listens with (optional; empty = use the environment, or run without Telegram)
        "TELEGRAM_API_ID": (ValueType.STRING, SettingCategory.TELEGRAM, "Telegram API ID from my.telegram.org (leave empty to run without Telegram)", ""),
        "TELEGRAM_API_HASH": (ValueType.STRING, SettingCategory.TELEGRAM, "Telegram API hash from my.telegram.org (stored encrypted)", ""),
        "TELEGRAM_PHONE": (ValueType.STRING, SettingCategory.TELEGRAM, "Phone number of the Telegram account; when set, the dashboard login is locked to it", ""),
                # Discord signal source (managed on the dashboard's Discord page; channels live in discord_channels)
        "DISCORD_ENABLED": (ValueType.BOOL, SettingCategory.DISCORD, "Listen to the Discord channels selected on the Discord page", "false"),
        "DISCORD_BOT_TOKEN": (ValueType.STRING, SettingCategory.DISCORD, "Discord bot token from the Developer Portal (stored encrypted)", ""),
        "DISCORD_ACCOUNT_TYPE": (ValueType.STRING, SettingCategory.DISCORD, "How Discord is read: bot (official bot, must be added by a server admin) or user (your own account; against Discord's terms, the account can be banned)", "bot"),
        "DISCORD_USER_TOKEN": (ValueType.STRING, SettingCategory.DISCORD, "Token of your own Discord account for the 'user' mode (stored encrypted)", ""),
        "COPY_MASTER_MODE": (ValueType.BOOL, SettingCategory.TRADING, "Copy master mode: wait for master position before entering (no limit orders)", "false"),
    }

    async def initialize_defaults(self):
        """Initialize default settings in database if they don't exist"""
        logger.info("🔧 Initializing default settings in database...")
        
        for key, (value_type, category, description, default_value) in self.DEFAULT_SETTINGS.items():
            existing = await self.db.setting.find_unique(where={"key": key})
            
            if not existing:
                # Encrypt if this is a secret setting
                is_secret = key in self.ENCRYPTED_KEYS
                value_to_store = default_value
                
                if is_secret:
                    value_to_store = self._encrypt(default_value)
                
                await self.db.setting.create(
                    data={
                        "key": key,
                        "value": value_to_store,
                        "valueType": value_type.value,
                        "category": category.value,
                        "description": description,
                        "isSecret": is_secret
                    }
                )
                logger.debug(f"   Created default setting: {key} (encrypted={is_secret})")
        
        logger.success("✅ Default settings initialized")

    async def initialize_from_env(self, env_settings: Dict[str, str]):
        """
        Auto-initialize settings from .env file values
        This will update existing settings with values from environment variables
        """
        logger.info("🔧 Initializing settings from .env file...")
        
        updated_count = 0
        for key, env_value in env_settings.items():
            # Check if this key exists in our DEFAULT_SETTINGS
            if key not in self.DEFAULT_SETTINGS:
                continue
            
            # Get setting metadata
            value_type, category, description, default_value = self.DEFAULT_SETTINGS[key]
            
            # Parse and then re-serialize to ensure correct format in DB
            # Especially important for JSON types coming from .env as CSV
            parsed_value = self._parse_value(env_value, value_type.value)
            serialized_value = self._serialize_value(parsed_value, value_type.value)
            
            # Check if setting exists in database
            existing = await self.db.setting.find_unique(where={"key": key})
            
            # Encrypt if this is a secret setting
            is_secret = key in self.ENCRYPTED_KEYS
            value_to_store = serialized_value
            
            if is_secret:
                value_to_store = self._encrypt(serialized_value)
            
            if existing:
                # Update existing setting
                await self.db.setting.update(
                    where={"key": key},
                    data={
                        "value": value_to_store,
                        "isSecret": is_secret
                    }
                )
                logger.debug(f"   Updated setting from .env: {key}")
            else:
                # Create new setting
                await self.db.setting.create(
                    data={
                        "key": key,
                        "value": value_to_store,
                        "valueType": value_type.value,
                        "category": category.value,
                        "description": description,
                        "isSecret": is_secret
                    }
                )
                logger.debug(f"   Created setting from .env: {key}")
            
            updated_count += 1
        
        logger.success(f"✅ Initialized {updated_count} settings from .env file")
        return updated_count

    async def load_settings(self, force_reload: bool = False) -> Dict[str, Any]:
        """Load all settings from database into cache"""
        if not force_reload and self._cache_loaded:
            return self._cache.copy()
        
        logger.info("📦 Loading settings from database...")
        settings = await self.db.setting.find_many()
        
        self._cache = {}
        for setting in settings:
            # Decrypt if this is a secret setting
            value_to_parse = setting.value
            if setting.isSecret:
                value_to_parse = self._decrypt(setting.value)
            
            self._cache[setting.key] = self._parse_value(value_to_parse, setting.valueType)
        
        self._cache_loaded = True
        logger.success(f"✅ Loaded {len(self._cache)} settings from database")
        return self._cache.copy()

    def _parse_value(self, value: str, value_type: str) -> Any:
        """Parse string value to appropriate type"""
        if value is None:
            return None
            
        try:
            if value_type == ValueType.INT.value:
                return int(value)
            elif value_type == ValueType.FLOAT.value:
                return float(value)
            elif value_type == ValueType.BOOL.value:
                return value.lower() in ("true", "1", "yes", "on")
            elif value_type == ValueType.JSON.value:
                if not value or value.strip() == "" or value.strip().startswith("#"):
                    return []
                import json
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    # Fallback: if it's a comma-separated string, convert to list
                    if "," in value:
                        return [v.strip() for v in value.split(",") if v.strip() and not v.strip().startswith("#")]
                    # If it's a single value that's not JSON, wrap it in a list
                    # (Most JSON settings in this app are expected to be lists)
                    cleaned_val = value.strip()
                    if cleaned_val and not cleaned_val.startswith("#"):
                        return [cleaned_val]
                    return []
            else:  # STRING
                return value
        except Exception as e:
            logger.warning(f"Failed to parse value '{value}' as {value_type}: {e}")
            return value

    def _serialize_value(self, value: Any, value_type: str) -> str:
        """Serialize value to string for storage"""
        if value_type == ValueType.JSON.value:
            import json
            return json.dumps(value)
        return str(value)

    async def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a setting value by key"""
        # Ensure cache is loaded
        if not self._cache_loaded:
            await self.load_settings()
        
        return self._cache.get(key, default)

    async def set_setting(self, key: str, value: Any, updated_by: Optional[str] = None) -> bool:
        """Update a setting value"""
        # Get setting metadata
        setting = await self.db.setting.find_unique(where={"key": key})
        
        if not setting:
            logger.error(f"Setting '{key}' not found")
            return False
        
        # Serialize value
        serialized_value = self._serialize_value(value, setting.valueType)
        
        # Encrypt if this is a secret setting
        value_to_store = serialized_value
        if setting.isSecret:
            value_to_store = self._encrypt(serialized_value)
        
        # Update in database
        await self.db.setting.update(
            where={"key": key},
            data={"value": value_to_store}
        )
        
        # Update cache (store decrypted value)
        self._cache[key] = value
        
        shown = "***" if setting.isSecret else value
        logger.info(f"✅ Setting '{key}' updated to '{shown}' (encrypted={setting.isSecret})")
        return True

    async def create_setting(
        self,
        key: str,
        value: Any,
        value_type: ValueType,
        category: SettingCategory,
        description: str,
        is_secret: bool = False
    ) -> bool:
        """Create a new setting in the database"""
        # Check if setting already exists
        existing = await self.db.setting.find_unique(where={"key": key})
        if existing:
            logger.warning(f"Setting '{key}' already exists")
            return False
        
        # Serialize value
        serialized_value = self._serialize_value(value, value_type.value)
        
        # Encrypt if this is a secret setting
        value_to_store = serialized_value
        if is_secret:
            value_to_store = self._encrypt(serialized_value)
        
        # Create in database
        await self.db.setting.create(
            data={
                "key": key,
                "value": value_to_store,
                "valueType": value_type.value,
                "category": category.value,
                "description": description,
                "isSecret": is_secret
            }
        )
        
        # Update cache (store decrypted value)
        self._cache[key] = value
        self._metadata_cache_loaded = False  # Force metadata reload
        
        logger.info(f"✅ Created new setting '{key}' (encrypted={is_secret})")
        return True

    async def get_settings_by_category(self, category: SettingCategory) -> Dict[str, Any]:
        """Get all settings in a category"""
        if not self._cache_loaded:
            await self.load_settings()
        
        # Filter by category
        category_settings = await self.db.setting.find_many(
            where={"category": category.value}
        )
        
        result = {}
        for s in category_settings:
            # Decrypt if this is a secret setting
            value_to_parse = s.value
            if s.isSecret:
                value_to_parse = self._decrypt(s.value)
            result[s.key] = self._parse_value(value_to_parse, s.valueType)
        
        return result

    async def get_all_settings_metadata(self, decrypt_secrets: bool = False) -> List[Dict[str, Any]]:
        """Get all settings with metadata (for dashboard UI)
        
        Args:
            decrypt_secrets: If True, return decrypted values for secret settings
        """
        # Always bypass cache when requesting decrypted secrets
        if self._metadata_cache_loaded and self._metadata_cache and not decrypt_secrets:
            return self._metadata_cache
        
        settings = await self.db.setting.find_many(order={"category": "asc"})
        
        result = [
            {
                "key": s.key,
                "value": s.value if not s.isSecret else ("••••••••" if not decrypt_secrets else self._decrypt(s.value)),
                "valueType": s.valueType,
                "category": s.category,
                "description": s.description,
                "isSecret": s.isSecret,
                "updatedAt": s.updatedAt.isoformat(),
                "parsedValue": None if (s.isSecret and not decrypt_secrets) else self._parse_value(
                    self._decrypt(s.value) if s.isSecret else s.value, 
                    s.valueType
                )
            }
            for s in settings
        ]
        
        # Only cache non-decrypted version for security
        if not decrypt_secrets:
            self._metadata_cache = result
            self._metadata_cache_loaded = True
        
        return result

    async def reload_cache(self):
        """Reload settings cache from database"""
        await self.load_settings(force_reload=True)
        self._metadata_cache_loaded = False  # Force metadata reload too
        await self.get_all_settings_metadata()  # Reload metadata


# Singleton instance (will be initialized in main.py)
settings_service: Optional[SettingsService] = None


async def get_settings_service(db: Prisma, encryption_key: Optional[str] = None) -> SettingsService:
    """Get or create settings service singleton"""
    global settings_service
    if settings_service is None:
        settings_service = SettingsService(db, encryption_key=encryption_key)
        await settings_service.initialize_defaults()
        await settings_service.encrypt_plaintext_secrets()
        await settings_service.load_settings()
    elif encryption_key:
        # Always reinitialize if encryption key is explicitly provided
        settings_service = SettingsService(db, encryption_key=encryption_key)
        await settings_service.initialize_defaults()
        await settings_service.encrypt_plaintext_secrets()
        await settings_service.load_settings()
    return settings_service
