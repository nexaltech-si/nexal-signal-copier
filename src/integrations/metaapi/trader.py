import asyncio
import time
from typing import Optional, List
from datetime import datetime, timedelta, timezone
from metaapi_cloud_sdk import MetaApi, MetaStats, SynchronizationListener
from loguru import logger

from src.models import TradingSignal, TradeResult, AccountInfo, SignalType, RiskAssessment
from config import settings
from src.utils.rate_limit_handler import with_rate_limit_handling, is_rate_limit_error, is_timeout_error
from src.services.position_cache import position_cache


from src.integrations.trading.base_provider import BaseTradingProvider


class _ChangeListener(SynchronizationListener):
    """Wakes waiters on structural account changes (positions/orders/deals/account)."""

    def __init__(self, trader):
        super().__init__()
        self._trader = trader
        self._seen_ids = set()

    async def on_position_updated(self, instance_index, position):
        self._trader._signal_change()

    async def on_positions_updated(self, instance_index, positions, removed_position_ids):
        # Fires on price ticks as well as real changes; wake only on opened/closed positions
        updated = positions if isinstance(positions, list) else [positions]
        ids = {str(p.get('id')) for p in updated if isinstance(p, dict)}
        if removed_position_ids or not ids <= self._seen_ids:
            self._trader._signal_change()
        self._seen_ids |= ids
        self._seen_ids -= {str(i) for i in (removed_position_ids or [])}

    async def on_position_removed(self, instance_index, position_id):
        self._seen_ids.discard(str(position_id))
        self._trader._signal_change()

    async def on_positions_replaced(self, instance_index, positions):
        self._seen_ids = {str(p.get('id')) for p in positions or [] if isinstance(p, dict)}
        self._trader._signal_change()

    async def on_pending_order_updated(self, instance_index, order):
        self._trader._signal_change()

    async def on_pending_orders_updated(self, instance_index, orders, completed_order_ids):
        self._trader._signal_change()

    async def on_pending_order_completed(self, instance_index, order_id):
        self._trader._signal_change()

    async def on_pending_orders_replaced(self, instance_index, orders):
        self._trader._signal_change()

    async def on_deal_added(self, instance_index, deal):
        self._trader._signal_change()


