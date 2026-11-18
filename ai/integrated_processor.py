"""
Integrated AI Processor with Enhanced Error Handling
Uses AI (OpenAI) as primary method with robust fallback mechanisms
"""
import json
import logging
import re
import asyncio
import time as _time
from typing import List, Optional
from .base_processor import BaseAIProcessor
from .image_signal_extractor import ImageSignalExtractor
from .signal_validation import detect_explicit_direction, sl_side_consistent
from .utils import safe_float, clean_json_response
from src.models import TradingSignal, SignalAction, OrderType, SignalType

logger = logging.getLogger(__name__)


class IntegratedProcessor(BaseAIProcessor):
    """
    Integrated processor that uses AI as primary method with pattern-based fallback
    
    Processing Flow:
    1. Try AI processing (OpenAI) first
    2. If AI fails or returns low confidence, use enhanced pattern matching
    3. Pattern matching extracts basic signal structure
    """
    
    def __init__(self, config):
        super().__init__(config)
        
        # Store config for instant execution settings
        self.config = config
        
        # AI availability gate. The actual text calls go through
        # llm_client.complete_with_fallback(), which builds its own clients across
        # the full provider chain (primary + FALLBACK_AI_PROVIDERS). self.client
        # here only answers "is any text provider available?", so it reuses that
        # SAME chain rather than duplicating provider/key/base_url logic — and can
        # never fail closed on a request the engine would serve via a fallback.
        from ai.llm_client import (
            first_available_provider, build_llm_client_for, get_model_for,
        )

        # Use primary_ai_provider if available, otherwise fallback to provider
        self.provider = getattr(config, 'primary_ai_provider', getattr(config, 'provider', 'openai'))
        if hasattr(self.provider, 'value'):
            self.provider = self.provider.value
        logger.info(f"🔧 IntegratedProcessor provider: {self.provider}")

        self.client = None
        available = first_available_provider(config, vision=False)
        if available is not None:
            self.client = build_llm_client_for(config, available)
            self.ai_model = get_model_for(config, available, vision=False)
            logger.info(f"✅ IntegratedProcessor AI client ready (provider: {available}, model: {self.ai_model})")
        else:
            logger.warning("⚠️ No AI provider has an API key - pattern matching will be used")

        # Configuration
        if not hasattr(self, 'ai_model'):
            self.ai_model = getattr(config, 'ai_model', 'gpt-4o-mini')
        self.temperature = getattr(config, 'temperature', 0.1)
        self.confidence_threshold = 0.4  # Minimum confidence to accept AI result (lowered from 0.7)
        
        # Tracking flags
        self.ai_explicit_rejection = False  # Track if AI explicitly rejected a message
        self.last_extraction_method = None  # Track which method extracted the signal
        self.rejection_reason: Optional[str] = None  # Human-readable reason for last rejection
        
        # Initialize image signal extractor
        self.image_extractor = ImageSignalExtractor(config)
        
        logger.info(f"IntegratedProcessor initialized with provider: {self.provider}, model: {self.ai_model}")
        
    async def process_message(
        self,
        message: str,
        image_data: Optional[bytes] = None,
        image_url: Optional[str] = None
    ) -> Optional[TradingSignal]:
        """
        Extract a signal, then apply deterministic gates to NEW trades only (reject a
        status recap, or force manual approval). Commands pass through untouched.
        """
        self.last_intent = None
        self.vision_from_untrusted_caption = False
        signal = await self._process_message_core(message, image_data, image_url)
        if signal is None:
            return None
        return self._apply_safety_gates(signal, message)

    def _instant_keyword(self, message: str) -> Optional[str]:
        """The configured instant-entry keyword this message uses ("SELL NOW"), if any."""
        from .message_guards import find_instant_keyword, DEFAULT_INSTANT_KEYWORDS
        raw = getattr(self.config, 'instant_execution_keywords', None)
        keywords = [k for k in str(raw).split(',') if k.strip()] if isinstance(raw, str) else raw
        return find_instant_keyword(message, keywords or DEFAULT_INSTANT_KEYWORDS)

    def _instant_trigger(self, signal: TradingSignal, message: str) -> Optional[str]:
        """
        Why this OPEN signal is an instant ("enter now") entry, or None.
        The extraction AI's entry_mode decides; the keyword detector is the backup
        for paths without it (AI down, vision-only, pattern matching).
        """
        if signal is None or signal.is_plan or signal.action not in (None, SignalAction.OPEN):
            return None
        mode = getattr(signal, 'entry_mode', None)
        if mode == 'market':
            return "AI entry_mode=market"
        if mode == 'pending':
            return None
        keyword = self._instant_keyword(message)
        return f"keyword '{keyword}'" if keyword else None

    def _apply_safety_gates(self, signal: TradingSignal, message: str) -> Optional[TradingSignal]:
        from .message_guards import is_status_not_command, negates_entry

        if signal.action not in (None, SignalAction.OPEN):
            return signal  # trade-management commands: the AI's decision stands

        # Entry intent is read here, once, for every extraction path (text, vision,
        # fused). Whether the channel may use it is decided later by execution_policy.
        trigger = self._instant_trigger(signal, message)
        signal.instant_execution = trigger is not None
        if trigger:
            logger.info(f"🚀 Instant entry: {trigger}")

        if self.last_intent == 'STATUS':
            if is_status_not_command(message):
                # Recaps often repeat the original entry/SL/TP ("XAUUSD BUY 4100 SL 4090
                # ✅ TP1 hit +200 pips") — extraction then sees a complete new signal.
                logger.warning("🛡️ Safety gate: OPEN extracted from a STATUS update — rejected")
                self.rejection_reason = "Status update (results/progress) — not a new trade"
                self.last_extraction_method = 'safety_gate'
                return None
            logger.warning("🛡️ Safety gate: OPEN extracted from a message classified STATUS — forcing manual approval")
            signal.force_manual_approval = True

        if self.vision_from_untrusted_caption:
            logger.warning("🛡️ Safety gate: vision-only signal from a non-trading caption — forcing manual approval")
            signal.force_manual_approval = True

        if negates_entry(message):
            logger.warning("🛡️ Safety gate: caption says no entry / wait for confirmation — forcing manual approval")
            signal.force_manual_approval = True

        return signal

    async def _process_message_core(
        self,
        message: str,
        image_data: Optional[bytes] = None,
        image_url: Optional[str] = None
    ) -> Optional[TradingSignal]:
        """
        Process message with TEXT-FIRST agent routing.
        
        Flow:
          1. Cheap pre-filters (caption keywords, image dimensions)
          2. Text AI classification FIRST (when text present)
          3. Text AI result determines if Vision AI is needed:
             - CLEAR SIGNAL (complete) → return directly, no vision
             - INCOMPLETE SIGNAL + image → fuse text direction + vision levels
             - NOT SIGNAL / STATUS → skip, no vision
          4. Image-only (no text) → vision AI directly
        """
        logger.info(f"Processing message with integrated processor: '{message[:100]}...'")
        
        # Reset extraction method tracking
        self.last_extraction_method = None
        self.ai_explicit_rejection = False
        self.rejection_reason = None
        has_image = bool(image_data or image_url)
        has_text = len(message.strip()) >= 3
        _vision_allow_analysis = False  # set True when NOT_TRADING+image path is taken

        # ── PRE-FILTERS (cheap, run before any AI call) ──────────────────────

        # Caption pre-filter: block vision if caption has non-tradeable keywords
        if has_image and self.image_extractor.caption_prefilter_enabled and has_text:
            msg_lower = message.lower()
            hit = next((kw for kw in self.image_extractor.caption_block_keywords if kw in msg_lower), None)
            if hit:
                logger.info(f"🚫 Caption pre-filter blocked vision call (keyword: '{hit}')")
                has_image = False  # treat as text-only for the rest of this method

        # Dimension pre-filter: block decorative images before vision
        if has_image and image_data:
            if isinstance(image_data, list):
                kept = []
                for img in image_data:
                    is_decorative, dim_reason = self.image_extractor.is_probably_decorative(img)
                    if is_decorative:
                        logger.info(f"🚫 Dimension pre-filter dropped album image ({dim_reason})")
                    else:
                        kept.append(img)
                image_data = kept or None
                if not image_data:
                    logger.info("🚫 All album images decorative — treating as text-only")
                    has_image = False
            else:
                is_decorative, dim_reason = self.image_extractor.is_probably_decorative(image_data)
                if is_decorative:
                    logger.info(f"🚫 Dimension pre-filter blocked vision call ({dim_reason}) — image stored for audit only")
                    has_image = False

        commands = self.image_extractor.extract_complex_commands(message)
        vision_available = bool(self.image_extractor.client)

        # ── EARLY INTENT GATE (all text messages) ──────────────────────────
        # Run cheap AI intent classification FIRST for every text message.
        # This catches non-spot content (options, stocks, commentary) before
        # the expensive full extraction runs.
        #
        # SIGNAL      → proceed with full extraction
        # COMMAND     → process text-only (commands never need charts)
        # STATUS      → process text-only (may trigger trade management)
        # NOT_TRADING → reject immediately (options, stocks, commentary, etc.)
        if has_text:
            intent = await self.classify_message_intent(message)
            self.last_intent = intent
            if intent == 'NOT_TRADING':
                if has_image and vision_available:
                    # Caption is non-trading commentary but there is a chart image —
                    # the actual signal may be visual (e.g. "scalp very small lot" as
                    # a caption on a TradingView setup chart, or "waiting confirmation"
                    # on an annotated zone chart). Skip to vision-only path and allow
                    # analysis-style images through the two-step classifier so that
                    # annotated zone/level charts can be extracted as plans.
                    logger.info(
                        "📸 Early intent gate: intent=NOT_TRADING but image present "
                        "— skipping text extraction, trying vision (allow_analysis=True)"
                    )
                    has_text = False  # suppress text-first routing below
                    _vision_allow_analysis = True  # passed to image extractor below
                    self.vision_from_untrusted_caption = True  # never auto-execute the result
                else:
                    logger.info(
                        "🚫 Early intent gate: intent=NOT_TRADING — "
                        "rejecting without extraction"
                    )
                    self.rejection_reason = (
                        "Message classified as not_trading — "
                        "not a spot trading signal"
                    )
                    self.last_extraction_method = 'intent_gate'
                    return None
            if intent in ('STATUS', 'COMMAND'):
                logger.info(
                    f"📋 Early intent gate: intent={intent} — "
                    f"proceeding text-only (no vision needed)"
                )
                # Status updates and commands may trigger trade management
                # (partial close, cancel pending, move SL) — let text AI
                # extract any actionable command. Vision is never needed.
                has_image = False

        # ── TEXT-FIRST ROUTING ──────────────────────────────────────────────
        # Text AI runs FIRST and decides whether Vision AI is needed.
        # Vision is expensive — only call it when text AI says "I have a signal
        # but need chart context for the levels."

        if has_text:
            logger.info("📝 Text detected — running text AI FIRST to classify intent")
            text_signal = await self._try_ai_processing(message)

            if text_signal:
                # ── CASE 1: Non-OPEN action = command (CLOSE, MODIFY, etc.) ──
                if text_signal.action != SignalAction.OPEN:
                    logger.info(f"✅ Text AI classified as COMMAND ({text_signal.action.value})")
                    self.last_extraction_method = 'ai'
                    text_signal.metadata = commands
                    return text_signal

                # ── CASE 2: OPEN signal — check completeness ──
                is_plan = bool(text_signal.is_plan)
                is_complete = self._is_signal_complete(text_signal)

                if is_complete and not is_plan:
                    # CLEAR SIGNAL: text has everything needed — no vision required
                    logger.info("✅ Text AI extracted CLEAR SIGNAL (complete) — skipping vision")
                    self.last_extraction_method = 'ai'
                    text_signal.metadata = commands
                    return text_signal

                if is_plan:
                    # Plans go through manual approval — text is enough
                    logger.info("📋 Text AI extracted PLAN — routing to approval, no vision needed")
                    self.last_extraction_method = 'ai'
                    text_signal.metadata = commands
                    return text_signal

                # ── CASE 3: INCOMPLETE SIGNAL — needs vision enrichment ──
                if has_image and vision_available:
                    logger.info("📝+📸 Text AI found INCOMPLETE signal — fusing with vision AI for levels")
                    fused = await self._fuse_text_and_vision(
                        message, text_signal, image_data, image_url
                    )
                    if fused:
                        fused.metadata = commands
                        return fused
                    # Fusion failed — check if partial signal is viable. An instant
                    # entry without SL goes on (temporary SL; permission checked later).
                    if not text_signal.stop_loss and not self._instant_trigger(text_signal, message):
                        logger.warning(
                            "⚠️ Vision fusion failed AND text signal missing SL — "
                            "rejecting for safety"
                        )
                        # _fuse_text_and_vision already sets a detailed rejection_reason
                        # (including the vision extractor's specific failure detail) before
                        # returning None — don't clobber it with this generic fallback.
                        self.rejection_reason = self.rejection_reason or (
                            f"Incomplete {text_signal.symbol} {text_signal.order_type.value if text_signal.order_type else '?'} "
                            "signal: vision AI could not extract SL/TP from the image, "
                            "and the text message also lacks stop loss"
                        )
                        self.last_extraction_method = 'failed'
                        return None
                    logger.warning("⚠️ Vision fusion failed — returning text signal with existing SL")
                    self.last_extraction_method = 'ai'
                    text_signal.metadata = commands
                    return text_signal

                if has_image and not vision_available:
                    if not text_signal.stop_loss and not self._instant_trigger(text_signal, message):
                        logger.warning(
                            "⚠️ Image present but no vision AI configured, "
                            "and text signal missing SL — rejecting for safety"
                        )
                        self.rejection_reason = (
                            f"Incomplete {text_signal.symbol} {text_signal.order_type.value if text_signal.order_type else '?'} "
                            "signal: image present but no vision AI key configured to extract SL/TP"
                        )
                        self.last_extraction_method = 'failed'
                        return None
                    logger.warning("📸 Image present but no vision AI — returning text signal")
                    self.last_extraction_method = 'ai'
                    text_signal.metadata = commands
                    return text_signal

                # INCOMPLETE + no image → only accept if SL is present, or it is an
                # instant entry ("SELL GOLD NOW"): that one enters on a temporary SL and
                # the follow-up message supplies the levels (signal_continuity).
                if not text_signal.stop_loss and not self._instant_trigger(text_signal, message):
                    logger.warning(
                        "⚠️ Incomplete signal with no SL and no image to enrich from — "
                        "rejecting for safety"
                    )
                    self.rejection_reason = (
                        f"Incomplete {text_signal.symbol} {text_signal.order_type.value if text_signal.order_type else '?'} "
                        "signal: no stop loss found in message and no chart image to extract from"
                    )
                    self.last_extraction_method = 'failed'
                    return None
                logger.info("📝 Incomplete signal with SL present, no image — returning as-is")
                self.last_extraction_method = 'ai'
                text_signal.metadata = commands
                return text_signal

            # ── CASE 4: Text AI found NO signal — STATUS / NOT_SIGNAL ──
            # When text clearly says "not a signal", skip vision entirely.
            # The exception: image-only signals with a garbled/non-trading caption
            # where the chart might still contain a valid setup.
            if self.ai_explicit_rejection:
                if has_image and vision_available:
                    # Run cheap intent classification FIRST to gate the vision
                    # fallback.  Messages like "TP2 DONE!" with a chart image
                    # should NOT trigger a vision call — the text clearly states
                    # a trade result/status, not a new setup.
                    intent = await self.classify_message_intent(message)
                    if intent in ('STATUS', 'NOT_TRADING', 'COMMAND'):
                        logger.info(
                            f"🚫 Text AI rejected caption + intent={intent} "
                            f"— skipping vision entirely"
                        )
                        self.rejection_reason = (
                            self.rejection_reason
                            or f"Not a trading signal — AI classified as {intent.lower()}"
                        )
                    else:
                        # Text AI rejected but intent=SIGNAL — try vision as last resort
                        # (caption may be unrelated to the chart, e.g. "check this out")
                        logger.info(
                            f"📸 Text AI rejected caption but intent={intent} "
                            f"— falling back to vision as last resort"
                        )
                        vision_signals = await self.image_extractor.process_message_with_image(
                            message, image_data, image_url
                        )
                        if vision_signals:
                            signal = vision_signals[0]
                            signal.metadata = commands
                            self.last_extraction_method = 'image_vision'
                            return signal
                        if self.image_extractor.last_rejection_reason and not self.rejection_reason:
                            self.rejection_reason = self.image_extractor.last_rejection_reason

                logger.info("🚫 Text AI classified as NOT A SIGNAL — skipping")
                self.rejection_reason = self.rejection_reason or "Not a trading signal — AI classified as commentary/status"
                self.last_extraction_method = 'failed'
                return None

            # Low-confidence AI result with no explicit rejection — try vision if available
            if has_image and vision_available:
                logger.info("📸 Text AI uncertain — trying vision")
                vision_signals = await self.image_extractor.process_message_with_image(
                    message, image_data, image_url
                )
                if vision_signals:
                    signal = vision_signals[0]
                    signal.metadata = commands
                    self.last_extraction_method = 'image_vision'
                    return signal
                if self.image_extractor.last_rejection_reason and not self.rejection_reason:
                    self.rejection_reason = self.image_extractor.last_rejection_reason

            logger.warning("AI processing failed or returned no signal — rejecting message")
            self.last_extraction_method = 'failed'
            return None

        # ── IMAGE-ONLY PATH (no text caption) ──────────────────────────────
        if has_image and vision_available:
            logger.info("📸 Image-only message — using vision-based extraction")
            image_signals = await self.image_extractor.process_message_with_image(
                message, image_data, image_url,
                allow_analysis=_vision_allow_analysis,
            )

            # Multiple setups in one image = PLAN
            if image_signals and len(image_signals) > 1:
                logger.info(f"📸 Vision found {len(image_signals)} setups — merging into plan")
                self.last_extraction_method = 'image_vision'
                plan_signal = self._merge_image_signals_into_plan(image_signals)
                plan_signal.metadata = commands
                return plan_signal

            if image_signals:
                image_signal = image_signals[0]
                if image_signal.is_plan:
                    logger.info("✅ Image-based PLAN extracted by vision AI")
                else:
                    logger.info("✅ Image-based signal extracted successfully")
                self.last_extraction_method = 'image_vision'
                image_signal.metadata = commands
                return image_signal

            if self.image_extractor.last_rejection_reason and not self.rejection_reason:
                self.rejection_reason = self.image_extractor.last_rejection_reason

            logger.info("📸 Vision model found no valid signal in image")
            self.last_extraction_method = 'failed'
            return None

        if has_image and not vision_available:
            logger.warning(
                "📸 Image present but no vision AI configured — "
                "configure an OpenAI/Gemini/Perplexity/OpenRouter/MiniMax/Qwen key for image signals"
            )

        # No text, no image — nothing to process
        logger.warning("No text and no actionable image — skipping")
        self.last_extraction_method = 'failed'
        return None

    def _is_signal_complete(self, signal: TradingSignal) -> bool:
        """
        Check if a text-extracted signal is COMPLETE enough to execute
        without needing vision AI enrichment.
        
        A complete OPEN signal must have:
        - symbol
        - order_type (BUY/SELL)
        - entry reference (entry_price or entry_range)
        - stop_loss
        """
        if not signal or signal.action != SignalAction.OPEN:
            return False
        if not signal.symbol:
            return False
        if not signal.order_type:
            return False
        has_entry = bool(
            signal.entry_price
            or (signal.entry_range_min and signal.entry_range_max)
        )
        has_sl = bool(signal.stop_loss)
        return has_entry and has_sl

    async def _fuse_text_and_vision(
        self,
        message: str,
        text_signal: TradingSignal,
        image_data: Optional[bytes] = None,
        image_url: Optional[str] = None,
    ) -> Optional[TradingSignal]:
        """
        Fuse text AI direction/authority with vision AI chart levels.
        
        Strategy:
        - Text direction (BUY/SELL) is AUTHORITATIVE — it overrides the chart.
        - Vision extracts entry, SL, TP from chart annotations.
        - Cross-check: if vision levels contradict text direction, lower confidence.
        
        Returns a fused signal, or None if fusion fails.
        """
        logger.info("🔗 Fusing text signal with vision chart analysis...")
        
        # Run vision extraction on the image
        vision_signals = await self.image_extractor.process_message_with_image(
            message, image_data, image_url
        )
        
        if not vision_signals:
            # Vision couldn't find a signal in the image.
            # If text also lacks SL (common for captions like "#XAUUSD Sell NOW"),
            # returning a signal without SL is dangerous — reject instead.
            if not text_signal.stop_loss:
                logger.warning(
                    "🔗 Vision found no signal and text has no SL — "
                    "rejecting (cannot execute without stop loss)"
                )
                detail = self.image_extractor.last_rejection_reason
                self.rejection_reason = (
                    f"Vision AI could not extract SL/TP from the chart image for "
                    f"{text_signal.symbol}, and the text message lacks a stop loss"
                    + (f" ({detail})" if detail else "")
                )
                return None
            logger.info("🔗 Vision found no signal — keeping text signal as-is (text has SL)")
            self.last_extraction_method = 'ai'
            return text_signal
        
        vision_signal = vision_signals[0]
        
        # ── Fuse: text direction wins ──────────────────────────────────────
        text_dir = text_signal.order_type
        text_symbol = text_signal.symbol
        
        # Use text direction as authoritative
        fused_order_type = text_dir
        
        # Use text symbol if available, otherwise vision's
        fused_symbol = text_symbol or vision_signal.symbol
        
        # Entry: prefer text if present, otherwise vision
        fused_entry = text_signal.entry_price or vision_signal.entry_price
        fused_entry_range_min = text_signal.entry_range_min or vision_signal.entry_range_min
        fused_entry_range_max = text_signal.entry_range_max or vision_signal.entry_range_max
        
        # SL: prefer text if present, otherwise vision
        fused_sl = text_signal.stop_loss or vision_signal.stop_loss
        
        # TP: merge both (deduplicated, text first)
        text_tps = text_signal.take_profit or []
        vision_tps = vision_signal.take_profit or []
        fused_tps = list(text_tps)
        for tp in vision_tps:
            if tp is not None and tp not in fused_tps:
                fused_tps.append(tp)
        
        # Cross-check confidence
        confidence = 0.85  # base confidence for fused signals
        vision_dir = vision_signal.order_type

        # When text provides ZERO price levels (no entry, no SL, no TP),
        # ALL values come from vision alone - penalize confidence heavily.
        text_has_prices = bool(
            text_signal.entry_price
            or text_signal.stop_loss
            or (text_signal.take_profit and any(tp is not None for tp in text_signal.take_profit))
        )
        if not text_has_prices:
            confidence = 0.60
            logger.warning(
                "Text has NO price confirmation - all SL/TP/entry from vision AI. "
                f"Confidence capped at {confidence}. Verify values before executing."
            )

        if vision_dir and text_dir and vision_dir != text_dir:
            # Direction mismatch: text says one thing, chart shows another
            # Text wins, but flag lower confidence
            confidence = 0.65
            logger.warning(
                f"⚠️ Direction mismatch: text={text_dir.value}, vision={vision_dir.value}. "
                f"Using text direction ({text_dir.value}) as authoritative. Confidence: {confidence}"
            )
        
        # Validate SL placement matches fused direction
        if fused_sl and fused_entry and fused_order_type:
            from .signal_validation import sl_side_consistent
            if sl_side_consistent(fused_order_type, fused_entry, fused_sl) is False:
                logger.warning(
                    f"⚠️ Fused signal SL ({fused_sl}) on wrong side of entry ({fused_entry}) "
                    f"for {fused_order_type.value} — using vision SL only if it's valid"
                )
                # Try vision's SL if it's on the correct side
                if vision_signal.stop_loss and vision_signal.entry_price:
                    if sl_side_consistent(fused_order_type, vision_signal.entry_price, vision_signal.stop_loss):
                        fused_sl = vision_signal.stop_loss
                        fused_entry = vision_signal.entry_price
                        confidence = max(confidence - 0.1, 0.5)
        
        # ── Build fused signal ─────────────────────────────────────────────
        fused = TradingSignal(
            symbol=fused_symbol,
            action=SignalAction.OPEN,
            order_type=fused_order_type,
            signal_type=text_signal.signal_type or vision_signal.signal_type,
            entry_price=fused_entry,
            entry_range_min=fused_entry_range_min,
            entry_range_max=fused_entry_range_max,
            stop_loss=fused_sl,
            take_profit=fused_tps,
            raw_message=message,
            confidence=confidence,
            is_plan=False,
        )
        
        # Preserve both raw model outputs (text + vision) so the dashboard shows
        # exactly what each AI returned for a fused signal.
        raw_parts = []
        if getattr(text_signal, 'ai_raw_response', None):
            raw_parts.append(f"=== TEXT AI ===\n{text_signal.ai_raw_response}")
        if getattr(vision_signal, 'ai_raw_response', None):
            raw_parts.append(f"=== VISION AI ===\n{vision_signal.ai_raw_response}")
        if raw_parts:
            fused.ai_raw_response = "\n\n".join(raw_parts)

        logger.info(
            f"🔗 Fused signal: {fused_order_type.value} {fused_symbol} "
            f"entry={fused_entry} SL={fused_sl} TP={fused_tps} confidence={confidence}"
        )
        self.last_extraction_method = 'fused'
        return fused

    async def classify_message_intent(self, message: str) -> str:
        """
        Cheap AI intent classification — runs BEFORE full signal extraction.
        
        Returns one of:
          - 'SIGNAL'     — new trading signal with entry/SL/TP
          - 'COMMAND'    — trade management (close, modify, breakeven, partial close)
          - 'STATUS'     — status update (TP hit, running pips, milestone)
          - 'NOT_TRADING' — commentary, analysis, or non-trading content
        
        Uses a short prompt and 1-token response for speed/cost.
        Falls back to 'SIGNAL' if AI is unavailable (fail-open to full extraction).
        """
        if not self.client:
            return 'SIGNAL'  # fail-open — let full extraction decide
        
        try:
            t0 = _time.monotonic()
            prompt = (
                "This is a SPOT trading bot for forex, gold/silver, crypto, and commodity futures. "
                "Classify the message into EXACTLY ONE category. "
                "The message may be in ANY language (Spanish, Arabic, Russian, Chinese, Turkish, Hindi/Urdu, etc.) - "
                "judge it by meaning. "
                "Reply with only the category name (English, exactly as listed), nothing else.\n\n"
                "Categories:\n"
                "- SIGNAL: a new SPOT trade setup with entry/stop/target levels "
                "(BUY/SELL of forex pairs, gold, silver, indices, crypto, or oil — "
                "with prices, entry zone, or chart levels). "
                "ALSO a SIGNAL: an instant entry call WITHOUT any levels — just a direction and an "
                "instrument, usually with 'now' ('GOLD SELL NOW', 'BUY GOLD NOW', 'Sell XAUUSD now!!'). "
                "The provider is entering at market and sends the levels in the next message.\n"
                "- COMMAND: managing existing spot trades (close, modify SL/TP, breakeven, "
                "partial close, cancel orders, move stop, lock profit, reduce risk)\n"
                "- STATUS: spot trade outcome or progress (TP hit, SL hit, "
                "running +X pips, profit milestone, missed entry, trade completed)\n"
                "- NOT_TRADING: anything that is NOT a spot trade — this includes: "
                "options strategies (puts, calls, spreads, credit/debit spreads, strangles, straddles), "
                "stock equity trades, bonds, futures contracts with expiration dates, "
                "market analysis without a concrete entry, commentary, advice, "
                "questions, celebrations, or any non-actionable content. "
                "If the message mentions puts, calls, IV rank, probability of profit, "
                "expiration dates, or options-specific terms → always NOT_TRADING."
            )
            
            from ai.llm_client import complete_with_fallback, provider_chain, extract_content, max_tokens_for

            def _intent_call(client, model, provider):
                return client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": f"Message: {message}"},
                    ],
                    temperature=0,
                    max_tokens=max_tokens_for(self.config, provider, output_tokens=5),
                    timeout=15.0,
                )

            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: complete_with_fallback(
                    self.config,
                    provider_chain(self.config),
                    _intent_call,
                    validate=lambda r: bool(extract_content(r).strip()),
                    caller='classify_intent',
                ),
            )
            elapsed_ms = int((_time.monotonic() - t0) * 1000)

            result = extract_content(response).strip().upper()
            # Normalize: extract the first recognized word
            valid = {'SIGNAL', 'COMMAND', 'STATUS', 'NOT_TRADING'}
            for word in result.split():
                if word in valid:
                    logger.info(f"🎯 Intent classification: {word} ({elapsed_ms}ms)")
                    return word
            
            logger.warning(f"⚠️ Unrecognized intent '{result}' — defaulting to SIGNAL")
            return 'SIGNAL'
            
        except Exception as e:
            logger.warning(f"⚠️ Intent classification failed: {e} — defaulting to SIGNAL")
            return 'SIGNAL'

    async def classify_signal_continuity_relationship(
        self,
        new_message: str,
        candidates: List[dict],
    ) -> dict:
        """
        Classifies relationship of a new signal message to existing candidate active signals
        from the same channel within the continuity window.

        Returns dict:
          {
             "relationship": "NEW" | "FOLLOW_UP" | "CORRECTION" | "DUPLICATE",
             "parent_id": str or None,
             "reason": str
          }
        """
        if not candidates:
            return {"relationship": "NEW", "parent_id": None, "reason": "No candidates"}
        if not self.client:
            # Not "NEW": that answer is final for the caller and skipped its own rules
            # (instant entry awaiting levels, repost of a deleted signal, same setup),
            # so without an AI client every follow-up opened a second trade.
            return {"relationship": "UNKNOWN", "parent_id": None, "reason": "No AI client"}

        try:
            t0 = _time.monotonic()
            
            # Format candidate summaries
            cand_summaries = []
            for i, c in enumerate(candidates, 1):
                cand_summaries.append(
                    f"Candidate #{i} (ID: {c.get('id', '')[:8]}, MsgID: {c.get('message_id')}, "
                    f"{c.get('minutes_ago', 0):.1f} min ago):\n"
                    f"  - Symbol: {c.get('symbol')} | Order: {c.get('order_type')}\n"
                    f"  - Levels: Entry={c.get('entry')} | SL={c.get('stop_loss')} | TP={c.get('take_profit')}\n"
                    f"  - State: was_deleted={c.get('was_deleted', False)}, is_awaiting_levels={c.get('is_awaiting_levels', False)}, "
                    f"has_open_position={c.get('has_open_position', False)} (open_price={c.get('open_position_price')})\n"
                    f"  - Original text: {repr(c.get('raw_message', '')[:120])}"
                )
            candidates_text = "\n\n".join(cand_summaries)

            prompt = (
                "You are an expert trading signal analyzer for a forex/commodity spot trading bot.\n"
                "A Telegram channel just posted a NEW trade message. We already have active/recent signal(s) "
                "from this channel in the same symbol and direction.\n\n"
                "Determine the EXACT relationship between the new message and the candidate signal(s):\n"
                "1. 'NEW': This is a completely distinct, independent trade setup (new trade, separate risk budget). "
                "IMPORTANT: If an earlier trade has already filled and is running (has_open_position=True), a new "
                "'SELL NOW' or 'BUY NOW' message or a new setup with new entries is a NEW trade, NOT a correction or follow-up.\n"
                "2. 'FOLLOW_UP': The earlier signal entered instantly on a temporary stop loss without levels "
                "(is_awaiting_levels=True), and this new message provides the real entry levels, SL, and TP for THAT entry.\n"
                "3. 'CORRECTION': The channel is correcting/updating an existing setup's levels (e.g. SL or TP was revised, "
                "or the original message was deleted before filling and reposted with corrected numbers).\n"
                "4. 'DUPLICATE': The identical setup was posted again (e.g. chart screenshot followed by verbatim text recap).\n\n"
                "CRITICAL RULES:\n"
                "- When in doubt between NEW and CORRECTION/FOLLOW_UP, prefer NEW if a position is already open and running. "
                "Never merge an independent second trade into an older trade!\n"
                "- If the new message is NEW, parent_id must be null.\n"
                "- If FOLLOW_UP, CORRECTION, or DUPLICATE, specify the matching candidate's exact ID in parent_id.\n\n"
                "Respond ONLY with valid JSON in this exact schema:\n"
                '{"relationship": "NEW"|"FOLLOW_UP"|"CORRECTION"|"DUPLICATE", "parent_id": "<candidate_id_or_null>", "reason": "<one sentence explanation>"}'
            )

            from ai.llm_client import complete_with_fallback, provider_chain, extract_content, max_tokens_for

            def _rel_call(client, model, provider):
                return client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": f"New Message: {new_message}\n\nExisting Signals:\n{candidates_text}"},
                    ],
                    temperature=0,
                    max_tokens=max_tokens_for(self.config, provider, output_tokens=150),
                    timeout=15.0,
                )

            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: complete_with_fallback(
                    self.config,
                    provider_chain(self.config),
                    _rel_call,
                    validate=lambda r: bool(extract_content(r).strip()),
                    caller='classify_signal_continuity',
                ),
            )
            elapsed_ms = int((_time.monotonic() - t0) * 1000)
            raw_text = extract_content(response).strip()
            
            import json as _json, re as _re
            match = _re.search(r'\{.*\}', raw_text, _re.DOTALL)
            if match:
                data = _json.loads(match.group(0))
                rel = str(data.get("relationship", "NEW")).upper()
                if rel not in {"NEW", "FOLLOW_UP", "CORRECTION", "DUPLICATE"}:
                    rel = "NEW"
                pid = data.get("parent_id")
                matched_id = None
                if pid and rel != "NEW":
                    for c in candidates:
                        if c.get("id") == pid or c.get("id", "").startswith(str(pid)):
                            matched_id = c.get("id")
                            break
                    if not matched_id and len(candidates) == 1:
                        matched_id = candidates[0].get("id")
                
                logger.info(f"🤖 Signal continuity classification: {rel} ({elapsed_ms}ms) -> parent {matched_id[:8] if matched_id else 'None'}: {data.get('reason')}")
                return {
                    "relationship": rel,
                    "parent_id": matched_id if rel != "NEW" else None,
                    "reason": data.get("reason", "")
                }
            
            logger.warning(f"⚠️ Could not parse JSON from continuity classification: {raw_text[:100]}")
            return {"relationship": "UNKNOWN", "parent_id": None, "reason": "Failed to parse JSON response"}
        except Exception as e:
            logger.warning(f"⚠️ Continuity classification failed: {e}")
            return {"relationship": "UNKNOWN", "parent_id": None, "reason": f"AI error: {str(e)}"}

    # ── Multi-signal posts ────────────────────────────────────────────────

    MAX_SIGNAL_BLOCKS = 4
    _DIRECTION_RE = re.compile(r'\b(?:buy|sell|long|short)\b', re.IGNORECASE)
    _SL_PRICE_RE = re.compile(r'\b(?:sl|stop\s*loss|stoploss)\b[^0-9\n]{0,12}\d', re.IGNORECASE)
    _NUMBER_RE = re.compile(r'\d+(?:[.,]\d+)?')

    @classmethod
    def looks_multi_trade(cls, message: str) -> bool:
        """Cheap, no-AI gate: several directions AND several stop-losses with prices. A single setup with
        TP1/TP2 or several entry legs has one SL; a breakout plan ('buy above / sell below') has one or none."""
        if not message or len(message) < 40:
            return False
        directions = len(cls._DIRECTION_RE.findall(message))
        stops = len(cls._SL_PRICE_RE.findall(message))
        return directions >= 2 and stops >= 2

    @classmethod
    def _numbers(cls, text: str) -> set:
        return {n.replace(',', '.') for n in cls._NUMBER_RE.findall(text or '')}

    async def split_signal_blocks(self, message: str) -> List[str]:
        """
        Split a message holding SEVERAL independent trades into one self-contained block per trade.
        Returns [message] (unchanged) when it is a single setup, when the AI is unavailable, or when the
        AI output fails validation - so the worst case is the old single-signal behaviour.
        """
        if not self.client or not self.looks_multi_trade(message):
            return [message]
        try:
            prompt = (
                "A trading channel posted ONE message. Decide whether it contains MORE THAN ONE independent "
                "trade setup, where each setup has its OWN direction, entry and stop loss "
                "(for example 'BUY XAUUSD 2300 SL 2290 TP 2330' followed by 'SELL EURUSD 1.08 SL 1.085 TP 1.07').\n"
                "Keep as ONE block (do NOT split): a single setup with several entries or TP1/TP2/TP3, a breakout "
                "plan with both 'buy above X / sell below Y' levels, a setup plus commentary or a recap, "
                "or anything you are unsure about.\n"
                "If you split: copy each trade's text VERBATIM (never change, add or remove a price). If a shared "
                "header names the symbol for all trades, prepend that header words to each block. "
                f"At most {self.MAX_SIGNAL_BLOCKS} blocks.\n"
                'Reply with JSON only: {"blocks": ["<block 1>", "<block 2>"]}  (one element when not splitting).'
            )
            from ai.llm_client import complete_with_fallback, provider_chain, extract_content, max_tokens_for

            def _call(client, model, provider):
                return client.chat.completions.create(
                    model=model,
                    messages=[{"role": "system", "content": prompt}, {"role": "user", "content": message}],
                    temperature=0,
                    max_tokens=max_tokens_for(self.config, provider, output_tokens=900),
                    timeout=20.0,
                )

            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: complete_with_fallback(
                    self.config, provider_chain(self.config), _call,
                    validate=lambda r: bool(extract_content(r).strip()), caller='split_signal_blocks',
                ),
            )
            raw = extract_content(response).strip()
            raw = re.sub(r'^```(?:json)?|```$', '', raw, flags=re.MULTILINE).strip()
            blocks = json.loads(raw).get("blocks")
            return self._validated_blocks(message, blocks)
        except Exception as e:
            logger.warning(f"⚠️ Multi-signal split failed ({e}) - treating as a single message")
            return [message]

    def _validated_blocks(self, message: str, blocks) -> List[str]:
        """Accept an AI split only if every block is non-trivial and uses ONLY numbers present in the original."""
        if not isinstance(blocks, list) or len(blocks) < 2:
            return [message]
        blocks = [b.strip() for b in blocks if isinstance(b, str) and b.strip()][: self.MAX_SIGNAL_BLOCKS]
        if len(blocks) < 2:
            return [message]
        original = self._numbers(message)
        for b in blocks:
            if len(b) < 15 or not self._numbers(b) or not self._numbers(b) <= original:
                logger.warning("⚠️ Multi-signal split rejected: a block altered or invented a number")
                return [message]
        # every block needs its own stop loss, otherwise it is a fragment, not a trade
        if sum(1 for b in blocks if self._SL_PRICE_RE.search(b)) < 2:
            return [message]
        return blocks

    async def _try_ai_processing(self, message: str) -> Optional[TradingSignal]:
        """
        Try processing with AI (OpenAI)
        
        Args:
            message: Message to process
            
        Returns:
            TradingSignal or None
        """
        # Reset rejection flag (will be set by _parse_response if needed)
        self.ai_explicit_rejection = False
        
        if not self.client:
            logger.debug("AI client not available, skipping AI processing")
            return None
        
        try:
            t0 = _time.monotonic()
            system_prompt = self.get_system_prompt()
            from ai.llm_client import complete_with_fallback, provider_chain, extract_content, max_tokens_for

            def _extract_call(client, model, provider):
                return client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": message}
                    ],
                    temperature=self.temperature,
                    timeout=30.0,
                    max_tokens=max_tokens_for(self.config, provider, output_tokens=1500),
                )

            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: complete_with_fallback(
                    self.config,
                    provider_chain(self.config),
                    _extract_call,
                    validate=lambda r: bool(extract_content(r).strip()),
                    caller='signal_extraction',
                ),
            )
            elapsed_ms = int((_time.monotonic() - t0) * 1000)
            logger.info(f"⏱️ Text AI extraction: {elapsed_ms}ms")

            content = extract_content(response)
            signal = self._parse_response(content, message)

            if signal:
                logger.debug(f"AI extracted signal: {signal.__dict__}")
                # Preserve the verbatim model output for dashboard inspection
                signal.ai_raw_response = content

            return signal
            
        except Exception as e:
            logger.error(f"AI processing error: {e}")
            self.rejection_reason = f"Text AI error: {e}"
            return None
    
    async def _try_pattern_matching(self, message: str) -> Optional[TradingSignal]:
        """
        Try processing with simple pattern matching
        
        Args:
            message: Message to process
            
        Returns:
            TradingSignal or None
        """
        try:
            logger.debug("Attempting pattern matching fallback")
            
            # Normalize message
            msg_upper = message.upper()
            
            # Extract action first (to determine if symbol is required)
            action, order_type, signal_type = self._extract_action_pattern(message)
            if not action:
                logger.debug("Pattern matching: Could not extract action")
                return None
            
            # Log detected signal type for STOP orders
            if signal_type:
                logger.debug(f"Pattern matching: Detected explicit signal_type: {signal_type.value}")
            
            # Extract symbol (optional for CLOSE/MODIFY actions)
            symbol = self._extract_symbol_pattern(message)
            
            # Symbol is required for OPEN actions, optional for others
            if action == SignalAction.OPEN and not symbol:
                logger.debug("Pattern matching: Could not extract symbol for OPEN action")
                return None
            
            # For CLOSE/MODIFY without symbol, it will be injected by message handler from context
            if not symbol and action in [SignalAction.CLOSE, SignalAction.PARTIAL_CLOSE, SignalAction.MODIFY]:
                logger.debug(f"Pattern matching: No symbol for {action.value} action - will be injected from context")
            
            # Extract prices and percentage based on action
            entry_price = None
            stop_loss = None
            take_profit = None
            percentage_close = None
            
            if action == SignalAction.OPEN:
                # Check if message is analysis/commentary (reject these)
                analysis_keywords = [
                    'SCENARIO', 'ANALYSIS', 'EXPECTING', 'BULLISH', 'BEARISH', 'CHOCH',
                    'LIQUIDITY SWEEP', 'ORDER BLOCK', 'QML', 'ZONE FOR', 'SAME AREA',
                    'WE FINALLY HAVE', 'I THINK', 'MY VIEW', 'IN MY OPINION', 'LIKELY',
                    'SHOULD', 'COULD', 'MIGHT', 'PROBABLY', 'POSSIBLY'
                ]
                is_analysis = any(keyword in msg_upper for keyword in analysis_keywords)
                
                # For OPEN signals, extract entry range first, then single entry, SL, TP
                entry_range_min, entry_range_max = self._extract_entry_range_pattern(message)
                entry_price = self._extract_entry_pattern(message)
                entry_legs = self._extract_entry_legs_pattern(message)
                if entry_legs and not entry_price:
                    entry_price = entry_legs[0]
                stop_loss = self._extract_sl_pattern(message)
                take_profit = self._extract_tp_pattern(message)
                
                # CRITICAL: Convert pip-based TPs to actual price levels
                # Detect if TP values are in pips (small numbers) vs price levels
                if take_profit and entry_price and order_type:
                    # Check if TPs look like pips (small numbers relative to entry price)
                    # For XAUUSD with entry ~4800, TP values like 100/200 are clearly pips
                    # TP values like 4900/5000 are price levels
                    if take_profit and len(take_profit) > 0:
                        # If all TP values are much smaller than entry price, they're likely pips
                        # Example: entry=4807, TP=[100, 200] → these are pips
                        # Example: entry=4807, TP=[4900, 5000] → these are price levels
                        avg_tp = sum(take_profit) / len(take_profit)
                        if entry_price > 100 and avg_tp < entry_price * 0.5:
                            logger.info(f"🎯 Detected pip-based TPs: {take_profit} (entry={entry_price})")
                            take_profit = self._convert_pips_to_price(take_profit, entry_price, symbol, order_type)
                            logger.info(f"   Converted to price levels: {take_profit}")
                
                # REQUIREMENT 1: Reject if analysis commentary without explicit entry
                if is_analysis and not entry_price:
                    logger.debug("Pattern matching: Message is market analysis/commentary without explicit entry - rejecting")
                    return None
                
                # REQUIREMENT 2: For STOP orders, entry price is REQUIRED
                if signal_type in [SignalType.BUY_STOP, SignalType.SELL_STOP]:
                    if not entry_price:
                        logger.debug("Pattern matching: STOP order requires entry price")
                        return None
                    logger.debug(f"Pattern matching: {signal_type.value} order with entry at {entry_price}")
                # For other orders, require entry price OR explicit NOW/MARKET command
                elif not entry_price:
                    if self._instant_keyword(message) is not None:
                        logger.debug("Pattern matching: No entry price, treating as market order")
                        entry_price = None  # Will be filled by smart defaults
                    else:
                        logger.debug("Pattern matching: REJECTED - no entry price and not a market order")
                        return None
                
                # REQUIREMENT 3: Must have stop loss (MANDATORY for safety)
                if not stop_loss:
                    logger.debug("Pattern matching: REJECTED - missing stop loss (mandatory for all OPEN signals)")
                    return None
                
                logger.debug(f"✅ Pattern matching OPEN signal validation passed: symbol={symbol}, entry={entry_price or 'NOW'}, SL={stop_loss}")
            
            elif action == SignalAction.PARTIAL_CLOSE:
                # For PARTIAL_CLOSE, extract percentage
                percentage_close = self._extract_percentage_pattern(message)
                if not percentage_close:
                    logger.debug("Pattern matching: Could not extract percentage for partial close")
                    percentage_close = 50.0  # Default to 50%
            
            elif action == SignalAction.MODIFY:
                # For MODIFY, extract new SL and/or TP
                stop_loss = self._extract_sl_pattern(message)
                take_profit = self._extract_tp_pattern(message)
                
                # Check for breakeven
                is_breakeven = any(word in msg_upper for word in ['BREAKEVEN', 'BREAK EVEN', 'BE', 'SET BE'])
                if is_breakeven:
                    # Breakeven will be handled by setting SL to entry (done in message handler)
                    logger.debug("Pattern matching: Detected breakeven request")
                
                # CRITICAL: MODIFY signals MUST have either SL, TP, or breakeven keyword
                # Otherwise it's just an update message like "SET SL❤️" not a trading instruction
                if not stop_loss and not take_profit and not is_breakeven:
                    logger.debug("Pattern matching: MODIFY action detected but no SL/TP/breakeven value found - rejecting as update message")
                    return None
            
            elif action == SignalAction.CLOSE:
                # For CLOSE, no additional data needed
                logger.debug("Pattern matching: Close action detected")
            
            # CRITICAL: Validate SL placement for OPEN signals (same as AI validation)
            if action == SignalAction.OPEN and entry_price and stop_loss and order_type:
                is_buy = (order_type == OrderType.BUY)
                sl_below_entry = stop_loss < entry_price
                
                # For BUY: SL must be BELOW entry
                # For SELL: SL must be ABOVE entry
                if is_buy and not sl_below_entry:
                    logger.error(f"🚨 Pattern matching INVALID BUY signal: SL ({stop_loss}) is ABOVE entry ({entry_price})")
                    logger.error("    This would result in immediate stop out! Rejecting signal.")
                    return None
                elif not is_buy and sl_below_entry:
                    logger.error(f"🚨 Pattern matching INVALID SELL signal: SL ({stop_loss}) is BELOW entry ({entry_price})")
                    logger.error("    This would result in immediate stop out! Rejecting signal.")
                    return None
                
                logger.debug(f"✅ Pattern matching SL placement validated: {'BUY' if is_buy else 'SELL'} with SL {'below' if sl_below_entry else 'above'} entry")
            
            # CRITICAL: Validate TP direction for OPEN signals
            if action == SignalAction.OPEN and entry_price and order_type and take_profit:
                is_buy = (order_type == OrderType.BUY)
                valid_tps = []
                for i, tp_val in enumerate(take_profit):
                    if tp_val is None:
                        continue
                    if is_buy and tp_val <= entry_price:
                        logger.error(
                            f"🚨 Pattern matching INVALID TP{i+1} for BUY: TP ({tp_val}) <= entry ({entry_price}). Removing."
                        )
                    elif not is_buy and tp_val >= entry_price:
                        logger.error(
                            f"🚨 Pattern matching INVALID TP{i+1} for SELL: TP ({tp_val}) >= entry ({entry_price}). Removing."
                        )
                    else:
                        valid_tps.append(tp_val)
                
                if len(valid_tps) < len([tp for tp in take_profit if tp is not None]):
                    logger.warning(
                        f"⚠️ Pattern matching: {len(take_profit) - len(valid_tps)} TP(s) removed. "
                        f"Original: {take_profit}, Valid: {valid_tps}"
                    )
                take_profit = valid_tps
            
            # Multi-entry scale-in legs — only for OPEN, drop legs on wrong side of SL
            entries = None
            if action == SignalAction.OPEN and entry_legs and len(entry_legs) >= 2:
                if stop_loss and order_type:
                    entry_legs = [
                        lg for lg in entry_legs
                        if sl_side_consistent(order_type, lg, stop_loss) is not False
                    ]
                if len(entry_legs) >= 2:
                    entries = entry_legs
                    logger.info(f"🪜 Pattern matching: multi-entry (scale-in) legs {entries}")

            # Create signal
            signal = TradingSignal(
                symbol=symbol,
                action=action,
                order_type=order_type,
                signal_type=signal_type,  # Explicitly set for STOP/LIMIT orders
                entry_price=entry_price,
                entries=entries,
                entry_range_min=entry_range_min if action == SignalAction.OPEN else None,
                entry_range_max=entry_range_max if action == SignalAction.OPEN else None,
                stop_loss=stop_loss,
                take_profit=take_profit if take_profit else [],
                lot_size=None,
                percentage_close=percentage_close,
                raw_message=message
            )
            
            logger.debug(f"Pattern matching extracted signal: {signal.__dict__}")
            return signal
            
        except Exception as e:
            logger.error(f"Pattern matching error: {e}")
            return None
    
    def _extract_symbol_pattern(self, message: str) -> Optional[str]:
        """Extract symbol using pattern matching - Comprehensive symbol mapping"""
        # Comprehensive symbol patterns with aliases
        symbols = {
            # Precious Metals
            'GOLD': 'XAUUSD', 'XAU': 'XAUUSD', 'XAUUSD': 'XAUUSD',
            'SILVER': 'XAGUSD', 'XAG': 'XAGUSD', 'XAGUSD': 'XAGUSD',
            
            # Major Forex Pairs
            'EUR': 'EURUSD', 'EURUSD': 'EURUSD', 'EUR/USD': 'EURUSD',
            'GBP': 'GBPUSD', 'GBPUSD': 'GBPUSD', 'GBP/USD': 'GBPUSD', 'CABLE': 'GBPUSD',
            'USD/JPY': 'USDJPY', 'USDJPY': 'USDJPY', 'JPY': 'USDJPY',
            'AUD': 'AUDUSD', 'AUDUSD': 'AUDUSD', 'AUD/USD': 'AUDUSD', 'AUSSIE': 'AUDUSD',
            'NZD': 'NZDUSD', 'NZDUSD': 'NZDUSD', 'NZD/USD': 'NZDUSD', 'KIWI': 'NZDUSD',
            'USD/CAD': 'USDCAD', 'USDCAD': 'USDCAD', 'CAD': 'USDCAD', 'LOONIE': 'USDCAD',
            'USD/CHF': 'USDCHF', 'USDCHF': 'USDCHF', 'CHF': 'USDCHF', 'SWISSY': 'USDCHF',
            
            # Cross Pairs
            'EUR/GBP': 'EURGBP', 'EURGBP': 'EURGBP',
            'EUR/JPY': 'EURJPY', 'EURJPY': 'EURJPY',
            'GBP/JPY': 'GBPJPY', 'GBPJPY': 'GBPJPY',
            'AUD/JPY': 'AUDJPY', 'AUDJPY': 'AUDJPY',
            
            # Indices
            'US30': 'US30', 'DOW': 'US30', 'DJIA': 'US30', 'DOW JONES': 'US30',
            'NAS100': 'NAS100', 'NASDAQ': 'NAS100', 'NDX': 'NAS100',
            'US500': 'US500', 'SPX': 'US500', 'S&P': 'US500', 'SP500': 'US500',
            'GER30': 'GER30', 'DAX': 'GER30', 'GER40': 'GER40',
            'UK100': 'UK100', 'FTSE': 'UK100',
            'JP225': 'JP225', 'NIKKEI': 'JP225',
            
            # Commodities
            'OIL': 'USOIL', 'CRUDE': 'USOIL', 'WTI': 'USOIL', 'USOIL': 'USOIL',
            'BRENT': 'UKOIL', 'UKOIL': 'UKOIL',
            'GAS': 'NATGAS', 'NATURAL GAS': 'NATGAS', 'NATGAS': 'NATGAS',
            
            # Crypto
            'BTC': 'BTCUSD', 'BITCOIN': 'BTCUSD', 'BTCUSD': 'BTCUSD',
            'ETH': 'ETHUSD', 'ETHEREUM': 'ETHUSD', 'ETHUSD': 'ETHUSD',
            'XRP': 'XRPUSD', 'RIPPLE': 'XRPUSD', 'XRPUSD': 'XRPUSD',
        }
        
        msg_upper = message.upper()
        
        # Try exact matches first (longer strings first to avoid partial matches)
        sorted_symbols = sorted(symbols.items(), key=lambda x: len(x[0]), reverse=True)
        for key, value in sorted_symbols:
            if key in msg_upper:
                return value
        
        return None
    
    def _extract_action_pattern(self, message: str) -> tuple:
        """Extract action and order type - Comprehensive action detection
        Returns: (SignalAction, OrderType, SignalType)
        """
        msg_upper = message.upper()
        
        # Priority 1: Check for CLOSE actions (full or partial)
        close_all_keywords = [
            'CLOSE ALL', 'CLOSE POSITION', 'EXIT ALL', 'CLOSE TRADE',
            'CLOSE EVERYTHING', 'EXIT POSITION', 'FULL CLOSE', 'CLOSE FULL'
        ]
        if any(word in msg_upper for word in close_all_keywords):
            return SignalAction.CLOSE, None, None
        
        # Check for partial close with percentage
        partial_patterns = [
            r'CLOSE\s+(\d+)%',
            r'PARTIAL\s+CLOSE\s+(\d+)%',
            r'CLOSE\s+(\d+)\s*PERCENT',
            r'EXIT\s+(\d+)%',
            r'TAKE\s+(\d+)%',
            r'BOOK\s+(\d+)%',
            r'(\d+)%\s+PROFIT',
        ]
        for pattern in partial_patterns:
            match = re.search(pattern, msg_upper)
            if match:
                return SignalAction.PARTIAL_CLOSE, None, None
        
        # Check for simple close/exit
        close_keywords = ['CLOSE', 'EXIT', 'CLOSE POSITION', 'CLOSE TRADE', 'TAKE PROFIT']
        if any(word in msg_upper for word in close_keywords):
            return SignalAction.CLOSE, None, None
        
        # Priority 2: Check for CANCEL actions
        cancel_keywords = [
            'CANCEL', 'DELETE', 'REMOVE ORDER', 'CANCEL ORDER',
            'DELETE ORDER', 'CANCEL PENDING', 'REMOVE PENDING',
            'CANCEL ALL', 'DELETE ALL PENDING'
        ]
        if any(word in msg_upper for word in cancel_keywords):
            return SignalAction.CLOSE, None, None  # Treat cancel as close for pending orders
        
        # Priority 3: Check for MODIFY actions (SL/TP updates, breakeven)
        modify_keywords = [
            # SL modifications
            'MOVE SL', 'UPDATE SL', 'CHANGE SL', 'NEW SL', 'SL TO', 'ADJUST SL',
            'SHIFT SL', 'SET SL', 'SL AT', 'STOP TO', 'MOVE STOP',
            
            # TP modifications
            'MOVE TP', 'UPDATE TP', 'CHANGE TP', 'NEW TP', 'TP TO', 'ADJUST TP',
            'SHIFT TP', 'SET TP', 'TP AT', 'TARGET TO', 'MOVE TARGET',
            
            # Breakeven
            'BREAKEVEN', 'BREAK EVEN', 'BE', 'SET BE', 'MOVE TO BE',
            'BREAK-EVEN', 'B/E', 'SET BREAK EVEN', 'MOVE TO BREAKEVEN',
            
            # General modify
            'MODIFY', 'UPDATE', 'CHANGE STOP', 'CHANGE TARGET', 'ADJUST',
            'EDIT', 'AMEND'
        ]
        if any(keyword in msg_upper for keyword in modify_keywords):
            return SignalAction.MODIFY, None, None
        
        # Priority 4: Check for OPEN signals (BUY/SELL)
        # IMPORTANT: Only use explicit text keywords, NO emoji detection
        # Emojis are too ambiguous (celebration vs. signal) and cause false positives
        
        # Detect specific order types first (STOP orders have priority)
        # Check for BUY STOP (must check before general BUY)
        if 'BUY STOP' in msg_upper:
            return SignalAction.OPEN, OrderType.BUY, SignalType.BUY_STOP
        
        # Check for SELL STOP (must check before general SELL)
        if 'SELL STOP' in msg_upper:
            return SignalAction.OPEN, OrderType.SELL, SignalType.SELL_STOP
        
        # Check for BUY LIMIT (must check before general BUY)
        if 'BUY LIMIT' in msg_upper:
            return SignalAction.OPEN, OrderType.BUY, SignalType.BUY_LIMIT
        
        # Check for SELL LIMIT (must check before general SELL)
        if 'SELL LIMIT' in msg_upper:
            return SignalAction.OPEN, OrderType.SELL, SignalType.SELL_LIMIT
        
        # General buy signals (will be auto-detected as LIMIT if entry_price is specified)
        buy_keywords = [
            'BUY', 'BUYING', 'LONG', 'GOING LONG', 'ENTER LONG',
            'BUY MARKET', 'BUY NOW',
            'LONG POSITION', 'OPEN BUY', 'ENTER BUY'
        ]
        
        if any(word in msg_upper for word in buy_keywords):
            return SignalAction.OPEN, OrderType.BUY, None  # None = will be auto-detected
        
        # General sell signals (will be auto-detected as LIMIT if entry_price is specified)
        sell_keywords = [
            'SELL', 'SELLING', 'SHORT', 'GOING SHORT', 'ENTER SHORT',
            'SELL MARKET', 'SELL NOW',
            'SHORT POSITION', 'OPEN SELL', 'ENTER SELL'
        ]
        
        if any(word in msg_upper for word in sell_keywords):
            return SignalAction.OPEN, OrderType.SELL, None  # None = will be auto-detected
        
        return None, None, None
    
    def _extract_entry_pattern(self, message: str) -> Optional[float]:
        """Extract entry price - Comprehensive entry detection"""
        # Comprehensive entry patterns (allow no space: entry113000)
        # NOTE: NO emoji patterns - emojis are ambiguous and cause false positives
        patterns = [
            r'ENTRY[:\s]*(\d+\.?\d*)',
            r'ENTER\s+AT[:\s]*(\d+\.?\d*)',
            r'ENTRY\s+AT[:\s]*(\d+\.?\d*)',
            r'ENTRY\s+PRICE[:\s]*(\d+\.?\d*)',
            r'@\s*(\d+\.?\d*)',
            r'AT\s+(\d+\.?\d*)',
            r'NOW[:\s]+(\d+\.?\d*)',
            r'PRICE[:\s]+(\d+\.?\d*)',
            r'OPEN[:\s]+(\d+\.?\d*)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1))
                except Exception as _exc:
                    logger.debug(f"Suppressed exception: {_exc!r}")
        
        # Fallback: find any reasonable price number
        numbers = re.findall(r'\d+\.\d+', message)
        for num_str in numbers:
            try:
                num = float(num_str)
                # Gold/Silver range
                if num > 1000:
                    return num
                # Forex major pairs range
                elif num > 0.5 and num < 2.0:
                    return num
                # Indices range
                elif num > 10000:
                    return num
            except Exception as _exc:
                logger.debug(f"Suppressed exception: {_exc!r}")
        
        # If no entry price found but message says "now", return None to signal market order
        # This will be handled by smart defaults
        return None
    
    def _extract_entry_legs_pattern(self, message: str) -> Optional[list]:
        """
        Detect discrete scale-in entries like "SELL NOW @ 4081 / MORE SELL @ 4091".

        Returns an ordered list of >=2 distinct leg prices (primary first) when the
        message clearly signals additional same-direction entries, else None. A single
        "@ price" or a "min-max" range is NOT a scale-in and returns None.
        """
        # A scale-in requires an explicit "add another entry" cue somewhere.
        cue = re.search(r'\b(MORE|ADD|2ND|3RD|SECOND|THIRD|ALSO|ANOTHER)\b', message, re.IGNORECASE)
        if not cue:
            return None

        # Collect every "@ price" / "at price" occurrence in order of appearance.
        legs: list = []
        seen: set = set()
        for m in re.finditer(r'(?:@|\bAT\b)\s*(\d+\.?\d*)', message, re.IGNORECASE):
            try:
                price = float(m.group(1))
            except (TypeError, ValueError):
                continue
            # Skip values that are part of a "a - b" range (handled as a zone elsewhere)
            if price > 0 and price not in seen:
                seen.add(price)
                legs.append(price)

        if len(legs) >= 2:
            logger.info(f"🎯 Pattern match scale-in legs detected: {legs}")
            return legs
        return None

    def _extract_entry_range_pattern(self, message: str) -> tuple[Optional[float], Optional[float]]:
        """Extract entry price range - Returns (min, max) or (None, None)"""
        # Patterns for range detection like "5000 - 4995" or "Buy Zone 5000-4995"
        range_patterns = [
            r'(?:BUY|SELL|ENTRY|ZONE)?\s*(?:ZONE|LEVELS|PRICE)?[:\s@]*(\d+\.?\d*)\s*[-–—/]\s*(\d+\.?\d*)',
            r'(?:ENTRY|PRICE)?\s*RANGE[:\s]*(\d+\.?\d*)\s*[-–—/]\s*(\d+\.?\d*)',
            r'(\d+\.?\d*)\s*[-–—/]\s*(\d+\.?\d*)(?:\s*(?:ZONE|RANGE))?',
        ]
        
        for pattern in range_patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                try:
                    price1 = float(match.group(1))
                    price2 = float(match.group(2))
                    
                    # Basic validation: ensure both are positive and not the same
                    if price1 > 0 and price2 > 0 and abs(price1 - price2) > 0.000001:
                        # Ensure we don't accidentally pick up dates or timestamps
                        # (Most trading prices aren't integers like 2024 or 12345678)
                        if (price1 < 100000 and price2 < 100000):
                            logger.info(f"🎯 Pattern match range detected: {price1} - {price2}")
                            return (min(price1, price2), max(price1, price2))
                except Exception as _exc:
                    logger.debug(f"Suppressed exception: {_exc!r}")
        
        return (None, None)

    
    def _extract_sl_pattern(self, message: str) -> Optional[float]:
        """Extract stop loss - Comprehensive SL detection"""
        patterns = [
            # Standalone SL formats (most common in Muru channel)
            r'SL\s+IS\s+(\d+\.?\d*)',  # "SL is 4661.7"
            r'SL\s+(\d+\.?\d*)',  # "SL 4963.5"
            r'SL[:\s]+(\d+\.?\d*)',  # "SL: 4661.7" or "SL 4661.7"
            
            # Standard formats (allow no space: sl111000)
            r'STOP\s*LOSS[:\s]*(\d+\.?\d*)',
            r'STOP[:\s]*(\d+\.?\d*)',
            r'STOPLOSS[:\s]*(\d+\.?\d*)',
            
            # Modification formats
            r'SL\s+TO\s+(\d+\.?\d*)',
            r'MOVE\s+SL\s+TO\s+(\d+\.?\d*)',
            r'UPDATE\s+SL\s+TO\s+(\d+\.?\d*)',
            r'CHANGE\s+SL\s+TO\s+(\d+\.?\d*)',
            r'NEW\s+SL[:\s]+(\d+\.?\d*)',
            r'SET\s+SL\s+TO\s+(\d+\.?\d*)',
            r'ADJUST\s+SL\s+TO\s+(\d+\.?\d*)',
            
            # Alternative formats
            r'SL\s+AT\s+(\d+\.?\d*)',
            r'STOP\s+AT\s+(\d+\.?\d*)',
            r'STOP\s+TO\s+(\d+\.?\d*)',
            
            # Pip-based (will need conversion)
            r'SL[:\s]+(\d+)\s*PIPS?',
            r'STOP[:\s]+(\d+)\s*PIPS?',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1))
                except Exception as _exc:
                    logger.debug(f"Suppressed exception: {_exc!r}")
        
        return None
    
    def _extract_tp_pattern(self, message: str) -> Optional[list]:
        """Extract take profit levels - Comprehensive TP detection"""
        patterns = [
            # Standalone TP formats (most common in Muru channel)
            r'TP-(\d+)\s+(\d+\.?\d*)',  # "Tp-1 4673.7"
            r'TP(\d+)\s+(\d+\.?\d*)',  # "TP1 4673.7"
            r'TP\s+(\d+\.?\d*)',  # "TP 4673.7"
            
            # Standard formats (supports multiple TPs, allow no space: tp113500)
            r'TP[:\s]*(\d+\.?\d*(?:[,/]\s*\d+\.?\d*)*)',
            r'TAKE\s*PROFIT[:\s]*(\d+\.?\d*(?:[,/]\s*\d+\.?\d*)*)',
            r'TAKEPROFIT[:\s]*(\d+\.?\d*(?:[,/]\s*\d+\.?\d*)*)',
            r'TARGET[:\s]*(\d+\.?\d*(?:[,/]\s*\d+\.?\d*)*)',
            r'TARGETS[:\s]*(\d+\.?\d*(?:[,/]\s*\d+\.?\d*)*)',
            
            # Modification formats
            r'TP\s+TO\s+(\d+\.?\d*)',
            r'MOVE\s+TP\s+TO\s+(\d+\.?\d*)',
            r'UPDATE\s+TP\s+TO\s+(\d+\.?\d*)',
            r'CHANGE\s+TP\s+TO\s+(\d+\.?\d*)',
            r'NEW\s+TP[:\s]+(\d+\.?\d*)',
            r'SET\s+TP\s+TO\s+(\d+\.?\d*)',
            r'ADJUST\s+TP\s+TO\s+(\d+\.?\d*)',
            
            # Alternative formats
            r'TP\s+AT\s+(\d+\.?\d*)',
            r'TARGET\s+AT\s+(\d+\.?\d*)',
            r'TARGET\s+TO\s+(\d+\.?\d*)',
            
            # Multi-TP formats
            r'TP1[:\s]+(\d+\.?\d*)(?:\s+TP2[:\s]+(\d+\.?\d*))?(?:\s+TP3[:\s]+(\d+\.?\d*))?',
            
            # Pip-based (will need conversion) - supports multiple values like "100/200 pips"
            r'TP[:\s]+(\d+(?:[,/]\s*\d+)*)\s*PIPS?',
            r'TARGET[:\s]+(\d+(?:[,/]\s*\d+)*)\s*PIPS?',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                try:
                    # Handle multi-group matches (TP1, TP2, TP3 or TP-1 format)
                    if len(match.groups()) > 1:
                        tp_values = [float(g) for g in match.groups() if g and g.replace('.', '').isdigit()]
                        if tp_values:
                            return tp_values
                    
                    tp_str = match.group(1) if match.group(1) else match.group(2) if len(match.groups()) > 1 else None
                    if not tp_str:
                        continue
                        
                    # Split by comma or slash
                    tp_values = re.split(r'[,/]', tp_str)
                    return [float(tp.strip()) for tp in tp_values if tp.strip()]
                except Exception as _exc:
                    logger.debug(f"Suppressed exception: {_exc!r}")
        
        return None
    
    def _get_pip_value_for_symbol(self, symbol: Optional[str]) -> float:
        """
        Get pip value for a symbol to convert pips to price levels
        
        IMPORTANT: Pips vs Points for Standard Accounts
        - For most forex pairs: 1 pip = 0.0001 (4th decimal)
        - Points (pipettes): 1 point = 0.00001 (5th decimal)
        - For JPY pairs: 1 pip = 0.01 (2nd decimal)
        - For Gold (XAUUSD): 1 pip = 0.1
        - For Crypto (BTC, ETH): 1 pip = 0.1
        """
        from src.utils.pip_utils import get_pip_size
        return get_pip_size(symbol)
    
    def _convert_pips_to_price(self, pip_values: list, entry_price: float, symbol: str, order_type: OrderType) -> list:
        """
        Convert pip-based TP values to actual price levels
        
        Args:
            pip_values: List of TP values in pips (e.g., [100, 200])
            entry_price: Entry price
            symbol: Trading symbol
            order_type: BUY or SELL
            
        Returns:
            List of TP values in actual price levels
        """
        pip_value = self._get_pip_value_for_symbol(symbol)
        is_buy = order_type == OrderType.BUY
        
        price_levels = []
        for pip in pip_values:
            if is_buy:
                # For BUY: TP = entry + (pips * pip_value)
                price_level = entry_price + (pip * pip_value)
            else:
                # For SELL: TP = entry - (pips * pip_value)
                price_level = entry_price - (pip * pip_value)
            
            price_levels.append(round(price_level, 5))
            logger.info(f"   Converted {pip} pips to price level: {price_level} (pip_value={pip_value})")
        
        return price_levels
    
    def _extract_percentage_pattern(self, message: str) -> Optional[float]:
        """Extract percentage for partial close - Comprehensive percentage detection"""
        msg_upper = message.upper()
        
        patterns = [
            # Standard formats
            r'CLOSE\s+(\d+)%',
            r'PARTIAL\s+CLOSE\s+(\d+)%',
            r'CLOSE\s+(\d+)\s*PERCENT',
            r'EXIT\s+(\d+)%',
            
            # Alternative formats
            r'(\d+)%\s+CLOSE',
            r'(\d+)%\s+EXIT',
            r'TAKE\s+(\d+)%',
            r'BOOK\s+(\d+)%',
            r'SECURE\s+(\d+)%',
            r'LOCK\s+(\d+)%',
            
            # Profit taking formats
            r'(\d+)%\s+PROFIT',
            r'PROFIT\s+(\d+)%',
            r'TAKE\s+PROFIT\s+(\d+)%',
            
            # Fractional formats
            r'CLOSE\s+HALF',  # Will return 50
            r'EXIT\s+HALF',   # Will return 50
            
            # Generic percentage (last resort)
            r'(\d+)%',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, msg_upper)
            if match:
                try:
                    # Handle special cases
                    if 'HALF' in msg_upper:
                        return 50.0
                    
                    percentage = float(match.group(1))
                    if 0 < percentage <= 100:
                        return percentage
                except Exception as _exc:
                    logger.debug(f"Suppressed exception: {_exc!r}")
        
        return None
    
    def _is_high_confidence_signal(self, signal: TradingSignal) -> bool:
        """
        Check if AI signal has high confidence
        
        Args:
            signal: TradingSignal to check
            
        Returns:
            True if high confidence, False otherwise
        """
        if not signal:
            return False
        
        # Calculate confidence based on completeness and action type
        confidence = 0.0
        
        # Action is always required
        if not signal.action:
            logger.debug("Signal confidence: 0.0 (no action)")
            return False
        
        confidence += 0.3  # Action present
        
        # Different requirements based on action type
        if signal.action == SignalAction.OPEN:
            # OPEN signals need symbol + (entry OR market order indication)
            if signal.symbol:
                confidence += 0.4  # Symbol is critical for OPEN
            if signal.entry_price:
                confidence += 0.2  # Entry price
            elif signal.raw_message and ('NOW' in signal.raw_message.upper() or 'MARKET' in signal.raw_message.upper()):
                confidence += 0.1  # Market order (entry will be filled by defaults)
            if signal.stop_loss:
                confidence += 0.1  # SL is good but not critical (can use defaults)
            if signal.take_profit:
                confidence += 0.05  # TP is good but not critical
        
        elif signal.action in [SignalAction.CLOSE, SignalAction.PARTIAL_CLOSE]:
            # CLOSE signals don't need symbol (can be inferred from context)
            # Just having the action is often enough
            confidence += 0.3  # Action is sufficient for close
            if signal.symbol:
                confidence += 0.2  # Symbol helps but not required
            if signal.percentage_close:
                confidence += 0.1  # Percentage for partial close
        
        elif signal.action == SignalAction.MODIFY:
            # MODIFY signals need at least SL or TP change
            confidence += 0.2  # Action present
            if signal.symbol:
                confidence += 0.2  # Symbol helps
            if signal.stop_loss:
                confidence += 0.2  # New SL
            if signal.take_profit:
                confidence += 0.1  # New TP
        
        logger.debug(f"Signal confidence: {confidence:.2f} (action: {signal.action.value}, symbol: {signal.symbol})")
        return confidence >= self.confidence_threshold
    
    def _parse_response(self, response: str, original_message: str) -> Optional[TradingSignal]:
        """
        Parse AI response into TradingSignal
        
        Args:
            response: AI response text
            original_message: Original message
            
        Returns:
            TradingSignal or None
        """
        try:
            # Clean response
            clean_response = clean_json_response(response)
            
            logger.debug(f"Parsing AI response: {clean_response}")
            
            try:
                data = json.loads(clean_response)
                logger.debug(f"Parsed JSON data: {data}")
            except json.JSONDecodeError as e:
                logger.error(f"JSON parsing error: {e}. Raw response: {clean_response[:500]}")
                self.rejection_reason = f"AI returned malformed JSON: {e}"
                self.ai_explicit_rejection = False
                return None
            
            # Check if signal was found
            if not data.get('action') and not data.get('symbol'):
                logger.debug("No signal found in AI response (explicit rejection)")
                self.rejection_reason = "Not a trading signal — AI classified this as commentary, analysis, or a non-actionable message"
                self.ai_explicit_rejection = True
                return None
            
            # Validate and extract fields
            symbol = data.get('symbol')
            if symbol is not None and not isinstance(symbol, str):
                symbol = str(symbol)
            
            # Map action to enum
            action_str = str(data.get('action', '')).upper()
            if 'CLOSE' in action_str and any(x in action_str for x in ['PARTIAL', '%', 'PERCENT']):
                action = SignalAction.PARTIAL_CLOSE
            elif 'CLOSE' in action_str or 'EXIT' in action_str:
                action = SignalAction.CLOSE
            elif 'MODIFY' in action_str or 'UPDATE' in action_str or 'EDIT' in action_str:
                action = SignalAction.MODIFY
            elif 'BUY' in action_str or 'SELL' in action_str or 'OPEN' in action_str or 'ENTER' in action_str:
                action = SignalAction.OPEN
            else:
                action = SignalAction.OPEN
            
            # Extract numeric values FIRST (needed for order type detection)
            entry_price = self._safe_float(data.get('entry_price'))
            entry_range_min = self._safe_float(data.get('entry_range_min'))
            entry_range_max = self._safe_float(data.get('entry_range_max'))
            stop_loss = self._safe_float(data.get('stop_loss'))

            # Discrete scale-in legs ("MORE SELL @ X"). Keep order, drop nulls/dupes.
            entries_raw = data.get('entries')
            entries = None
            if isinstance(entries_raw, list):
                _legs, _seen = [], set()
                for e in entries_raw:
                    ev = self._safe_float(e)
                    if ev is not None and ev not in _seen:
                        _seen.add(ev)
                        _legs.append(ev)
                if len(_legs) >= 2:
                    entries = _legs
                    # Primary leg drives all single-entry logic below
                    if entry_price is None:
                        entry_price = _legs[0]

            # Extract is_plan early — plans have both BUY and SELL keywords and need special order_type handling
            is_plan_early = bool(data.get('is_plan', False))
            plan_data_raw = data.get('plan') if is_plan_early else None

            # If AI marked is_plan=true but returned no plan structure, build minimal plan_data
            # from top-level entry fields so the signal reaches manual-approval flow
            if is_plan_early and not plan_data_raw:
                _e_min = self._safe_float(data.get('entry_range_min'))
                _e_max = self._safe_float(data.get('entry_range_max'))
                _e_price = self._safe_float(data.get('entry_price'))
                if _e_min or _e_max or _e_price:
                    plan_data_raw = {
                        "primary": {
                            "order_type": None,
                            "entry_min": _e_min or _e_price,
                            "entry_max": _e_max or _e_price,
                            "stop_loss": None,
                            "sl_condition": None,
                            "take_profits": data.get('take_profit') or [],
                        },
                        "fallback": None,
                    }
                    logger.info("📋 Plan: AI omitted plan structure — built minimal plan_data from top-level entry fields")

            # Map order type - CRITICAL: Check original message AND AI response
            # Bug fix: Don't default to SELL if 'BUY' not in action_str
            order_type = None

            # For plans: use the primary leg's order_type directly — don't scan the full message
            # (plans legitimately contain both BUY and SELL keywords for primary + fallback legs)
            if is_plan_early and plan_data_raw:
                primary = plan_data_raw.get('primary', {})
                primary_ot = str(primary.get('order_type', '')).upper()
                if primary_ot == 'BUY':
                    order_type = OrderType.BUY
                    logger.info("📋 Plan: primary order type from plan.primary.order_type: BUY")
                elif primary_ot == 'SELL':
                    order_type = OrderType.SELL
                    logger.info("📋 Plan: primary order type from plan.primary.order_type: SELL")
                else:
                    # Fallback: infer from primary SL vs entry_min
                    entry_min = self._safe_float(primary.get('entry_min'))
                    primary_sl = self._safe_float(primary.get('stop_loss'))
                    if entry_min and primary_sl:
                        if primary_sl < entry_min:
                            order_type = OrderType.BUY
                            logger.info("📋 Plan: primary order type inferred from SL placement: BUY")
                        elif primary_sl > entry_min:
                            order_type = OrderType.SELL
                            logger.info("📋 Plan: primary order type inferred from SL placement: SELL")

            if not order_type:
                # Check explicit order_type field from AI (highest priority — AI has full context)
                ai_order_type = str(data.get('order_type', '') or '').upper()
                if ai_order_type == 'BUY':
                    order_type = OrderType.BUY
                    logger.info("📊 Order type from AI order_type field: BUY")
                elif ai_order_type == 'SELL':
                    order_type = OrderType.SELL
                    logger.info("📊 Order type from AI order_type field: SELL")

            if not order_type:
                # Check the AI response action string (legacy path for models that embed direction in action)
                if 'BUY' in action_str:
                    order_type = OrderType.BUY
                elif 'SELL' in action_str:
                    order_type = OrderType.SELL

            # If still not determined, scan the original message for explicit direction keywords.
            # NOTE: this is a fallback — it can misfire on analysis text that contains BUY/SELL/LONG
            # context words (e.g. "COT 85.9% Long"). Prefer AI order_type above.
            if not order_type:
                order_type = detect_explicit_direction(original_message)
                if order_type:
                    logger.info(f"📊 Order type detected from original message: {order_type.value}")
                else:
                    # Neither keyword found, or both present (plan-style caption) —
                    # SL placement below acts as the tie-breaker
                    logger.warning("⚠️ No unambiguous BUY/SELL keyword in message - using SL placement")

            # Last resort: Detect from SL placement relative to entry.
            # For range-based signals entry_price may be null; fall back to entry_range bounds.
            effective_entry = entry_price or entry_range_min or entry_range_max
            if not order_type and effective_entry and stop_loss:
                if stop_loss < effective_entry:
                    # SL below entry = BUY order
                    order_type = OrderType.BUY
                    logger.warning("⚠️ Order type inferred from SL placement: BUY (SL below entry)")
                elif stop_loss > effective_entry:
                    # SL above entry = SELL order
                    order_type = OrderType.SELL
                    logger.warning("⚠️ Order type inferred from SL placement: SELL (SL above entry)")

            # If still not determined, reject (ambiguous direction, not a deliberate AI rejection)
            if not order_type:
                logger.warning("⚠️ Cannot determine order type (BUY/SELL) — skipping ambiguous signal")
                self.rejection_reason = "Could not determine trade direction (BUY or SELL) from the message"
                return None
            
            # Handle take_profit as list
            take_profit_raw = data.get('take_profit')
            if take_profit_raw is None:
                take_profit = []
            elif isinstance(take_profit_raw, list):
                take_profit = [self._safe_float(tp) for tp in take_profit_raw]
            else:
                take_profit = [self._safe_float(take_profit_raw)]
            
            # CRITICAL: Convert pip-based TPs to actual price levels (same logic as pattern matching)
            if take_profit and entry_price and order_type and action == SignalAction.OPEN:
                # Check if TPs look like pips (small numbers relative to entry price)
                if take_profit and len(take_profit) > 0:
                    avg_tp = sum(take_profit) / len(take_profit)
                    if entry_price > 100 and avg_tp < entry_price * 0.5:
                        logger.info(f"🎯 AI parsing: Detected pip-based TPs: {take_profit} (entry={entry_price})")
                        take_profit = self._convert_pips_to_price(take_profit, entry_price, symbol or '', order_type)
                        logger.info(f"   Converted to price levels: {take_profit}")
            
            lot_size = self._safe_float(data.get('lot_size'))
            percentage_close = self._safe_float(data.get('percentage_close'))
            signal_id = data.get('signal_id')
            
            if signal_id is not None and not isinstance(signal_id, str):
                signal_id = str(signal_id)
            
            # CRITICAL: Validate MODIFY signals - must have SL, TP, or breakeven keyword
            if action == SignalAction.MODIFY:
                msg_upper = original_message.upper()
                is_breakeven = any(word in msg_upper for word in ['BREAKEVEN', 'BREAK EVEN', 'BE', 'SET BE'])
                
                # Filter out None values from take_profit list
                has_valid_tp = take_profit and any(tp is not None for tp in take_profit)
                
                if not stop_loss and not has_valid_tp and not is_breakeven:
                    logger.debug("AI parsing: MODIFY action detected but no SL/TP/breakeven value found - rejecting as update message")
                    self.rejection_reason = "Update message ignored — no new SL, TP, or breakeven value found"
                    self.ai_explicit_rejection = True
                    return None
            
            # CRITICAL: Validate OPEN signals
            if action == SignalAction.OPEN:
                msg_upper = original_message.upper()

                # ── PLAN PATH ──────────────────────────────────────────────────────────
                # The AI already decided this is a plan. Trust it.
                # Only hard-fail on: missing symbol, or provably wrong SL direction.
                if is_plan_early:
                    if not symbol:
                        logger.debug("AI parsing: plan rejected - no symbol extracted")
                        self.rejection_reason = "Plan signal rejected: no trading symbol found in message"
                        self.ai_explicit_rejection = True
                        return None
                    # SL direction check — only when a single entry_price AND stop_loss are
                    # both present (range-entry plans use plan_data SL, checked later)
                    if entry_price and stop_loss and order_type:
                        is_buy = (order_type == OrderType.BUY)
                        if is_buy and stop_loss >= entry_price:
                            logger.warning(f"🚨 Plan BUY: SL ({stop_loss}) >= entry ({entry_price}) — keeping plan but flagging")
                        elif not is_buy and stop_loss <= entry_price:
                            logger.warning(f"🚨 Plan SELL: SL ({stop_loss}) <= entry ({entry_price}) — keeping plan but flagging")
                    logger.debug(f"✅ Plan signal accepted: symbol={symbol}, is_plan=True")

                # ── REGULAR SIGNAL PATH ────────────────────────────────────────────────
                else:
                    ai_entry_mode = str(data.get('entry_mode') or '').strip().lower()
                    has_now_command = ai_entry_mode == 'market' or (
                        ai_entry_mode != 'pending' and self._instant_keyword(original_message) is not None)

                    # Analysis/commentary phrases — only block when the AI also found no
                    # entry price (the AI already filtered pure commentary via null action)
                    analysis_keywords = [
                        'SCENARIO', 'ANALYSIS', 'EXPECTING',
                        'WE FINALLY HAVE', 'I THINK', 'MY VIEW', 'IN MY OPINION',
                    ]
                    is_analysis = any(keyword in msg_upper for keyword in analysis_keywords)

                    # Must have symbol
                    if not symbol:
                        logger.debug("AI parsing: OPEN signal rejected - missing symbol")
                        self.rejection_reason = "No trading symbol found (e.g. XAUUSD, EURUSD)"
                        self.ai_explicit_rejection = True
                        return None

                    # Must have an entry reference
                    if not entry_price and not has_now_command and not entry_range_min:
                        logger.debug("AI parsing: OPEN signal rejected - no entry price or NOW command")
                        self.rejection_reason = f"No entry price found for {symbol} signal"
                        self.ai_explicit_rejection = True
                        return None

                    # Must have stop loss (safety requirement for immediate execution)
                    # EXCEPTION: do NOT reject when we have a clear direction + symbol +
                    # entry reference — the signal is incomplete, not invalid.
                    # The caller (process_message CASE 3) will fuse with vision AI
                    # to fill in SL/TP from the chart image.
                    if not stop_loss:
                        # Use entry_range_min as effective entry for the "no SL" message.
                        # Also treat "NOW"/"MARKET" as implied entry (current price).
                        effective_entry = entry_price or entry_range_min
                        has_entry_reference = effective_entry or has_now_command
                        if has_entry_reference:
                            logger.info(
                                f"📝 AI parsing: {symbol} {order_type.value} signal has "
                                f"entry={'NOW' if has_now_command and not effective_entry else effective_entry} "
                                f"but no SL — treating as INCOMPLETE, "
                                f"not rejected (SL expected from chart image)"
                            )
                            # Keep ai_explicit_rejection = False so process_message
                            # routes to CASE 3 (incomplete signal → vision fusion)
                        else:
                            logger.debug("AI parsing: OPEN signal rejected - missing stop loss "
                                         "AND no entry reference")
                            self.rejection_reason = (
                                f"No stop loss (SL) found and no entry price "
                                f"— required for {symbol} signal"
                            )
                            self.ai_explicit_rejection = True
                            return None

                    # Pure analysis with no entry price → skip
                    if is_analysis and not entry_price:
                        logger.debug("AI parsing: OPEN signal rejected - analysis/commentary without entry price")
                        self.rejection_reason = "Message looks like market analysis/commentary without a concrete entry price"
                        self.ai_explicit_rejection = True
                        return None

                    # SL placement must be correct for the order direction
                    if entry_price and stop_loss and order_type:
                        is_buy = (order_type == OrderType.BUY)
                        if sl_side_consistent(order_type, entry_price, stop_loss) is False:
                            if is_buy:
                                self.rejection_reason = f"BUY signal rejected: SL ({stop_loss}) is above entry ({entry_price}) — SL must be below entry for BUY"
                                logger.error(f"🚨 INVALID BUY signal: SL ({stop_loss}) is ABOVE entry ({entry_price})")
                            else:
                                self.rejection_reason = f"SELL signal rejected: SL ({stop_loss}) is below entry ({entry_price}) — SL must be above entry for SELL"
                                logger.error(f"🚨 INVALID SELL signal: SL ({stop_loss}) is BELOW entry ({entry_price})")
                            self.ai_explicit_rejection = True
                            return None
                        logger.debug(f"✅ SL placement validated: {'BUY' if is_buy else 'SELL'} with SL on correct side of entry")
                
                # REQUIREMENT 6: Validate TP direction matches order direction
                if entry_price and order_type and take_profit:
                    is_buy = (order_type == OrderType.BUY)
                    valid_tps = []
                    for i, tp_val in enumerate(take_profit):
                        if tp_val is None:
                            continue
                        if is_buy and tp_val <= entry_price:
                            logger.error(
                                f"🚨 INVALID TP{i+1} for BUY: TP ({tp_val}) is BELOW entry ({entry_price}) — "
                                f"must be ABOVE entry for BUY. Removing invalid TP."
                            )
                        elif not is_buy and tp_val >= entry_price:
                            logger.error(
                                f"🚨 INVALID TP{i+1} for SELL: TP ({tp_val}) is ABOVE entry ({entry_price}) — "
                                f"must be BELOW entry for SELL. Removing invalid TP."
                            )
                        else:
                            valid_tps.append(tp_val)
                    
                    if len(valid_tps) < len([tp for tp in take_profit if tp is not None]):
                        logger.warning(
                            f"⚠️ {len(take_profit) - len(valid_tps)} TP(s) removed due to invalid direction. "
                            f"Original TPs: {take_profit}, Valid TPs: {valid_tps}"
                        )
                    take_profit = valid_tps
                
                logger.debug(f"✅ OPEN signal validation passed: symbol={symbol}, entry={entry_price or 'NOW'}, SL={stop_loss}, direction={order_type.value if order_type else 'UNKNOWN'}")
            
            # Extract plan fields (reuse is_plan_early already extracted above)
            is_plan = is_plan_early
            plan_data = self._normalize_plan_data(plan_data_raw, order_type, stop_loss, take_profit) if plan_data_raw else None

            # Multi-entry legs are mutually exclusive with plans (a plan's second leg is
            # conditional; scale-in legs are simultaneous). Drop legs on the wrong side of
            # SL so a misread price can't create an instantly-stopped entry.
            if entries and (is_plan or action != SignalAction.OPEN):
                entries = None
            if entries and stop_loss and order_type:
                valid_legs = [
                    lg for lg in entries
                    if sl_side_consistent(order_type, lg, stop_loss) is not False
                ]
                if len(valid_legs) < len(entries):
                    logger.warning(
                        f"⚠️ Dropped {len(entries) - len(valid_legs)} scale-in leg(s) with SL "
                        f"({stop_loss}) on wrong side for {order_type.value}: {entries} → {valid_legs}"
                    )
                entries = valid_legs if len(valid_legs) >= 2 else None
            if entries:
                logger.info(f"🪜 Multi-entry (scale-in) legs detected: {entries}")

            # Create signal
            signal = TradingSignal(
                symbol=symbol,
                action=action,
                order_type=order_type,
                entry_price=entry_price,
                entries=entries,
                entry_range_min=entry_range_min,
                entry_range_max=entry_range_max,
                stop_loss=stop_loss,
                take_profit=take_profit,
                lot_size=lot_size,
                percentage_close=percentage_close,
                signal_id=signal_id,
                raw_message=original_message,
                is_plan=is_plan,
                plan_data=plan_data,
            )
            entry_mode = str(data.get('entry_mode') or '').strip().lower()
            if action == SignalAction.OPEN and entry_mode in ('market', 'pending'):
                signal.entry_mode = entry_mode
            # "BUY STOP" / "SELL STOP" is a breakout entry and must stay a pending stop
            # order. The AI answer only carries the direction, so the wording was lost
            # and the order was placed as a limit-or-market entry.
            if action == SignalAction.OPEN and order_type in (OrderType.BUY, OrderType.SELL):
                side = order_type.value
                if re.search(rf"\b{side}\s*[-_]?\s*STOP\b(?!\s*[-_]?\s*LOSS)", (original_message or "").upper()):
                    signal.signal_type = SignalType.BUY_STOP if side == "BUY" else SignalType.SELL_STOP
                    signal.entry_mode = 'pending'
            
            logger.debug(f"Created TradingSignal: {signal.__dict__}")
            return signal
            
        except Exception as e:
            logger.error(f"Error parsing AI response: {e}", exc_info=True)
            self.rejection_reason = f"AI response parse error: {e}"
            return None

    def _normalize_plan_data(
        self,
        plan_data: dict,
        signal_order_type,   # OrderType enum from the signal (primary direction)
        signal_sl: float,    # top-level SL already extracted
        signal_tps: list,    # top-level TPs already extracted
    ) -> dict:
        """
        Enforce per-leg completeness rules the AI may have missed:
          1. order_type on every leg — fall back to signal direction / SL inference
          2. stop_loss on every leg — never 0 or null
          3. SL must be on correct side of entry for each leg's direction
          4. fallback take_profits copied from primary when empty (Rule 3)
          5. entry_min/max from top-level entry_range if missing on primary
        """
        primary = plan_data.get("primary") or {}
        fallback = plan_data.get("fallback")

        def _fix_leg(leg: dict, default_ot_str: str, leg_name: str) -> dict:
            # --- order_type ---
            ot = str(leg.get("order_type", "")).upper()
            if ot not in ("BUY", "SELL"):
                # Infer from SL placement vs entry_min
                e_min = leg.get("entry_min") or 0
                sl = leg.get("stop_loss") or 0
                if e_min and sl:
                    ot = "BUY" if sl < e_min else "SELL"
                    logger.info(f"📋 Plan {leg_name}: order_type inferred from SL placement → {ot}")
                else:
                    ot = default_ot_str
                    logger.info(f"📋 Plan {leg_name}: order_type defaulted to {ot}")
            leg["order_type"] = ot

            # --- stop_loss ---
            sl = self._safe_float(leg.get("stop_loss")) or 0
            if sl == 0 and signal_sl:
                sl = signal_sl
                logger.info(f"📋 Plan {leg_name}: stop_loss missing — using top-level SL {sl}")
            leg["stop_loss"] = sl

            # --- SL direction validation (flip if clearly wrong) ---
            e_min = self._safe_float(leg.get("entry_min")) or 0
            e_max = self._safe_float(leg.get("entry_max")) or 0
            if e_min and sl:
                is_buy = (ot == "BUY")
                if is_buy and sl > e_min:
                    logger.warning(f"📋 Plan {leg_name}: BUY but SL ({sl}) > entry_min ({e_min}) — likely extraction error, keeping as-is")
                elif not is_buy and sl < e_max:
                    logger.warning(f"📋 Plan {leg_name}: SELL but SL ({sl}) < entry_max ({e_max}) — likely extraction error, keeping as-is")

            return leg

        # Primary OT from signal order_type
        primary_ot_str = signal_order_type.value if hasattr(signal_order_type, 'value') else str(signal_order_type or "BUY")
        primary = _fix_leg(primary, primary_ot_str, "primary")

        # Primary TPs — fall back to signal TPs if empty
        if not primary.get("take_profits") and signal_tps:
            primary["take_profits"] = signal_tps
            logger.info("📋 Plan primary: take_profits missing — copied from signal TPs")

        if fallback:
            # Fallback inherits primary direction unless explicitly different
            fallback_default_ot = primary.get("order_type", primary_ot_str)
            fallback = _fix_leg(fallback, fallback_default_ot, "fallback")

            # RULE 3: copy primary TPs to fallback when not explicitly provided
            if not fallback.get("take_profits"):
                fallback["take_profits"] = list(primary.get("take_profits") or [])  # AI may send null
                logger.info(f"📋 Plan fallback: take_profits not stated — copied from primary: {fallback['take_profits']}")

        return {"primary": primary, "fallback": fallback}

    def _merge_image_signals_into_plan(self, signals: list) -> "TradingSignal":
        """
        Merge 2+ independent vision signals into a single plan signal.
        primary = signals[0], fallback = signals[1].
        Additional signals beyond index 1 are ignored (plan only supports one fallback).
        """
        from src.models.enums import SignalAction
        primary_sig = signals[0]
        fallback_sig = signals[1] if len(signals) > 1 else None

        def _leg(sig) -> dict:
            ot = sig.order_type.value if sig.order_type else "BUY"
            entry = sig.entry_price or 0.0
            entry_min = sig.entry_range_min or entry
            entry_max = sig.entry_range_max or entry
            return {
                "order_type": ot,
                "entry_min": entry_min,
                "entry_max": entry_max,
                "stop_loss": sig.stop_loss or None,
                "sl_condition": None,
                "take_profits": sig.take_profit or [],
            }

        plan_data = {
            "primary": _leg(primary_sig),
            "fallback": _leg(fallback_sig) if fallback_sig else None,
        }

        # Build a merged TradingSignal marked as a plan
        merged = TradingSignal(
            symbol=primary_sig.symbol,
            action=SignalAction.OPEN,
            order_type=primary_sig.order_type,
            entry_price=primary_sig.entry_price,
            entry_range_min=primary_sig.entry_range_min,
            entry_range_max=primary_sig.entry_range_max,
            stop_loss=primary_sig.stop_loss,
            take_profit=primary_sig.take_profit,
            raw_message=primary_sig.raw_message,
            confidence=primary_sig.confidence,
            is_plan=True,
            plan_data=plan_data,
        )
        leg_desc = f"{primary_sig.order_type.value if primary_sig.order_type else '?'} {primary_sig.symbol}"
        if fallback_sig:
            leg_desc += f" + {fallback_sig.order_type.value if fallback_sig.order_type else '?'} {fallback_sig.symbol}"
        logger.info(f"📋 Merged {len(signals)} image setups into plan: {leg_desc}")
        return merged

    def _safe_float(self, value):
        """Safely convert a value to float, returning None if conversion fails"""
        return safe_float(value)
