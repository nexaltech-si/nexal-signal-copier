"""
Telegram Browser API Router
Provides read-only dialog/message browsing and manual signal execution for the dashboard.
Completely isolated from the main listener — all failures return empty data, never raise.
"""
from typing import Optional, List

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from loguru import logger

from src.services.telegram_browser_service import telegram_browser_service

telegram_browser_router = APIRouter(prefix="/api/telegram-browser")


class SignalEdits(BaseModel):
    """User-edited core trade fields sent back on confirm. Any field left None
    keeps the AI-parsed value. Editing is scoped to core trade fields only."""
    symbol: Optional[str] = None
    action: Optional[str] = None          # OPEN | CLOSE | PARTIAL_CLOSE | MODIFY
    order_type: Optional[str] = None      # BUY | SELL
    entry_price: Optional[float] = None
    entry_range_min: Optional[float] = None
    entry_range_max: Optional[float] = None
    # Discrete scale-in legs (>=2 same-direction prices sharing this signal's
    # SL + TPs). None/[] keeps single-entry behaviour. Mutually exclusive with an
    # entry range — a range is one zone, legs are discrete points.
    entries: Optional[List[float]] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[List[float]] = None


class ExecuteRequest(BaseModel):
    channel_id: str
    message_id: int
    text: str
    # Phase 1 (preview): dry_run=True → parse only, never touches the market.
    # Phase 2 (confirm): dry_run=False + optional `edits` → place the trade.
    dry_run: bool = True
    edits: Optional[SignalEdits] = None


class ResolveSymbolRequest(BaseModel):
    clarification_id: str
    symbol: str


@telegram_browser_router.get("/dialogs")
async def get_dialogs(limit: int = 200):
    dialogs = await telegram_browser_service.get_dialogs(limit=min(limit, 500))
    return {"dialogs": dialogs}


@telegram_browser_router.get("/messages/{channel_id}")
async def get_messages(channel_id: str, limit: int = 50):
    try:
        cid = int(channel_id)
    except ValueError:
        return {"messages": []}
    messages = await telegram_browser_service.get_messages(cid, limit=min(limit, 100))
    return {"messages": messages}


