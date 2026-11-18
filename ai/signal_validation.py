"""
Shared signal validation helpers.

Pure functions used by both the text path (IntegratedProcessor) and the
vision path (ImageSignalExtractor) so direction detection and SL-placement
rules stay identical across extraction methods.
"""
import re
from typing import Optional

from src.models import OrderType


def detect_explicit_direction(message: str) -> Optional[OrderType]:
    """
    Detect an explicit BUY/SELL direction stated in the message text.

    Returns OrderType.BUY or OrderType.SELL only when exactly one side is
    mentioned. Returns None when neither side is mentioned, or when BOTH are
    (e.g. plan captions like "BUY above X / SELL below Y").
    """
    if not message:
        return None

    # Market-commentary phrases that contain direction words but are not a trade direction:
    # "short-term bullish", "long term view", "short squeeze", "short covering".
    message = re.sub(
        r'\b(?:short|long)[\s-]*term\b|\bshort\s+(?:squeeze|covering)\b',
        ' ',
        message,
        flags=re.IGNORECASE
    )
    msg_upper = message.upper()

    # Strip non-signal contextual SELL phrases before keyword scanning.
    # "selling pressure", "sellers", "sell stop orders wiped out" all contain
    # the substring SELL but describe market context, not a signal direction.
    msg_for_sell_check = re.sub(
        r'\bsell\s+stop\b|\bselling\b|\bsellers?\b',
        '',
        message,
        flags=re.IGNORECASE
    ).upper()

    # Use word-boundary matching to avoid partial-word false positives
    buy_patterns = [r'\bBUY\b', r'\bLONG\b', r'\bGOING LONG\b', r'\bENTER LONG\b']
    sell_patterns = [r'\bSELL\b', r'\bSHORT\b', r'\bGOING SHORT\b', r'\bENTER SHORT\b']

    has_buy = any(re.search(p, msg_upper) for p in buy_patterns)
    has_sell = any(re.search(p, msg_for_sell_check) for p in sell_patterns)

    if has_buy and not has_sell:
        return OrderType.BUY
    if has_sell and not has_buy:
        return OrderType.SELL
    return None


def sl_side_consistent(
    order_type: Optional[OrderType],
    entry: Optional[float],
    stop_loss: Optional[float],
) -> Optional[bool]:
    """
    Check that the stop loss sits on the correct side of the entry price
    for the given direction (BUY: SL below entry; SELL: SL above entry).

    Returns True/False when checkable, None when entry, SL, or direction
    is missing.
    """
    if order_type is None or entry is None or stop_loss is None:
        return None
    try:
        entry_f = float(entry)
        sl_f = float(stop_loss)
    except (TypeError, ValueError):
        return None
    if order_type == OrderType.BUY:
        return sl_f < entry_f
    return sl_f > entry_f
