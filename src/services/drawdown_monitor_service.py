"""
Drawdown Monitor Service for MT5 REST Provider
Periodically monitors account equity and triggers drawdown protection when limits are exceeded
"""
import asyncio
from typing import Optional
from datetime import datetime, timezone
from loguru import logger

from config import settings
from src.integrations.trading.provider_factory import create_trading_provider
from src.services.drawdown_protection_service import drawdown_protection_service
from src.core.database_service import db_service


class DrawdownMonitorService:
    """
    Service to monitor drawdown for MT5 REST provider (MetaAPI uses SDK-based monitoring)
    
    For MT5 REST, we need to manually:
    - Track daily starting balance
    - Track overall starting balance
    - Periodically calculate drawdown
    - Trigger protection when limits are exceeded
    """
    
    def __init__(self):
        self.is_running = False
        self.monitor_task = None
        self._stop_event = asyncio.Event()
        self._trading_provider = None  # Lazy initialization
        
        # Balance tracking
        self._daily_start_balance: Optional[float] = None
        self._overall_start_balance: Optional[float] = None
        self._daily_start_date: Optional[str] = None
        
        # Monitoring settings
        self._monitor_interval_seconds = 10  # Check every 10 seconds (polled providers)
        self._live_interval_seconds = 2      # ...every 2 seconds when equity is streamed
        
    @property
    def trading_provider(self):
        """Lazy initialization of trading provider"""
        if self._trading_provider is None:
            self._trading_provider = create_trading_provider()
        return self._trading_provider
    
    async def start_monitoring(self):
        """Start the drawdown monitoring loop"""
        if self.is_running:
            logger.warning("Drawdown monitoring is already running")
            return
        
        if not settings.enable_equity_protection:
            logger.info("Equity protection is disabled in settings")
            return
        
        # Only needed for MT5 REST (MetaAPI uses SDK monitoring)
        if settings.trading_provider.lower().strip() != "mt5rest":
            logger.info("Drawdown monitoring not needed for MetaAPI provider (uses SDK)")
            return
        
        self.is_running = True
        self._stop_event.clear()
        
        # Initialize balance tracking
        await self._initialize_balance_tracking()
        
        logger.success("🛡️  Drawdown monitoring started (MT5 REST provider)")
        logger.info(f"   Daily Limit: {settings.daily_drawdown_limit_percent}%")
        logger.info(f"   Overall Limit: {settings.overall_drawdown_limit_percent}%")
        logger.info(f"   Check Interval: {self._monitor_interval_seconds}s")
        
        # Start monitoring task
        self.monitor_task = asyncio.create_task(self._monitor_loop())
    
    async def stop_monitoring(self):
        """Stop the drawdown monitoring loop"""
        if not self.is_running:
            return
        
        logger.info("🛑 Stopping drawdown monitoring...")
        self.is_running = False
        self._stop_event.set()
        
        if self.monitor_task:
            await self.monitor_task
        
        logger.success("✅ Drawdown monitoring stopped")
    
    async def _initialize_balance_tracking(self):
        """Initialize balance tracking from database or current account state"""
        try:
            # Get current account info
            account_info = await self.trading_provider.get_account_info()
            current_balance = account_info.balance
            current_date = self._get_current_broker_date()
            
            # FIX (Bug 3): Load overall start balance from the active trading session in the DB.
            # Previously this always used the current balance, which reset the overall drawdown
            # counter to zero on every bot restart — breaking prop firm compliance tracking.
            overall_start = None
            try:
                active_session = await db_service.db.tradingsession.find_first(
                    where={"stoppedAt": None},
                    order={"startedAt": "desc"}
                )
                if active_session and active_session.startingBalance:
                    overall_start = active_session.startingBalance
                    logger.info(f"   Overall Start Balance loaded from active DB session (ID: {active_session.id[:8]}...): ${overall_start:.2f}")
            except Exception as db_err:
                logger.warning(f"⚠️  Could not load session start balance from DB: {db_err}")
            
            # Fall back to current balance only when no active session record exists
            if not overall_start:
                overall_start = current_balance
                logger.info(f"   No active DB session found — using current balance as overall start: ${overall_start:.2f}")
            
            self._overall_start_balance = overall_start
            self._daily_start_balance = current_balance
            self._daily_start_date = current_date
            
            logger.info("📊 Balance tracking initialized")
            logger.info(f"   Overall Start Balance: ${self._overall_start_balance:.2f}")
            logger.info(f"   Daily Start Balance: ${self._daily_start_balance:.2f}")
            logger.info(f"   Daily Start Date: {self._daily_start_date}")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize balance tracking: {str(e)}")
            # Set defaults to prevent crashes
            self._overall_start_balance = 10000.0
            self._daily_start_balance = 10000.0
            self._daily_start_date = self._get_current_broker_date()
    
    async def _check_daily_reset(self):
        """Check if we need to reset daily tracking (new trading day)"""
        current_date = self._get_current_broker_date()
        
        if current_date != self._daily_start_date:
            logger.info(f"📅 New trading day detected: {self._daily_start_date} -> {current_date}")
            
            # Reset daily tracking
            try:
                account_info = await self.trading_provider.get_account_info()
                self._daily_start_balance = account_info.balance
                self._daily_start_date = current_date
                logger.info(f"   Daily start balance reset to: ${self._daily_start_balance:.2f}")
            except Exception as e:
                logger.error(f"❌ Failed to reset daily balance: {str(e)}")
    
    async def _monitor_loop(self):
        """Main monitoring loop"""
        logger.info("🔄 Drawdown monitoring loop started")
        
        while not self._stop_event.is_set():
            try:
                # Check for daily reset
                await self._check_daily_reset()
                
                # Get current account state — fresh: a cached copy (60 s on MT5 REST)
                # would let equity fall through the limit unseen for up to a minute
                account_info = await self.trading_provider.get_account_info(use_cache=False)
                current_equity = account_info.equity
                
                # Calculate drawdowns
                daily_drawdown = self._calculate_drawdown(current_equity, self._daily_start_balance)
                overall_drawdown = self._calculate_drawdown(current_equity, self._overall_start_balance)
                
                # Log current state (only if significant change or periodically)
                if daily_drawdown > 0 or overall_drawdown > 0:
                    logger.debug(
                        f"📊 Drawdown Status - Daily: {daily_drawdown:.2f}% | Overall: {overall_drawdown:.2f}%"
                    )
                
                # FIX (Bug 2): Gate all limit checks on whether trading is already paused.
                # The protection service is the single source of truth for breach state.
                # The old code called _trigger_breach() on every loop tick while a breach was
                # active, causing handle_drawdown_breach() to run every 10 seconds indefinitely —
                # hammering the MT5 REST API and the database with redundant close/cancel calls.
                if drawdown_protection_service.is_trading_paused:
                    logger.debug("🛑 Trading is paused due to active drawdown breach — skipping limit checks")
                else:
                    # FIX (Bug 6): Use elif so only ONE breach type fires per monitoring tick.
                    # The old code used two independent 'if' blocks which could both trigger
                    # in the same tick when both limits were exceeded, causing _close_losing_positions()
                    # to run twice and attempt to close the same positions a second time.
                    if daily_drawdown >= settings.daily_drawdown_limit_percent:
                        logger.error(f"🚨 DAILY DRAWDOWN LIMIT BREACHED: {daily_drawdown:.2f}% >= {settings.daily_drawdown_limit_percent}%")
                        await self._trigger_breach("DAILY", daily_drawdown, current_equity)
                    
                    elif overall_drawdown >= settings.overall_drawdown_limit_percent:
                        logger.error(f"🚨 OVERALL DRAWDOWN LIMIT BREACHED: {overall_drawdown:.2f}% >= {settings.overall_drawdown_limit_percent}%")
                        await self._trigger_breach("OVERALL", overall_drawdown, current_equity)
                    
            except Exception as e:
                logger.error(f"❌ Error in drawdown monitoring loop: {str(e)}")
                logger.exception(e)
            
            # Wait for next check: streamed (free) equity -> check every 2 s and on any position
            # change; polled providers keep the slower interval to protect API quota
            from src.utils.loop_wait import wait_stop_or_change
            live = getattr(self.trading_provider, 'live_reads', False)
            await wait_stop_or_change(
                self._stop_event, self.trading_provider,
                self._live_interval_seconds if live else self._monitor_interval_seconds
            )
    
    def _calculate_drawdown(self, current_equity: float, start_balance: float) -> float:
        """
        Calculate drawdown percentage
        
        Args:
            current_equity: Current account equity
            start_balance: Starting balance for the period
            
        Returns:
            Drawdown percentage (0 if no drawdown)
        """
        if start_balance <= 0:
            return 0.0
        
        drawdown_amount = start_balance - current_equity
        if drawdown_amount <= 0:
            return 0.0  # No drawdown (in profit)
        
        return (drawdown_amount / start_balance) * 100
    
    async def _trigger_breach(
        self,
        breach_type: str,
        drawdown_percent: float,
        current_equity: float
    ):
        """
        Trigger drawdown breach handling
        
        Args:
            breach_type: "DAILY" or "OVERALL"
            drawdown_percent: Current drawdown percentage
            current_equity: Current account equity
        """
        try:
            # Construct event dict similar to MetaAPI format
            event = {
                'accountId': self._get_account_id(),
                'relativeDrawdown': drawdown_percent / 100.0,
                'period': 'day' if breach_type == "DAILY" else 'lifetime',
                'brokerTime': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
                'absoluteDrawdown': 0  # Not calculated for simplicity
            }
            
            # Generate a tracker ID (we don't have real trackers for MT5 REST)
            tracker_id = f"mt5rest_{breach_type}_monitor"
            
            logger.warning(f"🚨 Triggering drawdown breach handler for {breach_type} breach")
            logger.info(f"   Event data: {event}")
            logger.info(f"   Tracker ID: {tracker_id}")
            
            # Call the existing breach handler
            result = await drawdown_protection_service.handle_drawdown_breach(
                event=event,
                tracker_id=tracker_id
            )
            
            logger.info(f"   Breach handler result: {result}")
            
            if result.get('error'):
                logger.error(f"❌ Failed to handle breach: {result.get('error')}")
            else:
                logger.success("✅ Breach handled successfully")
                logger.info(f"   Positions closed: {result.get('losers_closed', 0)}")
                logger.info(f"   Orders cancelled: {result.get('pending_orders_cancelled', 0)}")
                logger.info(f"   Trading paused: {result.get('trading_paused', False)}")
                
        except Exception as e:
            logger.error(f"❌ Failed to trigger breach: {str(e)}")
            logger.exception(e)
    
    def _get_current_broker_date(self) -> str:
        """Get current broker date in YYYY-MM-DD format (UTC-based).
        
        FIX (Bug 1): This method was called on line 159 but was missing from this class,
        causing AttributeError to crash the monitor loop silently every 10 seconds.
        The same method exists in DrawdownProtectionService; both use UTC for consistency.
        """
        return datetime.now(timezone.utc).strftime('%Y-%m-%d')
    
    def _get_account_id(self) -> str:
        """Return the account identifier for MT5 REST provider"""
        return settings.mt5_rest_api_url or "mt5rest"


# Singleton instance
drawdown_monitor_service = DrawdownMonitorService()
