'use client'

import React, { useState, useEffect, useMemo, useRef, JSX } from 'react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import {
  Settings as SettingsIcon,
  RefreshCw,
  Lock,
  Terminal,
  BookOpen,
  Zap,
  TrendingUp,
  Brain,
  Search,
  CheckCircle2,
  AlertTriangle,
  History as HistoryIcon,
  LayoutGrid,
  ShieldAlert,
  Cpu,
  MessagesSquare,
  Globe,
  Loader2,
  ExternalLink,
  Eye,
  EyeOff,
  Plus,
  Save,
  XCircle,
  Server,
  Activity,
  Bell,
} from 'lucide-react'
import type { Setting } from '@/lib/types/settings'
import { useToast } from '@/hooks/use-toast'
import MobilePageHeader from '@/components/MobilePageHeader'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import TelegramChannelSelector, { type ExtraChannel } from '@/components/TelegramChannelSelector'
import TelegramNotificationSelector from '@/components/TelegramNotificationSelector'
import AIConfigPanel, { type AIConfigPanelRef } from '@/components/AIConfigPanel'
import ModelSelect from '@/components/ModelSelect'
import SearchableSelect from '@/components/SearchableSelect'

// ─── Model field → provider mapping ───────────────────────────────────────────

const MODEL_FIELD_PROVIDERS: Record<string, string> = {
  OPENAI_MODEL:            'openai',
  OPENAI_VISION_MODEL:     'openai',
  GEMINI_MODEL:            'gemini',
  GEMINI_VISION_MODEL:     'gemini',
  PERPLEXITY_MODEL:        'perplexity',
  PERPLEXITY_VISION_MODEL: 'perplexity',
  DEEPSEEK_MODEL:          'deepseek',
  DEEPSEEK_VISION_MODEL:     'deepseek',
  OPENROUTER_MODEL:          'openrouter',
  OPENROUTER_VISION_MODEL:   'openrouter',
  MINIMAX_MODEL:             'minimax',
  MINIMAX_VISION_MODEL:      'minimax',
  QWEN_MODEL:                'qwen',
  QWEN_VISION_MODEL:         'qwen',
  OLLAMA_MODEL:              'ollama',
}

// ─── Schema types ─────────────────────────────────────────────────────────────

const WIDE_SETTING_KEYS = new Set([
  'TELEGRAM_CHANNEL_ID',
  'TELEGRAM_NOTIFICATION_CHAT_ID',
  'SIGNAL_FORWARD_CHANNEL_ID',
  'APPROVAL_REQUIRED_CHANNELS',
  'INSTANT_EXECUTION_CHANNELS',
  'APPROVAL_CHANNEL_ID',
  'FALLBACK_AI_PROVIDERS',
  'NEWS_IMPORTANT_IMPACTS',
  'NEWS_TARGET_CURRENCIES',
  'NEWS_POST_CHANNEL_ID',
  'NEWS_POST_IMPACTS',
  'NEWS_POST_CURRENCIES',
  'BRAIN_ACTION_APPROVAL_TYPES',
])

interface FieldDef {
  key: string
  showWhen?: (s: Record<string, any>) => boolean
}

interface SubSection {
  id: string
  title: string
  description: string
  masterToggle?: string
  showWhen?: (s: Record<string, any>) => boolean
  fullWidth?: boolean
  fields: FieldDef[]
}

interface TabDef {
  id: string
  label: string
  icon: JSX.Element
  description: string
  twoCol?: boolean
  subSections: SubSection[]
}

// Master notification switch — treat "not yet loaded" as on so the per-category
// sections stay visible while settings are still being fetched.
const notifyMasterOn = (s: Record<string, any>) =>
  s['NOTIFY_ENABLED'] !== false && s['NOTIFY_ENABLED'] !== 'false'

// ─── Dropdown options ──────────────────────────────────────────────────────────

const settingOptions: Record<string, Array<{ value: string; label: string; description?: string }>> = {
  provider: [
    { value: 'openai',      label: 'OpenAI',      description: 'GPT-4o Mini — reliable, widely supported' },
    { value: 'gemini',      label: 'Gemini',      description: 'Gemini 2.0 Flash — cheapest (~10x less than OpenAI)' },
    { value: 'perplexity',  label: 'Perplexity',  description: 'Perplexity Sonar — web-augmented' },
    { value: 'openrouter',  label: 'OpenRouter',  description: 'OpenRouter — access hundreds of models via one API' },
    { value: 'minimax',     label: 'MiniMax',     description: 'MiniMax — strong vision models, OpenAI-compatible' },
    { value: 'qwen',        label: 'Qwen',        description: 'Qwen (Alibaba DashScope) — multilingual, OpenAI-compatible' },
  ],
  TRADING_PROVIDER: [
    { value: 'mt5rest',  label: 'MT5 REST API', description: 'Self-hosted (recommended)' },
    { value: 'metaapi',  label: 'MetaAPI',      description: 'Cloud SDK' },
  ],
  PRIMARY_AI_PROVIDER: [
    { value: 'openai',      label: 'OpenAI',      description: 'GPT-4 series' },
    { value: 'deepseek',    label: 'DeepSeek',    description: 'DeepSeek Chat' },
    { value: 'gemini',      label: 'Gemini',      description: 'Gemini 2.0 Flash' },
    { value: 'openrouter',  label: 'OpenRouter',  description: 'Hundreds of models via one API' },
    { value: 'ollama',      label: 'Ollama',      description: 'Local LLM' },
    { value: 'perplexity',  label: 'Perplexity',  description: 'Perplexity Sonar' },
    { value: 'minimax',     label: 'MiniMax',     description: 'MiniMax M2.7 — OpenAI-compatible' },
    { value: 'qwen',        label: 'Qwen',        description: 'Qwen — Alibaba DashScope' },
  ],
  AUTO_TP_CALCULATION_METHOD: [
    { value: 'PIPS', label: 'Pips',          description: 'Fixed pips distance' },
    { value: 'RR',   label: 'Risk/Reward',   description: 'Based on R:R ratio' },
  ],
  TRAILING_STOP_CALCULATION_METHOD: [
    { value: 'PIPS', label: 'Pips',          description: 'Fixed pips distance' },
    { value: 'RR',   label: 'Risk/Reward',   description: 'Based on R:R ratio' },
  ],
  TRAILING_ACTIVATION_METHOD: [
    { value: 'IMMEDIATE',    label: 'Immediate',       description: 'Start trailing immediately' },
    { value: 'PROFIT_PIPS',  label: 'Profit Pips',     description: 'After X pips profit' },
    { value: 'PROFIT_RR',    label: 'Profit R:R',      description: 'After X:1 R:R profit' },
    { value: 'PARTIAL_TP',   label: 'After Partial TP', description: 'After partial profit taken' },
  ],
  AUTO_PARTIAL_CALCULATION_METHOD: [
    { value: 'PIPS', label: 'Pips',          description: 'Fixed pips distance' },
    { value: 'RR',   label: 'Risk/Reward',   description: 'Based on R:R ratio' },
  ],
  BREAKEVEN_TRIGGER_METHOD: [
    { value: 'AFTER_PARTIAL',        label: 'After Partial',     description: 'After partial TP taken' },
    { value: 'PROFIT_PIPS',          label: 'Profit Pips',       description: 'After X pips profit' },
    { value: 'AFTER_SIBLING_TP_HIT', label: 'After Sibling TP',  description: 'When sibling trades hit TP' },
  ],
  SIGNAL_VALIDATOR_EXECUTION_POLICY: [
    { value: 'ALL',        label: 'All Signals',  description: 'Trade regardless of verdict' },
    { value: 'VALID_WARN', label: 'Valid + Warn', description: 'Block only INVALID (recommended)' },
    { value: 'VALID_ONLY', label: 'Valid Only',   description: 'Only VALID passes' },
  ],
  BRAIN_UNAVAILABLE_ACTION: [
    { value: 'APPROVE',  label: 'Approve (trade anyway)', description: 'Default — let signals through when the brain is down' },
    { value: 'REJECT',   label: 'Reject',                 description: 'Block every signal while the brain is unavailable' },
    { value: 'APPROVAL', label: 'Manual Approval',         description: 'Send every signal to the manual approval queue' },
    { value: 'PIPELINE', label: 'Use Pipeline As Configured', description: 'Skip the brain — defer to your normal pipeline (risk manager, validator, approval rules) exactly as configured' },
  ],
  LOG_LEVEL: [
    { value: 'DEBUG',   label: 'Debug',   description: 'All messages' },
    { value: 'INFO',    label: 'Info',    description: 'General information' },
    { value: 'WARNING', label: 'Warning', description: 'Warnings only' },
    { value: 'ERROR',   label: 'Error',   description: 'Errors only' },
  ],
  LOG_FILE_LEVEL: [
    { value: 'DEBUG',   label: 'Debug' },
    { value: 'INFO',    label: 'Info' },
    { value: 'WARNING', label: 'Warning' },
    { value: 'ERROR',   label: 'Error' },
  ],
  TIMEZONE: [
    { value: 'UTC',                  label: 'UTC' },
    { value: 'Europe/London',        label: 'London (GMT)' },
    { value: 'Europe/Berlin',        label: 'Berlin (CET)' },
    { value: 'America/New_York',     label: 'New York (EST)' },
    { value: 'America/Chicago',      label: 'Chicago (CST)' },
    { value: 'America/Los_Angeles',  label: 'Los Angeles (PST)' },
    { value: 'Asia/Tokyo',           label: 'Tokyo (JST)' },
    { value: 'Asia/Shanghai',        label: 'Shanghai (CST)' },
    { value: 'Asia/Dubai',           label: 'Dubai (GST)' },
  ],
}

// ─── Descriptions ──────────────────────────────────────────────────────────────

