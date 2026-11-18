"""
Reply actions that change running trades without closing them: break-even,
lock profit, SL/TP to a price, and adding lots.

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


class ReplyModifyMixin:
    """Break-even, lock profit, SL/TP modification and adding to a position."""

    async def _move_to_breakeven(self, positions: List[Dict], magic_number: int, reply_record_id: Optional[str] = None, orders: List[Dict] = None) -> Dict:
        """Move stop loss to breakeven for all positions, or cancel pending orders"""
        try:
            # Provider moved to BE = the trade has advanced; unfilled legs are stale.
            pending_note = ""
            if orders and len(orders) > 0:
                logger.info(f"⚠️ Found {len(orders)} pending order(s) - cancelling (breakeven can't apply to unfilled orders)")
                cancelled_result = await self._cancel_pending_orders(orders, magic_number, "Auto-cancel (invalid for pending orders)", reply_record_id)
                if not positions:
                    cancelled_result['message'] = f"⚠️ Cancelled {cancelled_result.get('cancelled_count', 0)} pending order(s) - cannot set breakeven on pending orders"
                    return cancelled_result
                pending_note = f" + cancelled {cancelled_result.get('cancelled_count', 0)} pending order(s)"
            
            if not positions or len(positions) == 0:
                return {
                    "success": False,
                    "error": "No open positions found to move to breakeven"
                }
            
            modified_count = 0
            already_count = 0
            errors = []

            for position in positions:
                try:
                    position_id = position.get('id')
                    entry_price = position.get('openPrice')
                    current_tp = position.get('takeProfit')
                    current_sl = position.get('stopLoss')

                    # Auto breakeven often got there first; MT5 rejects a modify that
                    # changes nothing (retcode 10025), so don't send one.
                    if current_sl and entry_price and abs(current_sl - entry_price) < 1e-7:
                        already_count += 1
                        logger.info(f"ℹ️ {position_id} already at breakeven ({entry_price})")
                        continue

                    # Broker rule: For a SELL, SL must be above current price; for a BUY, SL must be below current price.
                    # If position is in drawdown, setting SL to entry price violates broker stop rules (retcode 10016).
                    pos_type = str(position.get('type', '')).upper()
                    is_buy = 'BUY' in pos_type
                    current_price = position.get('currentPrice') or position.get('price_current')
                    if current_price and entry_price:
                        in_drawdown = (not is_buy and current_price > entry_price + 1e-4) or (is_buy and current_price < entry_price - 1e-4)
                        if in_drawdown:
                            pips_diff = abs(current_price - entry_price)
                            sym = position.get('symbol', '')
                            pips_str = f"{pips_diff * 10:.1f} pips" if 'XAU' in sym else f"{pips_diff:.4f}"
                            msg = f"Position {position_id} is in drawdown (current: {current_price}, entry: {entry_price}, -{pips_str}); broker rejects SL at entry while trade is negative"
                            logger.warning(f"⚠️ Cannot move to breakeven: {msg}")
                            errors.append(msg)
                            continue

                    # Move SL to entry price (breakeven)
                    try:
                        result = await self.trading_provider.modify_position(
                            position_id,
                            stop_loss=entry_price,
                            take_profit=current_tp
                        )
                        if isinstance(result, dict) and result.get('unchanged'):
                            already_count += 1
                            continue

                        modified_count += 1
                        logger.success(f"✅ Moved {position_id} to breakeven at {entry_price}")
                    except ValueError as e:
                        logger.warning(f"⚠️ Cannot move {position_id} to breakeven: {str(e)}")
                        continue
                    
                    # Update database
                    db_trades = await self.db.get_trades_by_magic_number(magic_number)
                    for trade in db_trades:
                        if trade.get('positionId') == position_id:
                            old_sl = trade.get('stopLoss')
                            await self.db.update_trade_field(trade['id'], 'stopLoss', entry_price)
                            await self.db.update_trade_field(trade['id'], 'breakEvenActivated', True)
                            
                            # Log action to audit trail
                            await self.db.log_trade_action(
                                trade_id=trade['id'],
                                action_type='BREAKEVEN',
                                success=True,
                                old_sl=old_sl,
                                new_sl=entry_price,
                                triggered_by='telegram_reply',
                                trigger_source='user_command_breakeven',
                                details=f'User reply: Manual breakeven - Moved SL from {old_sl} to {entry_price}'
                            )
                    
                except Exception as e:
                    errors.append(f"Failed to move {position_id} to breakeven: {str(e)}")
                    logger.error(errors[-1])
            
            success = modified_count > 0 or already_count > 0 or (not positions and not orders)
            already_note = f" ({already_count} already at breakeven)" if already_count else ""

            if success and modified_count > 0:
                try:
                    be_price = positions[0].get('openPrice') if positions else None
                    db_trades_for_reply = await self.db.get_trades_by_magic_number(magic_number)
                    signal_ids = set(t.get('signalId') for t in db_trades_for_reply if t.get('signalId'))
                    signal_forwarder_service = self.forwarder
                    for sig_id in signal_ids:
                        await signal_forwarder_service.reply_breakeven(sig_id, be_price)
                except Exception as _exc:
                    logger.debug(f"Suppressed exception: {_exc!r}")

            return {
                "success": success,
                "message": f"Moved {modified_count} position(s) to breakeven{already_note}{pending_note}",
                "error": None if success else (errors[0] if errors else "Failed to move any positions to breakeven"),
                "modified_count": modified_count,
                "already_at_breakeven": already_count,
                "errors": errors if errors else None
            }

        except Exception as e:
            logger.error(f"❌ Failed to move to breakeven: {str(e)}")
            return {"success": False, "error": str(e)}

    async def _lock_profit_by_pips(self, positions: List[Dict], pips: float, magic_number: int, command: str) -> Dict:
        """Lock profit by moving SL +X pips in favorable direction"""
        try:
            modified_count = 0
            errors = []
            
            for position in positions:
                try:
                    position_id = position.get('id')
                    entry_price = position.get('openPrice')
                    current_tp = position.get('takeProfit')
                    symbol = position.get('symbol')
                    is_buy = position.get('type') == 'POSITION_TYPE_BUY'
                    
                    # Calculate pip value
                    pip_value = await self._get_pip_value(symbol)
                    lock_distance = pips * pip_value
                    
                    # Calculate new SL (entry + X pips in profit direction)
                    if is_buy:
                        new_sl = entry_price + lock_distance
                    else:
                        new_sl = entry_price - lock_distance
                    
                    new_sl = round(new_sl, 5)
                    
                    # Apply spread adjustment
                    adjusted_sl = await self.spread_adjustment.adjust_sl_for_position(
                        position_id,
                        new_sl
                    )
                    if adjusted_sl != new_sl:
                        logger.info(f"📊 Lock profit SL adjusted for spread: {new_sl:.5f} → {adjusted_sl:.5f}")
                        new_sl = adjusted_sl
                    
                    logger.info(f"🔒 Locking profit for {position_id}: SL at +{pips} pips ({new_sl})")
                    
                    try:
                        await self.trading_provider.modify_position(
                            position_id,
                            stop_loss=new_sl,
                            take_profit=current_tp
                        )
                        
                        modified_count += 1
                    except ValueError as e:
                        logger.warning(f"⚠️ Cannot lock profit for {position_id}: {str(e)}")
                        continue
                    
                    # Update database
                    db_trades = await self.db.get_trades_by_magic_number(magic_number)
                    for trade in db_trades:
                        if trade.get('positionId') == position_id:
                            await self.db.update_trade_field(trade['id'], 'stopLoss', new_sl)
                            await self.db.log_trade_action(
                                trade_id=trade['id'],
                                action_type='LOCK_PROFIT',
                                success=True,
                                new_sl=new_sl,
                                triggered_by='telegram_reply',
                                trigger_source='user_command_lock_profit',
                                details=f'User reply: "{command}" - Locked profit at +{pips} pips'
                            )
                    
                except Exception as e:
                    errors.append(f"Failed to lock profit for {position_id}: {str(e)}")
                    logger.error(errors[-1])
            
            return {
                "success": True,
                "message": f"Locked profit for {modified_count} position(s) at +{pips} pips",
                "modified_count": modified_count,
                "pips": pips,
                "errors": errors if errors else None
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to lock profit: {str(e)}")
            return {"success": False, "error": str(e)}

    async def _modify_sl_to_price(self, positions: List[Dict], new_sl: float, magic_number: int, orders: List[Dict] = None) -> Dict:
        """Move SL to a specific price on open positions and on pending orders"""
        modified_count = 0
        orders_modified = 0
        errors = []

        # Pending orders keep their entry; only their SL changes. An SL on the wrong
        # side of an order's entry (provider locking profit past it) means the trade
        # has moved on — that unfilled order is stale, so cancel it.
        if orders and hasattr(self.trading_provider, 'modify_order'):
            stale = []
            for order in orders:
                entry = order.get('openPrice')
                is_sell = 'SELL' in str(order.get('type', '')).upper()
                if entry is not None and ((is_sell and new_sl <= entry) or (not is_sell and new_sl >= entry)):
                    stale.append(order)
            if stale:
                await self._cancel_pending_orders(stale, magic_number, f"Auto-cancel (SL {new_sl} past pending entry)")
                orders = [o for o in orders if o not in stale]
            for order in orders:
                order_id = order.get('id')
                try:
                    await self.trading_provider.modify_order(order_id, stop_loss=new_sl, take_profit=order.get('takeProfit'))
                    orders_modified += 1
                except Exception as e:
                    errors.append(f"Failed to modify SL on pending order {order_id}: {str(e)}")
        elif orders:
            logger.info(f"⚠️ Provider can't modify pending orders - cancelling {len(orders)} instead")
            cancelled_result = await self._cancel_pending_orders(orders, magic_number, "Auto-cancel (pending order SL not modifiable)")
            if not positions:
                cancelled_result['message'] = f"⚠️ Cancelled {cancelled_result.get('cancelled_count', 0)} pending order(s) - cannot modify SL on pending orders"
                return cancelled_result

        if not positions and not orders_modified:
            return {
                "success": False,
                "error": errors[0] if errors else "No open positions found to modify SL"
            }
        
        for position in positions:
            try:
                position_id = position.get('id')
                current_tp = position.get('takeProfit')
                
                # Apply spread adjustment
                adjusted_sl = await self.spread_adjustment.adjust_sl_for_position(
                    position_id,
                    new_sl
                )
                
                try:
                    await self.trading_provider.modify_position(
                        position_id,
                        stop_loss=adjusted_sl,
                        take_profit=current_tp
                    )
                    
                    modified_count += 1
                except ValueError as e:
                    errors.append(f"Invalid stops for {position_id}: {str(e)}")
                
            except Exception as e:
                errors.append(f"Failed to modify {position_id}: {str(e)}")
        
        success = modified_count > 0 or orders_modified > 0

        if success and modified_count > 0:
            try:
                db_trades_for_reply = await self.db.get_trades_by_magic_number(magic_number)
                signal_ids = set(t.get('signalId') for t in db_trades_for_reply if t.get('signalId'))
                import random as _rnd
                signal_forwarder_service = self.forwarder
                _sl_text = _rnd.choice([
                    f"moved the stop to <code>{new_sl}</code>",
                    f"stop updated to <code>{new_sl}</code>",
                    f"shifted stop to <code>{new_sl}</code>",
                    f"new stop: <code>{new_sl}</code>",
                    f"stop now at <code>{new_sl}</code>",
                    f"adjusted stop to <code>{new_sl}</code>",
                ])
                for sig_id in signal_ids:
                    await signal_forwarder_service.reply_action(sig_id, _sl_text)
            except Exception as _exc:
                logger.debug(f"Suppressed exception: {_exc!r}")

        return {
            "success": success,
            "message": f"Modified SL to {new_sl} on {modified_count} position(s) and {orders_modified} pending order(s)",
            "error": None if success else (errors[0] if errors else f"Failed to modify SL for any positions to {new_sl}"),
            "modified_count": modified_count,
            "new_sl": new_sl,
            "errors": errors if errors else None
        }

    @staticmethod
    def _legs_of_tp(positions: List[Dict], orders: List[Dict], db_trades: List[Dict], tp_index: int):
        """
        The open positions and pending orders that hold the setup's TP number tp_index.

        Each leg of a multi-TP setup is recorded with its target number (Trade.tpLevel).
        Without that record the targets are ranked by price, nearest to the entry first.
        Returns (positions, orders, known) — known is False when the setup has no such target.
        """
        numbered = [t for t in db_trades or [] if t.get('tpLevel')]
        if numbered:
            mine = [t for t in numbered if int(t['tpLevel']) == int(tp_index)]
            tickets = {str(x) for t in mine for x in (t.get('positionId'), t.get('orderId')) if x}
            return ([p for p in positions if str(p.get('id')) in tickets],
                    [o for o in orders if str(o.get('id')) in tickets], bool(mine))
        legs = [x for x in list(positions) + list(orders) if x.get('takeProfit')]
        if not legs:
            return [], [], False
        is_sell = 'SELL' in str(legs[0].get('type', '')).upper()
        levels = sorted({float(x['takeProfit']) for x in legs}, reverse=is_sell)
        if tp_index < 1 or tp_index > len(levels):
            return [], [], False
        level = levels[tp_index - 1]
        return ([p for p in positions if p.get('takeProfit') and float(p['takeProfit']) == level],
                [o for o in orders if o.get('takeProfit') and float(o['takeProfit']) == level], True)

    async def _modify_tp_to_price(self, positions: List[Dict], new_tp: float, magic_number: int,
                                  orders: List[Dict] = None, tp_index: Optional[int] = None) -> Dict:
        """
        Helper to modify TP to specific price.

        tp_index: the message named one target ("Tp1 : 3858") — only the leg(s) holding
        that target move, pending ones included; the other targets stay where they are.
        """
        modified_count = 0
        errors = []
        orders_of_tp: List[Dict] = []
        if tp_index:
            try:
                db_trades = await self.db.get_trades_by_magic_number(magic_number) or []
            except Exception as e:
                logger.debug(f"Trade lookup for TP{tp_index} skipped: {e}")
                db_trades = []
            positions, orders_of_tp, known = self._legs_of_tp(positions, orders or [], db_trades, int(tp_index))
            if not known:
                return {"success": False, "modified_count": 0,
                        "error": f"This setup has no TP{tp_index} — no take profit was changed"}
            if not positions and not orders_of_tp:
                logger.info(f"🤚 TP{tp_index} has no open leg any more — nothing to move")
                return {"success": True, "ignored": True, "modified_count": 0, "reason": "tp_leg_not_open",
                        "message": f"TP{tp_index} has no open position or pending order any more — nothing changed"}
        # A runner is in the setup without a TP on purpose: a new target from the
        # channel moves the targets of the positions that have one, not the runner.
        runners: set = set()
        try:
            from src.services.signal_continuity import signal_continuity
            runners = await signal_continuity._runner_tickets(magic_number)
        except Exception as e:
            logger.debug(f"Runner lookup for TP change skipped: {e}")
        skipped_runners = 0
        
        for position in positions:
            try:
                position_id = position.get('id')
                current_sl = position.get('stopLoss')
                if str(position_id) in runners and not position.get('takeProfit'):
                    skipped_runners += 1
                    continue
                
                try:
                    await self.trading_provider.modify_position(
                        position_id,
                        stop_loss=current_sl,
                        take_profit=new_tp
                    )
                    
                    modified_count += 1
                except ValueError as e:
                    errors.append(f"Invalid stops for {position_id}: {str(e)}")
                
            except Exception as e:
                errors.append(f"Failed to modify {position_id}: {str(e)}")
        
        for order in orders_of_tp:
            try:
                await self.trading_provider.modify_order(
                    order.get('id'), stop_loss=order.get('stopLoss'), take_profit=new_tp)
                modified_count += 1
            except Exception as e:
                errors.append(f"Failed to modify order {order.get('id')}: {str(e)}")

        success = modified_count > 0 or not (positions or orders_of_tp) or (
            not orders_of_tp and skipped_runners == len(positions))

        if success and modified_count > 0:
            try:
                import random as _rnd
                db_trades_for_reply = await self.db.get_trades_by_magic_number(magic_number)
                signal_ids = set(t.get('signalId') for t in db_trades_for_reply if t.get('signalId'))
                signal_forwarder_service = self.forwarder
                _tp_text = _rnd.choice([
                    f"updated target to <code>{new_tp}</code>",
                    f"TP moved to <code>{new_tp}</code>",
                    f"new target: <code>{new_tp}</code>",
                    f"going for <code>{new_tp}</code> now",
                    f"target shifted to <code>{new_tp}</code>",
                    f"TP now at <code>{new_tp}</code>",
                ])
                for sig_id in signal_ids:
                    await signal_forwarder_service.reply_action(sig_id, _tp_text)
            except Exception as _exc:
                logger.debug(f"Suppressed exception: {_exc!r}")

        return {
            "success": success,
            "message": (f"Moved TP{tp_index} to {new_tp} on {modified_count} leg(s)" if tp_index
                        else f"Modified TP for {modified_count} position(s) to {new_tp}"),
            "error": None if success else (errors[0] if errors else f"Failed to modify TP for any positions to {new_tp}"),
            "modified_count": modified_count,
            "new_tp": new_tp,
            "errors": errors if errors else None
        }

    async def _add_to_position_lots(self, positions: List[Dict], lots: float, magic_number: int) -> Dict:
        """Add to position with specific lot size"""
        try:
            if not positions:
                return {"success": False, "error": "No positions to add to"}
            
            # Get first position details
            position = positions[0]
            symbol = position.get('symbol')
            is_buy = position.get('type') == 'POSITION_TYPE_BUY'
            position.get('openPrice')
            sl = position.get('stopLoss')
            tp = position.get('takeProfit')
            
            logger.info(f"➕ Adding {lots} lots to {symbol} position")
            
            # Open additional position with same parameters
            from src.models import TradingSignal, SignalAction, OrderType
            
            signal = TradingSignal(
                symbol=symbol,
                action=SignalAction.OPEN,
                order_type=OrderType.BUY if is_buy else OrderType.SELL,
                entry_price=None,  # Market order
                stop_loss=sl,
                take_profit=[tp] if tp else [],
                lot_size=lots,
                raw_message=f"Add to position: {lots} lots"
            )
            
            # Execute trade
            from src.models import RiskAssessment
            risk = RiskAssessment(
                approved=True,
                calculated_lot_size=lots,
                risk_percent=0,
                risk_amount=0,
                stop_loss_pips=0,
                take_profit_pips=0,
                risk_reward_ratio=0,
                warnings=[],
                reason="Add to position via reply command"
            )
            result = await self.trading_provider.execute_trade(signal, risk, magic_number)
            
            if result.success:
                logger.success(f"✅ Added {lots} lots to position")

                # The add belongs to the signal of the position it was added to. A magic
                # (= Telegram message id) can repeat across channels, so match the live
                # position first and only then fall back to any trade with that magic.
                db_trades = await self.db.get_trades_by_magic_number(magic_number)
                live_ids = {str(p.get('id')) for p in positions}
                parent = next((t for t in db_trades if str(t.get('positionId')) in live_ids), None) \
                    or (db_trades[0] if db_trades else None)
                if parent:
                    await self.db.log_trade_action(
                        trade_id=parent['id'],
                        action_type='ADD_POSITION',
                        success=True,
                        triggered_by='telegram_reply',
                        trigger_source='user_command_add_position',
                        details=f'User reply - Added {lots} lots to position'
                    )
                    # Record the add as its own Trade row. Without one the copier snapshot
                    # can't tie the ticket to the signal, and mirror EAs size it like a
                    # hand-opened trade at a full risk budget (0.01 here -> 0.11 there).
                    try:
                        trade_id = await self.db.create_trade(
                            signal_id=parent['signalId'],
                            signal=signal,
                            risk_assessment=risk,
                            parent_trade_id=parent['id'],
                            magic_number=magic_number,
                        )
                        await self.db.update_trade_execution(trade_id, result)
                        await self.db.update_signal_status_from_trades(parent['signalId'])
                    except Exception as e:
                        logger.error(f"❌ Added position {result.position_id} but could not record it: {e}")

                return {
                    "success": True,
                    "message": f"Added {lots} lots to {symbol} position",
                    "lots_added": lots,
                    "position_id": result.position_id
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to add to position: {result.error_message}"
                }
            
        except Exception as e:
            logger.error(f"❌ Failed to add to position: {str(e)}")
            return {"success": False, "error": str(e)}
