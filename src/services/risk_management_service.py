"""
MetaAPI Risk Management Service
Provides equity protection for prop firm trading accounts
"""
from typing import Optional, List, Dict, Any
from loguru import logger
from metaapi_cloud_sdk import RiskManagement

from config import settings


class RiskManagementService:
    """
    Manages equity protection and risk limits using MetaAPI Risk Management API
    
    Features:
    - Daily and overall drawdown limits
    - Relative and absolute drawdown tracking
    - Profit target monitoring
    - Real-time drawdown event streaming
    - Equity chart tracking
    """
    
    def __init__(self):
        self.risk_management = None
        self.risk_management_api = None
        self.trackers = {}
        self.is_initialized = False
        self.drawdown_listeners = []  # List of (listener, listener_id) tuples
        
    async def initialize(self):
        """Initialize MetaAPI Risk Management (MetaAPI provider only)"""
        try:
            # MetaAPI Risk Management SDK only works with MetaAPI cloud provider
            if settings.trading_provider.lower().strip() == "mt5rest":
                logger.warning("⚠️  MetaAPI Risk Management SDK not available with MT5 REST provider")
                logger.info("🛡️  Use the local DrawdownProtectionService for drawdown monitoring")
                self.is_initialized = False
                return
            
            logger.info("🛡️  Initializing MetaAPI Risk Management...")
            
            # Initialize Risk Management API
            self.risk_management = RiskManagement(token=settings.metaapi_token)
            self.risk_management_api = self.risk_management.risk_management_api
            
            self.is_initialized = True
            logger.success("✅ Risk Management API initialized")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize Risk Management: {str(e)}")
            raise
    
    async def create_daily_drawdown_tracker(
        self,
        account_id: str,
        daily_limit_percent: float = 3.0,
        name: str = "Daily Drawdown Limit"
    ) -> Optional[Dict[str, Any]]:
        """
        Create a daily drawdown tracker with percentage limit
        
        Args:
            account_id: MetaAPI account ID
            daily_limit_percent: Daily loss limit as percentage (e.g., 3.0 for 3%)
            name: Tracker name
            
        Returns:
            Tracker info dict or None if failed
        """
        if not self.is_initialized:
            await self.initialize()
        
        try:
            logger.info(f"📊 Creating daily drawdown tracker: {daily_limit_percent}% limit")
            
            # Convert percentage to decimal (3% -> 0.03)
            relative_threshold = daily_limit_percent / 100.0
            
            tracker = await self.risk_management_api.create_tracker(
                account_id,
                {
                    'name': name,
                    'period': 'day',
                    'relativeDrawdownThreshold': relative_threshold
                }
            )
            
            self.trackers[tracker['id']] = tracker
            logger.success(f"✅ Daily tracker created: {tracker['id']}")
            logger.info(f"   Limit: {daily_limit_percent}% per day")
            
            return tracker
            
        except Exception as e:
            logger.error(f"❌ Failed to create daily tracker: {str(e)}")
            return None
    
    async def create_overall_drawdown_tracker(
        self,
        account_id: str,
        overall_limit_percent: float = 10.0,
        name: str = "Overall Drawdown Limit"
    ) -> Optional[Dict[str, Any]]:
        """
        Create an overall (lifetime) drawdown tracker
        
        Args:
            account_id: MetaAPI account ID
            overall_limit_percent: Overall loss limit as percentage (e.g., 10.0 for 10%)
            name: Tracker name
            
        Returns:
            Tracker info dict or None if failed
        """
        if not self.is_initialized:
            await self.initialize()
        
        try:
            logger.info(f"📊 Creating overall drawdown tracker: {overall_limit_percent}% limit")
            
            # Convert percentage to decimal (10% -> 0.10)
            relative_threshold = overall_limit_percent / 100.0
            
            tracker = await self.risk_management_api.create_tracker(
                account_id,
                {
                    'name': name,
                    'period': 'lifetime',
                    'relativeDrawdownThreshold': relative_threshold
                }
            )
            
            self.trackers[tracker['id']] = tracker
            logger.success(f"✅ Overall tracker created: {tracker['id']}")
            logger.info(f"   Limit: {overall_limit_percent}% lifetime")
            
            return tracker
            
        except Exception as e:
            logger.error(f"❌ Failed to create overall tracker: {str(e)}")
            return None
    
    async def create_comprehensive_protection(
        self,
        account_id: str,
        daily_percent: float = 3.0,
        overall_percent: float = 10.0,
        absolute_daily_limit: Optional[float] = None,
        absolute_overall_limit: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Create comprehensive equity protection with multiple trackers
        
        Args:
            account_id: MetaAPI account ID
            daily_percent: Daily loss limit percentage (default: 3%)
            overall_percent: Overall loss limit percentage (default: 10%)
            absolute_daily_limit: Optional absolute daily loss limit in account currency
            absolute_overall_limit: Optional absolute overall loss limit in account currency
            
        Returns:
            Dict with all created trackers
        """
        if not self.is_initialized:
            await self.initialize()
        
        logger.info("🛡️  Creating comprehensive equity protection...")
        logger.info(f"   Daily: {daily_percent}% | Overall: {overall_percent}%")
        
        trackers = {
            'daily_relative': None,
            'overall_relative': None,
            'daily_absolute': None,
            'overall_absolute': None
        }
        
        try:
            # 1. Daily relative drawdown tracker
            trackers['daily_relative'] = await self.create_daily_drawdown_tracker(
                account_id,
                daily_percent,
                "Daily Relative Drawdown"
            )
            
            # 2. Overall relative drawdown tracker
            trackers['overall_relative'] = await self.create_overall_drawdown_tracker(
                account_id,
                overall_percent,
                "Overall Relative Drawdown"
            )
            
            # 3. Daily absolute drawdown tracker (if specified)
            if absolute_daily_limit:
                logger.info(f"📊 Creating daily absolute tracker: ${absolute_daily_limit}")
                tracker = await self.risk_management_api.create_tracker(
                    account_id,
                    {
                        'name': 'Daily Absolute Drawdown',
                        'period': 'day',
                        'absoluteDrawdownThreshold': absolute_daily_limit
                    }
                )
                trackers['daily_absolute'] = tracker
                self.trackers[tracker['id']] = tracker
                logger.success(f"✅ Daily absolute tracker created: ${absolute_daily_limit}")
            
            # 4. Overall absolute drawdown tracker (if specified)
            if absolute_overall_limit:
                logger.info(f"📊 Creating overall absolute tracker: ${absolute_overall_limit}")
                tracker = await self.risk_management_api.create_tracker(
                    account_id,
                    {
                        'name': 'Overall Absolute Drawdown',
                        'period': 'lifetime',
                        'absoluteDrawdownThreshold': absolute_overall_limit
                    }
                )
                trackers['overall_absolute'] = tracker
                self.trackers[tracker['id']] = tracker
                logger.success(f"✅ Overall absolute tracker created: ${absolute_overall_limit}")
            
            logger.success("✅ Comprehensive equity protection activated!")
            return trackers
            
        except Exception as e:
            logger.error(f"❌ Failed to create comprehensive protection: {str(e)}")
            raise
    
    async def get_all_trackers(self, account_id: str) -> List[Dict[str, Any]]:
        """Get all trackers for an account"""
        if not self.is_initialized:
            await self.initialize()
        
        try:
            trackers = await self.risk_management_api.get_trackers(account_id)
            logger.info(f"📊 Found {len(trackers)} active trackers")
            return trackers
        except Exception as e:
            logger.error(f"❌ Failed to get trackers: {str(e)}")
            return []
    
    async def get_tracker_by_name(
        self,
        account_id: str,
        name: str
    ) -> Optional[Dict[str, Any]]:
        """Get a specific tracker by name"""
        if not self.is_initialized:
            await self.initialize()
        
        try:
            tracker = await self.risk_management_api.get_tracker_by_name(
                account_id,
                name
            )
            return tracker
        except Exception as e:
            logger.error(f"❌ Failed to get tracker '{name}': {str(e)}")
            return None
    
    async def get_drawdown_events(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        account_id: Optional[str] = None,
        tracker_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get drawdown events with optional filtering
        
        Args:
            start_time: Start broker time (format: "2024-01-01 00:00:00.000")
            end_time: End broker time
            account_id: Filter by account ID
            tracker_id: Filter by tracker ID
            
        Returns:
            List of drawdown events
        """
        if not self.is_initialized:
            await self.initialize()
        
        try:
            events = await self.risk_management_api.get_tracker_events(
                start_time,
                end_time,
                account_id,
                tracker_id
            )
            
            logger.info(f"📊 Retrieved {len(events)} drawdown events")
            return events
            
        except Exception as e:
            logger.error(f"❌ Failed to get drawdown events: {str(e)}")
            return []
    
    async def get_drawdown_statistics(
        self,
        account_id: str,
        tracker_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get drawdown statistics for a tracker"""
        if not self.is_initialized:
            await self.initialize()
        
        try:
            stats = await self.risk_management_api.get_tracking_statistics(
                account_id,
                tracker_id
            )
            
            logger.info(f"📊 Retrieved statistics for tracker {tracker_id}")
            return stats
            
        except Exception as e:
            logger.error(f"❌ Failed to get statistics: {str(e)}")
            return None
    
    async def get_equity_chart(
        self,
        account_id: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get equity chart data
        
        Args:
            account_id: MetaAPI account ID
            start_time: Optional start broker time
            end_time: Optional end broker time
            
        Returns:
            List of equity chart points
        """
        if not self.is_initialized:
            await self.initialize()
        
        try:
            chart = await self.risk_management_api.get_equity_chart(
                account_id,
                start_time,
                end_time
            )
            
            logger.info(f"📈 Retrieved equity chart: {len(chart)} data points")
            return chart
            
        except Exception as e:
            logger.error(f"❌ Failed to get equity chart: {str(e)}")
            return []
    
    async def start_drawdown_monitoring(self, account_id: str, callback=None, tracker_id: str = None):
        """
        Start real-time drawdown event monitoring
        
        Args:
            account_id: MetaAPI account ID to monitor
            callback: Optional callback function called on drawdown events
            tracker_id: Tracker ID to monitor (required)
        """
        if not self.is_initialized:
            await self.initialize()
        
        if not tracker_id:
            raise ValueError("tracker_id is required for drawdown monitoring")
        
        from metaapi_cloud_sdk import PeriodStatisticsListener
        
        class CustomPeriodStatisticsListener(PeriodStatisticsListener):
            def __init__(self, account_id: str, tracker_id: str, user_callback=None):
                super().__init__(account_id, tracker_id)
                self.user_callback = user_callback
            
            async def on_period_statistics_updated(self, period_statistics_event):
                """Called when period statistics are updated"""
                logger.warning("⚠️  PERIOD STATISTICS UPDATE DETECTED!")
                logger.warning(f"   Account: {period_statistics_event.get('accountId')}")
                logger.warning(f"   Period: {period_statistics_event.get('period')}")
                logger.warning(f"   Relative Drawdown: {period_statistics_event.get('relativeDrawdown', 0) * 100:.2f}%")
                logger.warning(f"   Absolute Drawdown: ${period_statistics_event.get('absoluteDrawdown', 0):.2f}")
                logger.warning(f"   Broker Time: {period_statistics_event.get('brokerTime')}")
                
                # Call custom callback if provided
                if self.user_callback:
                    await self.user_callback(period_statistics_event)
            
            async def on_tracker_completed(self, tracker_completed_event):
                """Called when a tracker completes"""
                logger.info("✅ Tracker completed!")
                logger.info(f"   Tracker ID: {tracker_completed_event.get('id')}")
        
        # Add listener
        listener = CustomPeriodStatisticsListener(account_id, tracker_id, callback)
        listener_id = self.risk_management_api.add_period_statistics_listener(
            listener,
            account_id,
            tracker_id
        )
        self.drawdown_listeners.append((listener, listener_id))
        
        logger.success(f"✅ Drawdown monitoring started for tracker {tracker_id}")
        return listener_id
    
    async def stop_drawdown_monitoring(self):
        """Stop real-time drawdown monitoring"""
        if self.drawdown_listeners:
            for listener, listener_id in self.drawdown_listeners:
                self.risk_management_api.remove_period_statistics_listener(listener_id)
            self.drawdown_listeners = []
            logger.info("🛑 Drawdown monitoring stopped")
    
    async def update_tracker(
        self,
        account_id: str,
        tracker_id: str,
        updates: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Update tracker configuration
        
        Args:
            account_id: MetaAPI account ID
            tracker_id: Tracker ID to update
            updates: Dict with fields to update
            
        Returns:
            Updated tracker info or None if failed
        """
        if not self.is_initialized:
            await self.initialize()
        
        try:
            logger.info(f"✏️  Updating tracker {tracker_id}")
            
            result = await self.risk_management_api.update_tracker(
                account_id,
                tracker_id,
                updates
            )
            
            logger.success(f"✅ Tracker updated: {tracker_id}")
            return result
            
        except Exception as e:
            logger.error(f"❌ Failed to update tracker: {str(e)}")
            return None
    
    async def delete_tracker(
        self,
        account_id: str,
        tracker_id: str
    ) -> bool:
        """Delete a tracker"""
        if not self.is_initialized:
            await self.initialize()
        
        try:
            logger.info(f"🗑️  Deleting tracker {tracker_id}")
            
            await self.risk_management_api.delete_tracker(
                account_id,
                tracker_id
            )
            
            if tracker_id in self.trackers:
                del self.trackers[tracker_id]
            
            logger.success(f"✅ Tracker deleted: {tracker_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to delete tracker: {str(e)}")
            return False
    
    async def check_account_safety(
        self,
        account_id: str
    ) -> Dict[str, Any]:
        """
        Check if account is within safety limits
        
        Returns:
            Dict with safety status and current drawdown levels
        """
        if not self.is_initialized:
            await self.initialize()
        
        try:
            trackers = await self.get_all_trackers(account_id)
            
            safety_status = {
                'is_safe': True,
                'trackers': [],
                'violations': []
            }
            
            for tracker in trackers:
                # Get latest statistics
                stats = await self.get_drawdown_statistics(account_id, tracker['_id'])
                
                tracker_info = {
                    'name': tracker.get('name'),
                    'period': tracker.get('period'),
                    'threshold': tracker.get('relativeDrawdownThreshold', 0) * 100,
                    'current': stats.get('relativeDrawdown', 0) * 100 if stats else 0
                }
                
                safety_status['trackers'].append(tracker_info)
                
                # Check if threshold exceeded
                if stats and stats.get('relativeDrawdown', 0) >= tracker.get('relativeDrawdownThreshold', 1.0):
                    safety_status['is_safe'] = False
                    safety_status['violations'].append(tracker_info)
            
            return safety_status
            
        except Exception as e:
            logger.error(f"❌ Failed to check account safety: {str(e)}")
            return {'is_safe': False, 'error': str(e)}


# Singleton instance
risk_management_service = RiskManagementService()
