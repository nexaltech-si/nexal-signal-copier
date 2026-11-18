"""
Position Monitor Service
Monitors open positions and applies auto TP, trailing stop loss, and breakeven functionality
"""
import asyncio
import time
from typing import Optional, List
from datetime import datetime, timedelta, timezone
from loguru import logger

from config import settings
from src.models.enums import CalculationMethod, TrailingActivationMethod, BreakevenTriggerMethod, TradeActionType
from src.integrations.trading.provider_factory import create_trading_provider
from src.services.spread_adjustment_service import spread_adjustment_service
from src.services.position_recovery_service import position_recovery_service
from src.core.database_service import db_service
from src.utils.trade_lock import trade_modification_lock

# Import AI market analysis (optional)
try:
    from src.services.signal_service import signal_service
    from src.services.ai_analysis_service import ai_analysis_service
    AI_ANALYSIS_AVAILABLE = True
    logger.info("✅ AI market analysis services loaded successfully")
except ImportError as e:
    AI_ANALYSIS_AVAILABLE = False
    logger.warning(f"⚠️ AI market analysis not available - Import error: {str(e)}")
    logger.warning("   This is normal if AI dependencies are not installed")
except Exception as e:
    AI_ANALYSIS_AVAILABLE = False
    logger.error(f"❌ Unexpected error loading AI services: {str(e)}")
    logger.exception(e)