class MetaAPITrader(BaseTradingProvider):
    """Execute trades using MetaAPI Cloud"""
    
    def __init__(self):
        self.api = None
        self.account = None
        self.connection = None
        self.metastats = None  # MetaStats SDK client (lazy)
        self.stream = None  # Streaming connection (read-only state; RPC does the trading)
        self._stream_subscribed = set()
        self._change_event = asyncio.Event()
        self._max_quote_age_seconds = 10.0
        self._watchdog_task = None
        self._trades_cache = {}  # (start, end) -> (timestamp, trades) for MetaStats
        self.is_connected = False
        self.symbol_cache = {}  # Cache for symbol mappings
        self.symbol_specs_cache = {}  # Cache for symbol specifications
        
        # Account info cache to prevent rate limiting
        self._account_info_cache = None
        self._account_info_cache_time = None
        self._account_info_cache_ttl = 60  # Cache for 60 seconds
        self._rate_limit_backoff_until = None  # Exponential backoff timestamp
        
        # Symbol variations to try for common instruments
        self.symbol_variations = {
            'BTCUSD': ['BTCUSD', 'BTCUSDm', 'BITCOIN', 'BTCUSD.a', 'BTC/USD', 'BTC-USD'],
            'ETHUSD': ['ETHUSD', 'ETHUSDm', 'ETHEREUM', 'ETHUSD.a', 'ETH/USD', 'ETH-USD'],
            'XAUUSD': ['XAUUSD', 'GOLD', 'XAUUSDm', 'XAUUSD.a'],
        }
        
        # Symbol-specific volume step overrides for brokers that report incorrect values
        # Only add symbols here if broker incorrectly reports volumeStep
        self.volume_step_overrides = {
            # 'BTCUSD': 0.01,  # Most brokers report this correctly
        }
        
    async def initialize(self):
        """Initialize MetaAPI connection with rate limit handling"""
        max_retries = 3
        retry_delay = 60  # Start with 60 seconds
        
        for attempt in range(max_retries):
            logger.info("🔌 Initializing MetaAPI connection...")
            
            # Initialize MetaAPI - SDK auto-detects region from account
            self.api = MetaApi(settings.metaapi_token)
            logger.info("🌍 MetaAPI SDK will auto-detect region from account")
            
            # Get account with rate limit handling
            try:
                self.account = await self.api.metatrader_account_api.get_account(
                    settings.metaapi_account_id
                )
            except Exception as e:
                if is_rate_limit_error(e):
                    if attempt < max_retries - 1:
                        logger.warning(f"⏸️ Rate limit hit during account fetch (attempt {attempt + 1}/{max_retries})")
                        logger.warning(f"⏳ Waiting {retry_delay}s before retry...")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                        continue
                    else:
                        logger.error("❌ Rate limit still active after retries. Please wait for quota reset (6 hours from first error).")
                        raise Exception("MetaAPI rate limit exceeded. Wait for quota reset and try again.")
                else:
                    logger.error(f"❌ Failed to initialize MetaAPI: {str(e)}")
                    raise
            
            # Check if account is already deployed
            logger.info("⏳ Checking account deployment status...")
            try:
                await self.account.deploy()
                await self.account.wait_deployed()
            except Exception as e:
                if "ForbiddenException" in str(type(e)) or "403" in str(e):
                    logger.warning("⚠️ Cannot deploy account (read-only token)")
                    logger.info("🔍 Assuming account is already deployed...")
                    logger.info("💡 If connection fails, please deploy manually at https://metaapi.cloud")
                    # Continue anyway - connection will fail if not deployed
                else:
                    raise
            
            # Wait for account to be connected to broker
            logger.info("⏳ Waiting for account to connect to broker...")
            try:
                await asyncio.wait_for(self.account.wait_connected(), timeout=60.0)
                logger.success("✅ Account connected to broker")
            except asyncio.TimeoutError:
                logger.error("❌ Account failed to connect to broker within 60 seconds")
                logger.error("💡 Please check MetaAPI dashboard that:")
                logger.error("   1. Account is deployed")
                logger.error("   2. MT4/MT5 terminal is running and logged in")
                logger.error("   3. Account has stable internet connection")
                raise Exception("Account not connected to broker - check MetaAPI dashboard")
            except Exception as e:
                logger.warning(f"⚠️ Could not verify broker connection: {str(e)}")
                logger.info("🔍 Attempting to connect anyway...")
            
            # Connect to terminal with timeout
            logger.info("🔗 Connecting to trading terminal...")
            self.connection = self.account.get_rpc_connection()
            
            # Try to connect with 30 second timeout
            try:
                logger.info("⏳ Waiting for connection (up to 30 seconds)...")
                await asyncio.wait_for(self.connection.connect(), timeout=30.0)
                logger.info("⏳ Synchronizing account data...")
                await asyncio.wait_for(self.connection.wait_synchronized(), timeout=30.0)
            except asyncio.TimeoutError:
                logger.error("❌ Connection timeout - check MetaAPI dashboard that account is deployed and connected")
                raise Exception("Connection timeout - check MetaAPI dashboard that account is deployed and connected")
            except Exception as e:
                if is_rate_limit_error(e):
                    if attempt < max_retries - 1:
                        logger.warning(f"⏸️ Rate limit hit during sync (attempt {attempt + 1}/{max_retries})")
                        logger.warning(f"⏳ Waiting {retry_delay}s before retry...")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                    else:
                        logger.error("❌ Rate limit still active. Please wait for quota reset.")
                        raise Exception("MetaAPI rate limit exceeded. Wait for quota reset and try again.")
                else:
                    raise
            
            self.is_connected = True
            logger.success("✅ MetaAPI connected successfully")

            await self._init_streaming()
            
            # Log account info with rate limit handling
            try:
                account_info = await self.get_account_info()
                logger.info(f"💰 Account Balance: ${account_info.balance:.2f}")
                logger.info(f"💵 Equity: ${account_info.equity:.2f}")
                logger.info(f"📊 Open Signals/Trades: {account_info.open_positions} (multi-TP trades count as 1)")
            except Exception as e:
                if is_rate_limit_error(e):
                    logger.warning("⏸️ Rate limit hit fetching account info - will retry later")
                else:
                    raise
            
            # Success - exit retry loop
            break
    
    async def disconnect(self):
        """Disconnect from MetaAPI"""
        if self._watchdog_task:
            self._watchdog_task.cancel()
            self._watchdog_task = None
        if self.stream:
            try:
                await self.stream.close()
            except Exception as e:
                logger.debug(f"Error closing streaming connection: {e}")
            self.stream = None
            self._stream_subscribed.clear()
        if self.connection:
            logger.info("🔌 Disconnecting from MetaAPI...")
            try:
                await self.connection.close()
                # Give MetaAPI websocket time to complete unsubscribe operations
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.warning(f"Error during MetaAPI disconnect: {e}")
            finally:
                self.is_connected = False
                logger.info("✅ MetaAPI disconnected")
    
    @staticmethod
    def _generate_random_comment() -> str:
        """
        Generate a random comment for trades to avoid prop firm detection.
        Uses random alphanumeric strings instead of identifiable patterns.
        """
        import random
        import string
        # Generate 8-character random string
        chars = string.ascii_uppercase + string.digits
        return ''.join(random.choice(chars) for _ in range(8))

    def _generate_symbol_variations(self, symbol: str) -> list:
        """
        Generate all possible symbol variations with common broker suffixes
        Many brokers add suffixes like +, .m, -, .a, etc.
        """
        variations = []
        
        # Try configured suffix first (fastest path when set)
        configured_suffix = settings.mt5_symbol_suffix
        if configured_suffix:
            variations.append(f"{symbol}{configured_suffix}")
        
        # Then bare symbol
        variations.append(symbol)
        
        # Common broker suffixes
        suffixes = [
            '.fx',    # EURUSD.fx
            '+',      # XAUUSD+
            '.m',     # XAUUSD.m (micro/mini lots)
            'm',      # XAUUSDm
            '.a',     # XAUUSD.a
            '-',      # XAUUSD-
            '.',      # XAUUSD.
            '.c',     # XAUUSD.c (cent accounts)
            '#',      # XAUUSD#
            '!',      # XAUUSD!
            '-5',     # XAUUSD-5 (5-digit broker)
            '-Z',     # XAUUSD-Z
            'pro',    # XAUUSDpro
            '.pro',   # XAUUSD.pro
        ]
        
        # Add suffix variations (skip configured suffix, already added)
        for suffix in suffixes:
            if suffix == configured_suffix:
                continue
            variations.append(f"{symbol}{suffix}")
        
        # Also try predefined variations if they exist
        if symbol in self.symbol_variations:
            for variation in self.symbol_variations[symbol]:
                if variation not in variations:
                    variations.append(variation)
        
        return variations
    
    # ── Streaming (read path) ────────────────────────────────────────────

    async def _init_streaming(self):
        """Open the stream and start the watchdog that reports/repairs it."""
        if not settings.metaapi_use_streaming:
            logger.info("ℹ️ MetaAPI streaming reads disabled (METAAPI_USE_STREAMING=false) - using RPC")
            return
        await self._open_stream()
        if self._watchdog_task is None or self._watchdog_task.done():
            self._watchdog_task = asyncio.create_task(self._stream_watchdog())

    async def _open_stream(self):
        """Open a streaming connection for free, push-updated reads. Falls back to RPC."""
        try:
            logger.info("📡 Opening MetaAPI streaming connection for reads...")
            stream = self.account.get_streaming_connection()
            stream.add_synchronization_listener(_ChangeListener(self))
            await asyncio.wait_for(stream.connect(), timeout=30.0)
            await asyncio.wait_for(stream.wait_synchronized(), timeout=90.0)
            self.stream = stream
            logger.success("✅ Streaming connection synchronized - reads no longer consume API calls")
        except Exception as e:
            logger.warning(f"⚠️ Streaming unavailable ({e}) - using RPC for reads")
            self.stream = None

    async def apply_streaming_setting(self):
        """Apply a live change of METAAPI_USE_STREAMING without reconnecting the RPC link."""
        if settings.metaapi_use_streaming:
            if not self.stream:
                await self._init_streaming()
        else:
            if self._watchdog_task:
                self._watchdog_task.cancel()
                self._watchdog_task = None
            if self.stream:
                try:
                    await self.stream.close()
                except Exception as e:
                    logger.debug(f"Error closing streaming connection: {e}")
                self.stream = None
                self._stream_subscribed.clear()
            logger.info("ℹ️ Streaming reads turned off - using RPC (cached) reads")

    def _signal_change(self):
        """Called from stream listeners: something structural changed on the account."""
        self._change_event.set()

    @property
    def live_reads(self) -> bool:
        """True when positions/orders/account are served live from the stream (no cache)."""
        return self._stream_ready()

    async def wait_for_change(self, timeout: float) -> bool:
        """Block until a position/order/deal change is streamed or `timeout` elapses."""
        if not self._stream_ready():
            await asyncio.sleep(timeout)
            return False
        try:
            await asyncio.wait_for(self._change_event.wait(), timeout=timeout)
            self._change_event.clear()
            return True
        except asyncio.TimeoutError:
            return False

    async def _alert(self, text: str):
        """Log + Telegram alert (never raises)."""
        logger.warning(text)
        from src.utils.audit import audit
        audit("WARNING", text[:300], "HIGH", module="metaapi_stream")
        try:
            from src.integrations.telegram.unified_sender import notification_sender
            await notification_sender.send_message(f"⚠️ <b>MetaAPI</b>\n{text}")
        except Exception as e:
            logger.debug(f"Could not send MetaAPI alert: {e}")

    async def stream_self_check(self) -> dict:
        """
        One-shot health report of the read path: active mode, stream health, and a
        cross-check of streamed positions/orders against a single RPC read.
        """
        report = {"mode": "RPC", "healthy": False, "details": []}
        if not self._stream_ready():
            report["details"].append("stream not synchronized/connected" if self.stream else "stream not open")
            return report
        ts = self.stream.terminal_state
        report["mode"] = "STREAM"
        s_pos = {str(p.get('id')) for p in ts.positions}
        s_ord = {str(o.get('id')) for o in ts.orders}
        report["details"].append(f"stream: {len(s_pos)} position(s), {len(s_ord)} order(s)")
        try:
            r_pos = {str(p.get('id')) for p in await asyncio.wait_for(self.connection.get_positions(), 15.0)}
            r_ord = {str(o.get('id')) for o in await asyncio.wait_for(self.connection.get_orders(), 15.0)}
            if r_pos != s_pos or r_ord != s_ord:
                report["details"].append(
                    f"MISMATCH vs RPC: positions {sorted(s_pos ^ r_pos)}, orders {sorted(s_ord ^ r_ord)}")
            else:
                report["healthy"] = True
                report["details"].append("matches RPC snapshot")
        except Exception as e:
            report["details"].append(f"RPC cross-check skipped ({str(e)[:60]})")
            report["healthy"] = True  # stream itself is healthy; only the cross-check failed
        try:
            lq = ts.last_quote_time
            if lq is not None and hasattr(lq, 'timestamp'):
                report["details"].append(f"last quote {datetime.now(timezone.utc).timestamp() - lq.timestamp():.0f}s ago")
        except Exception as _exc:
            logger.debug(f"Suppressed exception: {_exc!r}")
        return report

    async def _stream_watchdog(self, interval: float = 30.0, down_grace: float = 60.0, recheck_every: int = 20):
        """
        Background monitor: reports the active read path at startup, alerts on Telegram when
        the stream is lost (RPC fallback) or recovers, retries opening a failed stream, and
        periodically re-verifies streamed state against RPC.
        """
        if not settings.metaapi_use_streaming:
            return
        down_since = None
        alerted = False
        first = True
        tick = 0
        try:
            while True:
                if not self.stream and not first:  # initial attempt already made by _init_streaming
                    await self._open_stream()
                ready = self._stream_ready()
                if first or (ready and tick % recheck_every == 0):
                    rep = await self.stream_self_check()
                    if ready and not rep['healthy']:
                        await asyncio.sleep(3)  # a trade landing mid-check looks like a mismatch; re-verify once
                        rep = await self.stream_self_check()
                    logger.info(f"🩺 MetaAPI self-check: reads={rep['mode']} healthy={rep['healthy']} | " + "; ".join(rep['details']))
                    if ready and not rep['healthy']:
                        await self._alert("Streamed state does not match RPC: " + "; ".join(rep['details']))
                    first = False
                if ready:
                    if alerted:
                        await self._alert("✅ Streaming restored - reads are live again.")
                        alerted = False
                    down_since = None
                else:
                    now = datetime.now(timezone.utc).timestamp()
                    down_since = down_since or now
                    if not alerted and now - down_since >= down_grace:
                        await self._alert("Streaming connection lost - reads fell back to RPC (slower, uses API quota). Retrying automatically.")
                        alerted = True
                tick += 1
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass

    def _stream_ready(self) -> bool:
        """True when streamed terminal state can be trusted for reads."""
        s = self.stream
        if not s:
            return False
        try:
            ts = s.terminal_state
            return bool(s.synchronized and ts.connected and ts.connected_to_broker)
        except Exception:
            return False

    async def _stream_price(self, symbol: str):
        """Latest streamed quote for a (resolved) symbol, subscribing once per symbol."""
        if not self._stream_ready():
            return None
        try:
            if symbol not in self._stream_subscribed:
                await self.stream.subscribe_to_market_data(symbol, None, 5, True)
                self._stream_subscribed.add(symbol)
            price = self.stream.terminal_state.price(symbol)
            # Trading decisions must not use an old quote: fall back to a one-off RPC fetch
            qt = price.get('time') if price else None
            if qt is not None and hasattr(qt, 'timestamp'):
                age = datetime.now(timezone.utc).timestamp() - qt.timestamp()
                if age > self._max_quote_age_seconds:
                    logger.debug(f"Streamed quote for {symbol} is {age:.0f}s old - using RPC")
                    return None
            return price
        except Exception as e:
            logger.debug(f"Streamed price unavailable for {symbol}: {e}")
            return None

    async def get_symbol_price(self, symbol: str) -> dict:
        """Return current bid/ask for a symbol via MetaAPI connection."""
        resolved = await self.resolve_symbol(symbol)
        price_data = await self._stream_price(resolved)
        if price_data:
            return price_data
        return await self.connection.get_symbol_price(resolved)

    async def resolve_symbol(self, symbol: str) -> str:
        """
        Resolve symbol name to broker-specific format
        Tries various symbol name variations until one works
        Automatically tries common broker suffixes (+, .m, -, etc.)
        """
        # Check cache first
        if symbol in self.symbol_cache:
            return self.symbol_cache[symbol]
        
        # Generate all variations to try
        variations = self._generate_symbol_variations(symbol)
        
        logger.debug(f"🔍 Resolving symbol '{symbol}', trying {len(variations)} variation(s)")
        
        # Free path: look the variations up in the streamed symbol list
        if self._stream_ready():
            try:
                for variation in variations:
                    if self.stream.terminal_state.specification(variation):
                        if variation != symbol:
                            logger.success(f"✅ Symbol resolved: '{symbol}' → '{variation}'")
                        self.symbol_cache[symbol] = variation
                        return variation
            except Exception as e:
                logger.debug(f"Streamed symbol lookup failed: {e}")

        for variation in variations:
            try:
                # Try to get price for this variation
                price = await self.connection.get_symbol_price(variation)
                if price:
                    if variation != symbol:
                        logger.success(f"✅ Symbol resolved: '{symbol}' → '{variation}'")
                    else:
                        logger.debug(f"✅ Symbol '{symbol}' found (no variation needed)")
                    # Cache the mapping
                    self.symbol_cache[symbol] = variation
                    return variation
            except Exception as e:
                logger.debug(f"   ❌ '{variation}' not available: {str(e)[:50]}")
                continue
        
        # If no variation worked, return original and let it fail with clear error
        logger.warning(f"⚠️  Could not resolve symbol '{symbol}', using original name")
        logger.warning(f"💡 Tried {len(variations)} variations. Check your broker's symbol list.")
        return symbol
    
    async def execute_trade(
        self,
        signal: TradingSignal,
        risk_assessment: RiskAssessment,
        magic_number: Optional[int] = None
    ) -> TradeResult:
        """
        Execute a trade based on signal and risk assessment
        Supports multi-TP signals by splitting into multiple orders
        
        Args:
            signal: Trading signal to execute
            risk_assessment: Risk assessment with calculated position size
            
        Returns:
            TradeResult with execution details
        """
        if not self.is_connected:
            return TradeResult(
                success=False,
                error_message="MetaAPI not connected"
            )
        
        if settings.dry_run:
            logger.warning("🧪 DRY RUN MODE - Trade not executed")
            return TradeResult(
                success=True,
                position_id="DRY_RUN",
                entry_price=signal.entry_price,
                error_message="Dry run mode"
            )
        
        # CRITICAL SAFETY CHECK: Never execute trade without stop loss
        if not signal.stop_loss:
            logger.error("🚨 CRITICAL: Trade execution blocked - No stop loss!")
            return TradeResult(
                success=False,
                error_message="SAFETY BLOCK: Stop loss is mandatory for all trades"
            )
        
        # CRITICAL SAFETY CHECK: Never execute trade without take profit
        has_tp = (
            signal.take_profit
            and isinstance(signal.take_profit, list)
            and len(signal.take_profit) > 0
            and any(tp is not None for tp in signal.take_profit)
        )
        if not has_tp:
            logger.error("🚨 CRITICAL: Trade execution blocked - No take profit!")
            logger.error("   Signal TPs were either missing or stripped due to invalid direction.")
            return TradeResult(
                success=False,
                error_message="SAFETY BLOCK: Take profit is mandatory. All TPs were invalid or missing."
            )
        
        # Check if this is a multi-TP signal
        is_multi_tp = (
            signal.take_profit and
            isinstance(signal.take_profit, list) and
            len(signal.take_profit) > 1
        )

        # Multiple scale-in legs need one order PER LEG even with a single TP.
        has_multi_entry = bool(
            hasattr(signal, 'discrete_entry_prices') and signal.discrete_entry_prices()
        )

        if is_multi_tp or has_multi_entry:
            logger.info(
                f"🎯 Multi-order signal: {len(signal.take_profit or [])} TP level(s)"
                + (f", {len(signal.discrete_entry_prices())} entry legs" if has_multi_entry else "")
            )
            return await self._execute_multi_tp_trade(signal, risk_assessment, magic_number)

        # Execute single TP trade normally
        return await self._execute_single_trade(signal, risk_assessment, magic_number)
    
    async def _execute_single_trade(
        self,
        signal: TradingSignal,
        risk_assessment: RiskAssessment,
        magic_number: Optional[int] = None
    ) -> TradeResult:
        """
        Execute a single trade with one TP level
        """
        try:
            # CRITICAL SAFETY CHECK: Never execute without stop loss
            if not signal.stop_loss:
                logger.error("🚨 CRITICAL SAFETY BLOCK: Cannot execute trade without stop loss!")
                return TradeResult(
                    success=False,
                    error_message="BLOCKED: Stop loss is mandatory - trade execution prevented"
                )
            
            action = signal.action if hasattr(signal, 'action') else signal.signal_type
            logger.info(f"🚀 Executing trade: {action} {signal.symbol}")
            
            # Resolve symbol to broker-specific name
            resolved_symbol = await self.resolve_symbol(signal.symbol)
            logger.info(f"   Using symbol: {resolved_symbol}")
            
            # Round lot size to broker requirements
            lot_size = await self.round_lot_size(signal.symbol, risk_assessment.calculated_lot_size)
            logger.info(f"   Lot size: {lot_size}")
            logger.info(f"✅ Stop Loss VERIFIED: {signal.stop_loss}")
            
            # Get current price if no entry specified
            entry_price = signal.entry_price
            current_price_data = await self._stream_price(resolved_symbol) or await self.connection.get_symbol_price(resolved_symbol)
            
            if not entry_price:
                entry_price = current_price_data['ask'] if self._is_buy_signal(signal) else current_price_data['bid']
                logger.info(f"   Using market price: {entry_price}")
            
            # Final verification that SL is present
            if not signal.stop_loss:
                logger.error("🚨 Stop loss disappeared during execution - ABORTING")
                return TradeResult(
                    success=False,
                    error_message="Stop loss validation failed during execution"
                )
            
            # Warn if TP is missing
            if not signal.take_profit and not signal.take_profit_levels:
                logger.warning("⚠️  No take profit specified")
            
            # Prepare order parameters
            is_buy = self._is_buy_signal(signal)
            logger.info(f"   Order Direction: {'BUY' if is_buy else 'SELL'}")
            
            # Add stop loss (MANDATORY - should never reach here without it)
            if not signal.stop_loss:
                raise ValueError("🚨 CRITICAL: Stop loss missing at order creation!")
            
            logger.info(f"   Stop Loss: {signal.stop_loss} ✅ CONFIRMED")
            
            # Add take profit (handle both formats)
            tp_value = None
            if signal.take_profit:
                if isinstance(signal.take_profit, list) and len(signal.take_profit) > 0:
                    tp_value = signal.take_profit[0]
                elif isinstance(signal.take_profit, (int, float)):
                    tp_value = signal.take_profit
            elif hasattr(signal, 'take_profit_levels') and signal.take_profit_levels:
                tp_value = signal.take_profit_levels[0]
            
            if tp_value:
                logger.info(f"   Take Profit: {tp_value}")
            
            # Add comment and magic number
            comment = self._generate_random_comment()
            if magic_number:
                logger.info(f"   Magic Number: {magic_number}")
            
            # Prepare options dict with magic number
            order_options = {
                "comment": comment,
                "slippage": settings.slippage_pips
            }
            
            # Add magic number for MT4/MT5 tracking
            if magic_number:
                order_options["magic"] = magic_number
            
            # Determine order execution strategy based on signal type and entry price
            signal_type = signal.signal_type if signal.signal_type else (SignalType.BUY if is_buy else SignalType.SELL)
            
            # SMART EXECUTION LOGIC: Decide between market order, limit order, or immediate execution
            # This handles all scenarios including when entry_price is specified
            execute_as_market = False
            should_place_limit = False
            
            # Case 1: Entry price is specified (signal wants specific entry level)
            if entry_price:
                if is_buy:
                    # BUY order: Want to buy at entry_price or LOWER
                    current_ask = current_price_data['ask']
                    
                    if current_ask <= entry_price:
                        # Market is already at or below desired entry → Execute immediately as market order
                        logger.info(f"💰 FAVORABLE PRICE: Current ask {current_ask} <= desired entry {entry_price}")
                        logger.info("   → Executing as MARKET BUY (better price available now)")
                        execute_as_market = True
                    else:
                        # Market is above desired entry → Place limit order to wait for better price
                        logger.info(f"⏳ WAITING FOR BETTER PRICE: Current ask {current_ask} > desired entry {entry_price}")
                        logger.info(f"   → Placing BUY LIMIT order at {entry_price}")
                        should_place_limit = True
                        signal_type = SignalType.BUY_LIMIT  # Ensure correct order type
                else:
                    # SELL order: Want to sell at entry_price or HIGHER
                    current_bid = current_price_data['bid']
                    
                    if current_bid >= entry_price:
                        # Market is already at or above desired entry → Execute immediately as market order
                        logger.info(f"💰 FAVORABLE PRICE: Current bid {current_bid} >= desired entry {entry_price}")
                        logger.info("   → Executing as MARKET SELL (better price available now)")
                        execute_as_market = True
                    else:
                        # Market is below desired entry → Place limit order to wait for better price
                        logger.info(f"⏳ WAITING FOR BETTER PRICE: Current bid {current_bid} < desired entry {entry_price}")
                        logger.info(f"   → Placing SELL LIMIT order at {entry_price}")
                        should_place_limit = True
                        signal_type = SignalType.SELL_LIMIT  # Ensure correct order type
            
            # Case 2: No entry price specified → Market order (execute immediately)
            else:
                logger.info("📊 No entry price specified → Executing as MARKET order")
                execute_as_market = True
            
            # Case 3: Handle STOP orders (not affected by current price comparison)
            if signal_type in [SignalType.BUY_STOP, SignalType.SELL_STOP]:
                should_place_limit = True
                execute_as_market = False
                logger.info(f"📌 STOP order detected → Placing pending {signal_type.value} order")
            
            # Execute the order based on strategy
            if execute_as_market:
                # Execute as market order
                logger.info(f"📤 Sending {'BUY' if is_buy else 'SELL'} MARKET order to broker...")
                result = await self.connection.create_market_buy_order(
                    resolved_symbol,
                    lot_size,
                    signal.stop_loss,
                    tp_value,
                    order_options
                ) if is_buy else await self.connection.create_market_sell_order(
                    resolved_symbol,
                    lot_size,
                    signal.stop_loss,
                    tp_value,
                    order_options
                )
            
            elif should_place_limit:
                # Place pending order
                logger.info(f"📤 Placing {signal_type.value} pending order at {entry_price}...")
                
                # Prepare pending order options
                pending_options = {'comment': comment}
                if magic_number:
                    pending_options['magic'] = magic_number
                
                # Use the appropriate create order method based on signal type
                if signal_type == SignalType.BUY_LIMIT:
                    result = await self.connection.create_limit_buy_order(
                        resolved_symbol,
                        lot_size,
                        entry_price,
                        signal.stop_loss,
                        tp_value,
                        pending_options
                    )
                elif signal_type == SignalType.SELL_LIMIT:
                    result = await self.connection.create_limit_sell_order(
                        resolved_symbol,
                        lot_size,
                        entry_price,
                        signal.stop_loss,
                        tp_value,
                        pending_options
                    )
                elif signal_type == SignalType.BUY_STOP:
                    result = await self.connection.create_stop_buy_order(
                        resolved_symbol,
                        lot_size,
                        entry_price,
                        signal.stop_loss,
                        tp_value,
                        pending_options
                    )
                elif signal_type == SignalType.SELL_STOP:
                    result = await self.connection.create_stop_sell_order(
                        resolved_symbol,
                        lot_size,
                        entry_price,
                        signal.stop_loss,
                        tp_value,
                        pending_options
                    )
                else:
                    # Shouldn't reach here, but fallback to limit order
                    logger.warning(f"⚠️  Unexpected signal type {signal_type} for pending order, using limit order")
                    result = await self.connection.create_limit_buy_order(
                        resolved_symbol,
                        lot_size,
                        entry_price,
                        signal.stop_loss,
                        tp_value,
                        pending_options
                    ) if is_buy else await self.connection.create_limit_sell_order(
                        resolved_symbol,
                        lot_size,
                        entry_price,
                        signal.stop_loss,
                        tp_value,
                        pending_options
                    )
            
            else:
                # Fallback to market order (should not happen with new logic)
                logger.warning("⚠️  Unexpected execution path, executing as market order")
                fallback_options = {"comment": comment}
                if magic_number:
                    fallback_options['magic'] = magic_number
                
                result = await self.connection.create_market_buy_order(
                    resolved_symbol,
                    lot_size,
                    signal.stop_loss,
                    tp_value,
                    fallback_options
                ) if is_buy else await self.connection.create_market_sell_order(
                    resolved_symbol,
                    lot_size,
                    signal.stop_loss,
                    tp_value,
                    fallback_options
                )
            
            # Log full response details
            logger.success("✅ Trade executed successfully!")
            logger.info(f"📊 Full broker response: {result}")
            logger.info(f"   Position ID: {result.get('positionId', 'N/A')}")
            logger.info(f"   Order ID: {result.get('orderId', 'N/A')}")
            logger.info(f"   Ticket: {result.get('ticket', 'N/A')}")
            logger.info(f"   String Code: {result.get('stringCode', 'N/A')}")
            logger.info(f"   Message: {result.get('message', 'N/A')}")
            
            # Invalidate cache after new position/order
            if result.get('positionId'):
                await position_cache.invalidate_positions()
            if result.get('orderId'):
                await position_cache.invalidate_orders()
            
            # Convert datetime objects to strings for JSON serialization
            broker_response_serializable = {}
            for key, value in result.items():
                if isinstance(value, datetime):
                    broker_response_serializable[key] = value.isoformat()
                else:
                    broker_response_serializable[key] = value
            
            return TradeResult(
                success=True,
                position_id=result.get("positionId"),
                order_id=result.get("orderId"),
                entry_price=entry_price,
                broker_response=broker_response_serializable
            )
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ Trade execution failed: {error_msg}")
            
            # Enhanced diagnostics for common errors
            if 'Trade is disabled' in error_msg or 'TRADE_DISABLED' in error_msg:
                logger.error(f"🔧 DIAGNOSTIC: Trading may be disabled for {signal.symbol}")
                logger.error("Possible causes:")
                logger.error("  - Symbol trading disabled on broker/MT account")
                logger.error("  - Market is closed for this symbol")
                logger.error("  - Account trading permissions issue")
                logger.error("  - Broker may have disabled trading (check MT terminal)")
                logger.error("Action required: Verify symbol properties in MetaTrader terminal")
            elif 'Invalid stops' in error_msg or 'INVALID_STOPS' in error_msg:
                logger.error("🔧 DIAGNOSTIC: Stop levels too close to market price")
                logger.error(f"  Symbol: {signal.symbol}")
                logger.error(f"  Entry: {signal.entry_price}, SL: {signal.stop_loss}, TP: {signal.take_profit}")
                logger.error("Action required: Increase SL distance from entry or check symbol's stop level requirements")
            elif 'not connected' in error_msg.lower():
                logger.error("🔧 DIAGNOSTIC: MetaAPI connection issue")
                logger.error("Action required: Check MetaAPI account connection status")
            
            # Log additional error details if available
            if hasattr(e, 'details'):
                logger.error(f"   Error details: {e.details}")
            if hasattr(e, '__dict__'):
                logger.debug(f"   Full error object: {e.__dict__}")
            
            return TradeResult(
                success=False,
                error_message=error_msg
            )
    
    async def _execute_multi_tp_trade(
        self,
        signal: TradingSignal,
        risk_assessment: RiskAssessment,
        base_magic_number: Optional[int] = None
    ) -> TradeResult:
        """
        Execute a multi-TP trade by splitting into multiple positions
        
        For a signal with N take-profit levels:
        - Split total lot size into N equal parts
        - Execute N separate orders, each with its own TP
        - All orders share the same SL
        """
        try:
            # CRITICAL SAFETY CHECK: Never execute without stop loss
            if not signal.stop_loss:
                logger.error("🚨 CRITICAL SAFETY BLOCK: Cannot execute multi-TP trade without stop loss!")
                return TradeResult(
                    success=False,
                    error_message="BLOCKED: Stop loss is mandatory for multi-TP trades"
                )
            
            tp_levels = signal.take_profit
            num_tps = len(tp_levels)

            # ── MULTI-ENTRY (scale-in) planning ─────────────────────────────────
            # Discrete legs (e.g. SELL @4081 + MORE @4091) → one order per (leg,TP) pair.
            legs = signal.discrete_entry_prices() if hasattr(signal, 'discrete_entry_prices') else None
            if legs:
                leg_targets, tp_levels, order_leg_idx, order_tp_idx = self._pair_legs_to_tps(legs, tp_levels)
                logger.info(
                    f"🪜 Multi-entry: {len(legs)} legs {legs} × {num_tps} TP(s) → "
                    f"{len(leg_targets)} orders (leg→TP pairing)"
                )
            else:
                leg_targets = None
                order_leg_idx = [1] * num_tps
                order_tp_idx = list(range(1, num_tps + 1))
            num_orders = len(tp_levels)

            logger.info(f"🎯 Executing {'multi-entry' if leg_targets else 'multi-TP'} trade with {num_orders} order(s)")
            logger.info(f"   Total lot size: {risk_assessment.calculated_lot_size}")
            
            # Log entry range if available
            has_range_check = (hasattr(signal, 'entry_range_min') and signal.entry_range_min and 
                              hasattr(signal, 'entry_range_max') and signal.entry_range_max)
            if has_range_check:
                logger.info(f"📊 Entry Range: {signal.entry_range_max} - {signal.entry_range_min}")
            elif signal.entry_price:
                logger.info(f"📊 Entry Price: {signal.entry_price}")
            else:
                logger.info("📊 Entry: Market")
            
            logger.info(f"✅ Stop Loss VERIFIED: {signal.stop_loss}")
            
            # Resolve symbol once
            resolved_symbol = await self.resolve_symbol(signal.symbol)
            
            # Distribute lot size across TP levels using integer-unit arithmetic.
            # Simple equal-split rounding (e.g. 0.04 / 3 = 0.0133) collapses every
            # slice to the minimum lot; instead we distribute whole step-units and
            # assign any remainder to the first orders.
            _spec = await self.get_symbol_specification(signal.symbol)
            _step = self.volume_step_overrides.get(resolved_symbol, _spec.get('volumeStep', 0.01))
            _vmin = _spec.get('volumeMin', 0.01)
            _total_units = round(risk_assessment.calculated_lot_size / _step)
            _base = _total_units // num_orders
            _rem = _total_units % num_orders
            # Assign extra units to the LAST orders — those correspond to the best
            # entry prices (lowest for BUY, highest for SELL).
            lot_sizes = [
                max(_vmin, round((_base + (1 if i >= num_orders - _rem else 0)) * _step, 2))
                for i in range(num_orders)
            ]
            logger.info(f"   Lot distribution across {num_orders} order(s): {lot_sizes} (total={sum(lot_sizes):.2f})")
            
            # Get current price
            current_price_data = await self._stream_price(resolved_symbol) or await self.connection.get_symbol_price(resolved_symbol)
            is_buy = self._is_buy_signal(signal)
            current_price = current_price_data['ask'] if is_buy else current_price_data['bid']
            
            # SMART RANGE-BASED DISTRIBUTION
            # Multi-entry legs take precedence over range/single-entry distribution.
            has_range = (not leg_targets
                        and hasattr(signal, 'entry_range_min') and signal.entry_range_min and
                        hasattr(signal, 'entry_range_max') and signal.entry_range_max)

            # Calculate entry prices for each order
            entry_prices = []

            if leg_targets:
                # Each order's entry is its leg price: MARKET if live price is already
                # at/through the leg, else a pending LIMIT at that leg.
                for i, leg_price in enumerate(leg_targets):
                    if is_buy:
                        is_hit_or_better = current_price <= leg_price
                    else:
                        is_hit_or_better = current_price >= leg_price
                    if is_hit_or_better:
                        logger.success(f"   ✅ Leg {order_leg_idx[i]} ({leg_price}): current {current_price} hit/better → MARKET")
                        entry_prices.append(('MARKET', current_price))
                    else:
                        logger.info(f"   ⏳ Leg {order_leg_idx[i]} ({leg_price}): not reached → LIMIT")
                        entry_prices.append(('LIMIT', leg_price))
            elif has_range:
                range_min = signal.entry_range_min
                range_max = signal.entry_range_max
                logger.info(f"📊 RANGE DETECTED: {range_min} - {range_max}")
                
                # For BUY: range_max is start (higher), range_min is end (lower)
                # For SELL: range_min is start (lower), range_max is end (higher)
                if is_buy:
                    range_start = range_max
                    range_end = range_min
                else:
                    range_start = range_min
                    range_end = range_max
                
                # Calculate targeted distribution levels
                target_levels = []
                if num_tps == 1:
                    target_levels.append(range_start)
                else:
                    step = (range_end - range_start) / (num_tps - 1)
                    for i in range(num_tps):
                        target_levels.append(range_start + (step * i))
                
                # Evaluate each level against current price
                logger.info(f"📍 Evaluating {num_tps} entry levels for {signal.symbol} at current price {current_price}...")
                
                for i, target_price in enumerate(target_levels):
                    level_num = i + 1
                    # Determine if level is already hit or bettered by current price
                    if is_buy:
                        is_hit_or_better = current_price <= target_price
                    else:
                        is_hit_or_better = current_price >= target_price
                    
                    if is_hit_or_better:
                        logger.success(f"   ✅ Level {level_num} ({target_price:.5f}): Current {current_price:.5f} is hit or better → MARKET")
                        entry_prices.append(('MARKET', current_price))
                    else:
                        logger.info(f"   ⏳ Level {level_num} ({target_price:.5f}): Not reached yet → LIMIT")
                        entry_prices.append(('LIMIT', target_price))
                
                # Summary log
                market_count = sum(1 for t, _ in entry_prices if t == 'MARKET')
                limit_count = sum(1 for t, _ in entry_prices if t == 'LIMIT')
                logger.info(f"🎯 Distribution summary: {market_count} MARKET, {limit_count} LIMIT orders")

            
            elif signal.entry_price:
                # Single entry price specified - use old logic
                entry_price = signal.entry_price
                if is_buy:
                    if current_price <= entry_price:
                        logger.info("💰 FAVORABLE PRICE: Executing all as MARKET orders")
                        entry_prices = [('MARKET', current_price) for _ in range(num_tps)]
                    else:
                        logger.info(f"⏳ All orders as LIMIT at {entry_price}")
                        entry_prices = [('LIMIT', entry_price) for _ in range(num_tps)]
                else:
                    if current_price >= entry_price:
                        logger.info("💰 FAVORABLE PRICE: Executing all as MARKET orders")
                        entry_prices = [('MARKET', current_price) for _ in range(num_tps)]
                    else:
                        logger.info(f"⏳ All orders as LIMIT at {entry_price}")
                        entry_prices = [('LIMIT', entry_price) for _ in range(num_tps)]
            else:
                # No entry price - all market orders
                logger.info("📊 No entry specified: All MARKET orders")
                entry_prices = [('MARKET', current_price) for _ in range(num_tps)]

            # An explicit STOP order is a breakout entry: it waits at its level. Without this a
            # BUY STOP above the market was filled at once as a 'better price' — far from its
            # level and right on top of its SL (simulated 2026-11-12).
            if (signal.signal_type in (SignalType.BUY_STOP, SignalType.SELL_STOP) and signal.entry_price
                    and not leg_targets and not has_range):
                logger.info(f"📌 STOP order: {num_tps} pending {signal.signal_type.value} order(s) at {signal.entry_price}")
                entry_prices = [('STOP', signal.entry_price) for _ in range(num_tps)]
            
            # Execute orders with calculated entry prices
            results = []
            position_ids = []
            order_ids = []
            
            for i, (tp_level, (order_type, entry_price)) in enumerate(zip(tp_levels, entry_prices), 1):
                lot_here = lot_sizes[i - 1]
                leg_no = order_leg_idx[i - 1]
                tp_no = order_tp_idx[i - 1]
                logger.info(f"📤 Executing order {i}/{num_orders} (leg {leg_no}, TP{tp_no}): Type={order_type}, Entry={entry_price:.2f}, Target={tp_level}, Lot={lot_here}")

                try:
                    # Prepare options for this TP level
                    tp_options = {"comment": self._generate_random_comment()}

                    # Add magic number for MT4/MT5 tracking
                    if base_magic_number:
                        tp_options['magic'] = base_magic_number
                        logger.info(f"   Magic Number for TP{i}: {base_magic_number} (shared)")

                    # Execute based on order type
                    if order_type == 'MARKET':
                        # Execute as market order
                        if is_buy:
                            result = await self.connection.create_market_buy_order(
                                resolved_symbol,
                                lot_here,
                                signal.stop_loss,
                                tp_level,
                                tp_options
                            )
                        else:
                            result = await self.connection.create_market_sell_order(
                                resolved_symbol,
                                lot_here,
                                signal.stop_loss,
                                tp_level,
                                tp_options
                            )
                    elif order_type == 'STOP':
                        place = self.connection.create_stop_buy_order if is_buy else self.connection.create_stop_sell_order
                        result = await place(resolved_symbol, lot_here, entry_price, signal.stop_loss, tp_level, tp_options)
                    else:  # LIMIT
                        # Place limit order
                        if is_buy:
                            result = await self.connection.create_limit_buy_order(
                                resolved_symbol,
                                lot_here,
                                entry_price,
                                signal.stop_loss,
                                tp_level,
                                tp_options
                            )
                        else:
                            result = await self.connection.create_limit_sell_order(
                                resolved_symbol,
                                lot_here,
                                entry_price,
                                signal.stop_loss,
                                tp_level,
                                tp_options
                            )
                    
                    # Tag each order with its leg/TP indices for per-leg trade recording.
                    if isinstance(result, dict):
                        result = {**result, "tpLevel": tp_no, "entryLeg": leg_no, "entryPrice": entry_price}
                    results.append(result)

                    if result.get('positionId'):
                        position_ids.append(result['positionId'])
                    if result.get('orderId'):
                        order_ids.append(result['orderId'])

                    logger.success(f"   ✅ Order {i} (leg {leg_no}, TP{tp_no}) executed: Position {result.get('positionId', 'N/A')}, Order {result.get('orderId', 'N/A')}")
                    
                except Exception as tp_error:
                    error_msg = str(tp_error)
                    logger.error(f"   ❌ TP{i} failed: {error_msg}")
                    
                    # Enhanced diagnostics for common errors
                    if 'Trade is disabled' in error_msg or 'TRADE_DISABLED' in error_msg:
                        logger.error(f"   🔧 DIAGNOSTIC: Trading may be disabled for {resolved_symbol}")
                        logger.error("   Possible causes:")
                        logger.error("   - Symbol trading disabled on broker/MT account")
                        logger.error("   - Market is closed for this symbol")
                        logger.error("   - Account trading permissions issue")
                        logger.error("   - Check MT terminal symbol properties")
                    elif 'Invalid stops' in error_msg or 'INVALID_STOPS' in error_msg:
                        logger.error("   🔧 DIAGNOSTIC: Stop levels too close to entry")
                        logger.error(f"   Entry: {entry_price}, SL: {signal.stop_loss}, TP: {tp_level}")
                    
                    # Log additional error details if available
                    if hasattr(tp_error, 'details'):
                        logger.error(f"   Error details: {tp_error.details}")
                    if hasattr(tp_error, '__dict__'):
                        logger.debug(f"   Full error object: {tp_error.__dict__}")
                    
                    results.append({"error": error_msg, "tpLevel": tp_no, "entryLeg": leg_no, "entryPrice": entry_price})

            # Check if at least one order succeeded
            success_count = sum(1 for r in results if 'positionId' in r or 'orderId' in r)

            # Convert datetime objects for JSON serialization (used by both paths)
            serializable_results = []
            for result in results:
                serializable_result = {}
                for key, value in result.items():
                    serializable_result[key] = value.isoformat() if isinstance(value, datetime) else value
                serializable_results.append(serializable_result)

            broker_response = {
                "multi_tp": True,
                "tp_count": num_tps,
                "order_count": num_orders,
                "multi_entry": bool(leg_targets),
                "success_count": success_count,
                "position_ids": position_ids,
                "order_ids": order_ids,
                "individual_results": serializable_results,
            }

            if success_count > 0:
                logger.success(f"✅ {'Multi-entry' if leg_targets else 'Multi-TP'} trade: {success_count}/{num_orders} orders executed")
                return TradeResult(
                    success=True,
                    position_id=position_ids[0] if position_ids else None,
                    order_id=order_ids[0] if order_ids else None,
                    entry_price=entry_price,
                    broker_response=broker_response,
                )
            else:
                logger.error(f"❌ Multi-order trade failed: 0/{num_orders} orders executed")
                # Include individual_results even when all fail so trading_service.py
                # can mark each per-leg/per-TP trade as FAILED.
                return TradeResult(
                    success=False,
                    error_message=f"All {num_orders} order(s) failed",
                    broker_response=broker_response,
                )
                
        except Exception as e:
            logger.error(f"❌ Multi-TP execution failed: {str(e)}")
            return TradeResult(
                success=False,
                error_message=f"Multi-TP error: {str(e)}"
            )
    
    async def get_account_info(self, use_cache: bool = True) -> AccountInfo:
        """
        Get current account information with caching to prevent rate limiting
        
        Args:
            use_cache: Whether to use cached data if available and fresh (default: True)
        """
        if not self.is_connected:
            raise Exception("MetaAPI not connected")

        # Live stream: equity/margin/positions are pushed, so no TTL cache or backoff
        if self._stream_ready():
            live = self.stream.terminal_state.account_information
            if live:
                positions = [dict(p) for p in self.stream.terminal_state.positions]
                return AccountInfo(
                    balance=live.get("balance", 0.0),
                    equity=live.get("equity", 0.0),
                    margin=live.get("margin", 0.0),
                    free_margin=live.get("freeMargin", 0.0),
                    open_positions=self._count_unique_signals(positions),
                    currency=live.get("currency", "USD"),
                    leverage=live.get("leverage"),
                )

        # Check if we're in rate limit backoff period
        if self._rate_limit_backoff_until:
            time_remaining = self._rate_limit_backoff_until - datetime.now().timestamp()
            if time_remaining > 0:
                if self._account_info_cache:
                    logger.debug(f"⏸️ Rate limit backoff active ({time_remaining:.0f}s remaining) - using cached data")
                    return self._account_info_cache
                else:
                    # Wait out the backoff period
                    logger.warning(f"⏸️ Rate limit backoff active, waiting {time_remaining:.0f}s...")
                    await asyncio.sleep(min(time_remaining, 5))  # Max 5s wait per call
            else:
                # Backoff period expired
                self._rate_limit_backoff_until = None
        
        # Check cache first if enabled
        if use_cache and self._account_info_cache and self._account_info_cache_time:
            cache_age = (datetime.now().timestamp() - self._account_info_cache_time)
            if cache_age < self._account_info_cache_ttl:
                logger.debug(f"✅ Using cached account info (age: {cache_age:.1f}s)")
                return self._account_info_cache
        
        # Fetch fresh data from MetaAPI (streamed state first - no API call)
        try:
            logger.debug("📊 Fetching account information from MetaAPI...")
            account_info = self.stream.terminal_state.account_information if self._stream_ready() else None
            if not account_info:
                account_info = await asyncio.wait_for(
                    self.connection.get_account_information(),
                    timeout=30.0  # 30 second timeout
                )
            logger.debug("✅ Account information retrieved")
        except asyncio.TimeoutError:
            if self._account_info_cache:
                logger.warning("⚠️ Timeout fetching account info - using cached data")
                return self._account_info_cache
            logger.error("❌ Timeout fetching account information (30s)")
            raise Exception("Timeout fetching account information from MetaAPI")
        except Exception as e:
            # Check for rate limit error
            if is_rate_limit_error(e):
                logger.warning("⏸️ Rate limit hit on getAccountInformation - activating backoff")
                # Set exponential backoff (start with 60s)
                backoff_duration = 60
                self._rate_limit_backoff_until = datetime.now().timestamp() + backoff_duration
                logger.info(f"⏳ Rate limit backoff: {backoff_duration}s")
                
                # Return cached data if available
                if self._account_info_cache:
                    logger.info("✅ Using cached account info during rate limit")
                    return self._account_info_cache
                else:
                    logger.error("❌ No cached data available during rate limit")
                    raise Exception("Rate limit exceeded and no cached data available")
            
            logger.error(f"❌ Error fetching account information: {str(e)}")
            # Try to return cached data for other errors too
            if self._account_info_cache:
                logger.warning("⚠️ Using cached data due to error")
                return self._account_info_cache
            raise
        
        # Fetch positions (use cached positions to reduce API calls)
        logger.debug("📊 Fetching positions for account info...")
        try:
            positions = await self.get_open_positions(use_cache=True)
            logger.debug(f"✅ Positions retrieved: {len(positions)} positions")
        except asyncio.TimeoutError:
            if self._account_info_cache:
                logger.warning("⚠️ Timeout fetching positions - using cached data")
                return self._account_info_cache
            logger.error("❌ Timeout fetching positions (30s)")
            raise Exception("Timeout fetching positions from MetaAPI")
        except Exception as e:
            logger.error(f"❌ Error fetching positions: {str(e)}")
            # Still return account info with last known position count
            if self._account_info_cache:
                logger.warning("⚠️ Using cached position count due to error")
                positions = []
            else:
                raise
        
        # Count unique signals/trades instead of raw positions
        # Multi-TP trades share the same magic number and count as 1 signal
        unique_signals = self._count_unique_signals(positions)
        
        logger.debug(f"📊 Position count: {len(positions)} raw positions = {unique_signals} unique signals/trades")
        
        # Create account info object
        account_info_obj = AccountInfo(
            balance=account_info.get("balance", 0.0),
            equity=account_info.get("equity", 0.0),
            margin=account_info.get("margin", 0.0),
            free_margin=account_info.get("freeMargin", 0.0),
            open_positions=unique_signals,  # Count unique signals, not raw positions
            currency=account_info.get("currency", "USD"),
            leverage=account_info.get("leverage")
        )
        
        # Update cache
        self._account_info_cache = account_info_obj
        self._account_info_cache_time = datetime.now().timestamp()
        logger.debug(f"💾 Account info cached (TTL: {self._account_info_cache_ttl}s)")
        
        return account_info_obj
    
    async def get_open_positions(self, use_cache: bool = True):
        """
        Get all open positions with caching and rate limit handling
        
        Args:
            use_cache: Whether to use cached data if available (default: True)
        """
        self.positions_ok = True
        if not self.is_connected:
            self.positions_ok = False  # read failed - callers must not infer closures from this
            return []

        # Live stream: always fresh, cache not needed
        if self._stream_ready():
            return [dict(p) for p in self.stream.terminal_state.positions]
        
        # Try cache first if enabled
        if use_cache:
            cached_positions = await position_cache.get_positions()
            if cached_positions is not None:
                return cached_positions
        
        # Fetch from MetaAPI with rate limit handling
        try:
            positions = await self._fetch_positions_with_retry()
            if positions is None:  # decorator skipped the call during a rate-limit backoff
                raise Exception("rate limit: positions fetch skipped")
            # Update cache
            await position_cache.set_positions(positions)
            return positions
        except Exception as e:
            if is_rate_limit_error(e):
                logger.warning("⏸️ Rate limit hit - using cached data if available")
                cached = await position_cache.get_positions()
                if cached is not None:
                    logger.info(f"📦 Using cached positions ({len(cached)} items)")
                    return cached
                logger.warning("⚠️ No cached positions available")
            elif is_timeout_error(e):
                logger.warning("⏱️ Timeout fetching positions from MetaAPI - using cached data if available")
                logger.debug(f"Timeout error: {str(e)}")
                cached = await position_cache.get_positions()
                if cached is not None:
                    logger.info(f"📦 Using cached positions ({len(cached)} items)")
                    return cached
                logger.warning("⚠️ No cached positions available - account may not be connected to broker")
            else:
                logger.error(f"❌ Failed to fetch positions: {str(e)}")
            self.positions_ok = False  # read failed - callers must not infer closures from this
            return []
    
    async def get_all_pending_orders(self, use_cache: bool = True):
        """
        Get all pending orders from MetaAPI with caching and rate limit handling
        
        Args:
            use_cache: Whether to use cached data if available (default: True)
            
        Returns:
            List of all pending orders
        """
        self.orders_ok = True
        if not self.is_connected:
            self.orders_ok = False  # read failed - callers must not infer closures from this
            return []

        # Live stream: always fresh, cache not needed
        if self._stream_ready():
            return [dict(o) for o in self.stream.terminal_state.orders]
        
        # Try cache first if enabled
        if use_cache:
            cached_orders = await position_cache.get_all_orders()
            if cached_orders is not None:
                return cached_orders
        
        # Fetch from MetaAPI with rate limit handling
        try:
            orders = await self._fetch_orders_with_retry()
            if orders is None:  # decorator skipped the call during a rate-limit backoff
                raise Exception("rate limit: orders fetch skipped")
            # Update cache
            await position_cache.set_all_orders(orders)
            logger.debug(f"📋 Fetched {len(orders)} pending order(s)")
            return orders
            
        except Exception as e:
            if is_rate_limit_error(e):
                logger.warning("⏸️ Rate limit hit fetching orders - using cached data if available")
                cached = await position_cache.get_all_orders()
                if cached is not None:
                    logger.info(f"📦 Using cached orders ({len(cached)} items)")
                    return cached
                logger.warning("⚠️ No cached orders available")
            elif is_timeout_error(e):
                logger.warning("⏱️ Timeout fetching orders from MetaAPI - using cached data if available")
                logger.debug(f"Timeout error: {str(e)}")
                cached = await position_cache.get_all_orders()
                if cached is not None:
                    logger.info(f"📦 Using cached orders ({len(cached)} items)")
                    return cached
                logger.warning("⚠️ No cached orders available - account may not be connected to broker")
            else:
                logger.error(f"❌ Failed to fetch pending orders: {str(e)}")
            self.orders_ok = False  # read failed - callers must not infer closures from this
            return []
    
    @with_rate_limit_handling(max_retries=2, skip_on_rate_limit=True)
    async def _fetch_positions_with_retry(self):
        """Internal method to fetch positions with retry logic"""
        if self._stream_ready():
            return [dict(p) for p in self.stream.terminal_state.positions]
        return await self.connection.get_positions()
    
    @with_rate_limit_handling(max_retries=2, skip_on_rate_limit=True)
    async def _fetch_orders_with_retry(self):
        """Internal method to fetch orders with retry logic"""
        if self._stream_ready():
            return [dict(o) for o in self.stream.terminal_state.orders]
        return await self.connection.get_orders()
    
    async def close_position(self, position_id: str, volume: Optional[float] = None):
        """Close a position (full or partial)"""
        if not self.is_connected:
            raise Exception("MetaAPI not connected")
        
        try:
            if volume:
                # Partial close using MetaAPI's dedicated method
                logger.info(f"🔒 Partially closing position {position_id}: {volume} lots")
                logger.debug(f"   Calling close_position_partially(position_id={position_id}, volume={volume})")
                
                result = await self.connection.close_position_partially(
                    position_id=position_id,
                    volume=volume
                )
                
                # Invalidate cache after position change
                await position_cache.invalidate_positions()
                
                logger.success(f"✅ Partially closed position {position_id}: {volume} lots")
                return result
            else:
                # Full close
                logger.info(f"🔒 Closing position {position_id} (full close)")
                result = await self.connection.close_position(position_id)
                
                # Invalidate cache after position change
                await position_cache.invalidate_positions()
                
                logger.success(f"✅ Position {position_id} closed")
                return result
            
        except Exception as e:
            logger.error(f"❌ Failed to close position: {str(e)}")
            
            # Log additional error details if available
            if hasattr(e, 'details'):
                logger.error(f"   Error details: {e.details}")
            if hasattr(e, '__dict__'):
                logger.debug(f"   Full error object: {e.__dict__}")
            
            raise
    
    async def cancel_order(self, order_id: str):
        """Cancel a pending order"""
        if not self.is_connected:
            raise Exception("MetaAPI not connected")
        
        try:
            logger.info(f"❌ Cancelling pending order {order_id}")
            result = await self.connection.cancel_order(order_id)
            
            # Invalidate orders cache after cancellation
            await position_cache.invalidate_orders()
            
            logger.success(f"✅ Order {order_id} cancelled")
            return result
            
        except Exception as e:
            logger.error(f"❌ Failed to cancel order: {str(e)}")
            
            # Log additional error details if available
            if hasattr(e, 'details'):
                logger.error(f"   Error details: {e.details}")
            if hasattr(e, '__dict__'):
                logger.debug(f"   Full error object: {e.__dict__}")
            
            raise
    
    def _validate_stops(
        self,
        symbol: str,
        current_price: float,
        is_buy: bool,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None
    ) -> tuple[bool, Optional[str]]:
        """
        Validate stop loss and take profit values before modifying position.
        
        Returns:
            (is_valid, error_message) tuple
        """
        # Get pip value for the symbol
        if 'XAU' in symbol.upper() or 'GOLD' in symbol.upper():
            pip_value = 0.1
        elif 'BTC' in symbol.upper() or 'ETH' in symbol.upper():
            pip_value = 1.0
        elif 'JPY' in symbol.upper():
            pip_value = 0.01
        else:
            pip_value = 0.0001
        
        # Minimum distance: 10 pips from current price
        min_distance = 10 * pip_value
        
        # Validate stop loss
        if stop_loss is not None:
            if is_buy:
                # For buy positions, SL must be below current price
                if stop_loss >= current_price:
                    return False, f"Stop loss ({stop_loss}) must be below current price ({current_price}) for BUY"
                if (current_price - stop_loss) < min_distance:
                    return False, f"Stop loss too close to current price (min {min_distance}, got {current_price - stop_loss})"
            else:
                # For sell positions, SL must be above current price
                if stop_loss <= current_price:
                    return False, f"Stop loss ({stop_loss}) must be above current price ({current_price}) for SELL"
                if (stop_loss - current_price) < min_distance:
                    return False, f"Stop loss too close to current price (min {min_distance}, got {stop_loss - current_price})"
        
        # Validate take profit
        if take_profit is not None:
            if is_buy:
                # For buy positions, TP must be above current price
                if take_profit <= current_price:
                    return False, f"Take profit ({take_profit}) must be above current price ({current_price}) for BUY"
                if (take_profit - current_price) < min_distance:
                    return False, f"Take profit too close to current price (min {min_distance}, got {take_profit - current_price})"
            else:
                # For sell positions, TP must be below current price
                if take_profit >= current_price:
                    return False, f"Take profit ({take_profit}) must be below current price ({current_price}) for SELL"
                if (current_price - take_profit) < min_distance:
                    return False, f"Take profit too close to current price (min {min_distance}, got {current_price - take_profit})"
        
        return True, None
    
    async def modify_position(
        self,
        position_id: str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None
    ):
        """Modify position stop loss or take profit"""
        if not self.is_connected:
            raise Exception("MetaAPI not connected")
        
        try:
            # Get position details for validation (try cached first)
            positions = await self.get_open_positions(use_cache=True)
            position = next((p for p in positions if p.get('id') == position_id), None)
            
            # If not found in cache, invalidate and retry with fresh data
            if not position:
                logger.debug(f"🔄 Position {position_id[:8]}... not in cache, fetching fresh data")
                await position_cache.invalidate_positions()
                positions = await self.get_open_positions(use_cache=False)
                position = next((p for p in positions if p.get('id') == position_id), None)
            
            if not position:
                # Position truly doesn't exist (likely closed)
                logger.warning(f"⚠️ Position {position_id} not found (already closed)")
                raise Exception(f"Position {position_id} not found")
            
            # Extract position details
            symbol = position.get('symbol')
            current_price = position.get('currentPrice')
            is_buy = position.get('type') == 'POSITION_TYPE_BUY'
            
            # Validate stops if we have current price
            if current_price:
                is_valid, error_msg = self._validate_stops(
                    symbol, current_price, is_buy, stop_loss, take_profit
                )
                
                if not is_valid:
                    logger.warning(f"⚠️ Invalid stops for {position_id}: {error_msg}")
                    raise ValueError(f"Invalid stops: {error_msg}")
            
            stop_loss = await self._normalize_price(symbol, stop_loss)
            take_profit = await self._normalize_price(symbol, take_profit)
            logger.info(f"✏️ Modifying position {position_id}")
            logger.debug(f"   New SL: {stop_loss}, New TP: {take_profit}")
            
            # MetaAPI modify_position expects: (position_id, stop_loss, take_profit)
            result = await self.connection.modify_position(
                position_id,
                stop_loss,
                take_profit
            )
            
            # Invalidate cache after position modification
            await position_cache.invalidate_positions()
            
            logger.success(f"✅ Position {position_id} modified")
            return result
            
        except ValueError:
            # Re-raise validation errors without additional logging
            raise
        except Exception as e:
            error_msg = str(e)
            # Check if position was already closed
            if 'not found' in error_msg.lower() or 'ERR_TRADE_POSITION_NOT_FOUND' in error_msg:
                logger.warning(f"⚠️ Position {position_id} already closed during modification attempt")
            else:
                logger.error(f"❌ Failed to modify position: {error_msg}")
            raise
    
    async def remove_take_profit(self, ticket: str, stop_loss: Optional[float],
                                 pending: bool = False, price: Optional[float] = None):
        """MetaAPI replaces both stops on a modify: a TP that is not sent is removed."""
        if pending:
            return await self.modify_order(ticket, stop_loss=stop_loss, take_profit=None, price=price)
        return await self.modify_position(ticket, stop_loss=stop_loss, take_profit=None)

    def _is_buy_signal(self, signal_or_type) -> bool:
        """Check if signal is a buy signal - supports both SignalType enum and TradingSignal object"""
        from src.models import OrderType
        
        # If it's a TradingSignal object, check order_type first, then signal_type
        if hasattr(signal_or_type, 'order_type') and signal_or_type.order_type:
            return signal_or_type.order_type == OrderType.BUY
        elif hasattr(signal_or_type, 'signal_type') and signal_or_type.signal_type:
            return signal_or_type.signal_type in [SignalType.BUY, SignalType.BUY_LIMIT, SignalType.BUY_STOP]
        # If it's just a SignalType enum value
        elif isinstance(signal_or_type, SignalType):
            return signal_or_type in [SignalType.BUY, SignalType.BUY_LIMIT, SignalType.BUY_STOP]
        else:
            logger.error(f"🚨 Could not determine signal direction from {signal_or_type}")
            return False
    
    def _get_order_type(self, signal_type: SignalType) -> str:
        """Get MetaAPI order type from signal type"""
        mapping = {
            SignalType.BUY: "ORDER_TYPE_BUY",
            SignalType.SELL: "ORDER_TYPE_SELL",
            SignalType.BUY_LIMIT: "ORDER_TYPE_BUY_LIMIT",
            SignalType.SELL_LIMIT: "ORDER_TYPE_SELL_LIMIT",
            SignalType.BUY_STOP: "ORDER_TYPE_BUY_STOP",
            SignalType.SELL_STOP: "ORDER_TYPE_SELL_STOP",
        }
        return mapping.get(signal_type, "ORDER_TYPE_BUY")
    
    async def get_positions_by_magic(self, magic_number: int, use_cache: bool = True) -> list:
        """
        Get all open positions with a specific magic number (clientId)
        
        Args:
            magic_number: The magic number to search for
            use_cache: Whether to use cached positions (default: True)
            
        Returns:
            List of positions matching the magic number
        """
        if not self.is_connected:
            logger.warning("MetaAPI not connected")
            return []
        
        try:
            # Get all positions (uses cache internally)
            all_positions = await self.get_open_positions(use_cache=use_cache)
            
            # Filter by magic number (clientId)
            matching_positions = [
                pos for pos in all_positions
                if pos.get('clientId') == str(magic_number) or pos.get('magic') == magic_number
            ]
            
            logger.debug(f"🔍 Found {len(matching_positions)} position(s) with magic number {magic_number}")
            return matching_positions
            
        except Exception as e:
            if is_rate_limit_error(e):
                logger.warning(f"⏸️ Rate limit hit fetching positions for magic {magic_number}")
                return []
            logger.error(f"❌ Failed to fetch positions by magic: {str(e)}")
            return []
    
    @with_rate_limit_handling(max_retries=2, skip_on_rate_limit=True)
    async def get_orders_by_magic(self, magic_number: int) -> list:
        """
        Get all pending orders with a specific magic number (clientId)
        
        Args:
            magic_number: The magic number to search for
            
        Returns:
            List of orders matching the magic number
        """
        if not self.is_connected:
            logger.warning("MetaAPI not connected")
            return []
        
        try:
            # Get all orders
            all_orders = await self._fetch_orders_with_retry() or []
            
            # Filter by magic number
            # Note: Can't use clientId since we removed it from orders
            # Instead we rely on database magic_number field to track orders
            matching_orders = [
                order for order in all_orders
                if order.get('magic') == magic_number
            ]
            
            logger.debug(f"🔍 Found {len(matching_orders)} order(s) with magic number {magic_number}")
            return matching_orders
            
        except Exception as e:
            if is_rate_limit_error(e):
                logger.warning(f"⏸️ Rate limit hit fetching orders for magic {magic_number}")
                return []
            logger.error(f"❌ Failed to fetch orders by magic: {str(e)}")
            return []
    
    async def get_all_trades_by_magic(self, magic_number: int, use_cache: bool = True) -> dict:
        """
        Get all positions and orders with a specific magic number
        
        Args:
            magic_number: The magic number to search for
            use_cache: Whether to use cached data if available
            
        Returns:
            Dictionary with 'positions' and 'orders' lists
        """
        # Try cache first for orders
        orders = None
        if use_cache:
            orders = await position_cache.get_orders(magic_number)
        
        # Fetch orders if not cached
        if orders is None:
            try:
                orders = await self.get_orders_by_magic(magic_number)
                await position_cache.set_orders(magic_number, orders)
            except Exception as e:
                if is_rate_limit_error(e):
                    logger.warning(f"⏸️ Rate limit hit fetching orders for magic {magic_number}")
                    orders = await position_cache.get_orders(magic_number) or []
                else:
                    raise
        
        # Get positions (uses position cache internally)
        positions = await self.get_positions_by_magic(magic_number, use_cache=use_cache)
        
        return {
            "positions": positions,
            "orders": orders,
            "total_count": len(positions) + len(orders)
        }
    
    @with_rate_limit_handling(max_retries=2, skip_on_rate_limit=True)
    async def get_deals_by_position(
        self,
        position_id: str,
        symbol: Optional[str] = None,
        from_date: Optional[str] = None,
    ) -> list:
        """
        Get closed deals for a position via the MetaStats SDK (accurate net profit).

        Args:
            position_id: The MetaTrader position ID
            symbol: Optional symbol filter (guards against position-ID reuse)
            from_date: ISO date string start of search window (default: 30 days ago)

        Returns:
            List of deal dicts (positionId, profit, commission, swap, volume, price,
            time, entryType, type, symbol, openPrice, closePrice, pips)
        """
        if not self.is_connected:
            logger.warning("MetaAPI not connected")
            return []
        try:
            return await self._get_deals_from_metastats(position_id, symbol, from_date)
        except Exception as e:
            if is_rate_limit_error(e):
                logger.warning(f"⏸️ Rate limit hit fetching deal history for position {str(position_id)[:8]}...")
            else:
                logger.error(f"❌ Failed to fetch deal history: {str(e)}")
            return []

    def _get_metastats(self):
        """Lazily create the MetaStats SDK client (region is auto-resolved by the SDK)."""
        if self.metastats is None:
            self.metastats = MetaStats(settings.metaapi_token)
        return self.metastats

    async def _get_account_trades(self, start_time: datetime, end_time: datetime, ttl: float = 30.0, force: bool = False) -> list:
        """
        MetaStats closed trades for a window. update_history=True makes each call a
        billable MetaStats request, so results are cached briefly (window is
        truncated to the minute so repeated lookups share one entry).
        """
        import time as _t
        fmt = '%Y-%m-%d %H:%M:00.000'
        start = start_time.astimezone(timezone.utc).strftime(fmt)
        end = end_time.astimezone(timezone.utc).strftime(fmt)
        key = (start[:10],)  # same-day windows share an entry; start day is what matters
        cached = self._trades_cache.get(key)
        if cached and not force and _t.time() - cached[0] < ttl:
            return cached[1]
        trades = await self._get_metastats().get_account_trades(self.account.id, start, end)
        self._trades_cache[key] = (_t.time(), trades or [])
        if len(self._trades_cache) > 8:
            self._trades_cache.pop(next(iter(self._trades_cache)))
        return trades or []

    async def _get_deals_from_metastats(
        self,
        position_id: str,
        symbol: Optional[str] = None,
        from_date: Optional[str] = None,
    ) -> list:
        """Fetch closed trades for a position using the MetaStats SDK."""
        from datetime import timedelta

        end_time = datetime.now(timezone.utc) + timedelta(minutes=1)
        start_time = end_time - timedelta(days=30)
        if from_date:
            try:
                parsed = datetime.fromisoformat(str(from_date).replace('Z', '+00:00'))
                start_time = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                logger.debug(f"Invalid from_date '{from_date}', using 30-day window")

        try:
            trades = await self._get_account_trades(start_time, end_time)
        except Exception as e:
            if is_rate_limit_error(e):
                raise
            logger.debug(f"⚠️  MetaStats SDK error: {str(e)}")
            return []

        pid = str(position_id)
        deals = self._match_trades(trades, pid, symbol)
        entry = self._trades_cache.get((start_time.astimezone(timezone.utc).strftime('%Y-%m-%d'),))
        if not deals and entry and time.time() - entry[0] > 2:
            # Cached list may predate this position's closure - refresh once
            try:
                trades = await self._get_account_trades(start_time, end_time, force=True)
            except Exception as e:
                if is_rate_limit_error(e):
                    raise
                return []
            deals = self._match_trades(trades, pid, symbol)
        if deals:
            logger.debug(f"📊 MetaStats: Found {len(deals)} deal(s) for position {pid[:8]}...")
        return deals

    @staticmethod
    def _match_trades(trades: list, pid: str, symbol: Optional[str]) -> list:
        deals = []
        for t in trades or []:
            t_pid = str(t.get('positionId') or '')
            t_id = str(t.get('_id') or '')
            if t_pid != pid and not t_id.endswith(f":{pid}"):
                continue
            if symbol and t.get('symbol') and not str(t['symbol']).upper().startswith(symbol.upper()[:6]):
                continue
            deals.append({
                'positionId': t_pid or pid,
                'profit': t.get('profit', 0),
                'commission': t.get('commission', 0),
                'swap': t.get('swap', 0),
                'volume': t.get('volume', 0),
                'price': t.get('closePrice', 0),
                'time': t.get('closeTime'),
                'entryType': 'DEAL_ENTRY_OUT',  # MetaStats only returns closed trades
                'type': t.get('type'),
                'symbol': t.get('symbol'),
                'openPrice': t.get('openPrice'),
                'closePrice': t.get('closePrice'),
                'pips': t.get('pips'),
            })
        return deals

    async def get_closed_trades_by_magic(self, magic_number: int, days_back: int = 30) -> list:
        """
        Closed trades for a magic number (detects trades that opened + closed while the
        bot was offline). MetaStats trades carry no magic, so the magic is matched via
        the position's history orders over RPC (one call per candidate position).
        """
        from datetime import timedelta
        if not self.is_connected:
            return []
        try:
            end = datetime.now(timezone.utc) + timedelta(minutes=1)
            trades = await self._get_account_trades(end - timedelta(days=days_back), end, ttl=60.0)
            # Candidates: only positions not currently open
            # Fresh read: a position that opened seconds ago is not in the cache yet and
            # would otherwise be reported as closed
            open_ids = {str(p.get('id')) for p in await self.get_open_positions(use_cache=False) or []}
            result = []
            rpc_budget = 20  # cap history lookups per call to protect the API quota
            for t in sorted(trades, key=lambda x: str(x.get('closeTime') or ''), reverse=True):
                pid = str(t.get('positionId') or '')
                if not pid or pid in open_ids or not t.get('closeTime'):
                    continue
                if str(t.get('comment') or '').find(str(magic_number)) < 0:
                    if rpc_budget <= 0:
                        break
                    rpc_budget -= 1
                    try:
                        orders = await self.connection.get_history_orders_by_position(pid)
                        rows = orders.get('historyOrders', []) if isinstance(orders, dict) else []
                        if not any(o.get('magic') == magic_number for o in rows):
                            continue
                    except Exception as e:
                        if is_rate_limit_error(e):
                            break
                        continue
                profit = t.get('profit', 0) or 0
                result.append({
                    'position_id': pid,
                    'positionId': pid,
                    'symbol': t.get('symbol'),
                    'profit': profit,
                    'total_profit': profit,
                    'open_price': t.get('openPrice'),
                    'close_price': t.get('closePrice'),
                    'close_time': t.get('closeTime'),
                    'status': 'CLOSED_PROFIT' if profit > 0 else ('CLOSED_LOSS' if profit < 0 else 'CLOSED_BREAKEVEN'),
                    'is_open': False,
                })
            return result
        except Exception as e:
            logger.debug(f"get_closed_trades_by_magic failed for magic {magic_number}: {e}")
            return []

    async def _normalize_price(self, symbol: str, price: Optional[float]) -> Optional[float]:
        """Round a price to the symbol's broker digits; unchanged if the spec is unavailable."""
        if price is None:
            return None
        try:
            spec = await self.get_symbol_specification(symbol)
            digits = spec.get('digits')
            return round(float(price), int(digits)) if digits is not None else price
        except Exception:
            return price

    async def modify_order(
        self,
        order_id: str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        price: Optional[float] = None,
    ):
        """Modify a pending order's SL/TP and optionally its price."""
        if settings.dry_run:
            logger.warning(f"🧪 DRY RUN — not sent: modify order {order_id} SL {stop_loss} TP {take_profit} price {price}")
            return {"success": True, "dry_run": True}
        if not self.is_connected:
            raise Exception("MetaAPI not connected")
        try:
            if price is None:
                orders = await self.get_all_pending_orders(use_cache=False)
                order = next((o for o in orders if str(o.get('id')) == str(order_id)), None)
                if not order:
                    raise Exception(f"Pending order {order_id} not found")
                price = order.get('openPrice')
                if stop_loss is None:
                    stop_loss = order.get('stopLoss')
                if take_profit is None:
                    take_profit = order.get('takeProfit')
            result = await asyncio.wait_for(
                self.connection.modify_order(order_id, price, stop_loss, take_profit),
                timeout=30.0,
            )
            await position_cache.invalidate_orders()
            logger.success(f"✅ Pending order {order_id} modified")
            return result
        except asyncio.TimeoutError:
            raise Exception(f"Timeout modifying order {order_id}")
        except Exception as e:
            if is_rate_limit_error(e):
                raise Exception(f"Rate limit modifying order {order_id}")
            logger.error(f"❌ Failed to modify order {order_id}: {e}")
            raise

    async def fetch_mirror_snapshot(self) -> dict:
        """
        Strict, uncached snapshot for the EA mirror: raises unless it can vouch for the
        result (an empty list is only trusted if account margin/profit agree).
        """
        if not self.is_connected:
            raise Exception("MetaAPI not connected")
        if self._stream_ready():
            ts = self.stream.terminal_state
            positions = [dict(p) for p in ts.positions]
            orders = [dict(o) for o in ts.orders]
            account = ts.account_information
        else:
            positions = await asyncio.wait_for(self.connection.get_positions(), timeout=15.0)
            orders = await asyncio.wait_for(self.connection.get_orders(), timeout=15.0)
            account = await asyncio.wait_for(self.connection.get_account_information(), timeout=10.0)
        if not isinstance(positions, list) or not isinstance(orders, list):
            raise Exception("MetaAPI returned a malformed positions/orders payload")
        if not account or not account.get("login"):
            raise Exception("MetaAPI returned no account login")
        if not positions:
            margin = abs(float(account.get("margin") or 0.0))
            floating = abs(float(account.get("equity", 0.0) or 0.0) - float(account.get("balance", 0.0) or 0.0))
            if margin > 0.0 or floating > 0.005:
                raise Exception(f"Inconsistent snapshot: 0 positions but margin={margin} floating={floating}")
        return {"account": account, "positions": positions, "orders": orders}

    async def get_symbols_snapshot(self, select_unquoted: bool = True) -> list:
        """All broker symbols with streamed quotes (empty when streaming is off)."""
        if not self._stream_ready():
            return []
        rows = []
        ts = self.stream.terminal_state
        for spec in ts.specifications:
            name = spec.get('symbol')
            px = ts.price(name) or {}
            if not px and not select_unquoted:
                continue
            rows.append({
                'name': name, 'bid': px.get('bid'), 'ask': px.get('ask'),
                'digits': spec.get('digits'), 'description': spec.get('description'),
            })
        return rows

    async def get_symbol_specification(self, symbol: str) -> dict:
        """
        Get symbol specification from broker
        Returns dict with: tickSize, contractSize, digits, etc.
        Results are cached to minimize API calls.
        """
        # Check cache first
        if symbol in self.symbol_specs_cache:
            return self.symbol_specs_cache[symbol]
        
        if not self.is_connected:
            raise Exception("MetaAPI not connected")
        
        try:
            # Resolve symbol to broker format first
            resolved_symbol = await self.resolve_symbol(symbol)
            
            logger.debug(f"📋 Fetching symbol specification for {resolved_symbol}")
            
            # Get specification from broker
            spec = None
            if self._stream_ready():
                spec = self.stream.terminal_state.specification(resolved_symbol)
            if not spec:
                spec = await self.connection.get_symbol_specification(resolved_symbol)
            
            # Cache the result
            self.symbol_specs_cache[symbol] = spec
            self.symbol_specs_cache[resolved_symbol] = spec  # Cache both original and resolved
            
            logger.debug(f"✅ Symbol spec cached for {resolved_symbol}:")
            logger.debug(f"   tickSize={spec.get('tickSize')}, contractSize={spec.get('contractSize')}")
            logger.debug(f"   volumeStep={spec.get('volumeStep')}, volumeMin={spec.get('volumeMin')}, volumeMax={spec.get('volumeMax')}")
            
            return spec
            
        except Exception as e:
            logger.warning(f"⚠️ Could not fetch symbol specification for {symbol}: {str(e)}")
            # Return minimal fallback specification
            return {
                'symbol': symbol,
                'tickSize': 0.00001,  # Default for forex
                'contractSize': 100000,  # Standard lot
                'digits': 5
            }

    async def get_historical_candles(
        self,
        symbol: str,
        timeframe: str = '1h',
        start_time: Optional[datetime] = None,
        limit: int = 100
    ) -> Optional[List[dict]]:
        """
        Fetch historical OHLC candle data from MetaAPI.

        Args:
            symbol: Trading symbol (will be resolved internally)
            timeframe: Timeframe for candles (e.g., '1h', '15m', '1d')
            start_time: Start time for historical data (defaults to 100 hours ago)
            limit: Maximum number of candles to fetch

        Returns:
            List of candle dicts with keys: time, open, high, low, close, volume
            Returns None if data is unavailable
        """
        if not self.is_connected:
            logger.warning("MetaAPI not connected, cannot fetch candles")
            return None

        try:
            # Resolve symbol to broker-specific format
            resolved_symbol = await self.resolve_symbol(symbol)
            logger.debug(f"Fetching candles for resolved symbol: {resolved_symbol}")
            
            # Try to get from cache first
            from src.services.candle_cache_service import get_candle_cache_service
            cache_service = await get_candle_cache_service()
            
            cached_candles = await cache_service.get_cached_candles(
                resolved_symbol, timeframe, limit
            )
            if cached_candles:
                return cached_candles
            
            # Calculate start time if not provided
            if start_time is None:
                start_time = datetime.now(timezone.utc) - timedelta(hours=100)
            
            # Map timeframe string to MetaAPI timeframe
            timeframe_map = {
                '1m': '1m',
                '5m': '5m',
                '15m': '15m',
                '30m': '30m',
                '1h': '1h',
                '4h': '4h',
                '1d': '1d',
                '1w': '1w',
                '1M': '1Mn',
            }
            metaapi_timeframe = timeframe_map.get(timeframe, '1h')
            
            # Fetch candles from MetaAPI
            candles = await self.account.get_historical_candles(
                symbol=resolved_symbol,
                timeframe=metaapi_timeframe,
                start_time=start_time,
                limit=limit
            )
            
            if not candles:
                logger.warning(f"No candle data received for {resolved_symbol}")
                return None
            
            logger.debug(f"Retrieved {len(candles)} candles for {resolved_symbol}")
            
            # Normalize candle format to ensure consistent structure
            normalized_candles = []
            for candle in candles:
                normalized_candles.append({
                    "time": candle.get("time"),
                    "open": float(candle.get("open", 0)),
                    "high": float(candle.get("high", 0)),
                    "low": float(candle.get("low", 0)),
                    "close": float(candle.get("close", 0)),
                    "volume": int(candle.get("tick_volume", candle.get("volume", 0)))
                })
            
            # Cache the normalized candles
            await cache_service.cache_candles(
                resolved_symbol, timeframe, limit, normalized_candles
            )
            
            return normalized_candles
            
        except Exception as e:
            logger.error(f"Error fetching candles from MetaAPI: {e}")
            return None
    
    async def round_lot_size(self, symbol: str, lot_size: float) -> float:
        """
        Round lot size to broker's required volume step
        
        Args:
            symbol: Trading symbol
            lot_size: Desired lot size
            
        Returns:
            Properly rounded lot size that meets broker requirements
        """
        try:
            spec = await self.get_symbol_specification(symbol)
            volume_min = spec.get('volumeMin', 0.01)
            volume_max = spec.get('volumeMax', 100.0)
            
            # Check for symbol-specific override first (these take priority over broker values)
            resolved_symbol = await self.resolve_symbol(symbol)
            if resolved_symbol in self.volume_step_overrides:
                volume_step = self.volume_step_overrides[resolved_symbol]
                logger.debug(f"📊 Using override volumeStep={volume_step} for {resolved_symbol} (broker reported {spec.get('volumeStep')})")
            else:
                # Use broker-provided value or default
                volume_step = spec.get('volumeStep', 0.01)
                if spec.get('volumeStep') is None:
                    logger.debug(f"📊 Using default volumeStep={volume_step} for {resolved_symbol}")
            
            # Determine decimal places based on volume step
            if volume_step >= 1.0:
                decimal_places = 0
            elif volume_step >= 0.1:
                decimal_places = 1
            elif volume_step >= 0.01:
                decimal_places = 2
            else:
                decimal_places = 3
            
            # Round to nearest volume step
            rounded = round(lot_size / volume_step) * volume_step
            
            # Ensure within min/max bounds
            rounded = max(volume_min, min(rounded, volume_max))
            
            # Round to appropriate decimal places to avoid floating point errors
            rounded = round(rounded, decimal_places)
            
            if rounded != lot_size:
                logger.debug(f"📊 Lot size adjusted: {lot_size} → {rounded} (step={volume_step}, min={volume_min})")
            
            return rounded
            
        except Exception as e:
            logger.warning(f"⚠️ Could not validate lot size for {symbol}: {e}")
            # Fallback to basic rounding
            return round(lot_size, 2)
    
    def _count_unique_signals(self, positions: list) -> int:
        """
        Count unique signals/trades from positions.
        Multi-TP trades share the same magic number and count as 1 signal.
        Positions without magic number each count as 1 trade.
        
        Args:
            positions: List of MetaAPI position objects
            
        Returns:
            Number of unique signals/trades
        """
        if not positions:
            return 0
        
        unique_magics = set()
        positions_without_magic = 0
        
        for pos in positions:
            magic = pos.get('magic')
            if magic is not None and magic != 0:
                # Has magic number - group with others sharing same magic
                unique_magics.add(magic)
            else:
                # No magic number - count as separate trade
                positions_without_magic += 1
        
        total_signals = len(unique_magics) + positions_without_magic
        
        if len(positions) > total_signals:
            logger.debug(f"📊 Multi-TP detected: {len(positions)} positions grouped into {total_signals} signals")
        
        return total_signals