const settingDescriptions: Record<string, string> = {
  // Telegram
  TELEGRAM_BOT_TOKEN: 'Telegram bot token from @BotFather — required to send and receive messages',
  TELEGRAM_CHANNEL_ID: 'Channels the bot monitors for incoming trading signals',
  TELEGRAM_NOTIFICATION_CHAT_ID: 'Where the bot sends trade confirmations, alerts, and status updates',
  PROCESS_FORWARDED_SIGNALS: 'When enabled, signals forwarded from a monitored VIP channel into any other chat (public groups, private chats) are also detected and executed',
  SIGNAL_FORWARD_ENABLED: 'Post every executed signal to a Telegram channel as a message, and reply to it for every position action (partial close, SL/TP changes, brain actions, close)',
  SIGNAL_FORWARD_CHANNEL_ID: 'The channel where executed signals are posted. The bot must be an admin. All subsequent position actions are sent as replies to the original post.',
  BOT_ALLOWED_USER_IDS: 'Telegram user IDs that can control the bot via commands (/execute, /reject, /pause, etc). Leave empty to allow anyone in the approval channel. Find your user ID by messaging @userinfobot.',
  // Notification filters
  NOTIFY_ENABLED: 'Master switch for the notification channel. Turn this off to silence everything except approval prompts, which always come through because they need your answer to continue.',
  NOTIFY_SIGNAL_RECEIVED: 'A new signal was picked up from one of your monitored channels',
  NOTIFY_SIGNAL_REJECTED: 'A signal was blocked before execution — by the risk manager, news filter, drawdown protection, external validator or the Trading Brain. Usually the noisiest category.',
  NOTIFY_SIGNAL_PARSE_FAILED: 'The AI could not extract a valid signal from a message or chart image. Noisy on chatty channels that post commentary between signals.',
  NOTIFY_BRAIN_DECISIONS: 'The Trading Brain adjusted a signal\'s entry, stop loss or take profit before executing it',
  NOTIFY_TRADE_EXECUTED: 'A trade was successfully placed on your account',
  NOTIFY_TRADE_FAILED: 'An order was rejected by the broker, or the trading platform could not be reached — this is where connection failures show up',
  NOTIFY_ORDER_CANCELLED: 'A pending order was cancelled or expired without ever filling',
  NOTIFY_POSITION_MANAGEMENT: 'Stop loss and take profit moves, partial closes, breakeven moves and trailing stop updates on open positions',
  NOTIFY_RR_MILESTONES: 'A position reached 1:1 or 1:2 risk-to-reward',
  NOTIFY_TRADE_CLOSED: 'A position closed, with its final profit or loss',
  NOTIFY_TRADE_PLANS: 'Trade plans registered, executed, expired, or falling back to a secondary entry zone',
  NOTIFY_APPROVAL_OUTCOMES: 'Approval requests that timed out or that you rejected. The approval prompts themselves are always sent regardless of this setting.',
  NOTIFY_COMMAND_RESPONSES: 'Confirmations and error replies for commands you send the bot yourself',
  NOTIFY_AI_ANALYSIS: 'Periodic market analysis and recommendation changes from the AI',
  NOTIFY_ERRORS: 'Internal errors, API and connection failures, and service-unavailable warnings such as the Trading Brain being unreachable',
  NOTIFY_RISK_ALERTS: 'Drawdown limit breaches and risk-management warnings. Recommended to keep on.',
  NOTIFY_BOT_LIFECYCLE: 'The startup banner when the bot comes online and the notice when it shuts down',
  // Provider
  TRADING_PROVIDER: 'Which trading platform to execute trades on',
  MT5_REST_API_URL: 'MT5 REST API URL — Docker: http://mt5:5001 · Local: http://localhost:5001',
  MT5_SYMBOL_SUFFIX: 'Broker symbol suffix added to all pairs (e.g., .fx → EURUSD.fx; leave empty for standard names)',
  METAAPI_TOKEN: 'MetaAPI cloud authentication token from metaapi.cloud',
  METAAPI_ACCOUNT_ID: 'MetaAPI trading account identifier',
  // Risk
  MAX_RISK_PER_TRADE_PERCENT: 'Maximum account balance to risk on a single trade (recommended: 1–3%)',
  MAX_OPEN_POSITIONS: 'Maximum number of positions that can be open simultaneously',
  RISK_REWARD_RATIO: 'Default risk-to-reward ratio for calculations (e.g., 2.0 = 1:2 R:R)',
  DEFAULT_STOP_LOSS_PIPS: 'Fallback stop loss in pips when not provided in the signal',
  DEFAULT_TAKE_PROFIT_PIPS: 'Fallback take profit in pips when not provided in the signal',
  SPREAD_ADJUSTMENT_MULTIPLIER: 'Multiplier applied to spread when adjusting SL to prevent premature closure',
  ENABLE_EQUITY_PROTECTION: 'Monitor account equity and halt trading if drawdown limits are exceeded',
  DAILY_DRAWDOWN_LIMIT_PERCENT: 'Maximum allowed daily drawdown as a percentage before trading stops',
  OVERALL_DRAWDOWN_LIMIT_PERCENT: 'Maximum cumulative drawdown percentage before trading is halted',
  ENABLE_DRAWDOWN_MONITORING: 'Continuously monitor account drawdown in real-time',
  // Execution
  MIN_LOT_SIZE: 'Minimum allowed lot size — matches broker minimum',
  MAX_LOT_SIZE: 'Maximum allowed lot size per trade',
  SLIPPAGE_PIPS: 'Maximum acceptable slippage in pips during order placement',
  MAX_SIGNAL_AGE_MINUTES: 'Reject signals older than this — prevents executing stale signals after bot restart. Applies to instant signals too',
  ENABLE_INSTANT_EXECUTION: 'When a signal says to enter now ("SELL GOLD NOW 4115"), fill it at market even if price has moved slightly past the entry, instead of waiting for a limit. Never skips approval or the age check',
  INSTANT_EXECUTION_CHANNELS: 'Channels allowed for instant execution — leave empty to allow all monitored channels',
  INSTANT_EXECUTION_KEYWORDS: 'Words that mark an instant entry (e.g., now, instant, market). Matched as whole words next to the entry instruction; negated uses like "not now" are ignored',
  INSTANT_TEMP_SL_PIPS: 'A "SELL GOLD NOW" posted without SL enters one position on a temporary SL: the widest SL the channel used on that symbol in its last 10 signals, never tighter than these pips. The real SL from the follow-up message replaces it',
  INSTANT_FIRST_ENTRY_RISK_SHARE: 'Percent of the signal\'s risk budget the temporary-SL entry uses. When the full signal arrives, its other levels (e.g. "MORE SELL @") get whatever budget is left after re-measuring the first entry against the real SL; if the real SL puts the first entry over the budget, it is partially closed back within it',
  SIGNAL_CONTINUITY_WINDOW_MINUTES: 'A follow-up, repost (deleted and sent again) or edit from the same channel within this window updates the existing signal — SL/TP moved, removed levels cancelled, missing levels placed within the remaining risk — instead of opening a second trade',
  SAME_LEVEL_TOLERANCE_PIPS: 'Orders closer than this count as the same level. A new signal never adds orders at a level where the same channel already has orders, unless all of them are at break-even',
  INSTANT_EXECUTION_MAX_DEVIATION_PIPS: 'How far price may be past the entry (worse side) and still be filled at market for an instant signal. Further than this, the order waits as a limit at the entry',
  INSTANT_ONE_LEG_MAX_TP1_PROGRESS: 'Past the max deviation, one order (the one with the furthest TP) still goes in at market so a fast instant signal is not missed — its lots are scaled down so the money at risk stays the same. Only while price has covered less than this % of the way from the entry to TP1; the other orders wait as limits. 0 = off',
  REQUIRE_MANUAL_APPROVAL: 'Hold signals in the queue — requires /execute before a trade is placed',
  APPROVAL_REQUIRED_CHANNELS: 'Limit Manual Approval to these channels; others execute automatically. Leave empty to require approval for every channel',
  APPROVAL_CHANNEL_ID: 'Where approval request messages are sent (defaults to notification channel if empty)',
  APPROVAL_TIMEOUT_MINUTES: 'Auto-reject queued signals after this many minutes without approval',
  APPROVAL_SEND_IMAGE: 'When enabled, the signal image (if any) is sent to the approval channel before the approve/reject message so you can visually verify the signal',
  REQUIRE_APPROVAL_FOR_IMAGES: 'Force manual approval for any signal containing an image, even when Manual Approval is off',
  REQUIRE_APPROVAL_FOR_ESTIMATED_SIZING: 'When the broker\'s symbol data is unavailable the lot size is computed from an estimated pip value. With this on, such a trade waits in the approval queue (with a warning) instead of being traded blindly. Turn off to trade it automatically',
  ALLOW_HIGH_RISK_OVERRIDE: 'When a signal exceeds your Max Risk Per Trade, don\'t auto-reject it — send it to the approval queue with a high-risk disclaimer so you can accept the extra risk or skip it (lot size is already reduced to the minimum)',
  // Trade Plans
  PLAN_WATCHER_ENABLED: 'Master switch — when off, all plan zone-watching is paused but plans stay in the database and resume automatically when turned back on',
  PLAN_AUTO_EXECUTE: 'Automatically execute the trade when price enters an entry zone — when off, you must click Execute in the Plans page',
  PLAN_EXPIRY_HOURS: 'Hours before a plan expires if the entry zone is never reached',
  PLAN_GAP_RISK_BLOCK: 'Reject plans received while the market is closed or over the weekend to avoid gap-risk trades',
  ENABLE_POSITION_MONITORING: 'Master switch for automatic TP, trailing stop, partial close, and breakeven features',
  POSITION_MONITOR_INTERVAL_SECONDS: 'How often position monitoring checks run in seconds (lower = more responsive)',
  ORDER_CLOSE_GRACE_MISSES: 'Consecutive broker poll cycles with no position data before a running trade is marked closed. Lifecycle API is used first when available — this is only the fallback. Raise this if your broker API has occasional blips.',
  ORDER_CANCEL_GRACE_MISSES: 'Consecutive broker poll cycles with no order data before a pending order is marked cancelled. Lifecycle API is used first when available — this is only the fallback.',
  ORDER_STALE_PENDING_HOURS: 'Hours before an unmatched PENDING trade is automatically cancelled. A trade stays PENDING if the broker never confirmed the fill.',
  // Positions
  ENABLE_AUTO_TAKE_PROFIT: 'Automatically calculate and set take profit when not included in the signal',
  AUTO_TP_CALCULATION_METHOD: 'Method used to calculate the take profit level',
  AUTO_TP_PIPS: 'Distance in pips from entry to place the take profit (Pips method)',
  AUTO_TP_RISK_REWARD: 'Take profit distance as a multiple of the stop loss distance (R:R method)',
  ENABLE_TRAILING_STOP: 'Dynamically move stop loss to follow price as the trade moves in your favour',
  TRAILING_STOP_CALCULATION_METHOD: 'How the trailing stop distance is measured',
  TRAILING_STOP_DISTANCE_PIPS: 'Trailing stop stays this many pips behind the current price',
  TRAILING_STOP_DISTANCE_RR: 'Trailing stop distance as a proportion of the stop loss size',
  TRAILING_ACTIVATION_METHOD: 'When trailing begins: immediately, after profit threshold, or after partial close',
  TRAILING_ACTIVATION_PROFIT_PIPS: 'Start trailing after the trade is this many pips in profit',
  TRAILING_ACTIVATION_PROFIT_RR: 'Start trailing after profit reaches this R:R ratio',
  ENABLE_AUTO_PARTIAL: 'Automatically close part of the position when a profit target is reached',
  AUTO_PARTIAL_CALCULATION_METHOD: 'How the partial close trigger level is measured',
  AUTO_PARTIAL_TRIGGER_PIPS: 'Close partial after this many pips of profit (Pips method)',
  AUTO_PARTIAL_TRIGGER_RR: 'Close partial after profit reaches this R:R ratio (R:R method)',
  AUTO_PARTIAL_CLOSE_PERCENT: 'Percentage of the open position to close as partial (e.g., 50 = half)',
  ENABLE_RUNNER_SPLIT: 'Every signal is split: one part goes to the channel\'s TPs as usual, the other part is placed without a take profit to catch the rest of the move. The runner keeps the signal\'s SL and is closed by the SL or by the channel\'s messages (close, break-even, SL moves)',
  RUNNER_SHARE_PERCENT: 'Percent of the signal\'s lots placed without a take profit (50 = half). Signals too small to split keep all lots on the TPs',
  ENABLE_BREAKEVEN_MOVE: 'Move stop loss to the entry price once the trade is sufficiently profitable',
  BREAKEVEN_TRIGGER_METHOD: 'What event triggers the breakeven move',
  BREAKEVEN_TRIGGER_PIPS: 'Move to breakeven after this many pips of profit (Profit Pips method)',
  BREAKEVEN_BUFFER_PIPS: 'Extra pips added beyond the entry price for the breakeven level (cushion)',
  BREAKEVEN_MIN_SIBLING_TP_HITS: 'Number of sibling TPs that must hit before triggering breakeven (for multi-TP signals)',
  // AI — Providers
  PRIMARY_AI_PROVIDER: 'Main AI provider for signal extraction and market analysis',
  FALLBACK_AI_PROVIDERS: 'Backup providers tried in order if the primary fails (comma-separated)',
  OPENAI_API_KEY: 'OpenAI API key from platform.openai.com',
  OPENAI_MODEL: 'OpenAI model for signal text analysis (e.g., gpt-4o-mini)',
  OPENAI_VISION_MODEL: 'OpenAI model used for chart image analysis — gpt-4o-mini is cheapest with vision support',
  GEMINI_API_KEY: 'Google Gemini API key — free tier available at aistudio.google.com',
  GEMINI_MODEL: 'Gemini model for signal text analysis (e.g., gemini-2.0-flash)',
  GEMINI_VISION_MODEL: 'Gemini model for chart image analysis — gemini-2.0-flash is ~10× cheaper than GPT-4o-mini',
  DEEPSEEK_API_KEY: 'DeepSeek API key from platform.deepseek.com',
  DEEPSEEK_API_URL: 'DeepSeek API endpoint URL',
  DEEPSEEK_MODEL: 'DeepSeek text model for signal analysis (e.g., deepseek-v4-flash)',
  DEEPSEEK_VISION_MODEL: 'DeepSeek vision model for chart image analysis (e.g., deepseek-vl2)',
  provider: 'AI provider used to read and interpret trading chart images — must support vision/multimodal input',
  PERPLEXITY_API_KEY: 'Perplexity API key from perplexity.ai/settings/api',
  PERPLEXITY_BASE_URL: 'Perplexity API base URL',
  PERPLEXITY_MODEL: 'Perplexity model for signal text analysis (e.g., sonar-pro)',
  PERPLEXITY_VISION_MODEL: 'Perplexity model used for chart image analysis',
  ENABLE_AI_VISION: 'Master switch for AI-powered chart image analysis — when disabled, signals are extracted via text pattern matching only',
  // Vision Anti-Hallucination Filters
  VISION_CAPTION_PREFILTER_ENABLED: 'Skip the vision API call entirely if the message caption contains trade result keywords (e.g. "in profit", "closed") — prevents false signals and saves API cost',
  VISION_CAPTION_BLOCK_KEYWORDS: 'Comma-separated keywords that mark an image as non-signal — if any keyword is found in the caption the vision API is skipped',
  VISION_CONFIDENCE_FILTER_ENABLED: 'Reject vision signals where the AI rates its own confidence below the minimum threshold — reduces hallucinated signals',
  VISION_MIN_CONFIDENCE: 'Minimum AI self-confidence score (0.0–1.0) required to accept a vision-extracted signal — 0.75 is a good default',
  VISION_TWO_STEP_CLASSIFY_ENABLED: 'Use a separate API call to classify the image type before extraction — more accurate but doubles API calls per image',
  VISION_PRICE_SANITY_CHECK_ENABLED: 'Reject signals with entry/SL/TP prices outside realistic ranges for that instrument (e.g. EURUSD must be 0.5–3.0)',
  VISION_PRICE_RANGES: 'Per-symbol [min, max] price ranges for sanity validation — JSON object. Example: {"XAUUSD":[1000,5000],"EURUSD":[0.5,3.0]}',
  VISION_SL_DISTANCE_CHECK_ENABLED: 'Reject signals where the Stop Loss is unrealistically far from the entry price — catches hallucinated SL values',
  VISION_MAX_SL_DISTANCE_PERCENT: 'Maximum allowed distance between entry and SL as a % of entry price — signals with a wider SL are discarded',
  VISION_SYMBOL_WHITELIST_ENABLED: 'Only accept signals for symbols in the allowed list — off by default (accepts any symbol the AI identifies)',
  VISION_ALLOWED_SYMBOLS: 'Comma-separated list of trading symbols to accept when whitelist is enabled (e.g. XAUUSD,EURUSD,GBPUSD)',
  VISION_IMAGE_DIMENSION_FILTER_ENABLED: 'Skip vision analysis for decorative graphics (channel dividers, banners, tiny stickers) based on image dimensions — prevents hallucinated signals from non-chart images',
  VISION_MAX_IMAGE_ASPECT_RATIO: 'Images wider/taller than this width:height ratio are treated as decorative and skipped (typical chart screenshots are below 2.5)',
  VISION_MIN_IMAGE_HEIGHT: 'Images shorter than this many pixels are treated as decorative and skipped',
  OPENROUTER_API_KEY: 'OpenRouter API key from openrouter.ai/keys — routes to hundreds of models',
  OPENROUTER_BASE_URL: 'OpenRouter API base URL (default: https://openrouter.ai/api/v1)',
  OPENROUTER_MODEL: 'OpenRouter model for signal text analysis (e.g., qwen/qwen2.5-vl-72b-instruct)',
  OPENROUTER_VISION_MODEL: 'OpenRouter model for chart image analysis — any vision-capable model works',
  MINIMAX_API_KEY: 'MiniMax API key from platform.minimaxi.com — OpenAI-compatible endpoint',
  MINIMAX_BASE_URL: 'MiniMax API base URL (default: https://api.minimax.io/v1)',
  MINIMAX_MODEL: 'MiniMax model for signal text analysis (e.g., MiniMax-M2.7)',
  MINIMAX_VISION_MODEL: 'MiniMax model for chart image analysis (e.g., MiniMax-VL-01)',
  QWEN_API_KEY: 'Qwen API key from Alibaba DashScope — dashscope-intl.aliyuncs.com',
  QWEN_BASE_URL: 'Qwen API base URL (default: https://dashscope-intl.aliyuncs.com/compatible-mode/v1)',
  QWEN_MODEL: 'Qwen model for signal text analysis (e.g., qwen-plus, qwen-max)',
  QWEN_VISION_MODEL: 'Qwen model for chart image analysis (e.g., qwen-vl-max)',
  OLLAMA_URL: 'Ollama local server URL (default: http://localhost:11434)',
  OLLAMA_MODEL: 'Ollama model to load for signal analysis (e.g., llama2, mistral)',
  // AI — Brain
  ENABLE_TRADING_BRAIN: 'AI Trading Brain — a persistent AI session that reviews every signal and monitors open positions in real-time',
  BRAIN_BASE_URL: 'Custom OpenAI-compatible endpoint for the brain (leave empty to use the primary AI provider)',
  BRAIN_API_KEY: 'API key for the brain endpoint (leave empty to reuse the primary provider key)',
  BRAIN_MODEL: 'Model the brain uses (leave empty to use the active provider\'s model)',
  BRAIN_TEMPERATURE: 'Response randomness — lower values produce more consistent analysis (0.0–1.0)',
  BRAIN_MAX_HISTORY_MESSAGES: 'Maximum conversation turns kept in brain memory before the oldest are trimmed',
  BRAIN_POSITION_REVIEW_INTERVAL: 'How often (in seconds) the brain re-evaluates each open position',
  BRAIN_ACTION_REQUIRE_APPROVAL: 'Send a Telegram approval message before the brain executes any position action — tap Approve or Reject directly in chat',
  BRAIN_ACTION_APPROVAL_TYPES: 'Which brain actions require approval — comma-separated: CLOSE, PARTIAL_CLOSE, MODIFY_SL, MODIFY_TP',
  BRAIN_UNAVAILABLE_ACTION: 'What happens to signals when the brain is down or unconfigured: APPROVE = trade anyway (default), REJECT = block all signals, APPROVAL = send every signal to the manual approval queue, PIPELINE = skip the brain and use the rest of your pipeline exactly as configured',
  BRAIN_SEND_IMAGES: 'Send the signal\'s chart/screenshot image to the brain along with the text, so it can see what the channel posted, not just read a summary',
  REQUIRE_RISK_VALIDATION: 'When ON (default), the brain can REJECT a signal and a failed risk check blocks execution. When OFF, a signal that was extracted successfully (symbol, direction, SL) is never blocked by the brain\'s rejection or the risk assessment — it executes. The brain can still MODIFY entry/SL/TP/lot size. Drawdown protection stays active either way.',
  // AI — Analysis
  ENABLE_AI_MARKET_ANALYSIS: 'Enable real-time AI market condition monitoring for open positions',
  AI_ANALYSIS_CHECK_INTERVAL: 'How often (seconds) to run AI market analysis',
  ENABLE_AI_BREAKEVEN_TRIGGERS: 'AI detects adverse market conditions and triggers early breakeven moves',
  ENABLE_AI_TP_ADJUSTMENT: 'AI recommends take profit adjustments based on live market strength',
  ENABLE_AI_POSITION_REDUCTION: 'AI recommends partial closes when market conditions turn unfavourable',
  AI_ANALYSIS_CONFIDENCE_THRESHOLD: 'Minimum AI confidence score required before acting on a recommendation (0.0–1.0)',
  AI_AUTO_VERIFICATION_ENABLED: 'AI automatically verifies and validates trades displayed in the dashboard',
  ENABLE_LLM_MARKET_ANALYSIS: 'Enable LLM-powered market analysis (uses AI provider credits)',
  LLM_MARKET_ANALYSIS_INTERVAL: 'Minimum seconds between LLM market-analysis calls per symbol',
  // System — Validator
  ENABLE_SIGNAL_VALIDATOR: 'Send signals to an external API for validation before executing trades',
  SIGNAL_VALIDATOR_URL: 'URL of the signal validator service',
  SIGNAL_VALIDATOR_API_KEY: 'Authentication key sent as X-API-Key header to the validator service',
  SIGNAL_VALIDATOR_TIMEOUT_SECONDS: 'Seconds to wait for validator response before proceeding (fail-open policy)',
  SIGNAL_VALIDATOR_EXECUTION_POLICY: 'Which validator verdicts are allowed to trade',
  // System — News
  NEWS_ENABLE_FILTER: 'Block new trade entries around scheduled high-impact economic news events',
  NEWS_MINUTES_BEFORE: 'Stop opening new trades this many minutes before a news event',
  NEWS_MINUTES_AFTER: 'Resume trading this many minutes after a news event ends',
  NEWS_IMPORTANT_IMPACTS: 'News impact levels that block trading — select one or more (High, Medium, Low, Holiday)',
  NEWS_TARGET_CURRENCIES: 'Only block trades when news affects these currencies — select the currencies you trade (ALL = any currency)',
  NEWS_ENABLE_NOTIFICATIONS: 'Send Telegram notifications before upcoming news events',
  NEWS_NOTIFICATION_MINUTES_BEFORE: 'Send the notification this many minutes before the news event',
  NEWS_VERBOSE_LOGGING: 'Log detailed news filter activity for debugging',
  NEWS_API_URL: 'Economic calendar API endpoint — fetched weekly every Monday',
  NEWS_POST_ENABLED: 'Post upcoming news events to a Telegram channel of your choice. Has its own impact and currency selection — it does not change which news blocks trading',
  NEWS_POST_CHANNEL_ID: 'The channel the news posts go to. The bot (or your Telegram account) must be allowed to post there',
  NEWS_POST_IMPACTS: 'Impact levels that are posted to the channel — select one or more',
  NEWS_POST_CURRENCIES: 'Only news for these currencies is posted to the channel (ALL = events that affect every currency)',
  NEWS_POST_MINUTES_BEFORE: 'Post this many minutes before the event',
  NEWS_UPDATE_INTERVAL_HOURS: 'Hours between automatic refreshes of the economic news calendar from the API',
  // System — General
  LOG_LEVEL: 'Console log verbosity: DEBUG shows everything, ERROR shows only failures',
  LOG_FILE_LEVEL: 'Log file verbosity (defaults to LOG_LEVEL if empty)',
  LOG_FILE_DEBUG: 'Force DEBUG level in log files regardless of LOG_FILE_LEVEL',
  DRY_RUN: 'Simulation mode — signals are processed and logged but no real trades are placed',
  TIMEZONE: 'Timezone used for timestamps and scheduling throughout the bot',
  SKIP_METAAPI: 'Turns ALL trading off, on MetaAPI and MT5 REST alike: signals are detected and recorded as dry-run trades, nothing is sent to the broker. Needs a bot restart to take effect',
  POSITION_MONITOR_STARTUP_DELAY_SECONDS: 'Seconds to wait after bot starts before position monitor begins checking (0 = immediate)',
  METAAPI_USE_STREAMING: 'MetaAPI: use live streaming websocket rather than polling REST API',
  COPY_MASTER_MODE: 'Wait for the master account to have a RUNNING position before entering (no limit orders placed)',
  TRAILING_STOP_MIN_STEP_PIPS: 'Only move trailing stop loss when price improves by at least this many pips (reduces broker requests)',
  TRAILING_STOP_MIN_INTERVAL_SECONDS: 'Minimum seconds between trailing SL modifications per trade (prevents throttling)',
  ALLOW_MULTI_SIGNAL_POSTS: 'A text post that contains several independent trades (each with its own entry and stop loss) is split by the AI into one signal per trade. Each trade is risk-checked and approved on its own. Breakout plans and single setups with several targets are never split',
  CATCHUP_ENABLED: 'After downtime (restart, crash, lost updates) the bot checks what was posted while it was away: fresh messages are processed, older signals are only reported as expired (never traded), and missed commands come with Apply / Skip buttons',
  CATCHUP_MAX_MESSAGES: 'Per channel, how many of the newest missed messages the catch-up checks',
  CATCHUP_INTERVAL_MINUTES: 'Minutes between periodic checks for Telegram updates that were silently lost while connected (0 = only check at startup)',
  MESSAGE_PROCESSING_CONCURRENCY: 'Max Telegram messages processed in parallel during bursts (higher = faster under spam, more AI API load)',
}

