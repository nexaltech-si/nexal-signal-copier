// Settings types - Must match Python schema in prisma/schema.prisma and src/services/settings_service.py

export enum ValueType {
  STRING = 'STRING',
  INT = 'INT',
  FLOAT = 'FLOAT',
  BOOL = 'BOOL',
  JSON = 'JSON',
}

export enum SettingCategory {
  TELEGRAM = 'TELEGRAM',
  TRADING = 'TRADING',
  RISK_MANAGEMENT = 'RISK_MANAGEMENT',
  AI = 'AI',
  NEWS = 'NEWS',
  MONITORING = 'MONITORING',
  APPROVAL = 'APPROVAL',
  DASHBOARD = 'DASHBOARD',
  GENERAL = 'GENERAL',
}

export interface Setting {
  id: string;
  key: string;
  value: string;
  valueType: ValueType;
  category: SettingCategory;
  description: string | null;
  isSecret: boolean;
  updatedAt: string;
  createdAt: string;
  parsedValue?: any; // Parsed value based on valueType
}

export interface SettingUpdateRequest {
  key: string;
  value: any;
}

export interface SettingsGroup {
  category: SettingCategory;
  settings: Setting[];
}

export interface ReloadSettingsResponse {
  success: boolean;
  message: string;
}

// Phase 1: Risk Management Settings
export interface RiskManagementSettings {
  max_risk_per_trade_percent: number;
  max_open_positions: number;
  default_stop_loss_pips: number;
  default_take_profit_pips: number;
  risk_reward_ratio: number;
  spread_adjustment_multiplier: number;
  enable_equity_protection: boolean;
  daily_drawdown_limit_percent: number;
  overall_drawdown_limit_percent: number;
  enable_drawdown_monitoring: boolean;
}

// Phase 2: Trading Settings
export interface TradingSettings {
  min_lot_size: number;
  max_lot_size: number;
  slippage_pips: number;
  max_signal_age_minutes: number;
  enable_instant_execution: boolean;
  instant_execution_channels: string[];
  instant_execution_keywords: string[];
  instant_execution_max_deviation_pips: number;
  instant_one_leg_max_tp1_progress: number;
  instant_temp_sl_pips: number;
  instant_first_entry_risk_share: number;
  signal_continuity_window_minutes: number;
  same_level_tolerance_pips: number;
}

// Phase 3: Auto TP/Trailing/Breakeven
export interface AutoTpSettings {
  enable_auto_take_profit: boolean;
  auto_tp_calculation_method: 'PIPS' | 'RR';
  auto_tp_pips: number;
  auto_tp_risk_reward: number;
}

export interface TrailingStopSettings {
  enable_trailing_stop: boolean;
  trailing_stop_calculation_method: 'PIPS' | 'RR';
  trailing_stop_distance_pips: number;
  trailing_stop_distance_rr: number;
  trailing_activation_method: 'PROFIT_PIPS' | 'PROFIT_RR' | 'PARTIAL_TP';
  trailing_activation_profit_pips: number;
  trailing_activation_profit_rr: number;
}

export interface BreakevenSettings {
  enable_breakeven_move: boolean;
  breakeven_trigger_method: 'AFTER_PARTIAL' | 'PROFIT_PIPS';
  breakeven_trigger_pips: number;
  breakeven_buffer_pips: number;
}

export interface AutoPartialSettings {
  enable_auto_partial: boolean;
  auto_partial_calculation_method: 'PIPS' | 'RR';
  auto_partial_trigger_pips: number;
  auto_partial_trigger_rr: number;
  auto_partial_close_percent: number;
}

// Phase 4: Approval Settings
export interface ApprovalSettings {
  require_manual_approval: boolean;
  approval_required_channels: string[];
  approval_timeout_minutes: number;
}

// Phase 5: Channel Management
export interface ChannelSettings {
  telegram_channel_id: string[];
  telegram_notification_chat_id: string;
}
