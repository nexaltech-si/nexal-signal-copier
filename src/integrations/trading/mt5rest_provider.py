"""
MT5 REST API Trading Provider.
HTTP client that wraps the self-hosted MT5 Flask REST API (mt5/app/).
Implements BaseTradingProvider so it can be swapped in for MetaAPI SDK.
"""
import asyncio
import json
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Any

import aiohttp
from loguru import logger

from config import settings
from src.models import TradingSignal, TradeResult, AccountInfo, SignalType, RiskAssessment
from src.integrations.trading.base_provider import BaseTradingProvider
from src.utils.rate_limit_handler import with_rate_limit_handling, is_rate_limit_error, is_timeout_error
from src.services.position_cache import position_cache
from src.services.copy_master_service import copy_master_service, RUNNING as CM_RUNNING

# MT5 TRADE_RETCODE_NO_CHANGES: the SL/TP (or order price) asked for is what it already is.
RETCODE_NO_CHANGES = 10025


class MT5BridgeError(Exception):
    """The bridge answered with an HTTP error: it is up, the request or the broker said no.

    Kept apart from connection errors so a broker rejection is not reported as
    the bridge being down.
    """

    def __init__(self, status: int, path: str, body: str):
        self.status, self.path = status, path
        self.retcode: Optional[int] = None
        self.mt5_error = ""
        try:
            data = json.loads(body)
            self.retcode = data.get("retcode")
            self.mt5_error = data.get("mt5_error") or data.get("error") or ""
        except (ValueError, AttributeError):
            self.mt5_error = body[:200]
        # No retcode in the text: cancel_order string-matches "10013", and that
        # path must keep behaving as before (a filled order also returns 10013).
        super().__init__(f"MT5 REST API {status} on {path}: {self.mt5_error or 'no detail'}")


def order_tickets(order_result: dict):
    """(order_id, position_id, deal_id) from an MT5 order_send result.

    MT5 gives a position the ticket of the order that opened it; the deal ticket is
    a different number that only marks the fill. Recording the deal as the position
    made order sync miss the position (the trade was marked CLOSED at P/L 0) and
    orphan recovery add a second record for it — every market fill appeared twice.
    """
    order_id = str(order_result.get("order", "") or "")
    deal = order_result.get("deal")
    deal_id = str(deal) if deal and str(deal) != "0" else None
    return order_id, order_id, deal_id


