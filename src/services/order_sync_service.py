"""
Order Synchronization Service
Single source of truth for syncing positions/orders between MT5/MetaAPI and the database.

Design goals:
- One clean sync pass per cycle (no dual-loop conflicts with position_monitor_service)
- Provider-aware intervals: MT5 REST = 3 s (no limits), MetaAPI = 5 s (cloud limits)
- Clean state machine: PENDING→RUNNING, RUNNING→CLOSED, PENDING→CANCELLED
- Grace-period counters to avoid false closures from transient API glitches
- Reopen detection: CLOSED/CANCELLED trades whose position is still live in provider
- Single place for close notifications (no duplicate firing)
"""
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set
from loguru import logger

from src.integrations.trading.provider_factory import create_trading_provider
from src.core.database_service import db_service
from src.integrations.telegram.unified_sender import notification_sender
from src.utils.trade_lock import trade_modification_lock
from config import settings


class OrderSyncService:
    """
    Unified sync engine for trade state management.

    This is the single source of truth for detecting:
      PENDING  -> RUNNING   (order filled / position opened)
      RUNNING -> CLOSED     (position closed externally)
      PENDING  -> CANCELLED  (pending order cancelled externally)
      Reopen   : incorrectly CLOSED/CANCELLED trades that are actually active

    position_monitor_service handles only trade-management rules (TP/SL/breakeven/trailing).
    It never touches trade-state transitions - that is exclusively this service's job.

    Intervals
    ---------
    MT5 REST  : settings.position_monitor_interval_seconds  (default 3 s, no API limits)
    MetaAPI   : max(settings.position_monitor_interval_seconds, 5)  (cloud rate limits)
    """

    NOTIFY_DEDUP_SECONDS: int = 60
    REOPEN_CHECK_HOURS: int = 24   # check up to 24 h back for live positions on CLOSED trades

    @property
    def CLOSE_GRACE_MISSES(self) -> int:
        return settings.order_close_grace_misses

    @property
    def CANCEL_GRACE_MISSES(self) -> int:
        return settings.order_cancel_grace_misses

    @property
    def STALE_PENDING_HOURS(self) -> int:
        return settings.order_stale_pending_hours

    # Lifecycle statuses that mean the trade is definitively closed
    _CLOSED_STATUSES = frozenset({
        "CLOSED_PROFIT", "CLOSED_LOSS", "CLOSED_BREAKEVEN"
    })
    # Lifecycle statuses that mean the order was never filled
    _CANCELLED_STATUSES = frozenset({
        "CANCELED", "EXPIRED", "REJECTED"
    })

    def __init__(self):
        self.is_running = False
        self.sync_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._trading_provider = None

        self._missing_counts: Dict[str, int] = {}
        self._notified_rr_milestones: Dict[str, Set[int]] = {}
        self._recent_close_notifs: Dict[str, datetime] = {}
        self._magic_search_cache: Dict[int, datetime] = {}  # throttle magic history calls
        self._sync_cycle: int = 0  # cycle counter for throttled ops
        # Held by a sync pass, and by anything that swaps a trade's order for a
        # position (pending → market conversion), so no pass sees the order gone
        # before the new position is linked and marks the trade CANCELLED.
        self.lock = asyncio.Lock()

    # -- Provider helpers ----------------------------------------------------

    @property
    def trading_provider(self):
        if self._trading_provider is None:
            self._trading_provider = create_trading_provider()
        return self._trading_provider

    def _sync_interval(self) -> int:
        """Provider-appropriate poll interval."""
        base = settings.position_monitor_interval_seconds  # default 3 s
        if settings.trading_provider.lower().strip() == "mt5rest":
            return base
        if getattr(self.trading_provider, 'live_reads', False):
            return base  # streamed state: reads cost no API calls
        return max(base, 5)  # MetaAPI: at least 5 s to respect cloud limits

    async def _verify_connection(self) -> bool:
        """Connection check that works for both MT5REST and MetaAPI providers."""
        try:
            if hasattr(self.trading_provider, '_verify_connection'):
                return await self.trading_provider._verify_connection()
            return self.trading_provider.is_connected
        except Exception:
            return False

    # -- Public API ----------------------------------------------------------

    async def start_auto_sync(self, interval_seconds: Optional[int] = None):
        """Start the sync loop. interval_seconds is ignored - provider interval is used."""
        if self.is_running:
            logger.warning("Order sync already running")
            return
        self.is_running = True
        self._stop_event.clear()
        interval = self._sync_interval()
        logger.success(
            f"�� Order sync started (interval: {interval}s, provider: {settings.provider_label})"
        )
        self.sync_task = asyncio.create_task(self._sync_loop(interval))

    async def stop_auto_sync(self):
        """Stop the sync loop."""
        if not self.is_running:
            return
        logger.info("🛑 Stopping order sync...")
        self.is_running = False
        self._stop_event.set()
        if self.sync_task:
            try:
                await asyncio.wait_for(self.sync_task, timeout=10.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self.sync_task.cancel()
        logger.success("✅ Order sync stopped")

    async def sync_orders_by_message(self, message_id: int, chat_id: str) -> Dict:
        """Sync orders for a specific Telegram message (reply_handler compatibility)."""
        try:
            logger.info(f"🔄 Syncing orders for message {message_id}")
            mapping = await db_service.get_message_mapping_by_message_id(chat_id, message_id)
            if not mapping:
                return {
                    "success": False,
                    "error": "Message mapping not found",
                    "message_id": message_id,
                    "chat_id": chat_id,
                }
            magic_number = mapping.get('magicNumber')
            if not magic_number:
                return {"success": False, "error": "Magic number not found"}

            provider_data = await self.trading_provider.get_all_trades_by_magic(magic_number)
            positions = provider_data.get('positions', [])
            orders = provider_data.get('orders', [])
            pos_by_id = {p['id']: p for p in positions if p.get('id')}

            db_trades = await db_service.get_trades_by_magic_number(magic_number)
            updated = 0
            for trade in db_trades:
                trade_id = trade['id']
                position_id = trade.get('positionId')
                status = trade.get('status', '')
                if status == 'CLOSED':
                    continue
                if position_id:
                    pos = pos_by_id.get(position_id)
                    if pos:
                        await self._update_trade_from_position(trade_id, pos)
                        updated += 1
                    else:
                        await self._close_trade_from_deals(
                            trade_id, trade, position_id, source='sync_by_message'
                        )
                        updated += 1

            logger.success(f"✅ Synced {updated} trade(s) for message {message_id}")
            return {
                "success": True,
                "message_id": message_id,
                "magic_number": magic_number,
                "provider_positions": len(positions),
                "provider_orders": len(orders),
                "updated": updated,
            }
        except Exception as e:
            logger.error(f"Failed to sync orders for message {message_id}: {e}")
            return {"success": False, "error": str(e)}

    async def sync_all_active_orders(self) -> Dict[str, Any]:
        async with self.lock:
            return await self._sync_all_active_orders()

    async def _sync_all_active_orders(self) -> Dict[str, Any]:
        """
        Main sync pass - fetch provider snapshot and reconcile with database.

        State machine per trade
        -----------------------
        RUNNING + positionId found     -> update profit / SL / TP
        RUNNING + positionId missing   -> lifecycle API (MT5REST) for instant status;
                                          grace counter fallback (MetaAPI)
        PENDING  + orderId found        -> keep PENDING (order still live)
        PENDING  + orderId missing      -> lifecycle API check; else grace counter
        PENDING  + positionId set       -> position found -> RUNNING
        PENDING  + no ids               -> match by magic number
        CLOSED/CANCELLED (recent)       -> if position alive in provider -> reopen to RUNNING
        """
        try:
            if not await self._verify_connection():
                logger.debug("Provider not connected - skipping sync")
                return {"success": False, "error": "Provider not connected"}

            # 1. Fetch provider snapshot ----------------------------------------
            is_mt5rest = settings.trading_provider.lower().strip() == "mt5rest"
            # MT5REST and streamed MetaAPI are always fresh; only polled MetaAPI uses the cache
            use_cache = not (is_mt5rest or getattr(self.trading_provider, 'live_reads', False))

            positions: List[dict] = await self.trading_provider.get_open_positions(
                use_cache=use_cache
            ) or []
            pending_orders: List[dict] = await self.trading_provider.get_all_pending_orders(
                use_cache=use_cache
            ) or []

            # A failed read looks identical to "account is flat". Never infer closed/cancelled
            # trades from it - skip the cycle and try again (rate-limit/timeouts/disconnects).
            if not (getattr(self.trading_provider, 'positions_ok', True)
                    and getattr(self.trading_provider, 'orders_ok', True)):
                logger.warning("⚠️ Provider snapshot unreliable (read failed) - skipping sync cycle")
                return {"success": False, "error": "Unreliable provider snapshot"}

            # 2. Build lookup maps ----------------------------------------------
            pos_by_id: Dict[str, dict] = {p['id']: p for p in positions if p.get('id')}
            order_by_id: Dict[str, dict] = {o['id']: o for o in pending_orders if o.get('id')}

            pos_by_magic: Dict[int, List[dict]] = {}
            for p in positions:
                magic = self._magic_int(p.get('magic') or p.get('clientId'))
                if magic:
                    pos_by_magic.setdefault(magic, []).append(p)

            order_by_magic: Dict[int, List[dict]] = {}
            for o in pending_orders:
                magic = self._magic_int(o.get('magic') or o.get('clientId'))
                if magic:
                    order_by_magic.setdefault(magic, []).append(o)

            logger.debug(
                f"📊 Snapshot: {len(positions)} position(s), "
                f"{len(pending_orders)} pending order(s)"
            )

            # 3. Query all genuinely active DB trades ----------------------------
            # Terminal states (CLOSED, CANCELLED, FAILED) are excluded here.
            # The reopen check (step 5) separately handles the edge case where
            # a CANCELLED/FAILED trade still has a live position in MT5.
            active_trades = await db_service.db.trade.find_many(
                where={"status": {"notIn": ["CLOSED", "CANCELLED", "FAILED"]}}
            )
            
            logger.info(f"🔍 Order sync cycle started - checking {len(active_trades)} active trades")

            # 4. Pre-fetch batch lifecycle status for ALL missing tickets --------
            lifecycle_by_ticket: Dict[str, dict] = await self._fetch_missing_lifecycle(
                active_trades, pos_by_id, order_by_id
            )

            # 5. Query recently CLOSED/CANCELLED/FAILED for reopen check ---------
            reopen_cutoff = datetime.now(timezone.utc) - timedelta(hours=self.REOPEN_CHECK_HOURS)
            closed_trades = await db_service.db.trade.find_many(
                where={
                    "status": {"in": ["CLOSED", "CANCELLED", "FAILED"]},
                    "closedAt": {"gte": reopen_cutoff},
                    "positionId": {"not": None},
                }
            )

            stats: Dict[str, int] = {
                "updated": 0, "closed": 0, "cancelled": 0,
                "reopened": 0, "pending_filled": 0,
            }
            changed_signal_ids: Set[str] = set()

            # 6. Process active trades ------------------------------------------
            for trade in active_trades:
                try:
                    changed = await self._process_active_trade(
                        trade, pos_by_id, order_by_id,
                        pos_by_magic, order_by_magic,
                        lifecycle_by_ticket, stats,
                    )
                    if changed and trade.signalId:
                        changed_signal_ids.add(trade.signalId)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"Error processing trade {trade.id[:8]}...: {e}")

            # 7. Reopen check ---------------------------------------------------
            for trade in closed_trades:
                try:
                    reopened = await self._check_reopen(trade, pos_by_id)
                    if reopened:
                        stats["reopened"] += 1
                        if trade.signalId:
                            changed_signal_ids.add(trade.signalId)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"Reopen check error for {trade.id[:8]}...: {e}")

            # 8. Update signal statuses for trades that changed -----------------
            for signal_id in changed_signal_ids:
                try:
                    await db_service.update_signal_status_from_trades(signal_id)
                except Exception as e:
                    logger.debug(f"Signal status update failed ({signal_id[:8]}...): {e}")

            if any(v > 0 for v in stats.values()):
                parts = [f"{v} {k}" for k, v in stats.items() if v > 0]
                logger.success(f"✅ Sync: {', '.join(parts)}")
            else:
                logger.debug("✅ Sync complete - no changes")

            return {"success": True, **stats}

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"❌ Sync failed: {e}")
            return {"success": False, "error": str(e)}

    async def _fetch_missing_lifecycle(
        self,
        active_trades,
        pos_by_id: Dict[str, dict],
        order_by_id: Dict[str, dict],
    ) -> Dict[str, dict]:
        """
        Collect every position/order ticket that is tracked in the DB but absent
        from the provider's open lists, then query their lifecycle status in a
        single batch API call (MT5REST only).

        Returns a dict: { ticket_str -> lifecycle_status_dict }
        Empty dict if the provider doesn't support batch lifecycle queries.
        """
        missing: List[str] = []
        for trade in active_trades:
            pos_id = trade.positionId
            ord_id = trade.orderId
            if pos_id and pos_id not in pos_by_id:
                missing.append(pos_id)
            elif ord_id and ord_id not in order_by_id and not pos_id:
                missing.append(ord_id)

        if not missing:
            return {}

        logger.debug(
            f"🔍 Lifecycle batch check for {len(missing)} missing ticket(s)"
        )
        try:
            results = await self.trading_provider.get_batch_trade_status(missing)
            # Base class returns None for providers that don't support it (MetaAPI)
            if results is None:
                return {}
            return {str(r['ticket']): r for r in results if r.get('ticket')}
        except Exception as e:
            logger.debug(f"Lifecycle batch fetch failed: {e}")
            return {}

    # -- Internal trade processing -------------------------------------------

    async def _process_active_trade(
        self,
        trade,
        pos_by_id: Dict[str, dict],
        order_by_id: Dict[str, dict],
        pos_by_magic: Dict[int, List[dict]],
        order_by_magic: Dict[int, List[dict]],
        lifecycle_by_ticket: Dict[str, dict],
        stats: Dict[str, int],
    ) -> bool:
        """Process a single active trade. Returns True if DB state changed."""
        trade_id = trade.id
        position_id = trade.positionId
        order_id = trade.orderId
        status = trade.status
        magic = trade.magicNumber
        
        logger.debug(f"Processing trade {trade_id[:8]}... status={status} position_id={position_id[:8] if position_id else None} order_id={order_id[:8] if order_id else None} magic={magic}")

        # Safety net: skip trades already in a terminal state (should be
        # filtered out by the query, but guard against edge cases).
        if status in {"CANCELLED", "FAILED", "CLOSED"}:
            logger.debug(f"Skipping trade {trade_id[:8]}... already in terminal state {status}")
            return False

        # Normalise non-standard states:
        # Any status with a positionId behaves like RUNNING (position is live).
        # Any status without a positionId behaves like PENDING (needs linking).
        # This covers: EXECUTING, PROCESSING, RUNNING, CANCELLED, FAILED
        effective_status = status
        if status not in {"RUNNING", "PENDING"}:
            effective_status = "RUNNING" if position_id else "PENDING"

        # -- RUNNING trade with linked position ----------------------------
        if effective_status == "RUNNING" and position_id:
            if position_id in pos_by_id:
                self._missing_counts.pop(position_id, None)
                await self._update_trade_from_position(trade_id, pos_by_id[position_id])
                stats["updated"] += 1
                logger.debug(f"Trade {trade_id[:8]}... position {position_id[:8]}... found in MT5 - syncing state")
                return False  # Data update only, no state change
            else:
                logger.warning(f"Trade {trade_id[:8]}... position {position_id[:8]}... NOT FOUND in MT5 - checking lifecycle")

            # Position not in open list - check lifecycle status first
            lc = lifecycle_by_ticket.get(position_id)
            if lc:
                lc_status = lc.get("status", "UNKNOWN")
                if lc_status == "RUNNING":
                    # Provider confirmed it's still alive - transient poll glitch
                    logger.debug(
                        f"🔄 Position {position_id[:8]}... RUNNING per lifecycle - ignoring miss"
                    )
                    self._missing_counts.pop(position_id, None)
                    return False
                if lc_status in self._CLOSED_STATUSES:
                    self._missing_counts.pop(position_id, None)
                    logger.info(
                        f"🛑 Position {position_id[:8]}... lifecycle={lc_status} -> CLOSED"
                    )
                    await self._close_trade_from_lifecycle(
                        trade_id, trade, position_id, lc, source='lifecycle'
                    )
                    stats["closed"] += 1
                    return True
                if lc_status in self._CANCELLED_STATUSES:
                    self._missing_counts.pop(position_id, None)
                    logger.info(
                        f"❌ Position {position_id[:8]}... lifecycle={lc_status} -> CANCELLED"
                    )
                    await db_service.update_trade_fields(trade_id, {
                        "status": "CANCELLED",
                        "closedAt": datetime.now(timezone.utc),
                    })
                    await db_service.log_trade_action(
                        trade_id=trade_id, action_type="CANCEL",
                        success=True, triggered_by="order_sync",
                        trigger_source="lifecycle_api",
                        details=f"Lifecycle status: {lc_status}",
                    )
                    await self._send_cancel_notification(trade.symbol, f"broker reported {lc_status.lower()}")
                    if trade.signalId:
                        await db_service.update_signal_status_from_trades(trade.signalId)
                        await self._reply_cancelled_if_signal_done(trade.signalId, "cancelled")
                    stats["cancelled"] += 1
                    return True
                # UNKNOWN - fall through to grace counter

            # Grace-counter fallback (MetaAPI or lifecycle returned UNKNOWN)
            count = self._missing_counts.get(position_id, 0) + 1
            self._missing_counts[position_id] = count
            if count == 2:
                logger.warning(
                    f"⚠️ Position {position_id[:8]}... missing "
                    f"({count}/{self.CLOSE_GRACE_MISSES}) - confirming"
                )
            if count >= self.CLOSE_GRACE_MISSES:
                self._missing_counts.pop(position_id, None)
                logger.info(
                    f"🛑 Position {position_id[:8]}... confirmed closed "
                    f"after {count} misses"
                )
                await self._close_trade_from_deals(
                    trade_id, trade, position_id, source='sync_all'
                )
                stats["closed"] += 1
                return True
            return False

        # -- PENDING trade with orderId (not yet a position) ---------------
        if effective_status == "PENDING" and order_id and not position_id:
            if order_id in order_by_id:
                self._missing_counts.pop(order_id, None)
                stats["updated"] += 1
                return False

            # Check lifecycle for the order ticket
            lc = lifecycle_by_ticket.get(order_id)
            if lc:
                lc_status = lc.get("status", "UNKNOWN")
                if lc_status == "PENDING":
                    # Still a pending order, just not showing in orders list (transient)
                    self._missing_counts.pop(order_id, None)
                    return False
                if lc_status == "RUNNING":
                    # Order was filled - find the resulting position by magic
                    pass  # fall through to magic-number fill detection below
                if lc_status in self._CANCELLED_STATUSES:
                    self._missing_counts.pop(order_id, None)
                    logger.info(f"❌ Order {order_id[:8]}... lifecycle={lc_status} -> CANCELLED")
                    await db_service.update_trade_fields(trade_id, {
                        "status": "CANCELLED",
                        "closedAt": datetime.now(timezone.utc),
                    })
                    await db_service.log_trade_action(
                        trade_id=trade_id, action_type="CANCEL",
                        success=True, triggered_by="order_sync",
                        trigger_source="lifecycle_api",
                        details=f"Order lifecycle status: {lc_status}",
                    )
                    await self._send_cancel_notification(trade.symbol, f"broker reported {lc_status.lower()}")
                    if trade.signalId:
                        await db_service.update_signal_status_from_trades(trade.signalId)
                        await self._reply_cancelled_if_signal_done(trade.signalId, "cancelled")
                    stats["cancelled"] += 1
                    return True

            # Order missing - did it get filled? On MT5 the position keeps the order's
            # ticket; otherwise match by magic number
            candidates = [pos_by_id[order_id]] if order_id in pos_by_id else pos_by_magic.get(magic, []) if magic else []
            if candidates:
                for pos in candidates:
                    pos_id = pos.get('id')
                    if not pos_id:
                        continue
                    existing = await db_service.db.trade.find_first(
                        where={"positionId": pos_id, "id": {"not": trade_id}}
                    )
                    if not existing:
                        logger.info(
                            f"🔗 Order {order_id[:8]}... filled "
                            f"-> position {pos_id[:8]}..."
                        )
                        self._missing_counts.pop(order_id, None)
                        await db_service.update_trade_fields(trade_id, {
                            "status": "RUNNING",
                            "positionId": pos_id,
                            "executedAt": datetime.now(timezone.utc),
                            "entryPrice": pos.get("openPrice"),
                        })
                        await db_service.log_trade_action(
                            trade_id=trade_id, action_type="EXECUTION",
                            success=True, triggered_by="order_sync",
                            trigger_source="order_filled_detection",
                            details=f"Order {order_id} filled, linked to position {pos_id}",
                        )
                        await self._forward_position_opened(trade, pos)
                        stats["pending_filled"] += 1
                        return True

            if lc and lc.get("status") == "RUNNING":
                # The broker confirms the fill - its position just isn't listed yet
                return False

            # An order that has just filled can be missing from BOTH lists for a cycle:
            # positions and orders are read one after the other and the new position may
            # not be listed yet. Never conclude "closed" or "cancelled" from one miss.
            count = self._missing_counts.get(order_id, 0) + 1
            self._missing_counts[order_id] = count
            if count < self.CANCEL_GRACE_MISSES:
                logger.debug(f"⏳ Order {order_id[:8]}... missing ({count}/{self.CANCEL_GRACE_MISSES}) - waiting")
                return False

            # Order gone, no matching position - check if it was filled & closed quickly
            # This handles the case where an order fills and the position closes before next sync
            if magic and hasattr(self.trading_provider, 'get_closed_trades_by_magic'):
                try:
                    closed_trades = await self._closed_history_candidates(magic, trade_id)
                    if closed_trades:
                        for ct in closed_trades:
                            ct_id = str(ct.get('positionId') or ct.get('id'))
                            if ct_id:
                                existing = await db_service.db.trade.find_first(
                                    where={"positionId": ct_id, "id": {"not": trade_id}}
                                )
                                if not existing:
                                    position_id = ct_id
                                    hist_status = ct.get('status', 'UNKNOWN')
                                    profit = ct.get('profit')
                                    close_price = ct.get('closePrice')
                                    
                                    logger.info(
                                        f"� Order {order_id[:8]}... filled & closed "
                                        f"-> position {position_id[:8]}... (status: {hist_status})"
                                    )
                                    if position_id:
                                        await db_service.update_trade_fields(
                                            trade_id, {"positionId": position_id}
                                        )
                                    await db_service.update_trade_closure(
                                        trade_id=trade_id,
                                        close_price=close_price,
                                        profit_loss=profit,
                                    )
                                    await db_service.log_trade_action(
                                        trade_id=trade_id, action_type="CLOSE",
                                        success=True, triggered_by="order_sync",
                                        trigger_source="fast_fill_close_detection",
                                        details=f"Order was filled and closed before next sync. Status: {hist_status}",
                                    )
                                    # Update signal status
                                    if trade.signalId:
                                        await db_service.update_signal_status_from_trades(trade.signalId)
                                    symbol = getattr(trade, 'symbol', 'Unknown') or 'Unknown'
                                    await self._send_close_notification(symbol, close_price, profit, None)
                                    stats["closed"] += 1
                                    return True
                except Exception as e:
                    logger.debug(f"Fast-fill-close check failed for magic {magic}: {e}")

            # Missing for the whole grace period, not filled, not in history: cancelled
            if count >= self.CANCEL_GRACE_MISSES:
                self._missing_counts.pop(order_id, None)
                logger.info(f"❌ Order {order_id[:8]}... cancelled (confirmed missing after {count} misses)")
                await db_service.update_trade_fields(trade_id, {
                    "status": "CANCELLED",
                    "closedAt": datetime.now(timezone.utc),
                })
                await db_service.log_trade_action(
                    trade_id=trade_id, action_type="CANCEL",
                    success=True, triggered_by="order_sync",
                    trigger_source="order_cancelled_detection",
                    details="Pending order not found in provider",
                )
                if trade.signalId:
                    await db_service.update_signal_status_from_trades(trade.signalId)
                    await self._reply_cancelled_if_signal_done(trade.signalId, "cancelled")
                stats["cancelled"] += 1
                return True
            return False

        # -- PENDING trade with positionId already linked ------------------
        if effective_status == "PENDING" and position_id:
            # CRITICAL FIX: If position_id == order_id, it's an unfilled limit order
            # Check order_id against MT5 orders, not position_id against positions
            if position_id == order_id:
                # This is a pending limit order - check if it still exists in MT5 orders
                if order_id and order_id in order_by_id:
                    # Order still pending in MT5
                    stats["updated"] += 1
                    return False
                
                # Order not found in MT5 - check lifecycle or mark as cancelled
                lc = lifecycle_by_ticket.get(order_id)
                lc_status = lc.get("status", "UNKNOWN") if lc else "UNKNOWN"
                if lc:
                    if lc_status in self._CANCELLED_STATUSES:
                        self._missing_counts.pop(order_id, None)
                        logger.info(f"❌ Order {order_id[:8]}... lifecycle={lc_status} -> CANCELLED")
                        await db_service.update_trade_fields(trade_id, {
                            "status": "CANCELLED",
                            "closedAt": datetime.now(timezone.utc),
                        })
                        await db_service.log_trade_action(
                            trade_id=trade_id, action_type="CANCEL",
                            success=True, triggered_by="order_sync",
                            trigger_source="lifecycle_cancel",
                            details=f"Order lifecycle status: {lc_status}",
                        )
                        if trade.signalId:
                            await db_service.update_signal_status_from_trades(trade.signalId)
                        stats["cancelled"] += 1
                        return True
                    if lc_status in self._CLOSED_STATUSES:
                        # Filled AND closed (SL / TP) between two syncs: it never showed
                        # up as a position, and used to end as CANCELLED with no P/L.
                        self._missing_counts.pop(order_id, None)
                        logger.info(f"🛑 Order {order_id[:8]}... filled and closed between syncs "
                                    f"(lifecycle={lc_status}) -> CLOSED")
                        await self._close_trade_from_lifecycle(
                            trade_id, trade, order_id, lc, source='lifecycle_fast_fill_close')
                        stats["closed"] += 1
                        return True
                    if lc_status == "RUNNING":
                        # Lifecycle confirms the order filled — clear any stale grace count
                        # and fall through to magic-number detection below
                        self._missing_counts.pop(order_id, None)

                # Order might have filled. On MT5 the position keeps the order's ticket;
                # otherwise detect it by magic number (as the PENDING-without-positionId
                # path above does), never taking a sibling leg's position first.
                candidates = [pos_by_id[order_id]] if order_id in pos_by_id \
                    else pos_by_magic.get(magic, []) if magic else []
                if candidates:
                    for pos in candidates:
                        pos_id = pos.get('id')
                        if not pos_id:
                            continue
                        existing = await db_service.db.trade.find_first(
                            where={"positionId": pos_id, "id": {"not": trade_id}}
                        )
                        if not existing:
                            logger.info(
                                f"🔗 Order {order_id[:8]}... filled "
                                f"-> position {pos_id[:8]}..."
                            )
                            await db_service.update_trade_fields(trade_id, {
                                "status": "RUNNING",
                                "positionId": pos_id,
                                "executedAt": datetime.now(timezone.utc),
                                "entryPrice": pos.get("openPrice"),
                            })
                            await db_service.log_trade_action(
                                trade_id=trade_id, action_type="EXECUTION",
                                success=True, triggered_by="order_sync",
                                trigger_source="order_filled_detection",
                                details=f"Order {order_id} filled, linked to position {pos_id}",
                            )
                            await self._forward_position_opened(trade, pos)
                            stats["pending_filled"] += 1
                            return True

                # No position found yet — only use grace counter when lifecycle has NOT
                # confirmed a fill (RUNNING).  If the fill is confirmed, keep waiting.
                if lc_status == "RUNNING":
                    return False

                count = self._missing_counts.get(order_id, 0) + 1
                self._missing_counts[order_id] = count
                if count >= self.CANCEL_GRACE_MISSES:
                    self._missing_counts.pop(order_id, None)
                    logger.info(f"❌ Order {order_id[:8]}... cancelled (confirmed missing after {count} misses)")
                    await db_service.update_trade_fields(trade_id, {
                        "status": "CANCELLED",
                        "closedAt": datetime.now(timezone.utc),
                    })
                    await db_service.log_trade_action(
                        trade_id=trade_id, action_type="CANCEL",
                        success=True, triggered_by="order_sync",
                        trigger_source="order_cancelled_detection",
                        details="Pending order not found in provider",
                    )
                    if trade.signalId:
                        await db_service.update_signal_status_from_trades(trade.signalId)
                        await self._reply_cancelled_if_signal_done(trade.signalId, "cancelled")
                    stats["cancelled"] += 1
                    return True
                return False
            else:
                # position_id != order_id - this is a filled position
                if position_id in pos_by_id:
                    logger.info(f"✅ Trade {trade_id[:8]}... position active -> RUNNING")
                    await db_service.update_trade_fields(trade_id, {
                        "status": "RUNNING",
                        "executedAt": datetime.now(timezone.utc),
                        "entryPrice": pos_by_id[position_id].get("openPrice"),
                    })
                    await db_service.log_trade_action(
                        trade_id=trade_id, action_type="EXECUTION",
                        success=True, triggered_by="order_sync",
                        trigger_source="pending_position_found",
                        details="Position found in provider, marking RUNNING",
                    )
                    await self._forward_position_opened(trade, pos_by_id[position_id])
                    stats["pending_filled"] += 1
                    return True
            return False

        # -- RUNNING trade without position_id - check by magic number -----
        # This handles trades that were created but never linked to MT5 positions
        if effective_status == "RUNNING" and not position_id and magic:
            # Check if there are any positions with this magic number in MT5
            if magic in pos_by_magic and pos_by_magic[magic]:
                # Positions exist in MT5 - link them
                logger.info(f"Trade {trade_id[:8]}... has no position_id but found {len(pos_by_magic[magic])} position(s) with magic {magic} - should link them")
                # The linking logic should handle this, but for now log it
                pass
            else:
                # No positions in MT5 with this magic - trade should be closed, but a
                # just-filled position can be missing from one snapshot: confirm first
                key = f"magic:{trade_id}"
                count = self._missing_counts.get(key, 0) + 1
                self._missing_counts[key] = count
                if count < self.CLOSE_GRACE_MISSES:
                    return False
                self._missing_counts.pop(key, None)
                logger.warning(f"Trade {trade_id[:8]}... is RUNNING with no position_id and no positions in MT5 (magic {magic}) - marking as closed")
                await db_service.update_trade_fields(trade_id, {
                    "status": "CLOSED",
                    "closedAt": datetime.now(timezone.utc),
                })
                await db_service.log_trade_action(
                    trade_id=trade_id, action_type="CLOSE",
                    success=True, triggered_by="order_sync",
                    trigger_source="magic_number_check",
                    details="Trade had no position_id and no positions found in MT5 with matching magic number",
                )
                if trade.signalId:
                    await db_service.update_signal_status_from_trades(trade.signalId)
                stats["closed"] += 1
                return True

        # -- PENDING trade with no IDs - match by magic number -------------
        if effective_status == "PENDING" and not position_id and not order_id and magic:
            if magic in pos_by_magic:
                for pos in pos_by_magic[magic]:
                    pos_id = pos.get('id')
                    if not pos_id:
                        continue
                    existing = await db_service.db.trade.find_first(
                        where={"positionId": pos_id}
                    )
                    if not existing:
                        logger.info(
                            f"🔗 Magic {magic} matched position {pos_id[:8]}... -> RUNNING"
                        )
                        await db_service.update_trade_fields(trade_id, {
                            "status": "RUNNING",
                            "positionId": pos_id,
                            "executedAt": datetime.now(timezone.utc),
                            "entryPrice": pos.get("openPrice"),
                        })
                        await self._forward_position_opened(trade, pos)
                        stats["pending_filled"] += 1
                        return True
            elif magic in order_by_magic:
                first_order = order_by_magic[magic][0]
                ord_id = first_order.get('id')
                if ord_id and not order_id:
                    await db_service.update_trade_fields(trade_id, {"orderId": ord_id})
                    stats["updated"] += 1
                    return False

            # No live match - check if this trade already executed+closed
            # via MT5REST trade_search (handles offline period)
            changed = await self._resolve_no_id_pending(
                trade_id, trade, magic, stats
            )
            return changed

        return False

    async def _closed_history_candidates(self, magic: int, trade_id: str) -> List[dict]:
        """
        Closed positions in the broker history with this magic that can belong to this
        trade. The magic is shared by every order of a signal (and is only the message
        id, so other channels can share it too): a position already linked to another
        trade is that trade's, and a position that is open right now has not closed —
        taking either would falsely close this trade the moment its order fills.
        """
        history = await self.trading_provider.get_closed_trades_by_magic(magic) or []
        if not history:
            return []
        try:
            live = await self.trading_provider.get_open_positions(use_cache=False)
        except Exception as e:
            logger.debug(f"Fresh position read failed - not trusting history for magic {magic}: {e}")
            return []
        if not getattr(self.trading_provider, 'positions_ok', True):
            return []
        open_ids = {str(p.get('id')) for p in live or [] if p.get('id')}
        out = []
        for ct in history:
            pid = str(ct.get('positionId') or ct.get('position_id') or ct.get('ticket') or ct.get('id') or '')
            if not pid or pid in open_ids or ct.get('is_open'):
                continue
            if await db_service.db.trade.find_first(where={"positionId": pid, "id": {"not": trade_id}}):
                continue
            out.append(ct)
        return out

    async def _resolve_no_id_pending(
        self,
        trade_id: str,
        trade,
        magic: int,
        stats: Dict[str, int],
    ) -> bool:
        """
        Handle a PENDING trade that has no positionId/orderId and no live
        provider match for its magic number.

        Strategy
        --------
        1. MT5REST: query /trade_search?magic=X for closed history.
           - If found closed  -> close the trade with real P/L.
           - If not found     -> staleness check: cancel if too old.
        2. MetaAPI / no search support: staleness check only.
        """
        created_at = getattr(trade, 'createdAt', None)
        is_stale = (
            created_at is not None
            and (datetime.now(timezone.utc) - created_at).total_seconds()
            > self.STALE_PENDING_HOURS * 3600
        )

        # Try MT5REST trade_search to find a closed trade with this magic.
        # Throttle: only call once per 60s per magic to avoid hammering the API.
        magic_last_checked = self._magic_search_cache.get(magic)
        magic_search_ok = (
            magic_last_checked is None
            or (datetime.now(timezone.utc) - magic_last_checked).total_seconds() > 60
        )
        if magic_search_ok and hasattr(self.trading_provider, 'get_closed_trades_by_magic'):
            self._magic_search_cache[magic] = datetime.now(timezone.utc)
            try:
                closed_history = await self._closed_history_candidates(magic, trade_id)
                if closed_history:
                    # Pick the most recent one
                    best = sorted(
                        closed_history,
                        key=lambda t: t.get('exit_time') or '',
                        reverse=True,
                    )[0]
                    lc_status = best.get('status', 'UNKNOWN')
                    profit = best.get('net_pnl') or best.get('profit', 0.0)
                    close_price = best.get('exit_price')
                    position_id = str(best.get('position_id') or best.get('ticket') or '')

                    if lc_status in self._CLOSED_STATUSES:
                        logger.info(
                            f"📜 Trade {trade_id[:8]}... found in history "
                            f"(magic {magic}) -> {lc_status}, P/L: ${profit:.2f}"
                        )
                        # Update positionId so closure records correctly
                        if position_id:
                            await db_service.update_trade_fields(
                                trade_id, {"positionId": position_id}
                            )
                        await db_service.update_trade_closure(
                            trade_id=trade_id,
                            close_price=close_price,
                            profit_loss=profit,
                        )
                        await db_service.log_trade_action(
                            trade_id=trade_id, action_type="CLOSE",
                            success=True, triggered_by="order_sync",
                            trigger_source="magic_history_search",
                            details=f"Found in trade history via magic {magic}. "
                                    f"Status: {lc_status}",
                        )
                        symbol = getattr(trade, 'symbol', 'Unknown') or 'Unknown'
                        await self._send_close_notification(
                            symbol, close_price, profit, None
                        )
                        self._recent_close_notifs[trade_id] = datetime.now(timezone.utc)
                        stats["closed"] += 1
                        return True

                    if lc_status in self._CANCELLED_STATUSES:
                        logger.info(
                            f"❌ Trade {trade_id[:8]}... history shows "
                            f"{lc_status} (magic {magic})"
                        )
                        await db_service.update_trade_fields(trade_id, {
                            "status": "CANCELLED",
                            "closedAt": datetime.now(timezone.utc),
                        })
                        await db_service.log_trade_action(
                            trade_id=trade_id, action_type="CANCEL",
                            success=True, triggered_by="order_sync",
                            trigger_source="magic_history_search",
                            details=f"Trade history: {lc_status}",
                        )
                        await self._send_cancel_notification(trade.symbol, f"broker reported {lc_status.lower()}")
                        if trade.signalId:
                            await db_service.update_signal_status_from_trades(trade.signalId)
                            await self._reply_cancelled_if_signal_done(trade.signalId, "cancelled")
                        stats["cancelled"] += 1
                        return True
            except Exception as e:
                logger.debug(f"Magic history search failed for magic {magic}: {e}")

        # Staleness fallback: PENDING too long with zero provider activity
        if is_stale:
            logger.warning(
                f"⏳ Trade {trade_id[:8]}... PENDING with no provider match "
                f"for >{self.STALE_PENDING_HOURS}h -> CANCELLED (stale)"
            )
            await db_service.update_trade_fields(trade_id, {
                "status": "CANCELLED",
                "closedAt": datetime.now(timezone.utc),
            })
            await db_service.log_trade_action(
                trade_id=trade_id, action_type="CANCEL",
                success=True, triggered_by="order_sync",
                trigger_source="stale_pending_detection",
                details=f"PENDING with no provider match for >{self.STALE_PENDING_HOURS}h",
            )
            await self._send_cancel_notification(trade.symbol, f"pending for over {self.STALE_PENDING_HOURS}h with no fill — expired")
            if trade.signalId:
                await db_service.update_signal_status_from_trades(trade.signalId)
                await self._reply_cancelled_if_signal_done(trade.signalId, "expired")
            stats["cancelled"] += 1
            return True

        return False

    async def _scan_all_signal_statuses(self):
        """
        Safety-net pass: update status for every non-terminal signal.

        Terminal statuses that are never re-evaluated:
          REJECTED, EXPIRED, FAILED (with no trades), CLOSED

        Protected statuses that update_signal_status_from_trades will not
        overwrite (handled inside that method):
          AWAITING_APPROVAL (VALIDATED is only protected when it has no trades)
        """
        try:
            active_signals = await db_service.db.signal.find_many(
                where={"status": {"in": [
                    "PENDING",
                    "VALIDATED",
                    "AWAITING_APPROVAL",
                    "PROCESSING",
                    "RUNNING",
                    "PARTIALLY_RUNNING",
                    "PARTIALLY_CLOSED",
                ]}}
            )
            if not active_signals:
                return
            for sig in active_signals:
                try:
                    await db_service.update_signal_status_from_trades(sig.id)
                except Exception as e:
                    logger.debug(f"Signal scan failed ({sig.id[:8]}...): {e}")
        except Exception as e:
            logger.debug(f"_scan_all_signal_statuses error: {e}")

    async def _check_reopen(self, trade, pos_by_id: Dict[str, dict]) -> bool:
        """Reopen a CLOSED/CANCELLED trade if its position is still alive in provider."""
        position_id = trade.positionId
        if not position_id or position_id not in pos_by_id:
            return False
        logger.warning(
            f"⚠️ Trade {trade.id[:8]}... is {trade.status} but position "
            f"{position_id[:8]}... is ACTIVE -> reopening"
        )
        await db_service.update_trade_fields(trade.id, {
            "status": "RUNNING",
            "closedAt": None,
        })
        await self._update_trade_from_position(trade.id, pos_by_id[position_id])
        return True

    @staticmethod
    def _reason_from_deals(deals: list) -> Optional[str]:
        """
        Extract authoritative closure reason from MT5 deal list.
        MT5 DEAL_REASON values: 0-3=manual/expert, 4=SL, 5=TP, 6=stop-out
        Also checks comment field which MT5 auto-stamps '[sl X]' / '[tp X]'.
        """
        MT5_REASON_SL = 4
        MT5_REASON_TP = 5
        MT5_REASON_STOP_OUT = 6

        exit_deals = [
            d for d in deals
            if isinstance(d, dict) and (
                d.get('entry') == 'OUT'
                or d.get('entry_raw') == 1
                or d.get('entryType') == 'DEAL_ENTRY_OUT'
            )
        ]
        if not exit_deals:
            return None

        last = exit_deals[-1]
        reason_code = last.get('reason')
        if reason_code == MT5_REASON_SL:
            return 'sl'
        if reason_code == MT5_REASON_TP:
            return 'tp'
        if reason_code == MT5_REASON_STOP_OUT:
            return 'sl'

        # Fall back to comment parsing ('[sl X]' / '[tp X]' auto-stamped by MT5)
        comment = str(last.get('comment') or '').lower()
        if comment.startswith('[sl'):
            return 'sl'
        if comment.startswith('[tp'):
            return 'tp'

        return None

    async def _close_trade_from_lifecycle(
        self,
        trade_id: str,
        trade,
        position_id: str,
        lc: dict,
        source: str,
    ):
        """
        Close a trade using data returned by the lifecycle batch API.
        For MT5REST, tries to fetch full trade lifecycle for accurate profit calculation.
        """
        last = self._recent_close_notifs.get(trade_id)
        if last and (datetime.now(timezone.utc) - last).total_seconds() < self.NOTIFY_DEDUP_SECONDS:
            return

        profit_loss: Optional[float] = lc.get("total_profit")
        close_price: Optional[float] = None
        profit_loss_pips: Optional[float] = None

        entry_price = getattr(trade, 'entryPrice', None)
        symbol = getattr(trade, 'symbol', '') or ''
        action = getattr(trade, 'action', None)

        # Try to use trade_lifecycle API for accurate profit calculation (MT5REST only)
        is_mt5rest = settings.trading_provider.lower().strip() == "mt5rest"
        lifecycle_data = None
        broker_closure_reason: Optional[str] = None

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

                    # Extract authoritative closure reason from deal reason codes
                    broker_closure_reason = self._reason_from_deals(lifecycle_data.get('deals', []))
                    if broker_closure_reason:
                        logger.info(f"📋 Broker closure reason: {broker_closure_reason} (from lifecycle deals)")
                else:
                    logger.warning("⚠️ Trade lifecycle API returned no profit data, using batch lifecycle data")
                    lifecycle_data = None

        # Fallback to deals API if lifecycle not available or failed
        if not lifecycle_data and profit_loss is not None and entry_price and symbol:
            try:
                deals = await self.trading_provider.get_deals_by_position(position_id, symbol=symbol)
                if deals:
                    last_deal = deals[-1]
                    close_price = float(last_deal['price'])
                    pip_val = self._get_pip_value(symbol)
                    if await db_service.trade_is_buy(trade):
                        profit_loss_pips = (close_price - entry_price) / pip_val
                    else:
                        profit_loss_pips = (entry_price - close_price) / pip_val
                    if not broker_closure_reason:
                        broker_closure_reason = self._reason_from_deals(deals)
            except Exception as _exc:
                logger.debug(f"Suppressed exception: {_exc!r}")

        # Check if trade is already CLOSED to prevent duplicate actions
        if trade.status == "CLOSED":
            logger.info(f"Trade {trade_id[:8]}... is already CLOSED - skipping duplicate closure")
            return

        await db_service.update_trade_closure(
            trade_id=trade_id,
            close_price=close_price,
            profit_loss=profit_loss,
            profit_loss_pips=profit_loss_pips,
            broker_closure_reason=broker_closure_reason,
        )
        
        # Determine closure reason (TP hit, SL hit, or manual close)
        closure_reason = 'manual close'
        if close_price:
            tp = getattr(trade, 'takeProfit', None)
            sl = getattr(trade, 'stopLoss', None)
            # Check if TP was hit (within small tolerance for price precision)
            if tp and abs(close_price - tp) <= self._hit_tolerance(symbol):
                closure_reason = 'TP hit'
            # Check if SL was hit
            elif sl and abs(close_price - sl) <= self._hit_tolerance(symbol):
                closure_reason = 'SL hit'
        
        detail = (
            f"Position closed via lifecycle API [{lc.get('status')}] ({closure_reason}). "
            f"P/L: ${profit_loss:.2f}" if profit_loss is not None
            else f"Position closed via lifecycle API [{lc.get('status')}] ({closure_reason})"
        )
        await db_service.log_trade_action(
            trade_id=trade_id, action_type="CLOSE",
            success=True, triggered_by="order_sync",
            trigger_source=source, details=detail,
        )
        symbol = getattr(trade, 'symbol', 'Unknown') or 'Unknown'
        await self._send_close_notification(symbol, close_price, profit_loss, profit_loss_pips)
        self._recent_close_notifs[trade_id] = datetime.now(timezone.utc)

    async def _close_trade_from_deals(
        self,
        trade_id: str,
        trade,
        position_id: str,
        source: str,
    ):
        """Close a trade using deal history for accurate profit/loss (grace-counter path)."""
        # Dedup: skip if we already notified within the window
        last = self._recent_close_notifs.get(trade_id)
        if last and (datetime.now(timezone.utc) - last).total_seconds() < self.NOTIFY_DEDUP_SECONDS:
            logger.debug(f"⏭️ Skipping duplicate close for trade {trade_id[:8]}...")
            return

        logger.info(f"🛑 Closing trade {trade_id[:8]}... (pos {position_id[:8]}...)")
        close_price: Optional[float] = None
        profit_loss: Optional[float] = None
        profit_loss_pips: Optional[float] = None
        broker_closure_reason: Optional[str] = None

        try:
            symbol = getattr(trade, 'symbol', '') or ''

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
                        entry_price = summary.get('entry_price')

                        logger.info(
                            f"✅ Trade lifecycle API: P/L: ${profit_loss:.2f}, "
                            f"Entry: {entry_price}, Exit: {close_price}"
                        )

                        # Calculate pips if we have prices
                        if close_price and entry_price and symbol:
                            action = getattr(trade, 'action', None)
                            pip_val = self._get_pip_value(symbol)
                            if await db_service.trade_is_buy(trade):
                                profit_loss_pips = (close_price - entry_price) / pip_val
                            else:
                                profit_loss_pips = (entry_price - close_price) / pip_val

                        # Extract authoritative closure reason from deal reason codes
                        broker_closure_reason = self._reason_from_deals(lifecycle_data.get('deals', []))
                        if broker_closure_reason:
                            logger.info(f"📋 Broker closure reason: {broker_closure_reason} (from lifecycle deals)")

                        # Skip the fallback deals API since we have accurate data from lifecycle
                        deals = []
                    else:
                        logger.warning("⚠️ Trade lifecycle API returned no profit data, falling back to deals")
                        lifecycle_data = None

            # Fallback to deals API if lifecycle not available or failed
            if not lifecycle_data:
                deals = await self.trading_provider.get_deals_by_position(position_id, symbol=symbol)
                if deals:
                    profit_loss = sum(
                        d.get('profit', 0) for d in deals if isinstance(d, dict)
                    )
                    last_deal = deals[-1] if deals else None
                    close_price = float(last_deal['price']) if last_deal else None

                    entry_price = getattr(trade, 'entryPrice', None)
                    action = getattr(trade, 'action', None)
                    if close_price and entry_price and symbol:
                        pip_val = self._get_pip_value(symbol)
                        if await db_service.trade_is_buy(trade):
                            profit_loss_pips = (close_price - entry_price) / pip_val
                        else:
                            profit_loss_pips = (entry_price - close_price) / pip_val

                    broker_closure_reason = self._reason_from_deals(deals)
                    if broker_closure_reason:
                        logger.info(f"📋 Broker closure reason: {broker_closure_reason} (from deals API)")

                    logger.info(
                        f"✅ Deals: {len(deals)}, P/L: ${profit_loss:.2f}"
                    )
                else:
                    # Fallback: use last known DB value
                    current = await db_service.db.trade.find_unique(
                        where={"id": trade_id}
                    )
                    if current:
                        profit_loss = current.profitLoss
                        close_price = current.closePrice
                        profit_loss_pips = current.profitLossPips
                        logger.info(
                            f"📊 No deal history - using last DB profit: "
                            f"${profit_loss:.2f}" if profit_loss is not None else
                            "📊 No deal history and no DB profit available"
                        )
        except Exception as e:
            logger.error(f"Error fetching deal history for {position_id[:8]}...: {e}")

        # Check if trade is already CLOSED to prevent duplicate actions
        if trade.status == "CLOSED":
            logger.info(f"Trade {trade_id[:8]}... is already CLOSED - skipping duplicate closure")
            return

        await db_service.update_trade_closure(
            trade_id=trade_id,
            close_price=close_price,
            profit_loss=profit_loss,
            profit_loss_pips=profit_loss_pips,
            broker_closure_reason=broker_closure_reason,
        )

        # Determine closure reason (TP hit, SL hit, or manual close)
        closure_reason = 'manual close'
        if close_price:
            tp = getattr(trade, 'takeProfit', None)
            sl = getattr(trade, 'stopLoss', None)
            # Check if TP was hit (within small tolerance for price precision)
            if tp and abs(close_price - tp) <= self._hit_tolerance(symbol):
                closure_reason = 'TP hit'
            # Check if SL was hit
            elif sl and abs(close_price - sl) <= self._hit_tolerance(symbol):
                closure_reason = 'SL hit'
        
        detail = (
            f"Position closed ({closure_reason}). P/L: ${profit_loss:.2f}"
            if profit_loss is not None
            else f"Position closed externally ({closure_reason})"
        )
        await db_service.log_trade_action(
            trade_id=trade_id,
            action_type="CLOSE",
            success=True,
            triggered_by="order_sync",
            trigger_source=source,
            details=detail,
        )

        symbol = getattr(trade, 'symbol', 'Unknown') or 'Unknown'
        await self._send_close_notification(symbol, close_price, profit_loss, profit_loss_pips)
        self._recent_close_notifs[trade_id] = datetime.now(timezone.utc)

    async def _update_trade_from_position(self, trade_id: str, position: dict):
        """Update a trade record with live data from the provider position."""
        try:
            open_price = position.get('openPrice')
            sl = position.get('stopLoss')
            tp = position.get('takeProfit')
            profit = position.get('profit', 0)
            volume = position.get('volume')
            symbol = position.get('symbol', '') or ''
            pos_type = position.get('type', '')
            current_price = position.get('currentPrice')

            updates: Dict[str, Any] = {"lastModifiedAt": datetime.now(timezone.utc)}
            if open_price is not None:
                updates["entryPrice"] = open_price
            if sl is not None:
                updates["stopLoss"] = sl
            if tp is not None:
                updates["takeProfit"] = tp
            if profit is not None:
                updates["profitLoss"] = profit
            if volume is not None:
                updates["lotSize"] = volume

            if current_price and open_price and symbol:
                is_buy = pos_type == "POSITION_TYPE_BUY"
                pip_val = self._get_pip_value(symbol)
                pips = (
                    (current_price - open_price) if is_buy
                    else (open_price - current_price)
                ) / pip_val
                updates["profitLossPips"] = round(pips, 1)

            # PENDING -> RUNNING promotion
            trade = await db_service.db.trade.find_unique(where={"id": trade_id})
            if trade and trade.status == "PENDING":
                updates["status"] = "RUNNING"
                updates["executedAt"] = datetime.now(timezone.utc)
                logger.info(f"📊 Trade {trade_id[:8]}... PENDING -> RUNNING")
                # Forward position opened reply to signal channel
                await self._forward_position_opened(trade, position)

            async with trade_modification_lock(trade_id, caller='order_sync'):
                await db_service.update_trade_fields(trade_id, updates)

            # R:R milestone notification
            # CRITICAL: Use originalStopLoss for R:R calculation, NOT the current SL.
            # After partial close + breakeven, current SL is at entry price, which
            # makes sl_pips near-zero and inflates current_rr, causing spurious 1:2
            # milestone notifications for trades that already reached 1:1.
            original_sl = getattr(trade, 'originalStopLoss', None) or sl
            if trade and open_price and original_sl and current_price:
                signal_id = getattr(trade, 'signalId', None)
                await self._check_rr_milestone(
                    trade_id=trade_id,
                    signal_id=signal_id,
                    symbol=symbol,
                    open_price=open_price,
                    sl=original_sl,
                    current_price=current_price,
                    pos_type=pos_type,
                    profit=profit or 0,
                )
        except Exception as e:
            logger.error(f"Failed to update trade {trade_id[:8]}... from position: {e}")

    async def _check_rr_milestone(
        self,
        trade_id: str,
        signal_id: Optional[str],
        symbol: str,
        open_price: float,
        sl: float,
        current_price: float,
        pos_type: str,
        profit: float,
    ):
        """Fire a Telegram notification when 1:1 or 1:2 R:R milestone is reached.
        Deduplicates per signal so multi-trade signals only notify once."""
        try:
            pip_val = self._get_pip_value(symbol)
            sl_pips = abs(open_price - sl) / pip_val
            if sl_pips <= 0:
                return
            is_buy = pos_type == "POSITION_TYPE_BUY"
            profit_pips = (
                (current_price - open_price) if is_buy
                else (open_price - current_price)
            ) / pip_val
            current_rr = profit_pips / sl_pips

            # Deduplicate per signal (if available) so multi-trade signals only fire once
            dedup_key = signal_id or trade_id
            notified = self._notified_rr_milestones.setdefault(dedup_key, set())
            for milestone in (1, 2):
                if current_rr >= milestone and milestone not in notified:
                    notified.add(milestone)
                    msg = (
                        f"🎯 <b>R:R Milestone Reached</b>\n\n"
                        f"<b>Symbol:</b> {symbol}\n"
                        f"<b>Milestone:</b> 1:{milestone} R:R ✅\n"
                        f"<b>Current P/L:</b> ${profit:+.2f} ({profit_pips:+.1f} pips)"
                    )
                    await notification_sender.send_message(msg, category='rr_milestone')
                    logger.info(f"📤 R:R 1:{milestone} milestone for {symbol}")
                    # Also reply to the forwarding channel (once per signal)
                    if signal_id:
                        try:
                            from src.services.signal_forwarder_service import signal_forwarder_service
                            await signal_forwarder_service.reply_rr_milestone(signal_id, milestone, profit_pips, trade_id=trade_id)
                        except Exception as _exc:
                            logger.debug(f"Suppressed exception: {_exc!r}")
        except Exception as e:
            logger.debug(f"R:R milestone check failed: {e}")

    async def _reply_cancelled_if_signal_done(self, signal_id: str, reason: str = "") -> None:
        """Send a cancellation reply to the forwarding channel only when every
        trade for this signal is now terminal (nothing still running/pending)."""
        import random as _rnd
        try:
            signal = await db_service.db.signal.find_unique(where={"id": signal_id})
            if signal and signal.status in ("CANCELLED", "FAILED", "EXPIRED"):
                is_expired = "expired" in reason.lower() or "waited" in reason.lower()
                if is_expired:
                    text = _rnd.choice([
                        "order expired, never filled — skipping this one",
                        "waited too long, order expired",
                        "no fill, order timed out",
                        "expired without filling — moving on",
                        "order expired — price never came back",
                        "timed out, didn't get filled on this one",
                    ])
                else:
                    text = _rnd.choice([
                        "order cancelled, not entering this one",
                        "didn't fill — cancelled",
                        "order removed, sitting this one out",
                        "cancelled before filling",
                        "no fill, order pulled",
                        "order cancelled — price didn't come to us",
                        "called it off, order cancelled",
                    ])
                from src.services.signal_forwarder_service import signal_forwarder_service
                await signal_forwarder_service.reply_action(signal_id, text)
        except Exception as _exc:
            logger.debug(f"Suppressed exception: {_exc!r}")

    async def _send_cancel_notification(self, symbol: str, reason: str = "") -> None:
        """Send Telegram notification to the user when a pending order is cancelled."""
        try:
            reason_part = f" — {reason}" if reason else ""
            msg = (
                f"⚪ <b>Order Cancelled</b>\n\n"
                f"<b>{symbol}</b> pending order didn't fill{reason_part}.\n"
                f"No position was opened."
            )
            await notification_sender.send_message(msg, category='order_cancelled')
        except Exception as e:
            logger.debug(f"Could not send cancel notification: {e}")

    async def _send_close_notification(
        self,
        symbol: str,
        close_price: Optional[float],
        profit_loss: Optional[float],
        profit_loss_pips: Optional[float],
    ):
        """Send Telegram notification when a trade closes."""
        try:
            pips_text = (
                f" ({profit_loss_pips:+.1f} pips)"
                if profit_loss_pips is not None else ""
            )
            profit_text = f"${profit_loss:+.2f}" if profit_loss is not None else "N/A"
            emoji = (
                "✅" if (profit_loss or 0) > 0
                else ("❌" if (profit_loss or 0) < 0 else "⚪")
            )
            msg = (
                f"{emoji} <b>Trade Closed</b>\n\n"
                f"<b>Symbol:</b> {symbol}\n"
                f"<b>Final P/L:</b> {profit_text}{pips_text}"
            )
            if close_price is not None:
                msg += f"\n<b>Close Price:</b> {close_price}"
            await notification_sender.send_message(msg, category='trade_closed')
            logger.info(f"📤 Close notification sent for {symbol} (P/L: {profit_text})")
        except Exception as e:
            logger.debug(f"Could not send close notification: {e}")

    # -- Helpers -------------------------------------------------------------

    @staticmethod
    def _magic_int(value) -> Optional[int]:
        """Safely convert a magic number to int."""
        try:
            return int(value) if value else None
        except (ValueError, TypeError):
            return None

    @staticmethod
    async def _forward_position_opened(trade, position: dict) -> None:
        """Send a position-opened reply to the signal forwarding channel."""
        try:
            signal_id = getattr(trade, 'signalId', None)
            if not signal_id:
                return
            symbol = position.get('symbol') or getattr(trade, 'symbol', '') or ''
            open_price = position.get('openPrice')
            from src.services.signal_forwarder_service import signal_forwarder_service
            await signal_forwarder_service.reply_position_opened(
                signal_id, symbol, open_price, trade_id=getattr(trade, 'id', None)
            )
        except Exception as _exc:
            logger.debug(f"Suppressed exception: {_exc!r}")

    @classmethod
    def _hit_tolerance(cls, symbol: str) -> float:
        """Price tolerance for deciding a close was at TP/SL: one pip of the symbol
        (a fixed 0.0001 never matches gold/JPY fills, so those were always 'manual close')."""
        try:
            return max(cls._get_pip_value(symbol), 0.0001)
        except Exception:
            return 0.0001

    @staticmethod
    def _get_pip_value(symbol: str) -> float:
        """Return pip value for a symbol."""
        from src.utils.pip_utils import get_pip_size
        return get_pip_size(symbol)

    # -- Loop ----------------------------------------------------------------

    async def _sync_loop(self, interval: int):
        """Main sync loop."""
        while self.is_running and not self._stop_event.is_set():
            try:
                from src.core.prisma_client import prisma_client
                if not await prisma_client.ensure_connected():
                    logger.warning("DB unavailable - skipping sync cycle")
                    await asyncio.sleep(5)
                    continue

                # Signal status scan — pure DB, runs every cycle regardless
                # of MT5 connection. Checks signals first, then their trades.
                await self._scan_all_signal_statuses()

                await self.sync_all_active_orders()
            except asyncio.CancelledError:
                logger.info("⏹️ Order sync cancelled")
                break
            except Exception as e:
                logger.error(f"Error in sync loop: {e}")
                await asyncio.sleep(2)

            try:
                from src.utils.loop_wait import wait_stop_or_change
                await wait_stop_or_change(self._stop_event, self.trading_provider, self._sync_interval())
            except asyncio.CancelledError:
                break


# Singleton instance
order_sync_service = OrderSyncService()
