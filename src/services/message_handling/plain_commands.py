"""
Plain (non-reply) management commands such as "close all gold": detection,
parsing and execution.

Part of MessageHandler (src/services/message_handler.py); methods were moved here verbatim.
Module-level names are this module's own imports: to patch one in a test,
patch it here, not in message_handler.py.
"""
import re
import time
import asyncio
from typing import Optional, Dict, List
from datetime import datetime
from loguru import logger
from src.utils.tasks import spawn
from src.utils.split_ids import real_message_id
from src.models import TradingSignal, SignalAction, OrderType, SignalStatus
from src.models.message import MessageIdentifier
from src.services.trade_mapper import trade_mapper
from src.services.signal_service import signal_service
from src.services.reply_handler_service import reply_handler_service
from src.services.spread_adjustment_service import spread_adjustment_service
from src.services.channel_behavior_service import channel_behavior_service
from src.services.trade_context_manager import trade_context_manager
from src.services.split_post import SplitPostTracker
from src.services.action_results import partial_failures, failure_block, log_partial_failure
from src.core.database_service import db_service
from src.integrations.trading.provider_factory import create_trading_provider


class PlainCommandMixin:
    """Detect, parse and execute plain management commands."""

    def _is_plain_command(self, text: str) -> bool:
        """
        Layer 0: ZERO-AI keyword check — is this probably a trade management command?
        Uses the same candle/entry-context suppression as _is_reply_or_update.
        """
        text_lower = text.lower().strip()
        if not self._COMMAND_KEYWORDS_RE.search(text_lower):
            return False

        # Suppress candle-context false positives ("if candle closes below 4420")
        if re.search(r'candles?\s+close', text_lower):
            return False
        # Conditional close talk — require the inflected "closes/closed" so the
        # imperative "close 4020 ..." is not swallowed by a stray "if"/"when".
        if re.search(r'\b(?:if|when|once|after)\b[^.]*\bclose[sd]\b', text_lower):
            return False

        # Suppress if it has multiple entry markers (it's a signal, not a command)
        entry_markers = [
            r'\bentry\s+zone\b', r'\bentry\b.*\d{3,}', r'\bbuy\s+zone\b',
            r'\bsell\s+zone\b', r'\bstop\s+loss\b.*\d{3,}', r'\btake\s+profit\b.*\d{3,}',
            r'\bre-?entry\b', r'\bfallback\b',
        ]
        if sum(1 for p in entry_markers if re.search(p, text_lower)) >= 2:
            return False

        return True

    def _parse_plain_command(self, text: str) -> Optional[Dict]:
        """
        Layer 1: ZERO-AI regex-based command parser.
        Returns {'action': str, 'symbol': str|None, 'value': float|None}
        or None if can't parse.
        """
        text_lower = text.lower().strip()
        for pattern, action, symbol_group in self._PARSE_PATTERNS:
            m = re.search(pattern, text_lower)
            if not m:
                continue

            # Ambiguous / scoped closes ("close half", "close all but gold", "close bottom hold upper")
            # must NEVER degrade to a full close when no AI is available to interpret them.
            if action in ('close', 'close_all') and self._AMBIGUOUS_CLOSE_RE.search(text_lower):
                logger.warning(f"⚠️ Ambiguous close command not parsed by keywords (needs AI): {text[:80]!r}")
                return None

            result: Dict = {'action': action, 'symbol': None, 'value': None}

            # Extract value if present (group 1 is always value for patterns that have one)
            if symbol_group is not None:
                try:
                    result['value'] = float(m.group(symbol_group))
                except (ValueError, IndexError):
                    pass

            # Extract symbol from text
            symbol = trade_context_manager._extract_symbol_from_message(text)
            if symbol:
                result['symbol'] = symbol
            elif symbol_group == 1 and action == 'close':
                # For "close <word>" — the word might be a symbol name like "gold"
                raw_symbol = m.group(1).strip()
                mapped = trade_context_manager._extract_symbol_from_message(raw_symbol)
                if mapped:
                    result['symbol'] = mapped

            return result

        return None

    async def _handle_plain_command(
        self,
        parsed: Dict,
        channel_id: str,
        content: str,
        message_id: MessageIdentifier,
        signal_callback=None,
        image_data: Optional[bytes] = None,
    ) -> bool:
        """
        Execute a plain-text command detected by Layer 0/1 parser.
        Routes through the existing reply_handler_service execution methods.

        Args:
            parsed: Dict from _parse_plain_command with action, symbol, value
            channel_id: Telegram channel ID
            content: Original message text
            message_id: MessageIdentifier
            signal_callback: Optional callback (used for reenter fallback)
            image_data: Optional image bytes
        """
        started_at = time.monotonic()
        action = parsed.get('action')
        symbol = parsed.get('symbol')
        value = parsed.get('value')

        logger.info(
            f"📨 Plain command detected (Layer 0/1): action={action} "
            f"symbol={symbol or '?'} value={value} "
            f"msg=\"{content[:60]}\""
        )

        # ── Layer 2: Resolve symbol from open positions if missing ──────
        if not symbol and action != 'cancel_orders':
            open_positions = await db_service.get_open_positions(channel_id=channel_id)
            if open_positions:
                # Single position → use it; multiple → most recent
                if len(open_positions) == 1:
                    symbol = open_positions[0].get('symbol')
                    logger.info(f"   🔍 Symbol resolved via single open position: {symbol}")
                else:
                    most_recent = max(open_positions, key=lambda p: p.get('opened_at', datetime.min))
                    symbol = most_recent.get('symbol')
                    logger.info(f"   🔍 Symbol resolved via most recent position: {symbol}")

            # Also try context manager's conversation history
            if not symbol:
                resolved = await trade_context_manager.resolve_symbol_for_command(
                    command_text=content,
                    action=SignalAction.CLOSE,
                    channel_id=channel_id,
                )
                if resolved:
                    symbol = resolved
                    logger.info(f"   🔍 Symbol resolved via context manager: {symbol}")

        if not symbol and action not in ('cancel_orders', 'close_all'):
            logger.warning(f"   ⚠️  Could not resolve symbol for '{action}' — no open positions in channel {channel_id}")
            # Notify user
            try:
                from src.integrations.telegram.unified_sender import notification_sender
                await notification_sender.send_notification(
                    f"⚠️ <b>Cannot Execute</b>\n\n"
                    f"💬 <code>{content}</code>\n\n"
                    f"No open positions found in this channel — "
                    f"can't determine which trade you mean.\n\n"
                    f"💡 Reply directly to the signal message instead.",
                    category='command_response'
                )
            except Exception as _exc:
                logger.debug(f"Suppressed exception: {_exc!r}")
            return False

        # ── Get positions from broker/DB for this symbol + channel ──────
        open_positions = await db_service.get_open_positions_by_symbol(
            symbol=symbol, channel_id=channel_id
        )

        if not open_positions:
            logger.warning(f"   ⚠️  No open positions for {symbol} in channel {channel_id}")
            try:
                from src.integrations.telegram.unified_sender import notification_sender
                await notification_sender.send_notification(
                    f"⚠️ <b>No Open Trades</b>\n\n"
                    f"📊 <b>{symbol}</b> — no active positions "
                    f"found in this channel.\n\n"
                    f"The trade may have already been closed.",
                    category='command_response'
                )
            except Exception as _exc:
                logger.debug(f"Suppressed exception: {_exc!r}")
            return False

        # ── Build positions list for reply_handler_service ──────────────
        trading_provider = self.trading_provider
        positions_for_exec: List[Dict] = []
        orders_for_exec: List[Dict] = []
        db_trades: List[Dict] = []
        magic_numbers: set = set()

        for pos in open_positions:
            position_id = pos.get('position_id')
            order_id = pos.get('order_id')
            magic_number = pos.get('magic_number')
            if magic_number:
                magic_numbers.add(magic_number)

            if position_id:
                # Fetch live position from broker
                try:
                    all_positions = await trading_provider.get_open_positions(use_cache=False)
                    live_pos = next(
                        (p for p in (all_positions or []) if str(p.get('id')) == str(position_id)),
                        None
                    )
                    if live_pos:
                        positions_for_exec.append(live_pos)
                except Exception as e:
                    logger.warning(f"   Broker fetch failed for position {position_id}: {e}")

            if order_id:
                try:
                    all_orders = await trading_provider.get_all_pending_orders(use_cache=False)
                    live_order = next(
                        (o for o in (all_orders or []) if str(o.get('id')) == str(order_id)),
                        None
                    )
                    if live_order:
                        orders_for_exec.append(live_order)
                except Exception as e:
                    logger.warning(f"   Broker fetch failed for order {order_id}: {e}")

            # Build DB trade record
            db_trades.append({
                'id': pos.get('trade_id'),
                'signalId': pos.get('signal_id'),
                'positionId': position_id,
                'orderId': order_id,
                'status': pos.get('status'),
                'stopLoss': pos.get('stop_loss'),
                'takeProfit': pos.get('take_profit'),
                # Needed by entry-scoped close when a live openPrice is unavailable
                'entryPrice': pos.get('entry_price'),
                'entryLeg': pos.get('entry_leg'),
            })

        # ── Execute command ──────────────────────────────────────────────
        result: Dict = {'success': False, 'error': 'Unknown action'}

        try:
            if action in ('close', 'close_all'):
                if positions_for_exec or orders_for_exec:
                    result = await reply_handler_service._close_all_orders(
                        positions_for_exec, orders_for_exec,
                        magic_number=magic_numbers.pop() if magic_numbers else 0,
                        command=content,
                        db_trades=db_trades,
                    )
                    result['symbol'] = symbol
                else:
                    result = {'success': False, 'error': 'No active positions or orders to close'}

            elif action == 'close_by_entry':
                # Leg-scoped: close only the entry named, hold the rest.
                if positions_for_exec:
                    result = await reply_handler_service._close_positions_by_entry(
                        positions_for_exec,
                        magic_number=magic_numbers.pop() if magic_numbers else 0,
                        command=content,
                        entry_price=value,
                        db_trades=db_trades,
                    )
                    result['symbol'] = symbol
                else:
                    result = {'success': False, 'error': 'No active positions to close'}

            elif action == 'breakeven':
                result = await reply_handler_service._move_to_breakeven(
                    positions_for_exec,
                    magic_number=magic_numbers.pop() if magic_numbers else 0,
                    orders=orders_for_exec,
                )
                result['symbol'] = symbol

            elif action == 'modify_sl':
                result = await reply_handler_service._modify_sl_to_price(
                    positions_for_exec, new_sl=value,
                    magic_number=magic_numbers.pop() if magic_numbers else 0,
                    orders=orders_for_exec,
                )
                result['symbol'] = symbol

            elif action == 'modify_tp':
                result = await reply_handler_service._modify_tp_to_price(
                    positions_for_exec, new_tp=value,
                    magic_number=magic_numbers.pop() if magic_numbers else 0,
                )
                result['symbol'] = symbol

            elif action == 'partial_close':
                percentage = value or 50.0
                result = await reply_handler_service._partial_close_by_percentage(
                    positions_for_exec,
                    percentage=percentage,
                    magic_number=magic_numbers.pop() if magic_numbers else 0,
                    command=f"partial close {percentage}%",
                )
                result['symbol'] = symbol

            elif action == 'lock_profit':
                pips = value or 20
                result = await reply_handler_service._lock_profit_by_pips(
                    positions_for_exec,
                    pips=pips,
                    magic_number=magic_numbers.pop() if magic_numbers else 0,
                    command=f"lock profit +{pips} pips",
                )
                result['symbol'] = symbol

            elif action == 'cancel_orders':
                result = await reply_handler_service._cancel_pending_orders(
                    orders_for_exec,
                    magic_number=magic_numbers.pop() if magic_numbers else 0,
                    command=content,
                )
                result['symbol'] = symbol

            else:
                logger.warning(f"   ⚠️  Unsupported action from parser: {action}")
                result = {'success': False, 'error': f'Unsupported action: {action}'}

        except Exception as e:
            logger.error(f"   ❌ Command execution failed: {e}")
            result = {'success': False, 'error': str(e)}

        # ── Log timing ──────────────────────────────────────────────────
        elapsed_ms = (time.monotonic() - started_at) * 1000
        logger.info(f"   ⏱️  Plain command handled in {elapsed_ms:.0f}ms: "
                    f"action={action} symbol={symbol} success={result.get('success')}")

        # ── Send confirmation to notification channel ───────────────────
        try:
            from src.integrations.telegram.unified_sender import notification_sender
            if result.get('success'):
                failures = partial_failures(result)
                if failures:
                    log_partial_failure(failures, f"Plain command '{content}' on {symbol}")
                msg = (
                    f"{'⚠️ <b>Command Partly Executed</b>' if failures else '✅ <b>Command Executed</b>'}\n\n"
                    f"📊 <b>Symbol:</b> {symbol}\n"
                    f"💬 <b>Command:</b> {content}\n\n"
                    f"{result.get('message', 'Done')}"
                    f"{failure_block(failures) if failures else ''}"
                )
                await notification_sender.send_message(msg, category='command_response')
            else:
                error = result.get('error') or result.get('message') or 'Unknown error'
                logger.warning(f"   ⚠️  Plain command failed: {error}")
        except Exception as _exc:
            logger.debug(f"Suppressed exception: {_exc!r}")

        # ── Track in conversation history ───────────────────────────────
        trade_context_manager.add_to_conversation_history(
            channel_id=channel_id,
            message=content,
            signal_info={"action": action, "symbol": symbol}
        )

        return result.get('success', False)

    @staticmethod
    def _is_global_close(text: str) -> bool:
        """'close ALL / both / everything / full' as whole words. A substring test treated
        'small loss', 'call', 'overall' as 'ALL' and closed every trade of the symbol."""
        return bool(re.search(r'\b(?:all|global|everything|both|full)\b', text or "", re.IGNORECASE))

    def _is_explicit_close_command(self, text: str) -> bool:
        """
        Word-boundary close detection with the same candle/entry-context suppression
        used for update routing. Used by the edited-message handler so that edits like
        "if 4 M15 candles close below 4420" can never close live positions.
        """
        text_lower = (text or "").lower()
        if not re.search(r'\b(close|closed|closing|exit|exited)\b', text_lower):
            return False

        candle_close_patterns = [
            r'candles?\s+close[sd]?\b',     # "candle closes", "candles close"
            r'\bclose[sd]?\s+(below|above|under|over)\b',  # "closes below 4420"
            r'\bm\d+\s+close\b',             # "M15 close", "H4 close"
            r'\bprice\s+close[sd]?\b',        # "price closes"
            r'\bclose[sd]?\s+\d+',            # "closes 4420" (bare price)
        ]
        if any(re.search(p, text_lower) for p in candle_close_patterns):
            return False

        entry_markers = [
            r'\bentry\s+zone\b', r'\bentry\b.*\d{3,}', r'\bbuy\s+zone\b',
            r'\bsell\s+zone\b', r'\bstop\s+loss\b.*\d{3,}', r'\btake\s+profit\b.*\d{3,}',
            r'\bre-?entry\b', r'\bfallback\b',
        ]
        if sum(1 for p in entry_markers if re.search(p, text_lower)) >= 2:
            return False

        return True