// ─── Label map ────────────────────────────────────────────────────────────────

const SETTING_LABELS: Record<string, string> = {
  // Telegram
  TELEGRAM_BOT_TOKEN: 'Bot Token',
  TELEGRAM_CHANNEL_ID: 'Signal Channels',
  TELEGRAM_NOTIFICATION_CHAT_ID: 'Notification Target',
  SIGNAL_FORWARD_ENABLED: 'Enable Signal Forwarding',
  SIGNAL_FORWARD_CHANNEL_ID: 'Signal Forward Channel',
  BOT_ALLOWED_USER_IDS: 'Allowed Users',
  // Notification filters
  NOTIFY_ENABLED: 'Enable Notifications',
  NOTIFY_SIGNAL_RECEIVED: 'New Signal Detected',
  NOTIFY_SIGNAL_REJECTED: 'Signal Rejected / Filtered',
  NOTIFY_SIGNAL_PARSE_FAILED: 'Signal Extraction Failed',
  NOTIFY_BRAIN_DECISIONS: 'Brain Signal Adjustments',
  NOTIFY_TRADE_EXECUTED: 'Trade Opened',
  NOTIFY_TRADE_FAILED: 'Trade Execution Failed',
  NOTIFY_ORDER_CANCELLED: 'Pending Order Cancelled',
  NOTIFY_POSITION_MANAGEMENT: 'SL / TP & Partial Closes',
  NOTIFY_RR_MILESTONES: 'R:R Milestones',
  NOTIFY_TRADE_CLOSED: 'Trade Closed',
  NOTIFY_TRADE_PLANS: 'Trade Plan Updates',
  NOTIFY_APPROVAL_OUTCOMES: 'Approval Outcomes',
  NOTIFY_COMMAND_RESPONSES: 'Command Confirmations',
  NOTIFY_AI_ANALYSIS: 'AI Market Analysis',
  NOTIFY_ERRORS: 'Errors & Connection Failures',
  NOTIFY_RISK_ALERTS: 'Risk & Drawdown Alerts',
  NOTIFY_BOT_LIFECYCLE: 'Bot Started / Stopped',
  // Provider
  TRADING_PROVIDER: 'Trading Platform',
  MT5_REST_API_URL: 'MT5 REST API URL',
  MT5_SYMBOL_SUFFIX: 'Symbol Suffix',
  MT5_REST_API_KEY: 'MT5 API Key',
  METAAPI_TOKEN: 'MetaAPI Token',
  METAAPI_ACCOUNT_ID: 'MetaAPI Account ID',
  METAAPI_USE_STREAMING: 'MetaAPI Streaming Connection',
  // Risk
  MAX_RISK_PER_TRADE_PERCENT: 'Max Risk Per Trade (%)',
  MAX_OPEN_POSITIONS: 'Max Open Positions',
  RISK_REWARD_RATIO: 'Risk/Reward Ratio',
  DEFAULT_STOP_LOSS_PIPS: 'Default Stop Loss (pips)',
  DEFAULT_TAKE_PROFIT_PIPS: 'Default Take Profit (pips)',
  SPREAD_ADJUSTMENT_MULTIPLIER: 'Spread Adjustment Multiplier',
  ENABLE_EQUITY_PROTECTION: 'Enable Equity Protection',
  DAILY_DRAWDOWN_LIMIT_PERCENT: 'Daily Drawdown Limit (%)',
  OVERALL_DRAWDOWN_LIMIT_PERCENT: 'Overall Drawdown Limit (%)',
  ENABLE_DRAWDOWN_MONITORING: 'Real-time Drawdown Monitoring',
  // Execution
  MIN_LOT_SIZE: 'Min Lot Size',
  MAX_LOT_SIZE: 'Max Lot Size',
  SLIPPAGE_PIPS: 'Slippage (pips)',
  MAX_SIGNAL_AGE_MINUTES: 'Max Signal Age (min)',
  ENABLE_INSTANT_EXECUTION: 'Instant Execution',
  INSTANT_EXECUTION_CHANNELS: 'Instant Execution Channels',
  INSTANT_EXECUTION_KEYWORDS: 'Instant Execution Keywords',
  INSTANT_EXECUTION_MAX_DEVIATION_PIPS: 'Instant Max Deviation (pips)',
  INSTANT_ONE_LEG_MAX_TP1_PROGRESS: 'Instant One-Leg Chase (% to TP1)',
  INSTANT_TEMP_SL_PIPS: 'Temporary SL (pips)',
  INSTANT_FIRST_ENTRY_RISK_SHARE: 'First Entry Risk Share (%)',
  SIGNAL_CONTINUITY_WINDOW_MINUTES: 'Same-Signal Window (min)',
  SAME_LEVEL_TOLERANCE_PIPS: 'Same-Level Tolerance (pips)',
  COPY_MASTER_MODE: 'Copy Master Mode',
  REQUIRE_MANUAL_APPROVAL: 'Require Manual Approval',
  APPROVAL_REQUIRED_CHANNELS: 'Channels Requiring Approval',
  APPROVAL_CHANNEL_ID: 'Approval Notification Channel',
  APPROVAL_TIMEOUT_MINUTES: 'Approval Timeout (min)',
  APPROVAL_SEND_IMAGE: 'Send Image with Approval',
  REQUIRE_APPROVAL_FOR_IMAGES: 'Require Approval for Images',
  ALLOW_HIGH_RISK_OVERRIDE: 'Allow High-Risk Override',
  REQUIRE_APPROVAL_FOR_ESTIMATED_SIZING: 'Approve Estimated Lot Sizes',
  // Trade Plans
  PLAN_WATCHER_ENABLED: 'Plan Watcher',
  PLAN_AUTO_EXECUTE: 'Auto-Execute Zones',
  PLAN_EXPIRY_HOURS: 'Plan Expiry (hours)',
  PLAN_GAP_RISK_BLOCK: 'Block Plans on Market Close',
  ENABLE_POSITION_MONITORING: 'Position Monitoring',
  POSITION_MONITOR_INTERVAL_SECONDS: 'Monitor Interval (sec)',
  ORDER_CLOSE_GRACE_MISSES: 'Close Grace Misses',
  ORDER_CANCEL_GRACE_MISSES: 'Cancel Grace Misses',
  ORDER_STALE_PENDING_HOURS: 'Stale Pending Timeout (hrs)',
  // Positions
  ENABLE_AUTO_TAKE_PROFIT: 'Auto Take Profit',
  AUTO_TP_CALCULATION_METHOD: 'Calculation Method',
  AUTO_TP_PIPS: 'TP Distance (pips)',
  AUTO_TP_RISK_REWARD: 'TP Risk/Reward',
  ENABLE_TRAILING_STOP: 'Trailing Stop',
  TRAILING_STOP_CALCULATION_METHOD: 'Trailing Method',
  TRAILING_STOP_DISTANCE_PIPS: 'Trailing Distance (pips)',
  TRAILING_STOP_DISTANCE_RR: 'Trailing Distance (R:R)',
  TRAILING_ACTIVATION_METHOD: 'Activation Trigger',
  TRAILING_ACTIVATION_PROFIT_PIPS: 'Activation After (pips)',
  TRAILING_ACTIVATION_PROFIT_RR: 'Activation After (R:R)',
  TRAILING_STOP_MIN_STEP_PIPS: 'Min Step (pips)',
  TRAILING_STOP_MIN_INTERVAL_SECONDS: 'Min Update Gap (sec)',
  ENABLE_AUTO_PARTIAL: 'Auto Partial Close',
  AUTO_PARTIAL_CALCULATION_METHOD: 'Partial Method',
  AUTO_PARTIAL_TRIGGER_PIPS: 'Trigger After (pips)',
  AUTO_PARTIAL_TRIGGER_RR: 'Trigger After (R:R)',
  AUTO_PARTIAL_CLOSE_PERCENT: 'Close Percentage (%)',
  ENABLE_RUNNER_SPLIT: 'Runner Without TP',
  RUNNER_SHARE_PERCENT: 'Runner Share (%)',
  ENABLE_BREAKEVEN_MOVE: 'Move to Breakeven',
  BREAKEVEN_TRIGGER_METHOD: 'Trigger Method',
  BREAKEVEN_TRIGGER_PIPS: 'Trigger After (pips)',
  BREAKEVEN_BUFFER_PIPS: 'Buffer Pips',
  BREAKEVEN_MIN_SIBLING_TP_HITS: 'Min Sibling TP Hits',
  // AI
  PRIMARY_AI_PROVIDER: 'Primary Provider',
  FALLBACK_AI_PROVIDERS: 'Fallback Providers',
  OPENAI_API_KEY: 'OpenAI API Key',
  OPENAI_MODEL: 'OpenAI Model',
  OPENAI_VISION_MODEL: 'OpenAI Vision Model',
  GEMINI_API_KEY: 'Gemini API Key',
  GEMINI_MODEL: 'Gemini Model',
  GEMINI_VISION_MODEL: 'Gemini Vision Model',
  DEEPSEEK_API_KEY: 'DeepSeek API Key',
  DEEPSEEK_API_URL: 'DeepSeek API URL',
  DEEPSEEK_MODEL: 'DeepSeek Model',
  DEEPSEEK_VISION_MODEL: 'DeepSeek Vision Model',
  provider: 'Vision AI Provider',
  PERPLEXITY_API_KEY: 'Perplexity API Key',
  PERPLEXITY_BASE_URL: 'Perplexity Base URL',
  PERPLEXITY_MODEL: 'Perplexity Model',
  PERPLEXITY_VISION_MODEL: 'Perplexity Vision Model',
  OPENROUTER_API_KEY: 'OpenRouter API Key',
  OPENROUTER_BASE_URL: 'OpenRouter Base URL',
  OPENROUTER_MODEL: 'OpenRouter Model',
  OPENROUTER_VISION_MODEL: 'OpenRouter Vision Model',
  MINIMAX_API_KEY: 'MiniMax API Key',
  MINIMAX_BASE_URL: 'MiniMax Base URL',
  MINIMAX_MODEL: 'MiniMax Model',
  MINIMAX_VISION_MODEL: 'MiniMax Vision Model',
  QWEN_API_KEY: 'Qwen API Key',
  QWEN_BASE_URL: 'Qwen Base URL',
  QWEN_MODEL: 'Qwen Model',
  QWEN_VISION_MODEL: 'Qwen Vision Model',
  OLLAMA_URL: 'Ollama URL',
  OLLAMA_MODEL: 'Ollama Model',
  ENABLE_TRADING_BRAIN: 'Trading Brain',
  BRAIN_BASE_URL: 'Brain Endpoint URL',
  BRAIN_API_KEY: 'Brain API Key',
  BRAIN_MODEL: 'Brain Model',
  BRAIN_TEMPERATURE: 'Temperature',
  BRAIN_MAX_HISTORY_MESSAGES: 'Max History Messages',
  BRAIN_POSITION_REVIEW_INTERVAL: 'Position Review Interval (sec)',
  BRAIN_ACTION_REQUIRE_APPROVAL: 'Action Approval',
  BRAIN_ACTION_APPROVAL_TYPES: 'Actions Requiring Approval',
  BRAIN_UNAVAILABLE_ACTION: 'If Brain Unavailable',
  BRAIN_SEND_IMAGES: 'Send Images to Brain',
  REQUIRE_RISK_VALIDATION: 'Require Risk Validation',
  ENABLE_AI_MARKET_ANALYSIS: 'AI Market Analysis',
  AI_ANALYSIS_CHECK_INTERVAL: 'Check Interval (sec)',
  ENABLE_AI_BREAKEVEN_TRIGGERS: 'AI Breakeven Triggers',
  ENABLE_AI_TP_ADJUSTMENT: 'AI TP Adjustment',
  ENABLE_AI_POSITION_REDUCTION: 'AI Position Reduction',
  AI_ANALYSIS_CONFIDENCE_THRESHOLD: 'Confidence Threshold',
  AI_AUTO_VERIFICATION_ENABLED: 'AI Auto Verification',
  ENABLE_LLM_MARKET_ANALYSIS: 'Enable LLM Market Analysis',
  LLM_MARKET_ANALYSIS_INTERVAL: 'Analysis Interval (sec)',
  ENABLE_AI_VISION: 'AI Vision',
  // Vision Filters
  VISION_CAPTION_PREFILTER_ENABLED: 'Caption Pre-filter',
  VISION_CAPTION_BLOCK_KEYWORDS: 'Block Keywords',
  VISION_CONFIDENCE_FILTER_ENABLED: 'Confidence Filter',
  VISION_MIN_CONFIDENCE: 'Min Confidence',
  VISION_TWO_STEP_CLASSIFY_ENABLED: 'Two-Step Classify',
  VISION_PRICE_SANITY_CHECK_ENABLED: 'Price Sanity Check',
  VISION_PRICE_RANGES: 'Price Ranges',
  VISION_SL_DISTANCE_CHECK_ENABLED: 'SL Distance Check',
  VISION_MAX_SL_DISTANCE_PERCENT: 'Max SL Distance (%)',
  VISION_SYMBOL_WHITELIST_ENABLED: 'Symbol Whitelist',
  VISION_ALLOWED_SYMBOLS: 'Allowed Symbols',
  VISION_IMAGE_DIMENSION_FILTER_ENABLED: 'Dimension Filter',
  VISION_MAX_IMAGE_ASPECT_RATIO: 'Max Aspect Ratio',
  VISION_MIN_IMAGE_HEIGHT: 'Min Image Height (px)',
  // System
  ENABLE_SIGNAL_VALIDATOR: 'Signal Validator',
  SIGNAL_VALIDATOR_URL: 'Validator URL',
  SIGNAL_VALIDATOR_API_KEY: 'Validator API Key',
  SIGNAL_VALIDATOR_TIMEOUT_SECONDS: 'Validator Timeout (sec)',
  SIGNAL_VALIDATOR_EXECUTION_POLICY: 'Execution Policy',
  NEWS_ENABLE_FILTER: 'News Filter',
  NEWS_MINUTES_BEFORE: 'Block Before News (min)',
  NEWS_MINUTES_AFTER: 'Block After News (min)',
  NEWS_IMPORTANT_IMPACTS: 'Impact Levels',
  NEWS_TARGET_CURRENCIES: 'Target Currencies',
  NEWS_ENABLE_NOTIFICATIONS: 'News Notifications',
  NEWS_NOTIFICATION_MINUTES_BEFORE: 'Notify Before (min)',
  NEWS_VERBOSE_LOGGING: 'Verbose News Logging',
  NEWS_API_URL: 'News API URL',
  NEWS_POST_ENABLED: 'News Channel Posts',
  NEWS_POST_CHANNEL_ID: 'News Channel',
  NEWS_POST_IMPACTS: 'Posted Impact Levels',
  NEWS_POST_CURRENCIES: 'Posted Currencies',
  NEWS_POST_MINUTES_BEFORE: 'Post Before (min)',
  LOG_LEVEL: 'Console Log Level',
  LOG_FILE_LEVEL: 'File Log Level',
  LOG_FILE_DEBUG: 'Force File Debug',
  DRY_RUN: 'Dry Run Mode',
  TIMEZONE: 'Timezone',
  SKIP_METAAPI: 'Disable Trading (signal detection only)',
  ALLOW_MULTI_SIGNAL_POSTS: 'Split Multi-Trade Posts',
  CATCHUP_ENABLED: 'Catch Up After Downtime',
  CATCHUP_MAX_MESSAGES: 'Catch-Up Max Messages',
  CATCHUP_INTERVAL_MINUTES: 'Catch-Up Check Interval (min)',
  NEWS_UPDATE_INTERVAL_HOURS: 'News Refresh Interval (hours)',
  POSITION_MONITOR_STARTUP_DELAY_SECONDS: 'Position Monitor Startup Delay (sec)',
  MESSAGE_PROCESSING_CONCURRENCY: 'Message Processing Concurrency',
}

