"""
Image-Aware Signal Extractor
Processes trading signals from messages with chart images and complex trading commands
Handles: reenter, risky, limit orders, short/long positions, sl modifications, etc.
"""
import logging
import re
from typing import Optional, Dict, Any
from src.models import TradingSignal, SignalAction, OrderType, SignalType
from .signal_validation import detect_explicit_direction, sl_side_consistent

logger = logging.getLogger(__name__)


class ImageSignalExtractor:
    """
    Enhanced signal extractor that understands chart images and complex trading terminology
    """
    
    def __init__(self, config):
        self.config = config
        self.client = None

        # Check if AI vision is enabled — client stays None when disabled, but
        # filter settings below are still initialized (pre-filters use them)
        vision_enabled = getattr(config, 'enable_ai_vision', True)
        if not vision_enabled:
            logger.info("🔒 AI Vision is disabled via enable_ai_vision toggle")
        else:
            self._init_client(config)

        self.temperature = getattr(config, 'temperature', 0.1)

        # --- Anti-hallucination filter settings (all optional, safe defaults) ---
        self.caption_prefilter_enabled  = getattr(config, 'vision_caption_prefilter_enabled', True)
        raw_keywords = getattr(config, 'vision_caption_block_keywords',
            "in profit,floating,closed,result,pips gained,balance,equity,"
            "trade history,win rate,drawdown,performance,tp hit,sl hit,"
            "hit tp,hit sl,be hit,profit taken,loss taken,"
            "tp done,tp1 done,tp2 done,tp3 done,target hit,target reached,"
            "target done,take profit hit,hit all tp,all tp hit,"
            "sl done,position closed")
        self.caption_block_keywords = [k.strip().lower() for k in raw_keywords.split(',') if k.strip()]

        self.confidence_filter_enabled  = getattr(config, 'vision_confidence_filter_enabled', True)
        self.min_confidence             = float(getattr(config, 'vision_min_confidence', 0.75))

        self.two_step_classify_enabled  = getattr(config, 'vision_two_step_classify_enabled', True)

        self.price_sanity_enabled       = getattr(config, 'vision_price_sanity_check_enabled', True)
        raw_ranges = getattr(config, 'vision_price_ranges', '{}')
        try:
            import json as _json
            self.price_ranges: dict = _json.loads(raw_ranges) if isinstance(raw_ranges, str) else (raw_ranges or {})
        except Exception:
            self.price_ranges = {}
        if not self.price_ranges:
            self.price_ranges = {
                "XAUUSD": [1000, 5000], "EURUSD": [0.5, 3.0], "GBPUSD": [0.5, 3.0],
                "USDJPY": [50, 250],    "BTCUSD": [1000, 500000], "ETHUSD": [100, 50000],
                "US30":   [15000, 70000], "NAS100": [5000, 30000], "SPX500": [1000, 10000],
                "GBPJPY": [100, 300],   "USDCAD": [0.5, 2.5], "AUDUSD": [0.3, 1.5],
                "NZDUSD": [0.3, 1.5],   "USDCHF": [0.5, 2.0], "EURJPY": [50, 250],
                "EURGBP": [0.5, 2.0],
            }

        self.sl_distance_check_enabled  = getattr(config, 'vision_sl_distance_check_enabled', True)
        self.max_sl_distance_percent    = float(getattr(config, 'vision_max_sl_distance_percent', 10.0))

        self.dimension_filter_enabled   = getattr(config, 'vision_image_dimension_filter_enabled', True)
        self.max_image_aspect_ratio     = float(getattr(config, 'vision_max_image_aspect_ratio', 3.5))
        self.min_image_height           = int(getattr(config, 'vision_min_image_height', 150))

        # Human-readable reason for the last vision rejection (surfaced in dashboard)
        self.last_rejection_reason: Optional[str] = None

        self.symbol_whitelist_enabled   = getattr(config, 'vision_symbol_whitelist_enabled', False)
        raw_symbols = getattr(config, 'vision_allowed_symbols',
            "XAUUSD,EURUSD,GBPUSD,USDJPY,BTCUSD,ETHUSD,US30,NAS100,SPX500,"
            "GBPJPY,USDCAD,AUDUSD,NZDUSD,USDCHF,EURJPY,EURGBP")
        self.allowed_symbols = {s.strip().upper() for s in raw_symbols.split(',') if s.strip()}

    def _init_client(self, config):
        """
        Initialize the vision-capable AI availability gate.

        The actual vision calls go through llm_client.complete_with_fallback(),
        which builds its own clients across the full vision provider chain. This
        method only needs to answer "can any vision provider serve a request?",
        so it reuses that SAME chain (primary + fallbacks) instead of duplicating
        provider/key/base_url logic. Using the shared chain means the gate can
        never reject an image that the engine would have handled via a fallback
        provider.
        """
        from ai.llm_client import (
            first_available_provider, build_llm_client_for, get_model_for,
        )

        provider = first_available_provider(config, vision=True)
        if provider is None:
            logger.warning("⚠️ No vision-capable AI provider has an API key — image analysis disabled")
            return

        # self.client is kept only as the availability gate consumed by
        # process_message_with_image(); the per-call client/model are resolved
        # inside complete_with_fallback().
        self.client = build_llm_client_for(config, provider)
        self.ai_model = get_model_for(config, provider, vision=True)
        logger.info(f"✅ Image-aware extractor initialized (vision provider: {provider}, model: {self.ai_model})")

    async def process_message_with_image(
        self,
        message_text: str,
        image_data: Optional[bytes] = None,
        image_url: Optional[str] = None,
        allow_analysis: bool = False,
    ) -> list:  # Returns List[TradingSignal]
        """
        Process trading signal from message with chart image

        Args:
            message_text: Text message content
            image_data: Raw image bytes (optional)
            image_url: URL to image (optional)
            allow_analysis: When True, also pass images classified as 'analysis'
                through to the vision extraction step (used when text intent was
                NOT_TRADING but a chart image is present — the image may contain
                a plan-level setup like annotated zones + "waiting confirmation").

        Returns:
            TradingSignal or None
        """
        self.last_rejection_reason = None

        if not self.client:
            logger.warning("Vision AI not available, falling back to text-only processing")
            self.last_rejection_reason = "Vision: no vision-capable AI provider configured"
            return []

        try:
            # Build image content blocks once — reused across calls.
            # Albums pass a list of images; all are sent in one vision call.
            image_content = []
            if image_url:
                image_content.append({"type": "image_url", "image_url": {"url": image_url}})
            elif image_data:
                import base64
                images = image_data if isinstance(image_data, list) else [image_data]
                for img in images:
                    b64 = base64.b64encode(img).decode('utf-8')
                    image_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})

            # Filter 3: two-step classify → only extract if image type is a signal
            if self.two_step_classify_enabled and image_content:
                image_type = await self._classify_image(image_content, message_text)
                # 'signal' = executable setup; 'price_path' = arrow/forecast chart,
                # extracted as a PLAN (is_plan) rather than rejected.
                # 'analysis' is also allowed when allow_analysis=True — this covers
                # "waiting confirmation" style posts where the chart has annotated
                # zones/levels but no arrow yet; the vision prompt will extract a
                # plan if structure is present, or return empty if nothing is there.
                allowed_types = {"signal", "price_path"}
                if allow_analysis:
                    allowed_types.add("analysis")
                if image_type not in allowed_types:
                    self.last_rejection_reason = (
                        f"Vision: image classified as '{image_type}' — no executable Entry/SL/TP "
                        f"structure or forecast arrow found"
                    )
                    logger.info(f"🔍 Two-step classify rejected image as '{image_type}' — skipping extraction")
                    return []
                if image_type == "analysis":
                    logger.info("🔍 Two-step classify: 'analysis' image — attempting plan extraction (allow_analysis=True)")

            content = [{"type": "text", "text": self._get_vision_prompt(message_text)}] + image_content

            from ai.llm_client import complete_with_fallback, provider_chain, extract_content, max_tokens_for

            def _vision_call(client, model, provider):
                return client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "You are a strict trading signal validator. Only extract NEW, actionable trade setups that contain a clear Entry + Stop Loss + Take Profit structure. Return an empty signals array for anything else. When in doubt, return empty."},
                        {"role": "user", "content": content}
                    ],
                    temperature=self.temperature,
                    max_tokens=max_tokens_for(self.config, provider, output_tokens=1500, vision=True),
                )

            response = complete_with_fallback(
                self.config,
                provider_chain(self.config, vision=True),
                _vision_call,
                vision=True,
                validate=lambda r: bool(extract_content(r).strip()),
                caller='vision_extraction',
            )

            result = extract_content(response)
            signals = self._parse_vision_response(result, message_text)

            # Filter 4 & 5 & 6: post-extraction validation
            signals = self._post_validate(signals)

            # Preserve the verbatim vision model output for dashboard inspection
            for sig in signals:
                sig.ai_raw_response = result

            if signals:
                logger.info(f"✅ Vision extracted {len(signals)} signal(s)")
            return signals

        except Exception as e:
            from ai.api_error_handler import log_api_error
            log_api_error(e, "Vision/Image", logger)
            self.last_rejection_reason = f"Vision: API error — {e}"
            return []

    def is_probably_decorative(self, image_data: bytes) -> tuple:
        """
        Cheap pre-check that catches decorative graphics (channel dividers,
        banners, tiny stickers) before they reach the vision model, which can
        hallucinate trade setups from non-chart images.

        Returns (is_decorative: bool, reason: str). Fails open on any error.
        """
        if not self.dimension_filter_enabled or not image_data:
            return False, ""
        try:
            import io
            from PIL import Image
            with Image.open(io.BytesIO(image_data)) as img:
                width, height = img.size
            if not width or not height:
                return False, ""
            aspect = max(width / height, height / width)
            if aspect > self.max_image_aspect_ratio:
                return True, f"aspect ratio {aspect:.1f} > {self.max_image_aspect_ratio} ({width}x{height})"
            if height < self.min_image_height:
                return True, f"height {height}px < {self.min_image_height}px minimum"
            if width * height < 60_000:
                return True, f"image too small ({width}x{height})"
            return False, ""
        except Exception as e:
            logger.debug(f"Dimension pre-filter skipped (could not inspect image): {e}")
            return False, ""

    async def _classify_image(self, image_content: list, caption: str = "") -> str:
        """
        Filter 3 — two-step classify.
        Returns one of: 'signal', 'trade_result', 'mt5_screen', 'price_path', 'analysis', 'other'
        """
        try:
            classify_prompt = (
                "Look at this image and classify it into EXACTLY ONE of these categories:\n"
                "- signal: a new trade setup with Entry, SL, and TP (TradingView/MT5 position tool, annotated chart zones, "
                "or a directional arrow combined with marked entry/SL/TP levels)\n"
                "- trade_result: a closed trade result, profit/loss screenshot, or performance record\n"
                "- mt5_screen: MT5 or broker terminal showing open positions, account balance, or trade history\n"
                "- price_path: a forecast/prediction chart with ONLY arrows/paths showing where price might go and NO marked "
                "entry/SL/TP levels. Includes multi-leg/zigzag forecasts (e.g. small pullback then a sharp continuation, or "
                "up-then-down scenario paths) — classify these as price_path too, NOT analysis, as long as the lines are "
                "directional arrows/paths rather than static support/resistance levels "
                "(if the arrow has entry/SL/TP levels next to it, classify as signal instead)\n"
                "- analysis: market commentary, support/resistance levels, or indicators only — no trade structure\n"
                "- other: anything else\n\n"
                "Use the caption posted with the image: if it reports a result or progress (TP hit, +X pips, "
                "running, profit secured, booked, deal done), the image is trade_result even when it still shows "
                "the original entry/SL/TP boxes.\n\n"
                "Reply with ONLY the category name, nothing else."
            )
            if caption and caption.strip():
                classify_prompt += f"\n\nCaption: {caption.strip()[:500]}"
            from ai.llm_client import complete_with_fallback, provider_chain, extract_content, max_tokens_for

            def _classify_call(client, model, provider):
                return client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "You are an image classifier. Reply with one word only."},
                        {"role": "user", "content": [{"type": "text", "text": classify_prompt}] + image_content}
                    ],
                    temperature=0,
                    max_tokens=max_tokens_for(self.config, provider, output_tokens=5, vision=True),
                )

            resp = complete_with_fallback(
                self.config,
                provider_chain(self.config, vision=True),
                _classify_call,
                vision=True,
                validate=lambda r: bool(extract_content(r).strip()),
                caller='vision_classify',
            )
            category = extract_content(resp).strip().lower().split()[0]
            valid = {"signal", "trade_result", "mt5_screen", "price_path", "analysis", "other"}
            return category if category in valid else "other"
        except Exception as e:
            logger.warning(f"Image classification failed, proceeding with extraction: {e}")
            return "signal"  # fail-open: don't block if classify call errors
    
    def _get_vision_prompt(self, message_text: str) -> str:
        """Generate prompt for vision model"""
        return f"""You are a STRICT TRADING SIGNAL VALIDATOR. Avoid false positives — but capture every real setup.

## STEP 1 — THINK FIRST (fill every line before writing JSON)
<think>
SYMBOL & CHART: [what instrument, what timeframe, setup tool present yes/no]
PRICE LEVELS (read each digit explicitly from axis labels):
  Entry : ___
  SL    : ___
  TP(s) : ___ (list all visible labels; write "not labeled" if absent)
DIRECTION: SL is [above / below] entry → this is a [SELL / BUY]
ORDER CHECK: for a SELL, SL > entry > TP. For a BUY, SL < entry < TP. My numbers: SL ___ entry ___ TP ___ → [consistent / INCONSISTENT — re-read the axis labels before continuing, a digit was misread]
SIGNAL TYPE: entry is [at current price / above current price / below current price] → [MARKET / SELL_LIMIT / BUY_STOP / BUY_LIMIT / SELL_STOP]
ALREADY TRIGGERED?: [yes / no — is price already past the entry line?]
DECISION: [SIGNAL / PLAN / NOT A SIGNAL] — [one sentence why]
</think>

## ACCURACY — READ PRICE LEVELS CAREFULLY
1. **Y-axis first** — read the right-side scale to establish price magnitude. Cross-check values make sense for the symbol (XAUUSD: 1000–5500, EURUSD: 0.90–1.30, USDJPY: 50–200, BTCUSD: 10k–200k).
2. **Labeled annotations only** — read prices from explicit text labels ("SL: 4350", "TP: 4278") or the colored axis labels of the setup tool. Do NOT infer prices from unlabeled lines, zone midpoints, or candle highs/lows.
3. **Every digit matters** — 4350 vs 4380, 4278 vs 4318 can cause a losing trade. Read slowly.
4. **Blurry or cut-off number** — set it to null and lower confidence. Never guess.
5. **Multiple horizontal lines** — a line labeled only with a structure tag ("QML", "OB", "FVG", "BOS") with no Entry/SL/TP text is informational, not automatically a trade level. EXCEPTION: in an arrow/path forecast plan (no setup-tool rectangle), if such a level sits beyond the path's starting point on the invalidation side (above the start for a SELL path, below it for a BUY path), that is the conventional place a trader would set their stop — extract it as stop_loss for the plan. Do not, however, confuse that structural level WITH the entry itself — entry is where the drawn path actually starts, never the structure label above/below it.
6. **Dotted/dashed lines = S/R, not TP** — unless the line carries an explicit "TP" label. The real TP is the colored axis label at the outer edge of the TP zone.
7. **The "X" marker on TradingView** = expected-loss display of the position tool. Not a price level. Ignore it.
8. **Self-check the three numbers against each other** — for a SELL: SL > entry > TP. For a BUY: SL < entry < TP. If your readings don't sit in that order, you misread at least one digit (a single-digit slip like 3→1 or 8→6 produces a number that still "looks" plausible but breaks this ordering) — go back to the axis and re-read every label before answering. Do not finalize numbers that fail this check.

## TRADE SETUP TOOL (TradingView / MT5 / ProfitView)
If you see a Long/Short Position tool overlay:
- The SL/TP rectangle tool always splits PRICE space — two zones stacked vertically,
  divided by a horizontal Entry line, each with its own price-axis label.
- **Being bounded in time does NOT disqualify it.** Every genuine position-tool box is
  drawn at a fixed time/date width — that is normal, not a red flag. The test for "is this
  the SL/TP tool or just a session highlight" is COLOR COUNT, not width: a box with TWO
  distinct color bands (one above, one below a dividing line) is the SL/TP tool, full stop
  — extract it even if its right edge is cropped by the image border or it only spans a
  few hours. Only treat a box as a non-price session/time highlight when it is a SINGLE
  uniform color top-to-bottom with no internal dividing line and no price-axis label at
  its edges. If all you have besides that single-color shading is an arrow/path with price
  labels at the bends, that is still ARROW ONLY → is_plan=true.
- Two colored rectangular zones split by a horizontal Entry line — these are almost always real signals.
- **Zone color varies by trader theme.** SL zone: red, pink, or any warm tone. TP zone: green, teal, purple, lavender, blue, or any cool tone. Do NOT use color as the primary identifier.
- **Use position**: zone ABOVE entry = SL zone for SELL (and TP zone for BUY); zone BELOW entry = TP zone for SELL (and SL zone for BUY).
- **Colored axis labels on the right are the exact levels**: label at SL-zone outer edge = SL, label at TP-zone outer edge = TP, middle label = Entry. Always prefer these over inferred zone boundaries.
- **TP label is at the FAR outer edge** of the TP zone — may be near chart bottom (SELL) or top (BUY). Look all the way to the rectangle edge, not just the visible midpoint.
- **A separate full-width dotted/dashed line is the CURRENT PRICE marker, not Entry.** Many
  platforms draw a thin dotted horizontal line that spans the ENTIRE chart (left edge to
  right edge), with its own small axis label, independently of the position tool. This is
  the live/last price, not a trade level. It often sits very close to the tool's Entry
  line/label — when you see TWO axis labels within a few price-units of each other near the
  entry boundary, do not merge them or discard one as noise: read each digit-by-digit
  separately. The label that belongs to the position tool's own entry boundary (sits exactly
  on the line dividing the SL and TP zones, often with a small connector/arrow to that line)
  is Entry. The other one — sitting on a line that keeps going past the tool's left/right
  edges across the whole chart — is current price; ignore it for entry_price.

## DIRECTION — DETERMINED BY LEVELS, NOT ARROWS OR TEXT

When Entry + SL + TP are all known, direction is mathematically locked:
- SL **above** entry AND TP **below** entry → **SELL** (no exceptions)
- SL **below** entry AND TP **above** entry → **BUY** (no exceptions)

When SL or TP is missing, fall back in this order:
1. Drawn arrow direction (up = BUY, down = SELL)
2. Explicit BUY/SELL text in the message caption

**If arrow or message text contradicts the levels: levels win.** Flag it in your think block and lower confidence to ~0.80, but do NOT return empty just because cues conflict.

## ORDER TYPE (signal_type field)

Compare entry price to the current market price visible on the chart:
- **MARKET** — entry is at or very near current price (price already at the entry zone)
- **BUY_LIMIT** — BUY setup, entry is BELOW current price (waiting for dip)
- **BUY_STOP** — BUY setup, entry is ABOVE current price (breakout long)
- **SELL_LIMIT** — SELL setup, entry is ABOVE current price (waiting for rally)
- **SELL_STOP** — SELL setup, entry is BELOW current price (breakout short)

If you cannot determine current price from the chart, use SELL_LIMIT for SELL or BUY_LIMIT for BUY as the safe default.

## TAKE PROFIT — READ FIRST, CALCULATE AS FALLBACK

**Step 1 — Read from chart**: List all explicitly labeled TP levels (TP1, TP2, TP3, or multiple green/colored axis labels) in order from entry outward (closest first).

**Step 2 — RR fallback**: If NO TP label is readable or it is cut off, calculate from the SL distance:
  risk = |entry − SL|
  TP1 = entry ± (risk × 1.0)   →  1:1 RR
  TP2 = entry ± (risk × 2.0)   →  1:2 RR
  (use + for BUY, − for SELL)

**Step 3 — Cross-check every TP**: TP must be on the correct side of entry (BUY: TP > entry; SELL: TP < entry). Discard any TP that fails this check — including any you may have read incorrectly.

Never invent a TP number that is not on the chart. Use the RR fallback only when labels are genuinely absent or unreadable.

## ENTRY: SINGLE PRICE vs ZONE

- **entry_price** (single float): use when the setup tool shows one horizontal Entry line with a single price label. Set entry_range to null.
- **entry_range** ([min, max]): use when the chart shows a shaded entry zone or two labeled boundaries. Set entry_price to null.
- Never set both at the same time.

## COUNTING SETUPS

- Each independent Entry + SL + TP combination = ONE setup
- Two tools on different instruments = TWO independent setups
- Two setups sharing the SAME SL = ONE plan (primary + fallback legs), not two signals
- Two setups with DIFFERENT SLs = TWO independent signals

## HOW TO IDENTIFY A SETUP
**A)** Explicit "Entry", "SL", "TP", "BUY", "SELL" text labels
**B)** Two rectangular zones split by entry line (zone position, not color, identifies SL vs TP)
**C)** TradingView / broker setup tool overlay
**D)** Directional arrow with marked entry/SL/TP levels

## ARROW ONLY (no setup tool, no explicit SL/TP) = PLAN
- order_type from arrow direction (up = BUY, down = SELL)
- entry_range = where the arrow starts — this is a price the path actually touches,
  never a structure label sitting above/below the path's starting point
- take_profit = where the arrow ends (or [] if unreadable)
- stop_loss = only if a clear invalidation level is marked (see the structure-label
  EXCEPTION above — e.g. a QML level beyond the start, on the invalidation side);
  otherwise null. Never reuse the entry price itself as stop_loss.
- is_plan: true, fallback: null
- Missing SL is acceptable for plans — they go to manual approval (a human reviews and
  manually triggers every plan before it can execute, so it is safe to extract a plan
  even when you are not fully certain — do not return empty just because the path is
  imperfect or multi-legged)

## MULTI-LEG / ZIGZAG FORECAST PATHS (still a PLAN, do not reject)
Scenario charts often draw more than one leg: e.g. a small pullback/retrace first, then
a sharp continuation move (up-down-up-down or down-up-down). Treat the WHOLE path as one
plan, not a reason to reject:
- entry_range = where the FIRST leg starts (the earliest point on the drawn path)
- take_profit = where the LAST leg ends (the final target of the overall path)
- order_type = direction of the LAST/dominant leg (the move the path ultimately resolves
  toward), not necessarily the first leg
- is_plan: true — these always go to manual approval, never auto-execute
- Lower confidence appropriately (see CONFIDENCE ANCHORS) but still extract it

## NOT A SIGNAL — return empty signals array for:
- Raw S/R zones with no trade structure
- Pure analysis or commentary without Entry+SL+TP
- **Trade results / history** (closed trades, P&L records, win-rate screenshots)
- **Already-running positions** — visual cues: floating "Profit:" or "P&L:" text, pips gained/lost display, MT5 open ticket showing current price vs filled entry, "position opened" banners
- MT5/broker terminal: account balance, equity, margin, open positions list, trade history tab
- Charts with no directional structure (no arrow, no setup tool, no SL/TP labels)
- Trade summary cards (entry already taken, showing running pips)
- Market dashboards, economic calendars, news screenshots

## CONFIDENCE ANCHORS
- **0.95–1.00**: Setup tool present, all three labels (entry, SL, TP) clearly readable
- **0.85–0.94**: Clear setup, one label slightly blurry but still readable
- **0.75–0.84**: Arrow-based setup with readable levels, or setup tool with one label cut off
- **0.60–0.74**: Significant ambiguity on a direct signal, OR a multi-leg/zigzag forecast PLAN
  where the overall direction and end target are still readable — for PLANS, extract at this
  confidence rather than returning empty (a human approves every plan before it executes)
- **< 0.60**: Return empty — do not guess

## READ THE CAPTION AND THE IMAGE TOGETHER
The caption below was posted WITH this image. Decide what the post as a whole is before reading levels —
the same chart can be a fresh setup or a recap of a trade that is already running/closed:
- Caption reports a RESULT or PROGRESS ("TP hit", "+150 pips", "running", "profit secured", "deal done",
  "smashed", "zero float", "back to back", "booked") → the image is a results/proof screenshot of an
  EXISTING trade, even if it still shows the original entry/SL/TP boxes → return empty signals.
- Caption says NOT to enter yet ("no entry for me", "waiting confirmation", "just watching", "if you want,
  very small lot") → at most a PLAN (is_plan: true, confidence ≤ 0.70); never a direct signal.
- Caption gives a direction/levels that conflict with the chart → follow the LEVELS rule above and say so
  in "reason".
- Caption is empty, unrelated, or just the symbol → judge the image alone.

Caption: {message_text}

══════════════════════════════════════════
RESPONSE FORMAT — think block first, then JSON
══════════════════════════════════════════

Return ALL setups in a "signals" array. Even for a single setup, wrap it in the array.
The "reason" field must state the prices you read: "SELL: entry 4352.89, SL 4372.85 (above), TP 4300.04 (below)"

For a SINGLE regular signal (single entry line):
{{
  "signals": [
    {{
      "is_plan": false,
      "action": "OPEN",
      "symbol": "XAUUSD",
      "order_type": "SELL",
      "signal_type": "SELL_LIMIT",
      "entry_price": 4352.89,
      "entry_range": null,
      "stop_loss": 4372.85,
      "take_profit": [4300.04],
      "is_signal": true,
      "confidence": 0.95,
      "reason": "SELL: entry 4352.89, SL 4372.85 (above entry), TP 4300.04 (below entry) — TradingView tool, all labels clear"
    }}
  ]
}}

For a signal with an entry zone:
{{
  "signals": [
    {{
      "is_plan": false,
      "action": "OPEN",
      "symbol": "XAUUSD",
      "order_type": "BUY",
      "signal_type": "BUY_LIMIT",
      "entry_price": null,
      "entry_range": [4340.00, 4360.00],
      "stop_loss": 4320.00,
      "take_profit": [4400.00, 4450.00],
      "is_signal": true,
      "confidence": 0.90,
      "reason": "BUY: entry zone 4340–4360, SL 4320 (below entry), TP1 4400 / TP2 4450 (above entry)"
    }}
  ]
}}

For a PLAN (primary + fallback, same SL = one trade):
{{
  "signals": [
    {{
      "is_plan": true,
      "action": "OPEN",
      "symbol": "XAUUSD",
      "order_type": "SELL",
      "signal_type": "SELL_LIMIT",
      "entry_price": null,
      "entry_range": [3350.00, 3360.00],
      "stop_loss": 3370.00,
      "take_profit": [3340.00, 3330.00],
      "is_signal": true,
      "confidence": 0.85,
      "plan": {{
        "primary": {{"order_type":"SELL","entry_min":3350,"entry_max":3360,"stop_loss":3370,"sl_condition":null,"take_profits":[3340,3330]}},
        "fallback": {{"order_type":"BUY","entry_min":3370,"entry_max":3380,"stop_loss":3360,"sl_condition":null,"take_profits":[3390,3400]}}
      }},
      "reason": "Plan: primary SELL 3350–3360 SL 3370, fallback BUY above 3370 SL 3360"
    }}
  ]
}}

For an ARROW-ONLY chart (no setup tool — single-leg PLAN):
{{
  "signals": [
    {{
      "is_plan": true,
      "action": "OPEN",
      "symbol": "XAUUSD",
      "order_type": "SELL",
      "signal_type": "SELL_LIMIT",
      "entry_price": null,
      "entry_range": [4365.00, 4375.00],
      "stop_loss": null,
      "take_profit": [4300.00],
      "is_signal": true,
      "confidence": 0.78,
      "plan": {{
        "primary": {{"order_type":"SELL","entry_min":4365,"entry_max":4375,"stop_loss":null,"sl_condition":null,"take_profits":[4300]}},
        "fallback": null
      }},
      "reason": "Arrow-only plan: downward arrow starts 4365–4375, ends near 4300 — no SL/TP tool"
    }}
  ]
}}

For TWO independent setups (different SLs):
{{
  "signals": [
    {{
      "is_plan": false,
      "action": "OPEN",
      "symbol": "XAUUSD",
      "order_type": "BUY",
      "signal_type": "BUY_LIMIT",
      "entry_price": 4430.00,
      "entry_range": null,
      "stop_loss": 4410.00,
      "take_profit": [4500.00, 4550.00],
      "is_signal": true,
      "confidence": 0.90,
      "reason": "BUY: entry 4430, SL 4410 (below), TP1 4500 / TP2 4550 (above)"
    }},
    {{
      "is_plan": false,
      "action": "OPEN",
      "symbol": "EURUSD",
      "order_type": "SELL",
      "signal_type": "SELL_LIMIT",
      "entry_price": 1.0850,
      "entry_range": null,
      "stop_loss": 1.0900,
      "take_profit": [1.0800, 1.0750],
      "is_signal": true,
      "confidence": 0.88,
      "reason": "SELL: entry 1.0850, SL 1.0900 (above), TP1 1.0800 / TP2 1.0750 (below)"
    }}
  ]
}}

If NO trading signal found:
{{
  "signals": [],
  "reason": "No clear entry/SL/TP structure found"
}}
"""
    
    def _post_validate(self, signals: list) -> list:
        """Filters 4, 5, 6 — price sanity, SL distance, symbol whitelist."""
        if not signals:
            return signals
        validated = []
        for sig in signals:
            symbol = (sig.symbol or "").upper()

            # Filter 6: symbol whitelist. An unrecognized symbol holds for clarification
            # instead of being rejected outright or (worse) passed through to execution
            # when the whitelist is disabled — e.g. a quote-currency badge like "USD"
            # picked up off a chart with no visible ticker. Applies to plans and direct
            # signals alike: a wrong guess is cheap to ask about, never cheap to trade.
            if symbol and symbol not in self.allowed_symbols:
                sig.needs_clarification = "symbol"
                sig.symbol = None

            entry = sig.entry_price
            sl = sig.stop_loss

            # Filter 4: price sanity check
            if self.price_sanity_enabled and symbol in self.price_ranges and entry is not None:
                lo, hi = self.price_ranges[symbol]
                if not (lo <= float(entry) <= hi):
                    self.last_rejection_reason = f"Vision: {symbol} entry {entry} outside sane price range [{lo}, {hi}]"
                    logger.info(f"🚫 Vision: {symbol} entry {entry} outside range [{lo}, {hi}] — rejected")
                    continue
                if sl is not None and not (lo <= float(sl) <= hi):
                    self.last_rejection_reason = f"Vision: {symbol} SL {sl} outside sane price range [{lo}, {hi}]"
                    logger.info(f"🚫 Vision: {symbol} SL {sl} outside range [{lo}, {hi}] — rejected")
                    continue

            # Filter 5: SL distance check
            if self.sl_distance_check_enabled and entry is not None and sl is not None:
                try:
                    dist_pct = abs(float(entry) - float(sl)) / float(entry) * 100
                    if dist_pct > self.max_sl_distance_percent:
                        self.last_rejection_reason = (
                            f"Vision: {symbol} SL distance {dist_pct:.1f}% exceeds max {self.max_sl_distance_percent}%"
                        )
                        logger.info(f"🚫 Vision: {symbol} SL distance {dist_pct:.1f}% > max {self.max_sl_distance_percent}% — rejected")
                        continue
                except (ZeroDivisionError, TypeError, ValueError):
                    pass

            # Filter 7: direction consistency — SL must sit on the correct side of entry
            if sl_side_consistent(sig.order_type, entry, sl) is False:
                direction = sig.order_type.value if sig.order_type else '?'
                side = "below" if sig.order_type == OrderType.BUY else "above"
                self.last_rejection_reason = (
                    f"{direction} signal rejected: SL ({sl}) must be {side} entry ({entry}) for {direction}"
                )
                logger.error(f"🚨 Vision: {self.last_rejection_reason}")
                continue

            validated.append(sig)
        return validated

    def _parse_single_signal(self, data: dict, original_message: str) -> Optional[TradingSignal]:
        """Parse one signal dict entry into a TradingSignal."""
        try:
            is_plan = bool(data.get('is_plan', False))

            if data.get('is_signal') is False or data.get('action', '').upper() == 'NONE':
                reason = data.get('reason', '')
                self.last_rejection_reason = f"Vision: {reason}" if reason else "Vision: chart marked as non-signal"
                logger.debug(f"Vision: non-signal entry — {reason}")
                return None

            # Filter 2: AI self-confidence check.
            # Plans always require a manual dashboard trigger before they can execute
            # (see plan_filter_service / autoExecute=False), so a lower bar is safe here —
            # a human reviews every plan, unlike a direct signal that can auto-execute.
            confidence_val = data.get('confidence')
            if self.confidence_filter_enabled and confidence_val is not None:
                effective_min = self.min_confidence if not is_plan else min(self.min_confidence, 0.60)
                try:
                    if float(confidence_val) < effective_min:
                        reason = data.get('reason', '')
                        self.last_rejection_reason = (
                            f"Vision: confidence {confidence_val} below minimum {effective_min}"
                            + (f" — {reason}" if reason else "")
                        )
                        logger.info(f"🚫 Vision: confidence {confidence_val} < min {effective_min} — rejected")
                        return None
                except (TypeError, ValueError):
                    pass

            action_str = data.get('action', '').upper()
            action_map = {'OPEN': SignalAction.OPEN, 'CLOSE': SignalAction.CLOSE,
                          'MODIFY': SignalAction.MODIFY, 'PARTIAL_CLOSE': SignalAction.PARTIAL_CLOSE,
                          'CANCEL': SignalAction.CLOSE}
            action = action_map.get(action_str)
            if not action:
                return None

            entry_price = data.get('entry_price')
            stop_loss = data.get('stop_loss')
            symbol = data.get('symbol')

            order_type_str = data.get('order_type', '').upper()
            order_type = OrderType.BUY if order_type_str == 'BUY' else (
                OrderType.SELL if order_type_str == 'SELL' else None)
            if not order_type and entry_price and stop_loss:
                order_type = OrderType.BUY if float(stop_loss) < float(entry_price) else OrderType.SELL

            signal_type_str = data.get('signal_type', '').upper()
            signal_type_map = {'BUY_LIMIT': SignalType.BUY_LIMIT, 'SELL_LIMIT': SignalType.SELL_LIMIT,
                               'BUY_STOP': SignalType.BUY_STOP, 'SELL_STOP': SignalType.SELL_STOP}
            signal_type = signal_type_map.get(signal_type_str)

            # Use entry_range midpoint when no single entry_price
            if not entry_price:
                er = data.get('entry_range')
                if er and isinstance(er, list) and len(er) >= 2:
                    entry_price = (float(er[0]) + float(er[1])) / 2

            plan_data = data.get('plan') if is_plan else None
            has_plan_primary = is_plan and plan_data and plan_data.get('primary', {}).get('entry_min')

            needs_symbol_clarification = False

            # Validation for OPEN signals — trust the AI, only hard-block impossible combos
            if action == SignalAction.OPEN:
                # Try to get order_type from plan primary if still missing
                if not order_type and has_plan_primary:
                    pot = str(plan_data['primary'].get('order_type', '')).upper()
                    order_type = OrderType.BUY if pot == 'BUY' else (OrderType.SELL if pot == 'SELL' else None)
                if not order_type:
                    self.last_rejection_reason = f"Vision: could not determine direction (BUY/SELL) for {symbol or 'unknown symbol'}"
                    logger.warning(f"❌ Vision signal: no direction for {symbol}")
                    return None
                # Need at least entry or plan entry
                if not entry_price and not has_plan_primary:
                    self.last_rejection_reason = f"Vision: no entry price found for {symbol or 'unknown symbol'}"
                    logger.warning(f"❌ Vision signal: no entry for {symbol}")
                    return None
                # SL required for non-plan signals; plans allowed without SL (go to manual approval)
                plan_sl = plan_data.get('primary', {}).get('stop_loss') if plan_data else None
                if not stop_loss and not plan_sl and not is_plan:
                    self.last_rejection_reason = f"Vision: {symbol or 'unknown symbol'} setup has no stop loss (required for direct execution)"
                    logger.warning(f"❌ Vision signal: no SL for {symbol} (required for direct execution)")
                    return None
                # Symbol missing: direction + entry/SL/target are otherwise usable (SL is
                # already guaranteed present above for non-plan signals) — hold for
                # clarification instead of dropping a setup the chart clearly shows, or
                # worse, letting a misread symbol through to execution.
                if not symbol or len(str(symbol).strip()) < 2:
                    needs_symbol_clarification = True
                    symbol = None

            # Text-direction reconciliation — an explicit BUY/SELL written by the
            # trader is authoritative over what the vision model read from the chart
            if action == SignalAction.OPEN and order_type:
                text_dir = detect_explicit_direction(original_message)
                if text_dir and text_dir != order_type:
                    if is_plan:
                        self.last_rejection_reason = (
                            f"Direction conflict: message text says {text_dir.value} but vision plan's "
                            f"primary leg is {order_type.value} — rejected for safety"
                        )
                        logger.error(f"🚨 {self.last_rejection_reason}")
                        return None
                    if sl_side_consistent(text_dir, entry_price, stop_loss) is True:
                        logger.warning(
                            f"⚠️ Caption says {text_dir.value} but vision returned {order_type.value} — "
                            f"prices are consistent with {text_dir.value}, flipping to text direction"
                        )
                        order_type = text_dir
                        signal_type = None  # vision's limit/stop type no longer trustworthy
                    else:
                        # Vision may have swapped SL and TP (common with TradingView position tool
                        # when zone colours are ambiguous). Only treat this as a swap when vision's
                        # OWN reading is itself incoherent (SL on the wrong side for its own
                        # order_type) — if vision's SL/TP are already a self-consistent setup for
                        # the direction it reported, this is a genuine direction conflict, not a
                        # garbled swap, and must be rejected rather than "rescued".
                        vision_self_consistent = sl_side_consistent(order_type, entry_price, stop_loss) is True
                        raw_tp = data.get('take_profit') or []
                        candidate_sl = float(raw_tp[0]) if raw_tp else None
                        candidate_tp = [stop_loss] if stop_loss is not None else []
                        if (
                            not vision_self_consistent
                            and candidate_sl is not None
                            and sl_side_consistent(text_dir, entry_price, candidate_sl) is True
                        ):
                            logger.warning(
                                f"↔️ Vision SL/TP appear swapped vs caption direction. "
                                f"Caption: {text_dir.value}. Vision SL {stop_loss} → now TP, "
                                f"vision TP {raw_tp} → now SL {candidate_sl}. Accepting with swap."
                            )
                            stop_loss = candidate_sl
                            # Overwrite take_profit in data so the TP-direction validation below uses
                            # the corrected value. We store the old SL as TP(s).
                            data = dict(data)
                            data['take_profit'] = candidate_tp
                            data['stop_loss'] = stop_loss
                            order_type = text_dir
                            signal_type = None
                        else:
                            self.last_rejection_reason = (
                                f"Direction conflict: message text says {text_dir.value} but chart prices "
                                f"imply {order_type.value} — rejected for safety"
                            )
                            logger.error(f"🚨 {self.last_rejection_reason}")
                            return None

            # TP direction validation
            raw_take_profit = data.get('take_profit') or []
            take_profit = raw_take_profit
            if entry_price and order_type and take_profit:
                is_buy = (order_type == OrderType.BUY)
                take_profit = [
                    tp for tp in take_profit
                    if tp is not None and (
                        (is_buy and float(tp) > float(entry_price)) or
                        (not is_buy and float(tp) < float(entry_price))
                    )
                ]
                # Every TP the model itself reported landed on the wrong side of its own
                # entry — that's not a bad TP, it's a sign entry/SL were misread (e.g. a
                # structure label got bound to the wrong field, or a single digit was
                # misread — 4136 vs 4336). Applies to plans too: a broken plan sitting in
                # manual approval is still a broken plan, and auto-generating a fallback
                # TP here would silently mask the misread and approve garbage levels.
                if raw_take_profit and not take_profit:
                    self.last_rejection_reason = (
                        f"Vision: {symbol or 'unknown symbol'} {'plan ' if is_plan else ''}TP {raw_take_profit} is on the "
                        f"wrong side of entry {entry_price} for a {order_type.value} — "
                        f"entry/SL likely misread, rejected rather than guessing"
                    )
                    logger.warning(f"🚫 {self.last_rejection_reason}")
                    return None

            signal = TradingSignal(
                symbol=symbol,
                action=action,
                order_type=order_type,
                signal_type=signal_type,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                raw_message=original_message,
                confidence=0.8,
                is_plan=is_plan,
                plan_data=plan_data,
                needs_clarification="symbol" if needs_symbol_clarification else None,
            )
            return signal

        except Exception as e:
            logger.error(f"Error parsing single vision signal: {e}")
            return None

    def _parse_vision_response(self, response: str, original_message: str) -> list:
        """Parse vision AI response into a list of TradingSignals (0, 1, or many)."""
        try:
            import json
            # Log AI reasoning if present
            think_match = re.search(r'<think>(.*?)</think>', response, re.DOTALL | re.IGNORECASE)
            if think_match:
                logger.debug(f"Vision reasoning: {think_match.group(1).strip()}")
            # Strip think block before JSON parsing
            clean_response = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL | re.IGNORECASE)
            json_match = re.search(r'\{.*\}', clean_response, re.DOTALL)
            if not json_match:
                self.last_rejection_reason = "Vision: model response contained no parseable JSON"
                logger.warning("No JSON found in vision response")
                return []
            data = json.loads(json_match.group(0))

            # New format: {"signals": [...]}
            signals_raw = data.get('signals')
            if signals_raw is not None:
                if not signals_raw:
                    reason = data.get('reason', '')
                    self.last_rejection_reason = f"Vision: {reason}" if reason else "Vision: no signals found in chart"
                    logger.debug(f"Vision: no signals — {reason}")
                    return []
                results = []
                for i, entry in enumerate(signals_raw):
                    sig = self._parse_single_signal(entry, original_message)
                    if sig:
                        logger.info(f"✅ Vision signal {i+1}/{len(signals_raw)}: {sig.action} {sig.symbol}")
                        results.append(sig)
                return results

            # Legacy fallback: old single-signal format at top level
            sig = self._parse_single_signal(data, original_message)
            return [sig] if sig else []

        except Exception as e:
            logger.error(f"Error parsing vision response: {e}")
            return []
    
    def extract_complex_commands(self, message: str) -> Dict[str, Any]:
        """
        Extract complex trading commands from message text
        Handles: reenter, risky, limit, short sl, etc.
        
        Returns:
            Dictionary with command metadata
        """
        msg_upper = message.upper()
        commands = {
            'is_reenter': False,
            'is_risky': False,
            'is_limit_order': False,
            'is_stop_order': False,
            'is_breakeven': False,
            'is_partial_close': False,
            'risk_level': 'normal',
            'special_instructions': []
        }
        
        # Check for reenter
        reenter_keywords = ['REENTER', 'RE-ENTER', 'RE ENTER', 'ENTER AGAIN', 'BACK IN']
        if any(kw in msg_upper for kw in reenter_keywords):
            commands['is_reenter'] = True
            commands['special_instructions'].append('reenter_position')
            logger.debug("Detected: REENTER command")
        
        # Check for risky
        risky_keywords = ['RISKY', 'HIGH RISK', 'AGGRESSIVE', 'DANGEROUS', 'CAREFUL']
        if any(kw in msg_upper for kw in risky_keywords):
            commands['is_risky'] = True
            commands['risk_level'] = 'high'
            commands['special_instructions'].append('high_risk_trade')
            logger.debug("Detected: RISKY trade")
        
        # Check for limit order
        limit_keywords = ['LIMIT', 'BUY LIMIT', 'SELL LIMIT', 'LIMIT ORDER']
        if any(kw in msg_upper for kw in limit_keywords):
            commands['is_limit_order'] = True
            commands['special_instructions'].append('limit_order')
            logger.debug("Detected: LIMIT order")
        
        # Check for stop order
        stop_keywords = ['BUY STOP', 'SELL STOP', 'STOP ORDER', 'PENDING STOP']
        if any(kw in msg_upper for kw in stop_keywords):
            commands['is_stop_order'] = True
            commands['special_instructions'].append('stop_order')
            logger.debug("Detected: STOP order")
        
        # Check for breakeven
        be_keywords = ['BREAKEVEN', 'BREAK EVEN', 'BE', 'SET BE', 'MOVE TO BE', 'B/E']
        if any(kw in msg_upper for kw in be_keywords):
            commands['is_breakeven'] = True
            commands['special_instructions'].append('move_to_breakeven')
            logger.debug("Detected: BREAKEVEN command")
        
        # Check for partial close
        partial_keywords = ['PARTIAL', 'CLOSE HALF', 'CLOSE 50%', 'TAKE PROFIT 50%']
        if any(kw in msg_upper for kw in partial_keywords):
            commands['is_partial_close'] = True
            commands['special_instructions'].append('partial_close')
            logger.debug("Detected: PARTIAL CLOSE command")
        
        # Extract percentage for partial close
        percentage_match = re.search(r'(\d+)%', msg_upper)
        if percentage_match:
            commands['close_percentage'] = float(percentage_match.group(1))
        
        # Check for SL modification keywords
        sl_mod_keywords = ['MOVE SL', 'UPDATE SL', 'CHANGE SL', 'SL TO', 'SET SL']
        if any(kw in msg_upper for kw in sl_mod_keywords):
            commands['special_instructions'].append('modify_stop_loss')
            logger.debug("Detected: SL modification")
        
        # Check for TP modification keywords
        tp_mod_keywords = ['MOVE TP', 'UPDATE TP', 'CHANGE TP', 'TP TO', 'SET TP']
        if any(kw in msg_upper for kw in tp_mod_keywords):
            commands['special_instructions'].append('modify_take_profit')
            logger.debug("Detected: TP modification")
        
        return commands
