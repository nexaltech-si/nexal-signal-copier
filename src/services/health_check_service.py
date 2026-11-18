"""
Health Check Service - Non-blocking monitoring of bot components
Runs parallel checks without affecting bot performance
"""

import asyncio
import logging
import json
from datetime import datetime
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class ComponentHealth:
    """Health status of a single component"""
    name: str
    status: str  # 'healthy', 'degraded', 'unhealthy', 'unknown'
    message: str
    last_check: str
    response_time_ms: Optional[float] = None
    details: Optional[Dict[str, Any]] = None
    uptime: Optional[str] = None  # System uptime (e.g., "2h 30m")


class HealthCheckService:
    """
    Non-blocking health monitoring service
    Runs checks in parallel without impacting bot performance
    """
    
    def __init__(self):
        self.running = False
        self.check_task: Optional[asyncio.Task] = None
        self.check_interval = 15  # Check every 15 seconds for real-time monitoring
        self.startup_grace_period = 90  # Suppress warnings for first 90 seconds
        self.start_time: Optional[datetime] = None
        
        # Store latest health status
        self.health_status: Dict[str, ComponentHealth] = {}
        self.last_full_check: Optional[datetime] = None
        
        # Component references (set during initialization)
        self.prisma_client = None
        self.trading_provider = None
        self.telethon_listener = None
        self.notification_sender = None
        
        logger.info("HealthCheckService initialized")
    
    def set_components(self, **components):
        """
        Set component references for health checks
        
        Args:
            prisma_client: Prisma database client
            trading_provider: Trading provider instance (MetaAPI or MT5REST)
            telethon_listener: Telethon listener instance
            notification_sender: Notification sender instance
        """
        for key, value in components.items():
            setattr(self, key, value)
        logger.info(f"Health check components configured: {', '.join(components.keys())}")
    
    def _format_uptime(self) -> str:
        """Format uptime as human-readable string"""
        if not self.start_time:
            return "N/A"
        
        uptime_seconds = (datetime.now() - self.start_time).total_seconds()
        
        if uptime_seconds < 60:
            return f"{int(uptime_seconds)}s"
        elif uptime_seconds < 3600:
            minutes = int(uptime_seconds / 60)
            return f"{minutes}m"
        elif uptime_seconds < 86400:
            hours = int(uptime_seconds / 3600)
            minutes = int((uptime_seconds % 3600) / 60)
            return f"{hours}h {minutes}m"
        else:
            days = int(uptime_seconds / 86400)
            hours = int((uptime_seconds % 86400) / 3600)
            return f"{days}d {hours}h"
    
    async def check_database(self) -> ComponentHealth:
        """Check Prisma database connection"""
        start = asyncio.get_event_loop().time()
        
        try:
            if not self.prisma_client:
                return ComponentHealth(
                    name="Database",
                    status="unknown",
                    message="Database client not configured",
                    last_check=datetime.now().isoformat()
                )
            
            # Try a simple query
            count = await self.prisma_client.client.tradingsession.count()
            
            response_time = (asyncio.get_event_loop().time() - start) * 1000
            
            return ComponentHealth(
                name="Database",
                status="healthy",
                message="Database connection active",
                last_check=datetime.now().isoformat(),
                response_time_ms=round(response_time, 2),
                details={"session_count": count}
            )
        except Exception as e:
            response_time = (asyncio.get_event_loop().time() - start) * 1000
            return ComponentHealth(
                name="Database",
                status="unhealthy",
                message=f"Database error: {str(e)[:100]}",
                last_check=datetime.now().isoformat(),
                response_time_ms=round(response_time, 2)
            )
    
    def _get_provider_name(self) -> str:
        """Get human-readable trading provider name."""
        try:
            from config import settings
            if settings.trading_provider.lower().strip() == "mt5rest":
                return "MT5 REST API"
        except Exception as _exc:
            logger.debug(f"Suppressed exception: {_exc!r}")
        return "MetaAPI"

    async def check_trading_provider(self) -> ComponentHealth:
        """Check trading provider connection (MetaAPI or MT5 REST API)"""
        provider_name = self._get_provider_name()
        start = asyncio.get_event_loop().time()
        
        try:
            if not self.trading_provider:
                return ComponentHealth(
                    name=provider_name,
                    status="unknown",
                    message=f"{provider_name} not configured (may be disabled)",
                    last_check=datetime.now().isoformat()
                )
            
            # For MT5 REST API, check the health endpoint directly (no cache fallback)
            if provider_name == "MT5 REST API" and hasattr(self.trading_provider, '_get'):
                try:
                    health_data = await asyncio.wait_for(
                        self.trading_provider._get("/health"),
                        timeout=5.0
                    )
                    response_time = (asyncio.get_event_loop().time() - start) * 1000
                    
                    mt5_connected = health_data.get("mt5_connected", False)
                    
                    if mt5_connected:
                        return ComponentHealth(
                            name=provider_name,
                            status="healthy",
                            message=f"{provider_name} connected",
                            last_check=datetime.now().isoformat(),
                            response_time_ms=round(response_time, 2),
                            details={
                                "mt5_connected": True
                            }
                        )
                    else:
                        return ComponentHealth(
                            name=provider_name,
                            status="unhealthy",
                            message="REST API up but MT5 terminal disconnected",
                            last_check=datetime.now().isoformat(),
                            response_time_ms=round(response_time, 2)
                        )
                except Exception as e:
                    response_time = (asyncio.get_event_loop().time() - start) * 1000
                    return ComponentHealth(
                        name=provider_name,
                        status="unhealthy",
                        message=f"{provider_name} unreachable: {str(e)[:80]}",
                        last_check=datetime.now().isoformat(),
                        response_time_ms=round(response_time, 2)
                    )
            
            # For MetaAPI or fallback, use get_account_info with no cache
            account_info = await asyncio.wait_for(
                self.trading_provider.get_account_info(use_cache=False),
                timeout=10.0
            )
            
            response_time = (asyncio.get_event_loop().time() - start) * 1000
            
            return ComponentHealth(
                name=provider_name,
                status="healthy",
                message=f"{provider_name} connected",
                last_check=datetime.now().isoformat(),
                response_time_ms=round(response_time, 2),
                details={
                    "balance": account_info.balance,
                    "equity": account_info.equity
                }
            )
        except asyncio.TimeoutError:
            return ComponentHealth(
                name=provider_name,
                status="degraded",
                message=f"{provider_name} response timeout (>10s)",
                last_check=datetime.now().isoformat(),
                response_time_ms=10000.0
            )
        except Exception as e:
            response_time = (asyncio.get_event_loop().time() - start) * 1000
            return ComponentHealth(
                name=provider_name,
                status="unhealthy",
                message=f"{provider_name} error: {str(e)[:100]}",
                last_check=datetime.now().isoformat(),
                response_time_ms=round(response_time, 2)
            )
    
    async def check_telegram(self) -> ComponentHealth:
        """Check Telegram listener connection"""
        start = asyncio.get_event_loop().time()
        
        try:
            if not self.telethon_listener:
                return ComponentHealth(
                    name="Telegram",
                    status="unknown",
                    message="Telegram listener not configured",
                    last_check=datetime.now().isoformat()
                )
            
            # Check if client exists
            if not self.telethon_listener.client:
                return ComponentHealth(
                    name="Telegram",
                    status="degraded",
                    message="Telegram client initializing",
                    last_check=datetime.now().isoformat(),
                    response_time_ms=round((asyncio.get_event_loop().time() - start) * 1000, 2)
                )
            
            # Not logged in / login in progress: report it, and don't probe the client
            # (a login started from the dashboard swaps it out).
            auth_state = getattr(self.telethon_listener, "auth_state", "live")
            if auth_state != "live":
                messages = {
                    "starting": ("degraded", "Telegram connecting"),
                    "logged_out": ("unhealthy", "Telegram not logged in — log in from Connections"),
                    "code_sent": ("degraded", "Telegram login in progress (waiting for code)"),
                    "password_required": ("degraded", "Telegram login in progress (waiting for 2FA password)"),
                    "error": ("unhealthy", self.telethon_listener.auth_error or "Telegram listener failed to start"),
                }
                status, message = messages.get(auth_state, ("unknown", f"Telegram state: {auth_state}"))
                return ComponentHealth(
                    name="Telegram",
                    status=status,
                    message=message,
                    last_check=datetime.now().isoformat(),
                    response_time_ms=round((asyncio.get_event_loop().time() - start) * 1000, 2)
                )
            
            # Check basic connection status
            is_connected = self.telethon_listener.client.is_connected()
            
            # IMPORTANT: Only check authorization if connected
            # Don't interfere with auth flow by calling get_me() during authentication
            try:
                if is_connected:
                    # Check if authorized (this won't interfere if already logged in)
                    is_authorized = await asyncio.wait_for(
                        self.telethon_listener.client.is_user_authorized(),
                        timeout=2.0
                    )
                    
                    if is_authorized:
                        # Only get user info if fully authorized
                        try:
                            me = await asyncio.wait_for(
                                self.telethon_listener.client.get_me(),
                                timeout=3.0
                            )
                            response_time = (asyncio.get_event_loop().time() - start) * 1000
                            
                            return ComponentHealth(
                                name="Telegram",
                                status="healthy",
                                message=f"Telegram active ({me.first_name})",
                                last_check=datetime.now().isoformat(),
                                response_time_ms=round(response_time, 2),
                                details={"username": me.username or "none"}
                            )
                        except Exception:
                            # Authorized but can't get info - still healthy
                            return ComponentHealth(
                                name="Telegram",
                                status="healthy",
                                message="Telegram authorized",
                                last_check=datetime.now().isoformat(),
                                response_time_ms=round((asyncio.get_event_loop().time() - start) * 1000, 2)
                            )
                    else:
                        # Connected but not authorized - probably authenticating
                        return ComponentHealth(
                            name="Telegram",
                            status="degraded",
                            message="Telegram authenticating (waiting for code)",
                            last_check=datetime.now().isoformat(),
                            response_time_ms=round((asyncio.get_event_loop().time() - start) * 1000, 2)
                        )
                else:
                    return ComponentHealth(
                        name="Telegram",
                        status="degraded",
                        message="Telegram client disconnected",
                        last_check=datetime.now().isoformat(),
                        response_time_ms=round((asyncio.get_event_loop().time() - start) * 1000, 2)
                    )
            except asyncio.TimeoutError:
                return ComponentHealth(
                    name="Telegram",
                    status="degraded",
                    message="Telegram check timeout",
                    last_check=datetime.now().isoformat(),
                    response_time_ms=round((asyncio.get_event_loop().time() - start) * 1000, 2)
                )
                
        except Exception as e:
            response_time = (asyncio.get_event_loop().time() - start) * 1000
            # Don't mark as unhealthy during auth - could just be initializing
            return ComponentHealth(
                name="Telegram",
                status="degraded",
                message=f"Telegram check error: {str(e)[:50]}",
                last_check=datetime.now().isoformat(),
                response_time_ms=round(response_time, 2)
            )
    
    async def check_notifications(self) -> ComponentHealth:
        """Check notification service"""
        start = asyncio.get_event_loop().time()
        
        try:
            if not self.notification_sender:
                return ComponentHealth(
                    name="Notifications",
                    status="unknown",
                    message="Notification sender not configured",
                    last_check=datetime.now().isoformat()
                )
            
            # Check if notification sender is initialized
            is_healthy = hasattr(self.notification_sender, 'bot_sender') and self.notification_sender.bot_sender is not None
            
            response_time = (asyncio.get_event_loop().time() - start) * 1000
            
            if is_healthy:
                return ComponentHealth(
                    name="Notifications",
                    status="healthy",
                    message="Notification service active",
                    last_check=datetime.now().isoformat(),
                    response_time_ms=round(response_time, 2)
                )
            else:
                return ComponentHealth(
                    name="Notifications",
                    status="degraded",
                    message="Notification service not fully initialized",
                    last_check=datetime.now().isoformat(),
                    response_time_ms=round(response_time, 2)
                )
        except Exception as e:
            response_time = (asyncio.get_event_loop().time() - start) * 1000
            return ComponentHealth(
                name="Notifications",
                status="unhealthy",
                message=f"Notification error: {str(e)[:100]}",
                last_check=datetime.now().isoformat(),
                response_time_ms=round(response_time, 2)
            )
    
    async def check_news_monitor(self) -> ComponentHealth:
        """Check the news filter feed: service running and the Faireconomy cache fresh."""
        now = datetime.now()
        try:
            from src.services import news_service
            svc = news_service.news_trading_service
            if svc is None:
                return ComponentHealth(
                    name="News Monitor",
                    status="unknown",
                    message="News service not initialized",
                    last_check=now.isoformat()
                )
            if not svc.enable_news_filter:
                return ComponentHealth(
                    name="News Monitor",
                    status="healthy",
                    message="News filter disabled in settings",
                    last_check=now.isoformat(),
                    details={"enabled": False}
                )
            if not svc.is_running:
                return ComponentHealth(
                    name="News Monitor",
                    status="degraded",
                    message="News filter enabled but its monitor is not running",
                    last_check=now.isoformat()
                )

            # The feed is fetched weekly (Monday) or when the cache runs out of
            # current-week events, so staleness is the service's own test, not age.
            # The cache file's mtime is when it was last fetched.
            import os
            try:
                age_h = (now.timestamp() - os.path.getmtime(svc.news_cache_file)) / 3600
            except OSError:
                age_h = None
            details = {"events": len(svc.news_cache), "cache_age_hours": round(age_h, 1) if age_h is not None else None}

            if age_h is None or not svc.news_cache:
                return ComponentHealth(
                    name="News Monitor",
                    status="degraded",
                    message="No news events cached — trades are not being filtered around news",
                    last_check=now.isoformat(),
                    details=details
                )
            if svc._is_cache_stale():
                return ComponentHealth(
                    name="News Monitor",
                    status="degraded",
                    message=f"News cache has no events for the current week (fetched {age_h:.0f}h ago)",
                    last_check=now.isoformat(),
                    details=details
                )
            return ComponentHealth(
                name="News Monitor",
                status="healthy",
                message=f"{len(svc.news_cache)} events this week, fetched {age_h:.1f}h ago",
                last_check=now.isoformat(),
                details=details
            )
        except Exception as e:
            return ComponentHealth(
                name="News Monitor",
                status="unhealthy",
                message=f"News monitor error: {str(e)[:100]}",
                last_check=now.isoformat()
            )
    
    # News scraper and Forex Factory checks removed - scraping disabled due to 403 errors
    
    async def run_all_checks(self) -> Dict[str, Any]:
        """
        Run all health checks in PARALLEL
        Returns comprehensive health status
        """
        logger.debug("Running parallel health checks...")
        
        # Run all checks concurrently
        check_results = await asyncio.gather(
            self.check_database(),
            self.check_trading_provider(),
            self.check_telegram(),
            self.check_notifications(),
            self.check_news_monitor(),
            return_exceptions=True
        )
        
        # Update health status
        for result in check_results:
            if isinstance(result, ComponentHealth):
                self.health_status[result.name] = result
            elif isinstance(result, Exception):
                logger.error(f"Health check error: {result}")
        
        self.last_full_check = datetime.now()
        
        # Calculate overall status
        statuses = [health.status for health in self.health_status.values()]
        if "unhealthy" in statuses:
            overall_status = "unhealthy"
        elif "degraded" in statuses:
            overall_status = "degraded"
        elif "unknown" in statuses:
            overall_status = "partial"
        else:
            overall_status = "healthy"
        
        health_data = {
            "overall_status": overall_status,
            "last_check": self.last_full_check.isoformat() if self.last_full_check else None,
            "components": {name: asdict(health) for name, health in self.health_status.items()},
            "summary": {
                "total": len(self.health_status),
                "healthy": sum(1 for h in self.health_status.values() if h.status == "healthy"),
                "degraded": sum(1 for h in self.health_status.values() if h.status == "degraded"),
                "unhealthy": sum(1 for h in self.health_status.values() if h.status == "unhealthy"),
                "unknown": sum(1 for h in self.health_status.values() if h.status == "unknown")
            }
        }
        
        # Save to database for dashboard
        await self._save_to_database(health_data)
        
        return health_data
    
    async def _save_to_database(self, health_data: Dict[str, Any]):
        """Save health status to database for dashboard access"""
        try:
            if not self.prisma_client:
                return
            
            # Delete old health records (keep only latest)
            await self.prisma_client.client.systemhealth.delete_many()
            
            # Create new health record
            await self.prisma_client.client.systemhealth.create(
                data={
                    "overallStatus": health_data["overall_status"],
                    "lastCheck": datetime.fromisoformat(health_data["last_check"]),
                    "components": json.dumps(health_data["components"]),
                    "totalComponents": health_data["summary"]["total"],
                    "healthyComponents": health_data["summary"]["healthy"],
                    "degradedComponents": health_data["summary"]["degraded"],
                    "unhealthyComponents": health_data["summary"]["unhealthy"],
                    "unknownComponents": health_data["summary"]["unknown"]
                }
            )
            logger.debug("Health status saved to database")
        except Exception as e:
            logger.error(f"Failed to save health status to database: {e}")
    
    async def monitor_loop(self):
        """Background monitoring loop - runs checks periodically"""
        logger.info("🏥 Health check monitor started")
        
        while self.running:
            try:
                # Run all checks in parallel
                health_status = await self.run_all_checks()
                
                # Check if we're in startup grace period
                in_grace_period = False
                if self.start_time:
                    elapsed = (datetime.now() - self.start_time).total_seconds()
                    in_grace_period = elapsed < self.startup_grace_period
                
                # Log summary
                summary = health_status['summary']
                logger.info(
                    f"🏥 Health Check: {health_status['overall_status'].upper()} "
                    f"({summary['healthy']}/{summary['total']} healthy)"
                )
                
                # Only log unhealthy/degraded components after grace period
                if not in_grace_period:
                    for name, health in self.health_status.items():
                        if health.status in ['unhealthy', 'degraded']:
                            logger.warning(f"⚠️  {name}: {health.status.upper()} - {health.message}")
                else:
                    # During grace period, only log unhealthy (not degraded)
                    for name, health in self.health_status.items():
                        if health.status == 'unhealthy':
                            logger.warning(f"⚠️  {name}: {health.status.upper()} - {health.message}")
                
                # Wait before next check
                await asyncio.sleep(self.check_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in health check loop: {e}", exc_info=True)
                await asyncio.sleep(self.check_interval)
    
    async def trigger_immediate_check(self, component_name: Optional[str] = None):
        """
        Trigger an immediate health check (for real-time error detection)
        
        Args:
            component_name: Optional specific component to check, or None for all
        """
        try:
            if component_name:
                # Check only specific component
                logger.debug(f"Triggering immediate health check for {component_name}")
                if component_name == "Database":
                    result = await self.check_database()
                elif component_name in ["MetaAPI", "MT5 REST API"]:
                    result = await self.check_trading_provider()
                elif component_name == "Telegram":
                    result = await self.check_telegram()
                elif component_name == "Notifications":
                    result = await self.check_notifications()
                elif component_name == "News Monitor":
                    result = await self.check_news_monitor()
                elif component_name == "News Scraper":
                    result = await self.check_news_scraper()
                elif component_name == "Forex Factory":
                    result = await self.check_forex_factory()
                else:
                    logger.warning(f"Unknown component: {component_name}")
                    return
                
                # Update health status
                if isinstance(result, ComponentHealth):
                    self.health_status[result.name] = result
                    self.last_full_check = datetime.now()
                    
                    # Save to database
                    health_data = {
                        "overall_status": self._calculate_overall_status(),
                        "last_check": self.last_full_check.isoformat(),
                        "components": {name: asdict(health) for name, health in self.health_status.items()},
                        "summary": self._calculate_summary()
                    }
                    await self._save_to_database(health_data)
            else:
                # Run full health check
                logger.debug("Triggering immediate full health check")
                await self.run_all_checks()
        except Exception as e:
            logger.error(f"Error in immediate health check: {e}")
    
    def _calculate_overall_status(self) -> str:
        """Calculate overall status from component statuses"""
        statuses = [health.status for health in self.health_status.values()]
        if "unhealthy" in statuses:
            return "unhealthy"
        elif "degraded" in statuses:
            return "degraded"
        elif "unknown" in statuses:
            return "partial"
        else:
            return "healthy"
    
    def _calculate_summary(self) -> Dict[str, int]:
        """Calculate summary statistics"""
        return {
            "total": len(self.health_status),
            "healthy": sum(1 for h in self.health_status.values() if h.status == "healthy"),
            "degraded": sum(1 for h in self.health_status.values() if h.status == "degraded"),
            "unhealthy": sum(1 for h in self.health_status.values() if h.status == "unhealthy"),
            "unknown": sum(1 for h in self.health_status.values() if h.status == "unknown")
        }
    
    async def start(self):
        """Start the health check service"""
        if self.running:
            logger.warning("Health check service already running")
            return
        
        self.running = True
        self.start_time = datetime.now()
        self.check_task = asyncio.create_task(self.monitor_loop())
        logger.info(f"✅ Health check service started (grace period: {self.startup_grace_period}s)")
    
    async def stop(self):
        """Stop the health check service"""
        if not self.running:
            return
        
        logger.info("Stopping health check service...")
        self.running = False
        
        if self.check_task:
            self.check_task.cancel()
            try:
                await self.check_task
            except asyncio.CancelledError:
                pass
        
        logger.info("✅ Health check service stopped")
    
    def get_current_status(self) -> Dict[str, Any]:
        """
        Get current health status (non-blocking, returns cached data)
        """
        if not self.health_status:
            return {
                "overall_status": "unknown",
                "last_check": None,
                "message": "No health checks have been performed yet"
            }
        
        statuses = [health.status for health in self.health_status.values()]
        if "unhealthy" in statuses:
            overall_status = "unhealthy"
        elif "degraded" in statuses:
            overall_status = "degraded"
        elif "unknown" in statuses:
            overall_status = "partial"
        else:
            overall_status = "healthy"
        
        # Get current uptime
        uptime_str = self._format_uptime()
        
        # Add uptime to all components
        components_with_uptime = {}
        for name, health in self.health_status.items():
            health_dict = asdict(health)
            # Set uptime if not already set
            if not health_dict.get('uptime') or health_dict['uptime'] == 'N/A':
                health_dict['uptime'] = uptime_str
            components_with_uptime[name] = health_dict
        
        return {
            "overall_status": overall_status,
            "last_check": self.last_full_check.isoformat() if self.last_full_check else None,
            "components": components_with_uptime,
            "summary": {
                "total": len(self.health_status),
                "healthy": sum(1 for h in self.health_status.values() if h.status == "healthy"),
                "degraded": sum(1 for h in self.health_status.values() if h.status == "degraded"),
                "unhealthy": sum(1 for h in self.health_status.values() if h.status == "unhealthy"),
                "unknown": sum(1 for h in self.health_status.values() if h.status == "unknown")
            }
        }


# Singleton instance
health_check_service = HealthCheckService()
