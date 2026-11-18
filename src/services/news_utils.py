"""
News Utilities - Shared functions for news and scraping services
Standardizes common operations across all news-related modules
"""

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional
import pytz
from loguru import logger


class NewsUtils:
    """Utility class for news-related operations"""
    
    # Standard timezone objects
    EST_TZ = pytz.timezone('America/New_York')
    SERVER_TZ = pytz.UTC   # used only when no TIMEZONE is configured; see server_timezone()
    UTC_TZ = timezone.utc

    @staticmethod
    def server_timezone():
        """The timezone news times are shown and grouped in: the TIMEZONE setting (default UTC)."""
        try:
            from config import settings
            return pytz.timezone((getattr(settings, "timezone", None) or "UTC").strip())
        except Exception:
            return NewsUtils.SERVER_TZ
    
    @staticmethod
    def normalize_news_event(event: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize news event data structure for consistency across services"""
        return {
            'title': event.get('title', event.get('newsTitle', '')),
            'country': event.get('country', event.get('newsCountry', '')),
            'date': event.get('date', ''),
            'impact': event.get('impact', event.get('newsImpact', '')),
            'forecast': event.get('forecast', ''),
            'previous': event.get('previous', ''),
            'actual': event.get('actual', ''),
            'time_str': event.get('time_str', '')
        }
    
    @staticmethod
    def generate_event_hash(title: str, country: str, date: str, impact: str) -> str:
        """Generate consistent hash for news events across all services"""
        # Normalize date to YYYY-MM-DD format for consistent hashing
        date_normalized = date
        if date:
            try:
                dt = datetime.fromisoformat(date.replace('Z', '+00:00'))
                date_normalized = dt.strftime('%Y-%m-%d')
            except Exception as e:
                logger.debug(f"Date normalization failed for {date!r}: {e}")
                date_normalized = date[:10]
        
        hash_string = f"{title}|{country}|{date_normalized}|{impact}"
        return hashlib.md5(hash_string.encode(), usedforsecurity=False).hexdigest()
    
    @staticmethod
    def convert_to_server_time(time_str: str, server_tz=None) -> datetime:
        """Standardized time conversion - handles various timezone formats"""
        if server_tz is None:
            server_tz = NewsUtils.server_timezone()
            
        try:
            from dateutil import parser as dateutil_parser
            parsed_time = dateutil_parser.parse(time_str)

            # If no tzinfo present, assume UTC (SQLite strips '+00:00')
            if parsed_time.tzinfo is None:
                parsed_time = parsed_time.replace(tzinfo=NewsUtils.UTC_TZ)

            return parsed_time.astimezone(server_tz)

        except ImportError:
            pass
        except Exception as e:
            logger.error(f"dateutil parse failed: {e} for: {time_str!r}", exc_info=True)

        # Fallback: manual ISO 8601 parse
        try:
            clean = time_str.replace('T', ' ').replace('Z', '+00:00')
            for fmt in ("%Y-%m-%d %H:%M:%S%z", "%Y-%m-%d %H:%M:%S"):
                try:
                    dt = datetime.strptime(clean[:19], "%Y-%m-%d %H:%M:%S")
                    if '+' in time_str[10:] or (time_str.count('-') > 2):
                        dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
                    else:
                        dt = dt.replace(tzinfo=NewsUtils.UTC_TZ)
                    return dt.astimezone(server_tz)
                except Exception as e:
                    logger.debug(f"Fallback time format failed for {time_str!r}: {e}")
                    continue
        except Exception as parse_err:
            logger.error(f"All parsing methods failed: {parse_err} for: {time_str!r}", exc_info=True)
            raise
    
    @staticmethod
    def clean_economic_value(value: str) -> Optional[str]:
        """Clean and validate economic value"""
        if not value:
            return None
        
        value = value.strip()
        
        # Skip empty or placeholder values
        if value in ['', '-', 'N/A', 'TBD', 'n/a']:
            return None
        
        return value
    
    @staticmethod
    def cleanup_old_cache_events(cache_file: str = "data/news_cache.json") -> int:
        """Remove events older than current week from cache file to keep it lean"""
        try:
            if not os.path.exists(cache_file):
                logger.debug(f"Cache file not found, skipping cleanup: {cache_file}")
                return 0
            
            # Load existing cache
            with open(cache_file, 'r') as f:
                events = json.load(f)
            
            len(events)
            
            # Calculate start of current week (Monday 00:00:00) - timezone-aware
            now = datetime.now(NewsUtils.UTC_TZ)
            start_of_week = now - timedelta(days=now.weekday())  # Go back to Monday
            start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
            
            # Filter events: keep only current week onwards
            filtered_events = []
            removed_count = 0
            
            for event in events:
                try:
                    event_date = datetime.fromisoformat(event['date'].replace('Z', '+00:00'))
                    # Ensure timezone-aware datetime
                    if event_date.tzinfo is None:
                        event_date = event_date.replace(tzinfo=NewsUtils.UTC_TZ)
                    # Keep events from start of current week onwards
                    if event_date >= start_of_week:
                        filtered_events.append(event)
                    else:
                        removed_count += 1
                except Exception as e:
                    # If date parsing fails, keep the event to be safe
                    logger.warning(f"Could not parse date for event {event.get('title')}: {e}")
                    filtered_events.append(event)
            
            # Save cleaned cache if anything was removed
            if removed_count > 0:
                with open(cache_file, 'w') as f:
                    json.dump(filtered_events, f, indent=2)
                logger.info(f"🧹 Cleaned up cache file: Removed {removed_count} old events, kept {len(filtered_events)} current week events")
            else:
                logger.debug(f"No old events to clean up (all {len(events)} events are current)")
            
            return removed_count
                
        except Exception as e:
            logger.error(f"Error cleaning up cache file: {e}")
            return 0
    
    @staticmethod
    def update_cache_json_with_actual(
        cache_file: str, 
        title: str, 
        country: str, 
        date_str: str, 
        actual_value: str
    ) -> bool:
        """Update news_cache.json file with actual value"""
        try:
            # Load existing cache
            if not os.path.exists(cache_file):
                logger.warning(f"Cache file not found: {cache_file}")
                return False
            
            with open(cache_file, 'r') as f:
                events = json.load(f)
            
            # Find and update the matching event
            updated = False
            for event in events:
                if (event.get('title') == title and 
                    event.get('country') == country and 
                    event.get('date') == date_str):
                    event['actual'] = actual_value
                    updated = True
                    logger.info(f"📝 Updated news_cache.json: {title} = {actual_value}")
                    break
            
            if updated:
                # Save back to file
                with open(cache_file, 'w') as f:
                    json.dump(events, f, indent=2)
                return True
            else:
                logger.debug(f"Event not found in cache file: {title}")
                return False
                
        except Exception as e:
            logger.error(f"Error updating cache file: {e}")
            return False
    
    @staticmethod
    def handle_error(error: Exception, context: str, reraise: bool = False) -> None:
        """Standardized error handling and logging"""
        logger.error(f"Error in {context}: {str(error)}", exc_info=True)
        if reraise:
            raise error
    
    @staticmethod
    def handle_warning(message: str, context: str = "") -> None:
        """Standardized warning logging"""
        if context:
            logger.warning(f"{context}: {message}")
        else:
            logger.warning(message)
    
    @staticmethod
    def safe_execute(func, context: str, default=None, reraise: bool = False):
        """Safely execute a function with standardized error handling"""
        try:
            return func()
        except Exception as e:
            NewsUtils.handle_error(e, context, reraise)
            return default
    
    @staticmethod
    def get_base_impact_score(impact: str) -> int:
        """Get base impact score before AI analysis"""
        impact_scores = {
            'High': 7,
            'Medium': 4,
            'Low': 2,
            'Holiday': 10  # Bank holidays close markets
        }
        return impact_scores.get(impact, 3)
    
    @staticmethod
    def parse_forex_factory_time(time_str: str, date: datetime) -> Optional[str]:
        """Parse time string and combine with date, preserving EST/EDT timezone"""
        if not time_str or time_str.strip() in ['', 'Tentative']:
            return None
        
        try:
            # Handle different time formats
            time_str = time_str.strip()
            
            # Forex Factory times are in EST/EDT (US/Eastern timezone)
            eastern = NewsUtils.EST_TZ
            
            # Handle 'All Day' events - use noon (12:00) as default
            if time_str.lower() == 'all day':
                event_datetime = datetime.combine(date.date(), datetime.min.time().replace(hour=12))
                # Localize to Eastern time and preserve timezone info
                event_datetime = eastern.localize(event_datetime)
                # Return ISO format with timezone offset (e.g., -05:00 or -04:00)
                return event_datetime.isoformat()
            
            # Parse time (e.g., "2:00am", "14:30")
            time_formats = ["%I:%M%p", "%H:%M"]
            parsed_time = None
            
            for fmt in time_formats:
                try:
                    parsed_time = datetime.strptime(time_str, fmt).time()
                    break
                except ValueError:
                    continue
            
            if parsed_time:
                # Combine date and time (naive datetime)
                event_datetime = datetime.combine(date.date(), parsed_time)
                # Localize to Eastern time (handles DST automatically)
                event_datetime = eastern.localize(event_datetime)
                # Return ISO format with timezone offset (preserves EST/EDT)
                return event_datetime.isoformat()
            
            return None
        except Exception as e:
            logger.debug(f"Could not parse time '{time_str}': {e}")
            return None


# Create singleton instance
news_utils = NewsUtils()
