"""
Approval Queue Service
Manages pending signals awaiting manual approval with timeout handling
"""
import asyncio
from typing import Optional, Dict
from datetime import datetime, timezone, timedelta
from loguru import logger
from src.utils.tasks import spawn

from src.models import TradingSignal, RiskAssessment
from config import settings
from src.core.database_service import db_service


class PendingSignal:
    """Represents a signal awaiting approval"""
    
    def __init__(
        self,
        signal_id: str,
        signal: TradingSignal,
        risk_assessment: RiskAssessment,
        created_at: datetime,
        timeout_minutes: int
    ):
        self.signal_id = signal_id
        self.signal = signal
        self.risk_assessment = risk_assessment
        self.created_at = created_at
        self.timeout_at = created_at + timedelta(minutes=timeout_minutes)
        self.is_expired = False
        self.is_approved = False
        self.is_rejected = False
    
    def check_timeout(self) -> bool:
        """Check if signal has timed out"""
        if datetime.now(timezone.utc) >= self.timeout_at:
            self.is_expired = True
            return True
        return False
    
    def get_remaining_seconds(self) -> int:
        """Get remaining seconds before timeout"""
        remaining = (self.timeout_at - datetime.now(timezone.utc)).total_seconds()
        return max(0, int(remaining))


class ApprovalQueue:
    """
    Manages pending signals awaiting manual approval
    Handles timeout logic independently from message processing
    """
    
    def __init__(self):
        self._pending_signals: Dict[str, PendingSignal] = {}
        self._timeout_task: Optional[asyncio.Task] = None
        self._running = False
        self.paused: bool = False
    
    async def start(self):
        """Start the timeout monitor"""
        if self._running:
            logger.warning("Approval queue already running")
            return
        
        self._running = True
        self._timeout_task = asyncio.create_task(self._timeout_monitor())
        logger.info("✅ Approval queue started")
    
    async def stop(self):
        """Stop the timeout monitor"""
        self._running = False
        if self._timeout_task:
            self._timeout_task.cancel()
            try:
                await self._timeout_task
            except asyncio.CancelledError:
                pass
        logger.info("🛑 Approval queue stopped")
    
    async def add_pending_signal(
        self,
        signal_id: str,
        signal: TradingSignal,
        risk_assessment: RiskAssessment
    ) -> PendingSignal:
        """
        Add a signal to the approval queue
        
        Args:
            signal_id: Database signal ID
            signal: Trading signal
            risk_assessment: Risk assessment result
            
        Returns:
            PendingSignal object
        """
        timeout_minutes = settings.approval_timeout_minutes
        
        pending = PendingSignal(
            signal_id=signal_id,
            signal=signal,
            risk_assessment=risk_assessment,
            created_at=datetime.now(timezone.utc),
            timeout_minutes=timeout_minutes
        )
        
        self._pending_signals[signal_id] = pending
        
        logger.info(f"📋 Signal {signal_id[:8]}... added to approval queue")
        logger.info(f"   ⏰ Will timeout in {timeout_minutes} minutes")
        logger.info(f"   📊 Queue size: {len(self._pending_signals)}")
        
        return pending

    async def add_signal(self, signal: TradingSignal, risk_assessment: RiskAssessment) -> str:
        """
        Save signal to DB (if not already saved), queue for approval, return signal_id.
        Used by the first-generation process_signal pipeline.
        """
        from src.core.database_service import db_service

        signal_id = getattr(signal, 'signal_id', None)
        if not signal_id:
            from src.models.message import MessageIdentifier
            from datetime import datetime, timezone
            import hashlib
            raw_mid = getattr(signal, 'message_id', None) or 0
            raw_cid = str(getattr(signal, 'channel_id', '') or '')
            msg_hash = hashlib.md5(f"{raw_cid}:{raw_mid}".encode(), usedforsecurity=False).hexdigest()
            message_id = MessageIdentifier(
                chat_id=raw_cid,
                message_id=int(raw_mid),
                message_hash=msg_hash,
                timestamp=datetime.now(timezone.utc),
            )
            signal_id = await db_service.save_signal(signal, message_id)

        await db_service.update_signal_status(signal_id, "AWAITING_APPROVAL")
        await self.add_pending_signal(signal_id, signal, risk_assessment)
        return signal_id

    def get_pending_signal(self, signal_id: str) -> Optional[PendingSignal]:
        """Get a pending signal by ID"""
        return self._pending_signals.get(signal_id)
    
    def approve_signal(self, signal_id: str) -> Optional[PendingSignal]:
        """
        Approve a pending signal
        
        Args:
            signal_id: Signal ID to approve
            
        Returns:
            PendingSignal if found and approved, None otherwise
        """
        pending = self._pending_signals.get(signal_id)
        
        if not pending:
            logger.warning(f"Signal {signal_id[:8]}... not found in queue")
            return None
        
        if pending.is_expired:
            logger.warning(f"Signal {signal_id[:8]}... has expired")
            return None
        
        if pending.is_rejected:
            logger.warning(f"Signal {signal_id[:8]}... was already rejected")
            return None
        
        pending.is_approved = True
        logger.success(f"✅ Signal {signal_id[:8]}... approved")
        
        # Remove from queue
        del self._pending_signals[signal_id]
        
        return pending
    
    def reject_signal(self, signal_id: str, reason: str = "Manual rejection") -> bool:
        """
        Reject a pending signal
        
        Args:
            signal_id: Signal ID to reject
            reason: Rejection reason
            
        Returns:
            True if rejected, False if not found
        """
        pending = self._pending_signals.get(signal_id)
        
        if not pending:
            logger.warning(f"Signal {signal_id[:8]}... not found in queue")
            return False
        
        pending.is_rejected = True
        logger.info(f"❌ Signal {signal_id[:8]}... rejected: {reason}")
        
        # Remove from queue
        del self._pending_signals[signal_id]
        
        # Persist REJECTED status to database (fire-and-forget with error logging)
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                task = asyncio.ensure_future(
                    db_service.update_signal_status(signal_id, "REJECTED", rejection_reason=reason)
                )
                task.add_done_callback(
                    lambda t: logger.error(
                        f"Failed to persist REJECTED status for signal {signal_id[:8]}...: {t.exception()}"
                    ) if t.exception() else None
                )
        except (RuntimeError, asyncio.InvalidStateError) as e:
            logger.error(f"Failed to schedule DB status update for rejected signal {signal_id[:8]}...: {e}")
        
        return True
    
    def get_all_pending(self) -> list[PendingSignal]:
        """Get all pending signals"""
        return list(self._pending_signals.values())
    
    def get_pending_count(self) -> int:
        """Get count of pending signals"""
        return len(self._pending_signals)
    
    async def _timeout_monitor(self):
        """
        Background task that monitors for timed-out signals
        Runs independently from message processing
        """
        logger.info("⏰ Timeout monitor started")
        
        while self._running:
            try:
                # Check for expired signals
                expired_signals = []
                
                for signal_id, pending in list(self._pending_signals.items()):
                    if pending.check_timeout():
                        expired_signals.append((signal_id, pending))
                
                # Handle expired signals
                for signal_id, pending in expired_signals:
                    logger.warning(f"⏰ TIMEOUT: Signal {signal_id[:8]}... expired after {settings.approval_timeout_minutes} minutes without approval")
                    logger.info(f"   Symbol: {pending.signal.symbol}")
                    logger.info(f"   Action: {getattr(pending.signal, 'action', 'N/A')}")
                    logger.info(f"   Entry: {pending.signal.entry_price or 'Market'}")
                    
                    # Import here to avoid circular import
                    from src.integrations.telegram.unified_sender import notification_sender
                    
                    # Notify about timeout
                    await notification_sender.notify_approval_timeout(
                        pending.signal,
                        pending.risk_assessment
                    )
                    
                    # Persist EXPIRED status to database
                    try:
                        await db_service.update_signal_status(
                            signal_id,
                            "EXPIRED",
                            rejection_reason=f"Approval timed out after {settings.approval_timeout_minutes} minutes"
                        )
                        logger.info(f"📝 Signal {signal_id[:8]}... marked as EXPIRED in database")
                    except Exception as db_err:
                        logger.error(f"Failed to persist EXPIRED status for signal {signal_id[:8]}...: {db_err}")
                    
                    # Remove from queue
                    del self._pending_signals[signal_id]
                
                # Sleep for 10 seconds before next check
                await asyncio.sleep(10)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in timeout monitor: {e}")
                await asyncio.sleep(10)
        
        logger.info("⏰ Timeout monitor stopped")


