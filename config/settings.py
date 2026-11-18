from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Optional
from enum import Enum


class AIProvider(str, Enum):
    OPENAI = "openai"
    GEMINI = "gemini"
    DEEPSEEK = "deepseek"
    OLLAMA = "ollama"
    PERPLEXITY = "perplexity"
    OPENROUTER = "openrouter"
    MINIMAX = "minimax"
    QWEN = "qwen"
    ALL = "all"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        protected_namespaces=('model_',),
        extra='allow'  # Allow extra fields in .env file
    )
    
    # Database settings service (will be initialized at runtime)
    _db_settings_service = None
    _use_db_settings = False
    
    # Telethon (for listening to channels)
    # Optional: without them the bot runs without Telegram. From the environment (as
    # before) or from the dashboard (AI & Bot → Telegram); a saved dashboard value wins.
    telegram_api_id: Optional[int] = None
    telegram_api_hash: Optional[str] = None
    telegram_phone: Optional[str] = None
    telegram_session_name: str = "sessions/trading_bot_session"
    
    # Telegram Bot API (optional - for sending notifications)
    telegram_bot_token: Optional[str] = None  # Get from @BotFather, optional
    
    # Channels and Notifications (loaded from database)
    telegram_channel_id: str = ""  # Can be empty - loaded from database
    telegram_notification_chat_id: Optional[str] = None

    # Discord signal source. Both live in the settings table (seeded there, so the
    # database value always wins) and are edited on the dashboard's Discord page.
    discord_enabled: bool = False
    discord_bot_token: Optional[str] = None
    discord_account_type: str = "bot"          # "bot", or "user" = the owner's own Discord account
    discord_user_token: Optional[str] = None
    process_forwarded_signals: bool = False
    
    # Trading Provider Selection ('metaapi' or 'mt5rest')
    trading_provider: str = "metaapi"
    
    # MetaAPI Cloud SDK
    metaapi_token: str = ""
    metaapi_account_id: str = ""
    # Use a streaming connection for reads (positions/orders/account/prices/specs).
    # Streamed state is free of per-call API limits; RPC is kept for trading + fallback.
    metaapi_use_streaming: bool = True
    
    # Self-hosted MT5 REST API (mt5/app/)
    mt5_rest_api_url: str = "http://mt5:5001"
    mt5_rest_api_key: str = ""
    mt5_symbol_suffix: str = ""

    # Read-only EA signal feed (GET /api/ea/signals). Informational only — it never
    # drives order placement, so it is independent of TRADING_PROVIDER/MetaAPI.
    ea_api_key: Optional[str] = None

    # Copy Master Mode: instead of placing limit orders, wait for the master
    # account to have a RUNNING position, then enter at market on this account.
    copy_master_mode: bool = False
    mt5_master_api_url: str = ""   # Master MT5 REST API base URL
    mt5_master_api_key: str = ""   # Master MT5 REST API key
    # OpenAI
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4-turbo-preview"
    openai_vision_model: str = "gpt-4o-mini"  # Vision model for image analysis

    # Gemini (Google AI Studio - OpenAI-compatible)
    gemini_api_key: Optional[str] = None
    gemini_model: str = "gemini-2.5-flash"
    gemini_vision_model: str = "gemini-2.5-flash"  # Vision model for image analysis

    # DeepSeek
    deepseek_api_key: Optional[str] = None
    deepseek_api_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_vision_model: str = "deepseek-vl2"  # Vision model for image analysis

    # Ollama
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama2"

    # Perplexity (Sonar API - OpenAI compatible)
    perplexity_api_key: Optional[str] = None
    perplexity_base_url: str = "https://api.perplexity.ai"
    perplexity_model: str = "sonar-pro"
    perplexity_vision_model: str = "sonar-pro"  # Vision model for image analysis

    # OpenRouter (multi-provider gateway - OpenAI compatible)
    openrouter_api_key: Optional[str] = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "qwen/qwen2.5-vl-72b-instruct"
    openrouter_vision_model: str = "qwen/qwen2.5-vl-72b-instruct"  # Vision model for image analysis

    # MiniMax (OpenAI compatible — https://platform.minimaxi.com/docs/api-reference/text-openai-api)
    minimax_api_key: Optional[str] = None
    minimax_base_url: str = "https://api.minimax.io/v1"
    minimax_model: str = "MiniMax-M2.7"
    minimax_vision_model: str = "MiniMax-VL-01"  # Vision model for image analysis

    # Qwen / Alibaba DashScope (OpenAI compatible)
    qwen_api_key: Optional[str] = None
    qwen_base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    qwen_model: str = "qwen-plus"
    qwen_vision_model: str = "qwen-vl-max"  # Vision model for image analysis

    # AI Selection
    primary_ai_provider: AIProvider = AIProvider.OPENAI
    fallback_ai_providers: str = "deepseek,perplexity,ollama"

    # Vision AI provider for image/chart analysis: 'openai', 'gemini', 'perplexity', or 'openrouter'
    provider: str = "openai"
    
    # AI Vision toggle
    enable_ai_vision: bool = True

    # Vision Anti-Hallucination Filters (all optional — defaults are safe)
    vision_caption_prefilter_enabled: bool = True
    vision_caption_block_keywords: str = "in profit,floating,closed,result,pips gained,balance,equity,trade history,win rate,drawdown,performance,tp hit,sl hit,hit tp,hit sl,be hit,profit taken,loss taken,tp done,tp1 done,tp2 done,tp3 done,target hit,target reached,target done,take profit hit,hit all tp,all tp hit,sl done,position closed"
    vision_confidence_filter_enabled: bool = True
    vision_min_confidence: float = 0.75
    vision_two_step_classify_enabled: bool = True
    vision_price_sanity_check_enabled: bool = True
    vision_price_ranges: str = '{"XAUUSD":[1000,5000],"EURUSD":[0.5,3.0],"GBPUSD":[0.5,3.0],"USDJPY":[50,250],"BTCUSD":[1000,500000],"ETHUSD":[100,50000],"US30":[15000,70000],"NAS100":[5000,30000],"SPX500":[1000,10000],"GBPJPY":[100,300],"USDCAD":[0.5,2.5],"AUDUSD":[0.3,1.5],"NZDUSD":[0.3,1.5],"USDCHF":[0.5,2.0],"EURJPY":[50,250],"EURGBP":[0.5,2.0]}'
    vision_sl_distance_check_enabled: bool = True
    vision_max_sl_distance_percent: float = 10.0
    vision_symbol_whitelist_enabled: bool = False
    vision_allowed_symbols: str = "XAUUSD,EURUSD,GBPUSD,USDJPY,BTCUSD,ETHUSD,US30,NAS100,SPX500,GBPJPY,USDCAD,AUDUSD,NZDUSD,USDCHF,EURJPY,EURGBP"
    vision_image_dimension_filter_enabled: bool = True
    vision_max_image_aspect_ratio: float = 3.5
    vision_min_image_height: int = 150

    # Risk Management
    max_risk_per_trade_percent: float = 2.0
    max_total_risk_per_symbol_percent: float = 6.0  # Cap on total open risk per symbol across all active trades
    max_open_positions: int = 3
    default_stop_loss_pips: int = 60  # Auto-calculated when SL is missing
    default_take_profit_pips: int = 40
    risk_reward_ratio: float = 2.0
    spread_adjustment_multiplier: float = 1.0  # Multiplier for spread adjustment on SL

    # MetaAPI Risk Management (Equity Protection for Prop Firms)
    enable_equity_protection: bool = True
    daily_drawdown_limit_percent: float = 3.0
    overall_drawdown_limit_percent: float = 10.0
    enable_drawdown_monitoring: bool = True  # Real-time monitoring

    # Trading
    min_lot_size: float = 0.01
    max_lot_size: float = 1.0
    slippage_pips: int = 3
    
    # Message Age Validation (Prevent executing old signals)
    max_signal_age_minutes: int = 5  # Reject signals older than X minutes
    
    # Instant Market Order Execution (for specific channels)
    enable_instant_execution: bool = True  # Enable instant market order execution
    instant_execution_channels: str = ""  # Comma-separated channel IDs allowed for instant execution
    instant_execution_keywords: str = "now,instant,market,immediately,asap"  # Keywords that trigger instant execution
    # How far price may have moved past the signal's entry and still be filled at
    # market for an instant ("NOW") signal; beyond it the order waits as a LIMIT.
    instant_execution_max_deviation_pips: float = 20.0
    # Beyond that cap ONE order (the furthest-TP one) still fills at market, lots
    # scaled to the same risk, while price has covered less than this percent of the
    # way from the entry to TP1. 0 = off (all orders wait as limits).
    instant_one_leg_max_tp1_progress: float = 50.0
    # "SELL GOLD NOW" without SL enters ONE position on a temporary SL using this
    # share of the signal's risk budget; the follow-up message replaces the SL. The
    # temp SL is the channel's widest recent SL on the symbol, at least these pips.
    instant_temp_sl_pips: float = 100.0
    instant_first_entry_risk_share: float = 50.0
    # A follow-up / repost / edit from the same channel within this window updates
    # the existing signal instead of opening a second one.
    signal_continuity_window_minutes: int = 30
    # Orders closer than this are "the same level" (continuity + duplicate check).
    same_level_tolerance_pips: float = 20.0
    enable_same_level_filter_across_signals: bool = True  # If false, same-level filter only checks within the same signal group
    
    # Manual Trade Approval Settings
    require_manual_approval: bool = False  # Manual Approval switch — all channels, or only approval_required_channels when set
    approval_required_channels: str = ""  # Limits Manual Approval to these channels (comma-separated); ignored while the switch is off
    approval_channel_id: Optional[str] = None  # Channel where approval requests are sent
    approval_timeout_minutes: int = 4  # Auto-reject after X minutes without approval
    approval_send_image: bool = True  # Send signal image with the Telegram approval notification
    require_approval_for_images: bool = False  # Force approval for any signal containing an image, independent of the Manual Approval switch
    # When true, a signal that would be rejected ONLY because its risk exceeds
    # MAX_RISK_PER_TRADE_PERCENT is not auto-rejected. Instead it is sent for
    # manual approval with a prominent high-risk disclaimer, so you can choose
    # to accept the extra risk or skip the trade.
    allow_high_risk_override: bool = False
    # Send a trade for manual approval when its lot size came from an estimated pip value
    require_approval_for_estimated_sizing: bool = True

    # Auto Take Profit Settings
    enable_auto_take_profit: bool = True
    auto_tp_calculation_method: str = "RR"  # "PIPS" or "RR" (Risk-Reward)
    auto_tp_pips: int = 50  # If using PIPS method
    auto_tp_risk_reward: float = 2.0  # If using RR method (e.g., 2.0 = 1:2 RR)
    
    # Trailing Stop Loss Settings
    enable_trailing_stop: bool = True
    trailing_stop_calculation_method: str = "PIPS"  # "PIPS" or "RR"
    trailing_stop_distance_pips: int = 15  # Distance in pips behind current price
    trailing_stop_distance_rr: float = 0.5  # Distance as RR ratio
    trailing_stop_min_step_pips: float = 1.0  # Only move the trailing SL when it improves by at least this many pips
    trailing_stop_min_interval_seconds: int = 10  # Minimum seconds between trailing SL modifications per trade
    trailing_activation_method: str = "PROFIT_PIPS"  # "PROFIT_PIPS", "PROFIT_RR", "PARTIAL_TP"
    trailing_activation_profit_pips: int = 20  # Activate after X pips profit
    trailing_activation_profit_rr: float = 1.0  # Activate after X:1 RR profit
    
    # Auto Partial Profit Taking Settings
    enable_auto_partial: bool = True  # Enable auto partial profit taking
    auto_partial_calculation_method: str = "RR"  # "PIPS" or "RR" (Risk-Reward)
    auto_partial_trigger_pips: int = 30  # Take partials after X pips profit (if using PIPS)
    auto_partial_trigger_rr: float = 1.5  # Take partials after X:1 RR profit (if using RR)
    auto_partial_close_percent: float = 50.0  # Close X% of position as partial

    # Runner: part of every signal goes in without a take profit. It keeps the
    # signal's SL and is closed by the SL or by the channel's messages.
    enable_runner_split: bool = False
    runner_share_percent: float = 50.0  # Share of the signal's lots placed without TP
    
    # Breakeven Settings
    enable_breakeven_move: bool = True  # Move SL to breakeven when profitable
    breakeven_trigger_method: str = "AFTER_PARTIAL"  # "AFTER_PARTIAL", "PROFIT_PIPS", or "AFTER_SIBLING_TP_HIT"
    breakeven_trigger_pips: int = 15  # Move to breakeven after X pips profit (only if method is PROFIT_PIPS)
    breakeven_buffer_pips: int = 2  # Add buffer above/below entry (e.g., +2 pips)
    breakeven_min_sibling_tp_hits: int = 1  # For AFTER_SIBLING_TP_HIT: min number of sibling TPs that must hit before triggering BE
    
    # Trade Plan Watcher
    plan_watcher_enabled: bool = True    # Master switch — disabling pauses all zone checks (plans preserved in DB)
    plan_auto_execute: bool = False      # Global default; per-plan autoExecute field overrides this
    plan_expiry_hours: int = 72          # Auto-expire plan if entry zone is never reached
    plan_gap_risk_block: bool = True     # Filter plans received when market is closed/weekend

    # Position Monitoring
    position_monitor_interval_seconds: int = 3  # How often to check positions (always fetches fresh data)
    position_monitor_startup_delay_seconds: int = 0  # No startup delay needed (cache disabled)
    enable_position_monitoring: bool = True  # Master switch for monitoring
    allow_multi_signal_posts: bool = True     # one text post with several independent trades -> one signal per trade
    catchup_enabled: bool = True              # detect messages missed while offline (digest + approval)
    catchup_max_messages: int = 50            # per channel, newest messages checked after a gap
    catchup_interval_minutes: int = 10        # periodic gap check (0 = only at startup)
    message_processing_concurrency: int = 4  # Max messages processed in parallel during bursts
    order_close_grace_misses: int = 3   # Consecutive misses before a running position is marked closed
    order_cancel_grace_misses: int = 3  # Consecutive misses before a pending order is marked cancelled
    order_stale_pending_hours: int = 4  # Hours before an unmatched PENDING trade is auto-cancelled
    
    # Trading Brain (conversational LLM session that reviews every signal and position)
    enable_trading_brain: bool = True
    brain_base_url: Optional[str] = None     # Custom Hermes/OpenAI-compatible URL e.g. http://hermes:8080/v1
    brain_api_key: Optional[str] = None      # API key for the brain endpoint (falls back to provider key)
    brain_model: str = ""                    # Leave empty to use the configured AI provider's model
    brain_temperature: float = 0.3
    brain_max_history_messages: int = 60     # Trim conversation after this many messages
    brain_position_review_interval: int = 30  # Seconds between position reviews
    brain_action_require_approval: bool = True   # Require Telegram approval before brain executes position actions
    brain_action_approval_types: str = "CLOSE,PARTIAL_CLOSE,MODIFY_SL,MODIFY_TP"  # Comma-separated actions that need approval
    brain_unavailable_action: str = "APPROVE"    # When brain is down/unconfigured: APPROVE (trade anyway), REJECT, APPROVAL (manual approval queue), or PIPELINE (defer to the rest of the configured pipeline, as if the brain were disabled)
    brain_send_images: bool = True               # Send the signal's chart/screenshot image to the brain, not just text
    # Master "validation" switch. True (default) = current behavior: the Brain
    # can REJECT a signal and a failed risk assessment blocks execution. False =
    # a structurally valid signal (extracted with symbol/direction/SL) is never
    # blocked by the Brain's REJECT verdict or by the risk assessment's approval
    # flag — it executes. The Brain can still MODIFY (adjust entry/SL/TP/lot)
    # since that refines a trade rather than rejecting it. Risk sizing math still
    # runs either way (needed for lot size). Drawdown protection is a separate,
    # account-level safety net and is NOT affected by this switch.
    require_risk_validation: bool = True

    # AI Market Analysis Features (Advanced)
    enable_ai_market_analysis: bool = False  # Master switch for AI market analysis
    ai_analysis_check_interval: int = 30  # Check market conditions every X seconds (when enabled)
    enable_ai_breakeven_triggers: bool = False  # AI-powered breakeven recommendations
    enable_ai_tp_adjustment: bool = False  # AI-powered TP adjustment suggestions
    enable_ai_position_reduction: bool = False  # AI-powered position reduction in adverse trends
    ai_analysis_confidence_threshold: float = 0.7  # Minimum confidence to act on AI recommendations (0.0-1.0)
    ai_auto_verification_enabled: bool = False  # Enable AI auto-verification of signals
    
    # LLM-Powered Market Analysis
    enable_llm_market_analysis: bool = False    # Enable LLM-powered market analysis (uses AI provider credits)
    llm_market_analysis_interval: int = 60      # Minimum seconds between LLM calls per symbol
    
    # Database
    # Note: SQLite path is relative to where the script runs (project root)
    # timeout=30000 (30 seconds) helps prevent "database is locked" errors
    database_url: str = "sqlite:///./data/trading_bot.db?timeout=30000"
    
    # News Trading Filter (Economic Calendar)
    news_enable_filter: bool = True
    news_minutes_before: int = 10
    news_minutes_after: int = 5
    news_important_impacts: str = "High,Medium"
    news_target_currencies: str = "EUR,USD,CAD,JPY,GBP"
    news_api_url: str = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
    news_update_interval_hours: int = 24
    news_verbose_logging: bool = False
    news_enable_notifications: bool = True
    news_notification_minutes_before: int = 10
    # News posts to a channel of the owner's choice — own impact/currency filter,
    # independent of the trading filter above.
    news_post_enabled: bool = False
    news_post_channel_id: str = ""
    news_post_impacts: str = "High"
    news_post_currencies: str = "USD"
    news_post_minutes_before: int = 30
    
    # Signal Validator API
    enable_signal_validator: bool = False
    signal_validator_url: str = "http://signal-validator:8000"  # your own validator service
    signal_validator_api_key: Optional[str] = None
    signal_validator_timeout_seconds: int = 5
    signal_validator_execution_policy: str = "VALID_WARN"  # ALL, VALID_WARN, VALID_ONLY
    
    # Dashboard Settings
    dashboard_domain: Optional[str] = None
    dashboard_username: Optional[str] = None
    dashboard_hashed_password: Optional[str] = None
    
    # Clerk Authentication (Dashboard)
    settings_encryption_key: Optional[str] = None
    next_public_clerk_publishable_key: Optional[str] = None
    clerk_secret_key: Optional[str] = None
    next_public_clerk_sign_in_url: Optional[str] = None
    next_public_clerk_sign_up_url: Optional[str] = None
    next_public_clerk_after_sign_in_url: Optional[str] = None
    next_public_clerk_after_sign_up_url: Optional[str] = None
    authorized_user_id: Optional[str] = None
    
    # General
    log_level: str = "INFO"
    log_file_level: Optional[str] = None  # File logging level (defaults to log_level if not set)
    log_file_debug: bool = False  # Set to True to force DEBUG logging to files
    dry_run: bool = False
    timezone: str = "UTC"
    skip_metaapi: bool = False
    
    @property
    def telegram_channels(self) -> List[str]:
        """Parse comma-separated channel IDs"""
        return [ch.strip() for ch in self.telegram_channel_id.split(",")]
    
    @property
    def fallback_providers(self) -> List[str]:
        """Parse comma-separated fallback providers"""
        if not self.fallback_ai_providers:
            return []
        return [p.strip() for p in self.fallback_ai_providers.split(",")]
    
    @property
    def instant_execution_channel_list(self) -> List[str]:
        """Parse comma-separated instant execution channel IDs"""
        if not self.instant_execution_channels:
            return []
        return [ch.strip() for ch in self.instant_execution_channels.split(",")]
    
    @property
    def instant_execution_keyword_list(self) -> List[str]:
        """Parse comma-separated instant execution keywords"""
        if not self.instant_execution_keywords:
            return []
        return [kw.strip().lower() for kw in self.instant_execution_keywords.split(",")]
    
    @property
    def provider_label(self) -> str:
        """Human-readable label for the active trading provider."""
        p = self.trading_provider.lower().strip()
        if p == "mt5rest":
            return "MT5 REST API"
        return "MetaAPI"

    @property
    def approval_required_channel_list(self) -> List[str]:
        """Parse comma-separated approval required channel IDs"""
        if not self.approval_required_channels:
            return []
        return [ch.strip() for ch in self.approval_required_channels.split(",")]

    def set_db_settings_service(self, db_settings_service):
        """Set the database settings service for hot reload"""
        self._db_settings_service = db_settings_service
        self._use_db_settings = True

    # Keys where a value change only takes effect after bot restart.
    # Hot-reload will update the in-memory value but the active connection won't change.
    # (TRADING_PROVIDER is hot-switchable via provider_manager; credentials/URLs trigger a reconnect.)
    _RESTART_REQUIRED_KEYS: set = set()
    _loaded_once: bool = False

    # Full mapping: every DB key that maps to a Settings attribute.
    # TELEGRAM_API_ID / TELEGRAM_API_HASH / TELEGRAM_PHONE: see _ENV_FALLBACK_KEYS.
    _KEY_MAPPING = {
        # Credentials (loaded at startup; restart-required ones log a warning on hot-reload)
        "METAAPI_TOKEN":                    "metaapi_token",
        "METAAPI_ACCOUNT_ID":               "metaapi_account_id",
        "METAAPI_USE_STREAMING":            "metaapi_use_streaming",
        "NEWS_UPDATE_INTERVAL_HOURS":       "news_update_interval_hours",
        "POSITION_MONITOR_STARTUP_DELAY_SECONDS": "position_monitor_startup_delay_seconds",
        "SIGNAL_VALIDATOR_API_KEY":         "signal_validator_api_key",
        "MT5_REST_API_KEY":                 "mt5_rest_api_key",
        "EA_API_KEY":                       "ea_api_key",
        "OPENAI_API_KEY":                   "openai_api_key",
        "DEEPSEEK_API_KEY":                 "deepseek_api_key",
        "TELEGRAM_API_ID":                  "telegram_api_id",
        "TELEGRAM_API_HASH":                "telegram_api_hash",
        "TELEGRAM_PHONE":                   "telegram_phone",
        "TELEGRAM_BOT_TOKEN":               "telegram_bot_token",
        "TELEGRAM_CHANNEL_ID":              "telegram_channel_id",
        "TELEGRAM_NOTIFICATION_CHAT_ID":    "telegram_notification_chat_id",
        "PROCESS_FORWARDED_SIGNALS":        "process_forwarded_signals",
        "DISCORD_ENABLED":                  "discord_enabled",
        "DISCORD_BOT_TOKEN":                "discord_bot_token",
        "DISCORD_ACCOUNT_TYPE":             "discord_account_type",
        "DISCORD_USER_TOKEN":               "discord_user_token",
        # Trading Provider
        "TRADING_PROVIDER":                 "trading_provider",
        "MT5_REST_API_URL":                 "mt5_rest_api_url",
        "MT5_SYMBOL_SUFFIX":                "mt5_symbol_suffix",
        # Risk management
        "MAX_RISK_PER_TRADE_PERCENT":       "max_risk_per_trade_percent",
        "MAX_TOTAL_RISK_PER_SYMBOL_PERCENT": "max_total_risk_per_symbol_percent",
        "MAX_OPEN_POSITIONS":               "max_open_positions",
        "DEFAULT_STOP_LOSS_PIPS":           "default_stop_loss_pips",
        "DEFAULT_TAKE_PROFIT_PIPS":         "default_take_profit_pips",
        "RISK_REWARD_RATIO":                "risk_reward_ratio",
        "SPREAD_ADJUSTMENT_MULTIPLIER":     "spread_adjustment_multiplier",
        "ENABLE_EQUITY_PROTECTION":         "enable_equity_protection",
        "DAILY_DRAWDOWN_LIMIT_PERCENT":     "daily_drawdown_limit_percent",
        "OVERALL_DRAWDOWN_LIMIT_PERCENT":   "overall_drawdown_limit_percent",
        "ENABLE_DRAWDOWN_MONITORING":       "enable_drawdown_monitoring",
        # Trading
        "MIN_LOT_SIZE":                     "min_lot_size",
        "MAX_LOT_SIZE":                     "max_lot_size",
        "SLIPPAGE_PIPS":                    "slippage_pips",
        "MAX_SIGNAL_AGE_MINUTES":           "max_signal_age_minutes",
        "ENABLE_INSTANT_EXECUTION":         "enable_instant_execution",
        "INSTANT_EXECUTION_CHANNELS":       "instant_execution_channels",
        "INSTANT_EXECUTION_KEYWORDS":       "instant_execution_keywords",
        "INSTANT_EXECUTION_MAX_DEVIATION_PIPS": "instant_execution_max_deviation_pips",
        "INSTANT_ONE_LEG_MAX_TP1_PROGRESS": "instant_one_leg_max_tp1_progress",
        "INSTANT_TEMP_SL_PIPS":             "instant_temp_sl_pips",
        "INSTANT_FIRST_ENTRY_RISK_SHARE":   "instant_first_entry_risk_share",
        "SIGNAL_CONTINUITY_WINDOW_MINUTES": "signal_continuity_window_minutes",
        "SAME_LEVEL_TOLERANCE_PIPS":        "same_level_tolerance_pips",
        "ENABLE_SAME_LEVEL_FILTER_ACROSS_SIGNALS": "enable_same_level_filter_across_signals",
        "REQUIRE_MANUAL_APPROVAL":          "require_manual_approval",
        "APPROVAL_REQUIRED_CHANNELS":       "approval_required_channels",
        "APPROVAL_CHANNEL_ID":              "approval_channel_id",
        "APPROVAL_TIMEOUT_MINUTES":         "approval_timeout_minutes",
        "APPROVAL_SEND_IMAGE":              "approval_send_image",
        "REQUIRE_APPROVAL_FOR_IMAGES":      "require_approval_for_images",
        "ALLOW_HIGH_RISK_OVERRIDE":         "allow_high_risk_override",
        "REQUIRE_APPROVAL_FOR_ESTIMATED_SIZING": "require_approval_for_estimated_sizing",
        "ENABLE_AUTO_TAKE_PROFIT":          "enable_auto_take_profit",
        "AUTO_TP_CALCULATION_METHOD":       "auto_tp_calculation_method",
        "AUTO_TP_PIPS":                     "auto_tp_pips",
        "AUTO_TP_RISK_REWARD":              "auto_tp_risk_reward",
        "ENABLE_TRAILING_STOP":             "enable_trailing_stop",
        "TRAILING_STOP_CALCULATION_METHOD": "trailing_stop_calculation_method",
        "TRAILING_STOP_DISTANCE_PIPS":      "trailing_stop_distance_pips",
        "TRAILING_STOP_DISTANCE_RR":        "trailing_stop_distance_rr",
        "TRAILING_STOP_MIN_STEP_PIPS":      "trailing_stop_min_step_pips",
        "TRAILING_STOP_MIN_INTERVAL_SECONDS": "trailing_stop_min_interval_seconds",
        "TRAILING_ACTIVATION_METHOD":       "trailing_activation_method",
        "TRAILING_ACTIVATION_PROFIT_PIPS":  "trailing_activation_profit_pips",
        "TRAILING_ACTIVATION_PROFIT_RR":    "trailing_activation_profit_rr",
        "ENABLE_AUTO_PARTIAL":              "enable_auto_partial",
        "AUTO_PARTIAL_CALCULATION_METHOD":  "auto_partial_calculation_method",
        "AUTO_PARTIAL_TRIGGER_PIPS":        "auto_partial_trigger_pips",
        "AUTO_PARTIAL_TRIGGER_RR":          "auto_partial_trigger_rr",
        "AUTO_PARTIAL_CLOSE_PERCENT":       "auto_partial_close_percent",
        "ENABLE_RUNNER_SPLIT":              "enable_runner_split",
        "RUNNER_SHARE_PERCENT":             "runner_share_percent",
        "ENABLE_BREAKEVEN_MOVE":            "enable_breakeven_move",
        "BREAKEVEN_TRIGGER_METHOD":         "breakeven_trigger_method",
        "BREAKEVEN_TRIGGER_PIPS":           "breakeven_trigger_pips",
        "BREAKEVEN_BUFFER_PIPS":            "breakeven_buffer_pips",
        "BREAKEVEN_MIN_SIBLING_TP_HITS":    "breakeven_min_sibling_tp_hits",
        # Trade Plans
        "PLAN_WATCHER_ENABLED":             "plan_watcher_enabled",
        "PLAN_AUTO_EXECUTE":                "plan_auto_execute",
        "PLAN_EXPIRY_HOURS":                "plan_expiry_hours",
        "PLAN_GAP_RISK_BLOCK":              "plan_gap_risk_block",
        # Monitoring
        "POSITION_MONITOR_INTERVAL_SECONDS": "position_monitor_interval_seconds",
        "ENABLE_POSITION_MONITORING":        "enable_position_monitoring",
        "MESSAGE_PROCESSING_CONCURRENCY":    "message_processing_concurrency",
        "ALLOW_MULTI_SIGNAL_POSTS":          "allow_multi_signal_posts",
        "CATCHUP_ENABLED":                   "catchup_enabled",
        "CATCHUP_MAX_MESSAGES":              "catchup_max_messages",
        "CATCHUP_INTERVAL_MINUTES":          "catchup_interval_minutes",
        "ORDER_CLOSE_GRACE_MISSES":          "order_close_grace_misses",
        "ORDER_CANCEL_GRACE_MISSES":         "order_cancel_grace_misses",
        "ORDER_STALE_PENDING_HOURS":         "order_stale_pending_hours",
        # Trading Brain
        "ENABLE_TRADING_BRAIN":             "enable_trading_brain",
        "BRAIN_BASE_URL":                   "brain_base_url",
        "BRAIN_API_KEY":                    "brain_api_key",
        "BRAIN_MODEL":                      "brain_model",
        "BRAIN_TEMPERATURE":                "brain_temperature",
        "BRAIN_MAX_HISTORY_MESSAGES":       "brain_max_history_messages",
        "BRAIN_POSITION_REVIEW_INTERVAL":   "brain_position_review_interval",
        "BRAIN_ACTION_REQUIRE_APPROVAL":    "brain_action_require_approval",
        "BRAIN_ACTION_APPROVAL_TYPES":      "brain_action_approval_types",
        "BRAIN_UNAVAILABLE_ACTION":         "brain_unavailable_action",
        "BRAIN_SEND_IMAGES":                "brain_send_images",
        "REQUIRE_RISK_VALIDATION":          "require_risk_validation",
        # AI
        "ENABLE_AI_MARKET_ANALYSIS":        "enable_ai_market_analysis",
        "AI_ANALYSIS_CHECK_INTERVAL":       "ai_analysis_check_interval",
        "ENABLE_AI_BREAKEVEN_TRIGGERS":     "enable_ai_breakeven_triggers",
        "ENABLE_AI_TP_ADJUSTMENT":          "enable_ai_tp_adjustment",
        "ENABLE_AI_POSITION_REDUCTION":     "enable_ai_position_reduction",
        "AI_ANALYSIS_CONFIDENCE_THRESHOLD": "ai_analysis_confidence_threshold",
        # LLM Market Analysis
        "ENABLE_LLM_MARKET_ANALYSIS":       "enable_llm_market_analysis",
        "LLM_MARKET_ANALYSIS_INTERVAL":     "llm_market_analysis_interval",
        # News
        "NEWS_ENABLE_FILTER":               "news_enable_filter",
        "NEWS_MINUTES_BEFORE":              "news_minutes_before",
        "NEWS_MINUTES_AFTER":               "news_minutes_after",
        "NEWS_IMPORTANT_IMPACTS":           "news_important_impacts",
        "NEWS_TARGET_CURRENCIES":           "news_target_currencies",
        "NEWS_VERBOSE_LOGGING":             "news_verbose_logging",
        "NEWS_ENABLE_NOTIFICATIONS":        "news_enable_notifications",
        "NEWS_NOTIFICATION_MINUTES_BEFORE": "news_notification_minutes_before",
        "NEWS_API_URL":                     "news_api_url",
        "NEWS_POST_ENABLED":                "news_post_enabled",
        "NEWS_POST_CHANNEL_ID":             "news_post_channel_id",
        "NEWS_POST_IMPACTS":                "news_post_impacts",
        "NEWS_POST_CURRENCIES":             "news_post_currencies",
        "NEWS_POST_MINUTES_BEFORE":         "news_post_minutes_before",
        # AI Provider Configuration
        "OPENAI_MODEL":                     "openai_model",
        "DEEPSEEK_MODEL":                   "deepseek_model",
        "DEEPSEEK_API_URL":                 "deepseek_api_url",
        "DEEPSEEK_VISION_MODEL":            "deepseek_vision_model",
        "PERPLEXITY_API_KEY":               "perplexity_api_key",
        "PERPLEXITY_BASE_URL":              "perplexity_base_url",
        "PERPLEXITY_MODEL":                 "perplexity_model",
        "OPENROUTER_API_KEY":               "openrouter_api_key",
        "OPENROUTER_BASE_URL":              "openrouter_base_url",
        "OPENROUTER_MODEL":                 "openrouter_model",
        "OPENROUTER_VISION_MODEL":          "openrouter_vision_model",
        "MINIMAX_API_KEY":                  "minimax_api_key",
        "MINIMAX_BASE_URL":                 "minimax_base_url",
        "MINIMAX_MODEL":                    "minimax_model",
        "MINIMAX_VISION_MODEL":             "minimax_vision_model",
        "QWEN_API_KEY":                     "qwen_api_key",
        "QWEN_BASE_URL":                    "qwen_base_url",
        "QWEN_MODEL":                       "qwen_model",
        "QWEN_VISION_MODEL":                "qwen_vision_model",
        "OLLAMA_URL":                       "ollama_url",
        "OLLAMA_MODEL":                     "ollama_model",
        "PRIMARY_AI_PROVIDER":               "primary_ai_provider",
        "FALLBACK_AI_PROVIDERS":            "fallback_ai_providers",
        "provider":                         "provider",  # Vision AI provider
        "ENABLE_AI_VISION":                 "enable_ai_vision",
        "VISION_CAPTION_PREFILTER_ENABLED": "vision_caption_prefilter_enabled",
        "VISION_CAPTION_BLOCK_KEYWORDS":    "vision_caption_block_keywords",
        "VISION_CONFIDENCE_FILTER_ENABLED": "vision_confidence_filter_enabled",
        "VISION_MIN_CONFIDENCE":            "vision_min_confidence",
        "VISION_TWO_STEP_CLASSIFY_ENABLED": "vision_two_step_classify_enabled",
        "VISION_PRICE_SANITY_CHECK_ENABLED":"vision_price_sanity_check_enabled",
        "VISION_PRICE_RANGES":              "vision_price_ranges",
        "VISION_SL_DISTANCE_CHECK_ENABLED": "vision_sl_distance_check_enabled",
        "VISION_MAX_SL_DISTANCE_PERCENT":   "vision_max_sl_distance_percent",
        "VISION_SYMBOL_WHITELIST_ENABLED":  "vision_symbol_whitelist_enabled",
        "VISION_ALLOWED_SYMBOLS":           "vision_allowed_symbols",
        "VISION_IMAGE_DIMENSION_FILTER_ENABLED": "vision_image_dimension_filter_enabled",
        "VISION_MAX_IMAGE_ASPECT_RATIO":    "vision_max_image_aspect_ratio",
        "VISION_MIN_IMAGE_HEIGHT":          "vision_min_image_height",
        "OPENAI_VISION_MODEL":              "openai_vision_model",
        "GEMINI_API_KEY":                   "gemini_api_key",
        "GEMINI_MODEL":                     "gemini_model",
        "GEMINI_VISION_MODEL":              "gemini_vision_model",
        "PERPLEXITY_VISION_MODEL":          "perplexity_vision_model",
        "AI_AUTO_VERIFICATION_ENABLED":     "ai_auto_verification_enabled",
        # Signal Validator
        "ENABLE_SIGNAL_VALIDATOR":          "enable_signal_validator",
        "SIGNAL_VALIDATOR_URL":             "signal_validator_url",
        "SIGNAL_VALIDATOR_TIMEOUT_SECONDS": "signal_validator_timeout_seconds",
        "SIGNAL_VALIDATOR_EXECUTION_POLICY":"signal_validator_execution_policy",
        # General Settings
        "LOG_LEVEL":                        "log_level",
        "LOG_FILE_LEVEL":                   "log_file_level",
        "LOG_FILE_DEBUG":                   "log_file_debug",
        "DRY_RUN":                          "dry_run",
        "TIMEZONE":                         "timezone",
        "SKIP_METAAPI":                     "skip_metaapi",
        # Copy Master
        "COPY_MASTER_MODE":                 "copy_master_mode",
    }

    # Seeded empty in the database so they can be set from the dashboard, but existing
    # installs have them in the environment: an empty database value never replaces that.
    _ENV_FALLBACK_KEYS = {"TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_PHONE"}

    # Comma-separated string fields (DB may return lists for these)
    _CSV_ATTRS = {
        "telegram_channel_id", "instant_execution_channels",
        "approval_required_channels", "news_important_impacts",
        "news_target_currencies", "instant_execution_keywords",
        "news_post_impacts", "news_post_currencies",
        "fallback_ai_providers",   # seeded as a JSON list; the fallback_providers property splits a string
    }

    _AI_PREFIXES = ("OPENAI", "GEMINI", "DEEPSEEK", "PERPLEXITY", "OPENROUTER", "MINIMAX", "QWEN",
                    "VISION", "PRIMARY_AI", "FALLBACK_PROVIDERS", "ENABLE_AI_VISION")

    def _apply_service_reloads(self, changed_keys: set):
        """Services that snapshot settings at construction are refreshed when their keys change."""
        from loguru import logger
        try:
            if any(k.startswith(self._AI_PREFIXES) for k in changed_keys):
                from src.services.signal_service import signal_service
                signal_service.reinitialize()
                logger.info("🔄 Signal/vision service reloaded with new AI settings")
            if any(k.startswith("NEWS_") for k in changed_keys):
                from src.services.news_service import news_trading_service
                if news_trading_service:
                    news_trading_service.reload_settings()
                    logger.info("🔄 News service reloaded with new settings")
            if any(k.startswith("DISCORD_") for k in changed_keys):
                from src.integrations.discord.listener import discord_listener
                from src.utils.tasks import spawn
                spawn(discord_listener.apply_settings(), name="discord_apply_settings")
        except Exception as e:
            logger.warning(f"Service reload after settings change failed: {e}")

    async def reload_from_db(self):
        """Load/reload all settings from database into this Settings instance."""
        if not (self._db_settings_service and self._use_db_settings):
            return

        from loguru import logger
        first_load = not self._loaded_once
        self._loaded_once = True
        await self._db_settings_service.reload_cache()
        db_settings = await self._db_settings_service.load_settings()

        restart_changed = []
        logging_changed = []
        changed_keys = set()
        change_log = {}
        applied = 0
        missing_seeded = []      # DB should hold these (they're seeded) but doesn't — a real problem
        missing_unseeded = []    # not seeded (credentials/env-supplied) — expected to be absent

        # Keys that initialize_defaults() seeds into the DB. Anything mapped but
        # NOT in here is credential/env-supplied and legitimately may be absent.
        try:
            from src.services.settings_service import SettingsService
            seeded_keys = set(SettingsService.DEFAULT_SETTINGS.keys())
        except Exception:
            seeded_keys = set()

        for db_key, attr_name in self._KEY_MAPPING.items():
            if db_key not in db_settings:
                # DB is the source of truth — record what's missing instead of
                # silently keeping the hardcoded default.
                if db_key in seeded_keys:
                    missing_seeded.append(db_key)
                else:
                    missing_unseeded.append(db_key)
                continue
            value = db_settings[db_key]
            if db_key in self._ENV_FALLBACK_KEYS and str(value if value is not None else "").strip() in ("", "0"):
                applied += 1
                continue
            if isinstance(value, list) and attr_name in self._CSV_ATTRS:
                value = ",".join(str(v) for v in value)
            current = getattr(self, attr_name, None)
            # DB values are plain strings — cast back to the field's Enum type
            # (e.g. AIProvider) so attribute access like `.value` keeps working.
            if isinstance(current, Enum) and not isinstance(value, Enum):
                try:
                    value = type(current)(value)
                except ValueError:
                    logger.warning(
                        f"⚠️  DB value '{value}' for {db_key} is not a valid "
                        f"{type(current).__name__} — keeping current setting"
                    )
                    applied += 1
                    continue
            if value != current:
                if db_key in self._RESTART_REQUIRED_KEYS:
                    restart_changed.append(db_key)
                # Track logging settings that changed
                if db_key in ("LOG_LEVEL", "LOG_FILE_LEVEL", "LOG_FILE_DEBUG"):
                    logging_changed.append(db_key)
                from src.utils.audit import redact
                change_log[db_key] = {"old": redact(db_key, current), "new": redact(db_key, value)}
                setattr(self, attr_name, value)
                changed_keys.add(db_key)
            applied += 1

        # DB is authoritative: a seeded key missing from the DB means the value
        # silently fell back to a hardcoded default — surface it loudly so it can
        # be fixed rather than masked. (initialize_defaults() should have created
        # every seeded key, so this normally never fires.)
        if missing_seeded:
            logger.error(
                f"🚨 {len(missing_seeded)} setting(s) are missing from the database and "
                f"fell back to hardcoded defaults — run initialize_defaults() or add them "
                f"to the settings table: " + ", ".join(sorted(missing_seeded))
            )
        if missing_unseeded:
            logger.debug(
                f"ℹ️  {len(missing_unseeded)} mapped setting(s) not in DB (credential/"
                f"env-supplied, expected): " + ", ".join(sorted(missing_unseeded))
            )

        if restart_changed:
            logger.warning(
                "⚠️  Settings reloaded — the following changes require a bot restart to take effect: "
                + ", ".join(restart_changed)
            )

        # Reconfigure logging if logging settings changed
        if logging_changed:
            from config.logging_config import configure_logging
            configure_logging(self)
            logger.info(f"📝 Logging reconfigured (changed: {', '.join(logging_changed)})")
        
        if changed_keys:
            logger.info(f"⚙️  Settings changed: {', '.join(sorted(changed_keys))}")
            if not first_load:
                from src.utils.audit import audit
                audit("AUDIT", f"{len(changed_keys)} setting(s) changed", "LOW", change_log, module="settings")
            # Apply side effects live (provider switch / reconnect / stream toggle)
            try:
                from src.integrations.trading.provider_manager import provider_manager
                await provider_manager.on_settings_reload(changed_keys)
            except Exception as e:
                logger.error(f"Applying live settings changes failed: {e}")
            self._apply_service_reloads(changed_keys)
        logger.success(f"✅ Settings loaded from database ({applied} keys)") if (first_load or changed_keys) \
            else logger.debug(f"Settings unchanged ({applied} keys)")


settings = Settings()
