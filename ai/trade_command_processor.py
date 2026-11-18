"""
AI-Powered Trade Command Processor
Handles natural language trade management commands with AI + Pattern matching hybrid
"""
import json
import re
from ai.message_guards import has_breakeven_wording, bare_tp_level, offers_partial_profit
import asyncio
from typing import Optional, Dict
from loguru import logger

from .base_processor import BaseAIProcessor


# Returned by _try_ai_processing when the AI answered and chose no action — distinct
# from None, which means the AI could not be reached or its reply was unparseable.
_AI_NO_ACTION = object()


class TradeCommand:
    """Parsed trade command"""
    
    def __init__(
        self,
        action: str,
        target: Optional[str] = None,
        value: Optional[float] = None,
        percentage: Optional[float] = None,
        position_filter: Optional[str] = None,
        parameters: Optional[Dict] = None
    ):
        self.action = action  # close, partial_close, modify_sl, modify_tp, breakeven, lock_profit, add_position, cancel_orders, close_worst, close_best, close_by_loss_threshold, close_by_symbol, close_by_time
        self.target = target  # all, symbol, position_id, worst, best, losing, winning
        self.value = value  # price value for SL/TP, lot size for add position, count for close_worst/best
        self.percentage = percentage  # for partial close
        self.position_filter = position_filter  # filter by symbol, magic number, etc
        self.parameters = parameters or {}  # additional params (pips, lots, count, selection_criteria)


