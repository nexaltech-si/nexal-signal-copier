"""
Reply handling — reading what a channel message means for a running trade:
TP-hit announcements, status messages vs commands, and TP hits in the trade state.

Part of ReplyHandlerService (src/services/reply_handler_service.py); methods were moved here verbatim.
Module-level names are this module's own imports: to patch one in a test,
patch it here, not in reply_handler_service.py.
"""
from typing import Optional, Dict, List
from datetime import datetime, timezone, timedelta
import re
from loguru import logger
from src.integrations.trading.provider_factory import create_trading_provider
from src.services.magic_number_service import magic_number_service
from src.services.spread_adjustment_service import spread_adjustment_service
from src.core.database_service import db_service
from src.services.trade_context_manager import trade_context_manager
from src.services.channel_behavior_service import channel_behavior_service


class ReplyDetectionMixin:
    """TP-hit and status-message detection for replies."""

    def _detect_tp_hit_in_message(self, text: str) -> bool:
        """
        Detect if the message indicates a TP/target was hit.
        
        Args:
            text: Reply message text
            
        Returns:
            True if message indicates TP/target was hit
        """
        text_lower = text.lower().strip()
        
        # Patterns that indicate TP/target was hit
        tp_hit_patterns = [
            r'\btarget\s*\d*\s*:?\s*(hit|reached|done|achieved)',  # "Target 1: HIT", "Target hit"
            r'\btp\s*\d*\s*:?\s*(hit|reached|done|achieved)',  # "TP1: hit", "TP hit"
            r'\btp\s*\d+\s+(already\s+)?(hit|reached|done)',  # "TP1 already hit!", "TP2 hit"
            r'\btp\s*\d+\s+(check+|chek+)',  # "TP2 checkk!!", "TP1 check!" (typos)
            r'\b(hit|reached)\s+(tp|target)',  # "Hit TP1", "Reached target"
            r'\b(full\s+target|all\s+tp|final\s+tp)\s+(done|hit|reached)',  # "Full target done"
            r'\btp\d+\b.*\b(done|hit|dome)',  # "tp1 done", "tp1 dome" (typo)
            r'\+([\d]+)\s*pips?.*target.*hit',  # "+130 pips • Target 1: HIT"
            r'target.*✅',  # "Target 1: HIT ✅"
            r'tp.*✅',  # "TP1 ✅", "TP1✅ TP2✅✅"
            r'\btp\d+✅',  # "TP1✅"
            r'\b(first|second|third|1st|2nd|3rd)\s+(tp|takeprofit|take\s*profit|target).*\b(checked|reached|hit|done)',  # "First TakeProfit checked already"
            r'\btake\s+(some\s+)?(profit|partial)',  # "Take some profits", "Take profits", "Take partial"
            r'\bprofit(s)?\s+(secured|booked|taken|locked)',  # "Profits secured", "Profit taken"
            r'\b(lock|secure|book)\s+(in\s+)?(profit|partial)',  # "Lock in profits", "Secure profits"
            r'\babout\s+to\s+hit\s+(tp|target)',  # "TP2 about to hit"
            # Provider's trade is moving in profit while ours never filled
            r'\+?\b\d{2,4}\s*pips?\b',  # "80 pips", "+140 pips running"
            r'\bnear\s+(tp|target)',  # "Near TP"
            r'\bset\s+b\.?e\b|\bbreak\s*even\b|\brisk\s*free\b',  # provider moved to BE = trade advanced
            r'\bsave\s+(some\s+)?profits?',  # "Save some profits"
        ]
        
        for pattern in tp_hit_patterns:
            if re.search(pattern, text_lower):
                logger.debug(f"TP hit pattern matched: {pattern} in message: {text[:50]}")
                return True
        
        return False

    async def _ai_should_cancel_for_tp_hit(self, message: str, signal_id: str) -> bool:
        """
        Use AI to intelligently determine if a message indicates the signal provider's trade
        has already hit TP and pending orders should be cancelled.
        
        This is more accurate than pattern matching because it understands context.
        
        Args:
            message: The reply message from signal provider
            signal_id: The signal ID to check for context
            
        Returns:
            True if AI determines pending orders should be cancelled, False otherwise
        """
        if not self.ai_processor or not self.ai_processor.ai_available():
            # Fallback to pattern matching if AI not available
            logger.debug("AI not available, using pattern matching fallback for TP hit detection")
            return self._detect_tp_hit_in_message(message)
        
        try:
            # Get signal context for better AI decision
            signal_context = ""
            if signal_id:
                signal = await self.db.get_signal_by_id(signal_id)
                if signal:
                    signal_context = f"""
Signal Context:
- Symbol: {signal.get('symbol', 'N/A')}
- Entry: {signal.get('entryPrice', 'N/A')}
- Stop Loss: {signal.get('stopLoss', 'N/A')}
- Take Profit: {signal.get('takeProfit', 'N/A')}
- Signal Type: {signal.get('signalType', 'N/A')}
"""
            
            system_prompt = """You are an intelligent trading assistant analyzing messages from signal providers.

CRITICAL CONTEXT:
The user has PENDING ORDERS that were never triggered. The signal provider's trade already executed and may have hit targets.
Your job: Determine if the provider's message indicates their trade is done/profitable and user's pending orders should be cancelled.

WHY THIS MATTERS:
If the provider says "TP1 already hit!" or "TP2 checkk!!" - it means THEIR trade hit the target, but the user's pending orders 
never triggered (price didn't reach user's entry). The trade opportunity is OVER. Keeping pending orders active would enter 
a stale trade that already played out.

EXAMPLES REQUIRING CANCELLATION (Answer: YES):

1. "TP1 already hit!💪🏽" → YES (Provider's TP1 hit, trade is running, user missed entry)
2. "TP2 checkk!!" → YES (Provider's TP2 hit, trade is advanced, user still has pending orders)
3. "TP1✅ TP2✅✅" → YES (Multiple TPs hit, trade is done)
4. "First TakeProfit checked already" → YES (TP1 done, trade is running)
5. "TP2 about to hit, once we hit Tp2 set breakeven for zero risk ok!" → YES (TP2 imminent/hit, trade running)
6. "+150 pips secured!" → YES (Provider has profits, user never entered)
7. "All targets done 🎯" → YES (Trade complete)
8. "Running +200 pips, lock profits" → YES (Trade is profitable, user missed entry)
9. "Take some profits now" → YES (Provider taking profits, implies trade is profitable)
10. "Breakeven is set for zero risk!" → YES (Provider moved SL to BE after profits, trade is advanced)

EXAMPLES NOT REQUIRING CANCELLATION (Answer: NO):

1. "Entry triggered" → NO (Just entered, not at TP yet)
2. "Price approaching entry zone" → NO (Trade hasn't started)
3. "SL moved to 4538" → NO (Just managing SL, not about TP)
4. "Be ready to follow instructions!" → NO (Just a reminder)
5. "Floating in drawdown" → NO (Trade is losing, not at TP)
6. "What a volume🫣" → NO (Just commentary)
7. "Send us uppp now!🙏🏽🙏🏽🚀" → NO (Hoping for movement, not reporting TP)

KEY REASONING:
- If provider mentions TP/Target + (hit/done/check/reached/already/✅) → Trade is done → Cancel pending orders
- If provider mentions profits/pips secured → Their trade is profitable → Cancel pending orders  
- If provider mentions breakeven after TPs → Trade is advanced → Cancel pending orders
- If just commentary/hope/SL adjustments → Keep pending orders

BE INTELLIGENT: Understand context, intent, and trading flow. Don't just match keywords.
Consider: Is the provider reporting success/completion, or just managing an ongoing trade?

Respond with ONLY "YES" (cancel pending orders) or "NO" (keep pending orders)."""

            user_message = f"""Message from signal provider: "{message}"

{signal_context}

Should the user's pending orders be cancelled because the signal provider's trade has already hit TP?
Respond with YES or NO only."""

            content = await self.ai_processor.complete_text(
                system_prompt, user_message, caller='tp_detection', max_output_tokens=5
            )
            content = content.strip().upper().rstrip('.')
            
            if content == "YES":
                logger.info("🤖 AI DECISION: YES - Cancel pending orders")
                logger.info("   Reason: Provider's trade hit TP/is profitable")
                logger.info(f"   Message: '{message[:80]}...'")
                return True
            elif content == "NO":
                logger.info("🤖 AI DECISION: NO - Keep pending orders")
                logger.info("   Reason: Trade not complete or just commentary")
                logger.info(f"   Message: '{message[:80]}...'")
                return False
            else:
                # Fallback to pattern matching if AI response is unclear
                logger.warning(f"⚠️ AI returned unclear response: '{content}'")
                logger.warning("   Falling back to pattern matching (less intelligent)")
                return self._detect_tp_hit_in_message(message)
            
        except Exception as e:
            logger.error(f"❌ AI TP hit detection failed: {e}, falling back to pattern matching")
            return self._detect_tp_hit_in_message(message)

    def _is_status_message(self, text: str) -> bool:
        """
        Detect informal status messages that are NOT trading commands.
        These include performance updates, commentary, and celebratory messages.
        
        Args:
            text: Reply message text
            
        Returns:
            True if this is a status message (not a command)
        """
        text_lower = text.lower().strip()
        
        # First check: If message starts with or contains command keywords as whole words, it's NOT a status message
        # Use word boundaries to avoid matching "moved" when looking for "move"
        command_patterns = [
            r'\b(close|cancel|modify|add|exit|scale)\b',  # Must be whole words
            r'(move\s+sl|move\s+tp|move\s+the\s+sl|move\s+the\s+tp)',  # Move SL/TP anywhere in message
            r'(set\s+sl|set\s+tp|set\s+be|set\s+breakeven)',  # Set commands
            r'(sl\s+to\s+entry|sl\s+to\s+be|breakeven|break\s+even)',  # Breakeven commands
            r'^(set\s+|lock\s+)',  # At start with specific context
        ]
        for pattern in command_patterns:
            if re.search(pattern, text_lower):
                return False
        
        # Common status message patterns
        status_patterns = [
            # Performance updates (only if not a command)
            r'\d+\+?\s*pips?',  # "300+ pips", "50 pips running"
            r'\d+\s*pips?\s+(running|profit|gain|hit)',  # "50 pips running"
            r'running\s+\d+',  # "running 100 pips"
            
            # Target/TP hit messages
            r'^hit\s+(tp|sl|target)',  # "Hit TP1"
            r'^(tp|target)\s*(\d+)?\s*(hit|done|reached)',  # "TP1 hit", "Target done"
            r'(full\s+target|all\s+tp|final\s+tp)\s+(done|hit|reached)',  # "Full target done"
            r'\btp\d+\b.*\b(done|hit|dome)',  # "tp1 done", "tp1 dome" (typo)
            
            # Commentary patterns
            r'^(price|market)\s+(moved|is|going|heading)',  # "Price moved..."
            r'without\s+tapping',  # "without tapping our zone"
            r'^(great|good|nice|beautiful|amazing|perfect)',  # Positive commentary
            r'^(looking|seems|appears)\s+(good|great|nice)',  # "Looking good"
            r'^well\s+done',  # "Well done"
            r'(entry|limit).*didn.*trigger',  # "Entry didn't trigger"
            r'captured\s+(this|the)\s+move',  # "Captured this move"
            r'(risky|risk)\s+(trade|entry)',  # "Risky trade"
            r'i\s+take.*risk',  # "I take X% risk"
            r'manual\s+entry',  # "Manual entry"
            r'(too|very)\s+fast',  # "Too fast"
        ]
        
        # Check against patterns
        for pattern in status_patterns:
            if re.search(pattern, text_lower):
                return True
        
        # Check for emoji-only or emoji-heavy messages
        # Remove all alphanumeric characters and whitespace
        text_no_alnum = re.sub(r'[a-zA-Z0-9\s]', '', text).strip()
        # If what's left is mostly/only emojis/symbols and original text is short
        if len(text_no_alnum) >= len(text) * 0.7 and len(text) < 30:
            return True
        
        # Check for very short messages (likely not commands)
        # Commands typically have more structure
        text_no_emoji = re.sub(r'[^a-zA-Z0-9\s]', '', text).strip()
        if len(text_no_emoji) < 5 and len(text_no_emoji) > 0:
            # Short text like "ok", "yes", "nice" - likely status
            return True
        
        return False

    async def _check_tp_hits(self, signal_id: str) -> bool:
        """
        Check if any TP has been hit for trades belonging to this signal
        
        Args:
            signal_id: The signal ID to check
            
        Returns:
            True if any TP has been hit, False otherwise
        """
        try:
            # Get all trades for this signal
            trades = await self.db.db.trade.find_many(
                where={"signalId": signal_id}
            )
            
            if not trades:
                return False
            
            # Check trade actions for TP hits
            for trade in trades:
                # Look for CLOSE actions where TP was hit
                # The position_monitor logs closure reason in the details field
                close_actions = await self.db.db.tradeaction.find_many(
                    where={
                        "tradeId": trade.id,
                        "actionType": "CLOSE",
                        "success": True
                    }
                )
                
                for action in close_actions:
                    details = action.details or ""
                    if "TP hit" in details or "tp hit" in details.lower():
                        logger.info(f"✅ Found TP hit for trade {trade.id[:8]} - details: {details}")
                        return True
                
                # Also check for AUTO_TP actions (when TP is automatically set)
                # This is a secondary check for completeness
                tp_actions = await self.db.db.tradeaction.find_many(
                    where={
                        "tradeId": trade.id,
                        "actionType": "AUTO_TP",
                        "success": True
                    }
                )
                
                if tp_actions and len(tp_actions) > 0:
                    logger.info(f"✅ Found {len(tp_actions)} AUTO_TP action(s) for trade {trade.id[:8]}")
                    # Note: AUTO_TP means TP was set, not necessarily hit
                    # Continue checking other trades for actual TP hits
            
            return False
            
        except Exception as e:
            logger.error(f"❌ Error checking TP hits: {e}")
            return False
