"""
News Trading Service for AI Signal Executor
Monitors economic news and blocks trading during high-impact events
"""
import asyncio
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from loguru import logger
from config import settings as app_settings
from .news_utils import news_utils
from .news_message import compose_alert, group_events

class NewsTradingService:
    """Service to monitor economic news and manage trading restrictions"""
    
    def __init__(self, notification_service=None):
        self.settings = app_settings
        self.notification_service = notification_service

        # Load settings from the app settings object (DB-backed, with .env fallback)
        self._apply_settings()

        # File paths
        self.news_cache_file = "data/news_cache.json"
        self.news_blocks_file = "data/news_blocks.json"
        self.notified_events_file = "data/news_notified_events.json"
        
        # State tracking
        self.news_cache = []
        self.last_update = None
        self.last_monday_update = None  # Track last Monday 2 AM update
        # Timezone configuration - standardized
        self.est_tz = news_utils.EST_TZ
        self.server_tz = news_utils.server_timezone()
        self.utc_tz = news_utils.UTC_TZ
        self.last_notification_time = {}
        self.active_news_blocks = {}  # Track active news blocks
        self.notified_news_events = set()  # Track which news events we've already notified about (persisted to disk)
        self._refetch_needed = False  # a settings change widened the currencies the cache must hold
        
        # Monitoring task
        self.monitoring_task: Optional[asyncio.Task] = None
        self.is_running = False
        
        # Create data directory if it doesn't exist
        os.makedirs(os.path.dirname(self.news_cache_file), exist_ok=True)
        
        # Load cached data
        self.load_news_cache()
        self.load_news_blocks()
        self.load_notified_events()

        # A cache written before the channel posts were set up holds only the
        # trading filter's currencies; fetch again if the posts need others.
        extra = (self.post_currencies - self.target_currencies) if self.post_enabled else set()
        if extra and not any(n.get('country') in extra for n in self.news_cache):
            self._refetch_needed = True
        
        # Log initialization
        logger.info(f"News trading service initialized with: "
                    f"enable_filter={self.enable_news_filter}, "
                    f"minutes_before={self.minutes_before_news}, "
                    f"minutes_after={self.minutes_after_news}, "
                    f"impacts={self.important_impacts}, "
                    f"currencies={self.target_currencies}, "
                    f"notifications={self.enable_news_notifications}, "
                    f"notify_before={self.notification_minutes_before}min")

    def _apply_settings(self):
        """Pull current values from the app settings object (DB-backed, .env fallback)."""
        s = self.settings
        self.enable_news_filter = s.news_enable_filter
        self.minutes_before_news = s.news_minutes_before
        self.minutes_after_news = s.news_minutes_after
        self.important_impacts = [v.strip() for v in s.news_important_impacts.split(",") if v.strip()]
        self.target_currencies = set(v.strip() for v in s.news_target_currencies.split(",") if v.strip())
        self.news_api_url = s.news_api_url
        self.update_interval_hours = s.news_update_interval_hours
        self.verbose_logging = s.news_verbose_logging
        self.enable_news_notifications = s.news_enable_notifications
        self.notification_minutes_before = s.news_notification_minutes_before
        # Channel posts: their own filter, separate from the trading filter above
        self.post_enabled = bool(getattr(s, 'news_post_enabled', False))
        self.post_channel_id = str(getattr(s, 'news_post_channel_id', '') or '').strip()
        self.post_impacts = [v.strip() for v in str(getattr(s, 'news_post_impacts', '') or '').split(",") if v.strip()]
        self.post_currencies = set(v.strip() for v in str(getattr(s, 'news_post_currencies', '') or '').split(",") if v.strip())
        self.post_minutes_before = int(getattr(s, 'news_post_minutes_before', 30) or 30)

    @staticmethod
    def _currency_in(news: Dict, currencies) -> bool:
        country = news.get('country', '')
        return (country in currencies or (country == 'US' and 'USD' in currencies) or country == 'ALL')

    def _cached_currencies(self) -> set:
        """Currencies the calendar cache keeps: the trading filter's, plus the posts'."""
        return set(self.target_currencies) | (set(self.post_currencies) if self.post_enabled else set())

    def _is_filter_currency(self, news: Dict) -> bool:
        """Does the trading filter watch this event's currency? The cache may also
        hold currencies kept only for channel posts — those never block trading."""
        return self._currency_in(news, self.target_currencies)

    def reload_settings(self):
        """Re-apply settings after a DB settings reload so dashboard changes take effect live."""
        before = self._cached_currencies()
        self._apply_settings()
        if self._cached_currencies() - before:
            # a currency was added that the cache does not hold yet
            self._refetch_needed = True
        logger.info(f"News trading settings reloaded: "
                    f"enable_filter={self.enable_news_filter}, "
                    f"minutes_before={self.minutes_before_news}, "
                    f"minutes_after={self.minutes_after_news}, "
                    f"impacts={self.important_impacts}, "
                    f"currencies={self.target_currencies}, "
                    f"notifications={self.enable_news_notifications}, "
                    f"notify_before={self.notification_minutes_before}min")

    def log_info(self, message):
        """Conditionally log info messages based on verbose_logging setting"""
        if self.verbose_logging:
            logger.info(message)
    
    def load_news_cache(self):
        """Load news cache from a file if available."""
        try:
            if os.path.exists(self.news_cache_file):
                with open(self.news_cache_file, 'r') as file:
                    self.news_cache = json.load(file)
                self.last_update = datetime.now()
                logger.info(f"News cache loaded with {len(self.news_cache)} events")
            else:
                logger.info("No news cache found, will fetch on first update")
                self.news_cache = []
        except Exception as e:
            logger.error(f"Error loading news cache: {e}", exc_info=True)
            self.news_cache = []
    
    def load_news_blocks(self):
        """Load active news blocks from file"""
        try:
            if os.path.exists(self.news_blocks_file):
                with open(self.news_blocks_file, 'r') as file:
                    data = json.load(file)
                    # Convert string timestamps back to datetime objects
                    self.active_news_blocks = {}
                    for symbol, block_data in data.items():
                        self.active_news_blocks[symbol] = {
                            'start_time': datetime.fromisoformat(block_data['start_time']),
                            'end_time': datetime.fromisoformat(block_data['end_time']),
                            'reason': block_data['reason']
                        }
                logger.info(f"Loaded {len(self.active_news_blocks)} active news blocks")
        except Exception as e:
            logger.error(f"Error loading news blocks: {e}", exc_info=True)
            self.active_news_blocks = {}
    
    def load_notified_events(self):
        """Load persisted notified events from disk to survive restarts"""
        try:
            if os.path.exists(self.notified_events_file):
                with open(self.notified_events_file, 'r') as f:
                    data = json.load(f)
                    self.notified_news_events = set(data.get('events', []))
                logger.info(f"Loaded {len(self.notified_news_events)} persisted notified news events")
        except Exception as e:
            logger.error(f"Error loading notified events: {e}")
            self.notified_news_events = set()

    def save_notified_events(self):
        """Persist notified events to disk so restarts don't cause duplicate notifications"""
        try:
            with open(self.notified_events_file, 'w') as f:
                json.dump({'events': list(self.notified_news_events)}, f)
        except Exception as e:
            logger.error(f"Error saving notified events: {e}")

    def save_news_blocks(self):
        """Save active news blocks to file"""
        try:
            # Convert datetime objects to strings for JSON serialization
            data = {}
            for symbol, block_data in self.active_news_blocks.items():
                data[symbol] = {
                    'start_time': block_data['start_time'].isoformat(),
                    'end_time': block_data['end_time'].isoformat(),
                    'reason': block_data['reason']
                }
            
            with open(self.news_blocks_file, 'w') as file:
                json.dump(data, file, indent=2)
        except Exception as e:
            logger.error(f"Error saving news blocks: {e}")
    
    def save_news_cache(self, update_timestamp: bool = True):
        """Save news cache to a file, filtered for target currencies and current week only."""
        try:
            # Calculate start of current week (Monday 00:00:00) - use server timezone
            now = datetime.now(self.server_tz)
            start_of_week = now - timedelta(days=now.weekday())
            start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
            
            # Filter the news cache for target currencies AND current week
            filtered_news = []
            old_events_removed = 0
            
            for news in self.news_cache:
                # Check if event is for target currencies
                # ("US" is accepted for USD; "ALL" affects every currency)
                if not ('country' in news and self._currency_in(news, self._cached_currencies())):
                    continue
                
                # Check if event is from current week onwards
                try:
                    # Parse the date string properly - it comes from API with EST offset (-05:00)
                    event_date = datetime.fromisoformat(news['date'])
                    # Ensure timezone-aware datetime
                    if event_date.tzinfo is None:
                        # If no timezone info, assume EST (America/New_York)
                        event_date = self.est_tz.localize(event_date)
                    
                    # Convert to server timezone for comparison
                    event_date_server = event_date.astimezone(self.server_tz)
                    
                    if event_date_server >= start_of_week:
                        # Keep the original date string with timezone info
                        filtered_news.append(news)
                    else:
                        old_events_removed += 1
                except Exception as e:
                    logger.warning(f"UTC date parse failed for news event, keeping it: {e}", exc_info=True)
                    filtered_news.append(news)

            # Sort the filtered news by date
            filtered_news.sort(key=lambda x: x['date'])
            
            # Save the filtered news to file
            with open(self.news_cache_file, 'w') as file:
                json.dump(filtered_news, file, indent=2)
            
            self.news_cache = filtered_news  # Update the cache with filtered news
            if update_timestamp:
                self.last_update = datetime.now()
            
            logger.info(f"Saved filtered news cache with {len(filtered_news)} entries for {', '.join(self.target_currencies)}")
            if old_events_removed > 0:
                logger.info(f"🧹 Removed {old_events_removed} old events (older than current week)")
        
        except Exception as e:
            logger.error(f"Error saving news cache: {e}", exc_info=True)
    
    async def fetch_news(self, force_update: bool = False) -> bool:
        """Fetch news data from the direct API with correct timezone information.
        
        The API returns EST times with proper timezone offsets (-05:00).
        """
        try:
            import aiohttp
            import ssl
            import certifi
            
            # Check if we need to update
            current_time = datetime.now()
            if not force_update and self.last_update:
                hours_since_update = (current_time - self.last_update).total_seconds() / 3600
                if hours_since_update < self.update_interval_hours:
                    if self.verbose_logging:
                        logger.info(f"Using cached news data (last updated {hours_since_update:.1f} hours ago)")
                    return True
            
            # Create SSL context
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            
            # Fetch from API
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(self.news_api_url, ssl=ssl_context) as response:
                    if response.status == 200:
                        raw_news = await response.json()
                        
                        # Process and filter news
                        self.news_cache = []
                        for news_item in raw_news:
                            # Filter for target currencies
                            if 'country' in news_item and self._currency_in(news_item, self._cached_currencies()):
                                
                                # API dates are in EST with correct -05:00 offset
                                # e.g. 08:30:00-05:00 = 8:30 AM EST = 14:30 CET
                                # Keep as-is; convert_to_server_time handles EST→CET conversion
                                date_str = news_item.get('date', '')
                                if date_str and not self._has_timezone_offset(date_str):
                                    # If no timezone info, assume EST
                                    from dateutil import parser as dateutil_parser
                                    try:
                                        parsed_date = dateutil_parser.parse(date_str)
                                        if parsed_date.tzinfo is None:
                                            parsed_date = self.est_tz.localize(parsed_date)
                                        news_item['date'] = parsed_date.isoformat()
                                    except Exception as e:
                                        logger.warning(f"Could not parse date {date_str}: {e}")
                                        continue
                                
                                self.news_cache.append(news_item)
                        
                        # Sort by date
                        self.news_cache.sort(key=lambda x: x['date'])
                        
                        # Save to cache
                        self.save_news_cache(update_timestamp=True)
                        
                        logger.info(f"✅ Fetched {len(self.news_cache)} news events from API")
                        return True
                    else:
                        logger.error(f"Failed to fetch news: HTTP {response.status}")
                        return False
                        
        except Exception as e:
            logger.error(f"Error fetching news from API: {e}", exc_info=True)
            return False
    
    def _has_timezone_offset(self, date_str: str) -> bool:
        """Check if a date string has timezone offset information"""
        return '+' in date_str[-6:] or '-' in date_str[-6:]
    
    def _is_news_identical(self, new_news: List[Dict]) -> bool:
        """Compare new news with cached news to detect changes.
        
        Args:
            new_news: Newly fetched news data
            
        Returns:
            bool: True if news is identical, False if there are changes
        """
        try:
            # If cache is empty, news has changed
            if not self.news_cache:
                return False
            
            # Compare lengths first (quick check)
            if len(new_news) != len(self.news_cache):
                logger.info(f"News count changed: {len(self.news_cache)} -> {len(new_news)}")
                return False
            
            # Create comparable sets of news items (using title, date, country as key)
            def news_key(item):
                return (item.get('title', ''), item.get('date', ''), item.get('country', ''))
            
            cached_keys = {news_key(item) for item in self.news_cache}
            new_keys = {news_key(item) for item in new_news}
            
            # Check if there are any differences
            if cached_keys != new_keys:
                added = new_keys - cached_keys
                removed = cached_keys - new_keys
                if added:
                    logger.info(f"New news items detected: {len(added)} added")
                if removed:
                    logger.info(f"News items removed: {len(removed)} removed")
                return False
            
            # News is identical
            return True
            
        except Exception as e:
            logger.error(f"Error comparing news: {e}")
            # On error, assume news has changed to be safe
            return False
    
    async def update_news_cache_if_needed(self):
        """Update news cache if needed based on:
        1. File missing or cache empty → fetch immediately
        2. Cache stale (no current/future events) → fetch immediately
        3. Monday at 1 AM → weekly refresh
        """
        current_time = datetime.now()
        
        # If file doesn't exist or cache is empty, fetch immediately
        if not os.path.exists(self.news_cache_file) or not self.news_cache:
            logger.info("📰 News cache empty or missing. Fetching news data...")
            if await self.fetch_news(force_update=True):
                logger.success("✅ News cache populated with weekly data.")
                self.last_monday_update = current_time
            else:
                logger.warning("⚠️ Failed to fetch news. Will retry next cycle.")
            return
        
        # If cache is stale (no current/future events), fetch immediately
        if self._is_cache_stale():
            logger.info("📰 News cache is stale. Fetching fresh data...")
            if await self.fetch_news(force_update=True):
                logger.success("✅ News cache refreshed with fresh data.")
                self.last_monday_update = current_time
            else:
                logger.warning("⚠️ Failed to refresh stale cache. Will retry next cycle.")
            return
        
        # Check if it's Monday at 1 AM (weekly update ONLY)
        should_monday_update = self._should_do_monday_update(current_time)
        if should_monday_update:
            logger.info("📅 Weekly Monday 1 AM update triggered - fetching news for the week...")
            fetch_result = await self.fetch_news(force_update=True)
            if fetch_result:
                logger.success("✅ Weekly news cache updated successfully with fresh data.")
                self.last_monday_update = current_time
            else:
                logger.warning("⚠️ Weekly update failed (rate limited or API issue). Using existing cache until next Monday.")
            return
        
        # No other updates needed - using cached data until next Monday
        logger.debug("Using cached news data. Next update: Monday 1 AM")
    
    def _is_cache_stale(self) -> bool:
        """Check if the news cache contains old/stale data.
        
        Economic news events only occur on weekdays (Mon-Fri). On weekends,
        we should check if the cache covers the upcoming trading week rather
        than expecting events on Saturday or Sunday.
        
        Returns:
            bool: True if cache is stale and needs updating
        """
        try:
            if not self.news_cache:
                return True
            
            current_date = datetime.now().date()
            weekday = current_date.weekday()  # 0=Mon ... 6=Sun
            
            # On weekends, advance to next Monday — there are no economic
            # events on Saturday or Sunday, so the cache would always appear
            # stale if we check against today's date.
            if weekday >= 5:  # Saturday (5) or Sunday (6)
                days_until_monday = 7 - weekday
                current_date = current_date + timedelta(days=days_until_monday)
            
            # Check if any news events are from the current date or future
            has_current_data = False
            for news in self.news_cache:
                try:
                    news_time = self.convert_to_server_time(news['date'])
                    news_date = news_time.date()
                    
                    # If we have any news from target date or future, cache is not stale
                    if news_date >= current_date:
                        has_current_data = True
                        break
                except Exception as e:
                    logger.debug(f"Error parsing news date for staleness check: {e}")
                    continue
            
            if not has_current_data:
                logger.info("Cache is stale - no current or future news events found")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking cache staleness: {e}")
            # If we can't determine, assume it's stale to be safe
            return True
    
    def _should_do_monday_update(self, current_time: datetime) -> bool:
        """Check if we should perform the Monday 1 AM update.
        
        Args:
            current_time: Current datetime
            
        Returns:
            bool: True if it's Monday between 1:00 AM and 1:10 AM and hasn't been done this week
        """
        # Check if it's Monday (weekday 0)
        if current_time.weekday() != 0:
            return False
        
        # Check if it's between 1:00 AM and 1:10 AM (10-minute window for reliability)
        if not (1 <= current_time.hour < 2 and current_time.minute < 10):
            return False
        
        # Check if we've already done the update this week
        if self.last_monday_update:
            # If last update was less than 6 days ago, skip
            days_since_last = (current_time - self.last_monday_update).days
            if days_since_last < 6:
                return False
        
        return True
    
    def _normalize_news_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize news event data structure for consistency across services"""
        return news_utils.normalize_news_event(event)
    
    def _generate_event_hash(self, title: str, country: str, date: str, impact: str) -> str:
        """Generate consistent hash for news events across all services"""
        return news_utils.generate_event_hash(title, country, date, impact)
    
    def convert_to_server_time(self, time_str: str) -> datetime:
        """Standardized time conversion - handles various timezone formats"""
        return news_utils.convert_to_server_time(time_str, self.server_tz)
    
    def is_currency_affected(self, symbol: str, news_currency: str) -> bool:
        """Check if a symbol is affected by news for a specific currency."""
        if symbol == "XAUUSD" and news_currency in ["USD", "US"]:
            return True
        
        # Extract currencies from symbol (e.g., EURUSD -> EUR, USD)
        if len(symbol) >= 6:
            symbol_currencies = symbol[:3], symbol[3:6]
            return news_currency in symbol_currencies
        
        return False
    
    def is_trading_blocked_by_news(self, symbol: str = None) -> Tuple[bool, Optional[str]]:
        """
        Check if trading is blocked due to upcoming or ongoing news events.
        
        Args:
            symbol: Trading symbol to check (optional, if None checks general news blocks)
            
        Returns:
            Tuple[bool, Optional[str]]: (is_blocked, reason)
        """
        if not self.enable_news_filter:
            return False, None
        
        current_time = datetime.now(self.server_tz)
        
        # Clean up expired blocks first
        self._cleanup_expired_blocks(current_time)
        
        # Check symbol-specific blocks
        if symbol and symbol in self.active_news_blocks:
            block_data = self.active_news_blocks[symbol]
            if block_data['start_time'] <= current_time <= block_data['end_time']:
                return True, block_data['reason']
        
        # Check for upcoming news that should block trading
        for news in self.news_cache:
            try:
                if news['impact'] not in self.important_impacts:
                    continue
                if not self._is_filter_currency(news):
                    continue  # cached for channel posts only
                
                news_time = self.convert_to_server_time(news['date'])
                time_until_news = news_time - current_time
                minutes_until = time_until_news.total_seconds() / 60
                
                # Skip old events that are outside the blocking window
                # Only check events that are upcoming or recently passed (within after-news window)
                if minutes_until < -self.minutes_after_news:
                    self.log_info(f"Skipping old news event: {news['title']} ({news['country']}) - {abs(minutes_until):.1f} minutes ago")
                    continue
                
                # Check if we're in the blocking window (before or after news)
                if -self.minutes_after_news <= minutes_until <= self.minutes_before_news:
                    # If symbol is specified, check if this news affects it
                    if symbol:
                        if self.is_currency_affected(symbol, news['country']):
                            reason = f"{news['impact']} impact news: {news['title']} ({news['country']}) in {minutes_until:.1f} minutes"
                            return True, reason
                    else:
                        # General news block (no specific symbol)
                        reason = f"{news['impact']} impact news: {news['title']} ({news['country']}) in {minutes_until:.1f} minutes"
                        return True, reason
                        
            except Exception as e:
                logger.error(f"Error checking news event: {e}")
                continue
        
        return False, None
    
    def _cleanup_expired_blocks(self, current_time: datetime):
        """Remove expired news blocks"""
        expired_symbols = []
        for symbol, block_data in self.active_news_blocks.items():
            if current_time > block_data['end_time']:
                expired_symbols.append(symbol)
        
        for symbol in expired_symbols:
            del self.active_news_blocks[symbol]
            self.log_info(f"Removed expired news block for {symbol}")
        
        if expired_symbols:
            self.save_news_blocks()
    
    async def check_upcoming_news(self):
        """Check and log upcoming news events, send notifications for news approaching in 10 minutes."""
        if not self.enable_news_filter:
            return
            
        try:
            
            current_time = datetime.now(self.server_tz)
            upcoming_news = []
            news_to_notify = []
            
            for news in self.news_cache:
                try:
                    if news['impact'] not in self.important_impacts:
                        continue

                    # Filter by target currencies
                    news_country = news.get('country', '')
                    if not (news_country in self.target_currencies or
                            (news_country == 'US' and 'USD' in self.target_currencies) or
                            news_country == 'ALL'):
                        continue
                        
                    news_time = self.convert_to_server_time(news['date'])
                    time_until_news = news_time - current_time
                    minutes_until = time_until_news.total_seconds() / 60
                    
                    # Create unique identifier for this news event
                    news_id = f"{news['date']}_{news['title']}_{news['country']}"
                    
                    # Check for news in the next hour
                    if 0 <= minutes_until <= 60:
                        upcoming_news.append({
                            'title': news['title'],
                            'country': news['country'],
                            'impact': news['impact'],
                            'time': news_time,
                            'minutes_until': minutes_until,
                            'forecast': news.get('forecast', 'N/A'),
                            'news_id': news_id
                        })
                        
                        # Check if we should send notification.
                        # Use a 2-minute window so the 60s loop never misses the target.
                        # notified_news_events guarantees exactly ONE notification per event.
                        if (self.notification_minutes_before - 2 <= minutes_until <= self.notification_minutes_before and
                            news_id not in self.notified_news_events):
                            news_to_notify.append({
                                'title': news['title'],
                                'country': news['country'],
                                'impact': news['impact'],
                                'time': news_time,
                                'minutes_until': minutes_until,
                                'forecast': news.get('forecast', 'N/A'),
                                'previous': news.get('previous', 'N/A'),
                                'news_id': news_id
                            })
                        
                except Exception as e:
                    logger.error(f"Error processing news event: {e}")
                    continue
            
            # Sort by time until news
            upcoming_news.sort(key=lambda x: x['minutes_until'])
            
            # Log upcoming news
            if upcoming_news:
                logger.info(f"NEWS: {len(upcoming_news)} upcoming high-impact news events in the next hour:")
                for news in upcoming_news[:5]:  # Show top 5
                    logger.info(f"  - {news['title']} ({news['country']}) in {news['minutes_until']:.1f} min - {news['impact']} impact")
            
            # Send notifications for news approaching in notification window
            if news_to_notify and self.enable_news_notifications:
                await self._send_news_notifications(news_to_notify)
                self.save_notified_events()
            
        except Exception as e:
            logger.error(f"Error checking upcoming news: {e}", exc_info=True)
    
    def due_news_posts(self, current_time: datetime) -> List[Dict]:
        """Events to post to the channel now: the posts' own impact and currency
        filter, nothing to do with which news blocks trading."""
        if not (self.post_enabled and self.post_channel_id):
            return []
        due = []
        for news in self.news_cache:
            try:
                if news.get('impact') not in self.post_impacts:
                    continue
                if not self._currency_in(news, self.post_currencies):
                    continue
                news_time = self.convert_to_server_time(news['date'])
                minutes_until = (news_time - current_time).total_seconds() / 60
                # the "_POST_" id keeps posts and owner notifications apart
                post_id = f"{news['date']}_POST_{news['title']}_{news['country']}"
                # 2-minute window for the 60 s loop; the id set makes it once per event
                if (self.post_minutes_before - 2 <= minutes_until <= self.post_minutes_before
                        and post_id not in self.notified_news_events):
                    due.append({
                        'title': news['title'], 'country': news['country'], 'impact': news['impact'],
                        'time': news_time, 'minutes_until': minutes_until,
                        'forecast': news.get('forecast', 'N/A'), 'previous': news.get('previous', 'N/A'),
                        'news_id': post_id,
                    })
            except Exception as e:
                logger.error(f"Error preparing news post: {e}")
        return due

    async def check_news_posts(self):
        """Post upcoming news to the channel chosen in the dashboard."""
        try:
            due = self.due_news_posts(datetime.now(self.server_tz))
            if not due:
                return
            if not hasattr(self.notification_service, 'send_to_chat'):
                logger.warning("News posts: no sender that can post to a channel")
                return
            for group in group_events(due):
                titles = ", ".join(f"{n['title']} ({n['country']})" for n in group)
                if await self.notification_service.send_to_chat(self.post_channel_id, compose_alert(group)):
                    logger.info(f"📣 News posted to {self.post_channel_id}: {titles}")
                else:
                    logger.warning(f"News post to {self.post_channel_id} failed: {titles}")
                # marked either way: a failed post is not retried into the event itself
                for news in group:
                    self.notified_news_events.add(news['news_id'])
            self.save_notified_events()
        except Exception as e:
            logger.error(f"Error posting news to channel: {e}", exc_info=True)

    async def start_monitoring(self) -> bool:
        """Start the news monitoring service"""
        if not self.enable_news_filter:
            logger.info("News filtering is disabled")
            return False
            
        if self.is_running:
            logger.warning("News monitoring is already running")
            return True
        
        try:
            # Force initial news update on startup to ensure fresh data
            logger.info("Performing initial news cache update on startup...")
            await self.update_news_cache_if_needed()
            
            # Log cache status after update
            if self.news_cache:
                logger.info(f"News cache loaded with {len(self.news_cache)} events")
                # Show date range of cached news
                try:
                    dates = [self.convert_utc_to_server_time(n['date']) for n in self.news_cache[:5]]
                    if dates:
                        logger.info(f"First news event: {dates[0].strftime('%Y-%m-%d %H:%M')}")
                except Exception as e:
                    logger.debug(f"Error showing cache date range: {e}")
            else:
                logger.warning("News cache is empty after initial update")
            
            self.monitoring_task = asyncio.create_task(self._monitoring_loop())
            self.is_running = True
            logger.info("News monitoring started")
            return True
        except Exception as e:
            logger.error(f"Failed to start news monitoring: {e}")
            return False
    
    async def stop_monitoring(self):
        """Stop the news monitoring service"""
        if self.monitoring_task and not self.monitoring_task.done():
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass
        
        self.is_running = False
        logger.info("News trading monitoring stopped")
    
    def _cleanup_notified_events(self):
        """Clean up old notified events to prevent memory buildup"""
        try:
            current_time = datetime.now(self.server_tz)
            events_to_remove = set()
            
            for news_id in self.notified_news_events:
                # news_id format: "ISO_DATE_title_country" where ISO_DATE contains 'T'
                # Find the first occurrence of 'T' to locate the ISO date boundary
                try:
                    # The date portion is everything up to the first '_' AFTER the 'T'
                    # e.g. "2026-02-18T14:30:00+00:00_CPI_USD"
                    t_pos = news_id.find('T')
                    if t_pos == -1:
                        events_to_remove.add(news_id)  # Malformed ID, remove it
                        continue
                    # Find the '_' separator after the timestamp (after the timezone offset)
                    sep_pos = news_id.find('_', t_pos)
                    date_str = news_id[:sep_pos] if sep_pos != -1 else news_id
                    event_time = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                    
                    # Ensure timezone-aware
                    if event_time.tzinfo is None:
                        event_time = self.est_tz.localize(event_time)
                    
                    # Convert to server timezone
                    event_time = event_time.astimezone(self.server_tz)
                    
                    # Remove if event was more than 2 hours ago
                    if (current_time - event_time).total_seconds() > 7200:
                        events_to_remove.add(news_id)
                except Exception as e:
                    logger.debug(f"Error parsing news_id for cleanup: {e}, news_id: {news_id}")
                    events_to_remove.add(news_id)  # Remove unparseable IDs
                    continue
            
            # Remove old events
            for news_id in events_to_remove:
                self.notified_news_events.discard(news_id)
            
            if events_to_remove:
                logger.info(f"Cleaned up {len(events_to_remove)} old notified news events")
                self.save_notified_events()
                
        except Exception as e:
            logger.error(f"Error cleaning up notified events: {e}")
    
    async def _send_news_notifications(self, news_events: List[Dict]):
        """Send Telegram notifications for upcoming news events"""
        if not self.notification_service:
            logger.warning("Notification service not available for news alerts")
            return
        
        try:
            include_emoji = bool(getattr(self.notification_service, 'include_emoji', True))
            # Releases of one currency at the same minute go out as one message.
            for group in group_events(news_events):
                for news in group:
                    self.notified_news_events.add(news['news_id'])

                message = compose_alert(group, include_emoji=include_emoji)
                titles = ", ".join(f"{n['title']} ({n['country']})" for n in group)

                if hasattr(self.notification_service, '_send_to_channels'):
                    await self.notification_service._send_to_channels(message)
                    logger.info(f"Sent news notification for: {titles}")
                else:
                    logger.warning("Notification service doesn't support _send_to_channels method")

        except Exception as e:
            logger.error(f"Error sending news notifications: {e}")
    
    async def _monitoring_loop(self):
        """Main monitoring loop for news events"""
        check_counter = 0
        while self.is_running:
            try:
                # Update news cache if needed (Monday 1 AM weekly refresh)
                await self.update_news_cache_if_needed()
                if self._refetch_needed:
                    self._refetch_needed = not await self.fetch_news(force_update=True)
                
                # Check for upcoming news and send notifications
                await self.check_upcoming_news()

                # Channel posts run on their own filter, whether or not the trading filter is on
                await self.check_news_posts()
                
                # Clean up old notified events every 10 minutes
                if check_counter % 10 == 0:
                    self._cleanup_notified_events()
                
                # Sleep for 1 minute (allows catching Monday 1 AM window)
                await asyncio.sleep(60)
                check_counter += 1
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in news monitoring loop: {e}")
                await asyncio.sleep(60)
        
        logger.info("News monitoring loop ended")
    
    def get_status(self) -> Dict:
        """Get current news monitoring status"""
        current_time = datetime.now(self.server_tz)
        
        # Get next high-impact news
        next_news = None
        try:
            for news in self.news_cache:
                if news['impact'] in self.important_impacts and self._is_filter_currency(news):
                    news_time = self.convert_to_server_time(news['date'])
                    if news_time > current_time:
                        minutes_until = (news_time - current_time).total_seconds() / 60
                        next_news = {
                            'title': news['title'],
                            'country': news['country'],
                            'impact': news['impact'],
                            'minutes_until': minutes_until
                        }
                        break
        except Exception as e:
            logger.error(f"Error getting next news: {e}")
        
        return {
            'enabled': self.enable_news_filter,
            'running': self.is_running,
            'cache_size': len(self.news_cache),
            'last_update': self.last_update.isoformat() if self.last_update else None,
            'active_blocks': len(self.active_news_blocks),
            'next_news': next_news,
            'minutes_before': self.minutes_before_news,
            'minutes_after': self.minutes_after_news,
            'target_currencies': list(self.target_currencies),
            'important_impacts': self.important_impacts
        }
