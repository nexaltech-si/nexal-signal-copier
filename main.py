#!/usr/bin/env python3
"""
NEXAL
Automatically extracts trading signals from Telegram and executes trades via MetaAPI
"""

import asyncio
import signal as sys_signal
from datetime import datetime
from typing import Optional
from loguru import logger
from src.utils.tasks import spawn

from config import settings
from config.logging_config import configure_logging
import os
from src.integrations.telegram.listener import TelethonListener
from src.integrations.telegram.unified_sender import notification_sender
from src.services.trading_service import trading_service
from src.services.risk_management_service import risk_management_service
from src.services.drawdown_protection_service import drawdown_protection_service
from src.services.drawdown_monitor_service import drawdown_monitor_service
from src.services.position_monitor_service import position_monitor_service
from src.services import (
    initialize_news_services,
    start_news_monitoring,
    stop_news_monitoring
)
from src.services.health_check_service import health_check_service
from src.services.copy_master_service import copy_master_service
from src.core.prisma_client import prisma_client
from src.core.database_service import db_service
from src.models import TradingSignal, AccountInfo
from src.services.settings_service import get_settings_service
from ai.trading_brain import trading_brain
from src.services.telegram_channel_service_prisma import telegram_channel_service_prisma


async def start_api_server():
    """Start the Python API server in the same event loop
    Returns a uvicorn.Server that can be used to gracefully stop the server.
    """
    import uvicorn
    from src.api.api_server import app

    port = int(os.getenv("API_SERVER_PORT", "8001"))
    host = os.getenv("API_SERVER_HOST", "0.0.0.0")

    logger.info(f"🌐 Starting API server on {host}:{port}")

    config = uvicorn.Config(app, host=host, port=port, log_level="warning")

    class _NoSignalServer(uvicorn.Server):
        """Uvicorn server that does not override our SIGTERM/SIGINT handlers."""
        def install_signal_handlers(self) -> None:
            pass

    server = _NoSignalServer(config)

    # Run server as a task in the current event loop and return server for cleanup
    spawn(server.serve())
    logger.info(f"✅ API server started on {host}:{port} in same event loop")

    logger.success("✅ API server started in background task")
    return server


