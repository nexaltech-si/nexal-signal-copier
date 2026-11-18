"""
Shared AI-processing utilities.

Single home for small helpers that were previously copy-pasted across the
AI processors.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def safe_float(value) -> Optional[float]:
    """Safely convert a value to float, returning None if conversion fails."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError) as e:
        logger.warning(f"Failed to convert value to float: {value}, error: {e}")
        return None


def clean_json_response(response: str) -> str:
    """
    Extract a JSON object from an AI response.

    Handles the common cases where models wrap the JSON in markdown fences or
    add a sentence of explanation before/after the object (e.g. "Here is the
    extracted signal: {...}\\n\\nNote: ...").
    """
    clean = (response or "").strip()

    # Strip triple-backtick fences first
    if clean.startswith('```json'):
        clean = clean[7:]
        if clean.endswith('```'):
            clean = clean[:-3]
        clean = clean.strip()
    elif clean.startswith('```'):
        clean = clean[3:]
        if clean.endswith('```'):
            clean = clean[:-3]
        clean = clean.strip()

    # Extract the outermost {...} block using brace tracking.
    # This handles both preamble and postamble text added by some models,
    # correctly nesting into plan/sub-objects without stopping at inner '}'.
    start = clean.find('{')
    if start == -1:
        return clean
    depth = 0
    in_string = False
    escape_next = False
    for i, ch in enumerate(clean[start:], start=start):
        if escape_next:
            escape_next = False
            continue
        if ch == '\\' and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return clean[start:i + 1]
    return clean
