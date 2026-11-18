"""
Reply actions that close only some positions of a setup: the worst/best ones,
those past a loss threshold, by entry level, by symbol, or by age.

Part of ReplyHandlerService (src/services/reply_handler_service.py); methods were moved here verbatim.
Module-level names are this module's own imports: to patch one in a test,
patch it here, not in reply_handler_service.py.
"""
from typing import Optional, Dict, List
from datetime import datetime, timezone, timedelta
import re
from loguru import logger
from src.integrations.trading.provider_factory import create_trading_provider
from src.services.magic_number_service import magic_number_service
from src.services.spread_adjustment_service import spread_adjustment_service
from src.core.database_service import db_service
from src.services.trade_context_manager import trade_context_manager
from src.services.channel_behavior_service import channel_behavior_service


class ReplySelectiveCloseMixin:
    """Close a subset of positions (worst/best, loss threshold, entry, symbol, time)."""

    async def _close_worst_positions(self, positions: List[Dict], magic_number: int, command: str, count: Optional[int] = None, db_trades: List[Dict] = None, keep_one: bool = False) -> Dict:
        """
        Close worst performing positions (highest loss or lowest profit)
        
        Args:
            positions: List of open positions
            magic_number: Magic number for filtering
            command: Command string for logging
            count: Number of worst positions to close (None = all losing positions)
            db_trades: Pre-fetched database trades
            keep_one: The message also says to HOLD an entry — never close every position
        """
        try:
            if not positions or len(positions) == 0:
                return {
                    "success": False,
                    "error": "No open positions found to close"
                }
            
            # Worst first. Per lot, so that the worst ENTRY comes first: by money alone
            # a large position at a good level ranks behind a small one at a bad level.
            def per_lot(p):
                profit, volume = p.get('profit', 0) or 0, p.get('volume')
                return profit / volume if volume else profit
            sorted_positions = sorted(positions, key=per_lot)
            
            # If count specified, only take that many worst positions
            # If no count, take all positions with negative profit
            if count:
                positions_to_close = sorted_positions[:count]
                logger.info(f"🎯 Closing worst {count} position(s) out of {len(positions)}")
            else:
                # Close all positions with negative profit
                positions_to_close = [p for p in sorted_positions if p.get('profit', 0) < 0]
                if not positions_to_close:
                    # If no losing positions, close the worst performing one
                    positions_to_close = sorted_positions[:1]
                logger.info(f"🎯 Closing {len(positions_to_close)} losing position(s) out of {len(positions)}")

            if keep_one and len(positions) > 1 and len(positions_to_close) >= len(positions):
                kept = sorted_positions[-1]
                positions_to_close = [p for p in positions_to_close if p is not kept]
                logger.info(f"🤚 The message says to hold an entry — keeping the best one ({kept.get('id')})")
            
            # Log which positions we're closing
            for pos in positions_to_close:
                profit = pos.get('profit', 0)
                logger.info(f"   - Position {pos.get('id')}: {pos.get('symbol')} | Profit: ${profit:.2f}")
            
            # Close selected positions
            closed_count = 0
            errors = []
            affected_trade_ids = []
            
            for position in positions_to_close:
                try:
                    position_id = position.get('id')
                    profit = position.get('profit', 0)
                    symbol = position.get('symbol')
                    current_price = position.get('currentPrice')
                    
                    await self.trading_provider.close_position(position_id)
                    closed_count += 1
                    logger.success(f"✅ Closed worst position {position_id} ({symbol}) | Loss: ${profit:.2f}")
                    
                    # Update database
                    if db_trades is None:
                        db_trades = await self.db.get_trades_by_magic_number(magic_number)
                    
                    for trade in db_trades:
                        if trade.get('positionId') == position_id and trade.get('status') not in ['CLOSED', 'FAILED', 'CANCELLED']:
                            affected_trade_ids.append(trade['id'])
                            
                            await self.db.update_trade_closure(
                                trade_id=trade['id'],
                                close_price=current_price,
                                profit_loss=profit
                            )
                            
                            await self.db.log_trade_action(
                                trade_id=trade['id'],
                                action_type='CLOSE',
                                success=True,
                                triggered_by='telegram_reply',
                                trigger_source='user_command_close_worst',
                                details=f'User reply: "{command}" - Closed worst performing position. Profit: ${profit:.2f}'
                            )
                    
                except Exception as e:
                    error_msg = str(e)
                    if 'not found' in error_msg.lower():
                        logger.warning(f"⚠️ Position {position_id} already closed")
                    else:
                        errors.append(f"Failed to close position {position_id}: {error_msg}")
                        logger.error(errors[-1])
            
            success = closed_count > 0
            message = f"Closed {closed_count} worst performing position(s)"
            if errors:
                message += f" (Note: {len(errors)} errors occurred)"
            
            return {
                "success": success,
                "message": message,
                "error": None if success else (errors[0] if errors else "Failed to close any positions"),
                "closed_count": closed_count,
                "affected_trade_ids": affected_trade_ids,
                "errors": errors if errors else None
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to close worst positions: {str(e)}")
            return {"success": False, "error": str(e)}

    async def _close_best_positions(self, positions: List[Dict], magic_number: int, command: str, count: Optional[int] = None, db_trades: List[Dict] = None) -> Dict:
        """
        Close best performing positions (highest profit)
        
        Args:
            positions: List of open positions
            magic_number: Magic number for filtering
            command: Command string for logging
            count: Number of best positions to close (None = all winning positions)
            db_trades: Pre-fetched database trades
        """
        try:
            if not positions or len(positions) == 0:
                return {
                    "success": False,
                    "error": "No open positions found to close"
                }
            
            # Sort positions by profit (descending - best first)
            sorted_positions = sorted(positions, key=lambda p: p.get('profit', 0), reverse=True)
            
            # If count specified, only take that many best positions
            # If no count, take all positions with positive profit
            if count:
                positions_to_close = sorted_positions[:count]
                logger.info(f"🎯 Closing best {count} position(s) out of {len(positions)}")
            else:
                # Close all positions with positive profit
                positions_to_close = [p for p in sorted_positions if p.get('profit', 0) > 0]
                if not positions_to_close:
                    # If no winning positions, close the best performing one
                    positions_to_close = sorted_positions[:1]
                logger.info(f"🎯 Closing {len(positions_to_close)} winning position(s) out of {len(positions)}")
            
            # Log which positions we're closing
            for pos in positions_to_close:
                profit = pos.get('profit', 0)
                logger.info(f"   - Position {pos.get('id')}: {pos.get('symbol')} | Profit: ${profit:.2f}")
            
            # Close selected positions
            closed_count = 0
            errors = []
            affected_trade_ids = []
            
            for position in positions_to_close:
                try:
                    position_id = position.get('id')
                    profit = position.get('profit', 0)
                    symbol = position.get('symbol')
                    current_price = position.get('currentPrice')
                    
                    await self.trading_provider.close_position(position_id)
                    closed_count += 1
                    logger.success(f"✅ Closed best position {position_id} ({symbol}) | Profit: ${profit:.2f}")
                    
                    # Update database
                    if db_trades is None:
                        db_trades = await self.db.get_trades_by_magic_number(magic_number)
                    
                    for trade in db_trades:
                        if trade.get('positionId') == position_id and trade.get('status') not in ['CLOSED', 'FAILED', 'CANCELLED']:
                            affected_trade_ids.append(trade['id'])
                            
                            await self.db.update_trade_closure(
                                trade_id=trade['id'],
                                close_price=current_price,
                                profit_loss=profit
                            )
                            
                            await self.db.log_trade_action(
                                trade_id=trade['id'],
                                action_type='CLOSE',
                                success=True,
                                triggered_by='telegram_reply',
                                trigger_source='user_command_close_best',
                                details=f'User reply: "{command}" - Closed best performing position. Profit: ${profit:.2f}'
                            )
                    
                except Exception as e:
                    error_msg = str(e)
                    if 'not found' in error_msg.lower():
                        logger.warning(f"⚠️ Position {position_id} already closed")
                    else:
                        errors.append(f"Failed to close position {position_id}: {error_msg}")
                        logger.error(errors[-1])
            
            success = closed_count > 0
            message = f"Closed {closed_count} best performing position(s)"
            if errors:
                message += f" (Note: {len(errors)} errors occurred)"
            
            return {
                "success": success,
                "message": message,
                "error": None if success else (errors[0] if errors else "Failed to close any positions"),
                "closed_count": closed_count,
                "affected_trade_ids": affected_trade_ids,
                "errors": errors if errors else None
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to close best positions: {str(e)}")
            return {"success": False, "error": str(e)}

    async def _close_positions_by_loss_threshold(self, positions: List[Dict], magic_number: int, command: str, threshold: float, db_trades: List[Dict] = None) -> Dict:
        """
        Close positions that exceed a percentage loss threshold
        
        Args:
            positions: List of open positions
            magic_number: Magic number for filtering
            command: Command string for logging
            threshold: Percentage loss threshold (e.g., 5.0 for 5%)
            db_trades: Pre-fetched database trades
        """
        try:
            if not positions or len(positions) == 0:
                return {
                    "success": False,
                    "error": "No open positions found to close"
                }
            
            if threshold is None or threshold <= 0:
                return {
                    "success": False,
                    "error": "Invalid threshold value. Must be greater than 0"
                }
            
            positions_to_close = []
            
            # Calculate percentage loss for each position
            for position in positions:
                entry_price = position.get('openPrice')
                current_price = position.get('currentPrice')
                position_type = position.get('type')
                profit = position.get('profit', 0)
                symbol = position.get('symbol')
                
                # Calculate percentage loss based on position type
                if position_type == 'POSITION_TYPE_BUY':
                    # For BUY: loss when current < entry
                    if current_price < entry_price:
                        percentage_loss = ((entry_price - current_price) / entry_price) * 100
                    else:
                        percentage_loss = 0
                else:  # POSITION_TYPE_SELL
                    # For SELL: loss when current > entry
                    if current_price > entry_price:
                        percentage_loss = ((current_price - entry_price) / entry_price) * 100
                    else:
                        percentage_loss = 0
                
                # Check if position exceeds threshold
                if percentage_loss >= threshold:
                    positions_to_close.append({
                        'position': position,
                        'percentage_loss': percentage_loss,
                        'profit': profit
                    })
            
            if not positions_to_close:
                logger.info(f"ℹ️ No positions exceed {threshold}% loss threshold")
                return {
                    "success": True,
                    "message": f"No positions exceed {threshold}% loss threshold",
                    "closed_count": 0
                }
            
            # Sort by loss percentage (highest loss first)
            positions_to_close.sort(key=lambda x: x['percentage_loss'], reverse=True)
            
            logger.info(f"🎯 Closing {len(positions_to_close)} position(s) exceeding {threshold}% loss threshold")
            
            # Log which positions we're closing
            for item in positions_to_close:
                pos = item['position']
                logger.info(f"   - Position {pos.get('id')}: {pos.get('symbol')} | Loss: {item['percentage_loss']:.2f}% | Profit: ${item['profit']:.2f}")
            
            # Close selected positions
            closed_count = 0
            errors = []
            affected_trade_ids = []
            
            for item in positions_to_close:
                position = item['position']
                try:
                    position_id = position.get('id')
                    profit = position.get('profit', 0)
                    symbol = position.get('symbol')
                    current_price = position.get('currentPrice')
                    
                    await self.trading_provider.close_position(position_id)
                    closed_count += 1
                    logger.success(f"✅ Closed position {position_id} ({symbol}) | Loss: {item['percentage_loss']:.2f}% | Profit: ${profit:.2f}")
                    
                    # Update database
                    if db_trades is None:
                        db_trades = await self.db.get_trades_by_magic_number(magic_number)
                    
                    for trade in db_trades:
                        if trade.get('positionId') == position_id and trade.get('status') not in ['CLOSED', 'FAILED', 'CANCELLED']:
                            affected_trade_ids.append(trade['id'])
                            
                            await self.db.update_trade_closure(
                                trade_id=trade['id'],
                                close_price=current_price,
                                profit_loss=profit
                            )
                            
                            await self.db.log_trade_action(
                                trade_id=trade['id'],
                                action_type='CLOSE',
                                success=True,
                                triggered_by='telegram_reply',
                                trigger_source='user_command_close_by_loss_threshold',
                                details=f'User reply: "{command}" - Closed position exceeding {threshold}% loss threshold. Loss: {item["percentage_loss"]:.2f}%. Profit: ${profit:.2f}'
                            )
                    
                except Exception as e:
                    error_msg = str(e)
                    if 'not found' in error_msg.lower():
                        logger.warning(f"⚠️ Position {position_id} already closed")
                    else:
                        errors.append(f"Failed to close position {position_id}: {error_msg}")
                        logger.error(errors[-1])
            
            success = closed_count > 0
            message = f"Closed {closed_count} position(s) exceeding {threshold}% loss threshold"
            if errors:
                message += f" (Note: {len(errors)} errors occurred)"
            
            return {
                "success": success,
                "message": message,
                "error": None if success else (errors[0] if errors else "Failed to close any positions"),
                "closed_count": closed_count,
                "affected_trade_ids": affected_trade_ids,
                "errors": errors if errors else None
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to close positions by loss threshold: {str(e)}")
            return {"success": False, "error": str(e)}

    async def _close_positions_by_entry(
        self,
        positions: List[Dict],
        magic_number: int,
        command: str,
        entry_price: float,
        db_trades: List[Dict] = None,
        reply_record_id: Optional[str] = None,
    ) -> Dict:
        """
        Close ONLY the position(s) filled at/near a stated entry level, leaving
        every other leg of the signal open.

        This is the "close 4020, hold 4030" case for multi-entry scale-in signals.
        Matching is done on the live position's openPrice (the real fill) with a
        fallback to the DB entryPrice/entryLeg recorded at execution time.

        Args:
            entry_price: The entry level named by the trader (e.g. 4020)
        """
        try:
            if not positions:
                return {"success": False, "error": "No open positions found to close"}

            if not entry_price:
                return {"success": False, "error": "No entry price specified for closing"}

            if db_trades is None:
                db_trades = await self.db.get_trades_by_magic_number(magic_number)

            # Map positionId -> DB entryPrice/entryLeg as a fallback for positions
            # whose live openPrice is missing (e.g. recovered/synced positions).
            db_entry_by_position = {}
            for trade in db_trades:
                pos_id = trade.get('positionId')
                if pos_id and trade.get('entryPrice') is not None:
                    db_entry_by_position[pos_id] = {
                        'entryPrice': trade.get('entryPrice'),
                        'entryLeg': trade.get('entryLeg'),
                    }

            tolerance = self._entry_match_tolerance(
                positions[0].get('symbol', ''), entry_price
            )

            positions_to_close = []
            positions_kept = []
            for p in positions:
                fill = p.get('openPrice')
                if fill is None:
                    fallback = db_entry_by_position.get(p.get('id'))
                    fill = fallback.get('entryPrice') if fallback else None
                if fill is None:
                    # Cannot prove this leg matches — keeping it is the safe default.
                    positions_kept.append((p, None))
                    continue
                if abs(float(fill) - float(entry_price)) <= tolerance:
                    positions_to_close.append((p, float(fill)))
                else:
                    positions_kept.append((p, float(fill)))

            if not positions_to_close:
                known = [f"{f:.5g}" for _, f in positions_kept if f is not None]
                logger.warning(
                    f"⚠️ No position matched entry {entry_price} "
                    f"(tolerance ±{tolerance:.5g}); open fills: {known or 'unknown'}"
                )
                return {
                    "success": False,
                    "error": (
                        f"No open position found at entry {entry_price}. "
                        f"Open fills: {', '.join(known) if known else 'unknown'}. "
                        f"Nothing was closed."
                    ),
                    "closed_count": 0,
                }

            # SAFETY: if the stated level matches every open leg, the instruction
            # cannot be leg-scoped — refuse rather than silently closing them all.
            if len(positions_to_close) == len(positions) and len(positions) > 1:
                logger.warning(
                    f"⚠️ Entry {entry_price} matched ALL {len(positions)} open legs — "
                    f"refusing ambiguous close"
                )
                return {
                    "success": False,
                    "error": (
                        f"Entry {entry_price} matches all {len(positions)} open positions "
                        f"(they are within ±{tolerance:.5g} of each other). Refusing to "
                        f"close — use 'close all' if you meant every leg."
                    ),
                    "closed_count": 0,
                }

            logger.info(
                f"🎯 Entry-scoped close @ {entry_price}: closing {len(positions_to_close)}, "
                f"keeping {len(positions_kept)}"
            )
            for pos, fill in positions_to_close:
                logger.info(f"   ✂️ CLOSE {pos.get('id')} filled @ {fill}")
            for pos, fill in positions_kept:
                logger.info(f"   🤚 HOLD  {pos.get('id')} filled @ {fill}")

            closed_count = 0
            errors = []
            affected_trade_ids = []

            for position, fill in positions_to_close:
                position_id = position.get('id')
                try:
                    profit = position.get('profit', 0)
                    current_price = position.get('currentPrice')

                    await self.trading_provider.close_position(position_id)
                    closed_count += 1
                    logger.success(
                        f"✅ Closed leg @ {fill} (position {position_id}) | Profit: ${profit:.2f}"
                    )

                    for trade in db_trades:
                        if (trade.get('positionId') == position_id
                                and trade.get('status') not in ['CLOSED', 'FAILED', 'CANCELLED']):
                            affected_trade_ids.append(trade['id'])
                            await self.db.update_trade_closure(
                                trade_id=trade['id'],
                                close_price=current_price,
                                profit_loss=profit,
                            )
                            await self.db.log_trade_action(
                                trade_id=trade['id'],
                                action_type='CLOSE',
                                success=True,
                                triggered_by='telegram_reply',
                                trigger_source='user_command_close_by_entry',
                                details=(
                                    f'User reply: "{command}" - Closed leg filled @ {fill} '
                                    f'(stated entry {entry_price}). Profit: ${profit:.2f}. '
                                    f'{len(positions_kept)} leg(s) left open.'
                                ),
                            )
                except Exception as e:
                    error_msg = str(e)
                    if 'not found' in error_msg.lower():
                        logger.warning(f"⚠️ Position {position_id} already closed")
                    else:
                        errors.append(f"Failed to close position {position_id}: {error_msg}")
                        logger.error(errors[-1])

            # NOTE: deliberately NOT forcing the parent signal to CLOSED here.
            # Other legs remain open; the signal is only closed when the last
            # position for the magic number is gone (handled by order sync).
            success = closed_count > 0
            kept_desc = ', '.join(f"{f:.5g}" for _, f in positions_kept if f is not None)
            message = (
                f"Closed {closed_count} position(s) at entry {entry_price}; "
                f"holding {len(positions_kept)} leg(s)"
                + (f" @ {kept_desc}" if kept_desc else "")
            )
            if errors:
                message += f" (Note: {len(errors)} errors occurred)"

            return {
                "success": success,
                "message": message,
                "error": None if success else (errors[0] if errors else "Failed to close any positions"),
                "closed_count": closed_count,
                "kept_count": len(positions_kept),
                "affected_trade_ids": affected_trade_ids,
                "errors": errors if errors else None,
            }

        except Exception as e:
            logger.error(f"❌ Failed entry-scoped close: {str(e)}")
            return {"success": False, "error": str(e)}

    async def _close_positions_by_symbol(self, positions: List[Dict], magic_number: int, command: str, symbol: str, db_trades: List[Dict] = None) -> Dict:
        """
        Close all positions for a specific symbol
        
        Args:
            positions: List of open positions
            magic_number: Magic number for filtering
            command: Command string for logging
            symbol: Symbol to close (e.g., "XAUUSD", "EURUSD")
            db_trades: Pre-fetched database trades
        """
        try:
            if not positions or len(positions) == 0:
                return {
                    "success": False,
                    "error": "No open positions found to close"
                }
            
            if not symbol:
                return {
                    "success": False,
                    "error": "No symbol specified for closing"
                }
            
            # Filter positions by symbol (case-insensitive)
            symbol_upper = symbol.upper()
            positions_to_close = [p for p in positions if p.get('symbol', '').upper() == symbol_upper]
            
            if not positions_to_close:
                logger.info(f"ℹ️ No positions found for symbol {symbol}")
                return {
                    "success": True,
                    "message": f"No positions found for symbol {symbol}",
                    "closed_count": 0
                }
            
            logger.info(f"🎯 Closing {len(positions_to_close)} position(s) for symbol {symbol}")
            
            # Log which positions we're closing
            for pos in positions_to_close:
                profit = pos.get('profit', 0)
                logger.info(f"   - Position {pos.get('id')}: {pos.get('symbol')} | Profit: ${profit:.2f}")
            
            # Close selected positions
            closed_count = 0
            errors = []
            affected_trade_ids = []
            
            for position in positions_to_close:
                try:
                    position_id = position.get('id')
                    profit = position.get('profit', 0)
                    symbol_name = position.get('symbol')
                    current_price = position.get('currentPrice')
                    
                    await self.trading_provider.close_position(position_id)
                    closed_count += 1
                    logger.success(f"✅ Closed position {position_id} ({symbol_name}) | Profit: ${profit:.2f}")
                    
                    # Update database
                    if db_trades is None:
                        db_trades = await self.db.get_trades_by_magic_number(magic_number)
                    
                    for trade in db_trades:
                        if trade.get('positionId') == position_id and trade.get('status') not in ['CLOSED', 'FAILED', 'CANCELLED']:
                            affected_trade_ids.append(trade['id'])
                            
                            await self.db.update_trade_closure(
                                trade_id=trade['id'],
                                close_price=current_price,
                                profit_loss=profit
                            )
                            
                            await self.db.log_trade_action(
                                trade_id=trade['id'],
                                action_type='CLOSE',
                                success=True,
                                triggered_by='telegram_reply',
                                trigger_source='user_command_close_by_symbol',
                                details=f'User reply: "{command}" - Closed position for symbol {symbol}. Profit: ${profit:.2f}'
                            )
                    
                except Exception as e:
                    error_msg = str(e)
                    if 'not found' in error_msg.lower():
                        logger.warning(f"⚠️ Position {position_id} already closed")
                    else:
                        errors.append(f"Failed to close position {position_id}: {error_msg}")
                        logger.error(errors[-1])
            
            success = closed_count > 0
            message = f"Closed {closed_count} position(s) for symbol {symbol}"
            if errors:
                message += f" (Note: {len(errors)} errors occurred)"
            
            return {
                "success": success,
                "message": message,
                "error": None if success else (errors[0] if errors else "Failed to close any positions"),
                "closed_count": closed_count,
                "affected_trade_ids": affected_trade_ids,
                "errors": errors if errors else None
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to close positions by symbol: {str(e)}")
            return {"success": False, "error": str(e)}

    async def _close_positions_by_time(self, positions: List[Dict], magic_number: int, command: str, minutes: float, db_trades: List[Dict] = None) -> Dict:
        """
        Close positions older than specified time
        
        Args:
            positions: List of open positions
            magic_number: Magic number for filtering
            command: Command string for logging
            minutes: Time threshold in minutes (close positions older than this)
            db_trades: Pre-fetched database trades
        """
        try:
            if not positions or len(positions) == 0:
                return {
                    "success": False,
                    "error": "No open positions found to close"
                }
            
            if minutes is None or minutes <= 0:
                return {
                    "success": False,
                    "error": "Invalid time threshold. Must be greater than 0"
                }
            
            from datetime import datetime, timezone, timedelta
            
            positions_to_close = []
            current_time = datetime.now(timezone.utc)
            time_threshold = current_time - timedelta(minutes=minutes)
            
            # Filter positions by time
            for position in positions:
                # Try to get open time from position
                open_time_str = position.get('openTime') or position.get('time')
                
                if open_time_str:
                    try:
                        # Parse time (handle different formats)
                        if isinstance(open_time_str, str):
                            # Try ISO format
                            open_time = datetime.fromisoformat(open_time_str.replace('Z', '+00:00'))
                        else:
                            # Unix timestamp (milliseconds or seconds)
                            if open_time_str > 1000000000000:  # milliseconds
                                open_time = datetime.fromtimestamp(open_time_str / 1000, tz=timezone.utc)
                            else:  # seconds
                                open_time = datetime.fromtimestamp(open_time_str, tz=timezone.utc)
                        
                        # Check if position is older than threshold
                        if open_time < time_threshold:
                            positions_to_close.append({
                                'position': position,
                                'open_time': open_time,
                                'age_minutes': (current_time - open_time).total_seconds() / 60
                            })
                    except Exception as e:
                        logger.warning(f"Could not parse open time for position {position.get('id')}: {e}")
            
            if not positions_to_close:
                logger.info(f"ℹ️ No positions older than {minutes} minutes")
                return {
                    "success": True,
                    "message": f"No positions older than {minutes} minutes",
                    "closed_count": 0
                }
            
            # Sort by age (oldest first)
            positions_to_close.sort(key=lambda x: x['age_minutes'], reverse=True)
            
            logger.info(f"🎯 Closing {len(positions_to_close)} position(s) older than {minutes} minutes")
            
            # Log which positions we're closing
            for item in positions_to_close:
                pos = item['position']
                logger.info(f"   - Position {pos.get('id')}: {pos.get('symbol')} | Age: {item['age_minutes']:.1f} minutes")
            
            # Close selected positions
            closed_count = 0
            errors = []
            affected_trade_ids = []
            
            for item in positions_to_close:
                position = item['position']
                try:
                    position_id = position.get('id')
                    profit = position.get('profit', 0)
                    symbol = position.get('symbol')
                    current_price = position.get('currentPrice')
                    
                    await self.trading_provider.close_position(position_id)
                    closed_count += 1
                    logger.success(f"✅ Closed position {position_id} ({symbol}) | Age: {item['age_minutes']:.1f} minutes | Profit: ${profit:.2f}")
                    
                    # Update database
                    if db_trades is None:
                        db_trades = await self.db.get_trades_by_magic_number(magic_number)
                    
                    for trade in db_trades:
                        if trade.get('positionId') == position_id and trade.get('status') not in ['CLOSED', 'FAILED', 'CANCELLED']:
                            affected_trade_ids.append(trade['id'])
                            
                            await self.db.update_trade_closure(
                                trade_id=trade['id'],
                                close_price=current_price,
                                profit_loss=profit
                            )
                            
                            await self.db.log_trade_action(
                                trade_id=trade['id'],
                                action_type='CLOSE',
                                success=True,
                                triggered_by='telegram_reply',
                                trigger_source='user_command_close_by_time',
                                details=f'User reply: "{command}" - Closed position older than {minutes} minutes. Age: {item["age_minutes"]:.1f} minutes. Profit: ${profit:.2f}'
                            )
                    
                except Exception as e:
                    error_msg = str(e)
                    if 'not found' in error_msg.lower():
                        logger.warning(f"⚠️ Position {position_id} already closed")
                    else:
                        errors.append(f"Failed to close position {position_id}: {error_msg}")
                        logger.error(errors[-1])
            
            success = closed_count > 0
            message = f"Closed {closed_count} position(s) older than {minutes} minutes"
            if errors:
                message += f" (Note: {len(errors)} errors occurred)"
            
            return {
                "success": success,
                "message": message,
                "error": None if success else (errors[0] if errors else "Failed to close any positions"),
                "closed_count": closed_count,
                "affected_trade_ids": affected_trade_ids,
                "errors": errors if errors else None
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to close positions by time: {str(e)}")
            return {"success": False, "error": str(e)}