class TradeCommandProcessor(BaseAIProcessor):
    """
    AI-powered processor for trade management commands
    Uses hybrid approach: AI first, pattern matching fallback
    """
    
    def __init__(self, config):
        super().__init__(config)
        
        # AI client — same provider chain as the signal processor
        # (PRIMARY_AI_PROVIDER + FALLBACK_AI_PROVIDERS). A hand-rolled per-provider
        # switch here used to leave the client as None whenever the primary
        # provider had no key, silently dropping every reply to pattern matching.
        from ai.llm_client import first_available_provider, build_llm_client_for, get_model_for
        self.config = config
        self.client = None
        self.provider = first_available_provider(config, vision=False)
        if self.provider is not None:
            self.client = build_llm_client_for(config, self.provider)
            self.ai_model = get_model_for(config, self.provider, vision=False)
            logger.info(f"TradeCommandProcessor: {self.provider} initialized ({self.ai_model})")
        else:
            logger.error("❌ TradeCommandProcessor: no AI provider has an API key — replies fall back to pattern matching")

        if not hasattr(self, 'ai_model'):
            self.ai_model = getattr(config, 'openai_model', 'gpt-4o-mini')
        
        self.temperature = 0.1
    
    async def process_message(self, message: str) -> Optional[TradeCommand]:
        """Not used - use process_command instead"""
        return await self.process_command(message)
    
    async def process_command(self, command: str, symbol_context: Optional[str] = None, thread_context: Optional[str] = None) -> Optional[TradeCommand]:
        """
        Process a trade management command.

        Args:
            command: Natural language command (e.g., "close 50%", "move SL to breakeven")
            symbol_context: Optional symbol context from original signal
            thread_context: Optional previous replies in this signal thread (chronological),
                            lets the AI understand context like "1R done" before "can BE now"
        Returns:
            TradeCommand object or None
        """
        logger.info(f"Processing trade command: '{command[:100]}'")

        # "Tp1 : 3858" — nothing but a take-profit level: the channel moves that target
        # of its running trade. The AI read it as a remark and left the old TP in place.
        tp_level = bare_tp_level(command)
        if tp_level:
            index, price = tp_level
            logger.info(f"Take-profit level message: TP{index or ''} → {price}")
            return TradeCommand(action='modify_tp', value=price,
                                parameters={'tp_index': index} if index else None)

        # "Can booked some" — take half off. A position at the minimum lot cannot be
        # split and is left exactly as it is (owner's rule, 2026-11-17).
        if offers_partial_profit(command):
            logger.info("Partial-profit offer: closing 50% where a position can be split")
            return TradeCommand(action='partial_close', percentage=50.0, parameters={'min_lot': 'leave'})

        # Try AI processing first. The AI's decision is final — including "no action".
        # Pattern matching only runs when the AI could not answer at all; it used to
        # also run after a deliberate "no action" and close everything on any
        # message containing "close" ("Hold, don't close yet").
        ai_command = await self._try_ai_processing(command, symbol_context, thread_context)
        if ai_command is _AI_NO_ACTION:
            logger.info("AI decided: no action (status/commentary)")
            return None
        if ai_command:
            logger.info(f"AI parsed command: {ai_command.action}")
            return ai_command

        # Fallback to pattern matching
        logger.warning("AI unavailable or unparseable — falling back to pattern matching")
        pattern_command = await self._try_pattern_matching(command, symbol_context)

        if pattern_command:
            logger.info(f"Pattern parsed command: {pattern_command.action}")
            return pattern_command

        logger.debug(f"Message is not a recognized command (likely status/info message): {command[:100]}")
        return None
    
    def ai_available(self) -> bool:
        """Checked per call: DB-stored keys load after this processor is constructed at import time."""
        from ai.llm_client import first_available_provider
        return first_available_provider(self.config, vision=False) is not None

    async def complete_text(self, system_prompt: str, user_message: str, caller: str, max_output_tokens: int = 400) -> str:
        """One chat completion through the shared provider chain (with fallback), off the event loop."""
        from ai.llm_client import complete_with_fallback, provider_chain, extract_content, max_tokens_for

        def _call(client, model, provider):
            return client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=self.temperature,
                timeout=30.0,
                max_tokens=max_tokens_for(self.config, provider, output_tokens=max_output_tokens),
            )

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: complete_with_fallback(
                self.config,
                provider_chain(self.config),
                _call,
                validate=lambda r: bool(extract_content(r).strip()),
                caller=caller,
            ),
        )
        return extract_content(response)

    async def _try_ai_processing(self, command: str, symbol_context: Optional[str] = None, thread_context: Optional[str] = None) -> Optional[TradeCommand]:
        """Try AI processing"""
        if not self.ai_available():
            logger.error("❌ No AI provider has an API key — reply parsed by pattern matching only")
            return None

        try:
            system_prompt = self._get_command_system_prompt()
            user_message = f"Command: {command}"
            if symbol_context:
                user_message += f"\nSymbol Context: {symbol_context}"
            if thread_context:
                user_message += f"\n\n{thread_context}"

            content = await self.complete_text(system_prompt, user_message, caller='trade_command')
            return self._parse_ai_response(content)
            
        except Exception as e:
            from ai.api_error_handler import log_api_error
            log_api_error(e, "TradeCommand/AI", logger)
            return None
    
    async def _try_pattern_matching(self, command: str, symbol_context: Optional[str] = None) -> Optional[TradeCommand]:
        """Pattern matching fallback"""
        cmd_upper = command.upper()
        cmd_lower = command.lower()
        
        # 0. EARLY DETECTION: Common informational messages (not commands)
        # These are status updates from signal providers, not user commands
        # BUT: Check for action verbs first - if present, it's a command even with status info
        has_action_verb = any(verb in cmd_lower for verb in [
            'close', 'exit', 'move', 'modify', 'change', 'update', 'adjust', 
            'cancel', 'set', 'lock', 'reduce', 'cut', 'take', 'bank', 'secure'
        ])
        
        if not has_action_verb:
            informational_patterns = [
                r'missed\s+by\s+\d+\s+pips?',  # "MISSED By 15 pips"
                r'tp\d*\s+hit',  # "TP1 hit", "TP hit"
                r'target\s+\d+\s*:?\s*hit',  # "Target 1: HIT"
                r'^\s*done\s*$',  # Just "Done" alone
                r'^\s*✓\s*done\s*$',  # "✓ Done"
                r'\b\d+\.?\d*r\s+done\b',  # "1R done", "1.5R done" — profit milestone
                r'\b(tp\d*|target\s*\d+)\s+done\b',  # "TP1 done", "target 2 done"
                r'\btrade\s+(completed|finished|done)\b',  # "trade completed"
                r'running\s+[\+\-]?\d+\s+pips?',  # "running +50 pips"
                r'we\s+have\s+[\+\-]?\d+\s+pips',  # "we have +90 pips" (without action verb)
                r'^\s*no\s+action\s*$',  # "No Action"
            ]
            
            for pattern in informational_patterns:
                if re.search(pattern, cmd_lower):
                    logger.debug(f"Detected informational message pattern: {pattern}")
                    return None
        
        # 0b. BREAKEVEN EARLY CHECK — must run before close_keywords because 'DONE' is in
        # close_keywords and messages like "1R done risky buyers can BE now" would be
        # misinterpreted as close. "BE" as a standalone word in trading = breakeven.
        if has_breakeven_wording(command):
            return TradeCommand(action='breakeven')

        # 1. CLOSE COMMANDS - Comprehensive pattern matching for all close variations

        # 1a. REDUCE RISK - Special pattern for risk reduction commands
        if 'reduce' in cmd_lower and 'risk' in cmd_lower:
            logger.info("Detected 'reduce risk' command - closing worst positions")
            return TradeCommand(
                action='close_worst',
                target='worst',
                value=None,
                parameters={'selection': 'worst', 'count': None}
            )
        
        # 1b. SELECTIVE CLOSE - Close worst/best/losing/winning entries
        if any(x in cmd_lower for x in ['worst', 'bad', 'losing', 'negative', 'drawdown']) or re.search(r'\bred\b', cmd_lower):
            if any(y in cmd_lower for y in ['close', 'exit', 'cut', 'reduce', 'get out']):
                # Extract count if specified
                count_match = re.search(r'(\d+)\s*(?:entries|positions|trades|worst|best)', cmd_lower)
                count = int(count_match.group(1)) if count_match else None
                
                return TradeCommand(
                    action='close_worst',
                    target='worst',
                    value=count,
                    parameters={'selection': 'worst', 'count': count}
                )
        
        # 1c. CLOSE BY LOSS THRESHOLD - Close positions exceeding X% loss
        loss_threshold_patterns = [
            r'close\s+(?:all\s+)?positions?\s*(?:losing|exceeding)\s+more\s+than\s+(\d+(?:\.\d+)?)\s*%',
            r'close\s+(?:all\s+)?positions?\s+with\s+(\d+(?:\.\d+)?)\s*%\s+loss',
            r'cut\s+(?:all\s+)?positions?\s+(?:losing|exceeding)\s+(\d+(?:\.\d+)?)\s*%',
            r'close\s+positions?\s+exceeding\s+(\d+(?:\.\d+)?)\s*%\s+loss',
        ]
        
        for pattern in loss_threshold_patterns:
            match = re.search(pattern, cmd_lower)
            if match:
                threshold = float(match.group(1))
                logger.info(f"Detected loss threshold command: {threshold}%")
                return TradeCommand(
                    action='close_by_loss_threshold',
                    value=threshold,
                    parameters={'threshold': threshold}
                )
        
        # 1d. CLOSE BY SYMBOL - Close all positions for a specific symbol
        # Common forex/crypto symbols
        symbol_patterns = [
            r'close\s+(?:all\s+)?(?:positions?|trades?)\s+for\s+([A-Z]{3,6})',
            r'close\s+(?:all\s+)?([A-Z]{3,6})\s+(?:positions?|trades?)',
            r'exit\s+(?:all\s+)?(?:positions?|trades?)\s+for\s+([A-Z]{3,6})',
            r'exit\s+(?:all\s+)?([A-Z]{3,6})\s+(?:positions?|trades?)',
        ]
        
        for pattern in symbol_patterns:
            match = re.search(pattern, cmd_upper)
            if match:
                symbol = match.group(1)
                logger.info(f"Detected symbol close command: {symbol}")
                return TradeCommand(
                    action='close_by_symbol',
                    target=symbol,
                    parameters={'symbol': symbol}
                )
        
        # 1e. CLOSE BY TIME - Close positions older than X minutes
        time_patterns = [
            r'close\s+(?:all\s+)?positions?\s+older\s+than\s+(\d+)\s*(?:minutes?|mins?|hours?|hrs?)',
            r'close\s+(?:all\s+)?positions?\s+opened\s+(?:more\s+than\s+)?(\d+)\s*(?:minutes?|mins?|hours?|hrs?)\s+ago',
            r'exit\s+(?:all\s+)?positions?\s+older\s+than\s+(\d+)\s*(?:minutes?|mins?|hours?|hrs?)',
            r'exit\s+(?:all\s+)?positions?\s+opened\s+(?:more\s+than\s+)?(\d+)\s*(?:minutes?|mins?|hours?|hrs?)\s+ago',
        ]
        
        for pattern in time_patterns:
            match = re.search(pattern, cmd_lower)
            if match:
                time_value = int(match.group(1))
                time_unit = match.group(2) if len(match.groups()) > 1 else 'minutes'
                
                # Convert to minutes
                if 'hour' in time_unit.lower() or 'hr' in time_unit.lower():
                    minutes = time_value * 60
                else:
                    minutes = time_value
                
                logger.info(f"Detected time-based close command: {minutes} minutes")
                return TradeCommand(
                    action='close_by_time',
                    value=minutes,
                    parameters={'minutes': minutes}
                )
        
        if any(x in cmd_lower for x in ['best', 'winning', 'profit', 'green']) or re.search(r'\btop\b', cmd_lower):
            if any(y in cmd_lower for y in ['close', 'exit', 'take', 'bank', 'secure']):
                count_match = re.search(r'(\d+)\s*(?:entries|positions|trades|worst|best)', cmd_lower)
                count = int(count_match.group(1)) if count_match else None
                
                return TradeCommand(
                    action='close_best',
                    target='best',
                    value=count,
                    parameters={'selection': 'best', 'count': count}
                )
        
        # 1b. CLOSE ALL
        if any(x in cmd_upper for x in ['CLOSE ALL', 'EXIT ALL', 'CLOSE EVERYTHING', 'EXIT EVERYTHING', 'GET OUT ALL', 'LEAVE ALL', 'STOP ALL', 'END ALL']):
            return TradeCommand(action='close_all')
        
        # All unambiguous close/exit commands.
        # INTENTIONALLY EXCLUDED (too context-dependent — let AI handle them):
        #   DONE, FINISHED, COMPLETED, OVER, ENOUGH, THAT'S IT, NO MORE
        #   Reason: "1R done", "TP done", "trade completed TP2" are milestone STATUS
        #   messages, not close commands. Pattern matching has no context to tell them
        #   apart. These are handled correctly by the AI when thread context is available.
        close_keywords = [
            'CLOSE', 'EXIT', 'GET OUT', 'LEAVE', 'STOP', 'END', 'FINISH', 'TERMINATE',
            'CUT', 'CASH OUT', 'LIQUIDATE', 'SQUARE OFF', 'FLATTEN', 'OUT',
            'TAKE PROFIT', 'BANK PROFIT', 'SECURE PROFIT', 'LOCK IN PROFIT',
            'BOOK PROFIT', 'REALIZE PROFIT', 'TAKE PROFITS', 'BANK PROFITS',
            'SECURE PROFITS', 'LOCK PROFITS', 'BOOK PROFITS', 'REALIZE PROFITS',
            'GET ME OUT', 'PULL OUT', 'PULL THE PLUG', 'BAIL OUT', 'WRAP IT UP',
            'CALL IT A DAY', 'CALL IT QUITS', 'I\'M DONE', 'WE\'RE DONE',
            'THAT\'S ENOUGH', 'HAD ENOUGH', 'STOP LOSS', 'HIT SL', 'STOPPED OUT',
            'STOP OUT', 'SL HIT', 'CLS', 'EXIT NOW', 'CLOSE NOW', 'EXIT TRADE',
            'CLOSE TRADE', 'KILL IT', 'KILL TRADE', 'SCRATCH', 'SCRATCH IT',
            'FLAT', 'GO FLAT', 'BE FLAT'
        ]
        
        # 1c. LEG-SCOPED CLOSE — "close 4020 hold 4030".
        # MUST precede the generic close_keywords check below, which would otherwise
        # collapse a leg-scoped instruction into a full close of every entry.
        leg_close = re.search(
            r'\bclose\s+(?:the\s+)?(\d+(?:\.\d+)?)\b(?!\s*%)', cmd_lower
        )
        if leg_close and not re.search(r'\b(?:if|when|once|after)\b[^.]*\bclose[sd]\b', cmd_lower):
            return TradeCommand(
                action='close_by_entry',
                value=float(leg_close.group(1)),
                position_filter=symbol_context,
            )

        if any(x in cmd_upper for x in close_keywords):
            # Check for percentage
            percentage = self._extract_percentage(command)
            if percentage:
                return TradeCommand(
                    action='partial_close',
                    percentage=percentage,
                    position_filter=symbol_context
                )
            
            # Check for half
            if 'HALF' in cmd_upper:
                return TradeCommand(
                    action='partial_close',
                    percentage=50.0,
                    position_filter=symbol_context
                )
            
            # Full close
            return TradeCommand(action='close', position_filter=symbol_context)
        
        # 2. STOP LOSS MODIFICATIONS
        if any(x in cmd_lower for x in ['move sl', 'modify sl', 'change sl', 'update sl', 'sl to', 'sl at', 'new sl']):
            # Check for breakeven
            if has_breakeven_wording(command) or re.search(r'\bentry\b', cmd_lower):
                return TradeCommand(action='breakeven')
            
            # Check for lock profit (+X pips)
            lock_match = re.search(r'[\+](\d+)\s*pips?', cmd_lower)
            if lock_match:
                pips = float(lock_match.group(1))
                return TradeCommand(
                    action='lock_profit',
                    value=pips,
                    parameters={'unit': 'pips'}
                )
            
            # Extract price
            price = self._extract_price(command)
            if price:
                return TradeCommand(
                    action='modify_sl',
                    value=price
                )
            
            # If no price found, default to breakeven
            # This handles cases like "xauusd move sl" without explicit BE mention
            logger.info("No SL price found, defaulting to breakeven")
            return TradeCommand(action='breakeven')
        
        # 3. TAKE PROFIT MODIFICATIONS
        if any(x in cmd_lower for x in ['move tp', 'modify tp', 'change tp', 'update tp', 'tp to', 'tp at', 'new tp']):
            price = self._extract_price(command)
            if price:
                return TradeCommand(
                    action='modify_tp',
                    value=price
                )
        
        # 4. BREAKEVEN
        if has_breakeven_wording(command):
            return TradeCommand(action='breakeven')
        
        # 5. LOCK PROFIT
        if 'lock' in cmd_lower and 'profit' in cmd_lower:
            # Extract pips
            pips_match = re.search(r'(\d+)\s*pips?', cmd_lower)
            if pips_match:
                pips = float(pips_match.group(1))
                return TradeCommand(
                    action='lock_profit',
                    value=pips,
                    parameters={'unit': 'pips'}
                )
        
        # 6. CANCEL ORDERS
        # Explicit cancel commands
        if any(x in cmd_lower for x in ['cancel', 'delete']) and any(y in cmd_lower for y in ['order', 'pending']):
            return TradeCommand(action='cancel_orders')
        
        # "Pending position" commands - user has pending orders they want closed
        if any(x in cmd_lower for x in ['pending position', 'have pending', 'pending order', 'outstanding order']):
            logger.info("Detected 'pending position' mention - interpreting as cancel pending orders")
            return TradeCommand(action='cancel_orders')
        
        # Advisory "do not enter" commands (implies cancel pending orders)
        if any(x in cmd_lower for x in ['do not enter', "don't enter", 'dont enter', 'skip', 'avoid', 'not taking', 'dont take']):
            if any(y in cmd_lower for y in ['trade', 'setup', 'signal', 'entry', 'position']):
                logger.info("Detected 'do not enter' advisory - interpreting as cancel pending orders")
                return TradeCommand(action='cancel_orders')
        
        # "Invalid" commands - user saying trade/setup is invalid (cancel pending orders)
        if any(x in cmd_lower for x in ['invalid', 'not valid', 'wrong']):
            if any(y in cmd_lower for y in ['trade', 'setup', 'signal', 'entry', 'position']):
                logger.info("Detected 'invalid' response - interpreting as cancel pending orders")
                return TradeCommand(action='cancel_orders')
        
        # 7. ADD TO POSITION
        if any(x in cmd_lower for x in ['add to position', 'add position', 'scale in', 'pyramid']):
            # Extract lot size
            lots = self._extract_lot_size(command)
            return TradeCommand(
                action='add_position',
                value=lots,
                parameters={'lots': lots}
            )
        
        # 8. TRAILING STOP
        if 'trailing' in cmd_lower:
            # Extract distance
            pips_match = re.search(r'(\d+)\s*pips?', cmd_lower)
            if pips_match:
                pips = float(pips_match.group(1))
                return TradeCommand(
                    action='trailing_stop',
                    value=pips,
                    parameters={'distance_pips': pips}
                )
        
        return None
    
    def _get_command_system_prompt(self) -> str:
        """Get system prompt for command parsing"""
        return """You are a trade management command parser. Parse natural language trading commands into structured actions.

LANGUAGE: messages may be written in ANY language (Spanish, Portuguese, French, German, Italian, Russian, Turkish, Arabic, Persian, Hindi/Urdu in Latin letters, Indonesian, Vietnamese, Thai, Chinese, Japanese, Korean...) or mix several. Understand them by MEANING, e.g. compra/achat/kaufen/покупка/شراء/买入/買い/매수 = BUY; venta/vente/verkaufen/продажа/بيع/卖出/売り/매도 = SELL; stop/стоп/zarar durdur/وقف الخسارة/止损/損切り/손절 = stop loss; objetivo/alvo/ziel/тейк/هدف/止盈/利確/익절 = take profit. Copy every price EXACTLY as written, convert Arabic-Indic or Persian digits (٠١٢٣٤٥٦٧٨٩ / ۰۱۲۳۴۵۶۷۸۹) to ASCII digits, read a decimal comma as a decimal point when it is clearly a price (1,0850 = 1.0850) and as a thousands separator otherwise (2,300 = 2300). Never translate or alter numbers.

CHANNEL RULE (if provided):
"Channel rule set by the account owner" means the owner configured how THIS channel's messages are to be
handled and the current message matched it. It is the owner's explicit instruction and outranks your own
reading of the words:
- Return the action it names, with its parameters (e.g. "percentage": 50 → percentage: 50, "sl_price" →
  value, "pips" → value).
- Exceptions: if the LIVE ACCOUNT STATE makes the action impossible, follow the live-state guidance below
  (e.g. only pending orders → cancel_orders); if its "Only when" conditions are clearly not met by the live
  state, return action: null.
- "AI decides" rules carry no fixed action: use the owner's note as guidance for this channel.

THREAD CONTEXT (if provided):
When the user message includes "Previous messages in this signal thread:", treat those lines as historical context.
They tell you what already happened on this signal BEFORE the current command.
Use them to resolve ambiguous words like "done" — if prior messages show TP was hit, "done" is a status update, not a close command.

LIVE ACCOUNT STATE (if provided):
"Live account state for this signal" lists the follower's OPEN positions (filled, with P/L) and PENDING
orders (not yet filled). Decide using that state, not just the words:
- ONLY PENDING orders, NO open positions, and the provider says to take profit / save profits / close /
  set BE / lock profit, OR reports their trade is clearly in profit (+X pips, near TP, TP hit, running in
  profit) → action: cancel_orders. The entry was missed; a stale pending order would enter a trade that
  already played out. Never answer breakeven/partial_close/close_best when there is nothing open.
- OPEN positions and the provider says "set BE" / "B.E" / "risk free" / "SL to entry" → action: breakeven.
- OPEN positions and the provider says "save/secure/book some profits", "take partials" (+ optional
  "set BE") → action: partial_close, percentage: 50.
- OPEN positions and a pure progress report with no instruction ("80 pips", "Near TP", "Running!") →
  action: null — leave the trade running to its own TP/SL.
Examples:
- "• XAU +140 pips running now - Set B.E ~ Save some profits!" with open positions → partial_close, percentage: 50
- "• XAU +140 pips running now - Set B.E ~ Save some profits!" with only pending orders → cancel_orders
- "80 pips" with only pending orders → cancel_orders
- "80 pips" with open positions → null

Available Actions:
1. close_all - Close all positions
2. close - Close position(s) for specific symbol
3. partial_close - Close X% of position(s)
4. close_worst - Close worst performing positions (highest loss)
5. close_best - Close best performing positions (highest profit)
6. close_by_loss_threshold - Close positions exceeding X% loss threshold
7. close_by_symbol - Close all positions for a specific symbol
8. close_by_time - Close positions older than X minutes
8b. close_by_entry - Close ONLY the position filled at a specific entry price/level, leaving other legs open
9. modify_sl - Modify stop loss to specific price
10. modify_tp - Modify take profit to specific price
11. breakeven - Move SL to entry price
12. lock_profit - Move SL to lock profit (+X pips)
13. cancel_orders - Cancel pending orders
14. add_position - Add to existing position (scale in)
15. trailing_stop - Activate/modify trailing stop

COMMAND Examples (return action):
- "close" → action: close
- "close 50%" → action: partial_close, percentage: 50
- "close all" → action: close_all
- "close worst entries" → action: close_worst, target: worst
- "close the worst entries now to reduce the risk" → action: close_worst, target: worst
- "close worst 3 positions" → action: close_worst, target: worst, value: 3
- "close worst entry" (singular) → action: close_worst, target: worst, value: 1
- "close best entry" (singular) → action: close_best, target: best, value: 1
- "Cancel the 4130 order, keep the rest" → action: cancel_orders, value: 4130 (only that level)
- "Close 50% and move SL to entry" → action: partial_close, percentage: 50 (the BE part is applied after)
- "close losing positions" → action: close_worst, target: worst
- "close positions in drawdown" → action: close_worst, target: worst
- "reduce risk" → action: close_worst, target: worst
- "cut losses" → action: close_worst, target: worst
- "close positions losing more than 5%" → action: close_by_loss_threshold, value: 5
- "close all positions losing more than 3%" → action: close_by_loss_threshold, value: 3
- "cut positions with 10% loss" → action: close_by_loss_threshold, value: 10
- "close positions exceeding 7% loss" → action: close_by_loss_threshold, value: 7
- "close all XAUUSD positions" → action: close_by_symbol, target: XAUUSD
- "close EURUSD trades" → action: close_by_symbol, target: EURUSD
- "exit all GBPUSD positions" → action: close_by_symbol, target: GBPUSD
- "close positions older than 1 hour" → action: close_by_time, value: 60
- "Pls close 4020 hold 4030 play safe" → action: close_by_entry, value: 4020
- "close 4020" → action: close_by_entry, value: 4020
- "close the 4020 entry, keep 4030" → action: close_by_entry, value: 4020
- "close first entry only" → action: close_by_entry, target: first
CRITICAL — leg-scoped closes on multi-entry (scale-in) signals:
When a message names a SPECIFIC price level to close and/or names another level to
KEEP ("hold", "keep", "leave", "let run"), it is close_by_entry — NOT close/close_all.
Put the level to CLOSE in `value`. Never return close_all for such a message: closing
a level the trader explicitly said to hold is a serious, unrecoverable error.
Contrast: "close above 4020" / "if it closes 4020" are candle conditions, not commands.
- "close positions older than 30 minutes" → action: close_by_time, value: 30
- "exit positions opened more than 2 hours ago" → action: close_by_time, value: 120
- "close best entries" → action: close_best, target: best
- "close winning positions" → action: close_best, target: best
- "take profit on best 2 trades" → action: close_best, target: best, value: 2
- "exit" → action: close
- "get out" → action: close
- "leave" → action: close
- "stop" → action: close
- "end" → action: close
- "finish" → action: close
- "terminate" → action: close
- "cut" → action: close
- "cut losses" → action: close
- "cash out" → action: close
- "liquidate" → action: close
- "square off" → action: close
- "flatten" → action: close
- "close position" → action: close
- "exit position" → action: close
- "get out of position" → action: close
- "leave position" → action: close
- "stop position" → action: close
- "end position" → action: close
- "finish position" → action: close
- "terminate position" → action: close
- "cut position" → action: close
- "out" → action: close
- "done" → action: null  (ambiguous — could be profit milestone status; DO NOT close unless explicit close verb is also present or thread context confirms intent)
- "1R done" → action: null  (profit milestone status, NOT close)
- "TP1 done" → action: null  (status update, NOT close)
- "trade done" → action: null  (status — use thread context to decide; when in doubt, null)
- "finished" → action: null  (ambiguous — same rule as "done"; require explicit close verb)
- "completed" → action: null  (ambiguous — milestone status language)
- "over" → action: null  (ambiguous)
- "enough" → action: null  (ambiguous without context)
- "that's it" → action: close  (clear personal decision to exit)
- "no more" → action: close  (clear personal decision to exit)
- "sell" → action: close (if long position)
- "buy" → action: close (if short position)
- "take profit" → action: close
- "bank profit" → action: close
- "secure profit" → action: close
- "lock in profit" → action: close
- "book profit" → action: close
- "realize profit" → action: close
- "take profits" → action: close
- "bank profits" → action: close
- "secure profits" → action: close
- "lock profits" → action: close
- "book profits" → action: close
- "realize profits" → action: close
- "get me out" → action: close
- "pull out" → action: close
- "pull the plug" → action: close
- "bail out" → action: close
- "wrap it up" → action: close
- "call it a day" → action: close
- "call it quits" → action: close
- "I'm done" → action: close
- "we're done" → action: close
- "that's enough" → action: close
- "had enough" → action: close
- "stop loss" → action: close
- "hit sl" → action: close
- "stopped out" → action: close
- "stop out" → action: close
- "sl hit" → action: close
- "cls" → action: close (abbreviation)
- "x" → action: close (abbreviation)
- "exit now" → action: close
- "close now" → action: close
- "exit trade" → action: close
- "close trade" → action: close
- "kill it" → action: close
- "kill trade" → action: close
- "scratch" → action: close (breakeven exit)
- "scratch it" → action: close
- "flat" → action: close
- "go flat" → action: close
- "be flat" → action: close
- "move SL to 3850" → action: modify_sl, value: 3850
- "move SL" → action: breakeven (when no price specified, default to breakeven)
- "we have +70 pips move the sl to entry" → action: breakeven
- "move the sl to entry" → action: breakeven
- "xauusd move sl" → action: breakeven (no price = breakeven)
- "move SL to breakeven" → action: breakeven
- "set BE" → action: breakeven
- "can BE now" → action: breakeven (BE = breakeven abbreviation)
- "risky buyers can BE now" → action: breakeven
- "1R done risky buyers can BE now" → action: breakeven ("done" = profit achieved, "BE" = set breakeven)
- "lock profit at +20 pips" → action: lock_profit, value: 20
- "modify TP to 3900" → action: modify_tp, value: 3900
- "move TP1 to 3858" / "new TP2 3835 guys" → action: modify_tp, value: the price, parameters: {"tp_index": 1} (the
  number of the target named; omit tp_index when no target number is given — then every target moves)
- "cancel pending orders" → action: cancel_orders
- "do not enter" → action: cancel_orders (advisory to not enter = cancel pending)
- "don't enter this trade" → action: cancel_orders
- "skip this setup" → action: cancel_orders
- "avoid this signal" → action: cancel_orders
- "do not enter gold sell setup" → action: cancel_orders
- "add 0.5 lots" → action: add_position, value: 0.5
- "Re-enter sell 4125 SL 4145 TP 4100" → action: null (a NEW entry with its own levels is opened by the
  signal extractor with proper entry/SL/TP — never add_position at market)
- "Sell again from 4130, SL 4150" → action: null (same reason)
- "activate trailing stop 30 pips" → action: trailing_stop, value: 30

NON-COMMAND Examples (return action: null):
- "TP1 hit 🔥" → NOT a command (status update)
- "Target 1: HIT ✅" → NOT a command (status update)
- "GOLD (XAUUSD) 🟡 4801 • Target 1: HIT ✅ • Pips: +170 💰" → NOT a command (status update)
- "MISSED By 15 pips" → NOT a command (informational - trade didn't trigger)
- "✓ Done" → NOT a command (status confirmation)
- "No Action" → NOT a command (informational)
- "done" → NOT a command (standalone "done" is ambiguous; treat as status unless explicit close intent)
- "1R done" → NOT a command (profit milestone reached — status, not close)
- "2R done" → NOT a command (profit milestone — status)
- "TP1 done" → NOT a command (take profit milestone — status)
- "trade done" → NOT a command (status — use thread context if available)
- "1R done risky buyers can BE now" → action: breakeven (milestone + BE = set breakeven, "done" here is status context)
- "we have +90 pips move the Sl to Entry Ask for some profit, my friend. ✅" → NOT a command (suggestion/advice, not imperative)
- "we have now +220 pips✅✅✅ you can take some more profits" → NOT a command (suggestion)
- "running +50 pips" → NOT a command (performance update)
- "great trade everyone" → NOT a command (commentary)
- "hit target" → NOT a command (status update)
- "nice move" → NOT a command (commentary)
- "looking good" → NOT a command (commentary)
- "🔥🔥🔥" → NOT a command (emoji only)
- "Re-enter" → NOT a command (suggestion without specific entry details)
- "should we close?" → NOT a command (a QUESTION to followers is not an instruction — also not a cancel)
- "close? no way, hold" → NOT a command (negated)
- "dont exit yet hold tight" / "abhi hold karo, close mat karna" → NOT a command (explicit hold)
- "guys i think" (unfinished) → NOT a command

INVALID TRADE Examples (return action: cancel_orders):
- "invalid" → action: cancel_orders (user saying trade/setup is invalid)
- "invalid trade" → action: cancel_orders
- "trade invalid" → action: cancel_orders
- "invalid setup" → action: cancel_orders
- "wrong" → action: cancel_orders
- "wrong trade" → action: cancel_orders
- "not valid" → action: cancel_orders
- "this is invalid" → action: cancel_orders
- "setup invalid" → action: cancel_orders
- "Invald" → action: cancel_orders (misspelled, but intent is clear)

IMPORTANT:
- If command is "move sl" or "modify sl" without a specific price, default to action: breakeven
- If user says "do not enter", "don't enter", "skip", or "avoid" regarding a trade/setup/signal, interpret as action: cancel_orders
- If user says "invalid", "not valid", "wrong", or similar (including misspellings like "Invald"), interpret as action: cancel_orders
- If user INSTRUCTS followers to CLOSE/EXIT (close, exit, get out, leave it, cut, cash out, liquidate, square off, flatten, out, that's it, no more, take profit, bank profit, secure profit, lock in profit, book profit, realize profit, get me out, pull out, pull the plug, bail out, wrap it up, call it a day, call it quits, hit sl, stopped out, stop out, sl hit), interpret as action: close
- "done", "finished", "completed", "over", "enough" on their own are NOT close instructions (see the "done" rules below)

PAST-TENSE RESULTS / BRAG POSTS ARE NEVER COMMANDS (return action: null):
Signal providers constantly post recaps of what THEY already did. Past tense ("booked", "secured",
"closed", "smashed", "hit", "done") describes the provider's result — it is NOT an instruction to you.
Only an imperative addressed to followers ("book profits now", "close half", "set BE") is a command.
- "XAUUSD Target-Smacked +150 Pips Running, Deal Done - Profit Secured 🎯 THANKS GOLD!" → action: null
- "XAU bleeding +200 pips running! Timely booked maximum profits and secured the gains. TRADE SMART." → action: null
- "You Can't Beat Me in GOLD #back_to_back ✅ XAU SELL both entries +550 Pips running smashed tp-hit!" → action: null
- "100 pips already done🙌🏻" → action: null
- "1st target done. 4526 ✔️" → action: null
- "1:1 RR DONE 50+ pips" → action: null
- "+380 pips u better know what to do!" → action: null (hint, no explicit instruction)
- "I take entry in GOLD from 4395 when i was typing it move up in second. What about you ??" → action: null (chat)
- "GOLD will move up waiting pullback to execute our trades!" → action: null (market view, no instruction)
- "One entry placed, one still there" → action: null (status)
- Promotional / channel marketing text (join, DM me, free trial, giveaway, likes) → action: null
- "130 pips booked rest BE SET" → action: breakeven (the "BE SET" part IS an instruction)
- "Tp hit +460 pips close half set b.e" → action: partial_close (explicit "close half")
- "Close half or close all now. If hold set BE." → action: partial_close
EXCEPTION — the provider reporting a PARTIAL close of this trade names a fraction, so it is their trade
management for followers to mirror, not a recap: return action: partial_close with that percentage (half = 50).
- "Booked half" → action: partial_close, percentage: 50
- "Closed half here" / "Secured half" / "Took partials" → action: partial_close, percentage: 50
- "Booked 70%" → action: partial_close, percentage: 70
- "B.E" / "BE" alone → action: breakeven
A recap with no fraction ("booked profits", "100 pips booked") stays action: null.
When in doubt between a status report and a close, return action: null — closing a live position by mistake is unrecoverable.
- If user mentions "worst", "losing", "bad", "drawdown", "negative", "red" entries/positions with close/exit/reduce, interpret as action: close_worst
- If user mentions "best", "winning", "profit", "green", "top" entries/positions with close/exit/take, interpret as action: close_best
- "Reduce risk" or "reduce the risk" should be interpreted as action: close_worst (close worst performing positions)
- Look for ACTION VERBS (move, close, set, cancel, modify) - if missing, it's likely NOT a command
- Performance updates like "we have +X pips" are ONLY commands if followed by an action verb (move, set, close, etc.)
- Be forgiving of typos and misspellings - focus on INTENT (e.g., "Invald" = "invalid" = cancel orders)
- Abbreviations and slang should be recognized (e.g., "tp", "sl", "be", "out")
- "done" ALONE or as a milestone marker ("1R done", "TP1 done") is NOT a close command. Require a clear close verb ("close", "exit", "get out", "I'm done", "we're done") to return action: close.
- "BE" as a standalone uppercase word in trading messages ALWAYS means BREAKEVEN. If a message contains "BE now", "can BE", "buyers can BE", etc., it is ALWAYS action: breakeven — even if the message also contains "done". "done" here means a profit milestone was hit (status), not that the trade should be closed.
- "1R done" or "xR done" is a STATUS indicator (X units of risk in profit achieved). Combined with "BE", the command is breakeven, not close.
- USE THREAD CONTEXT: If "Previous messages in this signal thread" is provided, let it inform ambiguous words. For example, if previous messages show TP was hit, then "done" in the current message is a status confirmation, not a close command.

Respond ONLY with JSON:
{
    "action": "string",
    "target": "string or null (symbol for close_by_symbol, 'worst'/'best'/'first' selectors)",
    "value": number or null,
    "percentage": number or null,
    "position_filter": "string or null",
    "parameters": {"key": "value"} or null
}

If no valid command, return: {"action": null}
"""
    
    def _parse_ai_response(self, response: str) -> Optional[TradeCommand]:
        """Parse AI JSON response into TradeCommand"""
        try:
            from .utils import clean_json_response
            clean = clean_json_response(response)

            data = json.loads(clean)

            if not data.get('action'):
                return _AI_NO_ACTION

            return TradeCommand(
                action=data['action'],
                target=data.get('target'),
                value=data.get('value'),
                percentage=data.get('percentage'),
                position_filter=data.get('position_filter'),
                parameters=data.get('parameters')
            )
            
        except Exception as e:
            logger.error(f"Failed to parse AI response: {e}")
            return None
    
    def _extract_percentage(self, text: str) -> Optional[float]:
        """Extract percentage from text"""
        patterns = [
            r'(\d+)%',
            r'(\d+)\s*percent',
            r'(\d+\.?\d*)\s*%'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    pct = float(match.group(1))
                    if 0 < pct <= 100:
                        return pct
                except Exception as _exc:
                    logger.debug(f"Suppressed exception: {_exc!r}")
        
        if 'half' in text.lower():
            return 50.0
        
        return None
    
    def _extract_price(self, text: str) -> Optional[float]:
        """Extract price from text"""
        patterns = [
            r'to\s+(\d+\.?\d*)',
            r'at\s+(\d+\.?\d*)',
            r':\s*(\d+\.?\d*)',
            r'(\d+\.\d+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1))
                except Exception as _exc:
                    logger.debug(f"Suppressed exception: {_exc!r}")
        
        return None
    
    def _extract_lot_size(self, text: str) -> Optional[float]:
        """Extract lot size from text"""
        patterns = [
            r'(\d+\.?\d*)\s*lots?',
            r'add\s+(\d+\.?\d*)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1))
                except Exception as _exc:
                    logger.debug(f"Suppressed exception: {_exc!r}")
        
        return 0.01  # Default minimum lot
