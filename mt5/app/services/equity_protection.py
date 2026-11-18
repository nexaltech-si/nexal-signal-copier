import logging
import json
import os
import tempfile
import shutil
import MetaTrader5 as mt5
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple, List, Set
import pytz
import threading
import time
from lib import (
    close_all_positions, close_all_orders,
    close_buy_positions, close_sell_positions,
    close_all_profitable_positions, close_losing_positions,
    close_positions_by_symbol
)
# NOTE: Equity protection intentionally does NOT use the MT5 cache.
# Drawdown checks must read fresh account_info on every heartbeat tick so
# protection cannot trigger on stale data.

logger = logging.getLogger(__name__)

# The "trading day" used for daily-drawdown resets. Default 0 = the container's local date. Prop firms reset at
# a broker/server-time boundary, so `day_offset_hours` (protection config, editable on the dashboard Account page,
# applied without a restart) shifts it, e.g. 3 when broker midnight is 03:00 on the container clock.
# PROTECTION_DAY_OFFSET_HOURS in the environment is only the initial default; the saved config wins.
try:
    PROTECTION_DAY_OFFSET_HOURS = float(os.getenv("PROTECTION_DAY_OFFSET_HOURS", "0") or 0)
except ValueError:
    PROTECTION_DAY_OFFSET_HOURS = 0.0


def set_day_offset_hours(hours: float) -> None:
    global PROTECTION_DAY_OFFSET_HOURS
    PROTECTION_DAY_OFFSET_HOURS = max(-14.0, min(14.0, float(hours)))


def _today_date():
    return (datetime.now() + timedelta(hours=PROTECTION_DAY_OFFSET_HOURS)).date()


def _today_str() -> str:
    return _today_date().strftime('%Y-%m-%d')


