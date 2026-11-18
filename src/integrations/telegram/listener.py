import asyncio
import re
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Callable, Awaitable, Optional
from telethon import TelegramClient, events, utils
from telethon.errors import (
    ApiIdInvalidError,
    FloodWaitError,
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)
from telethon.tl.types import Channel, Chat, User
from telethon.tl.types.auth import SentCodeTypeApp, SentCodeTypeSms
from loguru import logger
from src.utils.tasks import spawn
from src.utils.audit import audit

from config import settings
from src.services.signal_service import signal_service
from src.services.message_handler import message_handler
from src.models import TradingSignal


CODE_RESEND_COOLDOWN_S = 60
RECONNECT_SECONDS = 30
CONFIG_POLL_SECONDS = 15   # how often "not set up" re-checks for credentials saved in the dashboard
MAX_CODE_ATTEMPTS = 5
MAX_PASSWORD_ATTEMPTS = 5


class TelegramAuthError(Exception):
    """A login/sign-out step failed; the message is safe to show the owner."""


def _digits(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


def _mask_phone(phone: str) -> str:
    d = _digits(phone)
    return f"+{d[:2]}{'•' * max(0, len(d) - 5)}{d[-3:]}" if len(d) > 5 else "•••"


class TelethonListener:
    """
    Listen to Telegram channels using Telethon (user client)
    
    Advantages over bot API:
    - Can read messages from any channel (no admin rights needed)
    - Can access message history
    - Works with private channels
    - More powerful message filtering
    """
    
    def __init__(self, signal_callback: Callable[[TradingSignal], Awaitable[None]]):
        """
        Initialize Telethon listener
        
        Args:
            signal_callback: Async function to call when signal is extracted
        """
        self.signal_callback = signal_callback
        self.client = None
        self.monitored_entities = []
        self.monitored_ids_set = set()
        # Bounded-concurrency message processing: a burst of spam should not
        # serialize behind one slow message (each LLM call blocks ~seconds).
        self._msg_semaphore = None
        self._inflight_tasks = set()
        self._chat_locks: dict = {}  # chat_id -> asyncio.Lock: same-channel messages run in arrival order
        self._new_message_builder = None
        self._edited_message_builder = None
        self._deleted_message_builder = None
        self._refresh_lock = asyncio.Lock()
        # Live feed state for the dashboard's Connections page (in-memory, so it
        # covers activity since this process started).
        self.started_at: Optional[datetime] = None
        self.configured_channel_ids: list = []
        self.unresolved_channels: dict = {}  # configured id -> resolve error
        self.last_message_at: Optional[datetime] = None
        self.last_message_by_chat: dict = {}  # chat id -> datetime
        # Login lifecycle: starting -> live | logged_out -> code_sent
        # -> (password_required) -> live; error = logged in but listening failed.
        self.auth_state = "starting"
        self.auth_error: Optional[str] = None
        self.account: Optional[dict] = None
        self._auth_lock = asyncio.Lock()
        self._state_changed = asyncio.Event()
        self._stopping = False
        self._signing_out = False
        self._announced_start = False
        self._login_phone: Optional[str] = None
        self._phone_code_hash: Optional[str] = None
        self._code_via: Optional[str] = None
        self._last_code_sent_at: Optional[float] = None
        self._code_attempts = 0
        self._password_attempts = 0

    def _chat_lock(self, chat_id) -> asyncio.Lock:
        return self._chat_locks.setdefault(str(chat_id), asyncio.Lock())

    async def _run_ordered(self, chat_id, make_coro):
        """
        Run one message-handling coroutine so that messages of the SAME channel are processed strictly
        in arrival order (asyncio.Lock is FIFO and tasks are created in arrival order), while different
        channels still run in parallel under the global concurrency limit. Without this a signal and its
        reply/edit posted seconds apart could be handled concurrently and race.
        """
        if self._msg_semaphore is None:
            limit = max(1, int(getattr(settings, 'message_processing_concurrency', 4)))
            self._msg_semaphore = asyncio.Semaphore(limit)
        async with self._chat_lock(chat_id):
            async with self._msg_semaphore:
                try:
                    await make_coro()
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"❌ Message processing task failed: {e}")
                    audit("ERROR", f"Message processing failed in chat {chat_id}: {str(e)[:200]}", "HIGH",
                          module="telegram_listener")

    def _handler_with_cursor(self, event, callback):
        """process_message wrapped so the catch-up cursor advances once the message has been handled
        (success or failure - a crash mid-handling leaves the cursor behind, so catch-up re-checks it)."""
        msg = event.message

        async def go():
            try:
                await message_handler.process_message(event, callback)
            finally:
                from src.services.catchup_service import catchup_service
                catchup_service.note_processed(msg.chat_id, msg.id, getattr(msg, "date", None))
        return go

    async def _process_bounded(self, event, callback):
        """Process a new message in order, under the concurrency limit."""
        await self._run_ordered(event.message.chat_id, self._handler_with_cursor(event, callback))

    def _spawn_ordered(self, chat_id, make_coro):
        """Fire-and-forget an ordered handler so the Telethon event loop keeps dispatching."""
        task = asyncio.create_task(self._run_ordered(chat_id, make_coro))
        self._inflight_tasks.add(task)
        task.add_done_callback(self._inflight_tasks.discard)

    def _spawn_processing(self, event, callback):
        """Fire-and-forget the ordered processor for a NEW message."""
        self._spawn_ordered(event.message.chat_id, self._handler_with_cursor(event, callback))

    @staticmethod
    def forward_original_key(fwd_channel_id, fwd) -> Optional[str]:
        """Dedup key of the channel post a forward copies (same form as MessageIdentifier.get_key)."""
        post = getattr(fwd, 'channel_post', None)
        return f"-100{fwd_channel_id}:{post}" if fwd_channel_id and post else None

    @staticmethod
    def _api_credentials() -> Optional[tuple]:
        """(api_id, api_hash), or None while Telegram is not set up."""
        api_hash = str(getattr(settings, "telegram_api_hash", None) or "").strip()
        try:
            api_id = int(str(getattr(settings, "telegram_api_id", None) or "").strip() or 0)
        except ValueError:
            return None
        return (api_id, api_hash) if api_id > 0 and api_hash else None

    def is_configured(self) -> bool:
        return self._api_credentials() is not None

    def _new_client(self) -> TelegramClient:
        credentials = self._api_credentials()
        if credentials is None:
            raise TelegramAuthError("Telegram is not set up — save the API ID and API hash first (AI & Bot → Telegram)")
        return TelegramClient(settings.telegram_session_name, *credentials)

    async def _wait_for_change(self, timeout: Optional[float] = None) -> None:
        """Sleep until the login state changes, stop() is called, or `timeout` passes."""
        self._state_changed.clear()
        if self._stopping:
            return
        try:
            await asyncio.wait_for(self._state_changed.wait(), timeout)
        except asyncio.TimeoutError:
            pass

    async def _connect_at_startup(self) -> None:
        if not self.client:
            self.client = self._new_client()
        await self.client.connect()
        if await self.client.is_user_authorized():
            await self._go_live()
        else:
            self._set_logged_out(None)
            logger.warning("🔐 Telegram is not logged in — log in from the dashboard: Connections → Telegram")

    async def _drop_client(self) -> None:
        client, self.client = self.client, None
        try:
            if client is not None and client.is_connected():
                await client.disconnect()
        except Exception as e:
            logger.debug(f"Telegram: disconnect failed: {e}")

    async def start(self):
        """Connect to Telegram and listen until stop() is called. Never raises.

        Telegram is one signal source among others, so nothing here may take the bot
        down: without API credentials it waits (not_configured) until they are saved in
        the dashboard; without a session it waits (logged_out) for a dashboard login
        (see begin_login); a failed connection is retried.
        """
        logger.info("🚀 Starting Telethon listener...")
        self.started_at = datetime.now(timezone.utc)

        while not self._stopping:
            if self.auth_state in ("starting", "not_configured"):
                if not self.is_configured():
                    if self.auth_state != "not_configured":
                        logger.warning("📵 Telegram is not set up (no API ID / API hash) — running without it. "
                                       "Add them in the dashboard: AI & Bot → Telegram")
                    self.auth_state = "not_configured"
                    self.auth_error = None
                    await self._wait_for_change(CONFIG_POLL_SECONDS)
                    continue
                self.auth_state = "starting"
                try:
                    await self._connect_at_startup()
                except Exception as e:
                    logger.error(f"❌ Telegram could not start: {e} — retrying in {RECONNECT_SECONDS}s")
                    self.auth_error = f"Could not connect: {str(e)[:200]} — retrying every {RECONNECT_SECONDS}s"
                    await self._drop_client()
                    await self._wait_for_change(RECONNECT_SECONDS)
                continue
            if self.auth_state != "live":
                await self._wait_for_change()
                continue
            try:
                await self.client.run_until_disconnected()
            except Exception as e:
                logger.error(f"❌ Telegram connection error: {e}")
            if self._stopping:
                break
            if self._signing_out:
                self._signing_out = False
                continue
            # Unexpected disconnect (Telethon gave up reconnecting). If Telegram revoked
            # the session (e.g. it was terminated from the phone), wait for a dashboard
            # login; otherwise reconnect here. The bot used to exit for a Docker restart,
            # which also cut off every other signal source.
            try:
                await self.client.connect()
                if not await self.client.is_user_authorized():
                    logger.error("🔐 Telegram session was revoked — log in again from the dashboard")
                    self._set_logged_out("Telegram session was revoked (signed out from another device?). Log in again.")
                    continue
                logger.warning("🔌 Telegram connection was lost and is back — checking for missed messages")
                self._start_catchup()
            except Exception as e:
                logger.error(f"❌ Telegram reconnect failed: {e} — retrying in {RECONNECT_SECONDS}s")
                await self._wait_for_change(RECONNECT_SECONDS)

    async def _go_live(self):
        """Wire the authorized client into every service and start listening."""
        me = await self.client.get_me()
        self.account = {"id": me.id, "name": me.first_name, "username": me.username}
        logger.success(f"✅ Logged in as: {me.first_name} (@{me.username or 'no username'})")

        # Set bot user ID in message handler to filter out bot's own messages
        message_handler.set_bot_user_id(me.id)

        # Initialize unified notification sender with our Telethon client
        from src.integrations.telegram.unified_sender import notification_sender
        await notification_sender.initialize(telethon_client=self.client)
        
        # Initialize Telegram channel service with shared client (avoids session locks)
        try:
            from src.services.telegram_channel_service_prisma import telegram_channel_service_prisma
            if telegram_channel_service_prisma._initialized:
                telegram_channel_service_prisma.client = self.client  # re-login: new client
            else:
                await telegram_channel_service_prisma.initialize(shared_client=self.client)
            logger.success("✅ Telegram channel service initialized with shared client")

            # Load dialogs cache in the background — iter_dialogs() can take minutes on
            # accounts with many chats and must not block event-handler registration.
            async def _load_cache_bg():
                try:
                    await telegram_channel_service_prisma.load_dialogs_cache()
                except Exception as _e:
                    logger.warning(f"⚠️ Background dialogs cache load failed: {_e}")
            spawn(_load_cache_bg())
            logger.info("📦 Dialogs cache loading in background (won't delay startup)")
        except Exception as e:
            logger.warning(f"⚠️ Could not initialize Telegram channel service: {e}")

        # Initialize Telegram browser service with shared client (avoids session locks)
        try:
            from src.services.telegram_browser_service import telegram_browser_service
            if telegram_browser_service._initialized:
                telegram_browser_service.client = self.client  # re-login: new client
            else:
                await telegram_browser_service.initialize(shared_client=self.client)
        except Exception as e:
            logger.warning(f"⚠️ Could not initialize Telegram browser service: {e}")

        # Share authenticated client with the simulator so it doesn't need its own session
        try:
            from simulator.service import simulator_service
            simulator_service.set_telegram_client(self.client)
            logger.success("✅ Simulator connected to shared Telegram client")
        except Exception as e:
            logger.warning(f"⚠️ Could not connect simulator to shared Telegram client: {e}")

        # Resolve channel entities
        await self._resolve_channels()
        
        # Extract chat IDs for event handlers (this is the key fix!)
        chat_ids = [entity.id for entity in self.monitored_entities]
        self.monitored_ids_set = set(chat_ids)

        logger.info(f"📝 Registering real-time event handlers for {len(chat_ids)} chats...")
        logger.info(f"📋 Monitoring chat IDs: {chat_ids}")

        # Register event handler for ALL messages (real-time)
        self._new_message_builder = events.NewMessage(chats=chat_ids)

        @self.client.on(self._new_message_builder)
        async def handle_new_message(event):
            logger.info(f"🔔 NEW MESSAGE EVENT from chat {event.message.chat_id}!")
            self._note_message(event.message.chat_id)
            self._spawn_processing(event, self.signal_callback)

        # Also handle edited messages
        self._edited_message_builder = events.MessageEdited(chats=chat_ids)

        @self.client.on(self._edited_message_builder)
        async def handle_edited_message(event):
            logger.info(f"✏️ MESSAGE EDITED in chat {event.message.chat_id}")
            self._note_message(event.message.chat_id)
            self._spawn_ordered(
                event.message.chat_id,
                lambda: message_handler.process_edited_message(event, self.signal_callback),
            )

        # Deleted messages — a deleted signal's pending orders are cancelled, and a
        # repost within the continuity window updates the same signal
        self._deleted_message_builder = events.MessageDeleted(chats=chat_ids)

        @self.client.on(self._deleted_message_builder)
        async def handle_deleted_message(event):
            logger.info(f"🗑️ MESSAGE(S) DELETED in chat {event.chat_id}: {event.deleted_ids}")
            self._spawn_ordered(event.chat_id, lambda: message_handler.process_deleted_messages(event))

        # Handle messages forwarded from monitored channels into any other chat
        if settings.process_forwarded_signals:
            logger.info("🔀 Forward signal processing ENABLED — listening for forwards from monitored channels")

            @self.client.on(events.NewMessage())
            async def handle_forwarded_from_monitored(event):
                if not settings.process_forwarded_signals:
                    return
                msg = event.message
                # Already handled by handle_new_message
                if msg.chat_id in self.monitored_ids_set:
                    return
                fwd = getattr(msg, 'fwd_from', None)
                if not fwd:
                    return
                # Resolve original channel ID from fwd_from
                fwd_channel_id = getattr(fwd, 'channel_id', None)
                if fwd_channel_id is None:
                    from_id = getattr(fwd, 'from_id', None)
                    fwd_channel_id = getattr(from_id, 'channel_id', None)
                if fwd_channel_id not in self.monitored_ids_set:
                    return
                logger.info(
                    f"🔀 Forwarded message from monitored channel {fwd_channel_id} "
                    f"received in chat {msg.chat_id} — processing as new signal"
                )
                # Wrap the callback so the signal carries the ORIGINAL channel's ID.
                # Without this, approval rules keyed on the VIP channel would be
                # bypassed because signal.channel_id would be the public channel's ID.
                _orig_channel_id = str(fwd_channel_id)
                _outer_callback = self.signal_callback

                async def _forwarded_signal_callback(signal):
                    signal.channel_id = _orig_channel_id
                    await _outer_callback(signal)

                # The account also receives the original post directly. Queue the copy
                # behind the original channel's messages and drop it once the original
                # was handled — a different chat/message id would otherwise give the
                # same post a second execution under its own magic number.
                original_key = self.forward_original_key(fwd_channel_id, fwd)
                handle = self._handler_with_cursor(event, _forwarded_signal_callback)

                async def _process_forward():
                    if original_key:
                        if original_key in message_handler.processed_message_ids:
                            logger.info(f"🔀 Forward of {original_key} skipped — the original post was already handled")
                            return
                        message_handler.processed_message_ids.add(original_key)
                    await handle()

                self._spawn_ordered(f"-100{fwd_channel_id}", _process_forward)
        else:
            logger.info("🔀 Forward signal processing DISABLED")
        
        self.auth_state = "live"
        self.auth_error = None
        self._state_changed.set()

        logger.success(f"✅ Telethon client started. Monitoring {len(self.monitored_entities)} channels")
        logger.info("🔊 Listening for trading signals in REAL-TIME...")

        self._start_catchup()

        try:
            from src.services.health_check_service import health_check_service
            if health_check_service.running:
                spawn(health_check_service.run_all_checks())
        except Exception as e:
            logger.debug(f"Could not trigger health check: {e}")

        if not self._announced_start:
            self._announced_start = True
            try:
                logger.info("📤 Sending startup notification...")
                result = await notification_sender.notify_bot_started()
                if result:
                    logger.success("✅ Startup notification sent successfully")
                else:
                    logger.warning("⚠️ Startup notification may have failed")
            except Exception as e:
                logger.warning(f"⚠️ Could not send startup notification: {e}")

    def _start_catchup(self) -> None:
        """Anything posted while the bot was offline: fresh -> processed, old signals -> reported, commands -> ask."""
        try:
            from src.services.catchup_service import catchup_service
            # Through self.client at call time: a dashboard re-login replaces the client
            history = SimpleNamespace(iter_messages=lambda *a, **kw: self.client.iter_messages(*a, **kw))
            spawn(
                catchup_service.run(history, self.monitored_entities, self.signal_callback,
                                    self._spawn_ordered, message_handler),
                name="catchup_startup",
            )
            catchup_service.start_periodic(
                history, lambda: self.monitored_entities, self.signal_callback,
                self._spawn_ordered, message_handler,
            )
        except Exception as e:
            logger.warning(f"Could not start catch-up: {e}")

    async def stop(self):
        """Stop the Telethon listener"""
        self._stopping = True
        try:
            from src.services.catchup_service import catchup_service
            await catchup_service.stop()   # persists the last message cursors
        except Exception as e:
            logger.debug(f"catch-up stop: {e}")
        self._state_changed.set()
        if self.client and self.client.is_connected():
            logger.info("🛑 Stopping Telethon listener...")
            await self.client.disconnect()
            logger.info("✅ Telethon listener stopped")

    # ------------------------------------------------------------------
    # Login / sign-out, driven from the dashboard (src/api/telegram_auth_router.py).
    # The owner-only dashboard route is the only caller; secrets (code, 2FA
    # password) are passed straight to Telegram and never stored or logged.
    # ------------------------------------------------------------------

    def _set_logged_out(self, error: Optional[str]):
        self.auth_state = "logged_out"
        self.auth_error = error
        self.account = None
        self._login_phone = None
        self._phone_code_hash = None
        self._code_via = None
        self._code_attempts = 0
        self._password_attempts = 0

    def configured_phone(self) -> str:
        return (settings.telegram_phone or "").strip()

    def auth_status(self) -> dict:
        phone = self._login_phone or self.configured_phone()
        cooldown = 0
        if self._last_code_sent_at is not None:
            cooldown = max(0, int(CODE_RESEND_COOLDOWN_S - (time.monotonic() - self._last_code_sent_at)))
        return {
            "state": self.auth_state,
            "error": self.auth_error,
            "account": self.account,
            "phoneLocked": bool(self.configured_phone()),
            "phoneHint": _mask_phone(phone) if phone else None,
            "codeVia": self._code_via,
            "resendInSeconds": cooldown,
        }

    async def _fresh_login_client(self):
        """Telethon clients are unusable after log_out(), and an unauthorized
        session may hold a key Telegram has already revoked — start clean."""
        old = self.client
        if old is not None:
            if old.is_connected():
                if await old.is_user_authorized():
                    raise TelegramAuthError("Already logged in — sign out first")
                await old.disconnect()
            if old.session is not None:
                old.session.delete()  # unauthorized (checked above): nothing to lose
        self.client = self._new_client()
        await self.client.connect()

    async def begin_login(self, phone: Optional[str] = None) -> dict:
        async with self._auth_lock:
            if self.auth_state in ("live", "error"):
                raise TelegramAuthError("Already logged in — sign out first")
            if self.auth_state == "not_configured" or not self.is_configured():
                raise TelegramAuthError("Telegram is not set up — save the API ID and API hash first (AI & Bot → Telegram)")
            if self.auth_state != "logged_out" and self.auth_state not in ("code_sent", "password_required"):
                raise TelegramAuthError("Telegram is still starting, try again in a moment")

            configured = self.configured_phone()
            given = (phone or "").strip()
            if configured and given and _digits(given) != _digits(configured):
                raise TelegramAuthError("The phone number is locked to TELEGRAM_PHONE in settings")
            target = configured or given
            if not target:
                raise TelegramAuthError("Enter the phone number of the Telegram account")

            if self._last_code_sent_at is not None:
                wait = CODE_RESEND_COOLDOWN_S - (time.monotonic() - self._last_code_sent_at)
                if wait > 0:
                    raise TelegramAuthError(f"Wait {int(wait) + 1}s before requesting another code")

            await self._fresh_login_client()
            try:
                sent = await self.client.send_code_request(target)
            except FloodWaitError as e:
                raise TelegramAuthError(f"Telegram asks to wait {e.seconds}s before another login attempt")
            except PhoneNumberInvalidError:
                raise TelegramAuthError("Telegram says this phone number is invalid")
            except ApiIdInvalidError:
                raise TelegramAuthError("TELEGRAM_API_ID / TELEGRAM_API_HASH are invalid")

            self._last_code_sent_at = time.monotonic()
            self._login_phone = target
            self._phone_code_hash = sent.phone_code_hash
            self._code_via = "Telegram app" if isinstance(sent.type, SentCodeTypeApp) else "SMS" \
                if isinstance(sent.type, SentCodeTypeSms) else "Telegram"
            self._code_attempts = 0
            self.auth_state = "code_sent"
            self.auth_error = None
            logger.info(f"🔐 Telegram login code sent to {_mask_phone(target)} via {self._code_via}")
            return self.auth_status()

    async def submit_code(self, code: str) -> dict:
        async with self._auth_lock:
            if self.auth_state != "code_sent":
                raise TelegramAuthError("Request a login code first")
            code = re.sub(r"\D", "", code or "")
            if not code:
                raise TelegramAuthError("Enter the code Telegram sent you")
            self._code_attempts += 1
            if self._code_attempts > MAX_CODE_ATTEMPTS:
                self._set_logged_out("Too many wrong codes — request a new one")
                raise TelegramAuthError(self.auth_error)
            try:
                await self.client.sign_in(phone=self._login_phone, code=code, phone_code_hash=self._phone_code_hash)
            except SessionPasswordNeededError:
                self.auth_state = "password_required"
                self.auth_error = None
                self._password_attempts = 0
                logger.info("🔐 Telegram login: 2FA password required")
                return self.auth_status()
            except PhoneCodeInvalidError:
                raise TelegramAuthError(f"Wrong code ({MAX_CODE_ATTEMPTS - self._code_attempts} attempts left)")
            except PhoneCodeExpiredError:
                self._set_logged_out("That code expired — request a new one")
                raise TelegramAuthError(self.auth_error)
            except FloodWaitError as e:
                raise TelegramAuthError(f"Telegram asks to wait {e.seconds}s before another attempt")
            return await self._finish_login()

    async def submit_password(self, password: str) -> dict:
        async with self._auth_lock:
            if self.auth_state != "password_required":
                raise TelegramAuthError("Telegram has not asked for the 2FA password")
            if not password:
                raise TelegramAuthError("Enter your Telegram 2FA password")
            self._password_attempts += 1
            if self._password_attempts > MAX_PASSWORD_ATTEMPTS:
                self._set_logged_out("Too many wrong passwords — start the login again")
                raise TelegramAuthError(self.auth_error)
            try:
                await self.client.sign_in(password=password)
            except PasswordHashInvalidError:
                raise TelegramAuthError(
                    f"Wrong 2FA password ({MAX_PASSWORD_ATTEMPTS - self._password_attempts} attempts left)"
                )
            except FloodWaitError as e:
                raise TelegramAuthError(f"Telegram asks to wait {e.seconds}s before another attempt")
            return await self._finish_login()

    async def _finish_login(self) -> dict:
        self._phone_code_hash = None
        self._last_code_sent_at = None
        try:
            await self._go_live()
        except Exception as e:
            logger.error(f"❌ Logged in to Telegram but failed to start listening: {e}")
            self.auth_state = "error"
            self.auth_error = f"Logged in, but listening failed to start: {str(e)[:200]}. Restart the bot."
            raise TelegramAuthError(self.auth_error)
        return self.auth_status()

    async def cancel_login(self) -> dict:
        async with self._auth_lock:
            if self.auth_state in ("code_sent", "password_required"):
                self._set_logged_out(None)
                logger.info("🔐 Telegram login cancelled from the dashboard")
            return self.auth_status()

    async def sign_out(self) -> dict:
        """Log out on Telegram's side (kills the session everywhere) and stop listening."""
        async with self._auth_lock:
            if self.auth_state not in ("live", "error"):
                raise TelegramAuthError("Not logged in")
            # Only when live is start() inside run_until_disconnected() and needs to
            # know this disconnect was on purpose.
            self._signing_out = self.auth_state == "live"
            try:
                ok = await self.client.log_out()
            except Exception as e:
                self._signing_out = False
                raise TelegramAuthError(f"Sign-out failed: {str(e)[:200]}")
            if not ok:
                self._signing_out = False
                raise TelegramAuthError("Telegram refused the sign-out request")
            self._new_message_builder = None
            self._edited_message_builder = None
            self.monitored_entities = []
            self.monitored_ids_set = set()
            self._set_logged_out(None)
            logger.warning("🔐 Signed out of Telegram from the dashboard — no signals will be received until you log in again")
            return self.auth_status()

    async def _get_channel_ids(self) -> list:
        """Get channel IDs from monitored_channels table, falling back to TELEGRAM_CHANNEL_ID setting."""
        try:
            from src.services.telegram_channel_service_prisma import telegram_channel_service_prisma
            db_channels = await telegram_channel_service_prisma.get_monitored_channels()
            if db_channels:
                ids = [ch["channel_id"] for ch in db_channels]
                logger.info(f"📋 Loaded {len(ids)} channel(s) from monitored_channels table")
                return ids
        except Exception as e:
            logger.warning(f"⚠️ Could not load monitored_channels table: {e}")
        # Fall back to TELEGRAM_CHANNEL_ID from the settings database table
        setting_channels = settings.telegram_channels
        if setting_channels and any(ch.strip() for ch in setting_channels):
            logger.info(f"📋 Loaded {len(setting_channels)} channel(s) from TELEGRAM_CHANNEL_ID setting")
            return setting_channels
        logger.warning("⚠️ No channels configured — set TELEGRAM_CHANNEL_ID in settings or add channels via the dashboard")
        return []

    def _note_message(self, chat_id) -> None:
        now = datetime.now(timezone.utc)
        self.last_message_at = now
        self.last_message_by_chat[chat_id] = now

    async def _resolve_channels(self):
        """Resolve channel usernames/IDs to entity objects"""
        self.monitored_entities = []
        self.configured_channel_ids = list(await self._get_channel_ids())
        self.unresolved_channels = {}

        for channel_id in self.configured_channel_ids:
            try:
                # Parse channel ID - handle both usernames (@channel) and numeric IDs
                parsed_id = channel_id
                
                # If it's a numeric string, convert to int
                if channel_id.lstrip('-').isdigit():
                    parsed_id = int(channel_id)
                    logger.debug(f"   Parsed numeric ID: {parsed_id}")
                
                # Resolve channel (can be username like @channel or numeric ID)
                entity = await self.client.get_entity(parsed_id)
                self.monitored_entities.append(entity)
                
                # Get channel info
                if isinstance(entity, Channel):
                    logger.info(f"📢 Monitoring channel: {entity.title} (@{entity.username or 'private'})")
                elif isinstance(entity, Chat):
                    logger.info(f"💬 Monitoring chat: {entity.title}")
                elif isinstance(entity, User):
                    logger.info(f"👤 Monitoring user: {entity.first_name}")
                    
            except Exception as e:
                self.unresolved_channels[str(channel_id)] = str(e)[:200]
                logger.error(f"❌ Failed to resolve channel {channel_id}: {str(e)}")
                logger.warning("   Make sure you're a member of the channel and ID/username is correct")
        
        # No channels is a state, not a crash: the bot keeps running (trading, Discord,
        # dashboard) and starts listening as soon as channels are added.
        if not self.monitored_entities:
            if self.configured_channel_ids:
                logger.error("❌ None of the configured Telegram channels could be resolved — listening to none")
            else:
                logger.warning("⚠️ No Telegram channels configured — listening to none until some are added")

    async def refresh_channels(self):
        """Re-resolve monitored channels and apply them to the running client live."""
        if not self.client or self._new_message_builder is None:
            logger.warning("⚠️ refresh_channels() called before listener finished starting — ignoring")
            return

        async with self._refresh_lock:
            previous_entities = self.monitored_entities
            try:
                await self._resolve_channels()
            except Exception as e:
                logger.error(f"❌ Failed to refresh channel list, keeping previous list: {e}")
                self.monitored_entities = previous_entities
                return
            if self.configured_channel_ids and not self.monitored_entities:
                logger.error("❌ No configured channel could be resolved, keeping previous list")
                self.monitored_entities = previous_entities
                return

            new_chat_ids = {entity.id for entity in self.monitored_entities}
            self.monitored_ids_set = set(new_chat_ids)
            # A resolved filter is matched against event.chat_id, which is the marked
            # peer id (-100… for channels), not the bare entity id.
            peer_ids = {utils.get_peer_id(entity) for entity in self.monitored_entities}

            for builder in (self._new_message_builder, self._edited_message_builder, self._deleted_message_builder):
                if builder is None:
                    continue
                if builder.resolved:
                    builder.chats.clear()
                    builder.chats.update(peer_ids)
                else:
                    builder.chats = list(new_chat_ids)

            logger.success(f"✅ Now monitoring {len(new_chat_ids)} chat(s): {sorted(new_chat_ids)}")

    async def _handle_message(self, event):
        """Handle incoming Telegram messages"""
        try:
            message = event.message
            
            # Skip empty messages
            if not message.text:
                return
            
            # Get chat info
            # ALWAYS use numeric chat ID for consistency with replies and database
            chat = await event.get_chat()
            channel_id = str(chat.id)
            if isinstance(chat, Channel):
                channel_name = chat.title
            elif isinstance(chat, Chat):
                channel_name = chat.title
            else:
                channel_name = getattr(chat, 'first_name', 'Unknown')
            
            message_text = message.text
            message_id = message.id
            message_date = message.date  # Get actual message timestamp
            
            logger.info(f"📩 New message from {channel_name} ({channel_id})")
            logger.debug(f"   Message ID: {message_id}, Date: {message_date}")
            logger.debug(f"   Message: {message_text[:100]}...")
            
            # Quick check if it looks like a signal
            if not signal_service.is_potential_signal(message_text):
                logger.debug("   Message doesn't appear to be a trading signal")
                return
            
            # Extract signal using advanced AI service
            signal = await signal_service.extract_signal(
                message_text=message_text,
                channel_id=channel_id,
                message_id=message_id,
                message_date=message_date,
                channel_name=channel_name
            )
            
            if signal:
                # Handle both new and legacy signal properties
                signal_action = signal.action if hasattr(signal, 'action') else signal.signal_type
                logger.success(f"🎯 Trading signal detected: {signal_action} {signal.symbol}")
                # Call the callback to process the signal
                await self.signal_callback(signal)
            
        except Exception as e:
            logger.error(f"❌ Error handling Telegram message: {str(e)}")
            logger.exception(e)
    
    async def get_channel_history(self, channel_id: str, limit: int = 100):
        """
        Get message history from a channel (useful for backtesting)
        
        Args:
            channel_id: Channel username or ID
            limit: Number of messages to retrieve
        """
        if not self.client:
            raise Exception("Client not initialized")
        
        try:
            entity = await self.client.get_entity(channel_id)
            messages = []
            
            async for message in self.client.iter_messages(entity, limit=limit):
                if message.text:
                    messages.append({
                        'id': message.id,
                        'text': message.text,
                        'date': message.date,
                        'channel': channel_id
                    })
            
            logger.info(f"📚 Retrieved {len(messages)} messages from {channel_id}")
            return messages
            
        except Exception as e:
            logger.error(f"❌ Failed to get channel history: {str(e)}")
            return []


# Singleton instance will be created in main.py
telethon_listener = None
