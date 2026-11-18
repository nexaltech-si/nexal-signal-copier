"""
Drawdown Protection Service
Handles drawdown breach detection, losing position closure, and trading pause management
"""
import json
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from loguru import logger

from src.core.database_service import db_service
from src.integrations.trading.provider_factory import create_trading_provider
from config import settings


def _get_account_id() -> str:
    """Return the account identifier for the active trading provider."""
    provider = settings.trading_provider.lower().strip()
    if provider == "mt5rest":
        return settings.mt5_rest_api_url or "mt5rest"
    return settings.metaapi_account_id or "unknown"


class DrawdownProtectionService:
    """
    Manages drawdown protection:
    - Saves breach events to database
    - Closes losing positions on breach
    - Manages trading pause state
    - Resets on new trading day
    - Persists state across bot restarts
    """
    
    def __init__(self):
        self.is_trading_paused = False
        self.active_breach_id: Optional[str] = None
        self.current_broker_date: Optional[str] = None
        self._trading_provider = None  # Lazy initialization
    
    def reset_state(self):
        """Forget the in-memory pause/breach state (it belongs to one account; used on provider switch)."""
        self.is_trading_paused = False
        self.active_breach_id = None
        self.current_broker_date = None

    @property
    def trading_provider(self):
        """Lazy initialization of trading provider"""
        if self._trading_provider is None:
            self._trading_provider = create_trading_provider()
        return self._trading_provider
        
    async def initialize(self):
        """Load any active drawdown breaches from database on startup"""
        try:
            logger.info("🔍 Checking for active drawdown breaches on startup...")
            self.reset_state()  # state is per account: never carry a pause over from another one
            
            # Check for active breaches
            active_breach = await db_service.db.drawdownbreach.find_first(
                where={
                    "accountId": _get_account_id(),
                    "isActive": True
                },
                order={"createdAt": "desc"}
            )
            
            if active_breach:
                logger.info(f"📋 Found active breach: ID={active_breach.id}, Date={active_breach.brokerDate}")
                
                # Check if breach is from today
                broker_date = await self._get_current_broker_date()
                logger.info(f"📅 Current broker date: {broker_date}")
                
                if active_breach.brokerDate == broker_date:
                    # Still valid - maintain trading pause
                    self.is_trading_paused = True
                    self.active_breach_id = active_breach.id
                    self.current_broker_date = broker_date
                    
                    logger.warning("⚠️  ACTIVE DRAWDOWN BREACH DETECTED ON STARTUP")
                    logger.warning(f"   Type: {active_breach.breachType}")
                    logger.warning(f"   Drawdown: {active_breach.drawdownPercent:.2f}%")
                    logger.warning("   Trading is PAUSED for today")
                else:
                    # From previous day - resolve it and allow trading
                    logger.info(f"🔄 Resolving previous day breach (Date: {active_breach.brokerDate} -> {broker_date})")
                    await self._resolve_breach(
                        active_breach.id,
                        "NEW_DAY",
                        f"New trading day started: {broker_date}"
                    )
                    logger.success(f"✅ Previous drawdown breach resolved (new day: {broker_date})")
            else:
                logger.info("✅ No active drawdown breaches - trading allowed")
                
        except Exception as e:
            logger.error(f"❌ Failed to initialize drawdown protection: {str(e)}")
            logger.exception(e)
            # Don't raise - allow bot to start even if this fails
            
    async def handle_drawdown_breach(
        self,
        event: Dict[str, Any],
        tracker_id: str
    ) -> Dict[str, Any]:
        """
        Handle a drawdown breach event
        
        Args:
            event: Drawdown event from MetaAPI
            tracker_id: ID of the tracker that triggered
            
        Returns:
            Dict with breach info and actions taken
        """
        try:
            # Extract event data
            account_id = event.get('accountId', _get_account_id())
            drawdown_percent = event.get('relativeDrawdown', 0) * 100
            period = event.get('period', 'unknown')
            broker_time = event.get('brokerTime', '')
            
            # Determine breach type
            breach_type = "DAILY" if period == "day" else "OVERALL"
            limit_percent = (
                settings.daily_drawdown_limit_percent if breach_type == "DAILY"
                else settings.overall_drawdown_limit_percent
            )
            
            logger.error("🚨" * 20)
            logger.error(f"🚨 DRAWDOWN BREACH DETECTED: {breach_type}")
            logger.error(f"   Limit: {limit_percent}% | Actual: {drawdown_percent:.2f}%")
            logger.error("🚨" * 20)
            
            # Get current broker date
            broker_date = await self._get_current_broker_date()
            
            # Check if we already have an active breach for today
            existing_breach = await db_service.db.drawdownbreach.find_first(
                where={
                    "accountId": account_id,
                    "breachType": breach_type,
                    "isActive": True,
                    "brokerDate": broker_date
                },
                order={"createdAt": "desc"}
            )
            
            if existing_breach:
                logger.warning(f"⚠️  Active breach already exists (ID: {existing_breach.id}) - will update instead of creating new record")
                # Don't return - continue to close positions
            else:
                logger.info("🔴 New breach detected - closing positions")
            
            logger.info("🔴 About to call _close_losing_positions...")
            # Close all losing positions
            closed_positions = await self._close_losing_positions()
            logger.info(f"🔴 _close_losing_positions returned {len(closed_positions)} positions")

            # Cancel all pending orders
            cancelled_orders = await self._cancel_pending_orders()

            # Save breach to database - update if exists, create if not
            if existing_breach:
                # Update existing breach with new closure counts
                breach = await db_service.db.drawdownbreach.update(
                    where={"id": existing_breach.id},
                    data={
                        "losersClosedCount": existing_breach.losersClosedCount + len(closed_positions),
                        "closedPositionIds": json.dumps(closed_positions),
                        "pendingOrdersCancelledCount": existing_breach.pendingOrdersCancelledCount + len(cancelled_orders),
                        "cancelledOrderIds": json.dumps(cancelled_orders),
                    }
                )
                logger.info(f"📝 Updated existing breach record (ID: {breach.id})")
            else:
                # Deactivate any other active breaches for same day/type before creating new one
                await db_service.db.drawdownbreach.update_many(
                    where={
                        "accountId": account_id,
                        "breachType": breach_type,
                        "brokerDate": broker_date,
                        "isActive": True
                    },
                    data={
                        "isActive": False,
                        "resolvedAt": datetime.now(timezone.utc),
                        "resolvedReason": "NEW_BREACH_CREATED"
                    }
                )
                
                # Create new breach record
                breach = await db_service.db.drawdownbreach.create(
                    data={
                        "breachType": breach_type,
                        "drawdownPercent": drawdown_percent,
                        "limitPercent": limit_percent,
                        "accountId": account_id,
                        "trackerId": tracker_id,
                        "tradingPaused": True,
                        "losersClosedCount": len(closed_positions),
                        "closedPositionIds": json.dumps(closed_positions),
                        "pendingOrdersCancelledCount": len(cancelled_orders),
                        "cancelledOrderIds": json.dumps(cancelled_orders),
                        "brokerTime": broker_time,
                        "brokerDate": broker_date,
                        "isActive": True
                    }
                )
                logger.info(f"📝 Created new breach record (ID: {breach.id})")
            
            # Set trading pause flag
            self.is_trading_paused = True
            self.active_breach_id = breach.id
            self.current_broker_date = broker_date
            
            logger.success(f"✅ Drawdown breach recorded (ID: {breach.id})")
            logger.warning("🛑 TRADING PAUSED for the rest of the day")
            
            return {
                "breach_id": breach.id,
                "breach_type": breach_type,
                "drawdown_percent": drawdown_percent,
                "limit_percent": limit_percent,
                "losers_closed": len(closed_positions),
                "closed_position_ids": closed_positions,
                "pending_orders_cancelled": len(cancelled_orders),
                "cancelled_order_ids": cancelled_orders,
                "trading_paused": True,
                "broker_date": broker_date
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to handle drawdown breach: {str(e)}")
            logger.exception(e)
            return {
                "error": str(e),
                "trading_paused": False
            }
    
    async def _close_losing_positions(self) -> List[str]:
        """
        Close all positions that are currently in loss
        
        Returns:
            List of position IDs that were closed
        """
        logger.info("🔴 _close_losing_positions called")
        closed_positions = []
        
        try:
            # FIX (Bug 5): Force a fresh fetch during a drawdown breach.
            # Using cached positions can miss positions opened in the last cache window
            # or include already-closed positions, causing spurious "position not found" errors.
            logger.info("🔴 Fetching fresh open positions from trading provider...")
            positions = await self.trading_provider.get_open_positions(use_cache=False)
            logger.info(f"🔴 Got {len(positions)} positions")
            
            if not positions:
                logger.info("ℹ️  No open positions to close")
                return closed_positions
            
            logger.info(f"📊 Checking {len(positions)} open positions for losses...")
            
            for position in positions:
                try:
                    position_id = position.get('id')
                    symbol = position.get('symbol')
                    # CRITICAL: 'profit' already includes unrealizedProfit, don't add twice
                    total_profit = position.get('profit', 0)
                    
                    # Check if position is losing
                    
                    if total_profit < 0:
                        logger.warning(f"🔴 Closing losing position: {symbol} (P&L: ${total_profit:.2f})")
                        
                        # Capture current position data BEFORE closing
                        current_price = position.get('currentPrice')
                        open_price = position.get('openPrice')
                        position_type = position.get('type')
                        
                        # Close the position
                        result = await self.trading_provider.close_position(position_id)
                        
                        # Check for successful close - MT5 REST API returns retcode, not stringCode
                        if result and (result.get('retcode') == 10009 or result.get('stringCode') == 'TRADE_RETCODE_DONE' or result.get('success')):
                            closed_positions.append(position_id)
                            logger.success(f"✅ Closed position {position_id}")
                            
                            # Update trade record with closure data
                            try:
                                # Find the trade record
                                trade = await db_service.get_trade_by_position_id(position_id)
                                if trade:
                                    # FIX (Bug 7): Skip DB update if Position Monitor already closed this
                                    # trade. Double-updating overwrites closedAt and profitLoss with
                                    # potentially different values from two different data sources.
                                    if trade.get('status') == 'CLOSED':
                                        logger.debug(f"Trade for position {position_id} already CLOSED in DB — skipping duplicate update")
                                    else:
                                        # Calculate profit in pips
                                        profit_pips = None
                                        if current_price and open_price:
                                            # Determine pip size by instrument type (not just digits)
                                            if 'XAU' in symbol.upper() or 'GOLD' in symbol.upper():
                                                pip_value = 0.1  # Gold: 1 pip = 0.1
                                            elif 'BTC' in symbol.upper() or 'ETH' in symbol.upper():
                                                pip_value = 0.1  # Crypto: 1 pip = 0.1
                                            elif 'JPY' in symbol.upper():
                                                pip_value = 0.01  # JPY pairs: 1 pip = 0.01
                                            else:
                                                pip_value = 0.0001  # Standard forex: 1 pip = 0.0001
                                            
                                            price_diff = current_price - open_price
                                            # Adjust for sell positions
                                            if position_type == 'POSITION_TYPE_SELL':
                                                price_diff = -price_diff
                                            profit_pips = price_diff / pip_value
                                        
                                        # Update trade with closure data including profit/loss
                                        await db_service.update_trade_closure(
                                            trade_id=trade['id'],
                                            close_price=current_price,
                                            profit_loss=total_profit,
                                            profit_loss_pips=profit_pips
                                        )
                                        
                                        await db_service.log_trade_action(
                                            trade_id=trade['id'],
                                            action_type='CLOSE',
                                            success=True,
                                            triggered_by='drawdown_protection',
                                            trigger_source='close_all_losing_positions',
                                            details=f'Position closed by drawdown protection - Loss: ${total_profit:.2f}' + (f' ({profit_pips:+.1f} pips)' if profit_pips else '') + (f' @ {current_price}' if current_price else '')
                                        )
                            except Exception as log_error:
                                logger.warning(f"⚠️ Position {position_id} was closed but its trade record "
                                               f"could not be updated (order sync will retry): {log_error}")
                        else:
                            logger.error(f"❌ Failed to close position {position_id}: {result}")
                    else:
                        logger.info(f"💰 Keeping winning position: {symbol} (P&L: ${total_profit:.2f})")
                        
                except Exception as e:
                    logger.error(f"❌ Error closing position {position.get('id')}: {str(e)}")
                    continue
            
            if closed_positions:
                logger.success(f"✅ Closed {len(closed_positions)} losing positions")
            else:
                logger.info("ℹ️  No losing positions found")
                
            return closed_positions

        except Exception as e:
            logger.error(f"❌ Failed to close losing positions: {str(e)}")
            return closed_positions

    async def _cancel_pending_orders(self) -> List[str]:
        """
        Cancel all pending orders (limit/stop orders) to prevent
        new positions from opening during drawdown breach

        Returns:
            List of order IDs that were cancelled
        """
        cancelled_orders = []

        try:
            # Get all pending orders from trading provider
            orders = await self.trading_provider.get_all_pending_orders()
            orders = orders or []

            if not orders:
                logger.info("ℹ️  No pending orders to cancel")
                return cancelled_orders

            logger.info(f"📋 Found {len(orders)} pending orders to cancel...")

            for order in orders:
                try:
                    order_id = order.get('id')
                    symbol = order.get('symbol', 'Unknown')
                    order_type = order.get('type', 'Unknown')

                    logger.warning(f"🔴 Cancelling pending order: {symbol} ({order_type})")

                    # Cancel the order
                    result = await self.trading_provider.cancel_order(order_id)

                    # FIX (Bug 4): Added retcode == 10009 to the success check.
                    # MT5 REST API returns {'retcode': 10009, ...} on success — it does NOT
                    # return stringCode. The missing retcode check caused all successful
                    # cancellations to appear as failures, leaving cancelled_order_ids empty in DB.
                    if result and (result.get('retcode') == 10009 or result.get('stringCode') == 'TRADE_RETCODE_DONE' or result.get('success')):
                        cancelled_orders.append(order_id)
                        logger.success(f"✅ Cancelled order {order_id}")
                    else:
                        logger.error(f"❌ Failed to cancel order {order_id}: {result}")

                except Exception as e:
                    logger.error(f"❌ Error cancelling order {order.get('id')}: {str(e)}")
                    continue

            if cancelled_orders:
                logger.success(f"✅ Cancelled {len(cancelled_orders)} pending orders")
            else:
                logger.info("ℹ️  No pending orders were cancelled")

            return cancelled_orders

        except Exception as e:
            logger.error(f"❌ Failed to cancel pending orders: {str(e)}")
            return cancelled_orders

    async def is_trading_allowed(self) -> tuple[bool, Optional[str]]:
        """
        Check if trading is currently allowed
        
        Returns:
            Tuple of (is_allowed: bool, reason: Optional[str])
        """
        if not self.is_trading_paused:
            return True, None
        
        # Check if we've moved to a new day
        current_date = await self._get_current_broker_date()
        
        if current_date != self.current_broker_date:
            # New day - reset the pause
            await self._reset_daily_breach()
            return True, None
        
        # FIX: Verify the active breach still belongs to the CURRENT account.
        # If the user switched accounts (changed METAAPI_ACCOUNT_ID), the old
        # breach should NOT block trading on the new account.
        current_account = _get_account_id()
        if self.active_breach_id:
            try:
                breach = await db_service.db.drawdownbreach.find_unique(
                    where={"id": self.active_breach_id}
                )
                if breach and breach.accountId != current_account:
                    logger.warning(
                        f"⚠️  Active breach (ID: {self.active_breach_id}) belongs to "
                        f"account '{breach.accountId}' but current account is "
                        f"'{current_account}' — auto-resolving mismatch"
                    )
                    await self._resolve_breach(
                        self.active_breach_id,
                        "ACCOUNT_MISMATCH",
                        f"Account switched from '{breach.accountId}' to '{current_account}'"
                    )
                    self.is_trading_paused = False
                    self.active_breach_id = None
                    return True, None
            except Exception as e:
                logger.error(f"❌ Failed to verify breach account ownership: {e}")
        
        # Still paused
        reason = f"Trading paused due to drawdown breach (Date: {self.current_broker_date})"
        return False, reason
    
    async def _reset_daily_breach(self):
        """Reset daily drawdown breach on new day"""
        try:
            if self.active_breach_id:
                await self._resolve_breach(
                    self.active_breach_id,
                    "NEW_DAY",
                    f"New trading day started: {await self._get_current_broker_date()}"
                )
                
            self.is_trading_paused = False
            self.active_breach_id = None
            self.current_broker_date = await self._get_current_broker_date()
            
            logger.success("✅ Daily drawdown breach reset - trading resumed")
            
        except Exception as e:
            logger.error(f"❌ Failed to reset daily breach: {str(e)}")
    
    async def _resolve_breach(
        self,
        breach_id: str,
        reason: str,
        notes: Optional[str] = None
    ):
        """Mark a breach as resolved"""
        try:
            await db_service.db.drawdownbreach.update(
                where={"id": breach_id},
                data={
                    "isActive": False,
                    "resolvedAt": datetime.now(timezone.utc),
                    "resolvedReason": reason,
                    "resumedAt": datetime.now(timezone.utc)
                }
            )
            
            if notes:
                logger.info(f"✅ Breach resolved: {notes}")
                
        except Exception as e:
            logger.error(f"❌ Failed to resolve breach: {str(e)}")
    
    async def _get_current_broker_date(self) -> str:
        """
        Get current broker date in YYYY-MM-DD format
        
        Returns:
            Date string (e.g., "2025-10-18")
        """
        try:
            # Use UTC time to avoid excessive API calls that trigger rate limiting
            # Broker time differences are typically minimal for daily calculations
            return datetime.now(timezone.utc).strftime('%Y-%m-%d')
            
        except Exception as e:
            logger.warning(f"⚠️  Could not get broker date: {str(e)}, using UTC")
            return datetime.now(timezone.utc).strftime('%Y-%m-%d')
    
    async def get_active_breach_info(self) -> Optional[Dict[str, Any]]:
        """Get information about the current active breach, if any"""
        if not self.active_breach_id:
            return None
        
        try:
            breach = await db_service.db.drawdownbreach.find_unique(
                where={"id": self.active_breach_id}
            )
            
            if breach:
                return {
                    "id": breach.id,
                    "type": breach.breachType,
                    "drawdown_percent": breach.drawdownPercent,
                    "limit_percent": breach.limitPercent,
                    "paused_at": breach.pausedAt.isoformat(),
                    "broker_date": breach.brokerDate,
                    "losers_closed": breach.losersClosedCount
                }
            
            return None
            
        except Exception as e:
            logger.error(f"❌ Failed to get breach info: {str(e)}")
            return None
    
    async def manual_resume_trading(self, reason: str = "MANUAL_RESET") -> bool:
        """
        Manually resume trading (admin override)
        
        Args:
            reason: Reason for manual resume
            
        Returns:
            True if successful
        """
        try:
            if self.active_breach_id:
                await self._resolve_breach(self.active_breach_id, reason)
            
            self.is_trading_paused = False
            self.active_breach_id = None
            
            logger.warning(f"⚠️  Trading manually resumed: {reason}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to manually resume trading: {str(e)}")
            return False


# Singleton instance
drawdown_protection_service = DrawdownProtectionService()