class PositionMonitorService:
    """
    Service to monitor open positions and automatically manage:
    - Auto Take Profit
    - Trailing Stop Loss
    - Breakeven stop loss movement
    """
    
    def __init__(self):
        self.is_running = False
        self.monitor_task = None
        self._stop_event = asyncio.Event()
        self._trading_provider = None  # Lazy initialization
        self._trading_brain = None    # Optional AI Trading Brain
        self._last_ai_analysis_check = {}  # Track when we last analyzed each position
        self._ai_analysis_cache = {}  # Cache analysis results to avoid excessive API calls
        self._monitor_cycle_count = 0  # Track monitoring cycles for periodic tasks
        self._orphan_scan_interval = 40  # Run orphan scan every N cycles (40 * 3s = 2 minutes)
        self._equity_snapshot_interval = 100  # Write equity snapshot every N cycles (100 * 3s = 5 minutes)
        self._position_data_cache = {}  # Cache last known state of positions for accurate closure logging
        self._executed_trades_cache = {}  # Cache executed trades {position_id: trade_id}
        self._executed_trades_cache_time = None  # Last time we refreshed the cache
        self._last_trail_at = {}  # trade_id -> monotonic time of last trailing SL modification
        self._last_profit_update = {}  # Track last profit values {trade_id: {'profit': float, 'pips': float}}

    def set_trading_brain(self, brain):
        """Inject the Trading Brain for autonomous position management."""
        self._trading_brain = brain
        logger.info("🧠 Trading Brain wired into position monitor")
        
    @property
    def trading_provider(self):
        """Lazy initialization of trading provider"""
        if self._trading_provider is None:
            self._trading_provider = create_trading_provider()
        return self._trading_provider
        
    async def start_monitoring(self):
        """Start the position monitoring loop"""
        if self.is_running:
            logger.warning("Position monitoring is already running")
            return
        
        if not settings.enable_position_monitoring:
            logger.info("Position monitoring is disabled in settings")
            return
        
        self.is_running = True
        self._stop_event.clear()
        
        logger.success("🔄 Position monitoring started")
        logger.info(f"   Interval: {settings.position_monitor_interval_seconds}s (always fetches fresh data)")
        if settings.position_monitor_startup_delay_seconds > 0:
            logger.info(f"   Startup delay: {settings.position_monitor_startup_delay_seconds}s")
        logger.info(f"   Auto TP: {'✅' if settings.enable_auto_take_profit else '❌'}")
        logger.info(f"   Auto Partial: {'✅' if settings.enable_auto_partial else '❌'}")
        logger.info(f"   Breakeven: {'✅' if settings.enable_breakeven_move else '❌'} (method: {settings.breakeven_trigger_method})")
        logger.info(f"   Trailing SL: {'✅' if settings.enable_trailing_stop else '❌'}")
        
        # Start monitoring task
        self.monitor_task = asyncio.create_task(self._monitor_loop())
    
    async def stop_monitoring(self):
        """Stop the position monitoring loop"""
        if not self.is_running:
            return
        
        logger.info("🛑 Stopping position monitoring...")
        self.is_running = False
        self._stop_event.set()
        
        if self.monitor_task:
            await self.monitor_task
        
        logger.success("✅ Position monitoring stopped")
    
    async def _monitor_loop(self):
        """Main monitoring loop"""
        # Optional startup delay (disabled by default for real-time monitoring)
        startup_delay = getattr(settings, 'position_monitor_startup_delay_seconds', 0)
        if startup_delay > 0:
            logger.info(f"⏳ Waiting {startup_delay}s before first check...")
            await asyncio.sleep(startup_delay)
        
        while self.is_running and not self._stop_event.is_set():
            try:
                # Ensure database connection is healthy before operations
                from src.core.prisma_client import prisma_client
                if not await prisma_client.ensure_connected():
                    logger.error("❌ Database connection unavailable - skipping monitoring cycle")
                    await asyncio.sleep(5)  # Wait before retry
                    continue
                
                await self._check_all_positions()

                # Plan watcher — runs after all position checks, isolated from main loop
                from src.services.plan_watcher_service import plan_watcher_service
                await plan_watcher_service.tick()

                self._monitor_cycle_count += 1

                # Cleanup old cache entries every 100 cycles (~5 minutes at 3s interval)
                if self._monitor_cycle_count % 100 == 0:
                    await self._cleanup_old_caches()

                # Persist an equity/balance snapshot every N cycles for the equity curve chart
                if self._monitor_cycle_count % self._equity_snapshot_interval == 0:
                    await self._write_equity_snapshot()
                
            except asyncio.CancelledError:
                logger.info("⏹️ Position monitoring cancelled - shutting down")
                break
            except Exception as e:
                logger.error(f"Error in position monitoring loop: {str(e)}")
                logger.exception(e)
                # Give the system time to recover from errors
                await asyncio.sleep(2)
            
            # Wait for next check
            from src.utils.loop_wait import wait_stop_or_change
            await wait_stop_or_change(
                self._stop_event, self.trading_provider,
                settings.position_monitor_interval_seconds
            )
    
    async def _check_all_positions(self):
        """Fetch open positions and apply trade-management rules (TP/SL/breakeven/trailing).
        State transitions (CLOSED, CANCELLED) are handled exclusively by order_sync_service."""
        try:
            if hasattr(self.trading_provider, '_verify_connection'):
                if not await self.trading_provider._verify_connection():
                    return
            elif not self.trading_provider.is_connected:
                return
        except Exception as e:
            # Skipping the cycle is right, but silently skipping every cycle means
            # TP/SL/break-even/trailing management has stopped without a trace.
            now = time.monotonic()
            if now - getattr(self, '_last_conn_check_warning', 0.0) > 300:
                self._last_conn_check_warning = now
                logger.warning(f"⚠️ Position monitor: connection check failed — trade management "
                               f"(TP/SL/break-even/trailing) is paused until it recovers: {e}")
            return
        
        positions = await self.trading_provider.get_open_positions()
        
        if not positions:
            return
        
        logger.debug(f"📊 Monitoring {len(positions)} open position(s)...")
        for position in positions:
            try:
                await self._check_position(position)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Error monitoring position {position.get('id')}: {str(e)}")
    
    async def _check_position(self, position: dict):
        """Check a single position and apply rules"""
        position_id = position.get('id')
        symbol = position.get('symbol')
        
        # Skip positions without magic number (manual trades or non-bot positions)
        magic = position.get('clientId') or position.get('magic')
        if not magic:
            logger.debug(f"⏭️ Skipping position {position_id[:8]}... (no magic number - likely manual trade)")
            return
        
        # Get trade from database
        trade = await self._get_trade_by_position_id(position_id)
        
        if not trade:
            logger.debug(f"No database record found for position {position_id}")
            
            # Check if position is known to be unrecoverable
            if position_id in position_recovery_service._unrecoverable_positions:
                logger.debug(f"⏭️ Position {position_id[:8]}... is unrecoverable - skipping monitoring")
                return
            
            # A position that just appeared may not be linked to its trade row yet
            # (streamed reads show it the instant it opens) - give the trading flow a moment.
            age = self._position_age_seconds(position)
            if age is not None and age < 15:
                logger.debug(f"⏳ Position {position_id[:8]}... is {age:.1f}s old with no DB link yet - retrying next cycle")
                return

            # Attempt to recover orphaned position
            logger.info(f"🔄 Attempting to recover orphaned position {position_id}")
            trade = await position_recovery_service.recover_position_by_id(position_id)
            
            if not trade:
                logger.warning(f"⚠️ Could not recover position {position_id} - skipping monitoring")
                return
            
            logger.success(f"✅ Recovered position {position_id} - continuing monitoring")
        
        # Skip only confirmed CLOSED trades - all other statuses should be monitored
        # as the position is still live in the broker
        current_status = trade.get('status')
        if current_status == 'CLOSED':
            return

        # CRITICAL: Upgrade any non-RUNNING status → RUNNING now that the position is live.
        # Covers: PENDING, EXECUTING, EXECUTED, PROCESSING
        # Note: CANCELLED and FAILED are NOT upgraded - these are terminal states
        _needs_upgrade = {'PENDING', 'EXECUTING', 'PROCESSING', 'EXECUTED'}
        if current_status in _needs_upgrade:
            logger.info(
                f"📊 Position {position_id[:8]}... is ACTIVE - "
                f"updating status: {current_status} → RUNNING"
            )
            exec_time = datetime.now(timezone.utc)
            await db_service.update_trade_fields(trade['id'], {
                'status': 'RUNNING',
                'executedAt': exec_time,
            })
            trade['status'] = 'RUNNING'
            trade['executedAt'] = exec_time
            await db_service.log_trade_action(
                trade_id=trade['id'],
                action_type='EXECUTION',
                success=True,
                triggered_by='position_monitor',
                trigger_source='inflight_to_running_sync',
                details=f'Position confirmed open - status updated from {current_status} to RUNNING',
            )
            # Forward "position opened" reply to signal channel
            try:
                from src.services.signal_forwarder_service import signal_forwarder_service
                _open_price = position.get('openPrice') or trade.get('entryPrice')
                _symbol = position.get('symbol', trade.get('symbol', ''))
                await signal_forwarder_service.reply_position_opened(trade.get('signalId'), _symbol, _open_price, trade_id=trade.get('id'))
            except Exception as _exc:
                logger.debug(f"Suppressed exception: {_exc!r}")
        
        # Get current price
        current_price = position.get('currentPrice')
        entry_price = position.get('openPrice') or trade.get('entryPrice')
        
        if not current_price or not entry_price:
            logger.warning(f"Missing price data for position {position_id}")
            return
        
        # Determine if this is a buy or sell
        is_buy = position.get('type') == 'POSITION_TYPE_BUY'
        
        # Calculate profit in pips
        profit_pips = self._calculate_profit_pips(
            entry_price,
            current_price,
            is_buy,
            symbol
        )
        
        # Calculate profit/loss in currency
        # CRITICAL: MetaAPI's 'profit' field already includes everything:
        # profit = realizedProfit (from partials) + unrealizedProfit (floating) + commission + swap
        # DO NOT add unrealizedProfit again - it's already included in profit!
        total_profit = position.get('profit', 0)
        
        # Log profit source for debugging
        if total_profit != 0:
            realized = position.get('realizedProfit', 0)
            unrealized = position.get('unrealizedProfit', 0)
            logger.debug(f"💰 Position {position_id[:8]}... P/L from {settings.provider_label}: ${total_profit:.2f} (realized: ${realized:.2f}, unrealized: ${unrealized:.2f})")
        
        # FALLBACK: If both are 0 or None, calculate manually from price movement
        # This can happen with some brokers or connection types during rapid updates
        if total_profit == 0 and current_price and entry_price:
            volume = position.get('volume', 0)
            if volume > 0:
                price_diff = current_price - entry_price if is_buy else entry_price - current_price
                
                # Calculate profit based on contract size
                # Gold/XAU: 1 lot = 100 oz, profit = price_diff * 100 * lots
                # Forex: 1 lot = 100,000 units, profit = price_diff * 100,000 * lots
                if 'XAU' in symbol.upper() or 'GOLD' in symbol.upper():
                    contract_size = 100  # 100 oz per lot
                    total_profit = price_diff * contract_size * volume
                else:
                    # For forex pairs, need to account for quote currency
                    # Simplified: assume USD pairs for now
                    contract_size = 100000  # Standard lot
                    pip_value = self._get_pip_value(symbol)
                    # Convert price diff to dollar value
                    total_profit = (price_diff / pip_value) * 10 * volume  # $10 per pip per standard lot
                
                logger.debug(f"📊 Manual profit calc for {position_id[:8]}...: ${total_profit:.2f} ({settings.provider_label} profit was 0)")
        
        # Cache position data for accurate closure logging
        # This data will be used if the position closes externally (TP/SL hit or manual close)
        self._position_data_cache[position_id] = {
            'current_price': current_price,
            'open_price': entry_price,
            'profit': total_profit,  # Total profit (includes realized + unrealized)
            'unrealized_profit': position.get('unrealizedProfit', 0),  # For reference
            'profit_pips': profit_pips,
            'symbol': symbol,
            'type': position.get('type'),
            'volume': position.get('volume'),
            'timestamp': datetime.now(timezone.utc)
        }
        
        # OPTIMIZED: Only update profit/loss if changed significantly (avoid DB writes every 3s)
        # This reduces DB load while keeping data reasonably current
        trade_id = trade['id']
        last_update = self._last_profit_update.get(trade_id, {})
        profit_changed = abs(total_profit - last_update.get('profit', 0)) > 0.5  # $0.50 threshold
        pips_changed = abs(profit_pips - last_update.get('pips', 0)) > 0.5  # 0.5 pips threshold
        
        # Sync SL/TP/volume from broker to DB (ensures DB always reflects broker reality)
        broker_sl = position.get('stopLoss')
        broker_tp = position.get('takeProfit')
        broker_volume = position.get('volume')
        sl_changed = broker_sl is not None and broker_sl != trade.get('stopLoss')
        tp_changed = broker_tp is not None and broker_tp != trade.get('takeProfit')
        volume_changed = broker_volume is not None and broker_volume != trade.get('lotSize')
        
        if profit_changed or pips_changed or sl_changed or tp_changed or volume_changed or not last_update:
            try:
                update_fields = {
                    'profitLoss': total_profit,
                    'profitLossPips': profit_pips,
                    'lastModifiedAt': datetime.now(timezone.utc)
                }
                if sl_changed:
                    update_fields['stopLoss'] = broker_sl
                    logger.info(f"📊 Syncing SL from broker for {trade_id[:8]}...: {trade.get('stopLoss')} → {broker_sl}")
                if tp_changed:
                    update_fields['takeProfit'] = broker_tp
                    logger.info(f"📊 Syncing TP from broker for {trade_id[:8]}...: {trade.get('takeProfit')} → {broker_tp}")
                if volume_changed:
                    update_fields['lotSize'] = broker_volume
                    logger.info(f"📊 Syncing volume from broker for {trade_id[:8]}...: {trade.get('lotSize')} → {broker_volume}")
                
                await db_service.update_trade_fields(trade['id'], update_fields)
                
                # Update local trade dict so subsequent checks in the same cycle see updated values
                if sl_changed:
                    trade['stopLoss'] = broker_sl
                if tp_changed:
                    trade['takeProfit'] = broker_tp
                if volume_changed:
                    trade['lotSize'] = broker_volume
                
                # Update cache
                self._last_profit_update[trade_id] = {'profit': total_profit, 'pips': profit_pips}
            except Exception as e:
                logger.warning(f"⚠️ Could not update trade data for {trade['id'][:8]}...: {str(e)}")
        
        # Update highest/lowest price tracking
        await self._update_price_tracking(trade, current_price, is_buy)
        
        # Apply rules in order of priority — brain only runs if no rules fire

        rules_acted = False

        # 1. Auto Take Profit (if enabled and not set)
        if settings.enable_auto_take_profit and trade.get('autoTpEnabled', True):
            if not position.get('takeProfit') or position.get('takeProfit') == 0:
                await self._apply_auto_take_profit(trade, position, entry_price, is_buy)
                rules_acted = True

        # 2. Auto Partial (if enabled and not yet activated)
        if settings.enable_auto_partial and trade.get('autoPartialEnabled', True):
            if profit_pips is not None and not trade.get('autoPartialActivated', False):
                partial_fired = await self._apply_auto_partial(trade, position, entry_price, is_buy, current_price, profit_pips)
                if partial_fired:
                    rules_acted = True

        # 3. Breakeven move (if enabled and not yet activated)
        if settings.enable_breakeven_move and trade.get('breakEvenEnabled', True):
            if profit_pips is not None and not trade.get('breakEvenActivated', False):
                should_move_be = await self._should_trigger_breakeven(trade, profit_pips)
                if should_move_be:
                    await self._move_to_breakeven(trade, position, entry_price, is_buy, current_price, profit_pips)
                    rules_acted = True

        # 4. Trailing stop (if enabled)
        if settings.enable_trailing_stop and trade.get('trailingStopEnabled', True) and profit_pips is not None:
            if not trade.get('trailingActivated', False):
                should_activate = await self._should_activate_trailing(trade, profit_pips, entry_price)
                if should_activate:
                    await self._activate_trailing(trade, position, current_price, is_buy, profit_pips)
                    rules_acted = True
            else:
                await self._apply_trailing_stop(trade, position, current_price, is_buy, profit_pips)
                rules_acted = True

        # 5. AI Market Analysis (if enabled)
        if settings.enable_ai_market_analysis and AI_ANALYSIS_AVAILABLE:
            await self._apply_ai_market_analysis(trade, position, entry_price, current_price, is_buy, profit_pips)
            rules_acted = True

        # Trading Brain — only runs when no rules fired (situation unclear)
        if not rules_acted:
            await self._run_brain_review(trade, position, profit_pips)
    
    async def _run_brain_review(self, trade: dict, position: dict, profit_pips: float) -> None:
        """
        Ask the Trading Brain whether to act on this position.
        Only called when no rule-based automation fired this cycle.
        """
        brain = self._trading_brain
        if brain is None or not getattr(brain, 'enabled', False):
            return

        try:
            account_info = None
            try:
                account_info = await self.trading_provider.get_account_info()
            except Exception as _exc:
                logger.debug(f"Suppressed exception: {_exc!r}")

            # Fetch news for brain context (best-effort)
            news_events = []
            try:
                from src.services.news_service import news_trading_service as nts
                symbol = position.get('symbol', '')
                if nts and hasattr(nts, 'get_upcoming_events_for_symbol') and symbol:
                    news_events = await nts.get_upcoming_events_for_symbol(symbol) or []
            except Exception as _exc:
                logger.debug(f"Suppressed exception: {_exc!r}")

            actions = await brain.review_position(trade, position, account_info, news_events)

            if not actions:
                return  # Rate-limited

            from src.services.approval_queue import brain_action_queue
            from src.integrations.telegram.unified_sender import notification_sender
            from src.core.database_service import db_service
            symbol = position.get('symbol', trade.get('symbol', '?'))

            require_approval = getattr(settings, 'brain_action_require_approval', True)
            approval_types = {
                t.strip().upper()
                for t in getattr(settings, 'brain_action_approval_types', 'CLOSE,PARTIAL_CLOSE,MODIFY_SL,MODIFY_TP').split(',')
                if t.strip()
            }

            # Build position context once for DB persistence
            pos_input_data = {
                "symbol": symbol,
                "position_id": position.get('id'),
                "type": position.get('type'),
                "volume": position.get('volume'),
                "open_price": position.get('openPrice'),
                "current_price": position.get('currentPrice'),
                "sl": position.get('stopLoss'),
                "tp": position.get('takeProfit'),
                "profit": position.get('profit'),
            }

            for action in actions:
                act = action.action
                needs_approval = require_approval and act in approval_types

                if act == 'HOLD':
                    logger.debug(f"🧠 Brain: HOLD {symbol} — {action.reason}")
                    continue

                # Persist to AIDecision before dispatching
                out_data = {}
                if action.value is not None:
                    out_data['value'] = action.value
                if action.percentage is not None:
                    out_data['percentage'] = action.percentage
                decision_id = await db_service.save_brain_position_action(
                    symbol=symbol,
                    action=act,
                    reason=action.reason,
                    input_data=pos_input_data,
                    output_data=out_data or None,
                    trade_id=trade.get('id'),
                    position_id=position.get('id'),
                    outcome="PENDING_APPROVAL" if needs_approval else "EXECUTED_DIRECTLY",
                )

                trade_snap = dict(trade)
                pos_snap = dict(position)

                if act == 'MODIFY_SL' and action.value is not None:
                    sl_val = action.value
                    reason = action.reason
                    if needs_approval:
                        action_id = brain_action_queue.add(
                            symbol=symbol, action='MODIFY_SL', reason=reason, value=sl_val,
                            decision_id=decision_id,
                            execute_fn=lambda t=trade_snap, p=pos_snap, v=sl_val, r=reason: self._brain_modify_sl(t, p, v, r),
                        )
                        await notification_sender.notify_brain_action_approval(
                            action_id=action_id, symbol=symbol, action='MODIFY_SL', reason=reason, value=sl_val,
                        )
                    else:
                        await self._brain_modify_sl(trade_snap, pos_snap, sl_val, reason)

                elif act == 'MODIFY_TP' and action.value is not None:
                    tp_val = action.value
                    reason = action.reason
                    if needs_approval:
                        action_id = brain_action_queue.add(
                            symbol=symbol, action='MODIFY_TP', reason=reason, value=tp_val,
                            decision_id=decision_id,
                            execute_fn=lambda t=trade_snap, p=pos_snap, v=tp_val, r=reason: self._brain_modify_tp(t, p, v, r),
                        )
                        await notification_sender.notify_brain_action_approval(
                            action_id=action_id, symbol=symbol, action='MODIFY_TP', reason=reason, value=tp_val,
                        )
                    else:
                        await self._brain_modify_tp(trade_snap, pos_snap, tp_val, reason)

                elif act == 'PARTIAL_CLOSE':
                    pct = action.percentage or 50
                    reason = action.reason
                    if needs_approval:
                        action_id = brain_action_queue.add(
                            symbol=symbol, action='PARTIAL_CLOSE', reason=reason, percentage=pct,
                            decision_id=decision_id,
                            execute_fn=lambda t=trade_snap, p=pos_snap, pc=pct, r=reason: self._brain_partial_close(t, p, pc, r),
                        )
                        await notification_sender.notify_brain_action_approval(
                            action_id=action_id, symbol=symbol, action='PARTIAL_CLOSE', reason=reason, percentage=pct,
                        )
                    else:
                        await self._brain_partial_close(trade_snap, pos_snap, pct, reason)

                elif act == 'CLOSE':
                    reason = action.reason
                    if needs_approval:
                        action_id = brain_action_queue.add(
                            symbol=symbol, action='CLOSE', reason=reason,
                            decision_id=decision_id,
                            execute_fn=lambda t=trade_snap, p=pos_snap, r=reason: self._brain_close(t, p, r),
                        )
                        await notification_sender.notify_brain_action_approval(
                            action_id=action_id, symbol=symbol, action='CLOSE', reason=reason,
                        )
                    else:
                        await self._brain_close(trade_snap, pos_snap, reason)

        except Exception as e:
            logger.error(f"❌ Brain position review failed: {e}")

    async def _brain_modify_sl(self, trade: dict, position: dict, new_sl: float, reason: str):
        try:
            pos_id = position.get('id')
            current_tp = position.get('takeProfit')
            async with trade_modification_lock(trade['id'], caller='brain_modify_sl'):
                await self.trading_provider.modify_position(pos_id, stop_loss=new_sl, take_profit=current_tp)
                await db_service.update_trade_field(trade['id'], 'stopLoss', new_sl)
            await db_service.log_trade_action(
                trade_id=trade['id'], action_type='BRAIN_MODIFY_SL', success=True,
                new_sl=new_sl, triggered_by='trading_brain',
                details=f"Brain: {reason}"
            )
            logger.success(f"🧠 Brain moved SL to {new_sl} — {reason}")
            # Notify via Telegram
            from src.integrations.telegram.unified_sender import notification_sender
            symbol = position.get('symbol', trade.get('symbol', '?'))
            await notification_sender.send_message(
                f"🧠 Moved SL to <code>{new_sl}</code> on <b>{symbol}</b> — {reason}",
                category='position_management'
            )
            # Forward reply to signal channel
            try:
                from src.services.signal_forwarder_service import signal_forwarder_service
                await signal_forwarder_service.reply_brain_sl(trade.get('signalId'), new_sl, reason, trade_id=trade.get('id'))
            except Exception as _exc:
                logger.debug(f"Suppressed exception: {_exc!r}")
        except Exception as e:
            logger.error(f"❌ Brain modify SL failed: {e}")

    async def _brain_modify_tp(self, trade: dict, position: dict, new_tp: float, reason: str):
        try:
            pos_id = position.get('id')
            current_sl = position.get('stopLoss')
            async with trade_modification_lock(trade['id'], caller='brain_modify_tp'):
                await self.trading_provider.modify_position(pos_id, stop_loss=current_sl, take_profit=new_tp)
                await db_service.update_trade_field(trade['id'], 'takeProfit', new_tp)
            await db_service.log_trade_action(
                trade_id=trade['id'], action_type='BRAIN_MODIFY_TP', success=True,
                triggered_by='trading_brain',
                details=f"Brain: {reason}"
            )
            logger.success(f"🧠 Brain moved TP to {new_tp} — {reason}")
            # Forward reply to signal channel
            try:
                from src.services.signal_forwarder_service import signal_forwarder_service
                await signal_forwarder_service.reply_brain_tp(trade.get('signalId'), new_tp, reason, trade_id=trade.get('id'))
            except Exception as _exc:
                logger.debug(f"Suppressed exception: {_exc!r}")
        except Exception as e:
            logger.error(f"❌ Brain modify TP failed: {e}")

    async def _brain_partial_close(self, trade: dict, position: dict, percentage: float, reason: str):
        try:
            pos_id = position.get('id')
            volume = position.get('volume', 0)
            if volume <= 0:
                return
            symbol = position.get('symbol', trade.get('symbol', ''))

            # Resolve the broker's real minimum for this symbol — never assume 0.01
            try:
                spec = await self.trading_provider.get_symbol_specification(symbol)
                volume_min = max(spec.get('volumeMin', settings.min_lot_size), settings.min_lot_size)
            except Exception as e:
                volume_min = settings.min_lot_size
                logger.warning(f"⚠️ {symbol}: broker volume spec unavailable for partial close — "
                               f"assuming minimum lot {volume_min}: {e}")

            close_volume = await self.trading_provider.round_lot_size(symbol, volume * (percentage / 100))
            remaining_volume = volume - close_volume

            # A "partial" that leaves nothing behind is a full close in disguise. On a
            # min-lot position there is no volume to give up, so protect it with
            # breakeven instead of surrendering the runner.
            if remaining_volume < volume_min - 0.001:
                logger.info(
                    f"⚖️ Brain partial ({percentage}%) on {symbol} would close the whole "
                    f"{volume}-lot position (broker min {volume_min}) — moving to breakeven instead"
                )
                await db_service.log_trade_action(
                    trade_id=trade['id'], action_type='BRAIN_PARTIAL_SKIPPED_MIN_LOT', success=True,
                    triggered_by='trading_brain',
                    details=f"Brain wanted {percentage}% close but volume {volume} is at broker minimum {volume_min}: {reason}"
                )
                await self._breakeven_fallback(trade, position, reason=f"min-lot, brain wanted {percentage}% partial")
                return

            await self.trading_provider.close_position(pos_id, volume=close_volume)
            await db_service.log_trade_action(
                trade_id=trade['id'], action_type='BRAIN_PARTIAL_CLOSE', success=True,
                triggered_by='trading_brain',
                details=f"Brain: {reason} — closed {percentage}% ({close_volume} lots)"
            )
            logger.success(f"🧠 Brain partial close {percentage}% ({close_volume} lots) — {reason}")
            from src.integrations.telegram.unified_sender import notification_sender
            symbol = position.get('symbol', trade.get('symbol', '?'))
            await notification_sender.send_message(
                f"🧠 Closed {percentage}% on <b>{symbol}</b> ({close_volume} lots) — {reason}",
                category='position_management'
            )
            # Forward reply to signal channel
            try:
                from src.services.signal_forwarder_service import signal_forwarder_service
                await signal_forwarder_service.reply_brain_partial(trade.get('signalId'), percentage, close_volume, reason, trade_id=trade.get('id'))
            except Exception as _exc:
                logger.debug(f"Suppressed exception: {_exc!r}")
        except Exception as e:
            logger.error(f"❌ Brain partial close failed: {e}")

    async def _brain_close(self, trade: dict, position: dict, reason: str):
        try:
            pos_id = position.get('id')
            await self.trading_provider.close_position(pos_id)
            await db_service.log_trade_action(
                trade_id=trade['id'], action_type='BRAIN_CLOSE', success=True,
                triggered_by='trading_brain',
                details=f"Brain: {reason}"
            )
            logger.success(f"🧠 Brain closed position {pos_id[:8]}... — {reason}")
            from src.integrations.telegram.unified_sender import notification_sender
            symbol = position.get('symbol', trade.get('symbol', '?'))
            await notification_sender.send_message(
                f"🧠 Closed <b>{symbol}</b> — {reason}",
                category='position_management'
            )
            # Forward reply to signal channel
            try:
                from src.services.signal_forwarder_service import signal_forwarder_service
                await signal_forwarder_service.reply_brain_close(trade.get('signalId'), reason, trade_id=trade.get('id'))
            except Exception as _exc:
                logger.debug(f"Suppressed exception: {_exc!r}")
            if self._trading_brain:
                profit = position.get('profit', 0)
                pips = self._calculate_profit_pips(
                    position.get('openPrice', 0),
                    position.get('currentPrice', 0),
                    position.get('type') == 'POSITION_TYPE_BUY',
                    position.get('symbol', '')
                )
                self._trading_brain.notify_position_closed(pos_id, symbol, profit, pips)
        except Exception as e:
            logger.error(f"❌ Brain close failed: {e}")

    async def _apply_auto_take_profit(
        self,
        trade: dict,
        position: dict,
        entry_price: float,
        is_buy: bool
    ):
        """Apply automatic take profit based on settings"""
        try:
            stop_loss = position.get('stopLoss') or trade.get('stopLoss')
            
            if not stop_loss:
                logger.debug(f"Cannot set auto TP without stop loss for position {position.get('id')}")
                return
            
            # Calculate TP based on method
            if settings.auto_tp_calculation_method == CalculationMethod.PIPS.value:
                # TP based on pips
                pip_value = self._get_pip_value(position.get('symbol'))
                if is_buy:
                    take_profit = entry_price + (settings.auto_tp_pips * pip_value)
                else:
                    take_profit = entry_price - (settings.auto_tp_pips * pip_value)
            else:
                # TP based on Risk-Reward ratio
                sl_distance = abs(entry_price - stop_loss)
                if is_buy:
                    take_profit = entry_price + (sl_distance * settings.auto_tp_risk_reward)
                else:
                    take_profit = entry_price - (sl_distance * settings.auto_tp_risk_reward)
            
            # Round to appropriate decimal places
            take_profit = await self._round_to_symbol_digits(position.get('symbol'), take_profit)
            
            logger.info(f"📈 Setting auto TP for position {position.get('id')}: {take_profit}")
            
            # Modify position
            try:
                async with trade_modification_lock(trade['id'], caller='auto_tp'):
                    await self.trading_provider.modify_position(
                        position.get('id'),
                        stop_loss=stop_loss,
                        take_profit=take_profit
                    )
                    # Persist new TP and modification time
                    await db_service.update_trade_field(trade['id'], 'takeProfit', take_profit)
                    await db_service.update_trade_field(trade['id'], 'lastModifiedAt', datetime.now(timezone.utc))
                trade['takeProfit'] = take_profit

                # Log to database
                await db_service.log_trade_action(
                    trade_id=trade['id'],
                    action_type='AUTO_TP',
                    success=True,
                    old_tp=None,
                    new_tp=take_profit,
                    triggered_by='auto_position_monitor',
                    trigger_source='auto_tp',
                    details=f"Auto TP set using {settings.auto_tp_calculation_method} method"
                )
                # Forward reply to signal channel
                try:
                    from src.services.signal_forwarder_service import signal_forwarder_service
                    await signal_forwarder_service.reply_auto_tp(trade.get('signalId'), take_profit, trade_id=trade.get('id'))
                except Exception as _exc:
                    logger.debug(f"Suppressed exception: {_exc!r}")

                logger.success(f"✅ Auto TP set: {take_profit}")
            
            except ValueError as e:
                # Validation error - log but don't raise
                logger.warning(f"⚠️ Cannot set auto TP: {str(e)}")
                
        except Exception as e:
            logger.error(f"Failed to set auto TP: {str(e)}")
    
    async def _apply_auto_partial(
        self,
        trade: dict,
        position: dict,
        entry_price: float,
        is_buy: bool,
        current_price: float,
        profit_pips: float
    ) -> bool:
        """Apply automatic partial profit taking based on settings. Returns True if partial was executed."""
        try:
            # CRITICAL: Position must be in profit to take partial
            if profit_pips <= 0:
                logger.debug(f"⏭️ Skipping auto partial: position in loss ({profit_pips:.1f} pips)")
                return False

            # CRITICAL: Check if partial was already taken by comparing volumes
            current_volume = position.get('volume', 0)
            original_volume = trade.get('volume') or trade.get('originalVolume')

            if original_volume and current_volume < original_volume * 0.95:  # 5% tolerance for floating point
                logger.debug(f"⏭️ Skipping auto partial: volume already reduced ({current_volume} < {original_volume}) - partial likely already taken")
                # Update flag if not set — this means manual partial was taken outside the bot
                if not trade.get('autoPartialActivated', False):
                    await db_service.update_trade_field(trade['id'], 'autoPartialActivated', True)
                    trade['autoPartialActivated'] = True
                    # Notify forwarding channel that a manual partial was detected
                    try:
                        from src.services.signal_forwarder_service import signal_forwarder_service
                        signal_id = trade.get('signalId')
                        closed_pct = round((1 - current_volume / original_volume) * 100)
                        current_price_val = position.get('currentPrice') or position.get('openPrice', '')
                        await signal_forwarder_service.reply_partial_close(
                            signal_id, closed_pct, original_volume - current_volume, current_price_val, profit_pips,
                            trade_id=trade.get('id'),
                        )
                        # BE reminder if auto-BE won't fire
                        be_will_auto_fire = (
                            settings.enable_breakeven_move
                            and settings.breakeven_trigger_method == "AFTER_PARTIAL"
                            and not trade.get('breakEvenActivated', False)
                        )
                        if not be_will_auto_fire:
                            await signal_forwarder_service.reply_be_reminder(signal_id, entry_price, trade_id=trade.get('id'))
                    except Exception as _exc:
                        logger.debug(f"Suppressed exception: {_exc!r}")
                    logger.info(f"📊 Manual partial detected for trade {trade['id'][:8]}...: {original_volume} → {current_volume} lots ({closed_pct}% closed)")
                return False

            # Check if profit threshold is met
            should_take_partial = False

            if settings.auto_partial_calculation_method == CalculationMethod.PIPS.value:
                # Partial based on pips
                if profit_pips >= settings.auto_partial_trigger_pips:
                    should_take_partial = True
            else:
                # Partial based on Risk-Reward ratio
                # Use DB originalStopLoss → DB stopLoss → live broker stopLoss (fallback)
                stop_loss = trade.get('originalStopLoss') or trade.get('stopLoss') or position.get('stopLoss')
                if not stop_loss:
                    logger.warning(
                        f"⚠️ Auto partial skipped: no stop loss found for trade {trade['id'][:8]}... "
                        f"(originalStopLoss={trade.get('originalStopLoss')}, "
                        f"stopLoss={trade.get('stopLoss')}, "
                        f"broker_sl={position.get('stopLoss')})"
                    )
                    return False

                sl_distance = abs(entry_price - stop_loss)

                # Calculate profit distance (must be positive for profit)
                if is_buy:
                    profit_distance = current_price - entry_price
                else:
                    profit_distance = entry_price - current_price

                # Only calculate RR if in profit
                if profit_distance > 0 and sl_distance > 0:
                    current_rr = profit_distance / sl_distance
                    logger.debug(f"📊 Auto partial RR check: current={current_rr:.2f} trigger={settings.auto_partial_trigger_rr} profit={profit_pips:.1f}pips")
                    if current_rr >= settings.auto_partial_trigger_rr:
                        should_take_partial = True

            if not should_take_partial:
                return False
            
            # Calculate partial close volume
            symbol = position.get('symbol')
            current_volume = position.get('volume', 0)
            
            # Get symbol specification for proper validation
            spec = await self.trading_provider.get_symbol_specification(symbol)
            volume_min = spec.get('volumeMin', 0.01)
            
            close_volume_raw = current_volume * (settings.auto_partial_close_percent / 100.0)
            
            # Round to broker's volume step for this symbol
            close_volume = await self.trading_provider.round_lot_size(symbol, close_volume_raw)
            remaining_volume = current_volume - close_volume
            
            # Validate minimum lot sizes using broker's volumeMin
            if close_volume < volume_min:
                logger.debug(f"Partial close volume {close_volume} below broker minimum {volume_min} lots")
                return False

            if remaining_volume < volume_min and remaining_volume > 0.001:  # Allow for floating point errors
                logger.debug(f"Remaining volume {remaining_volume} would be below broker minimum {volume_min} lots - skipping auto partial")
                return False

            # Position is at (or below) broker minimum — a partial would close it entirely.
            # Never give up a min-lot runner: mark the partial "done" so an AFTER_PARTIAL
            # breakeven still fires and protects the trade instead of stalling forever.
            if current_volume <= volume_min + 0.001:
                logger.info(
                    f"⚖️ Position {position.get('id')} at broker minimum ({current_volume} lots) — "
                    f"skipping partial close, deferring to breakeven"
                )
                await db_service.update_trade_field(trade['id'], 'autoPartialActivated', True)
                trade['autoPartialActivated'] = True
                await db_service.log_trade_action(
                    trade_id=trade['id'],
                    action_type='AUTO_PARTIAL_SKIPPED_MIN_LOT',
                    success=True,
                    triggered_by='auto_position_monitor',
                    trigger_source='auto_partial_trigger',
                    details=(
                        f"Partial skipped: volume {current_volume} at broker minimum {volume_min}. "
                        f"Position left open at {profit_pips:.1f} pips; breakeven will protect it."
                    )
                )
                return False
            
            logger.info(f"💰 Auto Partial triggered for position {position.get('id')}")
            logger.info(f"   Method: {settings.auto_partial_calculation_method}")
            logger.info(f"   Current profit: {profit_pips:.1f} pips")
            logger.info(f"   Closing {settings.auto_partial_close_percent}% ({close_volume} lots of {current_volume} lots)")
            logger.debug(f"   Remaining after close: {remaining_volume} lots")
            
            # Close partial position
            try:
                await self.trading_provider.close_position(
                    position.get('id'),
                    volume=close_volume
                )
            except Exception as e:
                logger.error(f"❌ Auto partial close_position failed: {str(e)}")
                return False

            # Update database (only reached if close succeeded)
            await db_service.update_trade_field(trade['id'], 'autoPartialActivated', True)
            await db_service.update_trade_field(trade['id'], 'lastModifiedAt', datetime.now(timezone.utc))

            # Update local trade dict so subsequent checks in the same cycle see the updated flag
            trade['autoPartialActivated'] = True
            trade['lastModifiedAt'] = datetime.now(timezone.utc)

            # Log to database for audit trail
            await db_service.log_trade_action(
                trade_id=trade['id'],
                action_type='AUTO_PARTIAL',
                success=True,
                triggered_by='auto_position_monitor',
                trigger_source='auto_partial_trigger',
                details=f"Auto partial: {settings.auto_partial_close_percent}% ({close_volume} lots) at {profit_pips:.1f} pips profit using {settings.auto_partial_calculation_method} method"
            )

            # Propagate partial close to signal status (RUNNING → PARTIALLY_CLOSED)
            signal_id = trade.get('signalId')
            if signal_id:
                await db_service.update_signal_status_from_trades(signal_id)

            # Forward reply to signal channel
            try:
                from src.services.signal_forwarder_service import signal_forwarder_service
                current_price_val = position.get('currentPrice') or position.get('openPrice', '')
                _pct = settings.auto_partial_close_percent
                await signal_forwarder_service.reply_partial_close(signal_id, _pct, close_volume, current_price_val, profit_pips, trade_id=trade.get('id'))

                # If auto-BE is off or won't fire after partial, warn user so SL hit = no loss
                be_will_auto_fire = (
                    settings.enable_breakeven_move
                    and settings.breakeven_trigger_method == "AFTER_PARTIAL"
                    and not trade.get('breakEvenActivated', False)
                )
                if not be_will_auto_fire:
                    await signal_forwarder_service.reply_be_reminder(signal_id, entry_price, trade_id=trade.get('id'))
            except Exception as _exc:
                logger.debug(f"Suppressed exception: {_exc!r}")

            logger.success(f"✅ Auto partial executed: {close_volume} lots closed at {profit_pips:.1f} pips profit")
            return True

        except Exception as e:
            logger.error(f"Failed to execute auto partial: {str(e)}")
            return False
    
    async def _should_trigger_breakeven(
        self,
        trade: dict,
        profit_pips: float
    ) -> bool:
        """Check if breakeven should be triggered based on configured method"""
        # CRITICAL: Position must be in profit to move to breakeven
        if profit_pips <= 0:
            logger.debug(f"⏭️ Skipping breakeven: position in loss ({profit_pips:.1f} pips)")
            return False
        
        method = settings.breakeven_trigger_method
        
        if method == BreakevenTriggerMethod.AFTER_PARTIAL.value:
            # Only trigger BE after auto partial has been taken AND position is still in profit
            return trade.get('autoPartialActivated', False) and profit_pips > 0
        
        elif method == BreakevenTriggerMethod.PROFIT_PIPS.value:
            # Trigger BE after profit threshold
            return profit_pips >= settings.breakeven_trigger_pips
        
        elif method == BreakevenTriggerMethod.AFTER_SIBLING_TP_HIT.value:
            # Trigger BE when sibling trades from same signal hit their TP (for multi-TP signals)
            return await self._check_sibling_tp_hits(trade)
        
        return False
    
    async def _check_sibling_tp_hits(self, trade: dict) -> bool:
        """
        Check if sibling trades (from the same signal) have hit their TP targets.
        Used for multi-TP signals to protect remaining positions after some TPs are hit.
        
        Args:
            trade: Current trade to check
            
        Returns:
            True if enough sibling trades have closed at profit (hit TP)
        """
        try:
            signal_id = trade.get('signalId')
            if not signal_id:
                logger.debug("⏭️ Trade has no signalId - skipping sibling TP check")
                return False
            
            # Get all trades for this signal
            all_trades = await db_service.get_trades_by_signal_id(signal_id)
            
            if len(all_trades) <= 1:
                # Not a multi-TP signal (only one trade)
                logger.debug("⏭️ Single trade signal - sibling TP check not applicable")
                return False
            
            # Count how many sibling trades have closed with profit (TP hit)
            current_trade_id = trade.get('id')
            closed_at_profit = 0
            
            for sibling in all_trades:
                # Skip the current trade
                if sibling.get('id') == current_trade_id:
                    continue
                
                # Check if trade is CLOSED with profit
                if sibling.get('status') == 'CLOSED':
                    profit = sibling.get('profitLoss', 0) or sibling.get('profit', 0)
                    if profit > 0:
                        closed_at_profit += 1
            
            min_hits = settings.breakeven_min_sibling_tp_hits
            
            if closed_at_profit >= min_hits:
                logger.info(f"✅ Sibling TP trigger: {closed_at_profit}/{len(all_trades)-1} sibling trades closed at profit (min: {min_hits})")
                return True
            else:
                logger.debug(f"⏭️ Not enough sibling TPs hit: {closed_at_profit}/{len(all_trades)-1} (need {min_hits})")
                return False
                
        except Exception as e:
            logger.error(f"Error checking sibling TP hits: {str(e)}")
            return False
    
    async def _breakeven_fallback(self, trade: dict, position: dict, reason: str) -> bool:
        """
        Protect a position we deliberately refused to close (min-lot) by moving to breakeven.

        Used when a partial close would have wiped out the whole position. Respects the
        breakeven enable flags but bypasses the *trigger* check — the caller already
        established the position is in profit far enough to warrant taking something off.
        """
        if not (settings.enable_breakeven_move and trade.get('breakEvenEnabled', True)):
            logger.info(f"⏭️ Breakeven fallback skipped ({reason}) — breakeven disabled for this trade")
            return False

        if trade.get('breakEvenActivated', False):
            logger.debug(f"Breakeven fallback skipped ({reason}) — already at breakeven")
            return False

        entry_price = position.get('openPrice') or trade.get('entryPrice')
        current_price = position.get('currentPrice')
        if not entry_price or not current_price:
            logger.warning(f"⚠️ Breakeven fallback skipped ({reason}) — missing entry/current price")
            return False

        is_buy = position.get('type') == 'POSITION_TYPE_BUY'
        profit_pips = self._calculate_profit_pips(
            entry_price, current_price, is_buy, position.get('symbol', '')
        )

        await self._move_to_breakeven(trade, position, entry_price, is_buy, current_price, profit_pips)
        return True

    async def _move_to_breakeven(
        self,
        trade: dict,
        position: dict,
        entry_price: float,
        is_buy: bool,
        current_price: float,
        profit_pips: float
    ):
        """Move stop loss to breakeven"""
        try:
            current_sl = position.get('stopLoss')
            
            # Calculate breakeven SL with buffer
            pip_value = self._get_pip_value(position.get('symbol'))
            buffer = settings.breakeven_buffer_pips * pip_value
            
            # FIXED: Only require buffer + small safety margin (not hardcoded 15 pips)
            # The profit_pips check already validated we meet trigger threshold
            min_profit_distance = buffer + (3 * pip_value)  # Just 3 pips safety margin
            
            if is_buy:
                # For BUY: current price must be sufficiently above entry
                price_movement = current_price - entry_price
                if price_movement < min_profit_distance:
                    logger.debug(f"⏭️ Skipping breakeven: insufficient profit (current {current_price} vs entry {entry_price}, need {min_profit_distance:.5f} movement)")
                    return
            else:
                # For SELL: current price must be sufficiently below entry
                price_movement = entry_price - current_price
                if price_movement < min_profit_distance:
                    logger.debug(f"⏭️ Skipping breakeven: insufficient profit (current {current_price} vs entry {entry_price}, need {min_profit_distance:.5f} movement)")
                    return
            
            if is_buy:
                new_sl = entry_price + buffer
            else:
                new_sl = entry_price - buffer
            
            new_sl = await self._round_to_symbol_digits(position.get('symbol'), new_sl)
            
            # Apply spread adjustment
            adjusted_sl = await spread_adjustment_service.adjust_sl_for_spread(
                position.get('symbol'),
                new_sl,
                is_buy
            )
            if adjusted_sl != new_sl:
                logger.info(f"📊 Breakeven SL adjusted for spread: {new_sl:.5f} → {adjusted_sl:.5f}")
                new_sl = adjusted_sl
            
            # CRITICAL: Breakeven SL must never be worse than the actual entry price.
            # The spread adjustment can push the SL below entry for BUY (or above for SELL),
            # which defeats the purpose of breakeven. Clamp to at least entry price.
            if is_buy and new_sl < entry_price:
                logger.info(f"📊 Breakeven SL {new_sl:.5f} below entry {entry_price:.5f} after spread adj → clamping to entry")
                new_sl = await self._round_to_symbol_digits(position.get('symbol'), entry_price)
            elif not is_buy and new_sl > entry_price:
                logger.info(f"📊 Breakeven SL {new_sl:.5f} above entry {entry_price:.5f} after spread adj → clamping to entry")
                new_sl = await self._round_to_symbol_digits(position.get('symbol'), entry_price)
            
            # Only move if new SL is better than current
            # Skip comparison if current_sl is None (no SL set yet)
            if current_sl is not None:
                if is_buy and new_sl <= current_sl:
                    return
                if not is_buy and new_sl >= current_sl:
                    return
            
            # FIXED: Reduce minimum distance requirement (was 10 pips, too strict)
            # Use broker's stop level or 3 pips minimum
            min_distance = 3 * pip_value  # Reduced from 10 to 3 pips
            
            if is_buy:
                # For buy positions, SL must be below current price
                if new_sl >= current_price:
                    logger.warning(f"⚠️ Cannot move to breakeven: new SL ({new_sl}) >= current price ({current_price})")
                    return
                # Check minimum distance (now 3 pips instead of 10)
                if (current_price - new_sl) < min_distance:
                    logger.debug(f"⏭️ Breakeven too close to current price, waiting... (distance: {(current_price - new_sl)/pip_value:.1f} pips, need 3+)")
                    return
            else:
                # For sell positions, SL must be above current price
                if new_sl <= current_price:
                    logger.warning(f"⚠️ Cannot move to breakeven: new SL ({new_sl}) <= current price ({current_price})")
                    return
                # Check minimum distance (now 3 pips instead of 10)
                if (new_sl - current_price) < min_distance:
                    logger.debug(f"⏭️ Breakeven too close to current price, waiting... (distance: {(new_sl - current_price)/pip_value:.1f} pips, need 3+)")
                    return
            
            logger.info(f"🎯 Moving to breakeven for position {position.get('id')}")
            logger.info(f"   Entry: {entry_price}, Current: {current_price}, New SL: {new_sl} (+{settings.breakeven_buffer_pips} pips buffer)")
            
            # Modify position
            try:
                async with trade_modification_lock(trade['id'], caller='breakeven'):
                    await self.trading_provider.modify_position(
                        position.get('id'),
                        stop_loss=new_sl,
                        take_profit=position.get('takeProfit')
                    )
                    # Update database
                    await db_service.update_trade_field(trade['id'], 'stopLoss', new_sl)
                    await db_service.update_trade_field(trade['id'], 'breakEvenActivated', True)
                    await db_service.update_trade_field(trade['id'], 'lastModifiedAt', datetime.now(timezone.utc))

                # Update local trade dict so subsequent checks in the same cycle see the updated flag
                trade['stopLoss'] = new_sl
                trade['breakEvenActivated'] = True
                trade['lastModifiedAt'] = datetime.now(timezone.utc)

                # Log to database for audit trail
                await db_service.log_trade_action(
                    trade_id=trade['id'],
                    action_type='BREAKEVEN',
                    success=True,
                    old_sl=current_sl,
                    new_sl=new_sl,
                    triggered_by='auto_position_monitor',
                    trigger_source='breakeven_trigger',
                    details=f"Moved to breakeven at {profit_pips:.1f} pips profit"
                )
                # Forward reply to signal channel
                try:
                    from src.services.signal_forwarder_service import signal_forwarder_service
                    await signal_forwarder_service.reply_breakeven(trade.get('signalId'), new_sl, trade_id=trade.get('id'))
                except Exception as _exc:
                    logger.debug(f"Suppressed exception: {_exc!r}")
            except ValueError as e:
                # Validation error - already logged in modify_position
                logger.debug(f"Breakeven validation failed: {str(e)}")

            logger.success(f"✅ Breakeven activated: SL moved to {new_sl}")
            
            # After breakeven, cancel pending orders for this magic number
            # Reason: Pending orders (like TP orders) will be automatically invalidated after BE + partial close
            # It doesn't make sense to keep them
            await self._cancel_pending_orders_after_breakeven(trade)
            
        except Exception as e:
            logger.error(f"Failed to move to breakeven: {str(e)}")
    
    async def _cancel_pending_orders_after_breakeven(self, trade: dict):
        """
        Cancel pending orders for the magic number after breakeven is triggered.
        
        Reason: After partial closure and hitting breakeven, pending orders (like TP orders)
        will be automatically invalidated. It doesn't make sense to keep them.
        
        Args:
            trade: The trade dict that triggered breakeven
        """
        try:
            magic_number = trade.get('magicNumber')
            if not magic_number:
                logger.debug("No magic number found, skipping pending order cancellation")
                return
            
            # Get all trades (including pending orders) for this magic number
            all_trades = await db_service.get_trades_by_magic_number(magic_number)
            pending_trades = [t for t in all_trades if t.get('status') == 'PENDING']
            
            if not pending_trades:
                logger.debug(f"No pending orders found for magic number {magic_number}")
                return
            
            logger.info(f"🎯 Cancelling {len(pending_trades)} pending order(s) after breakeven for magic number {magic_number}")
            
            cancelled_count = 0
            for pending_trade in pending_trades:
                try:
                    order_id = pending_trade.get('orderId')
                    if order_id:
                        # Cancel order via trading provider
                        await self.trading_provider.cancel_order(order_id)
                        logger.info(f"✅ Cancelled pending order {order_id}")
                    
                    # Update database
                    await db_service.update_trade_field(pending_trade['id'], 'status', 'CANCELLED')
                    await db_service.update_trade_field(pending_trade['id'], 'closedAt', datetime.now())
                    
                    # Log the action
                    await db_service.log_trade_action(
                        trade_id=pending_trade['id'],
                        action_type='CANCEL',
                        success=True,
                        triggered_by='auto_position_monitor',
                        trigger_source='breakeven_pending_order_cancel',
                        details=f'Auto-cancelled pending order after breakeven (magic number: {magic_number})'
                    )
                    
                    cancelled_count += 1
                except Exception as e:
                    logger.error(f"Failed to cancel pending order {pending_trade.get('orderId')}: {str(e)}")
            
            # Update signal status for affected signals
            affected_signal_ids = set(t.get('signalId') for t in pending_trades if t.get('signalId'))
            for signal_id in affected_signal_ids:
                try:
                    await db_service.update_signal_status_from_trades(signal_id)
                except Exception as e:
                    logger.debug(f"Signal status update failed after pending order cancel: {e}")
            
            logger.success(f"✅ Cancelled {cancelled_count} pending order(s) after breakeven")
            
        except Exception as e:
            logger.error(f"Failed to cancel pending orders after breakeven: {str(e)}")
    
    async def _should_activate_trailing(
        self,
        trade: dict,
        profit_pips: float,
        entry_price: float
    ) -> bool:
        """Check if trailing stop should be activated"""
        method = settings.trailing_activation_method
        
        if method == TrailingActivationMethod.IMMEDIATE.value:
            return True
        
        elif method == TrailingActivationMethod.PROFIT_PIPS.value:
            return profit_pips >= settings.trailing_activation_profit_pips
        
        elif method == TrailingActivationMethod.PROFIT_RR.value:
            # Check if profit meets RR requirement
            stop_loss = trade.get('originalStopLoss') or trade.get('stopLoss')
            if not stop_loss:
                return False
            sl_distance = abs(entry_price - stop_loss)
            required_profit = sl_distance * settings.trailing_activation_profit_rr
            pip_value = self._get_pip_value(trade.get('symbol'))
            return abs(profit_pips * pip_value) >= required_profit
        
        elif method == TrailingActivationMethod.PARTIAL_TP.value:
            # Could be extended to check if partial TP was hit
            # For now, use profit pips as fallback
            return profit_pips >= settings.trailing_activation_profit_pips
        
        return False
    
    async def _activate_trailing(
        self,
        trade: dict,
        position: dict,
        current_price: float,
        is_buy: bool,
        profit_pips: float
    ):
        """Activate trailing stop"""
        try:
            logger.info(f"🔄 Activating trailing stop for position {position.get('id')}")
            
            # Update database
            await db_service.update_trade_field(trade['id'], 'trailingActivated', True)
            await db_service.update_trade_field(trade['id'], 'lastModifiedAt', datetime.now(timezone.utc))
            
            # Update local trade dict so subsequent checks in the same cycle see the updated flag
            trade['trailingActivated'] = True
            trade['lastModifiedAt'] = datetime.now(timezone.utc)
            
            # Log action
            await self._log_trade_action(
                trade_id=trade['id'],
                action_type=TradeActionType.TRAILING_STOP,
                current_price=current_price,
                profit_pips=profit_pips,
                details=f"Trailing stop activated (method: {settings.trailing_activation_method})"
            )
            
            logger.success(f"✅ Trailing stop activated at {profit_pips:.1f} pips profit")
            
        except Exception as e:
            logger.error(f"Failed to activate trailing: {str(e)}")
    
    async def _apply_trailing_stop(
        self,
        trade: dict,
        position: dict,
        current_price: float,
        is_buy: bool,
        profit_pips: float
    ):
        """Apply trailing stop logic"""
        try:
            current_sl = position.get('stopLoss')
            
            if not current_sl:
                logger.debug(f"No stop loss set for position {position.get('id')}")
                return
            
            # Calculate new trailing stop
            if settings.trailing_stop_calculation_method == CalculationMethod.PIPS.value:
                # Trail by fixed pips
                pip_value = self._get_pip_value(position.get('symbol'))
                trailing_distance = settings.trailing_stop_distance_pips * pip_value
                
                if is_buy:
                    new_sl = current_price - trailing_distance
                else:
                    new_sl = current_price + trailing_distance
            
            else:
                # Trail by RR ratio
                entry_price = position.get('openPrice') or trade.get('entryPrice')
                original_sl = trade.get('originalStopLoss') or trade.get('stopLoss')
                
                if not entry_price or not original_sl:
                    return
                
                sl_distance = abs(entry_price - original_sl)
                trailing_distance = sl_distance * settings.trailing_stop_distance_rr
                
                if is_buy:
                    new_sl = current_price - trailing_distance
                else:
                    new_sl = current_price + trailing_distance
            
            new_sl = await self._round_to_symbol_digits(position.get('symbol'), new_sl)
            
            # Apply spread adjustment to trailing SL
            adjusted_sl = await spread_adjustment_service.adjust_sl_for_spread(
                position.get('symbol'),
                new_sl,
                is_buy
            )
            if adjusted_sl != new_sl:
                logger.debug(f"📊 Trailing SL adjusted for spread: {new_sl:.5f} → {adjusted_sl:.5f}")
                new_sl = adjusted_sl
            
            # Only move SL if it's better than current
            should_update = False
            if is_buy and new_sl > current_sl:
                should_update = True
            elif not is_buy and new_sl < current_sl:
                should_update = True
            
            # Throttle: ignore tiny improvements and rapid-fire modifications (broker rate limits,
            # DB/audit/Telegram spam). Live streamed prices make every tick a candidate otherwise.
            if should_update:
                pip = self._get_pip_value(position.get('symbol')) or 0.0001
                min_step = float(getattr(settings, 'trailing_stop_min_step_pips', 0) or 0) * pip
                if abs(new_sl - current_sl) < min_step:
                    should_update = False
                else:
                    min_gap = float(getattr(settings, 'trailing_stop_min_interval_seconds', 0) or 0)
                    last = self._last_trail_at.get(trade['id'])
                    if last is not None and (time.monotonic() - last) < min_gap:
                        should_update = False

            if should_update:
                self._last_trail_at[trade['id']] = time.monotonic()
                logger.info(f"📉 Trailing SL for position {position.get('id')}: {current_sl} → {new_sl}")
                
                # Modify position
                try:
                    async with trade_modification_lock(trade['id'], caller='trailing_sl'):
                        await self.trading_provider.modify_position(
                            position.get('id'),
                            stop_loss=new_sl,
                            take_profit=position.get('takeProfit')
                        )
                        # Update database - persist new SL
                        await db_service.update_trade_field(trade['id'], 'stopLoss', new_sl)
                        await db_service.update_trade_field(trade['id'], 'lastModifiedAt', datetime.now(timezone.utc))
                    trade['stopLoss'] = new_sl

                    # Log action
                    await self._log_trade_action(
                        trade_id=trade['id'],
                        action_type=TradeActionType.TRAILING_STOP,
                        old_sl=current_sl,
                        new_sl=new_sl,
                        current_price=current_price,
                        profit_pips=profit_pips,
                        details=f"Trailing stop moved (distance: {settings.trailing_stop_distance_pips} pips)"
                    )
                    # Forward reply to signal channel
                    try:
                        from src.services.signal_forwarder_service import signal_forwarder_service
                        await signal_forwarder_service.reply_trailing_sl(trade.get('signalId'), new_sl, trade_id=trade.get('id'))
                    except Exception as _exc:
                        logger.debug(f"Suppressed exception: {_exc!r}")

                    logger.success(f"✅ Trailing SL updated: {new_sl}")

                except ValueError as e:
                    # Validation error - already logged in modify_position
                    logger.debug(f"Trailing stop validation failed: {str(e)}")
        
        except Exception as e:
            logger.error(f"Failed to apply trailing stop: {str(e)}")
    
    @staticmethod
    def _position_age_seconds(position: dict) -> Optional[float]:
        """Seconds since the position opened, or None if the time is missing/unparseable."""
        t = position.get('openTime') or position.get('time')
        try:
            if isinstance(t, datetime):
                dt = t
            elif isinstance(t, (int, float)):
                return max(0.0, datetime.now(timezone.utc).timestamp() - float(t))
            elif isinstance(t, str) and t:
                dt = datetime.fromisoformat(t.replace('Z', '+00:00'))
            else:
                return None
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())
        except Exception:
            return None

    async def _round_to_symbol_digits(self, symbol: str, price: float) -> float:
        """Round a price to the symbol's broker digits (falls back to 5)."""
        digits = 5
        try:
            spec = await self.trading_provider.get_symbol_specification(symbol)
            digits = int(spec.get('digits', 5))
        except Exception as e:
            logger.debug(f"Could not read digits for {symbol}, using 5: {e}")
        return round(price, digits)

    async def _update_price_tracking(self, trade: dict, current_price: float, is_buy: bool):
        """Update highest/lowest price tracking for position"""
        try:
            if is_buy:
                highest = trade.get('highestPrice')
                if highest is None or current_price > highest:
                    await db_service.update_trade_field(trade['id'], 'highestPrice', current_price)
            else:
                lowest = trade.get('lowestPrice')
                if lowest is None or current_price < lowest:
                    await db_service.update_trade_field(trade['id'], 'lowestPrice', current_price)
        except Exception as e:
            logger.debug(f"Failed to update price tracking: {str(e)}")
    
    async def _check_for_closed_positions(self, open_positions: List[dict]):
        """
        Deprecated: closure detection is now handled exclusively by order_sync_service.
        Kept as a stub so existing callers don't break during the transition.
        """
        pass

    async def _check_for_closed_positions_DEPRECATED_BODY(self, open_positions: List[dict]):
        """
        Original body preserved for reference only – NOT called.
        """
        try:
            open_position_ids = {pos.get('id') for pos in open_positions if pos.get('id')}
            executed_trades = await db_service.db.trade.find_many(
                where={"status": "RUNNING", "positionId": {"not": None}}
            )
            
            # Check each executed trade to see if its position is still open
            for trade in executed_trades:
                position_id = trade.positionId
                if position_id and position_id not in open_position_ids:
                    # Increment missing count for this position
                    self._position_missing_counts[position_id] = self._position_missing_counts.get(position_id, 0) + 1
                    
                    # LOGGING POLICY:
                    # - 1st miss: Silent (could be a transient API glitch)
                    # - 2nd miss: Warning (suspicion)
                    # - 3rd miss: Confirmation (proceed to close)
                    
                    missing_count = self._position_missing_counts[position_id]
                    
                    if missing_count < 3:
                        if missing_count == 2:
                            logger.warning(f"⚠️ Position {position_id[:8]}... MISSING (2nd time) - waiting for 3rd confirmation before closing")
                        continue
                        
                    # Position is confirmed closed (3rd consecutive miss)
                    logger.success(f"🛑 Position {position_id[:8]}... CONFIRMED CLOSED after {missing_count} misses")
                    
                    # Cleanup tracking
                    if position_id in self._position_missing_counts:
                        del self._position_missing_counts[position_id]
                    
                    # FETCH ACTUAL RESULTS...

                    # Get the latest profit from the database (most recent update from position monitor)
                    current_trade = await db_service.db.trade.find_unique(
                        where={"id": trade.id}
                    )
                    
                    deals = None
                    total_profit = None
                    profit_pips = None
                    current_price = None
                    
                    if current_trade and current_trade.profitLoss is not None:
                        # Use last known DB profit (accurate within 3 seconds)
                        total_profit = current_trade.profitLoss
                        profit_pips = current_trade.profitLossPips
                        logger.info(f"📊 Using cached database profit: ${total_profit:.2f} ({profit_pips:+.1f} pips)")
                        
                        # Get price from cache
                        cached_data = self._position_data_cache.get(position_id, {})
                        current_price = cached_data.get('current_price')
                    else:
                        # Fallback: Fetch ACTUAL deal history from trading provider (slower but accurate)
                        logger.info("📊 No cached profit, fetching deal history...")
                        deals = await self.trading_provider.get_deals_by_position(position_id)
                    
                    if deals:
                        # Calculate actual total profit from all deals
                        actual_profit = 0
                        for deal in deals:
                            if isinstance(deal, dict):
                                actual_profit += deal.get('profit', 0)
                        
                        # Get the last deal's closing price and pips from MetaStats
                        last_deal = deals[-1] if deals else None
                        close_price = last_deal.get('price') if (last_deal and isinstance(last_deal, dict)) else None
                        
                        # Try to get pips from MetaStats first (most accurate)
                        profit_pips = last_deal.get('pips') if last_deal else None
                        
                        logger.info(f"✅ Deal history fetched: {len(deals)} deal(s), actual profit: ${actual_profit:.2f}")
                        
                        # Calculate pips if not provided by MetaStats
                        if profit_pips is None and close_price and trade.entryPrice:
                            symbol = trade.symbol
                            pip_value = self._get_pip_value(symbol)
                            
                            if trade.action == 'BUY':
                                profit_pips = (close_price - trade.entryPrice) / pip_value
                            else:
                                profit_pips = (trade.entryPrice - close_price) / pip_value
                        
                        total_profit = actual_profit
                        current_price = close_price
                    elif total_profit is None:
                        # No cached profit and no deal history - use memory cache as last resort
                        logger.warning(f"⚠️ No deal history found for {position_id[:8]}... - using memory cache")
                        cached_data = self._position_data_cache.get(position_id, {})
                        total_profit = cached_data.get('profit', 0)
                        current_price = cached_data.get('current_price')
                        profit_pips = cached_data.get('profit_pips')
                    
                    # Update trade with closure data including profit/loss
                    await db_service.update_trade_closure(
                        trade_id=trade.id,
                        close_price=current_price,
                        profit_loss=total_profit,
                        profit_loss_pips=profit_pips
                    )
                    
                    # Remove from cache since position is now closed
                    if position_id in self._executed_trades_cache:
                        del self._executed_trades_cache[position_id]
                    if trade.id in self._last_profit_update:
                        del self._last_profit_update[trade.id]
                    
                    # Clear AI analysis notification state for this position
                    if AI_ANALYSIS_AVAILABLE:
                        ai_analysis_service.clear_position_state(position_id)
                    
                    # Check if there's already a recent CLOSE action (within last 60 seconds)
                    # This prevents overwriting user-initiated closes (e.g., from telegram replies)
                    time_threshold = datetime.now(timezone.utc) - timedelta(seconds=60)
                    
                    existing_close_action = await db_service.db.tradeaction.find_first(
                        where={
                            "tradeId": trade.id,
                            "actionType": "CLOSE",
                            "createdAt": {"gte": time_threshold}
                        },
                        order={"createdAt": "desc"}
                    )
                    
                    if existing_close_action:
                        logger.debug(f"⏭️ Skipping duplicate CLOSE action for trade {trade.id[:8]}... - already logged by {existing_close_action.triggeredBy}")
                    else:
                        # Determine closure reason based on trade data
                        closure_reason = 'manual close'
                        if current_price:
                            tp = trade.takeProfit
                            sl = trade.stopLoss
                            # Check if TP was hit (within small tolerance)
                            if tp and abs(current_price - tp) < 0.0001:
                                closure_reason = 'TP hit'
                            # Check if SL was hit
                            elif sl and abs(current_price - sl) < 0.0001:
                                closure_reason = 'SL hit'
                        
                        # Log the closure with cached data
                        details = f'Position closed externally ({closure_reason})'
                        if current_price and profit_pips is not None:
                            details += f'. Profit: ${total_profit:.2f} ({profit_pips:+.1f} pips) at {current_price:.5f}'
                        
                        await db_service.log_trade_action(
                            trade_id=trade.id,
                            action_type='CLOSE',
                            success=True,
                            current_price=current_price,
                            profit_pips=profit_pips,
                            triggered_by='external_closure',
                            trigger_source='position_monitor_sync',
                            details=details
                        )
                        
                        # Clear cached data for this position
                        if position_id in self._position_data_cache:
                            del self._position_data_cache[position_id]
        except Exception as e:
            logger.debug(f"Error checking for closed positions: {str(e)}")
    
    async def _check_for_cancelled_orders(self, open_orders: List[dict]):
        """
        Deprecated: cancellation detection is now handled exclusively by order_sync_service.
        Kept as a stub so existing callers don't break during the transition.
        """
        pass

    async def _check_for_cancelled_orders_DEPRECATED_BODY(self, open_orders: List[dict]):
        """
        Original body preserved for reference only – NOT called.
        """
        try:
            if open_orders is None:
                return
            open_order_ids = {order.get('id') for order in open_orders if order.get('id')}
            pending_trades = await db_service.db.trade.find_many(
                where={"status": "PENDING", "orderId": {"not": None}}
            )
            
            # Check each pending trade to see if its order still exists
            for trade in pending_trades:
                order_id = trade.positionId  # For pending orders, positionId holds the order ID
                if order_id and order_id not in open_order_ids:
                    # Order no longer exists - mark as CANCELLED
                    logger.info(f"📊 Order {order_id[:8]}... no longer in {settings.provider_label} - marking as CANCELLED")
                    
                    # Update to CANCELLED status
                    await db_service.db.trade.update(
                        where={"id": trade.id},
                        data={
                            "status": "CANCELLED",
                            "closedAt": datetime.now(timezone.utc)
                        }
                    )
                    
                    # Log the cancellation
                    await db_service.log_trade_action(
                        trade_id=trade.id,
                        action_type='CANCEL',
                        success=True,
                        triggered_by='position_monitor',
                        trigger_source='cancelled_order_detection',
                        details='Pending order cancelled externally - not found in MetaAPI'
                    )
                    
                    logger.success(f"✅ Order {order_id[:8]}... marked as CANCELLED")
                    
        except Exception as e:
            logger.debug(f"Error checking for cancelled orders: {str(e)}")
    
    async def _get_trade_by_position_id(self, position_id: str) -> Optional[dict]:
        """Get trade record from database by position ID"""
        try:
            trade = await db_service.get_trade_by_position_id(position_id)
            return trade
        except Exception as e:
            logger.debug(f"Could not find trade for position {position_id}: {str(e)}")
            return None
    
    async def _log_trade_action(
        self,
        trade_id: str,
        action_type: TradeActionType,
        old_sl: Optional[float] = None,
        new_sl: Optional[float] = None,
        old_tp: Optional[float] = None,
        new_tp: Optional[float] = None,
        current_price: Optional[float] = None,
        profit_pips: Optional[float] = None,
        details: Optional[str] = None
    ):
        """Log a trade action to the database"""
        try:
            await db_service.create_trade_action(
                trade_id=trade_id,
                action_type=action_type.value,
                success=True,
                old_stop_loss=old_sl,
                new_stop_loss=new_sl,
                old_take_profit=old_tp,
                new_take_profit=new_tp,
                current_price=current_price,
                profit_pips=profit_pips,
                triggered_by='auto_position_monitor',
                trigger_source='position_monitor_service',
                details=details
            )
        except Exception as e:
            logger.error(f"Failed to log trade action: {str(e)}")
    
    def _calculate_profit_pips(
        self,
        entry_price: float,
        current_price: float,
        is_buy: bool,
        symbol: str
    ) -> float:
        """Calculate profit in pips"""
        pip_value = self._get_pip_value(symbol)
        
        if is_buy:
            price_diff = current_price - entry_price
        else:
            price_diff = entry_price - current_price
        
        profit_pips = price_diff / pip_value
        return round(profit_pips, 1)
    
    def _get_pip_value(self, symbol: str) -> float:
        """
        Get pip value for a symbol
        
        IMPORTANT: Pips vs Points for Standard Accounts
        - For most forex pairs: 1 pip = 0.0001 (4th decimal)
        - Points (pipettes): 1 point = 0.00001 (5th decimal)
        - For JPY pairs: 1 pip = 0.01 (2nd decimal)
        """
        from src.utils.pip_utils import get_pip_size
        return get_pip_size(symbol)
    
    async def _apply_ai_market_analysis(
        self,
        trade: dict,
        position: dict,
        entry_price: float,
        current_price: float,
        is_buy: bool,
        profit_pips: Optional[float]
    ):
        """
        Apply AI-powered market analysis for intelligent trade management
        
        Features:
        - AI-powered breakeven triggers (when market turns against position)
        - AI-powered TP adjustment (extend profit in strong trends)
        - AI-powered position reduction (partial close in adverse conditions)
        """
        try:
            position_id = position.get('id')
            symbol = position.get('symbol')
            
            # Check if we should analyze (based on interval)
            if not self._should_run_ai_analysis(position_id):
                return
            
            # Get market analysis (LLM-enriched when enabled, numerical otherwise)
            logger.debug(f"🤖 Running AI market analysis for {symbol}...")
            position_type = 'BUY' if is_buy else 'SELL'
            
            analysis = await signal_service.analyze_market_conditions_llm(
                symbol=symbol,
                position_type=position_type,
                metaapi_connection=None  # Will auto-fetch
            )
            
            if analysis.get('error'):
                logger.warning(f"AI analysis failed: {analysis['error']}")
                return
            
            # Cache analysis result
            self._ai_analysis_cache[position_id] = {
                'analysis': analysis,
                'timestamp': datetime.now(timezone.utc)
            }
            
            # Save analysis to database and send notification
            analysis_id = await ai_analysis_service.save_analysis(
                symbol=symbol,
                position_type=position_type,
                analysis=analysis,
                position_id=position_id,
                trade_id=trade.get('id'),
                profit_pips=profit_pips,
                current_price=current_price,
                send_notification=True  # Will only send if there are recommendations
            )
            
            # Store analysis ID in cache for later action updates
            if analysis_id:
                self._ai_analysis_cache[position_id]['analysis_id'] = analysis_id
            
            # Log analysis results
            logger.info(f"🤖 AI Analysis for {symbol}:")
            logger.info(f"   Trend: {analysis.get('trend', 'unknown')} | Regime: {analysis.get('regime', '?')} | Session: {analysis.get('session', '?')}")
            logger.info(f"   Volatility: {analysis.get('volatility', 'unknown')} | Momentum: {analysis.get('momentum', 'unknown')}")
            if analysis.get('reasoning'):
                logger.info(f"   💡 LLM: {analysis['reasoning'][:150]}")
            if analysis.get('key_support') or analysis.get('key_resistance'):
                logger.info(f"   📊 S/R: support={analysis.get('key_support')}, resistance={analysis.get('key_resistance')}")
            
            # Gate all actions on confidence threshold
            confidence = analysis.get('trend_strength', 0.0)
            if confidence < settings.ai_analysis_confidence_threshold:
                logger.debug(
                    f"🤖 AI analysis confidence {confidence:.2f} below threshold "
                    f"{settings.ai_analysis_confidence_threshold} — skipping actions"
                )
                return

            # Apply AI recommendations based on settings
            
            # 1. AI Breakeven Triggers (protect capital in adverse trends)
            if settings.enable_ai_breakeven_triggers:
                await self._apply_ai_breakeven_trigger(
                    trade, position, analysis, entry_price, current_price, 
                    is_buy, profit_pips
                )
            
            # 2. AI TP Adjustment (extend profits in strong trends)
            if settings.enable_ai_tp_adjustment:
                await self._apply_ai_tp_adjustment(
                    trade, position, analysis, entry_price, current_price, 
                    is_buy, profit_pips
                )
            
            # 3. AI Position Reduction (reduce exposure in adverse conditions)
            if settings.enable_ai_position_reduction:
                await self._apply_ai_position_reduction(
                    trade, position, analysis, entry_price, current_price, 
                    is_buy, profit_pips
                )
            
        except Exception as e:
            logger.error(f"AI market analysis error: {str(e)}")
            logger.exception(e)
    
    def _should_run_ai_analysis(self, position_id: str) -> bool:
        """Check if we should run AI analysis based on interval"""
        current_time = datetime.now(timezone.utc)
        last_check = self._last_ai_analysis_check.get(position_id)
        
        if not last_check:
            self._last_ai_analysis_check[position_id] = current_time
            return True
        
        time_diff = (current_time - last_check).total_seconds()
        if time_diff >= settings.ai_analysis_check_interval:
            self._last_ai_analysis_check[position_id] = current_time
            return True
        
        return False
    
    async def _apply_ai_breakeven_trigger(
        self,
        trade: dict,
        position: dict,
        analysis: dict,
        entry_price: float,
        current_price: float,
        is_buy: bool,
        profit_pips: Optional[float]
    ):
        """Apply AI-powered breakeven trigger when market turns against position"""
        try:
            # Skip if already at breakeven
            if trade.get('breakEvenActivated', False):
                return
            
            # Skip if not profitable enough
            if profit_pips is None or profit_pips < 5:  # Minimum 5 pips profit
                return
            
            # Respect breakeven trigger method
            if settings.breakeven_trigger_method == BreakevenTriggerMethod.AFTER_PARTIAL.value:
                # Only allow AI breakeven after auto partial has been taken
                if not trade.get('autoPartialActivated', False):
                    logger.debug("AI breakeven skipped: waiting for auto partial to be taken")
                    return
            
            # Check AI recommendation
            recommend_breakeven = analysis.get('recommend_breakeven', False)
            
            if recommend_breakeven:
                trend = analysis.get('trend', 'unknown')
                volatility = analysis.get('volatility', 'unknown')
                momentum = analysis.get('momentum', 'unknown')
                
                logger.info("🤖 AI RECOMMENDS BREAKEVEN:")
                logger.info(f"   Trend: {trend} (adverse to position)")
                logger.info(f"   Volatility: {volatility}")
                logger.info(f"   Momentum: {momentum}")
                logger.info(f"   Current profit: {profit_pips:.1f} pips")
                
                # Move to breakeven with AI trigger
                current_sl = position.get('stopLoss')
                
                # Calculate breakeven SL (entry price, no buffer for AI trigger)
                new_sl = entry_price
                
                # Apply spread adjustment
                adjusted_sl = await spread_adjustment_service.adjust_sl_for_spread(
                    position.get('symbol'),
                    new_sl,
                    is_buy
                )
                if adjusted_sl != new_sl:
                    logger.info(f"📊 AI Breakeven SL adjusted for spread: {new_sl:.5f} → {adjusted_sl:.5f}")
                    new_sl = adjusted_sl
                
                # CRITICAL: Clamp to at least entry price (same as regular breakeven)
                if is_buy and new_sl < entry_price:
                    logger.info(f"📊 AI Breakeven SL {new_sl:.5f} below entry {entry_price:.5f} → clamping to entry")
                    new_sl = entry_price
                elif not is_buy and new_sl > entry_price:
                    logger.info(f"📊 AI Breakeven SL {new_sl:.5f} above entry {entry_price:.5f} → clamping to entry")
                    new_sl = entry_price
                
                new_sl = await self._round_to_symbol_digits(position.get('symbol'), new_sl)
                
                # Only move if new SL is better than current
                should_update = False
                if current_sl is None:
                    should_update = True
                elif is_buy and new_sl > current_sl:
                    should_update = True
                elif not is_buy and new_sl < current_sl:
                    should_update = True
                
                if should_update:
                    logger.info(f"🤖 AI-triggered breakeven: {current_sl} → {new_sl}")
                    
                    # Modify position
                    try:
                        async with trade_modification_lock(trade['id'], caller='ai_breakeven'):
                            await self.trading_provider.modify_position(
                                position.get('id'),
                                stop_loss=new_sl,
                                take_profit=position.get('takeProfit')
                            )
                            # Update database - persist new SL
                            await db_service.update_trade_field(trade['id'], 'stopLoss', new_sl)
                            await db_service.update_trade_field(trade['id'], 'breakEvenActivated', True)
                            await db_service.update_trade_field(trade['id'], 'lastModifiedAt', datetime.now(timezone.utc))

                        trade['stopLoss'] = new_sl
                        trade['breakEvenActivated'] = True
                        trade['lastModifiedAt'] = datetime.now(timezone.utc)

                        # Log action
                        await db_service.log_trade_action(
                            trade_id=trade['id'],
                            action_type='AI_BREAKEVEN',
                            success=True,
                            old_sl=current_sl,
                            new_sl=new_sl,
                            triggered_by='ai_market_analysis',
                            trigger_source='ai_adverse_trend_detection',
                            details=f"AI-triggered breakeven at {profit_pips:.1f} pips profit"
                        )

                        logger.success(f"✅ AI Breakeven activated: SL moved to {new_sl}")

                    except ValueError as e:
                        logger.debug(f"AI breakeven validation failed: {str(e)}")
                
                # Update analysis record with action taken
                if should_update:
                    analysis_id = self._ai_analysis_cache.get(position.get('id'), {}).get('analysis_id')
                    if analysis_id:
                        await ai_analysis_service.update_analysis_action(
                            analysis_id=analysis_id,
                            action_type='AI_BREAKEVEN',
                            action_details={
                                'old_sl': current_sl,
                                'new_sl': new_sl,
                                'profit_pips': profit_pips,
                                'trend': trend,
                                'volatility': volatility
                            }
                        )
        
        except Exception as e:
            logger.error(f"AI breakeven trigger error: {str(e)}")
    
    async def _apply_ai_tp_adjustment(
        self,
        trade: dict,
        position: dict,
        analysis: dict,
        entry_price: float,
        current_price: float,
        is_buy: bool,
        profit_pips: Optional[float]
    ):
        """Apply AI-powered TP adjustment for extended profits in strong trends"""
        try:
            # Skip if not profitable
            if profit_pips is None or profit_pips < 10:
                return

            # Skip if TP was already extended by AI in this session
            if trade.get('aiTpExtended', False):
                return
            
            # Check AI recommendations
            tp_recommendations = analysis.get('tp_recommendations', {})
            
            if tp_recommendations.get('keep_open') and tp_recommendations.get('adjust_tp'):
                trend = analysis.get('trend', 'unknown')
                momentum = analysis.get('momentum', 'unknown')
                
                logger.info("🤖 AI SUGGESTS TP EXTENSION:")
                logger.info(f"   Strong trend: {trend}")
                logger.info(f"   Strong momentum: {momentum}")
                logger.info(f"   Current profit: {profit_pips:.1f} pips")
                
                # Calculate extended TP (20% extension)
                current_tp = position.get('takeProfit')
                if not current_tp or current_tp == 0:
                    return
                
                # Extend TP in the profitable direction
                tp_distance = abs(current_tp - entry_price)
                extended_distance = tp_distance * 1.2  # 20% extension
                
                if is_buy:
                    new_tp = entry_price + extended_distance
                else:
                    new_tp = entry_price - extended_distance
                
                new_tp = await self._round_to_symbol_digits(position.get('symbol'), new_tp)
                
                # Only update if new TP is better
                if (is_buy and new_tp > current_tp) or (not is_buy and new_tp < current_tp):
                    logger.info(f"🤖 AI extending TP: {current_tp} → {new_tp} (+20%)")

                    # Modify position - wrapped so failure doesn't corrupt DB state
                    try:
                        async with trade_modification_lock(trade['id'], caller='ai_tp_extension'):
                            await self.trading_provider.modify_position(
                                position.get('id'),
                                stop_loss=position.get('stopLoss'),
                                take_profit=new_tp
                            )
                            # Persist new TP and modification time (only on success)
                            await db_service.update_trade_field(trade['id'], 'takeProfit', new_tp)
                            await db_service.update_trade_field(trade['id'], 'aiTpExtended', True)
                            await db_service.update_trade_field(trade['id'], 'lastModifiedAt', datetime.now(timezone.utc))
                        trade['takeProfit'] = new_tp
                        trade['aiTpExtended'] = True
                    except Exception as e:
                        logger.error(f"❌ AI TP extension modify_position failed: {e}")
                        return

                    # Log action
                    await db_service.log_trade_action(
                        trade_id=trade['id'],
                        action_type='AI_TP_EXTENSION',
                        success=True,
                        old_tp=current_tp,
                        new_tp=new_tp,
                        triggered_by='ai_market_analysis',
                        trigger_source='ai_strong_trend_detection',
                        details=f"AI TP extension - Trend: {trend}, Momentum: {momentum}"
                    )

                    logger.success(f"✅ AI extended TP to {new_tp}")

                    # Update analysis record with action taken
                    analysis_id = self._ai_analysis_cache.get(position.get('id'), {}).get('analysis_id')
                    if analysis_id:
                        await ai_analysis_service.update_analysis_action(
                            analysis_id=analysis_id,
                            action_type='AI_TP_EXTENSION',
                            action_details={
                                'old_tp': current_tp,
                                'new_tp': new_tp,
                                'profit_pips': profit_pips,
                                'trend': trend,
                                'momentum': momentum,
                                'extension_percent': 20
                            }
                        )
                    
        except Exception as e:
            logger.error(f"AI TP adjustment error: {str(e)}")
    
    async def _apply_ai_position_reduction(
        self,
        trade: dict,
        position: dict,
        analysis: dict,
        entry_price: float,
        current_price: float,
        is_buy: bool,
        profit_pips: Optional[float]
    ):
        """Apply AI-powered position reduction in adverse market conditions"""
        try:
            # Skip if not profitable
            if profit_pips is None or profit_pips < 10:
                return

            # Skip if AI already reduced this position
            if trade.get('aiPositionReduced', False):
                return
            
            # Check AI recommendations
            tp_recommendations = analysis.get('tp_recommendations', {})
            
            if tp_recommendations.get('reduce_position'):
                trend = analysis.get('trend', 'unknown')
                momentum = analysis.get('momentum', 'unknown')
                
                logger.info("🤖 AI RECOMMENDS POSITION REDUCTION:")
                logger.info(f"   Adverse trend: {trend}")
                logger.info(f"   Negative momentum: {momentum}")
                logger.info(f"   Current profit: {profit_pips:.1f} pips")
                
                # Partial close 50% of position
                symbol = position.get('symbol')
                current_volume = position.get('volume', 0)
                close_volume = current_volume * 0.5
                
                # Round to broker's volume step for this symbol
                close_volume = await self.trading_provider.round_lot_size(symbol, close_volume)
                
                if close_volume >= 0.01:  # Minimum lot size
                    logger.info(f"🤖 AI closing 50% of position: {close_volume} lots")

                    # Close partial position - wrapped so failure doesn't corrupt DB state
                    try:
                        await self.trading_provider.close_position(
                            position.get('id'),
                            volume=close_volume
                        )
                    except Exception as e:
                        logger.error(f"❌ AI position reduction close_position failed: {e}")
                        return

                    # Update database (only on success)
                    await db_service.update_trade_field(trade['id'], 'aiPositionReduced', True)
                    await db_service.update_trade_field(trade['id'], 'lastModifiedAt', datetime.now(timezone.utc))
                    trade['aiPositionReduced'] = True
                    trade['lastModifiedAt'] = datetime.now(timezone.utc)

                    # Log action
                    await db_service.log_trade_action(
                        trade_id=trade['id'],
                        action_type='AI_PARTIAL_CLOSE',
                        success=True,
                        triggered_by='ai_market_analysis',
                        trigger_source='ai_adverse_condition_detection',
                        details=f"AI partial close (50%) - Trend: {trend}, Momentum: {momentum}, Profit secured: {profit_pips:.1f} pips"
                    )

                    # Propagate partial close to signal status (RUNNING → PARTIALLY_CLOSED)
                    signal_id = trade.get('signalId')
                    if signal_id:
                        await db_service.update_signal_status_from_trades(signal_id)

                    logger.success(f"✅ AI reduced position by 50% ({close_volume} lots)")

                    # Update analysis record with action taken
                    analysis_id = self._ai_analysis_cache.get(position.get('id'), {}).get('analysis_id')
                    if analysis_id:
                        await ai_analysis_service.update_analysis_action(
                            analysis_id=analysis_id,
                            action_type='AI_PARTIAL_CLOSE',
                            action_details={
                                'volume_closed': close_volume,
                                'percentage': 50,
                                'profit_pips': profit_pips,
                                'trend': trend,
                                'momentum': momentum
                            }
                        )
                    
        except Exception as e:
            logger.error(f"AI position reduction error: {str(e)}")
    
    async def _write_equity_snapshot(self):
        """Persist a point-in-time balance/equity snapshot for the equity curve chart.
        Fetches broker data first, then opens the DB write — never holds a
        transaction across the network call (SQLite WAL + single writer)."""
        try:
            account_info = await self.trading_provider.get_account_info()
        except Exception as e:
            logger.error(f"Failed to fetch account info for equity snapshot: {str(e)}")
            return

        try:
            await db_service.db.equitysnapshot.create(
                data={
                    "balance": account_info.balance,
                    "equity": account_info.equity,
                    "margin": account_info.margin,
                    "freeMargin": account_info.free_margin,
                    "openPositions": account_info.open_positions,
                    "currency": account_info.currency,
                }
            )
            logger.debug(f"📸 Equity snapshot recorded (equity=${account_info.equity:.2f})")
        except Exception as e:
            logger.error(f"Failed to write equity snapshot: {str(e)}")

    async def _cleanup_old_caches(self):
        """Clean up old cache entries to prevent memory leaks"""
        try:
            # Get all currently active position IDs
            positions = await self.trading_provider.get_open_positions()
            if not positions:
                return
            
            active_position_ids = {pos.get('id') for pos in positions if pos.get('id')}
            
            # Clean up position data cache
            old_position_ids = set(self._position_data_cache.keys()) - active_position_ids
            for pos_id in old_position_ids:
                del self._position_data_cache[pos_id]
            
            # Clean up AI analysis cache and interval tracker for closed positions
            old_ai_keys = set(self._ai_analysis_cache.keys()) - active_position_ids
            for pos_id in old_ai_keys:
                del self._ai_analysis_cache[pos_id]
                if AI_ANALYSIS_AVAILABLE:
                    ai_analysis_service.clear_position_state(pos_id)

            old_interval_keys = set(self._last_ai_analysis_check.keys()) - active_position_ids
            for pos_id in old_interval_keys:
                del self._last_ai_analysis_check[pos_id]

            # Keep AI analysis cache bounded (max 50 active positions)
            if len(self._ai_analysis_cache) > 50:
                sorted_keys = sorted(
                    self._ai_analysis_cache.keys(),
                    key=lambda k: self._ai_analysis_cache[k].get('timestamp', datetime.min),
                    reverse=True
                )
                for key in sorted_keys[50:]:
                    del self._ai_analysis_cache[key]
            
            # Clean up last profit update cache for closed positions
            if self._last_profit_update:
                # Get all active trade IDs
                active_trades = await db_service.db.trade.find_many(
                    where={"status": "RUNNING"},
                    select={"id": True}
                )
                active_trade_ids = {t.id for t in active_trades}
                
                old_trade_ids = set(self._last_profit_update.keys()) - active_trade_ids
                for trade_id in old_trade_ids:
                    del self._last_profit_update[trade_id]
            
            if old_position_ids:
                logger.debug(f"🧹 Cleaned up {len(old_position_ids)} position cache entries")
                
        except Exception as e:
            logger.debug(f"Cache cleanup error: {str(e)}")


# Singleton instance
position_monitor_service = PositionMonitorService()