class TradingBot:
    """Main trading bot orchestrator"""
    
    def __init__(self):
        self.telethon_listener = None
        self.session_id = None
        self.is_running = False
        self.is_stopping = False
        self._shutdown_event = asyncio.Event()
        self.trading_provider = None  # Store the initialized trading provider
        self._api_server: Optional[object] = None  # Store API server for cleanup
        
    async def initialize(self):
        """Initialize all components"""
        logger.info("🚀 Initializing NEXAL...")
        logger.info(f"📅 Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"🌍 Timezone: {settings.timezone}")
        logger.info(f"🧪 Dry Run Mode: {settings.dry_run}")
        
        # Initialize Prisma database
        await prisma_client.initialize()
        
        # Initialize settings service with encryption
        logger.info("⚙️  Initializing settings service...")
        encryption_key = os.getenv("SETTINGS_ENCRYPTION_KEY")
        settings_service = await get_settings_service(prisma_client.client, encryption_key=encryption_key)
        settings.set_db_settings_service(settings_service)
        await settings.reload_from_db()
        logger.success("✅ Settings service initialized and loaded from database")

        # --- Startup banner (printed after DB settings are loaded) ---
        try:
            _db_channels = await telegram_channel_service_prisma.get_monitored_channels()
            _channel_display = ", ".join(
                f"{ch['channel_id']} ({ch['channel_title']})" if ch.get('channel_title') else ch['channel_id']
                for ch in _db_channels
            ) if _db_channels else f"{', '.join(settings.telegram_channels)}"
        except Exception:
            _channel_display = ", ".join(settings.telegram_channels)

        _provider = settings.trading_provider.lower().strip()
        _is_mt5rest = _provider == "mt5rest"
        print("\n" + "="*60)
        print("  🤖 NEXAL")
        print("="*60)
        if _is_mt5rest:
            print(f"  Trading Provider: MT5 REST API ({settings.mt5_rest_api_url})")
        else:
            print(f"  Trading Provider: MetaAPI Cloud SDK ({settings.metaapi_account_id})")
        print(f"  AI Provider: {settings.primary_ai_provider.value}")
        print(f"  Monitoring Channels: {_channel_display}")
        print(f"  Max Risk per Trade: {settings.max_risk_per_trade_percent}%")
        print(f"  Dry Run: {'YES' if settings.dry_run else 'NO'}")
        if settings.enable_equity_protection:
            if _is_mt5rest:
                print("  🛡️  Equity Protection: ENABLED (local monitoring)")
                print(f"     Daily Limit: {settings.daily_drawdown_limit_percent}%")
                print(f"     Overall Limit: {settings.overall_drawdown_limit_percent}%")
            else:
                print("  🛡️  Equity Protection: ENABLED (MetaAPI trackers)")
                print(f"     Daily Limit: {settings.daily_drawdown_limit_percent}%")
                print(f"     Overall Limit: {settings.overall_drawdown_limit_percent}%")
        if settings.enable_position_monitoring:
            print("  🔄 Position Monitoring: ENABLED")
            print(f"     Auto TP: {'✅' if settings.enable_auto_take_profit else '❌'} ({settings.auto_tp_calculation_method})")
            print(f"     Trailing SL: {'✅' if settings.enable_trailing_stop else '❌'} ({settings.trailing_stop_calculation_method})")
            print(f"     Breakeven: {'✅' if settings.enable_breakeven_move else '❌'} ({settings.breakeven_trigger_pips} pips)")
        if settings.news_enable_filter:
            print("  📰 News Trading Filter: ENABLED")
            print(f"     Block: {settings.news_minutes_before}min before, {settings.news_minutes_after}min after news")
        print("="*60 + "\n")
        # --- End banner ---

        # Reinitialize signal service now that DB settings are loaded.
        # The singleton is created at module import time (before DB is ready),
        # so we must rebuild the AI processors with the correct settings from DB.
        from src.services.signal_service import signal_service
        signal_service.reinitialize()
        logger.info("✅ Signal service initialized")
        
        # Start API server for dashboard (after settings service is initialized)
        logger.info("🌐 Starting API server for dashboard...")
        from src.api.api_server import set_settings_service, set_settings_config
        set_settings_service(settings_service)
        set_settings_config(settings)
        self._api_server = await start_api_server()
        
        # Reconfigure logging with database settings
        configure_logging(settings)
        logger.info("📝 Logging reconfigured with database settings")
        
        # Initialize news services (must be done before other services)
        logger.info("📰 Initializing news services...")
        initialize_news_services(notification_service=notification_sender)
        
        # Start news monitoring in background (non-blocking, independent of MetaAPI)
        logger.info("📰 Starting news monitoring...")
        try:
            async def _start_news_monitoring_wrapper():
                try:
                    await start_news_monitoring()
                    logger.info("✅ News monitoring services initialized")
                except Exception as e:
                    logger.error(f"❌ Error in news monitoring: {e}", exc_info=True)
            
            self.news_monitoring_task = asyncio.create_task(_start_news_monitoring_wrapper())
            logger.success("✅ News monitoring started in background (non-blocking)")
        except Exception as e:
            logger.error(f"⚠️ News monitoring failed: {str(e)}", exc_info=True)
            logger.warning("⚠️ Continuing without news monitoring")
        
        # Initialize notification sender early (bot_sender can work without Telethon)
        logger.info("📢 Initializing notification sender...")
        await notification_sender.initialize(telethon_client=None)
        
        # Always start brain action queue (handles brain position-action approvals)
        from src.services.approval_queue import brain_action_queue
        await brain_action_queue.start()
        logger.success("✅ Brain action queue started")

        # Always expire signals stuck in AWAITING_APPROVAL from before this restart.
        # The in-memory approval queue is wiped on restart so those signals can
        # never be approved/rejected — mark them EXPIRED regardless of whether
        # require_manual_approval is currently on or off (the signals may have been
        # queued when the setting was on, or via per-channel approval rules).
        logger.warning("🔍 Checking for stale AWAITING_APPROVAL signals...")
        try:
            stale_signals = await db_service.db.signal.find_many(
                where={"status": "AWAITING_APPROVAL"}
            )
            if stale_signals:
                logger.warning(
                    f"⚠️  Found {len(stale_signals)} signal(s) stuck in AWAITING_APPROVAL "
                    f"from before restart — marking as EXPIRED"
                )
                for stale in stale_signals:
                    try:
                        await db_service.update_signal_status(
                            stale.id,
                            "EXPIRED",
                            rejection_reason="Bot restarted — pending approval was lost. Re-send the signal to approve.",
                        )
                        logger.warning(f"   ✅ Expired stale approval signal {stale.id[:8]} ({stale.symbol})")
                    except Exception as inner_e:
                        logger.error(f"   ❌ Failed to expire signal {stale.id[:8]}: {inner_e}")
            else:
                logger.warning("✅ No stale AWAITING_APPROVAL signals found")
        except Exception as e:
            logger.error(f"❌ Failed to query stale approval signals: {e}", exc_info=True)

        # Always start the approval queue when manual approval is enabled
        if settings.require_manual_approval:
            logger.warning("⏸️  Initializing approval queue...")
            from src.services.approval_queue import approval_queue
            await approval_queue.start()
            logger.warning("✅ Approval queue started")

        # Always register bot commands when a bot token is available —
        # /balance, /help, /positions, /pause, /resume etc. must work
        # regardless of whether manual approval is on or off.
        if hasattr(settings, 'telegram_bot_token') and settings.telegram_bot_token:
            logger.warning("🤖 Registering bot command handlers...")
            try:
                from telegram.ext import Application
                from src.integrations.telegram.approval_commands import register_approval_commands

                application = Application.builder().token(settings.telegram_bot_token).build()
                register_approval_commands(application)

                await application.initialize()
                await application.start()

                try:
                    spawn(application.updater.start_polling())
                    logger.warning("✅ Bot commands registered and polling started (/balance /help /positions /pause /resume /pending /execute /reject)")
                except Exception as e:
                    if "Conflict" in str(e) and "getUpdates" in str(e):
                        logger.error(f"⚠️ Telegram bot polling conflict: {e}")
                        logger.warning("⚠️ Another bot instance may be using the same token")
                    else:
                        raise
            except Exception as e:
                logger.error(f"⚠️ Failed to register bot commands: {e}")
                logger.warning("⚠️ Bot commands unavailable — check TELEGRAM_BOT_TOKEN")
        else:
            logger.warning("⚠️ TELEGRAM_BOT_TOKEN not set — /balance /help /positions and other commands unavailable")
        
        # Initialize Telethon listener
        self.telethon_listener = TelethonListener(
            signal_callback=self.process_signal
        )

        try:
            from src.api.api_server import set_telethon_listener
            set_telethon_listener(self.telethon_listener)
        except Exception as e:
            logger.warning(f"⚠️ Could not register Telethon listener with API server: {e}")

        # Discord signal source (optional): token, on/off and channels come from the
        # dashboard; settings changes re-apply it live (config/settings.py).
        try:
            from src.integrations.discord.listener import discord_listener
            discord_listener.configure(self.process_signal)
            await discord_listener.apply_settings()
        except Exception as e:
            logger.error(f"⚠️ Discord listener failed to start: {e}")
            logger.warning("⚠️ Continuing without Discord")

        # Initialize Telegram channel service with shared client (after listener starts)
        # This will be done in start() after the listener client is ready
        
        # Determine active trading provider
        is_mt5rest = settings.trading_provider.lower().strip() == "mt5rest"
        provider_label = "MT5 REST API" if is_mt5rest else "MetaAPI Cloud SDK"
        
        # Initialize trading provider (or skip if disabled)
        if settings.skip_metaapi:
            logger.warning("⚠️ Trading DISABLED - Running in SIGNAL DETECTION ONLY mode")
            logger.info("💡 Signals will be detected and analyzed but NOT traded")
            # Use dummy account info
            account_info = AccountInfo(
                balance=10000.0,
                equity=10000.0,
                margin=0.0,
                free_margin=10000.0,
                open_positions=0
            )
            self.session_id = await db_service.start_trading_session(account_info.balance)
            # Start brain session (no account info in skip mode)
            trading_brain.start_session(account_info)
        else:
            try:
                logger.info(f"🔧 Trading provider: {provider_label}")
                from src.integrations.trading.provider_manager import provider_manager
                trading_provider = provider_manager.proxy
                await provider_manager.start()
                provider_manager.add_switch_hook(self._on_provider_switched)
                # Store the provider for cleanup
                self.trading_provider = trading_provider
                # Set the provider on the global trading service
                trading_service.set_trading_provider(trading_provider)
                # Get account info and start session
                account_info = await trading_provider.get_account_info()
                self.session_id = await db_service.start_trading_session(account_info.balance)
                # Start the Trading Brain conversation session
                trading_brain.start_session(account_info)
                # Wire brain into position monitor for autonomous position management
                position_monitor_service.set_trading_brain(trading_brain)
                
                # Initialize equity protection if enabled (provider-specific; re-wired on provider switch)
                await self._start_equity_protection(settings.trading_provider.lower().strip())
                
                # Recover state for existing positions
                logger.info("🔄 Recovering trade states...")
                try:
                    from src.services.state_recovery_service import state_recovery_service
                    recovery_result = await state_recovery_service.recover_all_states()
                    if recovery_result.get('success'):
                        logger.success(f"✅ Recovered {recovery_result.get('recovered', 0)} trade(s)")
                except Exception as e:
                    logger.error(f"⚠️ State recovery failed: {str(e)}")
                    logger.warning("⚠️ Continuing without state recovery")
                
                # Start position monitoring if enabled
                if settings.enable_position_monitoring:
                    logger.info("🔄 Starting position monitoring...")
                    try:
                        await position_monitor_service.start_monitoring()
                    except Exception as e:
                        logger.error(f"⚠️ Position monitoring setup failed: {str(e)}")
                        logger.warning("⚠️ Continuing without position monitoring")
                
                # Resume active trade plans from DB (survives bot restarts)
                try:
                    from src.services.plan_watcher_service import plan_watcher_service
                    await plan_watcher_service.startup_load()
                except Exception as e:
                    logger.error(f"⚠️ Plan watcher startup failed: {str(e)}")

                # Start order sync service for continuous status updates
                logger.info("🔄 Starting order synchronization...")
                try:
                    from src.services.order_sync_service import order_sync_service
                    await order_sync_service.start_auto_sync()
                    logger.success(f"✅ Order sync started (provider: {settings.provider_label})")
                except Exception as e:
                    logger.error(f"⚠️ Order sync setup failed: {str(e)}")
                    logger.warning("⚠️ Continuing without automatic order sync")
                
                # News scraping and real-time monitoring DISABLED (403 Forbidden - Cloudflare bot detection)
                # News events are fetched from Faireconomy API via news_trading_service

                if settings.copy_master_mode:
                    await copy_master_service.start()
                    logger.success("✅ Copy master service started (polls master every 10s)")
            except Exception as e:
                logger.error(f"⚠️ Trading provider initialization failed: {str(e)}", exc_info=True)
                logger.warning("🔄 Running in SIGNAL DETECTION ONLY mode")
                logger.info("💡 Signals will be detected but NOT traded")
                # Use dummy account info
                account_info = AccountInfo(
                    balance=10000.0,
                    equity=10000.0,
                    margin=0.0,
                    free_margin=10000.0,
                    open_positions=0
                )
                self.session_id = await db_service.start_trading_session(account_info.balance)
        
        # Start health check service (monitors all components in parallel)
        # ALWAYS start this regardless of trading provider status - it should monitor what's available
        logger.info("🏥 Starting health check service...")
        try:
            health_check_service.set_components(
                prisma_client=prisma_client,
                trading_provider=self.trading_provider if hasattr(self, 'trading_provider') else None,
                telethon_listener=self.telethon_listener,
                notification_sender=notification_sender
            )
            await health_check_service.start()
            logger.success("✅ Health check service started (monitors every 15s)")
        except Exception as e:
            logger.error(f"⚠️ Health check service failed: {str(e)}")
            logger.warning("⚠️ Continuing without health monitoring")
        
        # Persist ERROR-level logs + audit events (provider switches, settings changes) to system_events
        try:
            from src.utils.audit import install_error_audit_sink
            install_error_audit_sink()
        except Exception as e:
            logger.warning(f"Error audit sink not installed: {e}")

        # Auto-apply settings edited in the DB/dashboard (provider switch, intervals, flags...)
        self._settings_task = asyncio.create_task(self._settings_watcher())

        logger.success("✅ All components initialized")
    
    async def _start_equity_protection(self, provider_name: str):
        """Start the equity protection that matches the active provider."""
        if not settings.enable_equity_protection:
            return
        if provider_name == "mt5rest":
            logger.info("🛡️  Equity protection: local drawdown monitoring (MT5 REST)")
            try:
                await drawdown_protection_service.initialize()
                await drawdown_monitor_service.start_monitoring()
            except Exception as e:
                logger.error(f"⚠️ Drawdown protection init failed: {str(e)}")
        else:
            logger.info("🛡️  Setting up equity protection (MetaAPI SDK)...")
            try:
                await self._setup_equity_protection()
            except Exception as e:
                logger.error(f"⚠️ Equity protection setup failed: {str(e)}")
                logger.warning("⚠️ Continuing without equity protection")

    async def _stop_equity_protection(self, provider_name: str):
        """Stop the equity protection that belongs to `provider_name`."""
        if not settings.enable_equity_protection:
            return
        if provider_name == "mt5rest":
            try:
                await drawdown_monitor_service.stop_monitoring()
                logger.info("🛡️  Drawdown monitoring stopped")
            except Exception as e:
                logger.warning(f"Could not stop drawdown monitoring: {str(e)}")
        elif settings.enable_drawdown_monitoring:
            try:
                await risk_management_service.stop_drawdown_monitoring()
            except Exception as e:
                logger.warning(f"Could not stop risk monitoring: {str(e)}")

    async def _on_provider_switched(self, old_name: str, new_name: str, old_balance=None):
        """
        Provider hot-switch. MetaAPI and MT5 REST are different accounts, so everything account-scoped
        starts fresh: trading session, brain context, drawdown pause state and equity protection.
        """
        from src.integrations.trading.provider_manager import provider_manager
        self.trading_provider = provider_manager.proxy
        if old_name == new_name:
            return  # credentials rebuild of the same account: nothing account-scoped changes

        await self._stop_equity_protection(old_name)
        drawdown_protection_service.reset_state()  # a pause for the old account must not block the new one
        try:
            info = await self.trading_provider.get_account_info(use_cache=False)
            if self.session_id:
                await db_service.end_trading_session(
                    self.session_id,
                    old_balance if old_balance is not None else info.balance,
                    {"total_signals": 0, "signals_executed": 0, "signals_rejected": 0, "total_profit_loss": 0.0},
                )
            self.session_id = await db_service.start_trading_session(info.balance)
            trading_brain.start_session(info)
            logger.info(f"📊 New trading session for {new_name} (balance ${info.balance:.2f})")
        except Exception as e:
            logger.warning(f"⚠️ Could not start a new trading session after provider switch: {e}")
        await self._start_equity_protection(new_name)

    async def _settings_watcher(self, interval: float = 30.0):
        """Apply settings changes made in the DB/dashboard automatically (no restart, no manual reload)."""
        while True:
            try:
                await asyncio.sleep(interval)
                await settings.reload_from_db()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Settings auto-reload failed: {e}")

    async def _setup_equity_protection(self):
        """Setup equity protection trackers"""
        try:
            # Initialize drawdown protection service (checks for active breaches)
            await drawdown_protection_service.initialize()
            
            # Initialize risk management service
            await risk_management_service.initialize()
            
            # Check if trackers already exist
            existing_trackers = await risk_management_service.get_all_trackers(
                settings.metaapi_account_id
            )
            
            trackers_to_monitor = []
            
            if existing_trackers:
                logger.info(f"📊 Found {len(existing_trackers)} existing trackers")
                for tracker in existing_trackers:
                    logger.info(f"   - {tracker.get('name')} ({tracker.get('period')})")
                trackers_to_monitor = existing_trackers
            else:
                # Create comprehensive protection
                logger.info("📊 Creating equity protection trackers...")
                trackers = await risk_management_service.create_comprehensive_protection(
                    settings.metaapi_account_id,
                    daily_percent=settings.daily_drawdown_limit_percent,
                    overall_percent=settings.overall_drawdown_limit_percent
                )
                
                logger.success("✅ Equity protection trackers created:")
                for key, tracker in trackers.items():
                    if tracker:
                        logger.info(f"   - {key}: {tracker.get('name')}")
                        trackers_to_monitor.append(tracker)
            
            # Start real-time monitoring if enabled
            if settings.enable_drawdown_monitoring and trackers_to_monitor:
                # Monitor each tracker
                for tracker in trackers_to_monitor:
                    tracker_id = tracker.get('_id') or tracker.get('id')
                    if tracker_id:
                        await risk_management_service.start_drawdown_monitoring(
                            settings.metaapi_account_id,
                            callback=self._on_drawdown_event,
                            tracker_id=tracker_id
                        )
                        logger.success(f"✅ Monitoring tracker: {tracker.get('name')}")
            
        except Exception as e:
            logger.error(f"❌ Failed to setup equity protection: {str(e)}")
            raise
    
    async def _on_drawdown_event(self, event: dict):
        """Handle drawdown events - close losing positions and pause trading"""
        logger.warning("⚠️  DRAWDOWN LIMIT BREACH DETECTED!")
        
        # Get tracker ID from event (we need to find it from the event data)
        tracker_id = event.get('trackerId', 'unknown')
        
        # Use drawdown protection service to handle the breach
        result = await drawdown_protection_service.handle_drawdown_breach(
            event=event,
            tracker_id=tracker_id
        )
        
        # Build notification message with actions taken
        breach_type = result.get('breach_type', 'Unknown')
        drawdown_percent = result.get('drawdown_percent', 0)
        losers_closed = result.get('losers_closed', 0)
        pending_orders_cancelled = result.get('pending_orders_cancelled', 0)

        message = (
            f"🚨 DRAWDOWN BREACH ALERT\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Type: {breach_type}\n"
            f"Drawdown: {drawdown_percent:.2f}%\n"
            f"Time: {event.get('brokerTime', 'Unknown')}\n"
            f"\n📊 ACTIONS TAKEN:\n"
            f"• Closed {losers_closed} losing position(s)\n"
            f"• Cancelled {pending_orders_cancelled} pending order(s)\n"
            f"• Trading PAUSED for the rest of the day\n"
            f"• Will auto-resume on new trading day\n"
            f"\n⛔ NO NEW TRADES ALLOWED TODAY"
        )
        
        try:
            await notification_sender.send_notification(message, category='risk_alerts')
        except Exception as e:
            logger.error(f"Failed to send drawdown notification: {str(e)}")
    
    async def start(self):
        """Start the trading bot"""
        try:
            await self.initialize()
            
            # Start Telethon listener first (this initializes the Telethon client and channel service)
            self.is_running = True
            logger.success("🎯 Trading Bot is running!")
            logger.info("Press Ctrl+C to stop")
            
            # Reload signal-continuity marks (instant entries awaiting their follow-up,
            # deleted signals awaiting a repost) before catch-up replays missed messages.
            from src.services.signal_continuity import signal_continuity
            await signal_continuity.restore()

            # Start listening (this will block until disconnected)
            # Note: Channel service is initialized inside listener.start() with shared client
            await self.telethon_listener.start()
            
        except Exception as e:
            logger.error(f"❌ Error starting bot: {str(e)}")
            logger.exception(e)
            raise
    
    async def stop(self):
        """Stop the trading bot and all services gracefully"""
        if self.is_stopping:
            logger.warning("⚠️ Bot is already stopping...")
            return
            
        self.is_stopping = True
        task = getattr(self, "_settings_task", None)
        if task:
            task.cancel()
        try:
            from src.integrations.trading.provider_manager import provider_manager
            await provider_manager.stop()
        except Exception as _exc:
            logger.debug(f"Suppressed exception: {_exc!r}")
        self.is_running = False
        logger.info("🛑 Stopping trading bot...")
        
        # Send shutdown notification FIRST, while Telethon client is still connected
        try:
            logger.info("📤 Sending shutdown notification...")
            # Use Bot API like the start function (not Telethon)
            result = await notification_sender.notify_bot_stopped()
            if result:
                logger.success("✅ Shutdown notification sent successfully")
            else:
                logger.warning("⚠️ Shutdown notification may have failed (check logs above)")
            # Give time for message to be fully delivered
            await asyncio.sleep(2.0)
        except Exception as e:
            logger.warning(f"⚠️ Could not send shutdown notification: {e}")
        
        # Now set shutdown event and stop everything
        self._shutdown_event.set()
        
        # Stop Telethon listener
        if self.telethon_listener:
            await self.telethon_listener.stop()

        try:
            from src.integrations.discord.listener import discord_listener
            await discord_listener.stop()
        except Exception as e:
            logger.warning(f"Could not stop Discord listener: {e}")
        
        # Stop API server gracefully
        if self._api_server:
            try:
                logger.info("🌐 Stopping API server...")
                self._api_server.should_exit = True
                await asyncio.sleep(0.5)  # Give it time to shut down
                logger.info("✅ API server stopped")
            except Exception as e:
                logger.warning(f"Could not stop API server: {e}")

        # Stop news monitoring
        try:
            await stop_news_monitoring()
            logger.info("📰 News monitoring stopped")
        except Exception as e:
            logger.warning(f"Could not stop news monitoring: {str(e)}")
        
        # Stop brain action queue
        try:
            from src.services.approval_queue import brain_action_queue
            await brain_action_queue.stop()
        except Exception as e:
            logger.warning(f"Could not stop brain action queue: {str(e)}")

        # Stop approval queue if running
        if settings.require_manual_approval:
            try:
                from src.services.approval_queue import approval_queue
                await approval_queue.stop()
                logger.info("⏸️  Approval queue stopped")
            except Exception as e:
                logger.warning(f"Could not stop approval queue: {str(e)}")
        
        # Stop health check service
        try:
            await health_check_service.stop()
            logger.info("🏥 Health check service stopped")
        except Exception as e:
            logger.warning(f"Could not stop health check service: {str(e)}")

        # Stop copy master service
        try:
            await copy_master_service.stop()
        except Exception as e:
            logger.warning(f"Could not stop copy master service: {str(e)})")
        
        # Stop position monitoring
        if settings.enable_position_monitoring:
            try:
                await position_monitor_service.stop_monitoring()
            except Exception as e:
                logger.warning(f"Could not stop position monitoring: {str(e)}")
        
        # Stop order sync service
        try:
            from src.services.order_sync_service import order_sync_service
            await order_sync_service.stop_auto_sync()
        except Exception as e:
            logger.warning(f"Could not stop order sync: {str(e)}")
        
        # Stop equity protection (provider-specific)
        await self._stop_equity_protection(settings.trading_provider.lower().strip())
        
        # End trading session WHILE still connected to provider and database
        if self.session_id:
            try:
                logger.info("📊 Closing trading session and recording final balance...")
                if not settings.skip_metaapi and self.trading_provider:
                    # Use existing INITIALIZED provider
                    account_info = await self.trading_provider.get_account_info()
                else:
                    # Use dummy info for skip_metaapi mode
                    account_info = AccountInfo(
                        balance=10000.0,
                        equity=10000.0,
                        margin=0.0,
                        free_margin=10000.0,
                        open_positions=0
                    )
                
                # Calculate statistics
                # Note: In a future update, we can query the database for actual session stats
                stats = {
                    "total_signals": 0,
                    "signals_executed": 0,
                    "signals_rejected": 0,
                    "total_profit_loss": 0.0
                }
                
                await db_service.end_trading_session(
                    self.session_id,
                    account_info.balance,
                    stats
                )
                logger.success("✅ Trading session ended successfully")
            except Exception as e:
                logger.warning(f"⚠️ Could not end session properly: {str(e)}")
        
        # Disconnect from trading provider
        try:
            if self.trading_provider:
                await self.trading_provider.disconnect()
                logger.info("🔌 Trading provider disconnected")
        except Exception as e:
            logger.warning(f"Error disconnecting from trading provider: {str(e)}")
        
        # Wait a moment for any pending tasks to complete
        await asyncio.sleep(0.5)
        
        # Disconnect from database
        try:
            await prisma_client.disconnect()
            logger.info("🗄️ Database disconnected")
        except Exception as e:
            logger.warning(f"Error disconnecting from database: {str(e)}")
        
        logger.success("✅ Trading bot stopped")
    
    async def process_signal(self, signal: TradingSignal):
        """
        Process a trading signal using the trading service
        
        Delegates to TradingService for complete workflow orchestration
        """
        await trading_service.process_signal(signal)


# Global bot instance
bot = TradingBot()


def setup_signal_handlers(loop):
    """Setup signal handlers for graceful shutdown"""
    def signal_handler():
        logger.info("🛑 Shutdown signal received")
        # Use loop.create_task — safe because this callback runs inside the event loop
        task = loop.create_task(bot.stop())
        task.add_done_callback(lambda t: logger.info("✅ Shutdown task completed"))

    # loop.add_signal_handler is the correct asyncio way: the callback runs
    # inside the event loop's context, making create_task safe and reliable.
    # signal.signal() runs as a raw Python interrupt which can race with asyncio internals.
    loop.add_signal_handler(sys_signal.SIGINT, signal_handler)
    loop.add_signal_handler(sys_signal.SIGTERM, signal_handler)




async def main():
    """Main entry point"""
    # Initial logging from .env values — reconfigured after DB settings load in initialize()
    configure_logging(settings)
    
    try:
        # Setup signal handlers
        loop = asyncio.get_event_loop()
        setup_signal_handlers(loop)

        # Start bot (banner is printed inside initialize() after DB settings are loaded)
        await bot.start()
        
    except KeyboardInterrupt:
        logger.info("🛑 Keyboard interrupt received")
    except Exception as e:
        logger.error(f"❌ Fatal error: {str(e)}")
        logger.exception(e)
    finally:
        try:
            await bot.stop()
        except Exception as e:
            logger.error(f"Error during shutdown: {str(e)}")
            logger.exception(e)
        
        # Give any remaining background tasks time to complete
        await asyncio.sleep(1.0)
        
        # Cancel any remaining tasks (with recursion protection)
        try:
            # Not this task itself: cancelling and then awaiting it from inside recursed
            # until the interpreter gave up, and the process never exited.
            current = asyncio.current_task()
            pending = [task for task in asyncio.all_tasks() if not task.done() and task is not current]
            if pending:
                logger.info(f"Cancelling {len(pending)} remaining tasks...")
                for task in pending:
                    try:
                        task.cancel()
                    except (RuntimeError, RecursionError):
                        pass  # Ignore recursion errors during cancellation
                # Wait for all tasks to be cancelled with timeout
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*pending, return_exceptions=True),
                        timeout=2.0
                    )
                except (asyncio.TimeoutError, RecursionError):
                    logger.warning("Some tasks did not cancel cleanly")
        except (Exception, RecursionError) as e:
            logger.warning(f"Error cancelling remaining tasks: {str(e)}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Goodbye!")
