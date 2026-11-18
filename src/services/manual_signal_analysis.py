"""
Signal analysis for a trade the owner places by hand from the Telegram page.

The automatic flow decides whether a message is worth trading at all: the intent
gate, caption and image-size pre-filters, the two-step image classifier, the
confidence / price-sanity / SL-distance filters and the ENABLE_AI_VISION switch.
Here the owner has already decided — they picked the message — so none of that
applies:

  • text AI runs without the intent gate;
  • vision runs on the image even when ENABLE_AI_VISION is off for the
    automatic flow, and its reading is taken leniently: a missing or doubtful
    level becomes a note for the owner, not a rejection;
  • the result is a proposal the owner checks and edits, never a trade.

It also leaves the live flow alone: own processor instances (no shared state
with the listener), and no plan registration, clarification question, channel
context update or failure notification.
"""
import json
import re
from dataclasses import dataclass, field
from typing import List, Optional

from loguru import logger

from src.models import TradingSignal, SignalAction, OrderType

# Appended to the vision prompt. The automatic prompt is tuned to return nothing
# when in doubt; a human checks every number here, so a partial reading helps more.
MANUAL_REVIEW_NOTE = """

## MANUAL REVIEW MODE — overrides the "return empty when in doubt" rules above
A trader picked this chart to trade by hand and will check every number before
anything is placed. Do NOT return an empty list because the setup is incomplete,
risky, a forecast/analysis chart, or the caption is commentary. Give your best
reading of ONE setup: symbol, direction, entry (price or zone), stop loss and
take profits. Use null for any level you cannot read — never guess digits.
Return an empty list only when the image is not a price chart at all.
"""


@dataclass
class ManualAnalysis:
    signal: Optional[TradingSignal] = None
    source: str = ""                 # "text", "image" or "text+image"
    reason: Optional[str] = None     # why nothing was found
    notes: List[str] = field(default_factory=list)  # things the owner should check


