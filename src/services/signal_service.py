"""
Signal Service
Handles signal extraction and processing using advanced AI processors
"""
import re
from typing import List, Optional
from datetime import datetime, timezone
from loguru import logger
from src.utils.tasks import spawn

from src.models import TradingSignal, SignalStatus, SignalAction
from ai.integrated_processor import IntegratedProcessor
from ai.market_analyzer import MarketAnalyzer
from ai.multi_timeframe_analyzer import AIMultiTimeframeAnalyzer
from src.services.trade_context_manager import trade_context_manager
from config import settings


class SignalService:
    """
    Service for extracting and processing trading signals
    Uses advanced AI processors from the ai/ folder
    """
    
    def __init__(self):
        """Initialize signal service with AI processors"""
        # Create a config object for AI processor
        class AIConfig:
            def __init__(self):
                # Primary AI for text processing
                self.primary_ai_provider = settings.primary_ai_provider
                # Explicitly set provider for text logic in IntegratedProcessor
                self.provider = settings.primary_ai_provider.value if hasattr(settings.primary_ai_provider, 'value') else settings.primary_ai_provider

                # API Keys — all supported providers
                self.openai_api_key = settings.openai_api_key
                self.gemini_api_key = settings.gemini_api_key
                self.deepseek_api_key = settings.deepseek_api_key
                self.perplexity_api_key = settings.perplexity_api_key
                self.openrouter_api_key = settings.openrouter_api_key
                self.minimax_api_key = settings.minimax_api_key
                self.qwen_api_key = settings.qwen_api_key

                # Models — text
                self.openai_model = settings.openai_model
                self.deepseek_model = settings.deepseek_model
                self.perplexity_model = settings.perplexity_model
                self.openrouter_model = settings.openrouter_model
                self.minimax_model = settings.minimax_model
                self.qwen_model = settings.qwen_model
                self.ai_model = settings.openai_model  # Fallback/Default

                # Models — vision
                self.openai_vision_model = settings.openai_vision_model
                self.gemini_vision_model = settings.gemini_vision_model
                self.deepseek_vision_model = settings.deepseek_vision_model
                self.perplexity_vision_model = settings.perplexity_vision_model
                self.openrouter_vision_model = settings.openrouter_vision_model
                self.minimax_vision_model = settings.minimax_vision_model
                self.qwen_vision_model = settings.qwen_vision_model

                # Base URLs
                self.perplexity_base_url = settings.perplexity_base_url
                self.openrouter_base_url = settings.openrouter_base_url
                self.minimax_base_url = settings.minimax_base_url
                self.qwen_base_url = settings.qwen_base_url
                self.deepseek_api_url = getattr(settings, 'deepseek_api_url', None)

                # Provider fallback chain (DB-driven) — used by complete_with_fallback
                # to auto-switch providers on quota/rate-limit/empty results.
                self.fallback_providers = settings.fallback_providers

                self.temperature = 0.1

                # ── Vision AI toggle ──────────────────────────────────────────────
                self.enable_ai_vision = settings.enable_ai_vision

                # ── Vision Anti-Hallucination Filters ─────────────────────────────
                self.vision_caption_prefilter_enabled = settings.vision_caption_prefilter_enabled
                self.vision_caption_block_keywords = settings.vision_caption_block_keywords
                self.vision_confidence_filter_enabled = settings.vision_confidence_filter_enabled
                self.vision_min_confidence = settings.vision_min_confidence
                self.vision_two_step_classify_enabled = settings.vision_two_step_classify_enabled
                self.vision_price_sanity_check_enabled = settings.vision_price_sanity_check_enabled
                self.vision_price_ranges = settings.vision_price_ranges
                self.vision_sl_distance_check_enabled = settings.vision_sl_distance_check_enabled
                self.vision_max_sl_distance_percent = settings.vision_max_sl_distance_percent
                self.vision_symbol_whitelist_enabled = settings.vision_symbol_whitelist_enabled
                self.vision_allowed_symbols = settings.vision_allowed_symbols
                self.vision_image_dimension_filter_enabled = settings.vision_image_dimension_filter_enabled
                self.vision_max_image_aspect_ratio = settings.vision_max_image_aspect_ratio
                self.vision_min_image_height = settings.vision_min_image_height

                # Vision AI provider: use explicit setting if it has a matching key,
                # otherwise auto-select the first available vision-capable provider.
                configured_vision = getattr(settings, 'provider', 'openai')
                vision_key_map = {
                    'openai': self.openai_api_key,
                    'gemini': self.gemini_api_key,
                    'perplexity': self.perplexity_api_key,
                    'openrouter': self.openrouter_api_key,
                    'minimax': self.minimax_api_key,
                    'qwen': self.qwen_api_key,
                }
                if vision_key_map.get(configured_vision):
                    self.vision_provider = configured_vision
                else:
                    # Auto-detect: pick first provider that has a key
                    self.vision_provider = next(
                        (p for p, k in vision_key_map.items() if k),
                        None
                    )
                    if self.vision_provider:
                        logger.warning(
                            f"⚠️ Vision provider '{configured_vision}' has no API key. "
                            f"Auto-selected '{self.vision_provider}' for image processing."
                        )
                    else:
                        logger.warning(
                            "⚠️ No vision-capable AI provider configured. "
                            "Image signals will be processed as text-only. "
                            "Set an OpenAI, Gemini, Perplexity, OpenRouter, MiniMax, or Qwen key to enable vision."
                        )
        
        self.ai_config = AIConfig()

        
        # Initialize the advanced IntegratedProcessor (AI + Pattern matching fallback)
        self.processor = IntegratedProcessor(self.ai_config)
        logger.info("✅ Signal service initialized with IntegratedProcessor")
        
        # Initialize market analyzer
        self.market_analyzer = MarketAnalyzer(self.ai_config)
        logger.info("✅ Market analyzer initialized")
        
        # Initialize multi-timeframe analyzer (gated by enableMultiTimeframe config)
        self.multi_tf_analyzer = AIMultiTimeframeAnalyzer(self.market_analyzer)
        logger.info("✅ Multi-timeframe analyzer initialized")
        
        # Initialize trade context manager with AI client
        if self.processor.client:
            trade_context_manager.ai_client = self.processor.client
            logger.info("✅ Trade context manager enhanced with AI")

    def reinitialize(self):
        """Reinitialize AI processors using current settings (call after DB settings are loaded)."""
        logger.info("🔄 Reinitializing SignalService with current settings...")
        self.__init__()
        logger.success(f"✅ SignalService reinitialized (vision_provider={settings.provider})")

    async def extract_signal(
        self,
        message_text: str,
        channel_id: str,
        message_id: int,
        message_date: Optional[datetime] = None,
        channel_name: Optional[str] = None,
        image_data=None,  # bytes, or list[bytes] for albums
        image_url: Optional[str] = None,
        context_symbol: Optional[str] = None,
    ) -> Optional[TradingSignal]:
        """
        Extract trading signal from message using advanced AI

        context_symbol: the instrument this message is about when it does not name
        one — the signal it replies to. Without it the channel's most recent symbol
        is used.

        Args:
            message_text: The message text to process
            channel_id: Telegram channel ID
            message_id: Telegram message ID
            message_date: Original message timestamp (from Telegram)
            channel_name: Telegram channel name
            image_data: Raw image bytes if message contains an image
            image_url: Image URL if available

        Returns:
            TradingSignal if extracted, None otherwise
        """
        has_image = bool(image_data or image_url)
        has_text = len(message_text.strip()) >= 3
        logger.info(f"📨 Extracting signal from message {message_id} from channel {channel_id} (image: {has_image}, text: {has_text})")
        logger.debug(f"Message: {message_text[:100]}...")

        # Reset rejection reason for this call
        self.last_rejection_reason: Optional[str] = None
        self.last_clarification: Optional[dict] = None

        # Text pre-filter: run cheaply before any AI call.
        # - Image + text caption: filter on text (saves vision tokens on "50 pips reached" etc.)
        # - Image only (no text): cannot pre-filter, let vision AI decide
        # - Text only: always filter
        if has_text and not self.is_potential_signal(message_text, has_image=has_image):
            logger.debug("Message text doesn't appear to be a trading signal — skipping vision")
            self.last_rejection_reason = "Pre-filter: no trading keywords or price numbers detected"
            return None
        if not has_image and not has_text:
            logger.debug("Message has no text and no image — skipping")
            self.last_rejection_reason = "Message has no text and no image"
            return None

        # Use advanced AI processor to extract signal
        signal = await self.processor.process_message(message_text, image_data=image_data, image_url=image_url)

        # If rejected due to missing symbol, retry with the most recent symbol from this channel's history.
        # This handles follow-up messages like "new entry at 70.540\nSL 71.295" that omit the symbol
        # because the channel already established it in a prior message.
        if not signal:
            first_rejection = getattr(self.processor, 'rejection_reason', None) or ""
            if "No trading symbol found" in first_rejection:
                # A reply is about the signal it replies to. The channel's most recent
                # symbol can be another instrument — even one that was never traded: a
                # re-entry replying to a gold signal was read as NZDCHF, the last symbol
                # the channel had mentioned (scripted history, 2026-11-13).
                recent_symbols = trade_context_manager.recent_symbols_cache.get(channel_id, [])
                if not context_symbol and recent_symbols:
                    context_symbol = recent_symbols[-1]
                if context_symbol:
                    logger.info(f"🔄 Retrying with context symbol '{context_symbol}'")
                    signal = await self.processor.process_message(
                        f"{context_symbol}\n{message_text}",
                        image_data=image_data,
                        image_url=image_url,
                    )
                    if signal:
                        logger.info(f"✅ Context-symbol retry succeeded: '{context_symbol}'")

        if not signal:
            # Propagate the processor's rejection reason if set
            self.last_rejection_reason = getattr(self.processor, 'rejection_reason', None) or "AI could not extract a valid signal"
            logger.warning(f"❌ Failed to extract signal: {self.last_rejection_reason}")

            # Only notify on genuine failures, not on correct non-signal classifications.
            # These are EXPECTED behaviour — the AI correctly identified a
            # non-actionable message (status update, commentary, empty, etc.).
            is_correct_rejection = (
                self.last_rejection_reason
                and any(phrase in (self.last_rejection_reason or "").lower() for phrase in [
                    "classified as commentary",
                    "classified as status",
                    "classified as not_trading",
                    "not a trading signal",
                    "pre-filter",
                    "no text and no image",
                    "incomplete",
                    "no stop loss",
                    "no trading symbol",
                    "no entry price",
                    "could not determine",
                ])
            )
            if not is_correct_rejection:
                await self._notify_extraction_failure(
                    message_text=message_text,
                    channel_id=channel_id,
                    channel_name=channel_name,
                    message_id=message_id,
                    reason=self.last_rejection_reason,
                    has_image=has_image,
                )
            return None
        
        # Enrich signal with Telegram metadata
        signal.raw_message = message_text
        signal.channel_id = channel_id
        signal.channel_name = channel_name
        signal.message_id = message_id
        # Carry image bytes for storage (albums pass a list — store the first image)
        signal.image_data = image_data[0] if isinstance(image_data, list) and image_data else image_data
        # Use actual message date if provided, otherwise use current time
        signal.timestamp = message_date if message_date else datetime.now(timezone.utc)
        signal.status = SignalStatus.VALIDATED
        
        # Normalize symbol
        if signal.symbol:
            signal.symbol = self._normalize_symbol(signal.symbol)
        
        # Resolve symbol from context for CLOSE/MODIFY/PARTIAL_CLOSE commands without symbol
        if not signal.symbol and signal.action in [SignalAction.CLOSE, SignalAction.MODIFY, SignalAction.PARTIAL_CLOSE]:
            logger.info("🔍 Symbol missing for command, attempting context resolution...")
            signal = await trade_context_manager.resolve_symbol_from_context(signal, channel_id)
            
            if not signal.symbol:
                logger.warning("⚠️ Could not resolve symbol from context")
                # Still return signal - it might be a "close all" command
        
        # Update recent symbols cache
        if signal.symbol and signal.action == SignalAction.OPEN:
            trade_context_manager.update_recent_symbols(channel_id, signal.symbol)
        
        # Add to conversation history for AI context
        signal_info = {
            "action": signal.action.value if signal.action else None,
            "symbol": signal.symbol,
            "entry": signal.entry_price
        }
        trade_context_manager.add_to_conversation_history(channel_id, message_text, signal_info)
        
        # Validate instant execution permissions
        wanted_instant = signal.instant_execution
        if signal.instant_execution:
            signal = self._validate_instant_execution_permissions(signal, channel_id)

        # A "NOW" entry without SL is let through extraction only to enter on a
        # temporary SL; when this channel may not use instant entries, drop it.
        if (wanted_instant and not signal.instant_execution
                and signal.action == SignalAction.OPEN and not signal.is_plan
                and not signal.stop_loss and not signal.needs_clarification):
            self.last_rejection_reason = (
                f"No stop loss for {signal.symbol or 'signal'} — entering without SL (temporary SL) "
                f"is only allowed for instant entries from Instant Execution channels"
            )
            logger.warning(f"⚠️ {self.last_rejection_reason}")
            return None
        
        logger.success(f"✅ Signal extracted: {signal.action} {signal.symbol or 'ALL'}")
        logger.info(f"   Entry: {signal.entry_price}, SL: {signal.stop_loss}, TP: {signal.take_profit}")
        logger.info(f"   Instant Execution: {signal.instant_execution}")
        logger.info(f"   Extraction method: {getattr(self.processor, 'last_extraction_method', 'unknown')}")

        # Clarification branch — vision found a usable plan but couldn't pin down one
        # field (currently only "symbol"). Hold it and ask the user instead of dropping
        # an otherwise-good setup. Checked before the plan branch since it can apply
        # to plan signals that are missing this one piece.
        if signal.needs_clarification:
            from src.services.signal_clarification_service import signal_clarification_service
            logger.info(f"❓ Signal needs clarification ({signal.needs_clarification}) — asking user")
            info = await signal_clarification_service.request_clarification(signal)
            self.last_clarification = info
            self.last_rejection_reason = (
                f"Needs {signal.needs_clarification} — asked you on Telegram "
                f"(reply or tap a button; id {info.get('id', '?')[:8] if info.get('id') else '?'})"
            )
            return None

        # Plan branch — always goes straight to validate_and_register, never through the
        # signal approval queue.  Plans have their own approval mechanism: the dashboard
        # shows the TradePlan, and autoExecute=False means the watcher waits for a manual
        # trigger from the dashboard before placing any order.  The signal approval queue
        # (with its 15-minute timeout) is inappropriate for plans.
        # Note: plans without SL or without full plan_data are still routed here — they
        # will be saved with image for manual approval and autoExecute=False.
        if signal.is_plan:
            from src.services.plan_filter_service import plan_filter_service
            logger.info(f"📋 Plan signal detected for {signal.symbol} — registering plan")
            spawn(plan_filter_service.validate_and_register(signal))
            return None  # trading_service is not called for plans

        return signal

    async def extract_signals(
        self,
        message_text: str,
        channel_id: str,
        message_id: int,
        message_date: Optional[datetime] = None,
        channel_name: Optional[str] = None,
        image_data=None,
        image_url: Optional[str] = None,
    ) -> List[TradingSignal]:
        """
        Like extract_signal(), but a TEXT-ONLY post holding several independent trades yields one signal per
        trade (the AI splits it; every block then goes through the normal single-signal extraction).
        Anything else behaves exactly like extract_signal(): a list of zero or one signal.
        """
        blocks = [message_text]
        has_image = bool(image_data or image_url)
        if (getattr(settings, 'allow_multi_signal_posts', True) and not has_image
                and hasattr(self.processor, 'split_signal_blocks')):
            try:
                blocks = await self.processor.split_signal_blocks(message_text)
            except Exception as e:
                logger.warning(f"Multi-signal split failed: {e}")
                blocks = [message_text]

        if len(blocks) <= 1:
            single = await self.extract_signal(
                message_text=message_text, channel_id=channel_id, message_id=message_id,
                message_date=message_date, channel_name=channel_name, image_data=image_data, image_url=image_url,
            )
            return [single] if single else []

        logger.info(f"🧩 Multi-signal post: {len(blocks)} independent trades detected")
        signals: List[TradingSignal] = []
        for i, block in enumerate(blocks):
            sig = await self.extract_signal(
                message_text=block, channel_id=channel_id, message_id=message_id,
                message_date=message_date, channel_name=channel_name,
            )
            if sig:
                sig.raw_message = message_text          # keep the full post for audit; the block drove extraction
                sig.split_block_index = i
                signals.append(sig)
            else:
                logger.warning(f"🧩 Block {i + 1}/{len(blocks)} produced no signal: {self.last_rejection_reason}")
        if not signals:
            # every block failed: fall back to the plain single-message path (old behaviour)
            single = await self.extract_signal(
                message_text=message_text, channel_id=channel_id, message_id=message_id,
                message_date=message_date, channel_name=channel_name,
            )
            return [single] if single else []
        return signals

    # Rate-limit extraction-failure notifications per channel (seconds)
    _failure_notify_cooldown: dict = {}
    _FAILURE_NOTIFY_COOLDOWN_S = 120  # max 1 notification per channel every 2 min

    async def _notify_extraction_failure(
        self,
        message_text: str,
        channel_id: str,
        channel_name: Optional[str],
        message_id: int,
        reason: str,
        has_image: bool,
    ) -> None:
        """Send a single notification to the notification channel when signal extraction fails."""
        import time as _time

        now = _time.monotonic()
        last = self._failure_notify_cooldown.get(channel_id, 0)
        if now - last < self._FAILURE_NOTIFY_COOLDOWN_S:
            return  # skip — already notified recently for this channel
        self._failure_notify_cooldown[channel_id] = now

        # Clean up old entries periodically
        if len(self._failure_notify_cooldown) > 50:
            cutoff = now - self._FAILURE_NOTIFY_COOLDOWN_S * 2
            self._failure_notify_cooldown = {
                k: v for k, v in self._failure_notify_cooldown.items() if v > cutoff
            }

        try:
            from src.integrations.telegram.unified_sender import notification_sender

            truncated = message_text[:200].replace("<", "&lt;").replace(">", "&gt;")
            img_tag = "📸" if has_image else ""
            channel_label = channel_name or channel_id

            msg = (
                f"⚠️ <b>Signal extraction failed</b> {img_tag}\n\n"
                f"📡 <b>Channel:</b> {channel_label}\n"
                f"🆔 <b>Msg ID:</b> {message_id}\n"
                f"📝 <b>Text:</b> {truncated}\n"
                f"❌ <b>Reason:</b> {reason}"
            )
            await notification_sender.send_message(msg, category='signal_parse_failed')
            logger.info(f"📤 Notified extraction failure for channel {channel_id}")
        except Exception as e:
            logger.warning(f"Could not send extraction-failure notification: {e}")

    async def classify_intent(self, message_text: str) -> str:
        """
        Cheap AI intent classification for message routing.
        Returns: 'SIGNAL', 'COMMAND', 'STATUS', or 'NOT_TRADING'.
        Falls back to 'SIGNAL' if AI is unavailable.
        """
        return await self.processor.classify_message_intent(message_text)

    async def classify_signal_relationship(self, message_text: str, candidates: list) -> dict:
        """
        AI classification of signal continuity relationship (NEW, FOLLOW_UP, CORRECTION, DUPLICATE).
        """
        return await self.processor.classify_signal_continuity_relationship(message_text, candidates)

    # Buy/sell/stop/target/entry vocabulary (es pt fr de it nl pl tr id ru ar zh ja ko vi th + common
    # transliterations). Latin-script words need word boundaries; other scripts match as substrings.
    _MULTILINGUAL_TRADE_RE = re.compile(
        r"(?:\b(?:comprar|compra|compro|vender|venta|vendo|venda|vendas|alvo|objetivo|entrada|"
        r"achat|acheter|vendre|vente|objectif|cible|"
        r"kaufen|kauf|verkaufen|verkauf|ziel|einstieg|"
        r"acquista|acquisto|vendi|vendita|obiettivo|ingresso|"
        r"kopen|verkopen|doel|kupuj|kup|sprzedaj|cel|wej[sś]cie|"
        r"hedef|giri[sş]|zarar|alis|satis|"
        r"beli|jual|masuk|"
        r"kharido|kharid|becho|bech|lakshya|"
        r"stop|stoploss|sl|tp)\b"
        r"|买入|卖出|做多|做空|止损|止盈|入场|目标|买进|卖空|"
        r"買い|売り|損切り|利確|目標|エントリー|ロング|ショート|"
        r"매수|매도|손절|익절|진입|목표|"
        r"покупк|купить|покупаю|продаж|продать|продаю|стоп|тейк|лонг|шорт|вход|цель|"
        r"شراء|اشتري|بيع|هدف|وقف|دخول|الخسارة|جني|"
        r"mua|bán|cắt lỗ|chốt lời|vào lệnh|"
        r"ซื้อ|ขาย|ตัดขาดทุน|เป้าหมาย|"
        r"קנה|מכור|יעד|"
        r"خرید|فروش|حد ضرر)",
        re.IGNORECASE,
    )

    def is_potential_signal(self, message_text: str, has_image: bool = False) -> bool:
        """
        Cheap pre-filter: only block messages that are obviously NOT trading-related
        to avoid wasting AI tokens. The AI does the real classification.
        Be permissive — false positives here just cost a small API call;
        false negatives silently miss valid signals/plans.
        """
        import re as _re

        if len(message_text) < 5:
            return False

        message_lower = message_text.lower()

        # ── Hard blocks: known non-signal patterns ─────────────────────────────
        # Pure celebration/milestone: "4100$ gold🔥" — number + $ + word + only emojis
        celebration_pattern = r'^\d+\$\s*\w+\s*[🔥❤️💯✨🚀💪🎉🎊🥳👏🙌]+\s*$'
        if _re.match(celebration_pattern, message_text.strip()):
            logger.debug("Pre-filter: celebration/milestone message — skipping")
            return False

        # Pure performance reports: "Week profit: +$1200" style, no price levels
        perf_pattern = r'^(week|month|daily|total)\s+(profit|result|pnl|gain|loss|performance)'
        if _re.match(perf_pattern, message_lower.strip()):
            logger.debug("Pre-filter: performance report — skipping")
            return False

        # ── Pass anything with a directional keyword ──────────────────────────
        # The AI will decide if it's a real signal/plan or just chatter.
        directional = ["buy", "sell", "long", "short", "bullish", "bearish",
                       "entry", "tp", "sl", "take profit", "stop loss",
                       "target", "close", "breakeven", "limit", "potential",
                       "opportunity", "setup", "trade", "zone", "level",
                       "support", "resistance", "order block", "reenter",
                       "swing", "position", "signal"]
        if any(kw in message_lower for kw in directional):
            return True

        # ── Trading vocabulary in other languages ─────────────────────────────
        # The English list above never matches "Покупка нефть 78.2 стоп 77.5" or "买入 原油 78.2 止损 77.5",
        # and a 2-digit price (oil, silver, many crypto/index quotes) has no 3-digit number either, so such
        # signals were dropped here, silently, before the AI ever saw them.
        if self._MULTILINGUAL_TRADE_RE.search(message_text):
            return True

        # ── Pass anything with a price number (3-6 digits, possibly decimal) ──
        if _re.search(r'\b\d{3,6}(?:\.\d+)?\b', message_text):
            return True

        # ── Two or more numbers of any size (entry + stop, "78.2 ... 77.5") ──
        # A false positive only costs one cheap intent-classification call.
        if len(_re.findall(r'\d+(?:[.,]\d+)?', message_text)) >= 2:
            return True

        # ── With image, be maximally permissive ───────────────────────────────
        if has_image:
            return True

        logger.debug("Pre-filter: no trading keywords or price numbers — skipping AI call")
        return False
    
    def _validate_instant_execution_permissions(self, signal: TradingSignal, channel_id: str) -> TradingSignal:
        """Clear the instant flag unless the owner allows instant execution for this channel."""
        from src.services.execution_policy import instant_execution_allowed
        allowed, why = instant_execution_allowed(channel_id)
        if allowed:
            logger.info(f"🚀 Instant execution allowed: {why}")
        else:
            logger.info(f"Instant wording ignored for channel {channel_id}: {why}")
            signal.instant_execution = False
        return signal

    def _normalize_symbol(self, symbol: str) -> str:
        """Normalize trading symbol format (shared canonical implementation)"""
        from src.utils.symbols import normalize_symbol
        return normalize_symbol(symbol)
    
    async def analyze_market_conditions(self, symbol: str, position_type: Optional[str] = None, metaapi_connection=None):
        """
        Analyze market conditions for intelligent trade management
        
        Args:
            symbol: Trading symbol
            position_type: Optional position type (BUY/SELL)
            metaapi_connection: Optional MetaAPI connection (auto-fetched if not provided)
            
        Returns:
            Market analysis dictionary
        """
        try:
            analysis = await self.market_analyzer.analyze_market_condition(
                symbol, 
                position_type,
                metaapi_connection
            )
            return analysis
        except Exception as e:
            logger.error(f"Market analysis failed: {e}", exc_info=True)
            return {"error": str(e)}
    
    async def analyze_all_timeframes(self, symbol: str, position_type: Optional[str] = None, metaapi_connection=None) -> dict:
        """
        Run multi-timeframe analysis (4H, 1H, 15M) for comprehensive market view.

        Gated by enableMultiTimeframe config in AIConfiguration. Returns combined
        analysis with overall trend, confidence, and per-timeframe breakdown.
        """
        try:
            result = await self.multi_tf_analyzer.analyze_all_timeframes(
                symbol=symbol,
                position_type=position_type,
                metaapi_connection=metaapi_connection,
            )
            return result
        except Exception as e:
            logger.error(f"Multi-timeframe analysis failed: {e}", exc_info=True)
            return {"error": str(e), "enabled": False}

    async def analyze_market_conditions_llm(self, symbol: str, position_type: Optional[str] = None, metaapi_connection=None, timeframe: str = '1h') -> dict:
        """
        Run market analysis with full enrichment: numerical + regime + LLM reasoning.

        Falls back to numerical-only if LLM is disabled or unavailable.
        """
        try:
            analysis = await self.market_analyzer.analyze_market_condition_llm(
                symbol=symbol,
                position_type=position_type,
                metaapi_connection=metaapi_connection,
                timeframe=timeframe,
            )
            return analysis
        except Exception as e:
            logger.error(f"LLM market analysis failed: {e}", exc_info=True)
            return {"error": str(e)}


# Singleton instance
signal_service = SignalService()