// ─── Component ─────────────────────────────────────────────────────────────────

export default function ConfigPage() {
  const { toast } = useToast()
  const [settings, setSettings] = useState<Record<string, any>>({})
  const [originalSettings, setOriginalSettings] = useState<Record<string, any>>({})
  const [pendingChanges, setPendingChanges] = useState<Record<string, any>>({})
  const [allSettingsList, setAllSettingsList] = useState<Setting[]>([])
  const [secretKeys, setSecretKeys] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(true)
  const [savingAll, setSavingAll] = useState(false)
  const [reloading, setReloading] = useState(false)
  const [savedButNotReloaded, setSavedButNotReloaded] = useState(false)
  const [activeTab, setActiveTab] = useState('telegram')
  const [searchQuery, setSearchQuery] = useState('')
  const [showSecrets, setShowSecrets] = useState(false)
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [showConfirmDialog, setShowConfirmDialog] = useState(false)
  const [newSetting, setNewSetting] = useState({
    key: '', value: '', valueType: 'STRING', category: 'GENERAL', description: '', isSecret: false,
  })

  const [sharedChannels, setSharedChannels] = useState<any>(null)
  const [channelsLoading, setChannelsLoading] = useState(false)
  // Discord channels selected on the Discord page: offered in the per-channel pickers
  const [discordChannels, setDiscordChannels] = useState<ExtraChannel[]>([])
  const [aiConfigDirty, setAiConfigDirty] = useState(false)
  const aiConfigRef = useRef<AIConfigPanelRef>(null)

  const hasPendingChanges = Object.keys(pendingChanges).length > 0 || aiConfigDirty

  // ─── Tab schema ─────────────────────────────────────────────────────────────

  const TAB_SCHEMA = useMemo<TabDef[]>(() => [
    {
      id: 'telegram',
      label: 'Telegram',
      icon: <MessagesSquare className="h-4 w-4" />,
      description: 'Signal channels and notification targets',
      subSections: [
        {
          id: 'account',
          title: 'Telegram Account (optional)',
          description: 'Empty fields are normal when these are set in the server\'s .env file: the bot uses those values. Fill them in only to set or override them here (API ID and hash from my.telegram.org). With neither, the bot runs without Telegram. Changing them for a logged-in account needs a bot restart',
          fields: [{ key: 'TELEGRAM_API_ID' }, { key: 'TELEGRAM_API_HASH' }, { key: 'TELEGRAM_PHONE' }],
        },
        {
          id: 'bot',
          title: 'Bot Credentials',
          description: 'Telegram bot token from @BotFather',
          fields: [{ key: 'TELEGRAM_BOT_TOKEN' }],
        },
        {
          id: 'channels',
          title: 'Signal Channels',
          description: 'Channels the bot monitors for incoming trading signals',
          fields: [
            { key: 'TELEGRAM_CHANNEL_ID' },
            { key: 'PROCESS_FORWARDED_SIGNALS' },
          ],
        },
        {
          id: 'signal-forwarding',
          title: 'Signal Forwarding',
          description: 'Post executed signals to a channel and reply with every position action',
          masterToggle: 'SIGNAL_FORWARD_ENABLED',
          fields: [
            { key: 'SIGNAL_FORWARD_ENABLED' },
            { key: 'SIGNAL_FORWARD_CHANNEL_ID', showWhen: (s) => !!s['SIGNAL_FORWARD_ENABLED'] },
          ],
        },
        {
          id: 'bot-access',
          title: 'Command Access',
          description: 'Control who can send commands to the bot — /execute, /reject, /pause, /balance, etc.',
          fields: [{ key: 'BOT_ALLOWED_USER_IDS' }],
        },
      ],
    },
    {
      id: 'notifications',
      label: 'Notifications',
      icon: <Bell className="h-4 w-4" />,
      description: 'Choose exactly which notifications reach your notification channel',
      twoCol: true,
      subSections: [
        {
          id: 'notify-channel',
          title: 'Notification Channel',
          description: 'The chat that receives everything below. Turn the master switch off to go quiet without losing your per-category choices.',
          masterToggle: 'NOTIFY_ENABLED',
          fields: [{ key: 'TELEGRAM_NOTIFICATION_CHAT_ID' }],
        },
        {
          id: 'notify-signals',
          title: 'Signals',
          description: 'Messages about incoming signals, before any trade is placed',
          showWhen: (s) => notifyMasterOn(s),
          fields: [
            { key: 'NOTIFY_SIGNAL_RECEIVED' },
            { key: 'NOTIFY_SIGNAL_REJECTED' },
            { key: 'NOTIFY_SIGNAL_PARSE_FAILED' },
            { key: 'NOTIFY_BRAIN_DECISIONS' },
          ],
        },
        {
          id: 'notify-execution',
          title: 'Trade Execution',
          description: 'Orders being placed, failing, or expiring unfilled',
          showWhen: (s) => notifyMasterOn(s),
          fields: [
            { key: 'NOTIFY_TRADE_EXECUTED' },
            { key: 'NOTIFY_TRADE_FAILED' },
            { key: 'NOTIFY_ORDER_CANCELLED' },
          ],
        },
        {
          id: 'notify-positions',
          title: 'Open Positions',
          description: 'Everything that happens to a trade after it is live',
          showWhen: (s) => notifyMasterOn(s),
          fields: [
            { key: 'NOTIFY_POSITION_MANAGEMENT' },
            { key: 'NOTIFY_RR_MILESTONES' },
            { key: 'NOTIFY_TRADE_CLOSED' },
          ],
        },
        {
          id: 'notify-plans',
          title: 'Plans & Approvals',
          description: 'Trade plan watching and the outcome of approval requests',
          showWhen: (s) => notifyMasterOn(s),
          fields: [
            { key: 'NOTIFY_TRADE_PLANS' },
            { key: 'NOTIFY_APPROVAL_OUTCOMES' },
          ],
        },
        {
          id: 'notify-system',
          title: 'System & Errors',
          description: 'Connection failures, risk alerts, command replies and other bot chatter',
          showWhen: (s) => notifyMasterOn(s),
          fields: [
            { key: 'NOTIFY_ERRORS' },
            { key: 'NOTIFY_RISK_ALERTS' },
            { key: 'NOTIFY_COMMAND_RESPONSES' },
            { key: 'NOTIFY_AI_ANALYSIS' },
            { key: 'NEWS_ENABLE_NOTIFICATIONS' },
            { key: 'NOTIFY_BOT_LIFECYCLE' },
          ],
        },
      ],
    },
    {
      id: 'provider',
      label: 'Provider',
      icon: <Server className="h-4 w-4" />,
      description: 'Trading platform and broker connection',
      subSections: [
        {
          id: 'platform',
          title: 'Trading Platform',
          description: 'Select which execution platform to connect to',
          fields: [{ key: 'TRADING_PROVIDER' }],
        },
        {
          id: 'mt5',
          title: 'MT5 REST API',
          description: 'Self-hosted MT5 REST server connection — recommended for low-latency execution',
          showWhen: (s) => !s['TRADING_PROVIDER'] || s['TRADING_PROVIDER'] === 'mt5rest',
          fields: [
            { key: 'MT5_REST_API_URL' },
            { key: 'MT5_REST_API_KEY' },
            { key: 'MT5_SYMBOL_SUFFIX' },
          ],
        },
        {
          id: 'metaapi',
          title: 'MetaAPI Cloud',
          description: 'Cloud-based MetaAPI connection credentials',
          showWhen: (s) => s['TRADING_PROVIDER'] === 'metaapi',
          fields: [
            { key: 'METAAPI_TOKEN' },
            { key: 'METAAPI_ACCOUNT_ID' },
            { key: 'METAAPI_USE_STREAMING' },
          ],
        },
      ],
    },
    {
      id: 'risk',
      label: 'Risk',
      icon: <ShieldAlert className="h-4 w-4" />,
      description: 'Risk limits, lot sizing defaults, and drawdown protection',
      subSections: [
        {
          id: 'core-risk',
          title: 'Core Risk Limits',
          description: 'Hard limits applied to every trade',
          fields: [
            { key: 'MAX_RISK_PER_TRADE_PERCENT' },
            { key: 'MAX_OPEN_POSITIONS' },
            { key: 'RISK_REWARD_RATIO' },
          ],
        },
        {
          id: 'defaults',
          title: 'Signal Fallbacks',
          description: 'Default values used when a signal does not specify SL or TP',
          fields: [
            { key: 'DEFAULT_STOP_LOSS_PIPS' },
            { key: 'DEFAULT_TAKE_PROFIT_PIPS' },
            { key: 'SPREAD_ADJUSTMENT_MULTIPLIER' },
          ],
        },
        {
          id: 'drawdown',
          title: 'Equity & Drawdown Protection',
          description: 'Halt trading automatically when account equity drops beyond configured thresholds',
          fields: [
            { key: 'ENABLE_EQUITY_PROTECTION' },
            { key: 'DAILY_DRAWDOWN_LIMIT_PERCENT' },
            { key: 'OVERALL_DRAWDOWN_LIMIT_PERCENT' },
            { key: 'ENABLE_DRAWDOWN_MONITORING' },
          ],
        },
      ],
    },
    {
      id: 'execution',
      label: 'Execution',
      icon: <Zap className="h-4 w-4" />,
      description: 'Lot sizing, signal handling, approval workflow, and monitoring',
      subSections: [
        {
          id: 'lots',
          title: 'Lot Sizing',
          description: 'Trade size boundaries applied to all executed orders',
          fields: [
            { key: 'MIN_LOT_SIZE' },
            { key: 'MAX_LOT_SIZE' },
          ],
        },
        {
          id: 'signal-handling',
          title: 'Signal Handling',
          description: 'How signals are validated and routed to execution',
          fields: [
            { key: 'COPY_MASTER_MODE' },
            { key: 'SLIPPAGE_PIPS' },
            { key: 'MAX_SIGNAL_AGE_MINUTES' },
            { key: 'ENABLE_INSTANT_EXECUTION' },
            { key: 'INSTANT_EXECUTION_CHANNELS', showWhen: (s) => s['ENABLE_INSTANT_EXECUTION'] === true },
            { key: 'INSTANT_EXECUTION_KEYWORDS', showWhen: (s) => s['ENABLE_INSTANT_EXECUTION'] === true },
            { key: 'INSTANT_EXECUTION_MAX_DEVIATION_PIPS', showWhen: (s) => s['ENABLE_INSTANT_EXECUTION'] === true },
            { key: 'INSTANT_ONE_LEG_MAX_TP1_PROGRESS', showWhen: (s) => s['ENABLE_INSTANT_EXECUTION'] === true },
            { key: 'INSTANT_TEMP_SL_PIPS', showWhen: (s) => s['ENABLE_INSTANT_EXECUTION'] === true },
            { key: 'INSTANT_FIRST_ENTRY_RISK_SHARE', showWhen: (s) => s['ENABLE_INSTANT_EXECUTION'] === true },
            { key: 'SIGNAL_CONTINUITY_WINDOW_MINUTES' },
            { key: 'SAME_LEVEL_TOLERANCE_PIPS' },
          ],
        },
        {
          id: 'approval',
          title: 'Manual Approval',
          description: 'Hold signals in a queue until manually approved with /execute',
          masterToggle: 'REQUIRE_MANUAL_APPROVAL',
          fields: [
            { key: 'APPROVAL_REQUIRED_CHANNELS' },
          ],
        },
        {
          id: 'approval-delivery',
          title: 'Approval Requests',
          description: 'Order of checks: safety gates (status / "no entry" captions, brain unavailable) → high-risk override → image signals → Manual Approval. Settings here apply to every approval request, whichever rule sent it',
          fields: [
            { key: 'REQUIRE_APPROVAL_FOR_IMAGES' },
            { key: 'APPROVAL_CHANNEL_ID' },
            { key: 'APPROVAL_TIMEOUT_MINUTES' },
            { key: 'APPROVAL_SEND_IMAGE' },
          ],
        },
        {
          id: 'high-risk-override',
          title: 'High-Risk Override',
          description: 'When a signal only fails because its risk exceeds Max Risk Per Trade, send it to the approval queue with a disclaimer instead of auto-rejecting — so you can accept the extra risk or skip it',
          fields: [
            { key: 'ALLOW_HIGH_RISK_OVERRIDE' },
          ],
        },
        {
          id: 'estimated-sizing',
          title: 'Estimated Lot Size',
          description: 'If the broker\'s symbol data is unavailable, the lot size falls back to an estimated pip value. Ask for manual approval in that case instead of trading it blindly',
          fields: [
            { key: 'REQUIRE_APPROVAL_FOR_ESTIMATED_SIZING' },
          ],
        },
        {
          id: 'monitoring',
          title: 'Position Monitoring',
          description: 'Real-time monitoring that drives automatic TP, trailing stop, partial close, and breakeven',
          masterToggle: 'ENABLE_POSITION_MONITORING',
          fields: [
            { key: 'POSITION_MONITOR_INTERVAL_SECONDS' },
            { key: 'ORDER_CLOSE_GRACE_MISSES' },
            { key: 'ORDER_CANCEL_GRACE_MISSES' },
            { key: 'ORDER_STALE_PENDING_HOURS' },
          ],
        },
        {
          id: 'trade-plans',
          title: 'Trade Plans',
          description: 'Conditional multi-entry setups — watch price zones and execute trades automatically or manually',
          masterToggle: 'PLAN_WATCHER_ENABLED',
          fields: [
            { key: 'PLAN_AUTO_EXECUTE' },
            { key: 'PLAN_EXPIRY_HOURS' },
            { key: 'PLAN_GAP_RISK_BLOCK' },
          ],
        },
      ],
    },
    {
      id: 'positions',
      label: 'Positions',
      icon: <TrendingUp className="h-4 w-4" />,
      description: 'Automatic position management — TP, trailing stop, partial close, and breakeven',
      twoCol: true,
      subSections: [
        {
          id: 'auto-tp',
          title: 'Auto Take Profit',
          description: 'Set TP automatically when the signal does not provide one',
          masterToggle: 'ENABLE_AUTO_TAKE_PROFIT',
          fields: [
            { key: 'AUTO_TP_CALCULATION_METHOD' },
            { key: 'AUTO_TP_PIPS',        showWhen: (s) => s['AUTO_TP_CALCULATION_METHOD'] === 'PIPS' },
            { key: 'AUTO_TP_RISK_REWARD', showWhen: (s) => s['AUTO_TP_CALCULATION_METHOD'] === 'RR' || !s['AUTO_TP_CALCULATION_METHOD'] },
          ],
        },
        {
          id: 'trailing',
          title: 'Trailing Stop',
          description: 'Dynamically follow price with the stop loss as the trade moves in profit',
          masterToggle: 'ENABLE_TRAILING_STOP',
          fields: [
            { key: 'TRAILING_STOP_CALCULATION_METHOD' },
            { key: 'TRAILING_STOP_DISTANCE_PIPS', showWhen: (s) => s['TRAILING_STOP_CALCULATION_METHOD'] === 'PIPS' || !s['TRAILING_STOP_CALCULATION_METHOD'] },
            { key: 'TRAILING_STOP_DISTANCE_RR',   showWhen: (s) => s['TRAILING_STOP_CALCULATION_METHOD'] === 'RR' },
            { key: 'TRAILING_ACTIVATION_METHOD' },
            { key: 'TRAILING_ACTIVATION_PROFIT_PIPS', showWhen: (s) => s['TRAILING_ACTIVATION_METHOD'] === 'PROFIT_PIPS' },
            { key: 'TRAILING_ACTIVATION_PROFIT_RR',   showWhen: (s) => s['TRAILING_ACTIVATION_METHOD'] === 'PROFIT_RR' },
            { key: 'TRAILING_STOP_MIN_STEP_PIPS' },
            { key: 'TRAILING_STOP_MIN_INTERVAL_SECONDS' },
          ],
        },
        {
          id: 'partial',
          title: 'Partial Close',
          description: 'Automatically take a portion of profits at a configured profit level',
          masterToggle: 'ENABLE_AUTO_PARTIAL',
          fields: [
            { key: 'AUTO_PARTIAL_CALCULATION_METHOD' },
            { key: 'AUTO_PARTIAL_TRIGGER_PIPS', showWhen: (s) => s['AUTO_PARTIAL_CALCULATION_METHOD'] === 'PIPS' || !s['AUTO_PARTIAL_CALCULATION_METHOD'] },
            { key: 'AUTO_PARTIAL_TRIGGER_RR',   showWhen: (s) => s['AUTO_PARTIAL_CALCULATION_METHOD'] === 'RR' },
            { key: 'AUTO_PARTIAL_CLOSE_PERCENT' },
          ],
        },
        {
          id: 'runner',
          title: 'Runner Without TP',
          description: 'Place part of every signal without a take profit and let the channel\'s messages manage it',
          masterToggle: 'ENABLE_RUNNER_SPLIT',
          fields: [
            { key: 'RUNNER_SHARE_PERCENT' },
          ],
        },
        {
          id: 'breakeven',
          title: 'Breakeven',
          description: 'Move stop loss to entry price once the trade is sufficiently profitable',
          masterToggle: 'ENABLE_BREAKEVEN_MOVE',
          fields: [
            { key: 'BREAKEVEN_TRIGGER_METHOD' },
            { key: 'BREAKEVEN_TRIGGER_PIPS',          showWhen: (s) => s['BREAKEVEN_TRIGGER_METHOD'] === 'PROFIT_PIPS' },
            { key: 'BREAKEVEN_BUFFER_PIPS' },
            { key: 'BREAKEVEN_MIN_SIBLING_TP_HITS',   showWhen: (s) => s['BREAKEVEN_TRIGGER_METHOD'] === 'AFTER_SIBLING_TP_HIT' },
          ],
        },
      ],
    },
    {
      id: 'ai',
      label: 'AI',
      icon: <Brain className="h-4 w-4" />,
      description: 'AI provider credentials, image vision settings, Trading Brain, and market analysis',
      twoCol: true,
      subSections: [
        {
          id: 'primary-provider',
          title: 'Primary Provider',
          description: 'Which AI provider to use for signal extraction and fallback chain',
          fields: [
            { key: 'PRIMARY_AI_PROVIDER' },
            { key: 'FALLBACK_AI_PROVIDERS' },
          ],
        },
        {
          id: 'vision',
          title: 'AI Vision (Image Analysis)',
          description: 'Provider and model used to read and interpret chart images in signals',
          masterToggle: 'ENABLE_AI_VISION',
          fields: [
            { key: 'provider' },
            { key: 'OPENAI_VISION_MODEL',      showWhen: (s) => s['provider'] === 'openai' || !s['provider'] },
            { key: 'GEMINI_VISION_MODEL',      showWhen: (s) => s['provider'] === 'gemini' },
            { key: 'PERPLEXITY_VISION_MODEL',  showWhen: (s) => s['provider'] === 'perplexity' },
            { key: 'OPENROUTER_VISION_MODEL',  showWhen: (s) => s['provider'] === 'openrouter' },
            { key: 'DEEPSEEK_VISION_MODEL',    showWhen: (s) => s['provider'] === 'deepseek' },
            { key: 'MINIMAX_VISION_MODEL',     showWhen: (s) => s['provider'] === 'minimax' },
            { key: 'QWEN_VISION_MODEL',        showWhen: (s) => s['provider'] === 'qwen' },
          ],
        },
        {
          id: 'vision-filters',
          title: 'Vision Anti-Hallucination Filters',
          description: 'Optional filters that prevent the AI from mistaking trade results, MT5 screenshots, or price path charts for new signals — all off by default except the two safest ones',
          masterToggle: 'ENABLE_AI_VISION',
          fields: [
            { key: 'VISION_CAPTION_PREFILTER_ENABLED' },
            { key: 'VISION_CAPTION_BLOCK_KEYWORDS',   showWhen: (s) => s['VISION_CAPTION_PREFILTER_ENABLED'] === 'true' || s['VISION_CAPTION_PREFILTER_ENABLED'] === true },
            { key: 'VISION_CONFIDENCE_FILTER_ENABLED' },
            { key: 'VISION_MIN_CONFIDENCE',           showWhen: (s) => s['VISION_CONFIDENCE_FILTER_ENABLED'] === 'true' || s['VISION_CONFIDENCE_FILTER_ENABLED'] === true },
            { key: 'VISION_TWO_STEP_CLASSIFY_ENABLED' },
            { key: 'VISION_PRICE_SANITY_CHECK_ENABLED' },
            { key: 'VISION_PRICE_RANGES',             showWhen: (s) => s['VISION_PRICE_SANITY_CHECK_ENABLED'] === 'true' || s['VISION_PRICE_SANITY_CHECK_ENABLED'] === true },
            { key: 'VISION_SL_DISTANCE_CHECK_ENABLED' },
            { key: 'VISION_MAX_SL_DISTANCE_PERCENT',  showWhen: (s) => s['VISION_SL_DISTANCE_CHECK_ENABLED'] === 'true' || s['VISION_SL_DISTANCE_CHECK_ENABLED'] === true },
            { key: 'VISION_SYMBOL_WHITELIST_ENABLED' },
            { key: 'VISION_ALLOWED_SYMBOLS',          showWhen: (s) => s['VISION_SYMBOL_WHITELIST_ENABLED'] === 'true' || s['VISION_SYMBOL_WHITELIST_ENABLED'] === true },
            { key: 'VISION_IMAGE_DIMENSION_FILTER_ENABLED' },
            { key: 'VISION_MAX_IMAGE_ASPECT_RATIO',   showWhen: (s) => s['VISION_IMAGE_DIMENSION_FILTER_ENABLED'] === 'true' || s['VISION_IMAGE_DIMENSION_FILTER_ENABLED'] === true },
            { key: 'VISION_MIN_IMAGE_HEIGHT',         showWhen: (s) => s['VISION_IMAGE_DIMENSION_FILTER_ENABLED'] === 'true' || s['VISION_IMAGE_DIMENSION_FILTER_ENABLED'] === true },
          ],
        },
        {
          id: 'openai',
          title: 'OpenAI',
          description: 'GPT-4 series — reliable, widely supported, good vision quality',
          fields: [
            { key: 'OPENAI_API_KEY' },
            { key: 'OPENAI_MODEL' },
            { key: 'OPENAI_VISION_MODEL' },
          ],
        },
        {
          id: 'gemini',
          title: 'Google Gemini',
          description: 'Gemini 2.0 Flash — ~10× cheaper than OpenAI with excellent vision support',
          fields: [
            { key: 'GEMINI_API_KEY' },
            { key: 'GEMINI_MODEL' },
            { key: 'GEMINI_VISION_MODEL' },
          ],
        },
        {
          id: 'perplexity',
          title: 'Perplexity',
          description: 'Perplexity Sonar — real-time web search augmented responses',
          fields: [
            { key: 'PERPLEXITY_API_KEY' },
            { key: 'PERPLEXITY_BASE_URL' },
            { key: 'PERPLEXITY_MODEL' },
            { key: 'PERPLEXITY_VISION_MODEL' },
          ],
        },
        {
          id: 'openrouter',
          title: 'OpenRouter',
          description: 'Access hundreds of models (Qwen, Llama, Gemini, etc.) via a single API key',
          fields: [
            { key: 'OPENROUTER_API_KEY' },
            { key: 'OPENROUTER_BASE_URL' },
            { key: 'OPENROUTER_MODEL' },
            { key: 'OPENROUTER_VISION_MODEL' },
          ],
        },
        {
          id: 'minimax',
          title: 'MiniMax',
          description: 'MiniMax M2.7 — strong reasoning, OpenAI-compatible API, affordable pricing',
          fields: [
            { key: 'MINIMAX_API_KEY' },
            { key: 'MINIMAX_BASE_URL' },
            { key: 'MINIMAX_MODEL' },
            { key: 'MINIMAX_VISION_MODEL' },
          ],
        },
        {
          id: 'qwen',
          title: 'Qwen (Alibaba DashScope)',
          description: 'Qwen — multilingual models with strong vision capabilities, OpenAI-compatible',
          fields: [
            { key: 'QWEN_API_KEY' },
            { key: 'QWEN_BASE_URL' },
            { key: 'QWEN_MODEL' },
            { key: 'QWEN_VISION_MODEL' },
          ],
        },
        {
          id: 'deepseek',
          title: 'DeepSeek',
          description: 'DeepSeek — fast, cost-efficient models with strong reasoning',
          fields: [
            { key: 'DEEPSEEK_API_KEY' },
            { key: 'DEEPSEEK_API_URL' },
            { key: 'DEEPSEEK_MODEL' },
            { key: 'DEEPSEEK_VISION_MODEL' },
          ],
        },
        {
          id: 'ollama',
          title: 'Ollama (Local)',
          description: 'Run models locally on your own hardware — no API costs, full privacy',
          fields: [
            { key: 'OLLAMA_URL' },
            { key: 'OLLAMA_MODEL' },
          ],
        },
        {
          id: 'brain',
          title: 'Trading Brain',
          description: 'Persistent AI session that reviews every signal and monitors open positions in real-time',
          masterToggle: 'ENABLE_TRADING_BRAIN',
          fields: [
            { key: 'BRAIN_BASE_URL' },
            { key: 'BRAIN_API_KEY' },
            { key: 'BRAIN_MODEL' },
            { key: 'BRAIN_TEMPERATURE' },
            { key: 'BRAIN_MAX_HISTORY_MESSAGES' },
            { key: 'BRAIN_POSITION_REVIEW_INTERVAL' },
            { key: 'BRAIN_ACTION_REQUIRE_APPROVAL' },
            { key: 'BRAIN_ACTION_APPROVAL_TYPES' },
            { key: 'BRAIN_UNAVAILABLE_ACTION' },
            { key: 'BRAIN_SEND_IMAGES' },
            { key: 'REQUIRE_RISK_VALIDATION' },
          ],
        },
        {
          id: 'market-analysis',
          title: 'Market Analysis',
          description: 'AI monitors open positions for trend changes and suggests adjustments',
          masterToggle: 'ENABLE_AI_MARKET_ANALYSIS',
          fields: [
            { key: 'AI_ANALYSIS_CHECK_INTERVAL' },
            { key: 'ENABLE_AI_BREAKEVEN_TRIGGERS' },
            { key: 'ENABLE_AI_TP_ADJUSTMENT' },
            { key: 'ENABLE_AI_POSITION_REDUCTION' },
            { key: 'AI_ANALYSIS_CONFIDENCE_THRESHOLD' },
            { key: 'AI_AUTO_VERIFICATION_ENABLED' },
          ],
        },
        {
          id: 'llm-market-analysis',
          title: 'LLM Market Analysis',
          description: 'Standalone LLM-powered market analysis that consumes AI provider credits',
          masterToggle: 'ENABLE_LLM_MARKET_ANALYSIS',
          fields: [
            { key: 'LLM_MARKET_ANALYSIS_INTERVAL' },
          ],
        },
      ],
    },
    {
      id: 'system',
      label: 'System',
      icon: <Cpu className="h-4 w-4" />,
      description: 'Signal validator, news filter, logging, and general bot settings',
      subSections: [
        {
          id: 'validator',
          title: 'Signal Validator',
          description: 'External API that validates signals before execution — fail-open if unreachable',
          masterToggle: 'ENABLE_SIGNAL_VALIDATOR',
          fields: [
            { key: 'SIGNAL_VALIDATOR_URL' },
            { key: 'SIGNAL_VALIDATOR_API_KEY' },
            { key: 'SIGNAL_VALIDATOR_TIMEOUT_SECONDS' },
            { key: 'SIGNAL_VALIDATOR_EXECUTION_POLICY' },
          ],
        },
        {
          id: 'news',
          title: 'News Filter',
          description: 'Block new trades around scheduled economic news events',
          masterToggle: 'NEWS_ENABLE_FILTER',
          fields: [
            { key: 'NEWS_MINUTES_BEFORE' },
            { key: 'NEWS_MINUTES_AFTER' },
            { key: 'NEWS_IMPORTANT_IMPACTS' },
            { key: 'NEWS_TARGET_CURRENCIES' },
            { key: 'NEWS_ENABLE_NOTIFICATIONS' },
            { key: 'NEWS_NOTIFICATION_MINUTES_BEFORE', showWhen: (s) => s['NEWS_ENABLE_NOTIFICATIONS'] === true },
            { key: 'NEWS_UPDATE_INTERVAL_HOURS' },
            { key: 'NEWS_VERBOSE_LOGGING' },
            { key: 'NEWS_API_URL' },
          ],
        },
        {
          id: 'news-posts',
          title: 'News Channel Posts',
          description: 'Post upcoming news to a channel you choose, with its own impact and currency selection. Independent of the news filter above',
          masterToggle: 'NEWS_POST_ENABLED',
          fields: [
            { key: 'NEWS_POST_CHANNEL_ID' },
            { key: 'NEWS_POST_IMPACTS' },
            { key: 'NEWS_POST_CURRENCIES' },
            { key: 'NEWS_POST_MINUTES_BEFORE' },
          ],
        },
        {
          id: 'logging',
          title: 'Logging',
          description: 'Console and file output verbosity',
          fields: [
            { key: 'LOG_LEVEL' },
            { key: 'LOG_FILE_LEVEL' },
            { key: 'LOG_FILE_DEBUG' },
          ],
        },
        {
          id: 'general',
          title: 'General',
          description: 'Bot behaviour and runtime options',
          fields: [
            { key: 'DRY_RUN' },
            { key: 'TIMEZONE' },
            { key: 'SKIP_METAAPI' },
            { key: 'POSITION_MONITOR_STARTUP_DELAY_SECONDS' },
            { key: 'MESSAGE_PROCESSING_CONCURRENCY' },
            { key: 'ALLOW_MULTI_SIGNAL_POSTS' },
            { key: 'CATCHUP_ENABLED' },
            { key: 'CATCHUP_MAX_MESSAGES' },
            { key: 'CATCHUP_INTERVAL_MINUTES' },
          ],
        },
      ],
    },
  ], [])

  // ─── Derived state ───────────────────────────────────────────────────────────

  const predefinedKeys = useMemo(() => {
    const keys = new Set<string>()
    TAB_SCHEMA.forEach(tab => {
      tab.subSections.forEach(sub => {
        if (sub.masterToggle) keys.add(sub.masterToggle)
        sub.fields.forEach(f => keys.add(f.key))
      })
    })
    return keys
  }, [TAB_SCHEMA])

  const customKeys = useMemo(
    // DISCORD_* (token, on/off) are managed on the Discord page
    () => allSettingsList.filter(s => !predefinedKeys.has(s.key) && !s.key.startsWith('DISCORD_')).map(s => s.key),
    [allSettingsList, predefinedKeys]
  )

  // ─── Effects ─────────────────────────────────────────────────────────────────

  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (hasPendingChanges) { e.preventDefault(); e.returnValue = '' }
    }
    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => window.removeEventListener('beforeunload', handleBeforeUnload)
  }, [hasPendingChanges])

  useEffect(() => { loadSettings() }, [showSecrets])
  useEffect(() => { void fetchDiscordChannels() }, [])

  // ─── Data loading ─────────────────────────────────────────────────────────────

  const loadSettings = async () => {
    try {
      setLoading(true)
      const decryptParam = showSecrets ? 'decryptSecrets=true' : ''
      const response = await fetch(`/api/settings?${decryptParam}`)
      if (!response.ok) throw new Error('Failed to load settings')
      const data = await response.json()
      const settingsMap: Record<string, any> = {}
      const secretSet = new Set<string>()
      const allSettings: Setting[] = data.all ?? data.settings ?? []
      setAllSettingsList(allSettings)
      allSettings.forEach((setting: Setting) => {
        settingsMap[setting.key] = setting.parsedValue
        if (setting.isSecret) secretSet.add(setting.key)
      })
      setSettings(settingsMap)
      setOriginalSettings({ ...settingsMap })
      setPendingChanges({})
      setSecretKeys(secretSet)
    } catch (err) {
      toast({ title: 'Error', description: err instanceof Error ? err.message : 'Failed to load settings', variant: 'destructive' })
    } finally {
      setLoading(false)
    }
  }

  const fetchSharedChannels = async () => {
    try {
      setChannelsLoading(true)
      const response = await fetch('/api/telegram/channels/all')
      const data = await response.json()
      if (data.success) setSharedChannels(data.data)
    } catch (error) {
      console.error('Error loading channels:', error)
    } finally {
      setChannelsLoading(false)
    }
  }

  const fetchDiscordChannels = async () => {
    try {
      const response = await fetch('/api/discord', { cache: 'no-store' })
      if (!response.ok) return
      const data = await response.json()
      setDiscordChannels(
        (data?.status?.channels ?? []).map((c: { id: string; name: string | null; guildName: string | null }) => ({
          id: c.id,
          title: `${c.guildName ?? 'Discord'} #${c.name ?? c.id}`,
        }))
      )
    } catch {
      // Discord is optional: without it the pickers simply list Telegram channels
    }
  }

  const refreshSharedChannels = async () => {
    try {
      setChannelsLoading(true)
      // Force-reload from Telegram so newly joined channels appear
      const response = await fetch('/api/telegram/channels/refresh', { method: 'POST' })
      const data = await response.json()
      if (data.success) {
        setSharedChannels(data.data)
        toast({ title: 'Channels Refreshed', description: `Found ${data.data?.statistics?.total_dialogs ?? 0} channels from Telegram.` })
      }
    } catch (error) {
      console.error('Error refreshing channels:', error)
      toast({ title: 'Refresh Failed', description: 'Could not reload channels from Telegram.', variant: 'destructive' })
    } finally {
      setChannelsLoading(false)
    }
  }

  // ─── Handlers ─────────────────────────────────────────────────────────────────

  const handleUpdateSetting = (key: string, value: any) => {
    setSettings(prev => ({ ...prev, [key]: value }))
    if (originalSettings[key] !== value) {
      setPendingChanges(prev => ({ ...prev, [key]: value }))
    } else {
      setPendingChanges(prev => { const n = { ...prev }; delete n[key]; return n })
    }
  }

  const handleSaveAll = async () => {
    if (!hasPendingChanges) return
    try {
      setSavingAll(true)
      const settingsCount = Object.keys(pendingChanges).length
      const savePromises = Object.entries(pendingChanges).map(([key, value]) =>
        fetch(`/api/settings/${key}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ value }),
        }).then(res => { if (!res.ok) throw new Error(`Failed to update ${key}`); return { key, success: true } })
      )
      if (aiConfigDirty) {
        savePromises.push(aiConfigRef.current?.save() as any)
      }
      await Promise.all(savePromises)
      setOriginalSettings({ ...settings })
      setPendingChanges({})
      setSavedButNotReloaded(true)
      toast({ title: 'Changes Saved', description: `Successfully saved ${settingsCount} setting(s)${aiConfigDirty ? ' + AI config' : ''}. Reload the bot to apply changes.` })
    } catch (err) {
      toast({ title: 'Save Failed', description: err instanceof Error ? err.message : 'Failed to save changes', variant: 'destructive' })
    } finally {
      setSavingAll(false)
      setShowConfirmDialog(false)
    }
  }

  const handleCancelChanges = () => {
    setSettings({ ...originalSettings })
    setPendingChanges({})
    aiConfigRef.current?.reset()
    toast({ title: 'Changes Discarded', description: 'All unsaved changes have been reverted' })
  }

  const handleCreateSetting = async (data: { key: string; value: string; valueType: string; category: string; description: string; isSecret: boolean }) => {
    try {
      const response = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
      if (!response.ok) { const error = await response.json(); throw new Error(error.error || 'Failed to create setting') }
      toast({ title: 'Setting Created', description: `Setting '${data.key}' created successfully.`, duration: 2000 })
      setShowCreateModal(false)
      loadSettings()
    } catch (err) {
      toast({ title: 'Creation Failed', description: err instanceof Error ? err.message : 'Failed to create setting', variant: 'destructive' })
    }
  }

  const handleReloadSettings = async () => {
    try {
      setReloading(true)
      const response = await fetch('/api/settings/reload', { method: 'POST' })
      if (!response.ok) throw new Error('Failed to reload settings')
      const data = await response.json()
      setSavedButNotReloaded(false)
      toast({ title: 'Bot Reloaded', description: data.message || 'Settings reloaded and applied to the bot.' })
    } catch (err) {
      toast({ title: 'Reload Failed', description: err instanceof Error ? err.message : 'Failed to reload settings', variant: 'destructive' })
    } finally {
      setReloading(false)
    }
  }

  // ─── Label helper ─────────────────────────────────────────────────────────────

  const getSettingLabel = (key: string): string =>
    SETTING_LABELS[key] ?? key.replace(/_/g, ' ').toLowerCase().replace(/\b\w/g, c => c.toUpperCase())

  // ─── Input renderer ───────────────────────────────────────────────────────────

  const renderSettingInput = (key: string, value: any) => {
    const isSecret = secretKeys.has(key)
    const hasChanged = pendingChanges.hasOwnProperty(key)

    if (isSecret && !showSecrets) {
      return (
        <div className="flex items-center gap-2 px-3 py-1.5 bg-muted/50 rounded-lg text-[10px] font-bold text-muted-foreground/70 border border-border/60 shadow-sm">
          <Lock className="h-3 w-3 text-muted-foreground/50" />
          <span className="uppercase tracking-wider italic">Value Protected</span>
        </div>
      )
    }

    if (MODEL_FIELD_PROVIDERS[key]) {
      return (
        <div className="flex items-center gap-2">
          <ModelSelect
            provider={MODEL_FIELD_PROVIDERS[key]}
            value={value?.toString() || ''}
            onChange={(v) => handleUpdateSetting(key, v)}
            hasChanged={hasChanged}
          />
          {hasChanged && <Badge variant="outline" className="text-[9px] bg-amber-500/10 text-amber-400 border-amber-500/20">Modified</Badge>}
        </div>
      )
    }

    if (key === 'BRAIN_ACTION_APPROVAL_TYPES') {
      const ALL_ACTIONS = ['CLOSE', 'PARTIAL_CLOSE', 'MODIFY_SL', 'MODIFY_TP']
      const ACTION_LABELS: Record<string, string> = {
        CLOSE: 'Close',
        PARTIAL_CLOSE: 'Partial Close',
        MODIFY_SL: 'Modify SL',
        MODIFY_TP: 'Modify TP',
      }
      const raw = typeof value === 'string' ? value : (Array.isArray(value) ? value.join(',') : '')
      const active = new Set(raw.split(',').map((s: string) => s.trim().toUpperCase()).filter(Boolean))
      const toggle = (action: string) => {
        const next = new Set(active)
        next.has(action) ? next.delete(action) : next.add(action)
        handleUpdateSetting(key, [...next].join(','))
      }
      return (
        <div className="flex items-center gap-1.5 flex-wrap">
          {ALL_ACTIONS.map(action => {
            const on = active.has(action)
            return (
              <button
                key={action}
                onClick={() => toggle(action)}
                className={cn(
                  'h-7 px-2.5 rounded-full text-[10px] font-bold uppercase tracking-wide border transition-all',
                  on
                    ? 'bg-blue-600 text-white border-blue-600 shadow-sm'
                    : 'bg-muted/50 text-muted-foreground/70 border-border hover:border-border hover:text-muted-foreground'
                )}
              >
                {ACTION_LABELS[action]}
              </button>
            )
          })}
          {hasChanged && <Badge variant="outline" className="text-[9px] bg-amber-500/10 text-amber-400 border-amber-500/30 ml-1">Modified</Badge>}
        </div>
      )
    }

    if (settingOptions[key]) {
      // Use searchable select for provider fields
      const isProviderField = ['provider', 'TRADING_PROVIDER', 'PRIMARY_AI_PROVIDER'].includes(key)
      
      if (isProviderField) {
        return (
          <div className="flex items-center gap-2">
            <SearchableSelect
              options={settingOptions[key]}
              value={value?.toString() || ''}
              onChange={(v) => handleUpdateSetting(key, v)}
              placeholder="Select provider"
              hasChanged={hasChanged}
            />
            {hasChanged && <Badge variant="outline" className="text-[9px] bg-amber-500/10 text-amber-400 border-amber-500/20">Modified</Badge>}
          </div>
        )
      }
      
      return (
        <div className="flex items-center gap-2">
          <Select value={value?.toString() || ''} onValueChange={(v) => handleUpdateSetting(key, v)}>
            <SelectTrigger className={cn('w-[180px] h-8 text-xs font-semibold', hasChanged && 'border-amber-500/50 bg-amber-500/10 text-foreground')}>
              <SelectValue placeholder="Select option" />
            </SelectTrigger>
            <SelectContent>
              {settingOptions[key].map((option) => (
                <SelectItem key={option.value} value={option.value} className="text-xs">
                  <div className="flex flex-col">
                    <span className="font-semibold">{option.label}</span>
                    {option.description && <span className="text-[10px] text-muted-foreground">{option.description}</span>}
                  </div>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {hasChanged && <Badge variant="outline" className="text-[9px] bg-amber-500/10 text-amber-400 border-amber-500/20">Modified</Badge>}
        </div>
      )
    }

    if (typeof value === 'boolean') {
      return (
        <div className="flex items-center gap-2">
          <span className={cn('text-[10px] font-bold uppercase tracking-wider', value ? 'text-primary' : 'text-muted-foreground/70')}>
            {value ? 'Enabled' : 'Disabled'}
          </span>
          <Switch checked={value} onCheckedChange={(checked) => handleUpdateSetting(key, checked)} />
          {hasChanged && <Badge variant="outline" className="text-[9px] bg-amber-500/10 text-amber-400 border-amber-500/20">Modified</Badge>}
        </div>
      )
    }

    if (typeof value === 'number') {
      return (
        <div className="flex items-center gap-2">
          <Input
            type="number" step="any" value={value}
            onChange={(e) => { const p = parseFloat(e.target.value); if (!isNaN(p)) handleUpdateSetting(key, p) }}
            className={cn('w-24 h-8 text-xs font-bold text-right pr-2.5', hasChanged && 'border-amber-500/50 bg-amber-500/10 text-foreground')}
          />
          {hasChanged && <Badge variant="outline" className="text-[9px] bg-amber-500/10 text-amber-400 border-amber-500/20">Modified</Badge>}
        </div>
      )
    }

    const displayValue = Array.isArray(value) ? value.join(',') : (value || '')
    return (
      <div className="flex items-center gap-2">
        <Input
          type="text" value={displayValue}
          // Empty here does not mean "not configured": the bot then uses the server's .env
          placeholder={key.startsWith('TELEGRAM_API_') || key === 'TELEGRAM_PHONE' ? 'empty = from server .env' : undefined}
          onChange={(e) => {
            const shouldConvertToArray = Array.isArray(value) || (typeof value === 'object' && value !== null)
            const newValue = shouldConvertToArray ? e.target.value.split(',').map(v => v.trim()).filter(Boolean) : e.target.value
            handleUpdateSetting(key, newValue)
          }}
          className={cn('w-[180px] h-8 text-xs font-semibold', hasChanged && 'border-amber-500/50 bg-amber-500/10 text-foreground')}
        />
        {hasChanged && <Badge variant="outline" className="text-[9px] bg-amber-500/10 text-amber-400 border-amber-500/20">Modified</Badge>}
      </div>
    )
  }

  // ─── Row renderer ─────────────────────────────────────────────────────────────

  const renderSettingRow = (key: string, value: any) => {
    const description = settingDescriptions[key]
    const displayValue = Array.isArray(value) ? value.join(',') : value

    if (key === 'TELEGRAM_CHANNEL_ID') {
      const stringValue = Array.isArray(value) ? value.join(',') : (value || '')
      return (
        <div key={key} className="flex flex-col gap-2 py-2.5 px-4 hover:bg-muted/15 transition-colors">
          <div className="space-y-0.5">
            <Label className="text-xs font-semibold text-foreground/90">{getSettingLabel(key)}</Label>
            {description && <p className="text-[11px] text-muted-foreground leading-normal">{description}</p>}
          </div>
          <TelegramChannelSelector currentValue={stringValue} onChange={(v) => handleUpdateSetting(key, v)} sharedChannels={sharedChannels} onFetchChannels={fetchSharedChannels} onRefreshChannels={refreshSharedChannels} isLoading={channelsLoading} />
        </div>
      )
    }

    if (key === 'TELEGRAM_NOTIFICATION_CHAT_ID' || key === 'SIGNAL_FORWARD_CHANNEL_ID' || key === 'NEWS_POST_CHANNEL_ID') {
      const stringValue = Array.isArray(value) ? value[0] || '' : (value ? String(value) : '')
      return (
        <div key={key} className="flex flex-col gap-2 py-2.5 px-4 hover:bg-muted/15 transition-colors">
          <div className="space-y-0.5">
            <Label className="text-xs font-semibold text-foreground/90">{getSettingLabel(key)}</Label>
            {description && <p className="text-[11px] text-muted-foreground leading-normal">{description}</p>}
          </div>
          <TelegramNotificationSelector currentValue={stringValue} onChange={(v) => handleUpdateSetting(key, v)} sharedChannels={sharedChannels} onFetchChannels={fetchSharedChannels} isLoading={channelsLoading} />
        </div>
      )
    }

    if (key === 'APPROVAL_REQUIRED_CHANNELS') {
      const telegramChannelId = settings['TELEGRAM_CHANNEL_ID']
      const allowedChannelIdsString = Array.isArray(telegramChannelId) ? telegramChannelId.join(',') : (telegramChannelId || '')
      return (
        <div key={key} className="flex flex-col gap-2 py-2.5 px-4 hover:bg-muted/15 transition-colors">
          <div className="space-y-0.5">
            <Label className="text-xs font-semibold text-foreground/90">{getSettingLabel(key)}</Label>
            {description && <p className="text-[11px] text-muted-foreground leading-normal">{description}</p>}
          </div>
          <TelegramChannelSelector currentValue={value || ''} onChange={(v) => handleUpdateSetting(key, v)} sharedChannels={sharedChannels} onFetchChannels={fetchSharedChannels} onRefreshChannels={refreshSharedChannels} isLoading={channelsLoading} allowedChannelIds={allowedChannelIdsString} extraChannels={discordChannels} />
        </div>
      )
    }

    if (key === 'INSTANT_EXECUTION_CHANNELS') {
      const telegramChannelId = settings['TELEGRAM_CHANNEL_ID']
      const allowedChannelIdsString = Array.isArray(telegramChannelId) ? telegramChannelId.join(',') : (telegramChannelId || '')
      return (
        <div key={key} className="flex flex-col gap-2 py-2.5 px-4 hover:bg-muted/15 transition-colors">
          <div className="space-y-0.5">
            <Label className="text-xs font-semibold text-foreground/90">{getSettingLabel(key)}</Label>
            {description && <p className="text-[11px] text-muted-foreground leading-normal">{description}</p>}
          </div>
          <TelegramChannelSelector currentValue={value || ''} onChange={(v) => handleUpdateSetting(key, v)} sharedChannels={sharedChannels} onFetchChannels={fetchSharedChannels} onRefreshChannels={refreshSharedChannels} isLoading={channelsLoading} allowedChannelIds={allowedChannelIdsString} extraChannels={discordChannels} />
        </div>
      )
    }

    if (key === 'FALLBACK_AI_PROVIDERS') {
      const ALL_PROVIDER_OPTIONS = [
        { value: 'openai',      label: 'OpenAI' },
        { value: 'gemini',      label: 'Gemini' },
        { value: 'deepseek',    label: 'DeepSeek' },
        { value: 'perplexity',  label: 'Perplexity' },
        { value: 'ollama',      label: 'Ollama' },
        { value: 'openrouter',  label: 'OpenRouter' },
        { value: 'minimax',     label: 'MiniMax' },
        { value: 'qwen',        label: 'Qwen' },
      ]
      const primaryProvider = settings['PRIMARY_AI_PROVIDER'] || ''
      const PROVIDER_OPTIONS = ALL_PROVIDER_OPTIONS.filter(o => o.value !== primaryProvider)
      const raw = Array.isArray(value) ? value.join(',') : (value || '')
      const selected: string[] = raw.split(',').map((v: string) => v.trim()).filter(Boolean).filter((v: string) => v !== primaryProvider)
      const hasChanged = pendingChanges.hasOwnProperty(key)
      const toggle = (opt: string) => {
        const next = selected.includes(opt)
          ? selected.filter((v: string) => v !== opt)
          : [...selected, opt]
        handleUpdateSetting(key, next.join(','))
      }
      return (
        <div key={key} className="group flex flex-col sm:flex-row sm:items-start justify-between gap-3 py-2.5 px-4 hover:bg-muted/15 transition-colors">
          <div className="flex-1 space-y-0.5 min-w-0 pr-3">
            <Label className="text-xs font-semibold text-foreground/90">{getSettingLabel(key)}</Label>
            {description && <p className="text-[11px] text-muted-foreground leading-normal">{description}</p>}
          </div>
          <div className="flex flex-col gap-1.5 shrink-0 self-start sm:pt-0.5">
            <div className="flex flex-wrap gap-1">
              {PROVIDER_OPTIONS.map(opt => {
                const active = selected.includes(opt.value)
                return (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => toggle(opt.value)}
                    className={cn(
                      'px-2.5 py-0.5 rounded-full text-[10px] font-bold border transition-colors',
                      active
                        ? 'bg-blue-600 text-white border-blue-600'
                        : 'bg-muted/40 text-muted-foreground border-border hover:border-border hover:text-foreground/80'
                    )}
                  >
                    {opt.label}
                  </button>
                )
              })}
            </div>
            {selected.length > 0 && (
              <p className="text-[10px] text-muted-foreground/70 font-medium">Order: {selected.join(' → ')}</p>
            )}
            {hasChanged && <Badge variant="outline" className="text-[9px] bg-amber-500/10 text-amber-400 border-amber-500/20 w-fit">Modified</Badge>}
          </div>
        </div>
      )
    }

    if (key === 'NEWS_IMPORTANT_IMPACTS' || key === 'NEWS_POST_IMPACTS') {
      const IMPACT_OPTIONS = [
        { value: 'High',    label: 'High',    color: 'bg-red-600 text-white border-red-600' },
        { value: 'Medium',  label: 'Medium',  color: 'bg-amber-500 text-white border-amber-500' },
        { value: 'Low',     label: 'Low',     color: 'bg-blue-500 text-white border-blue-500' },
        { value: 'Holiday', label: 'Holiday', color: 'bg-purple-600 text-white border-purple-600' },
      ]
      const raw = Array.isArray(value) ? value.join(',') : (value || '')
      const selected: string[] = raw.split(',').map((v: string) => v.trim()).filter(Boolean)
      const hasChanged = pendingChanges.hasOwnProperty(key)
      const toggle = (opt: string) => {
        const next = selected.includes(opt)
          ? selected.filter((v: string) => v !== opt)
          : [...selected, opt]
        handleUpdateSetting(key, next.join(','))
      }
      return (
        <div key={key} className="group flex flex-col sm:flex-row sm:items-start justify-between gap-3 py-2.5 px-4 hover:bg-muted/15 transition-colors">
          <div className="flex-1 space-y-0.5 min-w-0 pr-3">
            <Label className="text-xs font-semibold text-foreground/90">{getSettingLabel(key)}</Label>
            {description && <p className="text-[11px] text-muted-foreground leading-normal">{description}</p>}
          </div>
          <div className="flex flex-col gap-1.5 shrink-0 self-start sm:pt-0.5">
            <div className="flex flex-wrap gap-1">
              {IMPACT_OPTIONS.map(opt => {
                const active = selected.includes(opt.value)
                return (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => toggle(opt.value)}
                    className={cn(
                      'px-2.5 py-0.5 rounded-full text-[10px] font-bold border transition-colors',
                      active
                        ? opt.color
                        : 'bg-muted/40 text-muted-foreground border-border hover:border-border hover:text-foreground/80'
                    )}
                  >
                    {opt.label}
                  </button>
                )
              })}
            </div>
            {hasChanged && <Badge variant="outline" className="text-[9px] bg-amber-500/10 text-amber-400 border-amber-500/20 w-fit">Modified</Badge>}
          </div>
        </div>
      )
    }

    if (key === 'NEWS_TARGET_CURRENCIES' || key === 'NEWS_POST_CURRENCIES') {
      const CURRENCY_OPTIONS = [
        { value: 'EUR', label: 'EUR' },
        { value: 'USD', label: 'USD' },
        { value: 'GBP', label: 'GBP' },
        { value: 'JPY', label: 'JPY' },
        { value: 'CAD', label: 'CAD' },
        { value: 'AUD', label: 'AUD' },
        { value: 'NZD', label: 'NZD' },
        { value: 'CHF', label: 'CHF' },
        { value: 'ALL', label: 'ALL' },
      ]
      const raw = Array.isArray(value) ? value.join(',') : (value || '')
      const selected: string[] = raw.split(',').map((v: string) => v.trim().toUpperCase()).filter(Boolean)
      const hasChanged = pendingChanges.hasOwnProperty(key)
      const toggle = (opt: string) => {
        const next = selected.includes(opt)
          ? selected.filter((v: string) => v !== opt)
          : [...selected, opt]
        handleUpdateSetting(key, next.join(','))
      }
      return (
        <div key={key} className="group flex flex-col sm:flex-row sm:items-start justify-between gap-3 py-2.5 px-4 hover:bg-muted/15 transition-colors">
          <div className="flex-1 space-y-0.5 min-w-0 pr-3">
            <Label className="text-xs font-semibold text-foreground/90">{getSettingLabel(key)}</Label>
            {description && <p className="text-[11px] text-muted-foreground leading-normal">{description}</p>}
          </div>
          <div className="flex flex-col gap-1.5 shrink-0 self-start sm:pt-0.5">
            <div className="flex flex-wrap gap-1">
              {CURRENCY_OPTIONS.map(opt => {
                const active = selected.includes(opt.value)
                return (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => toggle(opt.value)}
                    className={cn(
                      'px-2 py-0.5 rounded text-[10px] font-bold border transition-colors',
                      active
                        ? 'bg-emerald-600 text-white border-emerald-600 shadow-sm'
                        : 'bg-muted/40 text-muted-foreground border-border hover:border-border hover:text-foreground/80'
                    )}
                  >
                    {opt.label}
                  </button>
                )
              })}
            </div>
            {hasChanged && <Badge variant="outline" className="text-[9px] bg-amber-500/10 text-amber-400 border-amber-500/20 w-fit">Modified</Badge>}
          </div>
        </div>
      )
    }

    if (key === 'APPROVAL_CHANNEL_ID') {
      const stringValue = Array.isArray(value) ? value[0] || '' : (value ? String(value) : '')
      return (
        <div key={key} className="flex flex-col gap-2 py-2.5 px-4 hover:bg-muted/15 transition-colors">
          <div className="space-y-0.5">
            <Label className="text-xs font-semibold text-foreground/90">{getSettingLabel(key)}</Label>
            {description && <p className="text-[11px] text-muted-foreground leading-normal">{description}</p>}
          </div>
          <TelegramNotificationSelector currentValue={stringValue} onChange={(v) => handleUpdateSetting(key, v)} sharedChannels={sharedChannels} onFetchChannels={fetchSharedChannels} isLoading={channelsLoading} />
        </div>
      )
    }

    return (
      <div key={key} className="group flex flex-col sm:flex-row sm:items-center justify-between gap-3 py-2.5 px-4 hover:bg-muted/15 transition-colors">
        <div className="flex-1 space-y-0.5 min-w-0 pr-3">
          <div className="flex items-center gap-2">
            <Label className="text-xs font-semibold text-foreground/90 flex items-center gap-2">
              {getSettingLabel(key)}
              {secretKeys.has(key) && <Lock className="h-3 w-3 text-muted-foreground/60 shrink-0" />}
            </Label>
          </div>
          {description && <p className="text-[11px] text-muted-foreground leading-normal">{description}</p>}
        </div>
        <div className="shrink-0 self-end sm:self-center">
          {renderSettingInput(key, displayValue)}
        </div>
      </div>
    )
  }

  // ─── Sub-section renderer ─────────────────────────────────────────────────────

  const renderSubSection = (sub: SubSection) => {
    if (sub.showWhen && !sub.showWhen(settings)) return null

    const isMasterEnabled = sub.masterToggle !== undefined && settings[sub.masterToggle] !== undefined
      ? !!settings[sub.masterToggle]
      : true

    const hasMasterInSettings = sub.masterToggle !== undefined && settings[sub.masterToggle] !== undefined

    const visibleFields = sub.fields
      .filter(f => !f.showWhen || f.showWhen(settings))
      .filter(f => settings[f.key] !== undefined || f.key in MODEL_FIELD_PROVIDERS)

    if (visibleFields.length === 0 && !hasMasterInSettings) return null

    return (
      <Card key={sub.id} className="border border-border/60 shadow-sm rounded-xl overflow-hidden bg-card/80 backdrop-blur-sm">
        <CardHeader className="py-2.5 px-4 border-b border-border/40 bg-muted/15">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <CardTitle className="text-xs font-bold text-foreground/95 uppercase tracking-wide">{sub.title}</CardTitle>
              {sub.description && (
                <CardDescription className="text-[11px] text-muted-foreground font-medium mt-0.5 leading-snug">
                  {sub.description}
                </CardDescription>
              )}
            </div>
            {hasMasterInSettings && (
              <div className="flex items-center gap-2 shrink-0 pt-0.5">
                <Switch
                  checked={isMasterEnabled}
                  onCheckedChange={(v) => handleUpdateSetting(sub.masterToggle!, v)}
                />
              </div>
            )}
          </div>
        </CardHeader>
        <CardContent className={cn('p-0 divide-y divide-border/40', !isMasterEnabled && 'opacity-50 pointer-events-none')}>
          {visibleFields.length > 0 ? (
            visibleFields.map(f => renderSettingRow(f.key, settings[f.key]))
          ) : hasMasterInSettings ? (
            <div className="px-4 py-3 text-[11px] text-muted-foreground/70 font-medium text-center">
              No additional settings — feature is controlled by the toggle above
            </div>
          ) : null}
        </CardContent>
      </Card>
    )
  }

  // ─── Tab renderer ─────────────────────────────────────────────────────────────

  const renderTab = (tab: TabDef) => {
    const left: SubSection[] = []
    const right: SubSection[] = []
    let leftWeight = 0
    let rightWeight = 0

    tab.subSections.forEach((sub) => {
      if (sub.showWhen && !sub.showWhen(settings)) return
      const visibleFields = sub.fields
        .filter(f => !f.showWhen || f.showWhen(settings))
        .filter(f => settings[f.key] !== undefined || f.key in MODEL_FIELD_PROVIDERS)
      const hasMaster = sub.masterToggle !== undefined && settings[sub.masterToggle] !== undefined
      if (visibleFields.length === 0 && !hasMaster) return

      const weight = Math.max(visibleFields.length, 1) + 3
      if (leftWeight <= rightWeight) {
        left.push(sub)
        leftWeight += weight
      } else {
        right.push(sub)
        rightWeight += weight
      }
    })

    if (right.length === 0) {
      return (
        <TabsContent key={tab.id} value={tab.id} className="mt-0 animate-in fade-in duration-200">
          <div className="max-w-4xl space-y-4">
            {left.map(sub => renderSubSection(sub))}
          </div>
        </TabsContent>
      )
    }

    return (
      <TabsContent key={tab.id} value={tab.id} className="mt-0 animate-in fade-in duration-200">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
          <div className="space-y-4">
            {left.map(sub => renderSubSection(sub))}
          </div>
          <div className="space-y-4">
            {right.map(sub => renderSubSection(sub))}
          </div>
        </div>
      </TabsContent>
    )
  }

  // ─── Search ───────────────────────────────────────────────────────────────────

  const filteredSettingsKeys = useMemo(() => {
    if (!searchQuery) return null
    const query = searchQuery.toLowerCase()
    return Object.keys(settings).filter(key => {
      const label = getSettingLabel(key).toLowerCase()
      const desc = (settingDescriptions[key] || '').toLowerCase()
      return label.includes(query) || desc.includes(query)
    })
  }, [settings, searchQuery])

  // ─── Loading ──────────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-muted/50">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
          <p className="tech-label">Initializing Configuration...</p>
        </div>
      </div>
    )
  }

  // ─── Render ───────────────────────────────────────────────────────────────────

  return (
    <div className="flex min-h-full flex-col">
      <MobilePageHeader title="AI & Bot" subtitle="AI & Bot Configuration" hidden icon={<Brain className="h-5 w-5 text-primary" />} />

      <header className="hidden md:flex sticky top-0 z-40 w-full tech-header">
        <div className="max-w-[1360px] w-full mx-auto flex h-16 items-center px-6 justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-primary/10 border border-primary/20">
              <Brain className="h-5 w-5 text-primary" />
            </div>
            <div className="flex flex-col">
              <h1 className="text-base font-black text-foreground leading-none">AI & Bot</h1>
              <p className="text-[10px] text-[#6b7288] font-bold uppercase tracking-wider mt-1.5">AI & bot behavior settings</p>
            </div>
          </div>

          <div className="flex items-center gap-2.5">
            <div className="relative group hidden lg:block mr-2">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground group-focus-within:text-primary transition-colors" />
              <Input
                placeholder="Search settings..."
                className="pl-9 w-56 h-9 bg-muted/40 border-border/60 focus:bg-card focus:border-primary/40 text-xs font-semibold rounded-xl transition-all"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>

            <Button
              variant="outline" size="sm"
              onClick={() => setShowSecrets(!showSecrets)}
              className={cn(
                'h-9 px-4 text-xs font-bold rounded-xl shadow-sm transition-all active:scale-95 border-border',
                showSecrets
                  ? 'bg-amber-500/10 text-amber-400 border-amber-500/30 hover:bg-amber-500/15'
                  : 'bg-card text-muted-foreground hover:bg-muted/40 hover:text-foreground'
              )}
            >
              {showSecrets ? <EyeOff className="h-3.5 w-3.5 mr-2" /> : <Eye className="h-3.5 w-3.5 mr-2" />}
              {showSecrets ? 'Hide Secrets' : 'Show Secrets'}
            </Button>

            <Button
              variant="outline" size="sm"
              onClick={() => setShowCreateModal(true)}
              className="h-9 px-4 text-xs font-bold bg-card text-muted-foreground border-border hover:bg-muted/40 hover:text-foreground rounded-xl shadow-sm transition-all active:scale-95"
            >
              <Plus className="h-3.5 w-3.5 mr-2" />
              Add Setting
            </Button>

            <div className="relative flex flex-col items-end gap-1">
              {savedButNotReloaded && !reloading && (
                <span className="text-[10px] font-semibold text-amber-400 flex items-center gap-1.5 animate-in fade-in duration-200">
                  <span className="inline-block w-1.5 h-1.5 rounded-full bg-amber-400" />
                  Reload required
                </span>
              )}
              <Button
                variant="outline" size="sm"
                onClick={handleReloadSettings}
                disabled={reloading}
                className={cn(
                  'h-9 px-4 text-xs font-bold rounded-xl shadow-sm transition-all active:scale-95',
                  reloading
                    ? 'bg-muted/50 text-muted-foreground border-border'
                    : savedButNotReloaded
                      ? 'bg-amber-600 hover:bg-amber-500 text-white border-amber-600'
                      : 'bg-primary hover:bg-primary/90 text-primary-foreground border-primary'
                )}
              >
                {reloading ? <Loader2 className="h-3.5 w-3.5 mr-2 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5 mr-2" />}
                {reloading ? 'Reloading...' : 'Reload Bot'}
              </Button>
            </div>
          </div>
        </div>
      </header>

      <main className="flex-1 px-4 md:px-6 py-6 max-w-[1360px] mx-auto w-full">
        {searchQuery ? (
          <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-bold text-foreground/90 flex items-center gap-2">
                <Search className="h-4 w-4 text-primary" />
                Search Results ({filteredSettingsKeys?.length})
              </h2>
              <Button variant="ghost" size="sm" onClick={() => setSearchQuery('')} className="h-8 text-xs font-bold text-primary hover:bg-primary/10">
                Clear Search
              </Button>
            </div>
            <Card className="border border-border/60 shadow-sm overflow-hidden rounded-xl bg-card/80 backdrop-blur-sm">
              <CardContent className="p-0 divide-y divide-border/40">
                {filteredSettingsKeys && filteredSettingsKeys.length > 0 ? (
                  filteredSettingsKeys.map(key => renderSettingRow(key, settings[key]))
                ) : (
                  <div className="py-12 flex flex-col items-center text-center space-y-3">
                    <div className="p-4 bg-muted/50 rounded-full">
                      <Search className="h-8 w-8 text-muted-foreground/50" />
                    </div>
                    <p className="text-sm font-bold text-foreground/90">No settings found</p>
                    <p className="text-xs text-muted-foreground mt-1">Try adjusting your search terms</p>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        ) : (
          <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full space-y-6">
            <TabsList className="flex h-11 items-center justify-start bg-muted/50 md:bg-card md:border border-border p-1 rounded-2xl w-full overflow-x-auto no-scrollbar shadow-sm">
              {TAB_SCHEMA.map(tab => (
                <TabsTrigger
                  key={tab.id}
                  value={tab.id}
                  className="px-4 text-[11px] font-bold uppercase tracking-wider data-[state=active]:bg-primary/10 data-[state=active]:text-primary data-[state=active]:shadow-sm rounded-xl transition-all whitespace-nowrap"
                >
                  <span className="flex items-center gap-2">
                    {tab.icon}
                    {tab.label}
                  </span>
                </TabsTrigger>
              ))}
              {customKeys.length > 0 && (
                <TabsTrigger value="CUSTOM" className="px-4 text-[11px] font-bold uppercase tracking-wider data-[state=active]:bg-primary/10 data-[state=active]:text-primary data-[state=active]:shadow-sm rounded-xl transition-all whitespace-nowrap">
                  <span className="flex items-center gap-2">
                    <Globe className="h-4 w-4" />
                    Custom
                  </span>
                </TabsTrigger>
              )}
              <TabsTrigger value="AI_CONFIG" className="px-4 text-[11px] font-bold uppercase tracking-wider data-[state=active]:bg-primary/10 data-[state=active]:text-primary data-[state=active]:shadow-sm rounded-xl transition-all whitespace-nowrap">
                <span className="flex items-center gap-2">
                  <Activity className="h-4 w-4" />
                  AI Config
                </span>
              </TabsTrigger>
              <TabsTrigger value="SETUP_GUIDE" className="px-4 text-[11px] font-bold uppercase tracking-wider data-[state=active]:bg-primary/10 data-[state=active]:text-primary data-[state=active]:shadow-sm rounded-xl transition-all whitespace-nowrap">
                <span className="flex items-center gap-2">
                  <BookOpen className="h-4 w-4" />
                  Guide
                </span>
              </TabsTrigger>
            </TabsList>

            {/* Main tabs from schema */}
            {TAB_SCHEMA.map(tab => renderTab(tab))}

            {/* Custom settings */}
            {customKeys.length > 0 && (
              <TabsContent value="CUSTOM" className="mt-0 animate-in fade-in duration-200">
                {customKeys.length <= 4 ? (
                  <div className="max-w-4xl">
                    <Card className="border border-border/60 shadow-sm rounded-xl overflow-hidden bg-card/80 backdrop-blur-sm">
                      <CardHeader className="py-2.5 px-4 border-b border-border/40 bg-muted/15">
                        <CardTitle className="text-xs font-bold text-foreground/95 uppercase tracking-wide flex items-center gap-2">
                          <Globe className="h-4 w-4 text-primary" />
                          Custom Settings
                        </CardTitle>
                        <CardDescription className="text-[11px] text-muted-foreground font-medium mt-0.5">
                          {customKeys.length} custom parameter{customKeys.length > 1 ? 's' : ''}
                        </CardDescription>
                      </CardHeader>
                      <CardContent className="p-0 divide-y divide-border/40">
                        {customKeys.map(key => renderSettingRow(key, settings[key]))}
                      </CardContent>
                    </Card>
                  </div>
                ) : (
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
                    <Card className="border border-border/60 shadow-sm rounded-xl overflow-hidden bg-card/80 backdrop-blur-sm">
                      <CardHeader className="py-2.5 px-4 border-b border-border/40 bg-muted/15">
                        <CardTitle className="text-xs font-bold text-foreground/95 uppercase tracking-wide flex items-center gap-2">
                          <Globe className="h-4 w-4 text-primary" />
                          Custom Parameters (1)
                        </CardTitle>
                      </CardHeader>
                      <CardContent className="p-0 divide-y divide-border/40">
                        {customKeys.slice(0, Math.ceil(customKeys.length / 2)).map(key => renderSettingRow(key, settings[key]))}
                      </CardContent>
                    </Card>
                    <Card className="border border-border/60 shadow-sm rounded-xl overflow-hidden bg-card/80 backdrop-blur-sm">
                      <CardHeader className="py-2.5 px-4 border-b border-border/40 bg-muted/15">
                        <CardTitle className="text-xs font-bold text-foreground/95 uppercase tracking-wide flex items-center gap-2">
                          <Globe className="h-4 w-4 text-primary" />
                          Custom Parameters (2)
                        </CardTitle>
                      </CardHeader>
                      <CardContent className="p-0 divide-y divide-border/40">
                        {customKeys.slice(Math.ceil(customKeys.length / 2)).map(key => renderSettingRow(key, settings[key]))}
                      </CardContent>
                    </Card>
                  </div>
                )}
              </TabsContent>
            )}

            {/* AI Config panel */}
            <TabsContent value="AI_CONFIG" className="mt-0 animate-in fade-in slide-in-from-bottom-2 duration-300">
              <AIConfigPanel ref={aiConfigRef} onDirtyChange={setAiConfigDirty} />
            </TabsContent>

            {/* Setup Guide */}
            <TabsContent value="SETUP_GUIDE" className="mt-0 animate-in fade-in slide-in-from-bottom-2 duration-300">
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <div className="lg:col-span-2 space-y-6">
                  <Card className="border-0 shadow-sm rounded-3xl overflow-hidden bg-card">
                    <CardHeader className="pb-4 pt-8 px-8 border-b border-border">
                      <CardTitle className="text-xl font-black flex items-center gap-3">
                        <div className="p-2 bg-primary/10 rounded-xl text-primary"><BookOpen className="h-5 w-5" /></div>
                        Setup Guide & Documentation
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="p-8 space-y-8">
                      <section className="space-y-4">
                        <h3 className="text-sm font-black text-foreground/90 flex items-center gap-2">
                          <LayoutGrid className="h-4 w-4 text-muted-foreground/70" />
                          Operational Logic
                        </h3>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                          <div className="p-5 bg-primary/5 border border-primary/20 rounded-2xl space-y-2">
                            <div className="flex items-center gap-2 text-primary">
                              <CheckCircle2 className="h-4 w-4" />
                              <span className="text-xs font-bold uppercase tracking-wider">Pending Changes Bar</span>
                            </div>
                            <p className="text-[11px] text-muted-foreground font-medium leading-relaxed">
                              Changes are tracked in the orange bar at the bottom. Click <strong>Save All Changes</strong> to persist them to the database.
                            </p>
                          </div>
                          <div className="p-5 bg-gold/5 border border-gold/20 rounded-2xl space-y-2">
                            <div className="flex items-center gap-2 text-gold">
                              <RefreshCw className="h-4 w-4" />
                              <span className="text-xs font-bold uppercase tracking-wider">Reload Requirement</span>
                            </div>
                            <p className="text-[11px] text-muted-foreground font-medium leading-relaxed">
                              Saved settings only take effect after clicking <strong>Reload Bot</strong>. This prevents partial configurations from affecting live trading.
                            </p>
                          </div>
                        </div>
                      </section>
                      <section className="space-y-4">
                        <h3 className="text-sm font-black text-foreground/90 flex items-center gap-2">
                          <Terminal className="h-4 w-4 text-muted-foreground/70" />
                          CLI Commands
                        </h3>
                        <div className="space-y-4">
                          {[
                            { label: 'Initialize database from .env', code: 'python scripts/init_settings_from_env.py', color: 'text-emerald-600 dark:text-emerald-400' },
                            { label: 'Generate encryption key', code: 'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"', color: 'text-indigo-600 dark:text-indigo-300' },
                          ].map((item, i) => (
                            <div key={i} className="space-y-2">
                              <p className="text-[10px] font-bold text-muted-foreground/70 uppercase tracking-widest px-1">{item.label}</p>
                              <div className="group relative">
                                <code className={cn('block text-xs bg-muted p-4 rounded-2xl font-mono overflow-x-auto border-4 border-border shadow-inner', item.color)}>{item.code}</code>
                                <Button variant="ghost" size="icon" className="absolute right-2 top-2 h-7 w-7 text-muted-foreground hover:text-white hover:bg-muted" onClick={() => { navigator.clipboard.writeText(item.code); toast({ title: 'Copied', description: 'Command copied to clipboard' }) }}>
                                  <HistoryIcon className="h-3.5 w-3.5" />
                                </Button>
                              </div>
                            </div>
                          ))}
                        </div>
                      </section>
                    </CardContent>
                  </Card>
                </div>

                <div className="space-y-6">
                  <Card className="border border-border shadow-sm rounded-3xl bg-card text-foreground overflow-hidden">
                    <CardHeader className="pb-3 pt-6 px-6">
                      <CardTitle className="text-sm font-bold flex items-center gap-2">
                        <Lock className="h-4 w-4 text-primary" />
                        Security Notice
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="px-6 pb-6 space-y-4">
                      <p className="text-[11px] text-muted-foreground leading-relaxed font-medium">
                        API keys and tokens are marked with a lock icon and stored encrypted. Use <strong>Show Secrets</strong> only when needed.
                      </p>
                      <div className="p-4 bg-muted/50 border border-border rounded-2xl">
                        <p className="text-[10px] font-bold text-primary uppercase tracking-widest mb-2">Protocol</p>
                        <p className="text-[11px] text-muted-foreground leading-relaxed font-medium">
                          Core credentials (Telegram API keys, phone number) must remain in your <code className="bg-muted px-1 rounded text-foreground font-mono">.env</code> file and cannot be changed from the dashboard.
                        </p>
                      </div>
                    </CardContent>
                  </Card>

                  <Card className="border-none shadow-sm rounded-3xl bg-card overflow-hidden">
                    <CardHeader className="pb-3 pt-6 px-6 border-b border-border">
                      <CardTitle className="text-sm font-bold flex items-center gap-2">
                        <ExternalLink className="h-4 w-4 text-primary" />
                        Quick Links
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="p-4">
                      <div className="space-y-1">
                        {[
                          { label: 'Telegram BotFather',    url: 'https://t.me/BotFather',              icon: <MessagesSquare className="h-3 w-3" /> },
                          { label: 'MT5 REST API Docs',     url: 'https://github.com/v2trading/mt5rest', icon: <Terminal className="h-3 w-3" /> },
                          { label: 'DeepSeek Platform',     url: 'https://platform.deepseek.com/',       icon: <Brain className="h-3 w-3" /> },
                          { label: 'MetaAPI Dashboard',     url: 'https://metaapi.cloud/',               icon: <Globe className="h-3 w-3" /> },
                          { label: 'OpenAI Platform',       url: 'https://platform.openai.com/',         icon: <Zap className="h-3 w-3" /> },
                        ].map((link, i) => (
                          <a key={i} href={link.url} target="_blank" rel="noopener noreferrer"
                            className="flex items-center justify-between p-3 rounded-xl hover:bg-muted/50 transition-colors group">
                            <div className="flex items-center gap-3">
                              <div className="p-1.5 bg-muted rounded-lg text-muted-foreground group-hover:bg-primary/10 group-hover:text-primary transition-colors">{link.icon}</div>
                              <span className="text-[11px] font-bold text-foreground/80">{link.label}</span>
                            </div>
                            <ExternalLink className="h-3 w-3 text-muted-foreground/50 group-hover:text-muted-foreground/70" />
                          </a>
                        ))}
                      </div>
                    </CardContent>
                  </Card>
                </div>
              </div>
            </TabsContent>
          </Tabs>
        )}
      </main>

      {/* Create Setting Modal */}
      <Dialog open={showCreateModal} onOpenChange={setShowCreateModal}>
        <DialogContent className="sm:max-w-[500px]">
          <DialogHeader>
            <DialogTitle className="text-lg font-black">Add New Setting</DialogTitle>
            <DialogDescription className="text-xs">
              Create a new configuration setting. Secret values are encrypted automatically.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="setting-key" className="text-xs font-bold">Setting Key</Label>
              <Input id="setting-key" placeholder="e.g., CUSTOM_API_KEY" value={newSetting.key}
                onChange={(e) => setNewSetting({ ...newSetting, key: e.target.value.toUpperCase().replace(/\s+/g, '_') })}
                className="text-xs font-semibold" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="setting-value" className="text-xs font-bold">Value</Label>
              <Input id="setting-value" placeholder="Setting value" value={newSetting.value}
                onChange={(e) => setNewSetting({ ...newSetting, value: e.target.value })}
                className="text-xs font-semibold" />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label className="text-xs font-bold">Value Type</Label>
                <Select value={newSetting.valueType} onValueChange={(v) => setNewSetting({ ...newSetting, valueType: v })}>
                  <SelectTrigger className="text-xs font-semibold"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {['STRING', 'INT', 'FLOAT', 'BOOL', 'JSON'].map(t => <SelectItem key={t} value={t} className="text-xs">{t.charAt(0) + t.slice(1).toLowerCase()}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label className="text-xs font-bold">Category</Label>
                <Select value={newSetting.category} onValueChange={(v) => setNewSetting({ ...newSetting, category: v })}>
                  <SelectTrigger className="text-xs font-semibold"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {['TELEGRAM', 'TRADING', 'RISK_MANAGEMENT', 'AI', 'NEWS', 'MONITORING', 'APPROVAL', 'DASHBOARD', 'GENERAL'].map(c => (
                      <SelectItem key={c} value={c} className="text-xs">{c.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="space-y-2">
              <Label className="text-xs font-bold">Description</Label>
              <Input placeholder="Brief description" value={newSetting.description}
                onChange={(e) => setNewSetting({ ...newSetting, description: e.target.value })}
                className="text-xs font-semibold" />
            </div>
            <div className="flex items-center space-x-2">
              <Switch id="setting-secret" checked={newSetting.isSecret} onCheckedChange={(checked) => setNewSetting({ ...newSetting, isSecret: checked })} />
              <Label htmlFor="setting-secret" className="text-xs font-bold flex items-center gap-2">
                <Lock className="h-3 w-3" />
                Encrypt this value (API keys, tokens, passwords)
              </Label>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => { setShowCreateModal(false); setNewSetting({ key: '', value: '', valueType: 'STRING', category: 'GENERAL', description: '', isSecret: false }) }} className="text-xs font-bold">
              Cancel
            </Button>
            <Button size="sm" onClick={() => handleCreateSetting(newSetting)} disabled={!newSetting.key || !newSetting.value || !newSetting.description} className="text-xs font-bold">
              <Plus className="h-3.5 w-3.5 mr-2" />
              Create Setting
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Unsaved Changes Bar */}
      {hasPendingChanges && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 w-[92%] max-w-2xl animate-in slide-in-from-bottom-4 duration-200">
          <div className="flex items-center justify-between gap-4 px-5 py-3.5 rounded-2xl bg-card/95 backdrop-blur-xl border border-border shadow-2xl shadow-black/50">
            <div className="flex items-center gap-3 min-w-0">
              <div className="p-2 bg-amber-500/10 text-amber-400 rounded-xl border border-amber-500/20 shrink-0">
                <AlertTriangle className="h-4 w-4" />
              </div>
              <div className="min-w-0">
                <p className="text-xs font-bold text-foreground truncate">
                  {Object.keys(pendingChanges).length + (aiConfigDirty ? 1 : 0)} unsaved change{(Object.keys(pendingChanges).length + (aiConfigDirty ? 1 : 0)) !== 1 ? 's' : ''}
                </p>
                <p className="text-[11px] text-muted-foreground truncate">Unsaved changes will be lost if you navigate away</p>
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <Button variant="ghost" size="sm" onClick={handleCancelChanges} className="h-8 px-3 text-xs font-semibold text-muted-foreground hover:text-foreground">
                <XCircle className="h-3.5 w-3.5 mr-1.5" />
                Discard
              </Button>
              <Button variant="outline" size="sm" onClick={() => setShowConfirmDialog(true)} className="h-8 px-3 text-xs font-semibold border-border">
                Review
              </Button>
              <Button size="sm" onClick={handleSaveAll} disabled={savingAll} className="h-8 px-4 text-xs font-bold bg-primary text-primary-foreground hover:bg-primary/90 shadow-sm">
                {savingAll ? <><Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />Saving...</> : <><Save className="h-3.5 w-3.5 mr-1.5" />Save Changes</>}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Confirm Dialog */}
      <Dialog open={showConfirmDialog} onOpenChange={setShowConfirmDialog}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-orange-500" />
              Review Pending Changes
            </DialogTitle>
            <DialogDescription>The following settings will be updated. Please review before saving.</DialogDescription>
          </DialogHeader>
          <div className="max-h-96 overflow-y-auto space-y-3 py-4">
            {Object.entries(pendingChanges).map(([key, newValue]) => {
              const oldValue = originalSettings[key]
              return (
                <div key={key} className="border border-border rounded-lg p-4 bg-muted/50">
                  <div className="font-bold text-sm text-foreground/90 mb-2">{getSettingLabel(key)}</div>
                  <div className="grid grid-cols-2 gap-4 text-xs">
                    <div>
                      <div className="text-muted-foreground font-semibold mb-1">Current Value:</div>
                      <div className="bg-card border border-border rounded px-3 py-2 font-mono text-muted-foreground">
                        {typeof oldValue === 'boolean' ? (oldValue ? 'Enabled' : 'Disabled') : String(oldValue || 'Not set')}
                      </div>
                    </div>
                    <div>
                      <div className="text-orange-600 font-semibold mb-1">New Value:</div>
                      <div className="bg-amber-500/10 border border-amber-500/30 rounded px-3 py-2 font-mono text-amber-400 font-bold">
                        {typeof newValue === 'boolean' ? (newValue ? 'Enabled' : 'Disabled') : String(newValue)}
                      </div>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowConfirmDialog(false)} className="font-bold">Cancel</Button>
            <Button onClick={handleSaveAll} disabled={savingAll} className="bg-orange-600 hover:bg-orange-700 font-bold">
              {savingAll ? <><Loader2 className="h-4 w-4 mr-2 animate-spin" />Saving...</> : <><Save className="h-4 w-4 mr-2" />Confirm & Save All</>}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Button
        onClick={handleReloadSettings}
        disabled={reloading}
        className={cn(
          'md:hidden fixed bottom-[168px] right-4 z-30 h-12 px-5 rounded-full shadow-lg font-black text-xs',
          reloading
            ? 'bg-muted text-muted-foreground'
            : savedButNotReloaded
              ? 'bg-amber-500 text-white hover:bg-amber-600 animate-pulse-slow'
              : 'bg-blue-600 text-white hover:bg-blue-700'
        )}
      >
        {reloading ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <RefreshCw className="h-4 w-4 mr-2" />}
        {reloading ? 'Reloading...' : 'Reload Bot'}
      </Button>
    </div>
  )
}