def _num(value) -> Optional[float]:
    try:
        return float(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def _direction(value) -> Optional[OrderType]:
    v = str(value or "").upper()
    return OrderType.BUY if v.startswith("BUY") else OrderType.SELL if v.startswith("SELL") else None


def setup_from_vision_response(response: str) -> tuple:
    """(TradingSignal | None, notes, reason) from the vision model's raw answer.

    Lenient on purpose: takes whatever levels the model read, fills direction from
    the plan or the SL side, and turns doubts into notes instead of rejecting.
    """
    clean = re.sub(r"<think>.*?</think>", "", response or "", flags=re.DOTALL | re.IGNORECASE)
    match = re.search(r"\{.*\}", clean, re.DOTALL)
    if not match:
        return None, [], "The vision model gave no readable answer"
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None, [], "The vision model gave no readable answer"

    entries = data.get("signals")
    if entries is None:
        entries = [data]  # legacy single-signal shape
    entries = [e for e in entries if isinstance(e, dict)]
    if not entries:
        return None, [], f"Chart: {data.get('reason') or 'no setup found'}"

    notes = []
    if len(entries) > 1:
        notes.append(f"The chart has {len(entries)} setups — showing the first")
    e = entries[0]
    primary = ((e.get("plan") or {}).get("primary") or {}) if e.get("is_plan") else {}

    entry = _num(e.get("entry_price"))
    rng = e.get("entry_range") or [primary.get("entry_min"), primary.get("entry_max")]
    lo, hi = (_num(rng[0]), _num(rng[1])) if isinstance(rng, list) and len(rng) >= 2 else (None, None)
    if entry is None and lo is not None and hi is not None and lo == hi:
        entry, lo, hi = lo, None, None
    if lo is not None and hi is not None and lo > hi:
        lo, hi = hi, lo
    sl = _num(e.get("stop_loss")) if e.get("stop_loss") is not None else _num(primary.get("stop_loss"))
    tps = [t for t in (_num(x) for x in (e.get("take_profit") or primary.get("take_profits") or [])) if t is not None]

    order_type = _direction(e.get("order_type")) or _direction(primary.get("order_type"))
    ref = entry if entry is not None else ((lo + hi) / 2 if lo is not None and hi is not None else None)
    if order_type is None and ref is not None and sl is not None and sl != ref:
        order_type = OrderType.BUY if sl < ref else OrderType.SELL

    if order_type is None and ref is None and sl is None and not tps:
        return None, [], f"Chart: {e.get('reason') or 'no levels could be read'}"

    if e.get("is_plan"):
        notes.append("Read as a plan/forecast chart — levels are where the drawn path starts and ends")

    signal = TradingSignal(
        symbol=(str(e["symbol"]).strip().upper() or None) if e.get("symbol") else None,
        action=SignalAction.OPEN,
        order_type=order_type,
        entry_price=entry,
        entry_range_min=lo if entry is None else None,
        entry_range_max=hi if entry is None else None,
        stop_loss=sl,
        take_profit=tps,
        confidence=_num(e.get("confidence")) or 0.0,
        ai_raw_response=response,
    )
    return signal, notes, None


def review_notes(signal: TradingSignal) -> List[str]:
    """What the owner must fill in or double-check before placing a new trade."""
    if signal.action not in (None, SignalAction.OPEN):
        return []
    notes = []
    if not signal.symbol:
        notes.append("Symbol could not be read — enter it")
    if signal.order_type is None:
        notes.append("Direction could not be read — choose BUY or SELL")
    entry = signal.entry_price
    if entry is None and signal.entry_range_min is not None and signal.entry_range_max is not None:
        entry = (signal.entry_range_min + signal.entry_range_max) / 2
    sl = signal.stop_loss
    if sl is None:
        notes.append("No stop loss — add one before placing")
    elif signal.order_type and entry is not None and (sl < entry) != (signal.order_type == OrderType.BUY):
        side = "below" if signal.order_type == OrderType.BUY else "above"
        notes.append(f"Stop loss {sl} is not {side} the entry for a {signal.order_type.value} — check it")
    return notes


def merge_text_and_chart(text_signal: Optional[TradingSignal], chart: Optional[TradingSignal]) -> tuple:
    """Fields the trader wrote win; the chart fills what the text left out."""
    if text_signal is None:
        return chart, []
    if chart is None:
        return text_signal, []
    notes = []
    if text_signal.order_type and chart.order_type and text_signal.order_type != chart.order_type:
        notes.append(f"The message says {text_signal.order_type.value} but the chart reads "
                     f"{chart.order_type.value} — kept the message's direction, check the levels")
    text_signal.symbol = text_signal.symbol or chart.symbol
    text_signal.order_type = text_signal.order_type or chart.order_type
    has_entry = text_signal.entry_price is not None or text_signal.entry_range_min is not None
    if not has_entry:
        text_signal.entry_price = chart.entry_price
        text_signal.entry_range_min = chart.entry_range_min
        text_signal.entry_range_max = chart.entry_range_max
    if text_signal.stop_loss is None:
        text_signal.stop_loss = chart.stop_loss
    if not text_signal.take_profit:
        text_signal.take_profit = list(chart.take_profit)
    return text_signal, notes


async def _read_chart(config, caption: str, image_data) -> tuple:
    """Vision reading of the chart. Returns (signal | None, notes, reason)."""
    from ai.image_signal_extractor import ImageSignalExtractor
    from ai.llm_client import complete_with_fallback, provider_chain, extract_content, max_tokens_for

    extractor = ImageSignalExtractor(config)
    if extractor.client is None:
        extractor._init_client(config)  # vision is on for hand-picked trades even when off for the automatic flow
    if extractor.client is None:
        return None, [], "No vision-capable AI provider has an API key — the image could not be read"

    import base64
    images = image_data if isinstance(image_data, list) else [image_data]
    content = [{"type": "text", "text": extractor._get_vision_prompt(caption) + MANUAL_REVIEW_NOTE}] + [
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64.b64encode(img).decode()}"}}
        for img in images
    ]

    def _vision_call(client, model, provider):
        return client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You read trade setups off charts for a trader who checks every number."},
                {"role": "user", "content": content},
            ],
            temperature=extractor.temperature,
            max_tokens=max_tokens_for(config, provider, output_tokens=1500, vision=True),
        )

    try:
        response = complete_with_fallback(
            config, provider_chain(config, vision=True), _vision_call, vision=True,
            validate=lambda r: bool(extract_content(r).strip()), caller='vision_manual',
        )
    except Exception as e:
        logger.warning(f"⚠️ Manual chart reading failed: {e}")
        return None, [], f"Vision AI error: {e}"
    return setup_from_vision_response(extract_content(response))


async def analyze_manual_message(text: str, image_data=None) -> ManualAnalysis:
    """Best reading of a hand-picked message for the owner to review — never placed from here."""
    from ai.integrated_processor import IntegratedProcessor
    from src.services.signal_service import signal_service
    from src.utils.symbols import normalize_symbol

    config = signal_service.ai_config
    text = text or ""
    text_signal, text_reason = None, None
    if len(text.strip()) >= 3:
        processor = IntegratedProcessor(config)  # own instance: nothing shared with the live listener
        text_signal = await processor._try_ai_processing(text)
        if text_signal is None:
            text_reason = processor.rejection_reason or "The text AI found no trade in the message"
        elif text_signal.action != SignalAction.OPEN or processor._is_signal_complete(text_signal):
            # A command, or a complete setup: the chart has nothing to add.
            text_signal.symbol = normalize_symbol(text_signal.symbol) if text_signal.symbol else None
            return ManualAnalysis(text_signal, "text", None, review_notes(text_signal))

    chart, notes, chart_reason = None, [], None
    if image_data:
        chart, notes, chart_reason = await _read_chart(config, text, image_data)

    signal, merge_notes = merge_text_and_chart(text_signal, chart)
    if signal is None:
        reason = chart_reason or text_reason or "No text or image to analyse"
        return ManualAnalysis(None, "", reason)

    if signal.symbol:
        signal.symbol = normalize_symbol(signal.symbol)
    source = "text+image" if text_signal and chart else "text" if text_signal else "image"
    if text_signal and image_data and not chart and chart_reason:
        notes.append(f"Image not used: {chart_reason}")
    return ManualAnalysis(signal, source, None, merge_notes + notes + review_notes(signal))
