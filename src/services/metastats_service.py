"""
MetaStats Service - Performance Analytics Integration
Tracks comprehensive account performance metrics using MetaAPI's MetaStats SDK
"""
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from metaapi_cloud_sdk import MetaStats
from loguru import logger

from config import settings


class MetaStatsService:
    """Service to fetch and manage performance metrics from MetaStats SDK"""
    
    def __init__(self):
        self._client_token = None
        self.metrics_cache = None
        self.cache_timestamp = None
        self.cache_ttl = 300  # Cache for 5 minutes
        self.metastats = None

    @property
    def token(self) -> str:
        return settings.metaapi_token

    @property
    def account_id(self) -> str:
        return settings.metaapi_account_id

    def _is_mt5rest(self) -> bool:
        """MetaStats reports the MetaAPI account, so it is only meaningful while MetaAPI is the active
        provider (MT5 REST trades a different account). True = unavailable."""
        return (settings.trading_provider.lower().strip() == "mt5rest"
                or not (settings.metaapi_token and settings.metaapi_account_id))

    def _ensure_initialized(self):
        """Lazy initialization of the MetaStats SDK client (region auto-resolved by the SDK)"""
        if self._is_mt5rest():
            raise RuntimeError("MetaStats is only available while MetaAPI is the active provider")
        if self.metastats is None or self._client_token != self.token:
            self.metastats = MetaStats(self.token)
            self._client_token = self.token
            self.clear_cache()
            logger.info("✅ MetaStats SDK initialized")

    async def get_account_metrics(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        include_open_positions: bool = True
    ) -> Dict[str, Any]:
        """
        Get comprehensive account performance metrics

        Args:
            start_time: Unused (MetaStats metrics cover the full account history)
            end_time: Unused
            include_open_positions: Whether to include open positions in calculations

        Returns:
            Dictionary containing all performance metrics
        """
        if self._is_mt5rest():
            logger.debug("📊 MetaStats unavailable (MetaAPI is not the active provider) — returning fallback")
            return self._get_fallback_metrics()

        if self._is_cache_valid():
            logger.debug("📊 Returning cached metrics")
            return self.metrics_cache

        try:
            logger.info("📊 Fetching account metrics from MetaStats SDK...")
            self._ensure_initialized()
            data = await self.metastats.get_metrics(self.account_id, include_open_positions)

            self.metrics_cache = data
            self.cache_timestamp = datetime.now()

            logger.success("✅ Fetched metrics successfully from SDK")
            return data

        except Exception as e:
            logger.error(f"❌ Failed to fetch MetaStats metrics: {str(e)}")
            return self._get_fallback_metrics()

    async def get_historical_trades(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 1000,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Get historical trades with details

        Args:
            start_time: 'YYYY-MM-DD HH:mm:ss.SSS' (default: 30 days ago)
            end_time: 'YYYY-MM-DD HH:mm:ss.SSS' (default: now)
        """
        if self._is_mt5rest():
            return {"trades": [], "total": 0}
        try:
            self._ensure_initialized()
            fmt = '%Y-%m-%d %H:%M:%S.000'
            now = datetime.utcnow()
            start = start_time or (now - timedelta(days=30)).strftime(fmt)
            end = end_time or (now + timedelta(minutes=1)).strftime(fmt)
            trades = await self.metastats.get_account_trades(
                self.account_id, start, end, True, limit, offset
            )
            return {"trades": trades or [], "total": len(trades or [])}
        except Exception as e:
            logger.error(f"❌ Failed to fetch historical trades: {str(e)}")
            return {"trades": [], "total": 0}

    async def get_open_trades(self) -> Dict[str, Any]:
        """Get currently open trades (non-billable MetaStats call)"""
        if self._is_mt5rest():
            return {"trades": []}
        try:
            self._ensure_initialized()
            trades = await self.metastats.get_account_open_trades(self.account_id)
            return {"trades": trades or []}
        except Exception as e:
            logger.error(f"❌ Failed to fetch open trades: {str(e)}")
            return {"trades": []}

    async def reset_metrics(self) -> bool:
        """
        Reset cached metrics (forces recalculation on next request)
        
        Returns:
            True if successful
        """
        try:
            logger.info("🔄 Resetting MetaStats metrics cache...")
            
            if not self._is_mt5rest():
                self._ensure_initialized()
                await self.metastats.reset_metrics(self.account_id)
            self.metrics_cache = None
            self.cache_timestamp = None
            
            logger.success("✅ MetaStats metrics reset")
            return True
                        
        except Exception as e:
            logger.error(f"❌ Failed to reset metrics: {str(e)}")
            return False
    
    def _is_cache_valid(self) -> bool:
        """Check if cached metrics are still valid"""
        if not self.metrics_cache or not self.cache_timestamp:
            return False
        
        age = (datetime.now() - self.cache_timestamp).total_seconds()
        return age < self.cache_ttl
    
    def _get_fallback_metrics(self) -> Dict[str, Any]:
        """Return fallback metrics structure when API is unavailable"""
        return {
            "error": "MetaStats API unavailable",
            "trades": 0,
            "profit": 0.0,
            "gain": 0.0,
            "drawdown": 0.0,
            "balance": 0.0,
            "equity": 0.0
        }
    
    def clear_cache(self):
        """Manually clear the local cache"""
        self.metrics_cache = None
        self.cache_timestamp = None
        logger.debug("🗑️ Local metrics cache cleared")
    
    async def get_performance_summary(self) -> Dict[str, Any]:
        """
        Get a simplified performance summary optimized for dashboard display
        
        Returns:
            Simplified metrics for dashboard
        """
        metrics = await self.get_account_metrics()
        
        if "error" in metrics:
            return metrics
        
        # Extract key metrics for dashboard
        summary = {
            # Overview
            "balance": metrics.get("balance", 0.0),
            "equity": metrics.get("equity", 0.0),
            "profit": metrics.get("profit", 0.0),
            "gain": metrics.get("gain", 0.0),
            
            # Performance
            "totalTrades": metrics.get("trades", 0),
            "wonTrades": metrics.get("wonTradesPercent", 0.0),
            "profitFactor": metrics.get("profitFactor", 0.0),
            "expectancy": metrics.get("expectancy", 0.0),
            
            # Risk
            "maxDrawdown": metrics.get("maxDrawdown", 0.0),
            "sharpeRatio": metrics.get("sharpeRatio", 0.0),
            "sortinoRatio": metrics.get("sortinoRatio", 0.0),
            
            # Growth
            "dailyGrowth": metrics.get("dailyGrowth", 0.0),
            "monthlyGrowth": metrics.get("monthlyGrowth", 0.0),
            "cagr": metrics.get("cagr", 0.0),
            
            # Detailed arrays for charts
            "dailyGrowthChart": metrics.get("dailyGrowth", []),
            "monthlyAnalytics": metrics.get("monthlyAnalytics", []),
            "currencySummary": metrics.get("currencySummary", []),
            "tradeDuration": metrics.get("tradeDuration", {}),
            
            # Timestamps
            "firstTradeDate": metrics.get("firstTradeDate"),
            "lastTradeDate": metrics.get("lastTradeDate"),
            "lastUpdateTime": datetime.now().isoformat()
        }
        
        return summary


# Global instance
metastats_service = MetaStatsService()