@telegram_browser_router.get("/channel-photo/{channel_id}")
async def get_channel_photo(channel_id: str):
    try:
        cid = int(channel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid channel_id")
    data, content_type = await telegram_browser_service.get_channel_photo(cid)
    if not data:
        raise HTTPException(status_code=404, detail="No profile photo found")
    return Response(content=data, media_type=content_type)


@telegram_browser_router.get("/media/{channel_id}/{message_id}")
async def get_media(channel_id: str, message_id: int):
    try:
        cid = int(channel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid channel_id")
    data, content_type = await telegram_browser_service.get_message_media(cid, message_id)
    if not data:
        raise HTTPException(status_code=404, detail="No image media found")
    return Response(content=data, media_type=content_type)


@telegram_browser_router.post("/execute")
async def execute_signal(req: ExecuteRequest):
    """Manual trade from a hand-picked message, independent of the automatic flow.

    Preview (dry_run) reads the text and the image with manual_signal_analysis —
    no intent gate, vision on even when ENABLE_AI_VISION is off, nothing written
    to the live flow. Confirm places exactly the reviewed fields: no second AI
    call that could read the chart differently.
    """
    image_data = None
    try:
        cid = int(req.channel_id)
        img_bytes, _ = await telegram_browser_service.get_message_media(cid, req.message_id)
        if img_bytes:
            image_data = img_bytes
            logger.info(f"🖼️ Browser execute: fetched image ({len(img_bytes):,} bytes) for message {req.message_id}")
    except Exception as e:
        logger.debug(f"Browser execute: no image for message {req.message_id}: {e}")

    # Phase 1 — preview. Return the reading for review/edit; place nothing.
    if req.dry_run:
        try:
            from src.services.manual_signal_analysis import analyze_manual_message
            analysis = await analyze_manual_message(req.text, image_data)
        except Exception as e:
            logger.warning(f"⚠️ Browser execute analysis failed: {e}")
            return {"extracted": False, "signal": None, "error": str(e), "has_image": bool(image_data)}
        if analysis.signal is None:
            return {"extracted": False, "signal": None, "error": None,
                    "rejection_reason": analysis.reason, "has_image": bool(image_data)}
        return {"extracted": True, "placed": False, "signal": _signal_to_dict(analysis.signal),
                "source": analysis.source, "notes": analysis.notes, "error": None,
                "has_image": bool(image_data)}

    # Phase 2 — confirm. Place the reviewed trade.
    if req.edits is None:
        return {"extracted": False, "placed": False, "signal": None,
                "error": "Nothing to place — review the trade first"}
    if (req.edits.action or "OPEN").strip().upper() != "OPEN":
        signal, problem = await _command_from_text(req)
    else:
        signal, problem = _signal_from_edits(req, image_data)
    if problem:
        return {"extracted": True, "placed": False, "signal": None, "error": problem}
    signal_data = _signal_to_dict(signal)
    try:
        from src.services.trading_service import trading_service
        await trading_service.process_signal(signal)
    except Exception as e:
        logger.warning(f"⚠️ Browser execute process_signal failed: {e}")
        return {"extracted": True, "placed": False, "signal": signal_data, "error": str(e)}

    return {"extracted": True, "placed": True, "signal": signal_data, "error": None}


def _signal_from_edits(req: ExecuteRequest, image_data) -> tuple:
    """New trade (TradingSignal, None) built from the reviewed fields, or (None, what is wrong)."""
    from src.models import TradingSignal
    from src.models.enums import SignalAction
    from src.utils.symbols import normalize_symbol

    signal = TradingSignal(action=SignalAction.OPEN)
    _apply_edits(signal, req.edits)
    if signal.symbol:
        signal.symbol = normalize_symbol(signal.symbol)
    if not signal.symbol or signal.order_type is None:
        return None, "Symbol and direction are required"
    bad = _sl_side_problem(signal)
    if bad:
        return None, bad
    # Rebuilt so __post_init__ derives the limit/stop type and TP list from the final levels.
    signal = TradingSignal(**{f: getattr(signal, f) for f in (
        'symbol', 'action', 'order_type', 'entry_price', 'entry_range_min', 'entry_range_max',
        'entries', 'stop_loss', 'take_profit')})
    _mark_manual(signal, req, image_data)
    return signal, None


async def _command_from_text(req: ExecuteRequest) -> tuple:
    """Trade-management command (close, modify…) read from the message text alone."""
    from src.models.enums import SignalAction
    from src.services.manual_signal_analysis import analyze_manual_message
    from src.services.trade_context_manager import trade_context_manager

    analysis = await analyze_manual_message(req.text)
    signal = analysis.signal
    if signal is None or signal.action in (None, SignalAction.OPEN):
        return None, analysis.reason or "The message is not a trade-management command"
    if req.edits.symbol:
        signal.symbol = req.edits.symbol.strip().upper()
    if not signal.symbol:
        signal = await trade_context_manager.resolve_symbol_from_context(signal, req.channel_id)
    _mark_manual(signal, req, None)
    return signal, None


def _mark_manual(signal, req: ExecuteRequest, image_data) -> None:
    from datetime import datetime, timezone
    from src.models.enums import SignalStatus
    signal.channel_id = req.channel_id
    signal.message_id = req.message_id
    signal.raw_message = req.text
    signal.image_data = image_data
    signal.timestamp = datetime.now(timezone.utc)
    signal.status = SignalStatus.VALIDATED
    signal.confidence = 1.0
    signal.manual_placement = True  # owner-reviewed: skips the automatic flow's judgement


def _sl_side_problem(signal) -> Optional[str]:
    from src.models.enums import OrderType
    entry = signal.entry_price
    if entry is None and signal.entry_range_min is not None and signal.entry_range_max is not None:
        entry = (signal.entry_range_min + signal.entry_range_max) / 2
    if entry is None or signal.stop_loss is None:
        return None
    is_buy = signal.order_type == OrderType.BUY
    if (signal.stop_loss < entry) != is_buy:
        return f"Stop loss must be {'below' if is_buy else 'above'} the entry for a {signal.order_type.value}"
    return None


def _signal_to_dict(signal) -> dict:
    return {
        "symbol": signal.symbol,
        "action": signal.action.value if signal.action else None,
        "order_type": signal.order_type.value if signal.order_type else None,
        "entry_price": signal.entry_price,
        "entry_range_min": signal.entry_range_min,
        "entry_range_max": signal.entry_range_max,
        # Canonical scale-in legs (>=2 distinct prices) or None; the dashboard
        # uses this to show/edit legs. Falls back to the raw field for signals
        # built before discrete_entry_prices() existed.
        "entries": (
            signal.discrete_entry_prices()
            if hasattr(signal, "discrete_entry_prices")
            else signal.entries
        ),
        "stop_loss": signal.stop_loss,
        "take_profit": signal.take_profit,
        "confidence": signal.confidence,
        "signal_id": signal.signal_id,
        "is_plan": signal.is_plan,
    }


def _apply_edits(signal, edits: "SignalEdits") -> None:
    """Overlay user-edited core trade fields onto the parsed signal in place.
    Enum fields are validated; an unknown value is ignored (parsed value kept)."""
    from src.models.enums import SignalAction, OrderType

    if edits.symbol is not None:
        signal.symbol = edits.symbol.strip().upper() or signal.symbol
    if edits.action is not None:
        try:
            signal.action = SignalAction(edits.action.strip().upper())
        except ValueError:
            logger.warning(f"Browser edit: ignoring invalid action {edits.action!r}")
    if edits.order_type is not None:
        try:
            signal.order_type = OrderType(edits.order_type.strip().upper())
        except ValueError:
            logger.warning(f"Browser edit: ignoring invalid order_type {edits.order_type!r}")
    if edits.entry_price is not None:
        signal.entry_price = edits.entry_price
    if edits.entry_range_min is not None:
        signal.entry_range_min = edits.entry_range_min
    if edits.entry_range_max is not None:
        signal.entry_range_max = edits.entry_range_max

    # Scale-in legs. Edits mutate in place and bypass __post_init__, so we
    # re-establish the model's invariants by hand:
    #   • de-dup preserving order; <2 distinct prices ⇒ not a real multi-entry
    #   • entry_price must equal entries[0] (the primary leg)
    #   • legs and an entry range are mutually exclusive (a range is one zone)
    # SL/TP stay shared automatically — the provider applies the single
    # signal.stop_loss + paired TP per leg; there is no per-leg SL/TP to break.
    if edits.entries is not None:
        seen: set = set()
        legs = [
            float(e) for e in edits.entries
            if e is not None and not (float(e) in seen or seen.add(float(e)))
        ]
        if len(legs) >= 2:
            signal.entries = legs
            signal.entry_price = legs[0]
            signal.entry_range_min = None
            signal.entry_range_max = None
        else:
            # Collapsed to a single entry: drop legs, keep entry_price sensible.
            signal.entries = None
            if legs:
                signal.entry_price = legs[0]

    if edits.stop_loss is not None:
        signal.stop_loss = edits.stop_loss
    if edits.take_profit is not None:
        signal.take_profit = edits.take_profit


@telegram_browser_router.post("/resolve-symbol")
async def resolve_symbol(req: ResolveSymbolRequest):
    """Answer a pending 'which instrument is this?' clarification from the dashboard."""
    from src.services.signal_clarification_service import signal_clarification_service
    ok, message = await signal_clarification_service.resolve(req.clarification_id, req.symbol)
    return {"ok": ok, "message": message}