class MT5RestProvider(BaseTradingProvider):
    """
    Trading provider that communicates with the self-hosted MT5 REST API.
    
    The REST API runs as a Flask app (mt5/app/) inside Docker and exposes
    endpoints for orders, positions, data, history, etc.
    """

    def __init__(self):
        self._is_connected = False
        self._session: Optional[aiohttp.ClientSession] = None
        self._base_url = settings.mt5_rest_api_url.rstrip("/")
        self._api_key = settings.mt5_rest_api_key
        self._request_timeout = aiohttp.ClientTimeout(total=30)
        self._last_health_check: Optional[float] = None
        self._health_check_interval = 30  # Check connection every 30 seconds
        self._reconnecting = False  # Flag to prevent recursive reconnection attempts
        self._last_error_message: Optional[str] = None
        self._reconnection_task: Optional[asyncio.Task] = None
        self._stop_reconnection = False

        # Caches
        self._account_info_cache: Optional[AccountInfo] = None
        self._account_info_cache_time: Optional[float] = None
        self._account_info_cache_ttl = 60

        self._positions_cache: Optional[List[dict]] = None
        self._positions_cache_time: Optional[float] = None
        self._positions_cache_ttl = 3

        self._orders_cache: Optional[List[dict]] = None
        self._orders_cache_time: Optional[float] = None
        self._orders_cache_ttl = 3

        self._symbol_specs_cache: dict = {}
        self._symbol_cache: dict = {}
        self._available_symbols: Optional[set] = None
        self._available_symbols_cache_time: Optional[float] = None
        self._available_symbols_cache_ttl = 300  # Cache for 5 minutes

        self._symbols_snapshot: Optional[List[dict]] = None
        self._symbols_snapshot_time: Optional[float] = None
        self._symbols_snapshot_ttl = 300  # name + quote for every symbol

        # Register for configuration changes
        self._register_config_callbacks()
        
    def _register_config_callbacks(self):
        """Register callbacks for configuration changes"""
        try:
            logger.debug("MT5 REST provider registered for config changes")
        except Exception as e:
            logger.warning(f"Failed to register config callbacks: {e}")
            
    def _on_config_change(self):
        """Handle configuration changes"""
        logger.info("🔄 MT5 REST provider updating configuration...")
        # Update connection parameters if they changed
        new_base_url = settings.mt5_rest_api_url.rstrip("/")
        new_api_key = settings.mt5_rest_api_key
        
        if new_base_url != self._base_url or new_api_key != self._api_key:
            logger.info("🔄 MT5 REST API configuration changed, will reconnect on next use")
            self._base_url = new_base_url
            self._api_key = new_api_key
            # Force reconnection on next API call
            self._is_connected = False
        
        # Clear ALL caches to prevent stale data after config change
        self._account_info_cache = None
        self._account_info_cache_time = None
        self._positions_cache = None
        self._positions_cache_time = None
        self._orders_cache = None
        self._orders_cache_time = None
        self._symbol_specs_cache = {}
        self._symbol_cache = {}
        self._available_symbols = None
        self._available_symbols_cache_time = None
        
        logger.info("🔄 MT5 REST provider configuration updated, all caches cleared")

    # ── helpers ───────────────────────────────────────────────────────────

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        return headers

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=self._request_timeout,
                headers=self._headers(),
            )
        return self._session

    async def _get(self, path: str, params: Optional[dict] = None) -> dict:
        session = await self._ensure_session()
        url = f"{self._base_url}{path}"
        try:
            async with session.get(url, params=params) as resp:
                if resp.status >= 400:
                    error_body = await resp.text()
                    logger.error(f"MT5 REST API {resp.status} on GET {path}: {error_body}")
                    raise MT5BridgeError(resp.status, path, error_body)
                return await resp.json()
        except asyncio.TimeoutError:
            logger.error(f"MT5 REST API timeout: {path}")
            raise Exception(f"MT5 REST API timeout: {path}")
        except aiohttp.ClientError as e:
            logger.error(f"MT5 REST API request failed: {path} — {e}")
            raise Exception(f"MT5 REST API connection error: {e}") from e

    async def _post(self, path: str, json_body: Optional[dict] = None) -> dict:
        session = await self._ensure_session()
        url = f"{self._base_url}{path}"
        try:
            async with session.post(url, json=json_body) as resp:
                if resp.status >= 400:
                    error_body = await resp.text()
                    error = MT5BridgeError(resp.status, path, error_body)
                    if error.retcode == RETCODE_NO_CHANGES:
                        # Not a failure: the caller decides what "already set" means.
                        logger.info(f"MT5 REST API {path}: nothing to change for {json_body}")
                    else:
                        # One entry: the log monitor attaches the second line as detail.
                        logger.error(f"MT5 REST API {resp.status} on POST {path}: {error_body}\n"
                                     f"   Request body was: {json_body}")
                    raise error
                return await resp.json()
        except asyncio.TimeoutError:
            logger.error(f"MT5 REST API timeout: {path}")
            raise Exception(f"MT5 REST API timeout: {path}")
        except aiohttp.ClientError as e:
            logger.error(f"MT5 REST API request failed: {path} — {e}")
            raise Exception(f"MT5 REST API connection error: {e}") from e

    def _cache_valid(self, cache_time: Optional[float], ttl: float) -> bool:
        if cache_time is None:
            return False
        return (datetime.now().timestamp() - cache_time) < ttl

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

    @staticmethod
    def _sanitize_channel_id(channel_id) -> str:
        """Sanitize channel ID for use in trade comments."""
        if not channel_id:
            return "unknown"
        return str(channel_id).replace("-", "")[:20]

    # ── Normalization helpers (MT5→MetaAPI field names) ───────────────────

    @staticmethod
    def _normalize_position(raw: dict) -> dict:
        """Convert MT5 REST position dict to MetaAPI-style field names."""
        pos_type = int(raw.get("type", 0))
        
        # Handle time normalization (MT5 often returns unix timestamp)
        open_time = raw.get("time")
        if isinstance(open_time, (int, float)):
            open_time = datetime.fromtimestamp(open_time, tz=timezone.utc)
        elif isinstance(open_time, str) and open_time:
            try:
                open_time = datetime.fromisoformat(open_time.replace('Z', '+00:00'))
            except ValueError:
                pass
        
        if open_time:
            logger.debug(f"⏰ Normalized position {raw.get('ticket')} time: {raw.get('time')} -> {open_time}")
            
        return {
            "id": str(raw.get("ticket", "")),
            "symbol": raw.get("symbol", ""),
            "type": "POSITION_TYPE_BUY" if pos_type == 0 else "POSITION_TYPE_SELL",
            "volume": float(raw.get("volume", 0)),
            "openPrice": float(raw.get("price_open", 0)),
            "currentPrice": float(raw.get("price_current", 0)),
            "stopLoss": float(raw.get("sl", 0)) or None,
            "takeProfit": float(raw.get("tp", 0)) or None,
            "profit": float(raw.get("profit", 0)),
            "swap": float(raw.get("swap", 0)),
            "magic": int(raw.get("magic", 0)),
            "clientId": str(raw.get("magic", 0)),
            "comment": raw.get("comment", ""),
            "openTime": open_time,
            "time": open_time,
            # keep raw data for debugging
            "_raw_ticket": raw.get("ticket"),
        }

    @staticmethod
    def _normalize_order(raw: dict) -> dict:
        """Convert MT5 REST pending order dict to MetaAPI-style field names."""
        type_map = {
            2: "ORDER_TYPE_BUY_LIMIT",
            3: "ORDER_TYPE_SELL_LIMIT",
            4: "ORDER_TYPE_BUY_STOP",
            5: "ORDER_TYPE_SELL_STOP",
            6: "ORDER_TYPE_BUY_STOP_LIMIT",
            7: "ORDER_TYPE_SELL_STOP_LIMIT",
        }
        raw_type = int(raw.get("type", 0))
        
        # Handle time normalization
        open_time = raw.get("time_setup") or raw.get("time")
        if isinstance(open_time, (int, float)):
            open_time = datetime.fromtimestamp(open_time, tz=timezone.utc)
        elif isinstance(open_time, str) and open_time:
            try:
                open_time = datetime.fromisoformat(open_time.replace('Z', '+00:00'))
            except ValueError:
                pass

        return {
            "id": str(raw.get("ticket", "")),
            "symbol": raw.get("symbol", ""),
            "type": type_map.get(raw_type, f"ORDER_TYPE_{raw_type}"),
            "volume": float(raw.get("volume_current", raw.get("volume_initial", 0))),
            "openPrice": float(raw.get("price_open", 0)),
            "stopLoss": float(raw.get("sl", 0)) or None,
            "takeProfit": float(raw.get("tp", 0)) or None,
            "magic": int(raw.get("magic", 0)),
            "clientId": str(raw.get("magic", 0)),
            "comment": raw.get("comment", ""),
            "openTime": open_time,
            "_raw_ticket": raw.get("ticket"),
        }

    # ── BaseTradingProvider implementation ────────────────────────────────

    # is_connected property with automatic connection verification
    @property
    def is_connected(self) -> bool:
        """
        Check if connected. For sync operations, returns cached status.
        For critical operations, _verify_connection() is called explicitly.
        """
        # Return cached status without async verification to avoid blocking
        # Actual verification happens in _verify_connection() called by operations
        return self._is_connected
    
    @is_connected.setter
    def is_connected(self, value: bool):
        self._is_connected = value

    async def initialize(self) -> None:
        """Verify the MT5 REST API is reachable and MT5 terminal is connected.
        
        Retries with exponential backoff. If connection fails, starts background
        reconnection task and continues - bot will function in degraded mode.
        """
        max_initial_retries = 3  # Quick initial attempts
        retry_delay = 5  # Start with 5 seconds

        for attempt in range(max_initial_retries):
            logger.info(f"🔌 Initializing MT5 REST API provider (attempt {attempt + 1}/{max_initial_retries})...")
            logger.info(f"   URL: {self._base_url}")

            try:
                data = await self._get("/health")
                mt5_ok = data.get("mt5_connected", False)
                if not mt5_ok:
                    logger.warning("⚠️  MT5 REST API is up but MT5 terminal is NOT connected")
                    if attempt < max_initial_retries - 1:
                        logger.info(f"⏳ Retrying in {retry_delay}s...")
                        await asyncio.sleep(retry_delay)
                        retry_delay = min(retry_delay * 2, 60)
                        continue
                    else:
                        logger.warning("⚠️  MT5 terminal not connected - starting background reconnection")
                        self._is_connected = False
                        self._last_error_message = "MT5 terminal not connected"
                        self._start_background_reconnection()
                        return
                else:
                    logger.success("✅ MT5 REST API connected — MT5 terminal is live")

                # Fetch account info to confirm trading is possible
                acct = await self._get("/account_info")
                logger.info(f"💰 Account: {acct.get('login')} @ {acct.get('server')}")
                logger.info(f"💰 Balance: ${acct.get('balance', 0):.2f}")
                logger.info(f"💵 Equity:  ${acct.get('equity', 0):.2f}")

                self._is_connected = True
                self._last_health_check = datetime.now().timestamp()
                
                # Pre-populate cache immediately after connecting
                try:
                    await self.get_account_info(use_cache=False)
                    logger.success("✅ MT5 REST API provider ready and account info cached")
                except Exception as cache_err:
                    logger.warning(f"⚠️ Provider initialized but failed to pre-populate cache: {cache_err}")
                
                return

            except asyncio.TimeoutError:
                err_msg = "request timed out (MT5 terminal may be under heavy load)"
                if attempt < max_initial_retries - 1:
                    logger.warning(f"⚠️  MT5 REST API not reachable (attempt {attempt + 1}/{max_initial_retries}): {err_msg}")
                    logger.info(f"⏳ Retrying in {retry_delay}s...")
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, 60)
                else:
                    logger.warning(f"⚠️  Failed to connect to MT5 REST API after {max_initial_retries} attempts: {err_msg}")
                    logger.info("🔄 Starting background reconnection task - bot will run in degraded mode")
                    self._is_connected = False
                    self._last_error_message = err_msg
                    self._start_background_reconnection()
                    return
            except Exception as e:
                if attempt < max_initial_retries - 1:
                    logger.warning(f"⚠️  MT5 REST API not reachable (attempt {attempt + 1}/{max_initial_retries}): {e}")
                    logger.info(f"⏳ Retrying in {retry_delay}s...")
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, 60)
                else:
                    logger.warning(f"⚠️  Failed to connect to MT5 REST API after {max_initial_retries} attempts: {e}")
                    logger.info("🔄 Starting background reconnection task - bot will run in degraded mode")
                    self._is_connected = False
                    self._last_error_message = str(e)
                    self._start_background_reconnection()
                    return

    def _start_background_reconnection(self):
        """Start background task to continuously retry connection"""
        if self._reconnection_task and not self._reconnection_task.done():
            logger.debug("Background reconnection already running")
            return
        
        self._stop_reconnection = False
        self._reconnection_task = asyncio.create_task(self._reconnection_loop())
        logger.info("🔄 Background reconnection task started")
    
    async def _reconnection_loop(self):
        """Continuously try to reconnect to MT5 REST API"""
        retry_delay = 10  # Start with 10 seconds
        attempt = 0
        
        while not self._stop_reconnection:
            try:
                attempt += 1
                logger.debug(f"🔄 Background reconnection attempt #{attempt}...")
                
                data = await self._get("/health")
                mt5_ok = data.get("mt5_connected", False)
                
                if mt5_ok:
                    # Successfully reconnected!
                    logger.success("✅ MT5 REST API reconnected successfully!")
                    
                    # Fetch account info to confirm
                    try:
                        acct = await self._get("/account_info")
                        logger.info(f"💰 Account: {acct.get('login')} @ {acct.get('server')}")
                        logger.info(f"💰 Balance: ${acct.get('balance', 0):.2f}")
                        logger.info(f"💵 Equity:  ${acct.get('equity', 0):.2f}")
                        
                        self._is_connected = True
                        self._last_health_check = datetime.now().timestamp()
                        self._last_error_message = None
                        
                        # Pre-populate cache
                        await self.get_account_info(use_cache=False)
                        logger.success("✅ MT5 REST API fully operational")
                        
                        # Stop reconnection loop
                        break
                    except Exception as acct_err:
                        logger.warning(f"⚠️  Reconnected but failed to fetch account: {acct_err}")
                        raise
                else:
                    logger.debug("⚠️  MT5 REST API reachable but terminal not connected")
                    self._last_error_message = "MT5 terminal not connected"
                    
            except Exception as e:
                self._last_error_message = str(e)
                logger.debug(f"🔄 Reconnection attempt #{attempt} failed: {str(e)[:100]}")
            
            # Wait before next attempt (exponential backoff, capped at 60s)
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 1.5, 60)
        
        logger.info("🔄 Background reconnection task stopped")

    async def disconnect(self) -> None:
        """Close the HTTP session."""
        logger.info("🔌 Disconnecting MT5 REST API provider...")
        self._is_connected = False
        self._stop_reconnection = True
        
        # Cancel reconnection task if running
        if self._reconnection_task and not self._reconnection_task.done():
            self._reconnection_task.cancel()
            try:
                await self._reconnection_task
            except asyncio.CancelledError:
                pass
        
        if self._session and not self._session.closed:
            await self._session.close()
            await asyncio.sleep(0.25)
        logger.info("✅ MT5 REST API provider disconnected")

    # ── Account ──────────────────────────────────────────────────────────

    async def _verify_connection(self) -> bool:
        """Verify connection is still alive with periodic health checks"""
        # MT5 terminal can take up to ~20s to respond under load — use a generous timeout
        _HEALTH_TIMEOUT = 25.0

        # Prevent recursive reconnection attempts
        if self._reconnecting:
            return False

        if not self._is_connected:
            # If background reconnection is already running, don't compete with it
            if self._reconnection_task and not self._reconnection_task.done():
                logger.debug("🔄 Reconnection in progress, skipping concurrent attempt")
                return False

            logger.info("🔄 Connection lost, starting background reconnection...")
            self._start_background_reconnection()

            # Try a single quick reconnect attempt
            self._reconnecting = True
            try:
                data = await asyncio.wait_for(self._get("/health"), timeout=_HEALTH_TIMEOUT)
                mt5_ok = data.get("mt5_connected", False)
                if mt5_ok:
                    logger.success("✅ Reconnected to MT5 REST API")
                    self._is_connected = True
                    self._last_health_check = datetime.now().timestamp()
                    self._last_error_message = None
                    self._stop_reconnection = True  # Stop background task
                    return True
                else:
                    logger.warning("⚠️  MT5 REST API reachable but MT5 terminal not connected")
                    self._last_error_message = "MT5 terminal not connected"
                    return False
            except asyncio.TimeoutError:
                self._last_error_message = f"Health check timed out ({_HEALTH_TIMEOUT:.0f}s)"
                logger.debug(f"Quick reconnection timed out after {_HEALTH_TIMEOUT:.0f}s")
                return False
            except Exception as e:
                self._last_error_message = str(e)
                logger.debug(f"Quick reconnection failed: {str(e)[:80]}")
                return False
            finally:
                self._reconnecting = False

        # Check if we need to verify connection health
        now = datetime.now().timestamp()
        if self._last_health_check and (now - self._last_health_check) < self._health_check_interval:
            return True  # Recently verified, assume still connected

        try:
            data = await asyncio.wait_for(self._get("/health"), timeout=_HEALTH_TIMEOUT)
            mt5_ok = data.get("mt5_connected", False)
            if not mt5_ok:
                msg = "MT5 terminal disconnected (REST API is up but MT5 is offline)"
                logger.warning(f"⚠️  {msg}")
                self._last_error_message = msg
                self._is_connected = False
                return False

            self._last_health_check = now
            return True
        except asyncio.TimeoutError:
            self._last_error_message = f"Health check timed out ({_HEALTH_TIMEOUT:.0f}s)"
            logger.warning(f"⚠️  Connection health check timed out ({_HEALTH_TIMEOUT:.0f}s) — MT5 may be under heavy load")
            self._is_connected = False
            return False
        except Exception as e:
            self._last_error_message = str(e)
            logger.warning(f"⚠️  Connection health check failed: {e}")
            self._is_connected = False
            return False

    @with_rate_limit_handling()
    async def get_account_info(self, use_cache: bool = True) -> AccountInfo:
        # 1. Try valid cache first to avoid unnecessary network calls
        if use_cache and self._cache_valid(self._account_info_cache_time, self._account_info_cache_ttl):
            return self._account_info_cache  # type: ignore

        # 2. Verify connection before proceeding with a fresh fetch
        if not await self._verify_connection():
            # If connection fails but we have a cache (even if stale), use it as fallback
            if self._account_info_cache:
                logger.warning(f"⚠️ MT5 REST API not reachable ({self._last_error_message}) - using stale cache as fallback for account info")
                return self._account_info_cache
            
            # If no cache at all, we must raise
            error_msg = f"MT5 REST API not connected: {self._last_error_message}" if self._last_error_message else "MT5 REST API not connected"
            raise Exception(error_msg)

        try:
            logger.debug("📊 Fetching account information from MT5 REST API...")
            data = await asyncio.wait_for(
                self._get("/account_info"),
                timeout=30.0  # 30 second timeout
            )
            logger.debug("✅ Account information retrieved")
        except asyncio.TimeoutError:
            if self._account_info_cache:
                logger.warning("⚠️ Timeout fetching account info - using cached data")
                return self._account_info_cache
            logger.error("❌ Timeout fetching account information (30s)")
            raise Exception("Timeout fetching account information from MT5 REST API")
        except Exception as e:
            # Check for rate limit error
            if is_rate_limit_error(e):
                if self._account_info_cache:
                    logger.warning("⚠️ Rate limit hit - using cached account info")
                    return self._account_info_cache
                logger.error("❌ Rate limit fetching account info and no cache available")
                raise Exception("Rate limit fetching account information")
            logger.error(f"❌ Failed to fetch account info: {e}")
            raise

        positions = await self.get_open_positions(use_cache=True)
        unique_signals = self._count_unique_signals(positions)

        info = AccountInfo(
            balance=float(data.get("balance", 0)),
            equity=float(data.get("equity", 0)),
            margin=float(data.get("margin", 0)),
            free_margin=float(data.get("margin_free", 0)),
            open_positions=unique_signals,
            currency=data.get("currency", "USD"),
            leverage=data.get("leverage"),
        )
        self._account_info_cache = info
        self._account_info_cache_time = datetime.now().timestamp()
        return info

    # ── Symbol resolution ────────────────────────────────────────────────

    async def _get_available_symbols(self) -> set:
        """Fetch and cache the list of available symbols from the broker"""
        if self._available_symbols and self._cache_valid(self._available_symbols_cache_time, self._available_symbols_cache_ttl):
            return self._available_symbols
        
        try:
            logger.debug("📋 Fetching available symbols from MT5 REST API...")
            data = await self._get("/symbols")
            self._available_symbols = set(data)
            self._available_symbols_cache_time = datetime.now().timestamp()
            logger.debug(f"✅ Cached {len(self._available_symbols)} available symbols")
            return self._available_symbols
        except Exception as e:
            logger.warning(f"⚠️ Failed to fetch available symbols: {e}")
            # Return empty set if fetch fails - allow resolution to proceed
            return set()

    async def get_symbols_snapshot(self, select_unquoted: bool = True) -> List[dict]:
        """
        Every broker symbol with its current quote, in one request.

        Returns a list of dicts: name, bid, ask, digits, description, visible.
        Used by the symbol matcher to work out which instruments trade near a
        given price when a signal arrives without a readable ticker.

        Cached for 5 minutes — quotes drift, but the matcher only needs the
        right order of magnitude, not a live tick.
        """
        if self._symbols_snapshot and self._cache_valid(
            self._symbols_snapshot_time, self._symbols_snapshot_ttl
        ):
            return self._symbols_snapshot

        try:
            data = await asyncio.wait_for(
                self._get("/symbols/quotes", params={"select": "1" if select_unquoted else "0"}),
                timeout=45.0,  # the select pass walks the whole symbol list
            )
            snapshot = [row for row in (data or []) if isinstance(row, dict) and row.get("name")]
            if snapshot:
                self._symbols_snapshot = snapshot
                self._symbols_snapshot_time = datetime.now().timestamp()
                logger.debug(f"✅ Cached quote snapshot for {len(snapshot)} symbols")
            return snapshot
        except Exception as e:
            # Older MT5 REST builds don't have /symbols/quotes — fall back to
            # names only so the caller can still price a shortlist by hand.
            logger.warning(f"⚠️ Could not fetch symbol quote snapshot: {e}")
            try:
                names = await self._get_available_symbols()
                return [{"name": n, "bid": 0, "ask": 0} for n in names]
            except Exception:
                return []

    async def _symbol_exists(self, symbol: str) -> bool:
        """Check if a symbol exists in the broker's available symbols"""
        try:
            available_symbols = await self._get_available_symbols()
            if not available_symbols:
                # If we couldn't fetch the list, try to check directly
                try:
                    await self._get(f"/symbol_info/{symbol}")
                    return True
                except Exception:
                    return False
            return symbol in available_symbols
        except Exception:
            return False

    async def resolve_symbol(self, symbol: str) -> str:
        """Resolve symbol name variations for MT5 REST API"""
        
        # Check cache first
        if symbol in self._symbol_cache:
            return self._symbol_cache[symbol]
        
        # Detect if this is a forex pair (6 characters, first 3 are letters, last 3 are letters)
        # Exclude metals like XAUUSD, XAGUSD which are 6 chars but not forex pairs
        metals = {'XAU', 'XAG', 'XPT', 'XPD'}  # Gold, Silver, Platinum, Palladium
        is_metal = len(symbol) >= 6 and symbol[:3] in metals
        is_forex_pair = len(symbol) == 6 and symbol[:3].isalpha() and symbol[3:].isalpha() and not is_metal
        
        configured_suffix = settings.mt5_symbol_suffix

        # 1) For forex pairs, try with .fx suffix first
        if is_forex_pair and configured_suffix:
            preferred = f"{symbol}{configured_suffix}"
            if await self._symbol_exists(preferred):
                logger.debug(f"✅ Forex symbol '{symbol}' → '{preferred}' (configured suffix)")
                self._symbol_cache[symbol] = preferred
                return preferred

        # 2) Try bare symbol (works for metals, indices, commodities)
        if await self._symbol_exists(symbol):
            logger.debug(f"✅ Symbol '{symbol}' → '{symbol}' (bare symbol)")
            self._symbol_cache[symbol] = symbol
            return symbol

        # 3) For forex pairs, try common suffixes if bare symbol failed
        if is_forex_pair:
            suffixes = [".fx", "m", "+", ".a", ".m", "-", ".c", "#", "pro"]
            for sfx in suffixes:
                if sfx == configured_suffix:
                    continue
                variation = f"{symbol}{sfx}"
                if await self._symbol_exists(variation):
                    logger.success(f"✅ Forex symbol resolved: '{symbol}' → '{variation}'")
                    self._symbol_cache[symbol] = variation
                    return variation

        logger.warning(f"⚠️  Symbol '{symbol}' not found in broker's available symbols")
        self._symbol_cache[symbol] = symbol
        return symbol

    @with_rate_limit_handling()
    async def get_symbol_price(self, symbol: str) -> dict:
        resolved = await self.resolve_symbol(symbol)
        try:
            data = await asyncio.wait_for(
                self._get(f"/symbol_info_tick/{resolved}"),
                timeout=10.0  # 10 second timeout for price data
            )
            return {
                "bid": float(data.get("bid", 0)),
                "ask": float(data.get("ask", 0)),
                "spread": float(data.get("ask", 0)) - float(data.get("bid", 0)),
            }
        except asyncio.TimeoutError:
            logger.error(f"❌ Timeout fetching price for {resolved}")
            raise Exception(f"Timeout fetching price for {symbol}")
        except Exception as e:
            error_msg = str(e)
            # Check for "No tick for symbol" error (market closed or not actively trading)
            if "No tick for symbol" in error_msg or "NOT FOUND" in error_msg:
                logger.error(f"❌ No price data available for {symbol}: {e}")
                raise Exception(f"No price data available for {symbol} - market may be closed or symbol not actively trading") from e
            if is_rate_limit_error(e):
                logger.warning(f"⚠️ Rate limit fetching price for {resolved}")
                raise Exception(f"Rate limit fetching price for {symbol}")
            logger.error(f"❌ Failed to get price for {resolved}: {e}")
            raise

    async def get_symbol_specification(self, symbol: str) -> dict:
        logger.info(f"🔧 get_symbol_specification called for {symbol}")
        if symbol in self._symbol_specs_cache:
            logger.info(f"📦 Using cached symbol spec for {symbol}")
            return self._symbol_specs_cache[symbol]

        try:
            resolved = await self.resolve_symbol(symbol)
            
            # Check if the resolved symbol actually exists
            if not await self._symbol_exists(resolved):
                logger.error(f"❌ Symbol '{symbol}' (resolved to '{resolved}') is not available on this broker")
                raise Exception(f"Symbol {symbol} is not available on this broker")
            
            logger.info(f"🔍 Fetching symbol info for resolved symbol: {resolved}")
            data = await self._get(f"/symbol_info/{resolved}")
            spec = {
                "symbol": resolved,
                "tickSize": data.get("trade_tick_size", 0.00001),
                "contractSize": data.get("trade_contract_size", 100000),
                "digits": data.get("digits", 5),
                "volumeStep": data.get("volume_step", 0.01),
                "volumeMin": data.get("volume_min", 0.01),
                "volumeMax": data.get("volume_max", 100.0),
            }
            self._symbol_specs_cache[symbol] = spec
            self._symbol_specs_cache[resolved] = spec
            logger.info(f"✅ Cached and returned symbol spec for {symbol}: min={spec.get('volumeMin')}, step={spec.get('volumeStep')}")
            return spec
        except Exception as e:
            error_msg = str(e)
            # Check if this is a "symbol not available" error
            if "is not available on this broker" in error_msg or "NOT FOUND" in error_msg:
                logger.error(f"❌ Symbol {symbol} not available: {e}")
                raise Exception(f"Symbol {symbol} is not available on this broker") from e
            logger.error(f"❌ Failed to fetch symbol spec for {symbol}: {e}")
            raise Exception(f"Cannot get symbol specification for {symbol}: {e}")

    async def round_lot_size(self, symbol: str, lot_size: float) -> float:
        logger.info(f"🔧 round_lot_size called for {symbol}: {lot_size}")
        try:
            spec = await self.get_symbol_specification(symbol)
            volume_min = spec.get("volumeMin")
            volume_max = spec.get("volumeMax")
            volume_step = spec.get("volumeStep")
            
            logger.info(f"📊 {symbol} lot size constraints: min={volume_min}, max={volume_max}, step={volume_step}")

            # Calculate decimal places for rounding
            if volume_step >= 1.0:
                dp = 0
            elif volume_step >= 0.1:
                dp = 1
            elif volume_step >= 0.01:
                dp = 2
            else:
                dp = 3

            # Round to nearest valid step
            rounded = round(lot_size / volume_step) * volume_step
            
            # Ensure within min/max bounds
            rounded = max(volume_min, min(rounded, volume_max))
            
            # Apply final rounding
            final_lot = round(rounded, dp)
            
            logger.info(f"📏 Lot size adjusted for {symbol}: {lot_size} → {final_lot} (min={volume_min}, step={volume_step})")
            
            return final_lot
        except Exception as e:
            logger.error(f"❌ Failed to round lot size for {symbol}: {e}")
            raise Exception(f"Cannot determine valid lot size for {symbol}: {e}")

    # ── Trade execution ──────────────────────────────────────────────────

    async def execute_trade(
        self,
        signal: TradingSignal,
        risk_assessment: RiskAssessment,
        magic_number: Optional[int] = None,
    ) -> TradeResult:
        # Verify connection before executing trade
        if not await self._verify_connection():
            return TradeResult(success=False, error_message="MT5 REST API not connected")

        if settings.dry_run:
            logger.warning("🧪 DRY RUN MODE — Trade not executed")
            return TradeResult(
                success=True,
                position_id="DRY_RUN",
                entry_price=signal.entry_price,
                error_message="Dry run mode",
            )

        if not signal.stop_loss:
            logger.error("🚨 CRITICAL: Trade blocked — No stop loss!")
            return TradeResult(
                success=False,
                error_message="SAFETY BLOCK: Stop loss is mandatory",
            )

        # CRITICAL: Never trade without take profit
        has_tp = (
            signal.take_profit
            and isinstance(signal.take_profit, list)
            and len(signal.take_profit) > 0
            and any(tp is not None for tp in signal.take_profit)
        )
        if not has_tp:
            logger.error("🚨 CRITICAL: Trade blocked — No take profit!")
            logger.error("   Signal TPs were either missing or stripped due to invalid direction.")
            return TradeResult(
                success=False,
                error_message="SAFETY BLOCK: Take profit is mandatory. All TPs were invalid or missing.",
            )

        is_multi_tp = (
            signal.take_profit
            and isinstance(signal.take_profit, list)
            and len(signal.take_profit) > 1
        )

        # Multiple scale-in legs need one order PER LEG even when there is a single TP,
        # so they also route through the multi-order executor.
        has_multi_entry = bool(
            hasattr(signal, 'discrete_entry_prices') and signal.discrete_entry_prices()
        )

        if is_multi_tp or has_multi_entry:
            return await self._execute_multi_tp_trade(signal, risk_assessment, magic_number)

        return await self._execute_single_trade(signal, risk_assessment, magic_number)

    @staticmethod
    def _instant_applies(signal: TradingSignal) -> bool:
        # Pending STOP orders are explicit breakout entries — "now" doesn't turn them into market.
        return bool(getattr(signal, 'instant_execution', False)) and signal.signal_type not in (
            SignalType.BUY_STOP, SignalType.SELL_STOP)

    @staticmethod
    def _instant_deviation(signal: TradingSignal) -> float:
        from src.services.execution_policy import instant_max_deviation_price
        return instant_max_deviation_price(signal.symbol)

    @staticmethod
    def _instant_one_leg_progress() -> float:
        return float(getattr(settings, 'instant_one_leg_max_tp1_progress', 0) or 0)

    async def _volume_spec(self, symbol: str) -> tuple:
        """(step, min) lot size for symbol; 0.01/0.01 when the broker spec is unavailable."""
        try:
            spec = await self.get_symbol_specification(symbol)
            return spec.get('volumeStep', 0.01) or 0.01, spec.get('volumeMin', 0.01) or 0.01
        except Exception:
            return 0.01, 0.01

    async def _execute_single_trade(
        self,
        signal: TradingSignal,
        risk_assessment: RiskAssessment,
        magic_number: Optional[int] = None,
    ) -> TradeResult:
        try:
            is_buy = self._is_buy_signal(signal)
            resolved = await self.resolve_symbol(signal.symbol)
            lot_size = await self.round_lot_size(signal.symbol, risk_assessment.calculated_lot_size)

            # Determine TP
            tp_value = None
            if signal.take_profit:
                if isinstance(signal.take_profit, list) and signal.take_profit:
                    tp_value = signal.take_profit[0]
                elif isinstance(signal.take_profit, (int, float)):
                    tp_value = signal.take_profit
            elif hasattr(signal, "take_profit_levels") and signal.take_profit_levels:
                tp_value = signal.take_profit_levels[0]

            # Get current price (MetaAPI-style: always fetch live price first)
            current_price_data = await self.get_symbol_price(signal.symbol)
            current_price = current_price_data['ask'] if is_buy else current_price_data['bid']
            
            # Determine entry price
            entry_price = signal.entry_price
            if not entry_price:
                entry_price = current_price
                logger.info(f"   Using market price: {entry_price}")
            
            # SMART EXECUTION LOGIC: Decide between market order, limit order, or immediate execution
            # This handles all scenarios including when entry_price is specified
            signal_type = signal.signal_type or (SignalType.BUY if is_buy else SignalType.SELL)
            execute_as_market = False
            should_place_limit = False
            
            # Case 1: Entry price is specified (signal wants specific entry level)
            if entry_price:
                if is_buy:
                    # BUY order: Want to buy at entry_price or LOWER
                    if current_price <= entry_price:
                        logger.info(f"💰 FAVORABLE PRICE: Current ask {current_price} <= desired entry {entry_price}")
                        logger.info("   → Executing as MARKET BUY (better price available now)")
                        execute_as_market = True
                    else:
                        logger.info(f"⏳ WAITING FOR BETTER PRICE: Current ask {current_price} > desired entry {entry_price}")
                        should_place_limit = True
                        signal_type = SignalType.BUY_LIMIT
                else:
                    # SELL order: Want to sell at entry_price or HIGHER
                    if current_price >= entry_price:
                        logger.info(f"💰 FAVORABLE PRICE: Current bid {current_price} >= desired entry {entry_price}")
                        logger.info("   → Executing as MARKET SELL (better price available now)")
                        execute_as_market = True
                    else:
                        logger.info(f"⏳ WAITING FOR BETTER PRICE: Current bid {current_price} < desired entry {entry_price}")
                        should_place_limit = True
                        signal_type = SignalType.SELL_LIMIT

            # Case 2: No entry price specified → Market order (execute immediately)
            else:
                logger.info("📊 No entry price specified → Executing as MARKET order")
                execute_as_market = True

            # Case 2b: instant ("NOW") signal whose entry isn't reached yet → market
            # within the deviation cap instead of waiting as a limit.
            if should_place_limit and self._instant_applies(signal):
                chase = self.instant_market_entry(
                    is_buy, current_price, [entry_price], self._instant_deviation(signal),
                    signal.stop_loss, [tp_value] if tp_value else None,
                )
                if chase is not None:
                    logger.info(f"🚀 INSTANT: entry {entry_price} not reached, current {current_price} within cap → MARKET")
                    execute_as_market, should_place_limit = True, False
                    signal_type = SignalType.BUY if is_buy else SignalType.SELL
                elif self.instant_one_leg_entry(
                        is_buy, current_price, [entry_price], signal.stop_loss,
                        [tp_value] if tp_value else None, self._instant_one_leg_progress()) is not None:
                    # Beyond the cap but the move is young: in at market, same money at risk.
                    step, vmin = await self._volume_spec(signal.symbol)
                    scaled = self.same_risk_volume(lot_size, entry_price, current_price, signal.stop_loss, step, vmin)
                    logger.info(f"🚀 INSTANT: current {current_price} beyond the cap for {entry_price} → MARKET, "
                                f"{lot_size} → {scaled} lots for the same risk")
                    lot_size = scaled
                    execute_as_market, should_place_limit = True, False
                    signal_type = SignalType.BUY if is_buy else SignalType.SELL
                else:
                    logger.info(f"🚀 INSTANT: current {current_price} beyond cap / SL / TP / chase limit for entry {entry_price} → keeping LIMIT")

            # Case 3: Handle STOP orders (not affected by current price comparison)
            if signal_type in [SignalType.BUY_STOP, SignalType.SELL_STOP]:
                should_place_limit = True
                execute_as_market = False
                logger.info(f"📌 STOP order detected → Placing pending {signal_type.value} order")

            # Copy Master Mode: instead of resting a limit order, wait for the
            # master account to fill first, then enter at market with its SL/TP.
            if should_place_limit and settings.copy_master_mode:
                direction_str = "BUY" if is_buy else "SELL"
                cm_state, cm_pos = await copy_master_service.master_live_state(signal.symbol, direction_str)
                if cm_state == CM_RUNNING and cm_pos:
                    # Master is live — enter at market using master's SL/TP
                    master_sl = float(cm_pos.get("sl") or 0) or signal.stop_loss
                    master_tp_raw = cm_pos.get("tp") or 0
                    master_tp = float(master_tp_raw) if master_tp_raw else tp_value
                    logger.info(f"copy_master: {signal.symbol} {direction_str} master RUNNING — "
                                f"entering at market sl={master_sl} tp={master_tp}")
                    signal.stop_loss = master_sl
                    if master_tp:
                        if isinstance(signal.take_profit, list):
                            signal.take_profit = [master_tp]
                        else:
                            signal.take_profit = master_tp
                        tp_value = master_tp
                    execute_as_market = True
                    should_place_limit = False
                else:
                    # Master not yet running — queue and return without placing anything
                    intent_key = f"{signal.symbol}:{direction_str}"
                    _sl_ref   = signal.stop_loss
                    _tp_ref   = tp_value
                    _lots_ref = lot_size
                    _sym_ref  = resolved
                    _magic_ref = magic_number

                    async def _execute_later(msl, mtp, _lots=_lots_ref, _sym=_sym_ref,
                                             _magic=_magic_ref, _comment=self._generate_random_comment()):
                        body = {
                            "symbol": _sym,
                            "volume": float(_lots),
                            "type": "BUY" if is_buy else "SELL",
                            "deviation": int(settings.slippage_pips),
                            "magic": int(_magic or 0),
                            "comment": _comment,
                            "sl": float(msl) if msl else None,
                        }
                        if mtp:
                            body["tp"] = float(mtp)
                        try:
                            res = await self._post("/order", body)
                            self._positions_cache = None
                            self._orders_cache = None
                            order_res = res.get("result", {})
                            pid = str(order_res.get("order", order_res.get("deal", "")))
                            return TradeResult(success=True, position_id=pid, order_id=pid,
                                               entry_price=entry_price, broker_response=order_res)
                        except Exception as ex:
                            return TradeResult(success=False, error_message=str(ex))

                    await copy_master_service.register_intent(intent_key, {
                        "symbol": signal.symbol,
                        "direction": direction_str,
                        "stop_loss": _sl_ref,
                        "take_profit": _tp_ref,
                        "execute_fn": _execute_later,
                    })
                    logger.info("copy_master: %s queued — master %s, holding (no limit placed)",
                                intent_key, cm_state)
                    return TradeResult(
                        success=True,
                        position_id=f"COPY_MASTER_WAIT:{intent_key}",
                        entry_price=entry_price,
                        error_message=f"copy_master: waiting for master to fill ({cm_state})",
                    )

            comment = self._generate_random_comment()

            if execute_as_market:
                # Execute as market order
                body = {
                    "symbol": resolved,
                    "volume": float(lot_size),
                    "type": "BUY" if is_buy else "SELL",
                    "deviation": int(settings.slippage_pips),
                    "magic": int(magic_number or 0),
                    "comment": comment,
                    "sl": float(signal.stop_loss) if signal.stop_loss else None,
                }
                if tp_value:
                    body["tp"] = float(tp_value)
                logger.info(f"📤 Sending market order payload: {body}")
                result = await self._post("/order", body)
            elif should_place_limit:
                # Place pending order - use /limit_order endpoint
                body = self._build_pending_order_body(
                    resolved, lot_size, signal_type, entry_price,
                    signal.stop_loss, tp_value, magic_number, comment,
                )
                logger.info(f"📤 Sending pending order payload: {body}")
                logger.info(f"📤 Request details: symbol={resolved}, type={signal_type}, price={entry_price}, volume={lot_size}")
                result = await self._post("/limit_order", body)
            else:
                # Fallback to market order
                body = {
                    "symbol": resolved,
                    "volume": float(lot_size),
                    "type": "BUY" if is_buy else "SELL",
                    "deviation": int(settings.slippage_pips),
                    "magic": int(magic_number or 0),
                    "comment": comment,
                    "sl": float(signal.stop_loss) if signal.stop_loss else None,
                }
                if tp_value:
                    body["tp"] = float(tp_value)
                logger.info(f"📤 Sending fallback market order payload: {body}")
                result = await self._post("/order", body)

            # Invalidate caches
            self._positions_cache = None
            self._orders_cache = None

            order_result = result.get("result", {})
            
            order_id, position_id, deal_id = order_tickets(order_result)

            logger.success(f"✅ Trade executed via MT5 REST API: {result.get('message')}")
            logger.info(f"   order_id: {order_id}, position_id: {position_id}, deal_id: {deal_id}")
            return TradeResult(
                success=True,
                position_id=position_id,
                order_id=order_id,
                entry_price=entry_price,
                broker_response={**order_result, "dealId": deal_id},
            )
        except Exception as e:
            logger.error(f"❌ Trade execution failed (MT5 REST): {e}")
            return TradeResult(success=False, error_message=str(e))

    async def _execute_multi_tp_trade(
        self,
        signal: TradingSignal,
        risk_assessment: RiskAssessment,
        base_magic_number: Optional[int] = None,
    ) -> TradeResult:
        try:
            if not signal.stop_loss:
                return TradeResult(
                    success=False,
                    error_message="BLOCKED: Stop loss is mandatory for multi-TP trades",
                )

            tp_levels = list(signal.take_profit)
            is_buy = self._is_buy_signal(signal)
            resolved = await self.resolve_symbol(signal.symbol)

            # Consolidate TP levels so each lot slice meets broker minimum.
            # Reduce num_tps until lot_per_tp >= min_lot_size; keep the first N TPs
            # (best risk/reward) and drop the rest rather than placing 0-lot orders.
            total_lots = risk_assessment.calculated_lot_size
            num_tps = len(tp_levels)
            if num_tps > 1:
                _est_per_tp = total_lots / num_tps
                if _est_per_tp < settings.min_lot_size:
                    max_tps = max(1, int(total_lots / settings.min_lot_size))
                    if max_tps < num_tps:
                        dropped = tp_levels[max_tps:]
                        tp_levels = tp_levels[:max_tps]
                        num_tps = max_tps
                        logger.warning(
                            f"⚠️ Lot size too small to split {len(signal.take_profit)} ways "
                            f"(~{round(_est_per_tp, 4)} < min {settings.min_lot_size}). "
                            f"Consolidating to {num_tps} TP(s). Dropped TPs: {dropped}"
                        )

            # ── MULTI-ENTRY (scale-in) planning ─────────────────────────────────
            # When the signal carries discrete entry legs (e.g. SELL @4081 + MORE @4091),
            # build one order per (leg,TP) pair. leg_indices/tp_indices tag each order for
            # per-leg trade recording. Otherwise this stays a pure multi-TP trade (leg=1).
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

            # Distribute lot size across orders using integer-unit arithmetic.
            # Simple equal-split rounding (e.g. 0.04 / 3 = 0.0133) collapses every
            # slice to the minimum lot; instead we distribute whole step-units and
            # assign any remainder to the first orders.
            try:
                _spec = await self.get_symbol_specification(signal.symbol)
                _step = _spec.get('volumeStep', 0.01)
                _vmin = _spec.get('volumeMin', 0.01)
            except Exception as e:
                _step = 0.01
                _vmin = 0.01
                logger.warning(f"⚠️ {signal.symbol}: broker volume spec unavailable — splitting the lot "
                               f"with step/min 0.01; the broker may reject slices if its real minimum is higher: {e}")
            # Equal-risk distribution for multi-entry legs, or integer-unit split for single-entry/range
            if leg_targets and signal.stop_loss and signal.entry_price:
                ref_dist = abs(float(signal.entry_price) - float(signal.stop_loss))
                equal_risk_lots = []
                for leg_px in leg_targets:
                    leg_dist = abs(float(leg_px) - float(signal.stop_loss))
                    if leg_dist > 1e-6 and ref_dist > 1e-6:
                        raw_leg_lot = (risk_assessment.calculated_lot_size / num_orders) * (ref_dist / leg_dist)
                        rounded_leg_lot = max(_vmin, round(round(raw_leg_lot / _step) * _step, 2))
                        equal_risk_lots.append(rounded_leg_lot)
                    else:
                        equal_risk_lots.append(_vmin)
                if len(equal_risk_lots) == num_orders:
                    lot_sizes = equal_risk_lots
            else:
                _total_units = round(risk_assessment.calculated_lot_size / _step)
                _base = _total_units // num_orders
                _rem = _total_units % num_orders
                lot_sizes = [
                    max(_vmin, round((_base + (1 if i >= num_orders - _rem else 0)) * _step, 2))
                    for i in range(num_orders)
                ]

            # Get current price (MetaAPI-style: always fetch live price first)
            current_price_data = await self.get_symbol_price(signal.symbol)
            current_price = current_price_data['ask'] if is_buy else current_price_data['bid']

            logger.info(f"🎯 Executing {'multi-entry' if leg_targets else 'multi-TP'} trade with {num_orders} order(s)")
            logger.info(f"   Total lot size: {risk_assessment.calculated_lot_size}")
            logger.info(f"   Lot distribution across {num_orders} order(s): {lot_sizes} (total={sum(lot_sizes):.2f})")
            
            # Multi-entry legs take precedence over range/single-entry distribution.
            has_range = (not leg_targets
                        and hasattr(signal, 'entry_range_min') and signal.entry_range_min and
                        hasattr(signal, 'entry_range_max') and signal.entry_range_max)
            if leg_targets:
                logger.info(f"🪜 Entry legs (per order): {leg_targets}")
            elif has_range:
                logger.info(f"📊 Entry Range: {signal.entry_range_max} - {signal.entry_range_min}")
            elif signal.entry_price:
                logger.info(f"📊 Entry Price: {signal.entry_price}")
            else:
                logger.info("📊 Entry: Market")

            logger.info(f"✅ Stop Loss VERIFIED: {signal.stop_loss}")

            # SMART RANGE-BASED DISTRIBUTION
            # Calculate entry prices for each order
            entry_prices = []

            if leg_targets:
                # Each order's entry is its leg price. Fill as MARKET when the live price
                # is already at/through the leg (better fill available now), or when Leg 1
                # is an instant execution ("NOW") leg, else a pending LIMIT waiting for price.
                for i, leg_price in enumerate(leg_targets):
                    if is_buy:
                        is_hit_or_better = current_price <= leg_price
                    else:
                        is_hit_or_better = current_price >= leg_price

                    is_instant_leg = (order_leg_idx[i] == 1 and self._instant_applies(signal))
                    if is_hit_or_better or is_instant_leg:
                        dev = abs(current_price - leg_price)
                        max_dev = self._instant_deviation(signal)
                        if is_instant_leg and not is_hit_or_better and dev > max_dev:
                            level = self.instant_one_leg_entry(
                                is_buy, current_price, [leg_price],
                                signal.stop_loss, tp_levels, self._instant_one_leg_progress(),
                            )
                            if level is None:
                                logger.info(f"   ⏳ Leg {order_leg_idx[i]} ({leg_price}): beyond instant deviation/progress → LIMIT")
                                entry_prices.append(('LIMIT', leg_price))
                                continue
                        logger.success(f"   ✅ Leg {order_leg_idx[i]} ({leg_price}): {'instant leg ' if is_instant_leg and not is_hit_or_better else ''}current {current_price} → MARKET")
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
                logger.info("� No entry specified: All MARKET orders")
                entry_prices = [('MARKET', current_price) for _ in range(num_tps)]

            # An explicit STOP order is a breakout entry: it waits at its level. Without this a
            # BUY STOP above the market was filled at once as a 'better price' — far from its
            # level and right on top of its SL (simulated 2026-11-12).
            if (signal.signal_type in (SignalType.BUY_STOP, SignalType.SELL_STOP) and signal.entry_price
                    and not leg_targets and not has_range):
                logger.info(f"📌 STOP order: {num_tps} pending {signal.signal_type.value} order(s) at {signal.entry_price}")
                entry_prices = [('STOP', signal.entry_price) for _ in range(num_tps)]

            # Instant ("NOW") signal with no level reached → nearest level fills at
            # market within the deviation cap; the other levels stay limits.
            if (self._instant_applies(signal) and entry_prices
                    and not any(kind == 'MARKET' for kind, _ in entry_prices)):
                chase = self.instant_market_entry(
                    is_buy, current_price, [px for _, px in entry_prices],
                    self._instant_deviation(signal), signal.stop_loss, tp_levels,
                )
                if chase is not None:
                    logger.info(f"🚀 INSTANT: nearest level {chase} not reached, current {current_price} within cap → MARKET")
                    entry_prices = [
                        ('MARKET', current_price) if abs(px - chase) < 1e-9 else (kind, px)
                        for kind, px in entry_prices
                    ]
                else:
                    # Beyond the cap: one order still goes in so a fast signal isn't missed.
                    level = self.instant_one_leg_entry(
                        is_buy, current_price, [px for _, px in entry_prices],
                        signal.stop_loss, tp_levels, self._instant_one_leg_progress(),
                    )
                    if level is None:
                        logger.info(f"🚀 INSTANT: current {current_price} beyond cap / SL / TP / chase limit → keeping LIMIT orders")
                    else:
                        at_level = [j for j, (_, px) in enumerate(entry_prices) if abs(px - level) < 1e-9]
                        # The runner: chasing used up TP1's room first, the furthest target keeps the most.
                        j = (max if is_buy else min)(at_level, key=lambda k: float(tp_levels[k]))
                        scaled = self.same_risk_volume(lot_sizes[j], level, current_price, signal.stop_loss, _step, _vmin)
                        logger.info(
                            f"🚀 INSTANT: current {current_price} beyond the cap for {level} → order {j + 1} "
                            f"(TP {tp_levels[j]}) at MARKET, {lot_sizes[j]} → {scaled} lots for the same risk; "
                            f"the other order(s) stay LIMIT")
                        entry_prices[j] = ('MARKET', current_price)
                        lot_sizes[j] = scaled

            # Copy Master Mode: wait for master RUNNING, then enter all TPs at market.
            has_limit_orders = any(kind == 'LIMIT' for kind, _ in entry_prices)
            if has_limit_orders and settings.copy_master_mode:
                direction_str = "BUY" if is_buy else "SELL"
                cm_state, cm_pos = await copy_master_service.master_live_state(signal.symbol, direction_str)
                if cm_state == CM_RUNNING and cm_pos:
                    master_sl = float(cm_pos.get("sl") or 0) or signal.stop_loss
                    master_tp_raw = cm_pos.get("tp") or 0
                    master_tp_first = float(master_tp_raw) if master_tp_raw else None
                    logger.info(f"copy_master multi-TP: {signal.symbol} {direction_str} master RUNNING — "
                                f"entering {num_tps} lots at market sl={master_sl}")
                    signal.stop_loss = master_sl
                    if master_tp_first:
                        signal.take_profit = [master_tp_first]
                        tp_levels = [master_tp_first]
                        num_tps = 1
                        num_orders = 1
                        lot_sizes = lot_sizes[:1]
                        order_leg_idx = order_leg_idx[:1]
                        order_tp_idx = order_tp_idx[:1]
                    entry_prices = [('MARKET', current_price) for _ in range(num_tps)]
                else:
                    fallback_entry = signal.entry_price or current_price
                    intent_key = f"{signal.symbol}:{direction_str}"
                    _sl_ref      = signal.stop_loss
                    _tps_ref     = list(tp_levels)
                    _lots_ref    = list(lot_sizes)
                    _sym_ref     = resolved
                    _magic_ref   = base_magic_number
                    _chan_ref     = signal.channel_id
                    _ntps_ref    = num_tps
                    _entry_ref   = fallback_entry

                    async def _execute_multi_later(msl, mtp,
                                                    _lots=_lots_ref, _sym=_sym_ref,
                                                    _magic=_magic_ref, _chan=_chan_ref,
                                                    _tps=_tps_ref, _ntps=_ntps_ref,
                                                    _is_buy=is_buy, _entry=_entry_ref):
                        pids = []
                        for idx, tp_lv in enumerate(_tps, 1):
                            lot_here = _lots[idx - 1] if idx - 1 < len(_lots) else _lots[-1]
                            body = {
                                "symbol": _sym,
                                "volume": float(lot_here),
                                "type": "BUY" if _is_buy else "SELL",
                                "deviation": int(settings.slippage_pips),
                                "magic": int(_magic or 0),
                                "comment": f"Bot TP{idx}/{_ntps} from {_chan}",
                                "sl": float(msl) if msl else None,
                                "tp": float(mtp or tp_lv),
                            }
                            try:
                                res = await self._post("/order", body)
                                order_res = res.get("result", {})
                                pid = str(order_res.get("order", order_res.get("deal", "")))
                                if pid:
                                    pids.append(pid)
                            except Exception as ex:
                                logger.warning("copy_master multi-TP: TP%d failed: %s", idx, ex)
                        self._positions_cache = None
                        self._orders_cache = None
                        return TradeResult(success=bool(pids), position_id=pids[0] if pids else None,
                                           entry_price=_entry)

                    await copy_master_service.register_intent(intent_key, {
                        "symbol": signal.symbol,
                        "direction": direction_str,
                        "stop_loss": _sl_ref,
                        "take_profit": _tps_ref,
                        "execute_fn": _execute_multi_later,
                    })
                    logger.info("copy_master: %s multi-TP queued — master %s, no limits placed",
                                intent_key, cm_state)
                    return TradeResult(
                        success=True,
                        position_id=f"COPY_MASTER_WAIT:{intent_key}",
                        entry_price=fallback_entry,
                        error_message=f"copy_master: waiting for master ({cm_state})",
                    )

            results = []
            position_ids = []
            order_ids = []

            for i, (tp_level, (order_type, entry_price)) in enumerate(zip(tp_levels, entry_prices), 1):
                lot_here = lot_sizes[i - 1]
                leg_no = order_leg_idx[i - 1]
                tp_no = order_tp_idx[i - 1]
                logger.info(f"📤 Executing order {i}/{num_orders} (leg {leg_no}, TP{tp_no}): Type={order_type}, Entry={entry_price:.2f}, Target={tp_level}, Lot={lot_here}")
                try:
                    comment = self._generate_random_comment()

                    # Execute based on order type (MARKET or LIMIT)
                    if order_type == 'MARKET':
                        # Execute as market order
                        body = {
                            "symbol": resolved,
                            "volume": float(lot_here),
                            "type": "BUY" if is_buy else "SELL",
                            "deviation": int(settings.slippage_pips),
                            "magic": int(base_magic_number or 0),
                            "comment": comment,
                            "sl": float(signal.stop_loss) if signal.stop_loss else None,
                            "tp": float(tp_level),
                        }
                        res = await self._post("/order", body)
                    else:  # LIMIT
                        # Place pending limit order at the specific entry_price
                        if order_type == 'STOP':
                            order_signal_type = SignalType.BUY_STOP if is_buy else SignalType.SELL_STOP
                        else:
                            order_signal_type = SignalType.BUY_LIMIT if is_buy else SignalType.SELL_LIMIT
                        body = self._build_pending_order_body(
                            resolved, lot_here, order_signal_type, entry_price,
                            signal.stop_loss, tp_level, base_magic_number, comment,
                        )
                        res = await self._post("/limit_order", body)
                    order_result = res.get("result", {})
                    
                    # CRITICAL FIX: Save ALL IDs returned by backend
                    order_id, position_id, deal_id = order_tickets(order_result)
                    
                    # CRITICAL: Normalize the result to include both orderId and positionId
                    # so trading_service.py can properly save each order's unique ID.
                    # tpLevel/entryLeg/entryPrice let recording tag each per-leg trade.
                    normalized_result = {
                        **order_result,
                        "orderId": order_id,
                        "positionId": position_id,
                        "dealId": deal_id,
                        "tpLevel": tp_no,
                        "entryLeg": leg_no,
                        "entryPrice": entry_price,
                        "lotSize": lot_here,  # this order's volume, not the signal total
                    }
                    results.append(normalized_result)
                    if order_id:
                        order_ids.append(order_id)
                    if position_id:
                        position_ids.append(position_id)
                    logger.success(f"   ✅ Order {i} (leg {leg_no}, TP{tp_no}) executed: order_id={order_id}, position_id={position_id}, deal_id={deal_id}")
                except Exception as tp_err:
                    logger.error(f"   ❌ TP{i} failed: {tp_err}")
                    results.append({"error": str(tp_err)})

            success_count = sum(1 for r in results if "error" not in r)
            if success_count > 0:
                return TradeResult(
                    success=True,
                    position_id=position_ids[0] if position_ids else None,
                    order_id=order_ids[0] if order_ids else None,
                    entry_price=signal.entry_price,
                    broker_response={
                        "multi_tp": True,
                        "tp_count": num_tps,
                        "order_count": num_orders,
                        "multi_entry": bool(leg_targets),
                        "success_count": success_count,
                        "position_ids": position_ids,
                        "order_ids": order_ids,
                        "individual_results": results,
                    },
                )
            # CRITICAL FIX: Include individual_results even when all fail
            # This allows trading_service.py to mark each trade as FAILED
            return TradeResult(
                success=False,
                error_message=f"All {num_orders} order(s) failed",
                broker_response={
                    "multi_tp": True,
                    "tp_count": num_tps,
                    "order_count": num_orders,
                    "multi_entry": bool(leg_targets),
                    "success_count": 0,
                    "position_ids": position_ids,
                    "order_ids": order_ids,
                    "individual_results": results,
                }
            )
        except Exception as e:
            logger.error(f"❌ Multi-TP execution failed (MT5 REST): {e}")
            return TradeResult(success=False, error_message=str(e))

    # ── Positions ────────────────────────────────────────────────────────

    @with_rate_limit_handling()
    async def get_open_positions(self, use_cache: bool = True) -> List[dict]:
        self.positions_ok = True
        # Verify connection before fetching positions
        if not await self._verify_connection():
            self.positions_ok = False  # read failed - callers must not infer closures from this
            return []

        # Writes invalidate by setting the cache to None, not its time: within the
        # TTL that read as "no positions" (a partial close then found nothing to
        # move to breakeven).
        if (use_cache and self._positions_cache is not None
                and self._cache_valid(self._positions_cache_time, self._positions_cache_ttl)):
            return self._positions_cache

        try:
            raw_list = await asyncio.wait_for(
                self._get("/get_positions"),
                timeout=30.0  # 30 second timeout
            )
            # API returns a list directly
            if isinstance(raw_list, dict):
                raw_list = raw_list.get("positions", raw_list.get("data", []))
            positions = [self._normalize_position(p) for p in raw_list]
            self._positions_cache = positions
            self._positions_cache_time = datetime.now().timestamp()
            return positions
        except asyncio.TimeoutError:
            if self._positions_cache is not None:
                logger.warning("⚠️ Timeout fetching positions - using cached data")
                return self._positions_cache
            logger.error("❌ Timeout fetching positions (30s)")
            self.positions_ok = False  # read failed - callers must not infer closures from this
            return []
        except Exception as e:
            if is_rate_limit_error(e):
                cached = await position_cache.get_positions()
                if cached is not None:
                    logger.info(f"📦 Using cached positions ({len(cached)} items)")
                    return cached
                logger.warning("⚠️ No cached positions available")
            elif is_timeout_error(e):
                cached = await position_cache.get_positions()
                if cached is not None:
                    logger.info(f"📦 Using cached positions ({len(cached)} items)")
                    return cached
                logger.warning("⚠️ No cached positions available")
            logger.error(f"❌ Failed to fetch positions: {e}")
            if self._positions_cache is not None:
                return self._positions_cache
            self.positions_ok = False  # read failed - callers must not infer closures from this
            return []

    async def fetch_mirror_snapshot(self) -> dict:
        """See BaseTradingProvider.fetch_mirror_snapshot — raises, never degrades.

        The bridge answers /get_positions with [] both when the account is flat
        AND when mt5.positions_get() fails (mt5/app/lib.py), so an empty list
        alone proves nothing. It is only trusted when account_info agrees: with
        no open positions, used margin and floating profit must both be zero.
        account_info is read AFTER positions so a close landing between the two
        calls errs towards "inconsistent" (retry next poll), never towards a
        false flat.
        """
        health = await asyncio.wait_for(self._get("/health"), timeout=10.0)
        if not health.get("mt5_connected"):
            raise Exception("MT5 terminal is not connected to the trade server")

        raw_positions = await asyncio.wait_for(self._get("/get_positions"), timeout=15.0)
        raw_orders = await asyncio.wait_for(self._get("/get_orders"), timeout=15.0)
        account = await asyncio.wait_for(self._get("/account_info"), timeout=10.0)

        if isinstance(raw_positions, dict):
            raw_positions = raw_positions.get("positions", raw_positions.get("data"))
        if isinstance(raw_orders, dict):
            raw_orders = raw_orders.get("orders", raw_orders.get("data"))
        if not isinstance(raw_positions, list) or not isinstance(raw_orders, list):
            raise Exception("MT5 REST API returned a malformed positions/orders payload")
        if not account or not account.get("login"):
            raise Exception("MT5 REST API returned no account login")

        if not raw_positions:
            margin = abs(float(account.get("margin") or 0.0))
            floating = abs(float(account.get("profit") or 0.0))
            if margin > 0.0 or floating > 0.005:
                raise Exception(
                    f"Inconsistent snapshot: 0 positions but margin={margin} profit={floating}"
                )

        return {
            "account": account,
            "positions": [self._normalize_position(p) for p in raw_positions],
            "orders": [self._normalize_order(o) for o in raw_orders],
        }

    async def get_positions_by_magic(
        self, magic_number: int, use_cache: bool = True
    ) -> List[dict]:
        all_pos = await self.get_open_positions(use_cache=use_cache)
        return [
            p for p in all_pos
            if p.get("magic") == magic_number
            or p.get("clientId") == str(magic_number)
        ]

    @with_rate_limit_handling()
    async def close_position(
        self, position_id: str, volume: Optional[float] = None
    ) -> Any:
        if settings.dry_run:
            # Dry run must cover trade management too, not only new orders.
            logger.warning(f"🧪 DRY RUN — not sent: close {position_id} volume={volume or 'full'}")
            return {"success": True, "dry_run": True}
        # Verify connection before closing position
        if not await self._verify_connection():
            raise Exception("MT5 REST API not connected")

        # Look up position details
        positions = await self.get_open_positions(use_cache=True)
        position = next((p for p in positions if p.get("id") == position_id), None)

        if not position:
            # Refresh cache and retry
            self._positions_cache = None
            positions = await self.get_open_positions(use_cache=False)
            position = next((p for p in positions if p.get("id") == position_id), None)

        if not position:
            raise Exception(f"Position {position_id} not found")

        pos_body = {
            "ticket": int(position["_raw_ticket"]),
            "type": 0 if position["type"] == "POSITION_TYPE_BUY" else 1,
            "symbol": position["symbol"],
            "volume": position["volume"],
        }

        try:
            if volume and volume < position["volume"]:
                logger.info(f"🔒 Partially closing position {position_id}: {volume} lots")
                result = await asyncio.wait_for(
                    self._post("/close_partial", {
                        "position": pos_body,
                        "volume": volume,
                    }),
                    timeout=30.0  # 30 second timeout
                )
            else:
                logger.info(f"🔒 Closing position {position_id} (full close)")
                result = await asyncio.wait_for(
                    self._post("/close_position", {"position": pos_body}),
                    timeout=30.0  # 30 second timeout
                )
            
            # Invalidate caches after position change
            await position_cache.invalidate_positions()
            self._positions_cache = None
            
            logger.success(f"✅ Position {position_id} closed")
            return result
        except asyncio.TimeoutError:
            logger.error(f"❌ Timeout closing position {position_id}")
            raise Exception(f"Timeout closing position {position_id}")
        except Exception as e:
            if is_rate_limit_error(e):
                logger.error(f"❌ Rate limit closing position {position_id}")
                raise Exception(f"Rate limit closing position {position_id}")
            logger.error(f"❌ Failed to close position: {e}")
            raise

    @with_rate_limit_handling()
    async def modify_position(
        self,
        position_id: str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> Any:
        if settings.dry_run:
            # Dry run must cover trade management too, not only new orders.
            logger.warning(f"🧪 DRY RUN — not sent: modify {position_id} SL {stop_loss} TP {take_profit}")
            return {"success": True, "dry_run": True}
        # Verify connection before modifying position
        if not await self._verify_connection():
            raise Exception("MT5 REST API not connected")

        body: dict = {"position": int(position_id)}
        if stop_loss is not None:
            body["sl"] = stop_loss
        if take_profit is not None:
            body["tp"] = take_profit

        try:
            result = await asyncio.wait_for(
                self._post("/modify_sl_tp", body),
                timeout=30.0  # 30 second timeout
            )
            
            # Invalidate caches after modification
            await position_cache.invalidate_positions()
            self._positions_cache = None
            
            logger.success(f"✅ Position {position_id} modified")
            return result
        except MT5BridgeError as e:
            if e.retcode == RETCODE_NO_CHANGES:
                logger.info(f"ℹ️ Position {position_id} already has SL {stop_loss} / TP {take_profit}")
                return {"unchanged": True}
            logger.error(f"❌ Failed to modify position {position_id}: {e}")
            raise
        except asyncio.TimeoutError:
            logger.error(f"❌ Timeout modifying position {position_id}")
            raise Exception(f"Timeout modifying position {position_id}")
        except Exception as e:
            if is_rate_limit_error(e):
                logger.error(f"❌ Rate limit modifying position {position_id}")
                raise Exception(f"Rate limit modifying position {position_id}")
            logger.error(f"❌ Failed to modify position: {e}")
            raise

    # ── Pending orders ───────────────────────────────────────────────────

    @with_rate_limit_handling()
    async def get_all_pending_orders(self, use_cache: bool = True) -> List[dict]:
        self.orders_ok = True
        # Verify connection before fetching orders
        if not await self._verify_connection():
            self.orders_ok = False  # read failed - callers must not infer closures from this
            return []

        if (use_cache and self._orders_cache is not None
                and self._cache_valid(self._orders_cache_time, self._orders_cache_ttl)):
            return self._orders_cache

        try:
            raw_list = await asyncio.wait_for(
                self._get("/get_orders"),
                timeout=30.0  # 30 second timeout
            )
            # API returns a list directly
            if isinstance(raw_list, dict):
                raw_list = raw_list.get("orders", raw_list.get("data", []))
            orders = [self._normalize_order(o) for o in raw_list]
            self._orders_cache = orders
            self._orders_cache_time = datetime.now().timestamp()
            return orders
        except asyncio.TimeoutError:
            if self._orders_cache is not None:
                logger.warning("⚠️ Timeout fetching orders - using cached data")
                return self._orders_cache
            logger.error("❌ Timeout fetching orders (30s)")
            self.orders_ok = False  # read failed - callers must not infer closures from this
            return []
        except Exception as e:
            if is_rate_limit_error(e):
                cached = await position_cache.get_all_orders()
                if cached is not None:
                    logger.info(f"📦 Using cached orders ({len(cached)} items)")
                    return cached
                logger.warning("⚠️ No cached orders available")
            elif is_timeout_error(e):
                cached = await position_cache.get_all_orders()
                if cached is not None:
                    logger.info(f"📦 Using cached orders ({len(cached)} items)")
                    return cached
                logger.warning("⚠️ No cached orders available")
            logger.error(f"❌ Failed to fetch orders: {e}")
            if self._orders_cache is not None:
                return self._orders_cache
            self.orders_ok = False  # read failed - callers must not infer closures from this
            return []

    @with_rate_limit_handling()
    async def get_orders_by_magic(self, magic_number: int) -> List[dict]:
        """Return pending orders filtered by magic number."""
        # Verify connection before fetching orders
        if not await self._verify_connection():
            return []

        try:
            all_orders = await self.get_all_pending_orders()
            all_orders = all_orders or []
            # Filter orders by magic number
            filtered_orders = [
                order for order in all_orders 
                if order.get('magic') == magic_number
            ]
            return filtered_orders
        except Exception as e:
            logger.error(f"❌ Failed to filter orders by magic {magic_number}: {e}")
            return []

    @with_rate_limit_handling()
    async def cancel_order(self, order_id: str) -> Any:
        if settings.dry_run:
            # Dry run must cover trade management too, not only new orders.
            logger.warning(f"🧪 DRY RUN — not sent: cancel order {order_id}")
            return {"success": True, "dry_run": True}
        # Verify connection before cancelling order
        if not await self._verify_connection():
            raise Exception("MT5 REST API not connected")

        try:
            logger.info(f"❌ Cancelling pending order {order_id}")
            result = await asyncio.wait_for(
                self._post("/cancel_order", {"ticket": int(order_id)}),
                timeout=30.0  # 30 second timeout
            )
            
            # Invalidate orders cache after cancellation
            await position_cache.invalidate_orders()
            self._orders_cache = None
            
            logger.success(f"✅ Order {order_id} cancelled")
            return result
        except asyncio.TimeoutError:
            logger.error(f"❌ Timeout cancelling order {order_id}")
            raise Exception(f"Timeout cancelling order {order_id}")
        except Exception as e:
            if is_rate_limit_error(e):
                logger.error(f"❌ Rate limit cancelling order {order_id}")
                raise Exception(f"Rate limit cancelling order {order_id}")
            # Retcode 10013 = order no longer exists in MT5 (already filled/expired/cancelled)
            # Treat as success — the order is gone either way
            if "10013" in str(e) or "retcode=10013" in str(e).lower():
                logger.warning(f"⚠️ Order {order_id} not found in MT5 (already filled/expired) — treating as cancelled")
                return None
            logger.error(f"❌ Failed to cancel order: {e}")
            raise

    @with_rate_limit_handling()
    async def modify_order(
        self,
        order_id: str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        price: Optional[float] = None
    ) -> Any:
        """Modify a pending order's SL/TP and optionally price"""
        if settings.dry_run:
            # Dry run must cover trade management too, not only new orders.
            logger.warning(f"🧪 DRY RUN — not sent: modify order {order_id} SL {stop_loss} TP {take_profit} price {price}")
            return {"success": True, "dry_run": True}
        # Verify connection before modifying order
        if not await self._verify_connection():
            raise Exception("MT5 REST API not connected")

        body: dict = {"ticket": int(order_id)}
        if stop_loss is not None:
            body["sl"] = stop_loss
        if take_profit is not None:
            body["tp"] = take_profit
        if price is not None:
            body["price"] = price

        try:
            result = await asyncio.wait_for(
                self._post("/modify_order", body),
                timeout=30.0  # 30 second timeout
            )
            
            # Invalidate caches after modification
            await position_cache.invalidate_orders()
            self._orders_cache = None
            
            logger.success(f"✅ Pending order {order_id} modified")
            return result
        except MT5BridgeError as e:
            if e.retcode == RETCODE_NO_CHANGES:
                logger.info(f"ℹ️ Pending order {order_id} already has these values")
                return {"unchanged": True}
            logger.error(f"❌ Failed to modify order {order_id}: {e}")
            raise
        except asyncio.TimeoutError:
            logger.error(f"❌ Timeout modifying order {order_id}")
            raise Exception(f"Timeout modifying order {order_id}")
        except Exception as e:
            if is_rate_limit_error(e):
                logger.error(f"❌ Rate limit modifying order {order_id}")
                raise Exception(f"Rate limit modifying order {order_id}")
            logger.error(f"❌ Failed to modify order: {e}")
            raise

    async def place_market_order(
        self, symbol: str, is_buy: bool, volume: float,
        stop_loss: Optional[float], take_profit: Optional[float],
        magic: int, comment: str,
    ) -> dict:
        """One market order with an exact volume; returns the MT5 order_send result."""
        if settings.dry_run:
            logger.warning(f"🧪 DRY RUN — not sent: market {'BUY' if is_buy else 'SELL'} {volume} {symbol}")
            return {"dry_run": True, "order": 0, "price": 0, "volume": volume}
        body: dict = {
            "symbol": symbol,
            "volume": float(volume),
            "type": "BUY" if is_buy else "SELL",
            "deviation": int(settings.slippage_pips),
            "magic": int(magic or 0),
            "comment": comment,
        }
        if stop_loss:
            body["sl"] = float(stop_loss)
        if take_profit:
            body["tp"] = float(take_profit)
        logger.info(f"📤 Sending market order payload: {body}")
        result = await asyncio.wait_for(self._post("/order", body), timeout=30.0)
        await position_cache.invalidate_positions()
        self._positions_cache = None
        return result.get("result", {}) if isinstance(result, dict) else {}

    async def place_pending_order(
        self, symbol: str, order_type: str, volume: float, price: float,
        stop_loss: Optional[float], take_profit: Optional[float],
        magic: int, comment: str,
    ) -> dict:
        """One pending order (BUY_LIMIT / SELL_LIMIT / BUY_STOP / SELL_STOP); returns the MT5 result."""
        if settings.dry_run:
            logger.warning(f"🧪 DRY RUN — not sent: {order_type} {volume} {symbol} @ {price}")
            return {"dry_run": True, "order": 0}
        body = self._build_pending_order_body(
            symbol, volume, SignalType(order_type), price, stop_loss, take_profit, magic, comment)
        logger.info(f"📤 Sending pending order payload: {body}")
        result = await asyncio.wait_for(self._post("/limit_order", body), timeout=30.0)
        await position_cache.invalidate_orders()
        self._orders_cache = None
        return result.get("result", {}) if isinstance(result, dict) else {}

    # ── Combined queries ─────────────────────────────────────────────────

    async def get_all_trades_by_magic(
        self, magic_number: int, use_cache: bool = True
    ) -> dict:
        positions = await self.get_positions_by_magic(magic_number, use_cache=use_cache)
        orders = await self.get_orders_by_magic(magic_number)
        return {
            "positions": positions,
            "orders": orders,
            "total_count": len(positions) + len(orders),
        }

    # ── History ──────────────────────────────────────────────────────────

    async def get_deals_by_position(
        self,
        position_id: str,
        symbol: Optional[str] = None,
        from_date: Optional[str] = None,
    ) -> List[dict]:
        """
        Get exit deals for a position.

        Args:
            position_id: MT5 position ticket.
            symbol: Filter by symbol (prevents position-ID reuse contamination).
            from_date: ISO date string for the start of the search window.
                       Defaults to 30 days ago.  Using a narrow window avoids
                       pulling in deals from old, unrelated trades that happen
                       to share the same reused position ID.
        """
        # Verify connection before fetching deals
        if not await self._verify_connection():
            return []

        try:
            if not from_date:
                from_date = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

            params = {
                "from_date": from_date,
                "to_date": datetime.now(timezone.utc).isoformat(),
                "position": int(position_id),
            }
            # Pass symbol to prevent position-ID reuse contamination
            if symbol:
                params["symbol"] = symbol

            data = await self._get("/history_deals_get", params=params)
            if isinstance(data, list):
                deals = data
            else:
                deals = data.get("deals", [])

            # Filter for exit deals and normalize
            exit_deals = []
            for d in deals:
                entry = d.get("entry", 0)
                if entry == 1:  # DEAL_ENTRY_OUT
                    exit_deals.append({
                        "positionId": position_id,
                        "profit": float(d.get("profit", 0)),
                        "commission": float(d.get("commission", 0)),
                        "swap": float(d.get("swap", 0)),
                        "volume": float(d.get("volume", 0)),
                        "price": float(d.get("price", 0)),
                        "time": d.get("time"),
                        "entryType": "DEAL_ENTRY_OUT",
                        "symbol": d.get("symbol"),
                        "reason": d.get("reason"),   # MT5 DEAL_REASON_* (4=SL, 5=TP, 0-3=manual/expert)
                        "comment": d.get("comment"),
                    })
            return exit_deals
        except Exception as e:
            logger.error(f"❌ Failed to fetch deal history: {e}")
            return []

    async def get_closed_trades_by_magic(
        self, magic_number: int, days_back: int = 30
    ) -> List[dict]:
        """
        Search closed trade history by magic number via /trade_search.
        Returns list of closed trade summaries with position_id, status, profit, etc.
        Used to detect trades that executed + closed while the bot was offline.
        """
        if not await self._verify_connection():
            return []
        try:
            from datetime import timezone as _tz
            to_dt = datetime.now(_tz.utc)
            from_dt = to_dt - timedelta(days=days_back)
            data = await self._get("/trade_search", params={
                "magic": magic_number,
                "from_date": from_dt.isoformat(),
                "to_date": to_dt.isoformat(),
            })
            return data.get("trades", [])
        except Exception as e:
            logger.debug(f"get_closed_trades_by_magic failed for magic {magic_number}: {e}")
            return []

    async def get_historical_candles(
        self,
        symbol: str,
        timeframe: str = '1h',
        start_time: Optional[datetime] = None,
        limit: int = 100
    ) -> Optional[List[dict]]:
        """
        Fetch historical OHLC candle data from MT5 via REST API.

        Uses the existing /fetch_data_pos endpoint with Redis caching.
        """
        if not await self._verify_connection():
            logger.warning("MT5 REST API not connected, cannot fetch candles")
            return None

        try:
            # Resolve symbol to broker-specific format
            resolved_symbol = await self.resolve_symbol(symbol)
            
            # Try to get from cache first
            from src.services.candle_cache_service import get_candle_cache_service
            cache_service = await get_candle_cache_service()
            
            cached_candles = await cache_service.get_cached_candles(
                resolved_symbol, timeframe, limit
            )
            if cached_candles:
                return cached_candles
            
            # Map timeframe string to MT5 REST API format
            timeframe_map = {
                '1m': 'M1',
                '5m': 'M5',
                '15m': 'M15',
                '30m': 'M30',
                '1h': 'H1',
                '4h': 'H4',
                '1d': 'D1',
                '1w': 'W1',
                '1M': 'MN1',
            }
            mt5_timeframe = timeframe_map.get(timeframe, 'H1')
            
            # Call existing MT5 REST API endpoint
            data = await self._get("/fetch_data_pos", params={
                "symbol": resolved_symbol,
                "timeframe": mt5_timeframe,
                "num_bars": limit
            })
            
            if not data or not isinstance(data, list) or len(data) == 0:
                logger.warning(f"No candle data received for {resolved_symbol}")
                return None
            
            candles = data
            logger.debug(f"Retrieved {len(candles)} candles for {resolved_symbol}")
            
            # Normalize candle format to match MetaAPI structure
            normalized_candles = []
            for candle in candles:
                normalized_candles.append({
                    "time": candle.get("time"),
                    "open": float(candle.get("open", 0)),
                    "high": float(candle.get("high", 0)),
                    "low": float(candle.get("low", 0)),
                    "close": float(candle.get("close", 0)),
                    "volume": int(candle.get("tick_volume", 0))
                })
            
            # Cache the normalized candles
            await cache_service.cache_candles(
                resolved_symbol, timeframe, limit, normalized_candles
            )
            
            return normalized_candles
            
        except Exception as e:
            logger.error(f"Error fetching candles from MT5 REST API: {e}")
            return None

    # ── Trade lifecycle ───────────────────────────────────────────────────

    async def get_trade_status(self, ticket: str) -> Optional[dict]:
        """
        Call /trade_status to get the definitive lifecycle status of a ticket.

        Returned dict always contains:
            ticket, status, is_open
        And optionally:
            total_profit, symbol, type, price_open, price_current, sl, tp, volume
        Returns None on connection error or if the API returns an error.
        """
        if not await self._verify_connection():
            return None
        try:
            data = await asyncio.wait_for(
                self._get("/trade_status", params={"ticket": int(ticket)}),
                timeout=10.0,
            )
            if "error" in data:
                logger.debug(f"trade_status error for {ticket}: {data['error']}")
                return None
            return data
        except asyncio.TimeoutError:
            logger.warning(f"⚠️ Timeout calling /trade_status for ticket {ticket}")
            return None
        except Exception as e:
            logger.debug(f"get_trade_status failed for {ticket}: {e}")
            return None

    async def get_batch_trade_status(self, tickets: List[str]) -> Optional[List[dict]]:
        """
        Call /trade_batch_status to get lifecycle status for multiple tickets in one request.

        Returns list of status dicts (same shape as get_trade_status per ticket),
        or None on error.
        """
        if not tickets:
            return []
        if not await self._verify_connection():
            return None
        try:
            int_tickets = [int(t) for t in tickets]
            data = await asyncio.wait_for(
                self._post("/trade_batch_status", json_body={"tickets": int_tickets}),
                timeout=15.0,
            )
            if "error" in data:
                logger.debug(f"trade_batch_status error: {data['error']}")
                return None
            return data.get("results", [])
        except asyncio.TimeoutError:
            logger.warning(f"⚠️ Timeout calling /trade_batch_status for {len(tickets)} ticket(s)")
            return None
        except Exception as e:
            logger.debug(f"get_batch_trade_status failed: {e}")
            return None

    async def get_trade_lifecycle(
        self,
        ticket: str,
        days_back: int = 30
    ) -> Optional[dict]:
        """
        Call /trade_lifecycle to get complete trade history with accurate profit calculation.

        This API returns the full lifecycle including:
        - All deals (entry and exit)
        - Order history
        - Position info
        - Summary with accurate net_pnl

        Args:
            ticket: MT5 position/order ticket
            days_back: Number of days to search back for history

        Returns:
            Dict with keys: deals, order_history, pending_order, position, status, summary
            or None on error.
        """
        if not await self._verify_connection():
            return None
        try:
            data = await asyncio.wait_for(
                self._get("/trade_lifecycle", params={"ticket": int(ticket), "days_back": days_back}),
                timeout=15.0,
            )
            if "error" in data:
                logger.debug(f"trade_lifecycle error for ticket {ticket}: {data['error']}")
                return None
            return data
        except asyncio.TimeoutError:
            logger.warning(f"⚠️ Timeout calling /trade_lifecycle for ticket {ticket}")
            return None
        except Exception as e:
            logger.debug(f"get_trade_lifecycle failed for ticket {ticket}: {e}")
            return None

    # ── Private helpers ──────────────────────────────────────────────────

    def _is_buy_signal(self, signal_or_type) -> bool:
        from src.models import OrderType
        if hasattr(signal_or_type, "order_type") and signal_or_type.order_type:
            return signal_or_type.order_type == OrderType.BUY
        if hasattr(signal_or_type, "signal_type") and signal_or_type.signal_type:
            return signal_or_type.signal_type in [
                SignalType.BUY, SignalType.BUY_LIMIT, SignalType.BUY_STOP,
            ]
        if isinstance(signal_or_type, SignalType):
            return signal_or_type in [
                SignalType.BUY, SignalType.BUY_LIMIT, SignalType.BUY_STOP,
            ]
        return False

    @staticmethod
    def _build_pending_order_body(
        symbol: str, volume: float, signal_type: SignalType,
        price: float, sl: float, tp: Optional[float],
        magic: Optional[int], comment: str,
    ) -> dict:
        type_map = {
            SignalType.BUY_LIMIT: "BUY_LIMIT",
            SignalType.SELL_LIMIT: "SELL_LIMIT",
            SignalType.BUY_STOP: "BUY_STOP",
            SignalType.SELL_STOP: "SELL_STOP",
        }

        # ── TP direction validation ──────────────────────────────────────
        # For SELL orders: TP must be BELOW entry price (profit when price drops)
        # For BUY orders:  TP must be ABOVE entry price (profit when price rises)
        is_sell = signal_type in (SignalType.SELL_LIMIT, SignalType.SELL_STOP)
        is_buy = signal_type in (SignalType.BUY_LIMIT, SignalType.BUY_STOP)
        validated_tp = tp

        if tp is not None and price:
            if is_sell and float(tp) >= float(price):
                logger.error(
                    f"🚨 INVALID TP DIRECTION for {signal_type.value}: "
                    f"TP ({tp}) is ABOVE entry ({price}) — must be BELOW for SELL. "
                    f"Stripping TP to avoid 400 rejection. Symbol={symbol}, magic={magic}"
                )
                validated_tp = None
            elif is_buy and float(tp) <= float(price):
                logger.error(
                    f"🚨 INVALID TP DIRECTION for {signal_type.value}: "
                    f"TP ({tp}) is BELOW entry ({price}) — must be ABOVE for BUY. "
                    f"Stripping TP to avoid 400 rejection. Symbol={symbol}, magic={magic}"
                )
                validated_tp = None

        # ── SL direction validation (warn only) ─────────────────────────
        if sl and price:
            if is_sell and float(sl) <= float(price):
                logger.warning(
                    f"⚠️ Suspicious SL for {signal_type.value}: "
                    f"SL ({sl}) <= entry ({price}). SL should be ABOVE entry for SELL."
                )
            elif is_buy and float(sl) >= float(price):
                logger.warning(
                    f"⚠️ Suspicious SL for {signal_type.value}: "
                    f"SL ({sl}) >= entry ({price}). SL should be BELOW entry for BUY."
                )

        body: dict = {
            "symbol": symbol,
            "volume": float(volume),
            "type": type_map.get(signal_type, "BUY_LIMIT"),
            "price": float(price),
            "magic": int(magic or 0),
            "comment": comment,
            "type_filling": "ORDER_FILLING_RETURN",  # Required for pending orders
            "sl": float(sl) if sl else None,
        }
        if validated_tp:
            body["tp"] = float(validated_tp)
        return body

    # ── Protection Status ────────────────────────────────────────────────
    
    @with_rate_limit_handling()
    async def get_protection_status(self) -> Optional[dict]:
        """
        Get protection status from MT5 REST API.
        
        Returns protection data including:
        - daily_starting_value: Today's opening equity
        - peak_equity: All-time peak equity
        - daily_drawdown_pct: Drawdown from today's start
        - total_drawdown_pct: Drawdown from peak
        - max_daily_loss_pct: Daily drawdown threshold
        - max_total_drawdown_pct: Total drawdown threshold
        
        Returns:
            dict with protection status or None if unavailable
        """
        try:
            session = await self._ensure_session()
            url = f"{self._base_url}/protection/status"
            
            logger.debug(f"Fetching protection status from {url}")
            
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    logger.debug(
                        f"📊 Protection status: "
                        f"Daily DD: {data.get('daily_drawdown_pct', 0):.2f}%, "
                        f"Total DD: {data.get('total_drawdown_pct', 0):.2f}%"
                    )
                    return data
                elif resp.status == 404:
                    # Protection endpoint not available
                    logger.debug("Protection endpoint not available (404)")
                    return None
                else:
                    text = await resp.text()
                    logger.warning(f"Protection status returned {resp.status}: {text}")
                    return None
                    
        except aiohttp.ClientError as e:
            logger.debug(f"Failed to fetch protection status: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching protection status: {e}")
            return None
    
    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _count_unique_signals(positions: list) -> int:
        if not positions:
            return 0
        unique_magics: set = set()
        no_magic = 0
        for p in positions:
            magic = p.get("magic")
            if magic and magic != 0:
                unique_magics.add(magic)
            else:
                no_magic += 1
        return len(unique_magics) + no_magic
