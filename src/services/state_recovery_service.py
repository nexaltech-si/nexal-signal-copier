"""
State Recovery Service
Recovers trade state on bot restart to prevent duplicate actions
"""
from typing import Dict, List
from loguru import logger
from datetime import datetime, timezone

from src.integrations.trading.provider_factory import create_trading_provider
from src.core.database_service import db_service
from config import settings


class StateRecoveryService:
    """
    Service to recover and sync trade state on bot restart
    Prevents duplicate actions like double breakeven moves
    """
    
    def __init__(self):
        self.trading_provider = create_trading_provider()
    
    async def recover_all_states(self) -> Dict:
        """
        Recover state for all active trades
        Called on bot startup
        
        Fetches positions from MT5 API and matches with database trades using magic numbers.
        Updates trades with position IDs and syncs state, or marks closed trades.
        
        Returns:
            Summary of recovery operation
        """
        try:
            logger.info("🔄 Recovering ALL trade states from database and MT5 API...")
            
            # Get ALL trades from database - verify every status against MT5 reality
            all_trades = await db_service.db.trade.find_many(
                where={
                    "status": {
                        "in": ["PENDING", "EXECUTING", "PROCESSING", "RUNNING", "CLOSED", "CANCELLED", "FAILED"]
                    }
                }
            )
            
            if not all_trades:
                logger.info("No trades to recover")
                return {"success": True, "recovered": 0}
            
            logger.info(f"Found {len(all_trades)} trade(s) in database (all statuses)")
            
            # Count by status
            status_counts = {}
            for trade in all_trades:
                status_counts[trade.status] = status_counts.get(trade.status, 0) + 1
            logger.info(f"Trade status breakdown: {status_counts}")
            
            # Get all open positions from MT5
            broker_positions = await self.trading_provider.get_open_positions()
            logger.info(f"Found {len(broker_positions)} open position(s) in MT5")
            
            # Get all pending orders from MT5
            broker_orders = await self.trading_provider.get_all_pending_orders()
            broker_orders = broker_orders or []
            logger.info(f"Found {len(broker_orders)} pending order(s) in MT5")
            
            # Create lookups by position ID and magic number
            positions_by_id = {pos.get('id'): pos for pos in broker_positions if pos.get('id')}
            positions_by_magic = {}
            for pos in broker_positions:
                magic = pos.get('magic') or pos.get('clientId')
                if magic:
                    try:
                        magic_int = int(magic) if isinstance(magic, str) else magic
                        if magic_int not in positions_by_magic:
                            positions_by_magic[magic_int] = []
                        positions_by_magic[magic_int].append(pos)
                    except (ValueError, TypeError):
                        pass
            
            orders_by_id = {order.get('id'): order for order in broker_orders if order.get('id')}
            
            recovered_count = 0
            closed_count = 0
            linked_count = 0
            reopened_count = 0
            
            for trade in all_trades:
                try:
                    position_id = trade.positionId
                    order_id = trade.orderId
                    magic_number = trade.magicNumber
                    
                    # Case 1: Trade has position_id - check if it still exists.
                    # Finished trades go to Case 4 instead: a cancelled limit order
                    # keeps its order ticket as positionId, and treating it here
                    # turned every cancelled order into a CLOSED trade at P/L 0 on
                    # each restart ("Position closed externally").
                    if position_id and trade.status not in ('CLOSED', 'CANCELLED', 'FAILED'):
                        broker_position = positions_by_id.get(position_id)
                        
                        if broker_position:
                            # Position exists - sync state and ensure correct status
                            await self._sync_trade_state(trade, broker_position)
                            
                            # CRITICAL: Update trade status to match MT5 reality
                            # If position exists, status should be EXECUTED or RUNNING
                            if trade.status in ['PENDING', 'PROCESSING', 'EXECUTING']:
                                logger.info(f"Trade {trade.id[:8]}... status was {trade.status} but position exists in MT5 - updating to EXECUTED")
                                await db_service.update_trade_field(trade.id, 'status', 'EXECUTED')
                            elif trade.status == 'PENDING':
                                logger.info(f"Trade {trade.id[:8]}... status was PENDING but position exists in MT5 - updating to EXECUTED")
                                await db_service.update_trade_field(trade.id, 'status', 'EXECUTED')
                            
                            recovered_count += 1
                        else:
                            # CRITICAL FIX: Check if this is a pending order before closing
                            # Pending orders have order_id but no position_id initially
                            if order_id and order_id in orders_by_id:
                                logger.info(f"Trade {trade.id[:8]}... has position_id {position_id[:8]}... but order still exists in MT5 - keeping as PENDING")
                                # Order still exists, update status to PENDING if not already
                                if trade.status != 'PENDING':
                                    await db_service.update_trade_field(trade.id, 'status', 'PENDING')
                                recovered_count += 1
                            else:
                                # CRITICAL FIX: Check if trade is PENDING (limit order waiting to be filled)
                                # If PENDING, don't close it even if position not found - it might be waiting for execution
                                if trade.status == 'PENDING':
                                    logger.info(f"Trade {trade.id[:8]}... is PENDING (limit order waiting for execution) - keeping as PENDING even though position not found")
                                    recovered_count += 1
                                else:
                                    # CRITICAL FIX: Add grace period before marking as closed
                                    # MT5 API might temporarily not return positions (API lag, network issues)
                                    # Only mark as closed if trade is older than 5 minutes
                                    trade_age_minutes = None
                                    if trade.executedAt or trade.createdAt:
                                        reference_time = trade.executedAt or trade.createdAt
                                        trade_age = datetime.now(timezone.utc) - reference_time
                                        trade_age_minutes = trade_age.total_seconds() / 60
                                    
                                    # CRITICAL: Use short grace period for EXECUTED/RUNNING trades to detect manual closures quickly
                                    # For PROCESSING/EXECUTING trades, use longer grace period (15 minutes)
                                    # For EXECUTED/RUNNING trades, use 30 seconds to detect manual closures in real-time
                                    grace_period = 15 if trade.status in ['PROCESSING', 'EXECUTING'] else 0.5
                                    
                                    if trade_age_minutes and trade_age_minutes < grace_period:
                                        # Trade is too recent - skip closing, MT5 API might be lagging
                                        logger.warning(f"Position {position_id[:8]}... not found in MT5 but trade is only {trade_age_minutes:.1f} min old (status={trade.status}) - skipping closure (grace period {grace_period}m)")
                                    else:
                                        # CRITICAL: Double-check by fetching fresh data from MT5 before closing
                                        # This ensures we have the most current state before taking action
                                        logger.info(f"Verifying position state before closure - fetching fresh data for {position_id[:8]}...")
                                        fresh_positions = await self.trading_provider.get_open_positions()
                                        fresh_positions_by_id = {pos.get('id'): pos for pos in fresh_positions if pos.get('id')}
                                        
                                        if position_id in fresh_positions_by_id:
                                            # Position exists in fresh check - it was a temporary API lag
                                            logger.warning(f"Position {position_id[:8]}... found in fresh MT5 check - was temporary API lag, syncing state instead of closing")
                                            await self._sync_trade_state(trade, fresh_positions_by_id[position_id])
                                            recovered_count += 1
                                        else:
                                            # Trade is old enough and position not found - fetch deal history for actual profit/loss
                                            logger.info(f"Position {position_id[:8]}... confirmed not found in MT5 (status={trade.status}, age={trade_age_minutes:.1f}m) - fetching deal history")
                                            await self._close_trade_with_deal_history(trade, position_id)
                                            closed_count += 1
                    
                    # Case 2: Trade has no position_id but has magic_number - try to match with MT5 positions
                    elif magic_number and not position_id:
                        logger.debug(f"Trade {trade.id[:8]}... has no position ID, attempting to match by magic {magic_number}")
                        
                        # Check if there are positions with this magic number
                        matching_positions = positions_by_magic.get(magic_number, [])
                        
                        if matching_positions:
                            # Get all trades with this magic number to avoid duplicate linking
                            trades_with_magic = await db_service.get_trades_by_magic_number(magic_number)
                            linked_position_ids = {t.get('positionId') for t in trades_with_magic if t.get('positionId')}
                            
                            # Find an unlinked position
                            unlinked_position = None
                            for pos in matching_positions:
                                if pos.get('id') not in linked_position_ids:
                                    unlinked_position = pos
                                    break
                            
                            if unlinked_position:
                                # Link this position to the trade
                                pos_id = unlinked_position.get('id')
                                logger.info(f"🔗 Linking trade {trade.id[:8]}... to MT5 position {pos_id[:8]}... (magic: {magic_number})")
                                
                                await db_service.update_trade_field(trade.id, 'positionId', pos_id)
                                # CRITICAL: Update status to EXECUTED since position exists
                                if trade.status in ['PENDING', 'PROCESSING', 'EXECUTING']:
                                    logger.info(f"Trade {trade.id[:8]}... status was {trade.status} - updating to EXECUTED after linking")
                                await db_service.update_trade_field(trade.id, 'status', 'EXECUTED')
                                if not trade.executedAt:
                                    await db_service.update_trade_field(trade.id, 'executedAt', datetime.now(timezone.utc))
                                
                                # Sync state from position
                                await self._sync_trade_state(trade, unlinked_position)
                                linked_count += 1
                                recovered_count += 1
                            else:
                                logger.debug(f"All positions with magic {magic_number} already linked")
                        else:
                            # No positions found with this magic - check if it was closed
                            logger.debug(f"No MT5 positions found for magic {magic_number} - trade may be closed or pending")
                            
                            # Check if it's a pending order that still exists
                            if order_id and order_id in orders_by_id:
                                logger.debug(f"Trade {trade.id[:8]}... is a pending order")
                                # Order still exists, keep as is
                            elif trade.status in ['EXECUTED', 'EXECUTING', 'PROCESSING', 'RUNNING', 'PENDING']:
                                # CRITICAL FIX: Add grace period before marking as closed
                                # Trades created recently might not have been linked to positions yet
                                # Only mark as closed if trade is older than 5 minutes
                                trade_age_minutes = None
                                if trade.createdAt:
                                    trade_age = datetime.now(timezone.utc) - trade.createdAt
                                    trade_age_minutes = trade_age.total_seconds() / 60
                                
                                if trade_age_minutes and trade_age_minutes < 5:
                                    # Trade is too recent - skip closing, position might still be linking
                                    logger.debug(f"Trade {trade.id[:8]}... is only {trade_age_minutes:.1f} min old - skipping closure (grace period)")
                                elif trade.status == 'PENDING':
                                    # Never filled (no position was ever linked) and the order is
                                    # gone: it was cancelled/expired, not closed. Closing it here
                                    # recorded a fake trade and posted "closed at —" on restart.
                                    logger.info(f"Trade {trade.id[:8]}... PENDING order gone from MT5 with no position - marking as cancelled")
                                    await db_service.update_trade_field(trade.id, 'status', 'CANCELLED')
                                    await db_service.update_trade_field(trade.id, 'closedAt', datetime.now(timezone.utc))
                                    closed_count += 1
                                else:
                                    # Trade is old enough and no position/order found in MT5 - mark as closed
                                    logger.info(f"Trade {trade.id[:8]}... (status={trade.status}, age={trade_age_minutes:.1f}m) has no position/order in MT5 - marking as closed")
                                    await self._close_trade_without_position(trade)
                                    closed_count += 1
                    
                    # Case 3: Trade has order_id - check if order still exists
                    elif order_id and not position_id:
                        if order_id in orders_by_id:
                            logger.debug(f"Pending order {order_id[:8]}... still exists in MT5")
                            # CRITICAL: Ensure status is PENDING when order exists
                            if trade.status != 'PENDING':
                                logger.info(f"Trade {trade.id[:8]}... status was {trade.status} but order exists in MT5 - updating to PENDING")
                                await db_service.update_trade_field(trade.id, 'status', 'PENDING')
                            recovered_count += 1
                        else:
                            # Check if trade is marked as closed/cancelled - verify it's actually not in MT5
                            if trade.status in ['CLOSED', 'CANCELLED']:
                                logger.debug(f"Trade {trade.id[:8]}... is {trade.status} and order not found in MT5 - status is correct")
                            else:
                                # CRITICAL: Double-check by fetching fresh data from MT5 before cancelling
                                logger.info(f"Verifying order state before cancellation - fetching fresh data for {order_id[:8]}...")
                                fresh_orders = await self.trading_provider.get_all_pending_orders()
                                fresh_orders = fresh_orders or []
                                fresh_orders_by_id = {order.get('id'): order for order in fresh_orders if order.get('id')}
                                
                                if order_id in fresh_orders_by_id:
                                    # Order exists in fresh check - it was a temporary API lag
                                    logger.warning(f"Order {order_id[:8]}... found in fresh MT5 check - was temporary API lag, keeping as PENDING")
                                    recovered_count += 1
                                else:
                                    logger.info(f"Pending order {order_id[:8]}... confirmed not found in MT5 - marking as cancelled")
                                    await db_service.update_trade_field(trade.id, 'status', 'CANCELLED')
                                    await db_service.update_trade_field(trade.id, 'closedAt', datetime.now(timezone.utc))
                                    closed_count += 1
                    
                    # Case 4: Trade is marked CLOSED/CANCELLED in DB - verify against MT5
                    elif trade.status in ['CLOSED', 'CANCELLED']:
                        # Check if position or order still exists in MT5 (it shouldn't)
                        if position_id and position_id in positions_by_id:
                            logger.warning(f"Trade {trade.id[:8]}... is marked {trade.status} but position still exists in MT5 - reopening")
                            await db_service.update_trade_field(trade.id, 'status', 'EXECUTED')
                            await self._sync_trade_state(trade, positions_by_id[position_id])
                            reopened_count += 1
                        elif order_id and order_id in orders_by_id:
                            logger.warning(f"Trade {trade.id[:8]}... is marked {trade.status} but order still exists in MT5 - reopening as PENDING")
                            await db_service.update_trade_field(trade.id, 'status', 'PENDING')
                            reopened_count += 1
                        else:
                            logger.debug(f"Trade {trade.id[:8]}... is {trade.status} and not found in MT5 - status is correct")
                
                except Exception as e:
                    logger.error(f"Failed to recover trade {trade.id[:8]}...: {str(e)}")
                    continue
            
            # Update signal statuses using the canonical logic in db_service
            # which respects protected statuses and handles all trade status combos.
            # CRITICAL: Update signals for ALL affected trades, not just non-terminal ones
            # This ensures signals are in sync with the corrected trade statuses
            signals_updated = 0
            affected_signal_ids = set()
            
            # Collect all signal IDs from trades that were recovered/closed/linked
            for trade in all_trades:
                if trade.signalId:
                    affected_signal_ids.add(trade.signalId)
            
            logger.info(f"Updating signal statuses for {len(affected_signal_ids)} affected signals")
            
            for signal_id in affected_signal_ids:
                try:
                    await db_service.update_signal_status_from_trades(signal_id)
                    signals_updated += 1
                    logger.debug(f"Updated signal {signal_id[:8]}... status after state recovery")
                except Exception as e:
                    logger.debug(f"Signal status update failed ({signal_id[:8]}...): {e}")

            logger.success(f"✅ State recovery complete: {recovered_count} synced, {closed_count} closed, {reopened_count} reopened")
            if linked_count > 0:
                logger.success(f"🔗 Linked {linked_count} trade(s) to MT5 positions by magic number")
            if signals_updated > 0:
                logger.success(f"📝 Refreshed {signals_updated} signal status(es)")

            return {
                "success": True,
                "recovered": recovered_count,
                "closed": closed_count,
                "linked": linked_count,
                "reopened": reopened_count,
                "signals_updated": signals_updated,
                "total": len(all_trades)
            }
            
        except Exception as e:
            logger.error(f"❌ State recovery failed: {str(e)}")
            return {"success": False, "error": str(e)}
    
    async def _close_trade_with_deal_history(self, trade, position_id: str):
        """
        Close a trade by fetching deal history from MT5 API
        Uses trade_lifecycle API for accurate profit calculation (MT5REST only)
        
        Args:
            trade: Database trade record
            position_id: MT5 position ID
        """
        try:
            close_price = None
            profit_loss = None
            profit_loss_pips = None
            symbol = trade.symbol
            entry_price = trade.entryPrice
            action = trade.action
            
            # Try to use trade_lifecycle API for accurate profit calculation (MT5REST only)
            is_mt5rest = settings.trading_provider.lower().strip() == "mt5rest"
            lifecycle_data = None
            
            if is_mt5rest and hasattr(self.trading_provider, 'get_trade_lifecycle'):
                logger.info(f"📊 Fetching trade lifecycle for ticket {position_id} for accurate profit calculation")
                lifecycle_data = await self.trading_provider.get_trade_lifecycle(position_id, days_back=30)
                
                if lifecycle_data:
                    summary = lifecycle_data.get('summary', {})
                    lifecycle_profit = summary.get('net_pnl')
                    
                    if lifecycle_profit is not None:
                        profit_loss = float(lifecycle_profit)
                        close_price = summary.get('exit_price')
                        entry_price = summary.get('entry_price') or entry_price
                        
                        logger.info(
                            f"✅ Trade lifecycle API: P/L: ${profit_loss:.2f}, "
                            f"Entry: {entry_price}, Exit: {close_price}"
                        )
                        
                        # Calculate pips if we have prices
                        if close_price and entry_price and symbol:
                            pip_val = self._get_pip_value(symbol)
                            if await db_service.trade_is_buy(trade):
                                profit_loss_pips = (close_price - entry_price) / pip_val
                            else:
                                profit_loss_pips = (entry_price - close_price) / pip_val
                    else:
                        logger.warning("⚠️ Trade lifecycle API returned no profit data, falling back to deals")
                        lifecycle_data = None
            
            # Fallback to deals API if lifecycle not available or failed
            if not lifecycle_data:
                # Fetch actual closed deal history from MT5
                deals = await self.trading_provider.get_deals_by_position(position_id)
                
                if deals:
                    # Calculate actual total profit from all deals
                    profit_loss = 0
                    for deal in deals:
                        if isinstance(deal, dict):
                            profit_loss += deal.get('profit', 0)
                    
                    # Get the last deal's closing price
                    last_deal = deals[-1] if deals else None
                    close_price = last_deal.get('price') if (last_deal and isinstance(last_deal, dict)) else None
                    
                    logger.info(f"✅ Deal history: {len(deals)} deal(s), actual profit: ${profit_loss:.2f}")
                    
                    # Calculate pips if we have prices
                    if close_price and entry_price:
                        pip_value = self._get_pip_value(symbol)
                        
                        if await db_service.trade_is_buy(trade):
                            profit_loss_pips = (close_price - entry_price) / pip_value
                        else:
                            profit_loss_pips = (entry_price - close_price) / pip_value
                else:
                    # Fallback to last known profit from database
                    logger.warning(f"⚠️ No deal history found for {position_id[:8]}... - using last database profit")

                    if trade.profitLoss is not None:
                        profit_loss = trade.profitLoss
                        close_price = trade.closePrice
                        profit_loss_pips = trade.profitLossPips
                        logger.info(f"📊 Using last database profit: ${profit_loss:.2f}")
                    else:
                        logger.warning("⚠️ No database profit found - closing with null profit")

            # Check if trade is already CLOSED to prevent duplicate actions
            if trade.status == "CLOSED":
                logger.info(f"Trade {trade.id[:8]}... is already CLOSED - skipping duplicate closure")
                return

            await db_service.update_trade_closure(
                trade_id=trade.id,
                close_price=close_price,
                profit_loss=profit_loss,
                profit_loss_pips=profit_loss_pips
            )

            # Log the closure
            details = 'Position closed externally - not found in MT5 during state recovery'
            if profit_loss is not None:
                details += f'. Actual profit: ${profit_loss:.2f}'
                if profit_loss_pips is not None:
                    details += f' ({profit_loss_pips:+.1f} pips)'
            
            await db_service.log_trade_action(
                trade_id=trade.id,
                action_type='CLOSE',
                success=True,
                triggered_by='state_recovery',
                trigger_source='recover_orphaned_trades',
                details=details
            )
        except Exception as e:
            logger.error(f"Failed to close trade with deal history: {str(e)}")
    
    async def _close_trade_without_position(self, trade):
        """
        Close a trade that has no position in MT5 (no deal history available)
        
        Args:
            trade: Database trade record
        """
        try:
            # Use last known profit from database if available
            profit_loss = trade.profitLoss
            close_price = trade.closePrice
            profit_loss_pips = trade.profitLossPips
            
            await db_service.update_trade_closure(
                trade_id=trade.id,
                close_price=close_price,
                profit_loss=profit_loss,
                profit_loss_pips=profit_loss_pips
            )
            
            details = 'Position not found in MT5 - marked as closed during state recovery'
            if profit_loss is not None:
                details += f'. Last known profit: ${profit_loss:.2f}'
            
            await db_service.log_trade_action(
                trade_id=trade.id,
                action_type='CLOSE',
                success=True,
                triggered_by='state_recovery',
                trigger_source='recover_orphaned_trades',
                details=details
            )
        except Exception as e:
            logger.error(f"Failed to close trade without position: {str(e)}")
    
    async def _sync_trade_state(self, trade, broker_position: Dict):
        """
        Sync trade state from broker position
        Detects if breakeven/trailing was already applied
        
        Args:
            trade: Database trade record
            broker_position: Position from MetaAPI
        """
        try:
            trade_id = trade.id
            position_id = broker_position.get('id')
            
            # Get current values from broker
            broker_sl = broker_position.get('stopLoss')
            broker_tp = broker_position.get('takeProfit')
            entry_price = broker_position.get('openPrice')
            current_price = broker_position.get('currentPrice')
            
            # Get original values from database
            original_sl = trade.originalStopLoss or trade.stopLoss
            db_sl = trade.stopLoss
            
            # Check if values changed (indicating action was taken)
            if broker_sl and original_sl and abs(broker_sl - original_sl) > 0.00001:
                pass
            
            # Detect if breakeven was activated
            # Breakeven = SL near entry price
            if broker_sl and entry_price:
                distance_to_entry = abs(broker_sl - entry_price)
                pip_value = self._get_pip_value(broker_position.get('symbol'))
                distance_pips = distance_to_entry / pip_value
                
                # If SL within 5 pips of entry, likely breakeven
                if distance_pips < 5 and not trade.breakEvenActivated:
                    logger.info(f"🎯 Detected breakeven on {position_id} (SL near entry)")
                    await db_service.update_trade_field(trade_id, 'breakEvenActivated', True)
            
            # Detect if trailing was activated
            # If SL moved in favorable direction beyond original
            if broker_sl and original_sl:
                is_buy = broker_position.get('type') == 'POSITION_TYPE_BUY'
                
                if is_buy and broker_sl > original_sl:
                    # SL moved up for BUY = trailing likely active
                    if not trade.trailingActivated:
                        logger.info(f"🔄 Detected trailing on {position_id} (SL moved up)")
                        await db_service.update_trade_field(trade_id, 'trailingActivated', True)
                elif not is_buy and broker_sl < original_sl:
                    # SL moved down for SELL = trailing likely active
                    if not trade.trailingActivated:
                        logger.info(f"🔄 Detected trailing on {position_id} (SL moved down)")
                        await db_service.update_trade_field(trade_id, 'trailingActivated', True)
            
            # Update database with current broker values
            if broker_sl and abs(broker_sl - db_sl) > 0.00001:
                await db_service.update_trade_field(trade_id, 'stopLoss', broker_sl)
                logger.debug(f"📊 Updated SL: {db_sl} → {broker_sl}")
            
            if broker_tp != trade.takeProfit:
                await db_service.update_trade_field(trade_id, 'takeProfit', broker_tp)
                logger.debug(f"📊 Updated TP: {trade.takeProfit} → {broker_tp}")
            
            # Update price tracking
            if current_price:
                is_buy = broker_position.get('type') == 'POSITION_TYPE_BUY'
                
                if is_buy:
                    highest = trade.highestPrice
                    if highest is None or current_price > highest:
                        await db_service.update_trade_field(trade_id, 'highestPrice', current_price)
                else:
                    lowest = trade.lowestPrice
                    if lowest is None or current_price < lowest:
                        await db_service.update_trade_field(trade_id, 'lowestPrice', current_price)
            
            logger.debug(f"✅ Synced state for {position_id}")
            
        except Exception as e:
            logger.error(f"Failed to sync trade state: {str(e)}")
    
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
    
    async def add_comment_tags(self, position_id: str, tags: List[str]) -> bool:
        """
        Add state tags to position comment
        Format: "Bot signal from @channel [BE] [TS]"
        
        Args:
            position_id: MetaAPI position ID
            tags: Tags to add (e.g., ['BE', 'TS', 'ATP'])
            
        Returns:
            Success status
        """
        try:
            # Get current position
            positions = await self.trading_provider.get_open_positions()
            position = next((p for p in positions if p.get('id') == position_id), None)
            
            if not position:
                logger.warning(f"Position {position_id} not found")
                return False
            
            current_comment = position.get('comment', '')
            
            # Parse existing tags
            existing_tags = []
            if '[' in current_comment:
                tag_part = current_comment[current_comment.find('['):]
                existing_tags = [t.strip('[]') for t in tag_part.split() if t.startswith('[')]
            
            # Add new tags
            all_tags = list(set(existing_tags + tags))
            
            # Rebuild comment
            base_comment = current_comment.split('[')[0].strip()
            tag_str = ' '.join([f'[{tag}]' for tag in sorted(all_tags)])
            f"{base_comment} {tag_str}".strip()
            
            # Update position (comment update via modify)
            # Note: MetaAPI doesn't support comment-only updates
            # We'll store in database instead
            logger.debug(f"Tags for {position_id}: {all_tags}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to add comment tags: {str(e)}")
            return False


# Singleton instance
state_recovery_service = StateRecoveryService()
