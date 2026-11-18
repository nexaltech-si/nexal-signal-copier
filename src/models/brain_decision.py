from dataclasses import dataclass
from typing import Optional, List


@dataclass
class BrainDecision:
    verdict: str  # APPROVE | REJECT | MODIFY
    reason: str
    modified_entry: Optional[float] = None
    modified_sl: Optional[float] = None
    modified_tp: Optional[List[float]] = None
    modified_lot: Optional[float] = None
    # Set when the brain is unavailable and BRAIN_UNAVAILABLE_ACTION=APPROVAL —
    # forces the signal through the manual approval queue regardless of other flags
    force_approval: bool = False


@dataclass
class BrainAction:
    action: str  # HOLD | MODIFY_SL | MODIFY_TP | PARTIAL_CLOSE | CLOSE
    value: Optional[float] = None
    percentage: Optional[float] = None
    reason: str = ""