class EquityProtection:
    ALLOWED_ACTIONS = ('close_all', 'notify_only', 'close_losers_only', 'close_losing', 'close_profitable')

    def __init__(self, socketio):
        self.socketio = socketio
        self.config_schema = None  # Store schema reference if present
        
        # Configuration file (use separate mount for equity protection)
        self.config_file = "/protection_config/protection_config.json"
        
        # Lock for thread safety
        self.lock = threading.Lock()
        
        # Thread control
        self.running = False
        self.monitor_thread = None
        self.heartbeat_thread = None
        
        # Load configuration from JSON file
        self.load_config()
        
        # File to store historical data (use protection_config directory)
        self.history_file = "/protection_config/equity_history.json"
        
        # State tracking
        self.est_tz = pytz.timezone('US/Eastern')
        self.last_check_date = None
        self.trading_blocked_accounts = set()  # Track blocked accounts by account number
        self.daily_high_equity = 0
        self.daily_starting_balance = 0
        self.daily_starting_equity = 0
        self.historical_peak = 0
        self.historical_peak_equity = 0
        self.historical_peak_balance = 0
        
        # For backwards compatibility - this will be set based on current account
        self.trading_blocked = False  
        
        # Track notifications per account to prevent looping messages
        self.notification_sent_accounts = set()
        self.last_notification_reasons = {}  # Map account numbers to reasons
        
        # Create data directory if it doesn't exist
        os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
        
        # Current account tracking
        self.current_account = None
        
        # Track last saved values to avoid unnecessary writes
        self.last_saved_equity = 0
        self.last_saved_balance = 0
        self.last_save_time = datetime.now()
        self.save_interval = 5.0  # Minimum seconds between history saves
        
        # WebSocket throttling
        self.last_ws_update_time = datetime.now()
        self.ws_update_interval = 2.0  # Minimum seconds between updates if no change
        self.last_ws_equity = 0
        self.last_ws_balance = 0
        self.last_history_load_time = datetime.now() - timedelta(minutes=1)  # Force first load
        
        # Track orders/positions being processed to prevent duplicate cancellations
        self.orders_being_processed = set()
        self.last_order_check_time = datetime.now()
        self.order_check_interval = 1.0  # seconds
        
        # Guard to prevent redundant liquidation runs
        self.is_liquidating = False
        self.last_liquidation_time = None
        
        # Connection state tracking
        self.mt5_connected = False
        
        # Load historical data
        self.load_historical_data()
        
        # Auto-start monitoring if enabled in config
        if self.running:
            logger.info("Protection enabled in config, starting monitoring...")
            self.start()
        
        # Log initialization with settings
        logger.info(f"Equity protection initialized with: "
                    f"max_daily_loss_pct={self.max_daily_loss_pct}%, "
                    f"max_total_drawdown_pct={self.max_total_drawdown_pct}%, "
                    f"protection_mode={self.protection_mode}, "
                    f"verbose_logging={self.verbose_logging}")
    
    def load_config(self) -> None:
        """Load protection configuration from JSON file."""
        # 1. Start with defaults to ensure variables are always initialized
        config = {
            "max_daily_loss_pct": 1.0,
            "max_total_drawdown_pct": 5.0,
            "max_daily_loss_abs": 0.0,
            "max_total_drawdown_abs": 0.0,
            "min_margin_level_pct": 0.0,
            "protection_mode": "equity",
            "action": "close_all",
            "heartbeat_interval": 0.1,
            "order_check_interval": 1.0,
            "ws_update_interval": 2.0,
            "auto_reset_daily": False,
            "verbose_logging": True,
            "enabled": False,
            "day_offset_hours": PROTECTION_DAY_OFFSET_HOURS,
        }

        # 2. Try to load from file
        try:
            if os.path.exists(self.config_file) and os.path.getsize(self.config_file) > 0:
                with self.lock:
                    with open(self.config_file, 'r', encoding='utf-8') as f:
                        file_config = json.load(f)
                        self.config_schema = file_config.get('$schema')
                        config.update(file_config)
        except json.JSONDecodeError as je:
            logger.error(f"Config file {self.config_file} is not a valid JSON: {je}. Using defaults.")
        except Exception as e:
            logger.error(f"Error reading config file: {e}")

        # 3. Always set instance variables (either defaults or from file)
        try:
            self.max_daily_loss_pct = float(config["max_daily_loss_pct"])
            self.max_total_drawdown_pct = float(config["max_total_drawdown_pct"])
            self.max_daily_loss_abs = float(config.get("max_daily_loss_abs", 0.0))
            self.max_total_drawdown_abs = float(config.get("max_total_drawdown_abs", 0.0))
            self.min_margin_level_pct = float(config.get("min_margin_level_pct", 0.0))
            self.protection_mode = config["protection_mode"]
            self.action = config.get("action", "close_all")
            self.heartbeat_interval = float(config.get("heartbeat_interval", 0.1))
            self.order_check_interval = float(config.get("order_check_interval", 1.0))
            self.ws_update_interval = float(config.get("ws_update_interval", 2.0))
            self.auto_reset_daily = bool(config.get("auto_reset_daily", False))
            self.verbose_logging = bool(config["verbose_logging"])
            self.running = bool(config["enabled"])
            self.day_offset_hours = float(config.get("day_offset_hours", PROTECTION_DAY_OFFSET_HOURS))
            set_day_offset_hours(self.day_offset_hours)
        except Exception as e:
            logger.error(f"Error assigning config variables: {e}")
            # Fallback for critical variables if assignment failed
            if not hasattr(self, 'max_daily_loss_pct'): self.max_daily_loss_pct = 1.0
            if not hasattr(self, 'max_total_drawdown_pct'): self.max_total_drawdown_pct = 5.0
            if not hasattr(self, 'protection_mode'): self.protection_mode = "equity"
            if not hasattr(self, 'verbose_logging'): self.verbose_logging = True
            if not hasattr(self, 'running'): self.running = False
    
    def save_config(self) -> None:
        """Save current protection configuration to JSON file (atomic replace)."""
        try:
            # Read existing config to preserve comments and extra fields
            existing_config = {}
            try:
                if os.path.exists(self.config_file) and os.path.getsize(self.config_file) > 0:
                    with open(self.config_file, 'r', encoding='utf-8') as f:
                        existing_config = json.load(f)
            except Exception as e:
                logger.warning(f"Could not read existing config for comment preservation: {e}")
            
            # Update only the actual config values, preserving comments and other fields
            config = existing_config.copy() if existing_config else {}
            config.update({
                "max_daily_loss_pct": self.max_daily_loss_pct,
                "max_total_drawdown_pct": self.max_total_drawdown_pct,
                "max_daily_loss_abs": self.max_daily_loss_abs,
                "max_total_drawdown_abs": self.max_total_drawdown_abs,
                "min_margin_level_pct": self.min_margin_level_pct,
                "protection_mode": self.protection_mode,
                "action": self.action,
                "heartbeat_interval": self.heartbeat_interval,
                "order_check_interval": self.order_check_interval,
                "ws_update_interval": self.ws_update_interval,
                "auto_reset_daily": self.auto_reset_daily,
                "verbose_logging": self.verbose_logging,
                "enabled": self.running,
                "day_offset_hours": getattr(self, "day_offset_hours", PROTECTION_DAY_OFFSET_HOURS),
            })

            with self.lock:
                cfg_dir = os.path.dirname(self.config_file) or "."
                os.makedirs(cfg_dir, exist_ok=True)
                fd, temp_path = tempfile.mkstemp(dir=cfg_dir, prefix="protection_config_", suffix=".tmp")
                try:
                    with os.fdopen(fd, 'w', encoding='utf-8') as f:
                        json.dump(config, f, indent=2)
                    shutil.move(os.path.abspath(temp_path), os.path.abspath(self.config_file))
                except Exception:
                    if os.path.exists(temp_path):
                        try:
                            os.remove(temp_path)
                        except Exception:
                            pass
                    raise

            logger.info(f"Configuration saved to {self.config_file}")
        except Exception as e:
            logger.error(f"Error saving config: {e}")
    
    def _read_history_file(self) -> Dict:
        """Read the history file with locking and error handling."""
        if not os.path.exists(self.history_file):
            return {"accounts": {}, "blocked_accounts": [], "notification_sent_accounts": [], "notification_reasons": {}}
        
        with self.lock:
            try:
                if os.path.getsize(self.history_file) == 0:
                    return {"accounts": {}, "blocked_accounts": [], "notification_sent_accounts": [], "notification_reasons": {}}
                    
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, Exception) as e:
                logger.error(f"Error reading history file {self.history_file}: {e}")
                raise

    def _write_history_file(self, data: Dict) -> None:
        """Write the history file atomically using a temporary file and locking."""
        with self.lock:
            temp_path = None
            try:
                # Ensure directory exists
                os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
                
                # Use tempfile to create a secure temporary file
                fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(self.history_file), prefix="equity_history_", suffix=".tmp")
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2)
                
                # Use abspath to ensure consistent path format for Wine
                abs_history_path = os.path.abspath(self.history_file)
                abs_temp_path = os.path.abspath(temp_path)
                
                # Atomic replace using shutil.move (more resilient under Wine/Docker)
                shutil.move(abs_temp_path, abs_history_path)
            except Exception as e:
                logger.error(f"Error writing history file {self.history_file}: {e}")
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass
                raise
    
    def log_info(self, message):
        """Conditionally log info messages based on verbose_logging setting"""
        if self.verbose_logging:
            logger.info(message)
    
    def load_historical_data(self) -> None:
        """Load historical equity and balance data for all accounts."""
        try:
            logger.info(f"Attempting to load historical data from: {self.history_file}")
            data = self._read_history_file()
            
            # Load blocked accounts
            self.trading_blocked_accounts = set(data.get('blocked_accounts', []))
            self.notification_sent_accounts = set(data.get('notification_sent_accounts', []))
            self.last_notification_reasons = data.get('notification_reasons', {})
            
            logger.info(f"Loaded historical data with {len(self.trading_blocked_accounts)} blocked accounts")
        except Exception as e:
            logger.error(f"Failed to load historical data: {e}. Starting with empty state but NOT overwriting file.")
            # We don't call save_base_data here to prevent overwriting potentially salvageable data
            self.trading_blocked_accounts = set()
            self.notification_sent_accounts = set()
            self.last_notification_reasons = {}
    
    def save_base_data(self) -> None:
        """Save base data structure while preserving account information."""
        try:
            # Try to load existing data to preserve account history
            existing_data = {}
            try:
                existing_data = self._read_history_file()
            except Exception as e:
                logger.error(f"Could not read existing data in save_base_data: {e}. Aborting to prevent data loss.")
                return
            
            # Use the existing accounts data but update the other fields
            data = {
                'accounts': existing_data.get('accounts', {}),
                'blocked_accounts': list(self.trading_blocked_accounts),
                'notification_sent_accounts': list(self.notification_sent_accounts),
                'notification_reasons': self.last_notification_reasons
            }
            
            self._write_history_file(data)
            logger.info(f"Saved base data while preserving {len(data['accounts'])} account histories")
            
        except Exception as e:
            logger.error(f"Error saving base data: {e}")

    def _load_account_data(self, account_number: str) -> None:
        """Load specific account data from history file into memory."""
        try:
            self.last_history_load_time = datetime.now()
            data = self._read_history_file()
            
            if 'accounts' in data and account_number in data['accounts']:
                acc_data = data['accounts'][account_number]
                
                # Load peaks
                self.historical_peak_equity = acc_data.get('peak_equity', 0)
                self.historical_peak_balance = acc_data.get('peak_balance', 0)
                self.historical_peak = self.historical_peak_equity if self.protection_mode == 'equity' else self.historical_peak_balance
                
                # Load daily starting values
                today = _today_str()
                if 'daily' in acc_data and today in acc_data['daily']:
                    daily = acc_data['daily'][today]
                    self.daily_starting_balance = daily.get('starting_balance', 0)
                    self.daily_starting_equity = daily.get('starting_equity', 0)
                    self.daily_high_equity = daily.get('high_equity', 0)
                    logger.info(f"Loaded today's data for {account_number}: Start Balance=${self.daily_starting_balance}")
                else:
                    # Reset daily values if today is not in history
                    self.daily_starting_balance = 0
                    self.daily_starting_equity = 0
                    self.daily_high_equity = 0
                    logger.info(f"No data for today ({today}) found in history for account {account_number}")
                
                logger.info(f"Memory populated for account {account_number}: Peak {self.protection_mode}=${self.historical_peak}")
        except Exception as e:
            logger.error(f"Error loading account data: {e}")
    
    def update_current_account(self, _account_info=None) -> bool:
        """Update the current MT5 account and return True if successful.
        
        Pass a pre-fetched account_info via _account_info to avoid a duplicate
        MT5 API call when the caller already has the data.
        """
        try:
            account_info = _account_info if _account_info is not None else mt5.account_info()
            if account_info is None:
                # Log periodically to avoid spamming
                now = time.time()
                if not hasattr(self, '_last_account_info_error_time') or now - self._last_account_info_error_time > 60:
                    logger.warning("Could not retrieve account info from MT5. Heartbeat will skip protection check.")
                    self._last_account_info_error_time = now
                return False
                
            new_account = str(account_info.login)
            
            # If account changed or was not set, load its data
            if new_account != self.current_account:
                logger.info(f"Account switched/initialized: {self.current_account} -> {new_account}")
                self.current_account = new_account
                self.trading_blocked = self.current_account in self.trading_blocked_accounts
                self._load_account_data(self.current_account)
            
            return True
        except Exception as e:
            logger.error(f"Error updating current account: {e}")
            return False
    
    def should_update_history(self, account_info) -> bool:
        """Determine if the history file needs updating based on value changes and time throttling.
        
        Peaks (new all-time highs) bypass the throttle — they must be persisted immediately
        so a crash/restart does not lose the reference point for drawdown calculations.
        """
        # 1. Always save immediately when a new peak is hit (safety-critical)
        if account_info.equity > self.historical_peak_equity:
            return True
        if account_info.balance > self.historical_peak_balance:
            return True

        # 2. Throttle non-peak updates to reduce file I/O
        time_since_last_save = (datetime.now() - self.last_save_time).total_seconds()
        if time_since_last_save < self.save_interval:
            return False

        # 3. Update if equity or balance has changed by more than 0.01
        equity_change = abs(account_info.equity - self.last_saved_equity)
        balance_change = abs(account_info.balance - self.last_saved_balance)
        
        return (equity_change >= 0.01 or balance_change >= 0.01)
    
    def save_historical_data(self, account_info) -> None:
        """Save current equity and balance data to history file."""
        try:
            # Get the current account number
            account_number = str(account_info.login)
            
            # Check if we need to update the history file
            if not self.should_update_history(account_info):
                return
            
            # Load structure
            try:
                data = self._read_history_file()
            except Exception as e:
                logger.error(f"Error reading history file in save_historical_data: {e}. Aborting save.")
                return
            
            # Initialize sections if they don't exist
            if 'accounts' not in data:
                data['accounts'] = {}
            if account_number not in data['accounts']:
                data['accounts'][account_number] = {
                    'peak_equity': 0,
                    'peak_balance': 0,
                    'daily': {}
                }
                
            # Update blocked accounts
            data['blocked_accounts'] = list(self.trading_blocked_accounts)
            data['notification_sent_accounts'] = list(self.notification_sent_accounts)
            data['notification_reasons'] = self.last_notification_reasons
            
            # Update peak values for this account
            account_data = data['accounts'][account_number]
            if account_info.equity > account_data.get('peak_equity', 0):
                account_data['peak_equity'] = account_info.equity
            if account_info.balance > account_data.get('peak_balance', 0):
                account_data['peak_balance'] = account_info.balance
            
            # Update daily values
            today = _today_str()
            if today not in account_data['daily']:
                account_data['daily'][today] = {
                    'starting_balance': account_info.balance,
                    'starting_equity': account_info.equity,
                    'high_equity': account_info.equity
                }
            else:
                # Update high equity if current is higher
                current_high = account_data['daily'][today].get('high_equity', 0)
                # Ensure high_equity is at least the starting_equity
                start_equity = account_data['daily'][today].get('starting_equity', account_info.equity)
                if account_info.equity > current_high:
                    account_data['daily'][today]['high_equity'] = account_info.equity
                if account_data['daily'][today]['high_equity'] < start_equity:
                    account_data['daily'][today]['high_equity'] = start_equity
            
            # Save to file atomically
            try:
                self._write_history_file(data)
                
                # Update instance variables for the current account
                self.historical_peak_equity = account_data['peak_equity']
                self.historical_peak_balance = account_data['peak_balance']
                
                if self.protection_mode == 'equity':
                    self.historical_peak = self.historical_peak_equity
                else:
                    self.historical_peak = self.historical_peak_balance
                    
                # Update daily values for the current account
                daily_data = account_data['daily'][today]
                self.daily_starting_balance = daily_data['starting_balance']
                self.daily_starting_equity = daily_data['starting_equity']
                self.daily_high_equity = daily_data['high_equity']
                
                # Update last saved values
                self.last_saved_equity = account_info.equity
                self.last_saved_balance = account_info.balance
                self.last_save_time = datetime.now()
                
                self.log_info(f"Saved historical data for account {account_number}: Peak {self.protection_mode}: {self.historical_peak}")
            except Exception as e:
                logger.error(f"Error writing to history file: {e}")
        except Exception as e:
            logger.error(f"Error saving historical data: {e}")
    
    def check_daily_reset(self, account_info) -> bool:
        """Check if we need to reset for a new trading day."""
        current_date = _today_date()
        today_str = current_date.strftime('%Y-%m-%d')
        
        # If this is the first check or a new day
        if self.last_check_date is None or current_date > self.last_check_date:
            logger.info(f"Daily reset check triggered: current_date={current_date}, last_check_date={self.last_check_date}")
            self.last_check_date = current_date
            
            # Reset notifications
            self.notification_sent_accounts = set()
            
            # If auto_reset_daily is enabled, unblock all accounts
            if self.auto_reset_daily:
                logger.info(f"Auto-reset daily enabled. Unblocking all {len(self.trading_blocked_accounts)} accounts.")
                self.trading_blocked_accounts = set()
                self.last_notification_reasons = {}
                self.save_base_data()
            
            # Ensure today's entry exists in the file and memory
            if account_info:
                self._initialize_daily_data(str(account_info.login), account_info, today_str)
            
            logger.info(f"New trading day detected: {current_date}. Reset notification flags.")
            return True
        
        return False

    def _initialize_daily_data(self, account_number: str, account_info, today_str: str) -> None:
        """Initialize daily data for a new day in both file and memory."""
        try:
            data = self._read_history_file()
            
            if 'accounts' not in data: data['accounts'] = {}
            if account_number not in data['accounts']:
                data['accounts'][account_number] = {
                    'peak_equity': account_info.equity, 
                    'peak_balance': account_info.balance, 
                    'daily': {}
                }
            
            acc_data = data['accounts'][account_number]
            if 'daily' not in acc_data: acc_data['daily'] = {}
            
            # Only set if not already present (preserve if service restarted on same day)
            if today_str not in acc_data['daily']:
                logger.info(f"Initializing new daily record for {account_number} on {today_str}")
                acc_data['daily'][today_str] = {
                    'starting_balance': account_info.balance,
                    'starting_equity': account_info.equity,
                    'high_equity': account_info.equity
                }
                
                # Update memory immediately
                self.daily_starting_balance = account_info.balance
                self.daily_starting_equity = account_info.equity
                self.daily_high_equity = account_info.equity
                
                # Save immediately while still holding the lock (handled inside _write_history_file)
                self._write_history_file(data)
            else:
                # If already in file, just ensure memory is synced
                daily = acc_data['daily'][today_str]
                self.daily_starting_balance = daily.get('starting_balance', account_info.balance)
                self.daily_starting_equity = daily.get('starting_equity', account_info.equity)
                # Ensure high_equity is at least the starting_equity
                self.daily_high_equity = max(daily.get('high_equity', account_info.equity), self.daily_starting_equity)

        except Exception as e:
            logger.error(f"Error initializing daily data: {e}")
    
    def is_trading_blocked(self, account_number=None) -> bool:
        """Check if trading is blocked for the specified or current account."""
        if account_number is None:
            # Use current account if none specified
            if self.current_account is None:
                self.update_current_account()
            account_number = self.current_account
        
        is_blocked = account_number in self.trading_blocked_accounts if account_number else False
        
        # For backwards compatibility - update the legacy flag
        if account_number == self.current_account:
            self.trading_blocked = is_blocked
            
        return is_blocked
    
    def block_trading(self, account_number, reason) -> None:
        """Block trading for the specified account."""
        with self.lock:
            self.trading_blocked_accounts.add(account_number)
            self.last_notification_reasons[account_number] = reason

            # Update the legacy flag if this is the current account
            if account_number == self.current_account:
                self.trading_blocked = True

        # Save outside the lock to avoid deadlock (_read_history_file also acquires self.lock)
        self.save_base_data()

        logger.warning(f"Trading blocked for account {account_number}: {reason}")

        # Broadcast via websocket
        self._broadcast_account_blocked(account_number, reason)
    
    def unblock_trading(self, account_number=None) -> bool:
        """Manually unblock trading for an account."""
        did_unblock = False
        with self.lock:
            if account_number is None:
                # Use current account if none specified
                if self.current_account is None:
                    self.update_current_account()
                account_number = self.current_account

            if account_number in self.trading_blocked_accounts:
                self.trading_blocked_accounts.remove(account_number)
                if account_number in self.last_notification_reasons:
                    del self.last_notification_reasons[account_number]
                if account_number in self.notification_sent_accounts:
                    self.notification_sent_accounts.remove(account_number)

                # Update the legacy flag if this is the current account
                if account_number == self.current_account:
                    self.trading_blocked = False

                did_unblock = True

        if did_unblock:
            # Save outside the lock to avoid deadlock (_read_history_file also acquires self.lock)
            self.save_base_data()
            logger.info(f"Trading unblocked for account {account_number}")

            # Broadcast via websocket
            self._broadcast_account_unblocked(account_number)
            return True
        return False
    
    def set_verbose_logging(self, enabled: bool) -> None:
        """Enable or disable verbose logging"""
        self.verbose_logging = enabled
        self.save_config()
        logger.info(f"Verbose logging {'enabled' if enabled else 'disabled'}")
    
    def check_equity_protection(self, _account_info=None) -> Tuple[bool, Optional[str]]:
        """
        Check if equity protection should be triggered for the current account.
        
        Pass a pre-fetched account_info via _account_info to avoid duplicate MT5 calls.
        
        Returns:
            Tuple[bool, Optional[str]]: (trading_should_continue, reason_if_stopped)
        """
        try:
            # Update current account (reuses pre-fetched account_info)
            if not self.update_current_account(_account_info=_account_info):
                return True, None  # Continue if we can't get account info
            
            # Use pre-fetched or fetch now
            account_info = _account_info if _account_info is not None else mt5.account_info()
            if account_info is None:
                logger.error("Could not retrieve account info")
                return True, None  # Continue trading if we can't get info
            
            account_number = str(account_info.login)
            
            # Check for new day and initialize if needed - MUST HAPPEN BEFORE BLOCK CHECK for auto-unblock
            self.check_daily_reset(account_info)
            
            # Check if this account is already blocked
            if self.is_trading_blocked(account_number):
                reason = self.last_notification_reasons.get(account_number, "Trading blocked by equity protection")
                return False, reason
            
            # If instance variables are still 0 (e.g. first run of the day), force initialization
            if self.daily_starting_balance == 0:
                self._initialize_daily_data(account_number, account_info, _today_str())

            # Save historical data (this will update high water marks)
            self.save_historical_data(account_info)
            
            # Determine reference values based on protection mode
            if self.protection_mode == 'equity':
                # Daily drawdown from today's starting equity
                daily_reference = self.daily_starting_equity
                daily_current = account_info.equity
                
                # Total drawdown from peak equity
                reference_value = self.historical_peak
                current_value = account_info.equity
            else:  # 'balance' mode
                # Daily drawdown from today's starting balance
                daily_reference = self.daily_starting_balance
                daily_current = account_info.balance
                
                # Total drawdown from peak balance
                reference_value = self.historical_peak
                current_value = account_info.balance
            
            # Calculate percentage drawdowns
            daily_drawdown_pct = 0
            if daily_reference > 0:
                daily_drawdown_pct = (daily_reference - daily_current) / daily_reference * 100
            
            total_drawdown_pct = 0
            if reference_value > 0:
                total_drawdown_pct = (reference_value - current_value) / reference_value * 100
            
            self.log_info(f"Account {account_number} equity protection check: Daily drawdown: {daily_drawdown_pct:.2f}%, Total drawdown: {total_drawdown_pct:.2f}%")
            
            # Check if we need to trigger protection
            if daily_drawdown_pct >= self.max_daily_loss_pct:
                reason = f"Daily {self.protection_mode} drawdown of {daily_drawdown_pct:.2f}% exceeded limit of {self.max_daily_loss_pct}%"
                self.block_trading(account_number, reason)
                logger.warning(reason)
                return False, reason

            # Check absolute daily drawdown
            daily_drawdown_abs = daily_reference - daily_current
            if self.max_daily_loss_abs > 0 and daily_drawdown_abs >= self.max_daily_loss_abs:
                reason = f"Daily {self.protection_mode} loss of ${daily_drawdown_abs:.2f} exceeded absolute limit of ${self.max_daily_loss_abs:.2f}"
                self.block_trading(account_number, reason)
                logger.warning(reason)
                return False, reason
                
            if total_drawdown_pct >= self.max_total_drawdown_pct:
                reason = f"Total {self.protection_mode} drawdown of {total_drawdown_pct:.2f}% exceeded limit of {self.max_total_drawdown_pct}%"
                self.block_trading(account_number, reason)
                logger.warning(reason)
                return False, reason

            # Check absolute total drawdown
            total_drawdown_abs = reference_value - current_value
            if self.max_total_drawdown_abs > 0 and total_drawdown_abs >= self.max_total_drawdown_abs:
                reason = f"Total {self.protection_mode} loss of ${total_drawdown_abs:.2f} exceeded absolute limit of ${self.max_total_drawdown_abs:.2f}"
                self.block_trading(account_number, reason)
                logger.warning(reason)
                return False, reason
            
            # Margin Level Protection
            if self.min_margin_level_pct > 0:
                margin_level = getattr(account_info, 'margin_level', 0)
                if margin_level > 0 and margin_level <= self.min_margin_level_pct:
                    reason = f"Margin level of {margin_level:.2f}% dropped below threshold of {self.min_margin_level_pct}%"
                    self.block_trading(account_number, reason)
                    logger.warning(reason)
                    return False, reason
            
            # All checks passed
            return True, None
            
        except Exception as e:
            logger.error(f"Error in equity protection check: {e}")
            return True, None  # Continue trading on error
    
    def monitor_equity(self):
        """Main monitoring loop for equity protection with permanent heartbeat mechanism."""
        # Start the permanent heartbeat thread
        self.heartbeat_thread = threading.Thread(target=self._heartbeat_protection, daemon=True)
        self.heartbeat_thread.start()
        
        # Main monitoring loop (still needed for periodic checks and notifications)
        while self.running:
            try:
                # Skip if MT5 is not connected (use same logic as heartbeat)
                term = mt5.terminal_info()
                if not term or not term.connected:
                    # Only log periodically to avoid spam
                    now = time.time()
                    if not hasattr(self, '_last_monitor_mt5_warn') or now - self._last_monitor_mt5_warn > 60:
                        logger.warning("MT5 not connected in monitor loop, skipping")
                        self._last_monitor_mt5_warn = now
                    time.sleep(5)
                    continue
                
                # Update current account
                if not self.update_current_account():
                    time.sleep(5)
                    continue
                    
                account_number = self.current_account
                
                # Send status updates every minute
                # The actual protection will be handled by the heartbeat thread
                time.sleep(60)  # Sleep for a minute before next update
                
            except Exception as e:
                logger.error(f"Error in equity protection monitor main loop: {e}")
                time.sleep(30)

    def _heartbeat_protection(self):
        """Permanent heartbeat task that continuously monitors positions and protects the account."""
        # Exponential backoff state for MT5 reconnection
        reconnect_delay = 1.0
        reconnect_max = 60.0
        last_reconnect_attempt = 0.0

        while self.running:
            try:
                # Ensure MT5 is initialized and connected (with exponential backoff)
                term = mt5.terminal_info()
                if not term:
                    now_ts = time.time()
                    if now_ts - last_reconnect_attempt >= reconnect_delay:
                        last_reconnect_attempt = now_ts
                        try:
                            # Use the session manager so we re-login with the stored
                            # broker credentials (set via /mt5/login or env vars).
                            from services.mt5_session import reconnect as _mt5_reconnect
                            ok = _mt5_reconnect()
                            if ok:
                                logger.info("MT5 re-initialized after disconnect")
                                reconnect_delay = 1.0
                            else:
                                ec, es = mt5.last_error()
                                logger.warning(
                                    "MT5 reconnect failed (code=%s, msg=%s). Next attempt in %.1fs",
                                    ec, es, reconnect_delay,
                                )
                                reconnect_delay = min(reconnect_delay * 2, reconnect_max)
                        except Exception as e:
                            logger.error("MT5 reconnect raised: %s", e)
                            reconnect_delay = min(reconnect_delay * 2, reconnect_max)
                    term = mt5.terminal_info()

                is_connected = bool(term and term.connected)

                # Broadcast connection status changes
                if is_connected != self.mt5_connected:
                    self.mt5_connected = is_connected
                    self._broadcast_connection_status(is_connected)
                    logger.info(f"MT5 Connection Status Changed: {'Connected' if is_connected else 'Disconnected'}")
                    if is_connected:
                        reconnect_delay = 1.0  # reset backoff once link is healthy

                if not is_connected:
                    # Sleep at least the heartbeat interval, but never faster than backoff
                    time.sleep(max(self.heartbeat_interval, 1.0))
                    continue
                
                # ── Single MT5 account_info() call per heartbeat ─────────────────
                # All downstream methods (update_current_account, check_equity_protection,
                # _handle_realtime_broadcast) reuse this one result instead of hammering
                # the Wine/MT5 bridge with redundant calls.
                account_info = mt5.account_info()
                if account_info is None:
                    time.sleep(self.heartbeat_interval)
                    continue

                account_number = str(account_info.login)

                # Update current account (reuses account_info)
                self.update_current_account(_account_info=account_info)

                # Check for new day and initialize daily records
                self.check_daily_reset(account_info)

                # Ensure daily data is initialized (critical for daily record tracking)
                today_str = _today_str()
                if self.daily_starting_balance == 0:
                    self._initialize_daily_data(account_number, account_info, today_str)

                # Check equity protection (reuses account_info)
                should_continue, reason = self.check_equity_protection(_account_info=account_info)

                # Periodic heartbeat log (every 5 minutes)
                now = time.time()
                if not hasattr(self, '_last_heartbeat_log_time') or now - self._last_heartbeat_log_time > 300:
                    logger.info(f"Heartbeat alive for account {account_number}. Protection mode: {self.protection_mode}, Action: {self.action}")
                    self._last_heartbeat_log_time = now

                # Real-time WebSocket Updates (reuses account_info)
                self._handle_realtime_broadcast(_account_info=account_info)
                
                liquidation_summary = ""
                if not should_continue and account_number not in self.notification_sent_accounts:
                    # Check if there are any positions or orders before closing
                    positions = mt5.positions_get()
                    orders = mt5.orders_get()
                    positions_before = len(positions) if positions else 0
                    orders_before = len(orders) if orders else 0
                    
                    # Action: Close positions if any exist and action is 'close_all'
                    if self.action == "close_all" and not self.is_liquidating:
                        with self.lock:
                            self.is_liquidating = True
                            self.last_liquidation_time = datetime.now()
                            
                        logger.info(f"Protection triggered: Starting full liquidation for account {account_number}")
                        
                        # Close everything
                        try:
                            close_all_positions()
                            close_all_orders()
                        finally:
                            with self.lock:
                                self.is_liquidating = False
                    elif self.action in ["close_losers_only", "close_losing"] and not self.is_liquidating:
                        with self.lock:
                            self.is_liquidating = True
                        logger.info(f"Protection triggered: Liquidating LOSERS ONLY for account {account_number}")
                        try:
                            close_losing_positions()
                            close_all_orders()
                        finally:
                            with self.lock:
                                self.is_liquidating = False
                    elif self.action == "close_profitable" and not self.is_liquidating:
                        with self.lock:
                            self.is_liquidating = True
                        logger.info(f"Protection triggered: Liquidating PROFITABLE ONLY for account {account_number}")
                        try:
                            close_all_profitable_positions()
                            close_all_orders()
                        finally:
                            with self.lock:
                                self.is_liquidating = False
                    elif self.action == "notify_only":
                        logger.info(f"Protection triggered (notify_only): Account {account_number} would have been closed.")
                        liquidation_summary = "Action is notify_only: nothing was closed."

                    if self.action != "notify_only" and (positions_before or orders_before):
                        left_pos = mt5.positions_get()
                        left_ord = mt5.orders_get()
                        n_pos = len(left_pos) if left_pos else 0
                        n_ord = len(left_ord) if left_ord else 0
                        liquidation_summary = (
                            f"Action: {self.action}. Positions {positions_before - n_pos}/{positions_before} closed, "
                            f"orders {orders_before - n_ord}/{orders_before} cancelled."
                        )
                        if self.action == "close_all" and (n_pos or n_ord):
                            liquidation_summary += f" {n_pos} position(s) / {n_ord} order(s) still open - retrying."
                        elif self.action != "close_all":
                            liquidation_summary += " (Other positions are left open by this action.)"
                        
                        # Cleanup the processing set after a while to avoid memory issues
                        if len(self.orders_being_processed) > 100:
                            self.orders_being_processed.clear()
                
                # Send notification - only once per trigger event per account
                if not should_continue and account_number not in self.notification_sent_accounts:
                    message = (
                        f"⚠️ EQUITY PROTECTION TRIGGERED - ACCOUNT {account_number} ⚠️\n\n{reason}\n\n"
                        f"{liquidation_summary or 'No open positions or orders.'}\n"
                        f"Trading is blocked until manually reset."
                    )
                    self._broadcast_protection_alert(account_number, reason, message)
                    
                    # Set flag to prevent repeated notifications for this account
                    with self.lock:
                        self.notification_sent_accounts.add(account_number)
                    
                    # Save to persist notification status
                    self.save_base_data()
                    
                    # Log the notification
                    logger.info(f"Equity protection notification sent for account {account_number} and flag set to prevent repeats")
                
                # Check for new orders/positions if trading is blocked
                # This will continually enforce the block even if new orders are attempted
                if self.is_trading_blocked(account_number):
                    # Check if there are any positions before attempting to close them
                    positions = mt5.positions_get()
                    if self.action == "close_all" and positions and len(positions) > 0:
                        # Only close positions if there are any open and action is close_all
                        logger.info(f"Closing {len(positions)} open positions for blocked account {account_number}")
                        close_all_positions()
                    elif self.action in ("close_losers_only", "close_losing") and positions and not self.is_liquidating:
                        # A loser that failed to close (requote/market closed) must be retried, not forgotten
                        close_losing_positions()
                    elif self.action == "close_profitable" and positions and not self.is_liquidating:
                        close_all_profitable_positions()
                    
                    # Get all types of pending orders and report details before closing - with duplicate prevention
                    now = datetime.now()
                    if (now - self.last_order_check_time).total_seconds() >= self.order_check_interval:
                        # Update the last check time
                        self.last_order_check_time = now
                        
                        orders = mt5.orders_get()
                        if orders and len(orders) > 0:
                            # Find orders that aren't already being processed
                            new_orders = []
                            for order in orders:
                                if order.ticket not in self.orders_being_processed:
                                    new_orders.append(order)
                                    self.orders_being_processed.add(order.ticket)
                            
                            if new_orders:
                                # Log detailed info about each pending order
                                order_types = {}
                                for order in new_orders:
                                    order_type = order.type
                                    order_types[order_type] = order_types.get(order_type, 0) + 1
                                
                                # Create detailed order type breakdown
                                order_details = ", ".join([f"{count} {self._get_order_type_name(order_type)}" 
                                                      for order_type, count in order_types.items()])
                                
                                # Log with detailed breakdown
                                if self.action == "close_all":
                                    logger.info(f"Closing {len(new_orders)} pending orders for blocked account {account_number} [{order_details}]")
                                    # Use close_all_orders
                                    close_all_orders()
                                    # Orders that are still there failed to cancel: forget them so the next
                                    # check retries instead of treating them as already handled forever
                                    still = mt5.orders_get()
                                    for o in (still or ()):
                                        self.orders_being_processed.discard(o.ticket)
                                else:
                                    logger.info(f"Account {account_number} is blocked but action is notify_only. Orders remain.")
                            
                            # Cleanup the processing set after a while to avoid memory issues
                            if len(self.orders_being_processed) > 100:
                                self.orders_being_processed.clear()
                
                # Configurable heartbeat interval
                time.sleep(self.heartbeat_interval)
                
            except Exception as e:
                logger.error(f"Error in equity protection heartbeat: {e}")
                time.sleep(self.heartbeat_interval * 10)  # Short recovery time on error

    def _handle_realtime_broadcast(self, _account_info=None):
        """Handle throttling and broadcasting of real-time equity data.
        
        Pass a pre-fetched account_info via _account_info to avoid a duplicate MT5 call.
        """
        try:
            now = datetime.now()
            time_since_last_ws = (now - self.last_ws_update_time).total_seconds()
            
            # Get current status (reuses pre-fetched account_info)
            status = self.get_equity_status(_account_info=_account_info)
            if "error" in status:
                return
            
            current_equity = status.get('equity', 0)
            current_balance = status.get('balance', 0)
            
            # Broadcast if:
            # 1. Equity/Balance changed significantly (> 0.01)
            # 2. OR it's been more than the update interval (e.g. 2s)
            significant_change = (abs(current_equity - self.last_ws_equity) > 0.01 or 
                                 abs(current_balance - self.last_ws_balance) > 0.01)
            
            if significant_change or time_since_last_ws >= self.ws_update_interval:
                self._broadcast_equity_update(status)
                self.last_ws_update_time = now
                self.last_ws_equity = current_equity
                self.last_ws_balance = current_balance
                
        except Exception as e:
            logger.error(f"Error handling real-time broadcast: {e}")
    
    def get_equity_status(self, account_number=None, _account_info=None) -> Dict:
        """Get current equity protection status for the specified or current account.
        
        Pass a pre-fetched account_info via _account_info to avoid a duplicate MT5 call.
        """
        try:
            # Use current account if none specified
            if account_number is None:
                if self.current_account is None:
                    self.update_current_account(_account_info=_account_info)
                account_number = self.current_account
            
            # Use pre-fetched account_info if available and account matches
            account_info = _account_info
            if account_info is None or (account_number and str(account_info.login) != account_number):
                account_info = mt5.account_info()
            if account_info is None:
                return {"error": "Could not retrieve account info"}
            if account_number is None:
                account_number = str(account_info.login)
            
            # Calculate current equity-to-balance difference
            
            # Load account data from history if it's not the current account
            # (Note: real-time balance/equity will still be for current MT5 login)
            if account_number == self.current_account:
                acc_peak_equity = self.historical_peak_equity
                acc_peak_balance = self.historical_peak_balance
                acc_daily_start_equity = self.daily_starting_equity
                acc_daily_start_balance = self.daily_starting_balance
                acc_historical_peak = self.historical_peak
            else:
                # Load from file for other accounts
                data = self._read_history_file()
                acc_data = data.get('accounts', {}).get(account_number, {})
                acc_peak_equity = acc_data.get('peak_equity', 0)
                acc_peak_balance = acc_data.get('peak_balance', 0)
                
                today = _today_str()
                daily = acc_data.get('daily', {}).get(today, {})
                acc_daily_start_equity = daily.get('starting_equity', 0)
                acc_daily_start_balance = daily.get('starting_balance', 0)
                
                acc_historical_peak = acc_peak_equity if self.protection_mode == 'equity' else acc_peak_balance

            # Calculate current equity-to-balance difference
            current_equity_balance_diff = 0
            current_equity_balance_pct = 0
            if account_info.balance > 0:
                current_equity_balance_diff = account_info.balance - account_info.equity
                current_equity_balance_pct = (current_equity_balance_diff / account_info.balance) * 100
            
            # Calculate drawdowns based on mode
            if self.protection_mode == 'equity':
                daily_reference = acc_daily_start_equity
                daily_current = account_info.equity
                current_value = account_info.equity
                reference_value = acc_historical_peak
                mode_display = "Equity"
            else:  # 'balance' mode
                daily_reference = acc_daily_start_balance
                daily_current = account_info.balance
                current_value = account_info.balance
                reference_value = acc_historical_peak
                mode_display = "Balance"
            
            # Calculate percentage drawdowns
            daily_drawdown_pct = 0
            if daily_reference > 0:
                daily_drawdown_pct = (daily_reference - daily_current) / daily_reference * 100
            
            total_drawdown_pct = 0
            if reference_value > 0:
                total_drawdown_pct = (reference_value - current_value) / reference_value * 100
            
            # Get block status
            is_blocked = account_number in self.trading_blocked_accounts
            block_reason = self.last_notification_reasons.get(account_number) if is_blocked else None
            
            status = {
                "account_number": account_number,
                "protection_mode": mode_display,
                "trading_blocked": is_blocked,
                "daily_starting_value": daily_reference,
                "current_value": current_value,
                "historical_peak": reference_value,
                "peak_equity": acc_peak_equity,
                "peak_balance": acc_peak_balance,
                "daily_drawdown_pct": daily_drawdown_pct,
                "total_drawdown_pct": total_drawdown_pct,
                "max_daily_loss_pct": self.max_daily_loss_pct,
                "max_total_drawdown_pct": self.max_total_drawdown_pct,
                "max_daily_loss_abs": self.max_daily_loss_abs,
                "max_total_drawdown_abs": self.max_total_drawdown_abs,
                "min_margin_level_pct": self.min_margin_level_pct,
                "action": self.action,
                "heartbeat_interval": self.heartbeat_interval,
                "order_check_interval": self.order_check_interval,
                "ws_update_interval": self.ws_update_interval,
                "auto_reset_daily": self.auto_reset_daily,
                "block_reason": block_reason,
                # Add current balance and equity info for all modes
                "balance": account_info.balance,
                "equity": account_info.equity,
                "margin_level": getattr(account_info, 'margin_level', 0),
                "current_equity_balance_diff": current_equity_balance_diff,
                "current_equity_balance_pct": current_equity_balance_pct,
                "verbose_logging": self.verbose_logging,
                "protection_enabled": self.running
            }
            
            return status
            
        except Exception as e:
            logger.error(f"Error getting equity status: {e}")
            return {"error": str(e)}
    
    def get_all_accounts_status(self) -> Dict:
        """Get status for all accounts that have data."""
        try:
            # Load all account data
            data = {'accounts': {}}
            try:
                if os.path.exists(self.history_file) and os.path.getsize(self.history_file) > 0:
                    with self.lock:
                        with open(self.history_file, 'r') as f:
                            data = json.load(f)
                else:
                    return {"error": "No account data found"}
            except json.JSONDecodeError:
                logger.error("JSON file is corrupted in get_all_accounts_status.")
                return {"error": "Account data file was corrupted"}
            
            if 'accounts' not in data or not data['accounts']:
                return {"error": "No account data found"}
            
            # Generate a summary for all accounts
            accounts_summary = {}
            
            for account_number in data['accounts']:
                status = self.get_equity_status(account_number)
                if "error" not in status:
                    accounts_summary[account_number] = status
            
            return {
                "accounts": accounts_summary,
                "blocked_accounts": list(self.trading_blocked_accounts),
                "notification_reasons": self.last_notification_reasons
            }
            
        except Exception as e:
            logger.error(f"Error getting all accounts status: {e}")
            return {"error": str(e)}
    
    def reset_account_block(self, account_number=None) -> bool:
        """Reset block for a specific account or current account."""
        try:
            # Use current account if none specified
            if account_number is None:
                if self.current_account is None:
                    self.update_current_account()
                account_number = self.current_account
            
            if not account_number:
                logger.error("Could not determine account number to reset")
                return False
            
            if self.unblock_trading(account_number):
                return True
            else:
                logger.info(f"Account {account_number} was not blocked")
                return False
                
        except Exception as e:
            logger.error(f"Error resetting account block: {e}")
            return False
    
    def toggle_verbose_logging(self) -> bool:
        """Toggle verbose logging mode."""
        try:
            # Toggle the setting
            self.verbose_logging = not self.verbose_logging
            
            # Log the change
            logger.info(f"Verbose logging has been {'enabled' if self.verbose_logging else 'disabled'}")
            
            # Save configuration
            self.save_config()
            
            return True
            
        except Exception as e:
            logger.error(f"Error toggling verbose logging: {e}")
            return False
    
    def update_config(self, config: Dict) -> bool:
        """Update protection configuration with hot-reload and save to JSON."""
        try:
            if 'max_daily_loss_pct' in config:
                self.max_daily_loss_pct = float(config['max_daily_loss_pct'])
            if 'max_total_drawdown_pct' in config:
                self.max_total_drawdown_pct = float(config['max_total_drawdown_pct'])
            if 'protection_mode' in config:
                if config['protection_mode'] in ['equity', 'balance']:
                    self.protection_mode = config['protection_mode']
            if 'max_daily_loss_abs' in config:
                self.max_daily_loss_abs = float(config['max_daily_loss_abs'])
            if 'max_total_drawdown_abs' in config:
                self.max_total_drawdown_abs = float(config['max_total_drawdown_abs'])
            if 'min_margin_level_pct' in config:
                self.min_margin_level_pct = float(config['min_margin_level_pct'])
            if 'action' in config:
                # same list the /protection/config route validates and the heartbeat acts on; the old
                # shorter list silently ignored 'close_losing' / 'close_profitable' (saved, never applied)
                if config['action'] in self.ALLOWED_ACTIONS:
                    self.action = config['action']
            if 'heartbeat_interval' in config:
                self.heartbeat_interval = max(0.01, float(config['heartbeat_interval']))
            if 'order_check_interval' in config:
                self.order_check_interval = float(config['order_check_interval'])
            if 'ws_update_interval' in config:
                self.ws_update_interval = float(config['ws_update_interval'])
            if 'auto_reset_daily' in config:
                self.auto_reset_daily = bool(config['auto_reset_daily'])
            if 'verbose_logging' in config:
                self.verbose_logging = bool(config['verbose_logging'])
            if 'day_offset_hours' in config:
                self.day_offset_hours = max(-14.0, min(14.0, float(config['day_offset_hours'])))
                set_day_offset_hours(self.day_offset_hours)
            if 'enabled' in config:
                enabled = bool(config['enabled'])
                if enabled and not self.running:
                    self.start()
                elif not enabled and self.running:
                    self.stop()
            
            # Save to JSON file for persistence
            self.save_config()
            
            logger.info(f"Protection config updated: "
                       f"max_daily_loss_pct={self.max_daily_loss_pct}%, "
                       f"max_total_drawdown_pct={self.max_total_drawdown_pct}%, "
                       f"protection_mode={self.protection_mode}, "
                       f"verbose_logging={self.verbose_logging}")
            return True
        except Exception as e:
            logger.error(f"Error updating config: {e}")
            return False
    
    def get_config(self) -> Dict:
        """Get current protection configuration."""
        config = {
            "max_daily_loss_pct": self.max_daily_loss_pct,
            "max_total_drawdown_pct": self.max_total_drawdown_pct,
            "max_daily_loss_abs": self.max_daily_loss_abs,
            "max_total_drawdown_abs": self.max_total_drawdown_abs,
            "min_margin_level_pct": self.min_margin_level_pct,
            "protection_mode": self.protection_mode,
            "action": self.action,
            "heartbeat_interval": self.heartbeat_interval,
            "order_check_interval": self.order_check_interval,
            "ws_update_interval": self.ws_update_interval,
            "auto_reset_daily": self.auto_reset_daily,
            "verbose_logging": self.verbose_logging,
            "enabled": self.running,
            "day_offset_hours": getattr(self, "day_offset_hours", PROTECTION_DAY_OFFSET_HOURS),
        }
        
        # Add schema if present
        if self.config_schema:
            # Create a new dict with $schema as the first key
            return {"$schema": self.config_schema, **config}
            
        return config
    
    def start(self):
        """Start the equity protection monitoring."""
        # Ensure running is True
        self.running = True
        
        # Only start thread if not already alive
        if self.monitor_thread is None or not self.monitor_thread.is_alive():
            self.monitor_thread = threading.Thread(target=self.monitor_equity, daemon=True)
            self.monitor_thread.start()
            logger.info("Equity protection monitoring started")
            self._broadcast_protection_status(True)
            # Save enabled status to config
            self.save_config()
            return True
        return False
    
    def stop(self):
        """Stop the equity protection monitoring."""
        if self.running:
            self.running = False
            logger.info("Equity protection monitoring stopped")
            self._broadcast_protection_status(False)
            # Save enabled status to config
            self.save_config()
            return True
        return False
    
    def manual_close_all(self) -> Dict:
        """Manually trigger full liquidation of all positions and orders. Reports what really happened."""
        try:
            with self.lock:
                self.is_liquidating = True

            logger.info("Manual liquidation triggered via API")
            p_res = close_all_positions()
            o_res = close_all_orders()

            left_pos = mt5.positions_get()
            left_ord = mt5.orders_get()
            n_pos = len(left_pos) if left_pos else 0
            n_ord = len(left_ord) if left_ord else 0
            complete = n_pos == 0 and n_ord == 0
            if not complete:
                logger.warning("Manual close-all incomplete: %d position(s), %d order(s) still open", n_pos, n_ord)

            self._broadcast_manual_action(
                "Full Liquidation",
                f"Closed {len(p_res)} positions, cancelled {len(o_res)} orders"
                + ("" if complete else f" - {n_pos} position(s) / {n_ord} order(s) STILL OPEN"),
            )

            return {
                "positions_closed": n_pos == 0,
                "orders_cancelled": n_ord == 0,
                "positions_closed_count": len(p_res),
                "orders_cancelled_count": len(o_res),
                "positions_remaining": n_pos,
                "orders_remaining": n_ord,
                "complete": complete,
            }
        finally:
            with self.lock:
                self.is_liquidating = False

    def manual_close_profitable(self) -> Dict:
        """Manually close only profitable positions."""
        logger.info("Manual close-profitable triggered via API")
        results = close_all_profitable_positions()
        self._broadcast_manual_action("Profit Liquidation", f"Closed {len(results)} profitable positions")
        return {"count": len(results)}

    def manual_close_losing(self) -> Dict:
        """Manually close only losing positions."""
        logger.info("Manual close-losing triggered via API")
        results = close_losing_positions()
        self._broadcast_manual_action("Loss Liquidation", f"Closed {len(results)} losing positions")
        return {"count": len(results)}

    def manual_close_symbol(self, symbol: str) -> Dict:
        """Manually close all positions for a specific symbol."""
        logger.info(f"Manual close-symbol {symbol} triggered via API")
        results = close_positions_by_symbol(symbol)
        self._broadcast_manual_action(f"Symbol Liquidation: {symbol}", f"Closed {len(results)} positions for {symbol}")
        return {"symbol": symbol, "count": len(results)}

    def _broadcast_manual_action(self, action_type: str, message: str):
        """Broadcast manual closure action via websocket."""
        try:
            self.socketio.emit('manual_action', {
                'type': action_type,
                'message': message,
                'timestamp': datetime.now().isoformat()
            })
        except Exception as e:
            logger.error(f"Error broadcasting manual action: {e}")
    
    def _broadcast_protection_alert(self, account_number: str, reason: str, message: str):
        """Broadcast protection alert via websocket."""
        try:
            self.socketio.emit('protection_alert', {
                'account_number': account_number,
                'reason': reason,
                'message': message,
                'timestamp': datetime.now().isoformat()
            })
        except Exception as e:
            logger.error(f"Error broadcasting protection alert: {e}")
    
    def _broadcast_equity_update(self, status: Dict):
        """Broadcast equity update via websocket."""
        try:
            self.socketio.emit('equity_update', {
                'status': status,
                'timestamp': datetime.now().isoformat()
            })
        except Exception as e:
            logger.error(f"Error broadcasting equity update: {e}")
    
    def _broadcast_protection_status(self, enabled: bool):
        """Broadcast protection status change via websocket."""
        try:
            self.socketio.emit('protection_status', {
                'enabled': enabled,
                'timestamp': datetime.now().isoformat()
            })
        except Exception as e:
            logger.error(f"Error broadcasting protection status: {e}")
    
    def _broadcast_account_blocked(self, account_number: str, reason: str):
        """Broadcast account blocked event via websocket."""
        try:
            self.socketio.emit('account_blocked', {
                'account_number': account_number,
                'reason': reason,
                'timestamp': datetime.now().isoformat()
            })
        except Exception as e:
            logger.error(f"Error broadcasting account blocked: {e}")
    
    def _broadcast_account_unblocked(self, account_number: str):
        """Broadcast account unblocked event via websocket."""
        try:
            self.socketio.emit('account_unblocked', {
                'account_number': account_number,
                'timestamp': datetime.now().isoformat()
            })
        except Exception as e:
            logger.error(f"Error broadcasting account unblocked: {e}")
            
    def _broadcast_connection_status(self, connected: bool):
        """Broadcast MT5 connection status change via websocket."""
        try:
            self.socketio.emit('connection_status', {
                'connected': connected,
                'message': "MT5 Terminal Connected" if connected else "MT5 Terminal Disconnected - Protection Degraded",
                'timestamp': datetime.now().isoformat()
            })
        except Exception as e:
            logger.error(f"Error broadcasting connection status: {e}")
    
    def _get_order_type_name(self, order_type):
        """Convert MT5 order type code to readable name"""
        order_types = {
            mt5.ORDER_TYPE_BUY: "Buy",
            mt5.ORDER_TYPE_SELL: "Sell",
            mt5.ORDER_TYPE_BUY_LIMIT: "Buy Limit",
            mt5.ORDER_TYPE_SELL_LIMIT: "Sell Limit",
            mt5.ORDER_TYPE_BUY_STOP: "Buy Stop",
            mt5.ORDER_TYPE_SELL_STOP: "Sell Stop",
            mt5.ORDER_TYPE_BUY_STOP_LIMIT: "Buy Stop Limit",
            mt5.ORDER_TYPE_SELL_STOP_LIMIT: "Sell Stop Limit"
        }
        return order_types.get(order_type, f"Unknown ({order_type})")


# Global instance
_protection_service = None

def get_protection_service():
    """Get the global protection service instance."""
    return _protection_service

def init_protection_service(socketio):
    """Initialize the global protection service instance."""
    global _protection_service
    if _protection_service is None:
        _protection_service = EquityProtection(socketio)
    return _protection_service
