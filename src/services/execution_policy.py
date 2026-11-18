"""
Execution policy for NEW trades — the one place that decides

  1. whether a signal may use instant ("NOW") execution, and
  2. whether it needs manual approval, and why.

Approval priority (first match wins):

  1. Safety gate      signal.force_manual_approval — status caption, "no entry /
                      waiting confirmation" caption, vision from a non-trading
                      caption, brain unavailable with BRAIN_UNAVAILABLE_ACTION=APPROVAL
  2. High-risk        risk above Max Risk Per Trade with ALLOW_HIGH_RISK_OVERRIDE on
  2b. Estimated size  lot size came from an estimated pip value (broker symbol data
                      unavailable) and REQUIRE_APPROVAL_FOR_ESTIMATED_SIZING is on
  3. Image signal     REQUIRE_APPROVAL_FOR_IMAGES and the message carried an image
                      (independent of the Manual Approval switch)
  4. Manual approval  REQUIRE_MANUAL_APPROVAL on — every channel, or only the
                      channels in APPROVAL_REQUIRED_CHANNELS when that list is set
  5. otherwise        auto-execute

Instant execution never lowers an approval gate: a word typed by the channel
("now") must not override a rule the owner set. It changes HOW a signal is
placed once it is allowed through (market fill within a deviation cap, see
BaseTradingProvider.instant_market_entry; beyond the cap one order still fills
at the same money risk while the move is young, see instant_one_leg_entry),
not WHETHER it is placed.
"""
from dataclasses import dataclass
from typing import Optional, Tuple

from config import settings


@dataclass(frozen=True)
class ApprovalDecision:
    required: bool
    reason: str


def _channel_list(raw) -> list:
    if not raw:
        return []
    if isinstance(raw, (list, tuple)):
        return [str(c).strip() for c in raw if str(c).strip()]
    return [c.strip() for c in str(raw).split(',') if c.strip()]


def instant_execution_allowed(channel_id: Optional[str]) -> Tuple[bool, str]:
    """Owner permission for instant execution from this channel."""
    if not settings.enable_instant_execution:
        return False, "instant execution is disabled"
    allowed = _channel_list(settings.instant_execution_channels)
    if not allowed:
        return True, "no channel restriction"
    if str(channel_id or '').strip() in allowed:
        return True, "channel is authorized"
    return False, "channel is not in Instant Execution Channels"


def instant_max_deviation_price(symbol: Optional[str]) -> float:
    """INSTANT_EXECUTION_MAX_DEVIATION_PIPS converted to a price distance for symbol."""
    from src.utils.pip_utils import get_pip_size
    pips = float(getattr(settings, 'instant_execution_max_deviation_pips', 0) or 0)
    return max(pips, 0.0) * get_pip_size(symbol)


def approval_decision(signal, high_risk_override: bool = False, estimated_sizing: bool = False) -> ApprovalDecision:
    """Whether this new trade waits for manual approval (see module docstring for priority)."""
    # Placed by hand from the dashboard: the owner approved it in the review dialog.
    # Only the sizing gates still apply — that dialog does not show the lot size.
    manual = getattr(signal, 'manual_placement', False) is True
    if getattr(signal, 'force_manual_approval', False) and not manual:
        return ApprovalDecision(True, "safety gate (message doubts it is a fresh entry, or brain unavailable)")
    if high_risk_override:
        return ApprovalDecision(True, "risk exceeds Max Risk Per Trade (high-risk override)")
    if estimated_sizing and getattr(settings, 'require_approval_for_estimated_sizing', True):
        return ApprovalDecision(True, "lot size uses an estimated pip value (Require Approval for Estimated Sizing)")
    if manual:
        return ApprovalDecision(False, "placed by hand from the dashboard")
    if settings.require_approval_for_images and getattr(signal, 'image_data', None):
        return ApprovalDecision(True, "signal has an image (Require Approval for Images)")
    if settings.require_manual_approval:
        channels = _channel_list(settings.approval_required_channels)
        if not channels:
            return ApprovalDecision(True, "Manual Approval is on for all channels")
        if str(getattr(signal, 'channel_id', '') or '').strip() in channels:
            return ApprovalDecision(True, "channel is in Channels Requiring Approval")
        return ApprovalDecision(False, "channel is not in Channels Requiring Approval")
    return ApprovalDecision(False, "no approval rule applies")