# Singleton instance
approval_queue = ApprovalQueue()


# ── Brain Action Queue ────────────────────────────────────────────────────────

import uuid
from dataclasses import dataclass
from typing import Callable, Coroutine


@dataclass
class PendingBrainAction:
    """A brain position action waiting for user approval."""
    action_id: str
    symbol: str
    action: str           # MODIFY_SL, MODIFY_TP, PARTIAL_CLOSE, CLOSE
    reason: str
    value: Optional[float]
    percentage: Optional[float]
    execute_fn: Callable[[], Coroutine]   # async callable that performs the action
    created_at: datetime
    timeout_at: datetime
    decision_id: Optional[str] = None    # AIDecision record ID for outcome tracking

    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) >= self.timeout_at

    def get_remaining_seconds(self) -> int:
        remaining = (self.timeout_at - datetime.now(timezone.utc)).total_seconds()
        return max(0, int(remaining))


class BrainActionQueue:
    """Stores brain position-management decisions pending user approval."""

    def __init__(self):
        self._pending: Dict[str, PendingBrainAction] = {}
        self._timeout_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        if self._running:
            return
        self._running = True
        self._timeout_task = asyncio.create_task(self._timeout_monitor())
        logger.info("✅ Brain action queue started")

    async def stop(self):
        self._running = False
        if self._timeout_task:
            self._timeout_task.cancel()
            try:
                await self._timeout_task
            except asyncio.CancelledError:
                pass

    def add(
        self,
        symbol: str,
        action: str,
        reason: str,
        execute_fn: Callable[[], Coroutine],
        value: Optional[float] = None,
        percentage: Optional[float] = None,
        timeout_minutes: int = 5,
        decision_id: Optional[str] = None,
    ) -> str:
        action_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        self._pending[action_id] = PendingBrainAction(
            action_id=action_id,
            symbol=symbol,
            action=action,
            reason=reason,
            value=value,
            percentage=percentage,
            execute_fn=execute_fn,
            created_at=now,
            timeout_at=now + timedelta(minutes=timeout_minutes),
            decision_id=decision_id,
        )
        logger.info(f"🧠 Brain action queued for approval: {action} {symbol} [{action_id[:8]}]")
        return action_id

    def get(self, action_id: str) -> Optional[PendingBrainAction]:
        return self._pending.get(action_id)

    def remove(self, action_id: str):
        self._pending.pop(action_id, None)

    async def execute(self, action_id: str) -> bool:
        """Approve and execute a pending brain action. Returns True on success."""
        pending = self._pending.pop(action_id, None)
        if not pending:
            logger.warning(f"Brain action {action_id[:8]} not found in queue")
            return False
        if pending.is_expired():
            logger.warning(f"Brain action {action_id[:8]} has expired")
            return False
        try:
            await pending.execute_fn()
            if pending.decision_id:
                try:
                    await db_service.update_brain_decision(
                        pending.decision_id, outcome="APPROVED_EXECUTED"
                    )
                except Exception as _exc:
                    logger.debug(f"Suppressed exception: {_exc!r}")
            return True
        except Exception as e:
            logger.error(f"❌ Brain action execution failed: {e}")
            return False

    def reject(self, action_id: str) -> bool:
        """Reject (remove) a pending brain action."""
        if action_id in self._pending:
            pending = self._pending.pop(action_id)
            logger.info(f"🧠 Brain action rejected: {pending.action} {pending.symbol} [{action_id[:8]}]")
            if pending.decision_id:
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        spawn(
                            db_service.update_brain_decision(
                                pending.decision_id, outcome="REJECTED_BY_USER"
                            )
                        )
                except Exception as _exc:
                    logger.debug(f"Suppressed exception: {_exc!r}")
            return True
        return False

    async def _timeout_monitor(self):
        while self._running:
            try:
                expired = [pid for pid, p in list(self._pending.items()) if p.is_expired()]
                for action_id in expired:
                    pending = self._pending.pop(action_id, None)
                    if pending:
                        logger.warning(
                            f"⏰ Brain action timed out: {pending.action} {pending.symbol} [{action_id[:8]}]"
                        )
                        from src.integrations.telegram.unified_sender import notification_sender
                        await notification_sender.send_message(
                            f"⏰ <b>Brain action expired</b> ({pending.symbol})\n"
                            f"Action: {pending.action}\n"
                            f"Reason: {pending.reason}\n"
                            f"<i>No approval received — action skipped.</i>",
                            category='approval_outcome'
                        )
                        if pending.decision_id:
                            try:
                                await db_service.update_brain_decision(
                                    pending.decision_id, outcome="EXPIRED"
                                )
                            except Exception as _exc:
                                logger.debug(f"Suppressed exception: {_exc!r}")
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Brain action queue monitor error: {e}")
                await asyncio.sleep(10)


brain_action_queue = BrainActionQueue()
