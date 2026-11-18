"""
Position Recovery Service
Recovers orphaned positions that exist in the trading provider but have no database record
"""
from typing import Optional, Dict, List
from datetime import datetime
from loguru import logger

from config import settings
from src.integrations.trading.provider_factory import create_trading_provider
from src.core.database_service import db_service
from src.services.magic_number_service import magic_number_service


class PositionRecoveryService:
    """
    Service to recover and restore orphaned positions
    
    An orphaned position is one that exists in the trading provider but has no corresponding
    database record. This can happen due to:
    - Database connection issues during trade execution
    - Manual trades placed directly in MT4/MT5
    - Database sync failures
    - System restarts during trade execution
    """
    
    def __init__(self):
        self._trading_provider = None  # Lazy initialization
        self._recovery_cache = {}  # Cache to avoid repeated recovery attempts
        self._unrecoverable_positions = set()  # Track positions that cannot be recovered
    
    @property
    def trading_provider(self):
        """Lazy initialization of trading provider"""
        if self._trading_provider is None:
            self._trading_provider = create_trading_provider()
        return self._trading_provider
    
    async def recover_position_by_id(self, position_id: str) -> Optional[Dict]:
        """
        Recover a single orphaned position by its position ID
        
        Args:
            position_id: Position ID from trading provider
            
        Returns:
            Recovered trade record or None if recovery failed
        """
        try:
            # Check if position is known to be unrecoverable
            if position_id in self._unrecoverable_positions:
                logger.debug(f"Position {position_id} is unrecoverable (cached), skipping")
                return None
            
            logger.info(f"🔄 Attempting to recover orphaned position {position_id}")
            
            # Check cache first
            if position_id in self._recovery_cache:
                cached_time = self._recovery_cache[position_id].get('timestamp')
                # If we tried within last 5 minutes, skip
                if cached_time and (datetime.now() - cached_time).total_seconds() < 300:
                    logger.debug(f"Position {position_id} recently processed, skipping")
                    return self._recovery_cache[position_id].get('trade')
            
            # Get all open positions from trading provider
            all_positions = await self.trading_provider.get_open_positions()
            
            # Find our position
            position = None
            for pos in all_positions:
                if pos.get('id') == position_id:
                    position = pos
                    break
            
            if not position:
                logger.warning(f"Position {position_id} not found in {settings.provider_label}")
                return None
            
            # Extract magic number
            magic_number = position.get('magic')
            
            if not magic_number:
                logger.warning(f"Position {position_id} has no magic number - marking as unrecoverable")
                self._unrecoverable_positions.add(position_id)
                return None
            
            logger.info(f"📊 Found position {position_id} with magic number {magic_number}")
            
            # Try to find existing signal/message by magic number
            trade = await self._find_or_create_trade_record(position, magic_number)
            
            # Convert Prisma object to dict for compatibility
            trade_dict = trade.dict() if (trade and hasattr(trade, 'dict')) else trade
            
            # Cache result
            self._recovery_cache[position_id] = {
                'trade': trade_dict,
                'timestamp': datetime.now()
            }
            
            return trade_dict
            
        except Exception as e:
            logger.error(f"❌ Failed to recover position {position_id}: {str(e)}")
            # Mark as unrecoverable to prevent infinite retries
            self._unrecoverable_positions.add(position_id)
            return None
    
    async def recover_position_by_magic(self, magic_number: int, message_id: Optional[int] = None) -> List[Dict]:
        """
        Recover all orphaned positions and pending orders with a specific magic number
        
        Args:
            magic_number: Magic number to search for
            message_id: Optional message ID if known
            
        Returns:
            List of recovered trade records
        """
        try:
            logger.info(f"🔄 Recovering positions and orders with magic number {magic_number}")
            
            # Get both positions AND orders from trading provider with this magic number
            metaapi_data = await self.trading_provider.get_all_trades_by_magic(magic_number)
            positions = metaapi_data.get('positions', [])
            orders = metaapi_data.get('orders', [])
            
            logger.debug(f"🔍 Found {len(positions)} position(s) and {len(orders)} order(s) with magic number {magic_number}")
            
            if not positions and not orders:
                logger.warning(f"No positions or orders found with magic number {magic_number}")
                return []
            
            logger.info(f"📊 Found {len(positions)} position(s) and {len(orders)} order(s) with magic number {magic_number}")
            
            recovered_trades = []
            
            # Process positions
            for position in positions:
                position_id = position.get('id')
                
                # Check if trade already exists in database
                existing_trade = await db_service.get_trade_by_position_id(position_id)
                
                if existing_trade:
                    logger.debug(f"Position {position_id} already has DB record")
                    recovered_trades.append(existing_trade)
                    continue
                
                # Recover this orphaned position
                logger.warning(f"⚠️ Position {position_id} is orphaned - creating DB record")
                trade = await self._find_or_create_trade_record(position, magic_number, message_id)
                
                if trade:
                    # Convert Prisma object to dict for compatibility
                    trade_dict = trade.dict() if hasattr(trade, 'dict') else trade
                    recovered_trades.append(trade_dict)
            
            # Process pending orders
            for order in orders:
                order_id = order.get('id')
                
                # Check if trade already exists in database by orderId
                existing_trade = await db_service.db.trade.find_first(
                    where={"orderId": order_id}
                )
                
                if existing_trade:
                    logger.debug(f"Order {order_id} already has DB record")
                    trade_dict = existing_trade.dict() if hasattr(existing_trade, 'dict') else existing_trade
                    recovered_trades.append(trade_dict)
                    continue
                
                # Recover this orphaned order
                logger.warning(f"⚠️ Order {order_id} is orphaned - creating DB record")
                trade = await self._find_or_create_trade_record(order, magic_number, message_id, is_order=True)
                
                if trade:
                    # Convert Prisma object to dict for compatibility
                    trade_dict = trade.dict() if hasattr(trade, 'dict') else trade
                    recovered_trades.append(trade_dict)
            
            logger.success(f"✅ Recovered {len(recovered_trades)} position(s) and order(s)")
            return recovered_trades
            
        except Exception as e:
            logger.error(f"❌ Failed to recover positions with magic {magic_number}: {str(e)}")
            return []
    
    async def scan_and_recover_all_orphaned(self) -> Dict:
        """
        Scan all open positions and recover any orphaned ones
        
        Returns:
            Dictionary with recovery statistics
        """
        try:
            logger.info("🔍 Scanning for orphaned positions...")
            
            # Get all open positions from trading provider
            all_positions = await self.trading_provider.get_open_positions()
            
            # Clean up unrecoverable positions that are no longer open
            if all_positions and self._unrecoverable_positions:
                current_position_ids = {pos.get('id') for pos in all_positions}
                closed_positions = self._unrecoverable_positions - current_position_ids
                if closed_positions:
                    logger.info(f"🧹 Removing {len(closed_positions)} closed positions from unrecoverable cache")
                    self._unrecoverable_positions -= closed_positions
            
            if not all_positions:
                logger.debug("No open positions to scan")
                # If provider IS connected but returned genuinely empty positions list,
                # check if any EXECUTED trades in DB need to be marked CLOSED.
                # Only do this when connected — if provider is unreachable, [] is ambiguous
                # and we must not falsely mark live trades as closed.
                return {"total_positions": 0, "orphaned": 0, "recovered": 0}
            
            logger.info(f"📊 Scanning {len(all_positions)} open position(s)...")
            
            orphaned_count = 0
            recovered_count = 0
            
            for position in all_positions:
                position_id = position.get('id')
                magic_number = position.get('magic')
                
                # Skip if already marked as unrecoverable
                if position_id in self._unrecoverable_positions:
                    logger.debug(f"Skipping known unrecoverable position {position_id}")
                    continue
                
                # Skip if no magic number (manual trades or other EAs)
                if not magic_number:
                    logger.debug(f"Skipping position {position_id} - no magic number (manual trade/other EA)")
                    self._unrecoverable_positions.add(position_id)
                    continue
                
                # Skip if magic number doesn't belong to this bot
                # Bot magic numbers are typically in range 10000000-99999999
                if magic_number < 10000000 or magic_number > 99999999:
                    logger.debug(f"Skipping position {position_id} - magic {magic_number} not from this bot")
                    self._unrecoverable_positions.add(position_id)
                    continue
                
                # Check if trade exists in database by position ID
                existing_trade = await db_service.get_trade_by_position_id(position_id)
                
                # If position is already linked to a CLOSED trade, skip it
                if existing_trade and existing_trade.get('status') == 'CLOSED':
                    logger.debug(f"Position {position_id} is linked to CLOSED trade - skipping")
                    continue
                
                # If not found by position ID, check by magic number (might not have position ID yet)
                if not existing_trade:
                    trades_by_magic = await db_service.get_trades_by_magic_number(magic_number)
                    if trades_by_magic:
                        # Filter to only active trades (exclude CANCELLED/CLOSED/FAILED)
                        active_trades = [t for t in trades_by_magic if t.get('status') not in ['CANCELLED', 'CLOSED', 'FAILED']]
                        
                        # Trades exist with this magic - not truly orphaned
                        logger.debug(f"Position {position_id} has {len(trades_by_magic)} trade(s) with magic {magic_number} ({len(active_trades)} active)")
                        
                        # Check if any trade already has this position ID
                        already_linked = any(t.get('positionId') == position_id for t in trades_by_magic)
                        if already_linked:
                            logger.debug(f"Position {position_id} already linked to trade")
                            continue
                        
                        # CRITICAL FIX: Skip recovery if there are ANY active trades with this magic
                        # Position monitor handles PENDING → EXECUTED transitions and linking
                        # Recovery should only handle truly orphaned positions (no DB record at all)
                        if active_trades:
                            logger.debug(f"Position {position_id} has active trade(s) with magic {magic_number} - position_monitor will handle linking")
                            continue
                    else:
                        # No trades found by magic number either - truly orphaned
                        orphaned_count += 1
                        logger.warning(f"⚠️ Found truly orphaned position: {position_id} (magic: {magic_number})")
                        trade = await self._find_or_create_trade_record(position, magic_number)
                        if trade:
                            recovered_count += 1
            
            result = {
                "total_positions": len(all_positions),
                "orphaned": orphaned_count,
                "recovered": recovered_count,
                "failed": orphaned_count - recovered_count
            }
            
            if orphaned_count > 0:
                logger.success(f"✅ Recovery complete: {recovered_count}/{orphaned_count} positions restored")
            else:
                logger.info("✅ No orphaned positions found")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Failed to scan for orphaned positions: {str(e)}")
            return {"error": str(e)}
    
    async def _find_or_create_trade_record(
        self,
        position_or_order: Dict,
        magic_number: int,
        message_id: Optional[int] = None,
        is_order: bool = False
    ) -> Optional[Dict]:
        """
        Find existing trade record or create a new one for a position or order
        
        Args:
            position_or_order: Position or order data from trading provider
            magic_number: Magic number from position/order
            message_id: Optional message ID if known
            is_order: True if this is a pending order, False if position
            
        Returns:
            Trade record dictionary or None
        """
        try:
            entity_id = position_or_order.get('id')
            symbol = position_or_order.get('symbol')
            entity_type = "order" if is_order else "position"
            
            # First, try to find existing trades with this magic number
            existing_trades = await db_service.get_trades_by_magic_number(magic_number)
            
            if existing_trades:
                # Found existing trade(s) - try to link this position/order
                logger.info(f"📋 Found {len(existing_trades)} existing trade(s) with magic {magic_number}")
                
                # Filter out CANCELLED and CLOSED trades - only link to active trades
                active_trades = [t for t in existing_trades if t.get('status') not in ['CANCELLED', 'CLOSED', 'FAILED']]
                
                if is_order:
                    # For orders, check if any trade already has this order ID
                    for trade in existing_trades:  # Check all trades including inactive
                        if trade.get('orderId') == entity_id:
                            # This order is already linked - no action needed
                            logger.debug(f"Order {entity_id} already linked to trade {trade['id']} - no recovery needed")
                            return trade
                    
                    # Find an ACTIVE trade without an orderId to link
                    for trade in active_trades:
                        if not trade.get('orderId'):
                            # This trade has no order ID yet - link it
                            logger.info(f"🔗 Linking order {entity_id} to existing trade {trade['id']}")
                            await db_service.update_trade_field(trade['id'], 'orderId', entity_id)
                            # Keep status as PENDING for orders
                            if trade.get('status') != 'PENDING':
                                await db_service.update_trade_field(trade['id'], 'status', 'PENDING')
                            
                            # Log recovery action
                            await db_service.log_trade_action(
                                trade_id=trade['id'],
                                action_type='RECOVERY',
                                success=True,
                                triggered_by='position_recovery_service',
                                trigger_source='orphaned_order_scan',
                                details=f"Restored orphaned order {entity_id} with magic {magic_number}"
                            )
                            
                            return trade
                else:
                    # For positions, check if any trade already has this position ID
                    for trade in existing_trades:  # Check all trades including inactive
                        if trade.get('positionId') == entity_id:
                            # This position is already linked - no action needed
                            logger.debug(f"Position {entity_id} already linked to trade {trade['id']} - no recovery needed")
                            return trade
                    
                    # Find an ACTIVE trade without a positionId to link
                    for trade in active_trades:
                        if not trade.get('positionId'):
                            # This trade has no position ID yet - link it
                            logger.info(f"🔗 Linking position {entity_id} to existing trade {trade['id']}")
                            await db_service.update_trade_field(trade['id'], 'positionId', entity_id)
                            await db_service.update_trade_field(trade['id'], 'status', 'RUNNING')
                            await db_service.update_trade_field(trade['id'], 'executedAt', datetime.now())
                            
                            # Update entry price if different
                            entry_price = position_or_order.get('openPrice')
                            if entry_price:
                                await db_service.update_trade_field(trade['id'], 'entryPrice', entry_price)
                            
                            # Log recovery action
                            await db_service.log_trade_action(
                                trade_id=trade['id'],
                                action_type='RECOVERY',
                                success=True,
                                triggered_by='position_recovery_service',
                                trigger_source='orphaned_position_scan',
                                details=f"Restored orphaned position {entity_id} with magic {magic_number}"
                            )
                            
                            return trade
                
                # All active trades already have positions/orders - this might be a multi-TP trade
                # IMPORTANT: Only create new trade if this is truly a new position (multi-TP scenario)
                # Check if this exact position/order already exists in ANY trade (active or inactive)
                already_linked = False
                for trade in existing_trades:
                    if is_order and trade.get('orderId') == entity_id:
                        already_linked = True
                        break
                    elif not is_order and trade.get('positionId') == entity_id:
                        already_linked = True
                        break
                
                if already_linked:
                    logger.warning(f"⚠️ {entity_type.capitalize()} {entity_id} already linked to a trade - skipping duplicate creation")
                    return None
                
                # Check if all active trades have the same symbol and already have positions/orders
                # This indicates a multi-TP scenario where we need a new trade
                if active_trades:
                    all_have_positions = all(
                        (trade.get('positionId') if not is_order else trade.get('orderId')) 
                        for trade in active_trades
                    )
                    same_symbol = all(trade.get('symbol') == symbol for trade in active_trades)
                    
                    if all_have_positions and same_symbol:
                        # Multi-TP scenario - create new trade for this additional position/order
                        logger.info(f"📊 Multi-TP detected: Creating new trade for {entity_type} {entity_id}")
                        return await self._create_recovered_trade_record(
                            position_or_order,
                            magic_number,
                            active_trades[0].get('signalId'),
                            is_order=is_order
                        )
                
                # No suitable active trade found to link, and not a multi-TP scenario
                logger.warning(f"⚠️ No linkable active trade found for {entity_type} {entity_id} (magic: {magic_number})")
                # Mark as unrecoverable to prevent infinite retries
                self._unrecoverable_positions.add(entity_id)
                return None
            
            # No existing trades found - try to find signal by message ID
            if message_id:
                signal = await self._find_signal_by_message_id(message_id)
                if signal:
                    return await self._create_recovered_trade_record(
                        position_or_order,
                        magic_number,
                        signal.get('id'),
                        is_order=is_order
                    )
            
            # Last resort: Create orphaned trade record without signal
            logger.warning(f"⚠️ Creating orphaned trade record for {entity_type} {entity_id}")
            return await self._create_recovered_trade_record(position_or_order, magic_number, None, is_order=is_order)
            
        except Exception as e:
            logger.error(f"❌ Failed to find/create trade record: {str(e)}")
            return None
    
    def get_unrecoverable_positions(self) -> set:
        """
        Get the set of positions that cannot be recovered
        
        Returns:
            Set of position IDs that are unrecoverable
        """
        return self._unrecoverable_positions.copy()
    
    def clear_unrecoverable_position(self, position_id: str) -> bool:
        """
        Remove a position from the unrecoverable set
        
        Args:
            position_id: Position ID to remove
            
        Returns:
            True if removed, False if not found
        """
        if position_id in self._unrecoverable_positions:
            self._unrecoverable_positions.remove(position_id)
            logger.info(f"✅ Removed {position_id} from unrecoverable positions")
            return True
        return False
    
    async def _find_signal_by_message_id(self, message_id: int) -> Optional[Dict]:
        """Try to find signal by message ID"""
        try:
            # Search for signals with this message ID
            signals = await db_service.db.signal.find_many(
                where={
                    "messageId": message_id  # Fixed: use int not str
                }
            )
            
            if signals and len(signals) > 0:
                return signals[0]
            
            return None
            
        except Exception as e:
            logger.debug(f"Could not find signal for message {message_id}: {str(e)}")
            return None
    
    async def _create_recovered_trade_record(
        self,
        position_or_order: Dict,
        magic_number: int,
        signal_id: Optional[str] = None,
        is_order: bool = False
    ) -> Optional[Dict]:
        """
        Create a new trade record for a recovered position or order
        
        Args:
            position_or_order: Position or order data from trading provider
            magic_number: Magic number
            signal_id: Optional signal ID to link to
            is_order: True if this is a pending order, False if position
            
        Returns:
            Created trade record or None
        """
        try:
            entity_id = position_or_order.get('id')
            symbol = position_or_order.get('symbol')
            entry_price = position_or_order.get('openPrice') if not is_order else position_or_order.get('openPrice')
            stop_loss = position_or_order.get('stopLoss')
            take_profit = position_or_order.get('takeProfit')
            volume = position_or_order.get('volume')
            is_buy = position_or_order.get('type') in ['POSITION_TYPE_BUY', 'ORDER_TYPE_BUY', 'ORDER_TYPE_BUY_LIMIT', 'ORDER_TYPE_BUY_STOP']
            action = "BUY" if is_buy else "SELL"
            entity_type = "order" if is_order else "position"
            
            logger.info(f"📝 Creating recovered trade record for {symbol} {entity_type} {entity_id}")
            
            # If no signal_id, create a dummy signal for this orphaned position/order
            if not signal_id:
                logger.info(f"📋 Creating dummy signal for orphaned {entity_type} {entity_id}")
                dummy_signal = await db_service.db.signal.create(
                    data={
                        "action": "OPEN",
                        "orderType": action,
                        "symbol": symbol,
                        "entryPrice": entry_price,
                        "stopLoss": stop_loss,
                        "takeProfit": str(take_profit) if take_profit else None,
                        "lotSize": volume,
                        "confidence": 0.5,
                        "channelId": "ORPHANED",
                        "channelName": "Recovered Orphan",
                        "messageId": magic_number if magic_number else 0,
                        "rawMessage": f"[RECOVERED] {symbol} {action} {entity_type} recovered from {settings.provider_label}",
                        "messageHash": f"orphan_{entity_id}_{magic_number}",
                        "status": "RUNNING" if not is_order else "PENDING",
                        "riskApproved": True
                    }
                )
                signal_id = dummy_signal.id
                logger.success(f"✅ Created dummy signal: {signal_id}")
            
            # Create trade record with appropriate fields for position or order
            trade_data = {
                "signalId": signal_id,
                "symbol": symbol,
                "action": action,
                "entryPrice": entry_price,
                "stopLoss": stop_loss,
                "takeProfit": take_profit,
                "originalStopLoss": stop_loss,
                "originalTakeProfit": take_profit,
                "lotSize": volume,
                "magicNumber": magic_number,
                "lastModifiedAt": datetime.now(),
                # Auto monitoring flags - enable for recovered positions
                "autoTpEnabled": settings.enable_auto_take_profit,
                "trailingStopEnabled": settings.enable_trailing_stop,
                "breakEvenEnabled": settings.enable_breakeven_move,
                "autoPartialEnabled": settings.enable_auto_partial
            }
            
            if is_order:
                # For pending orders
                trade_data["orderId"] = entity_id
                trade_data["status"] = "PENDING"
            else:
                # For positions
                trade_data["positionId"] = entity_id
                trade_data["status"] = "RUNNING"
                trade_data["executedAt"] = datetime.now()
            
            trade = await db_service.db.trade.create(data=trade_data)
            
            # Log recovery
            await db_service.log_trade_action(
                trade_id=trade.id,
                action_type='RECOVERY',
                success=True,
                triggered_by='position_recovery_service',
                trigger_source=f'orphaned_{entity_type}_recovery',
                details=f"Created trade record for orphaned {entity_type} {entity_id} (magic: {magic_number}, symbol: {symbol})"
            )
            
            logger.success(f"✅ Created recovered trade record: {trade.id}")
            
            # Register with magic number service
            if is_order:
                magic_number_service.register_order(
                    magic_number=magic_number,
                    order_id=entity_id,
                    symbol=symbol
                )
            else:
                magic_number_service.register_order(
                    magic_number=magic_number,
                    position_id=entity_id,
                    symbol=symbol
                )
            
            # Create message mapping for future replies
            if magic_number:
                try:
                    mapping_params = {
                        "chat_id": "ORPHANED",
                        "message_id": magic_number,
                        "signal_id": signal_id,
                        "trade_ids": [trade.id],
                        "magic_number": magic_number,
                        "mapping_type": "RECOVERY"
                    }
                    
                    # Add position_ids or order_ids depending on type
                    if is_order:
                        mapping_params["order_ids"] = [entity_id]
                    else:
                        mapping_params["position_ids"] = [entity_id]
                    
                    await db_service.create_or_update_message_mapping(**mapping_params)
                    logger.info(f"📌 Created message mapping for recovered {entity_type} (message_id: {magic_number})")
                except Exception as e:
                    logger.warning(f"⚠️ Could not create message mapping: {str(e)}")
            
            return trade
            
        except Exception as e:
            logger.error(f"❌ Failed to create recovered trade record: {str(e)}")
            return None


# Singleton instance
position_recovery_service = PositionRecoveryService()
