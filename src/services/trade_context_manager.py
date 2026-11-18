"""
Trade Context Manager
Provides context for resolving ambiguous commands like "close gold" or "set BE"
Uses AI to understand conversation context, falls back to database queries
"""
from typing import Optional, List, Dict
from datetime import datetime, timezone, timedelta
from loguru import logger
from collections import defaultdict

from src.models import TradingSignal, SignalAction
from src.core.database_service import db_service


class TradeContextManager:
    """
    Manages trade context for resolving ambiguous commands
    
    Examples:
    - "Close gold" → Finds open XAUUSD position
    - "Set BE" → Applies to most recent trade
    - "Take 50% EURUSD" → Finds open EURUSD position
    """
    
    def __init__(self, ai_client=None):
        """Initialize trade context manager"""
        self.recent_symbols_cache: Dict[str, List[str]] = defaultdict(list)  # channel_id → [symbols]
        self.conversation_history: Dict[str, List[Dict]] = defaultdict(list)  # channel_id → messages
        self.cache_ttl = timedelta(hours=24)  # Cache recent symbols for 24 hours
        self.ai_client = ai_client  # OpenAI/DeepSeek client for AI resolution

    
    async def resolve_symbol_from_context(
        self,
        signal: TradingSignal,
        channel_id: str
    ) -> TradingSignal:
        """
        Resolve missing symbol from context
        
        Args:
            signal: Signal with possibly missing symbol
            channel_id: Channel where command was sent
            
        Returns:
            Signal with resolved symbol (or original if can't resolve)
        """
        # If symbol is already present, no need to resolve
        if signal.symbol:
            logger.debug(f"Symbol already present: {signal.symbol}")
            return signal
        
        # Only resolve for CLOSE, MODIFY, PARTIAL_CLOSE actions
        if signal.action not in [SignalAction.CLOSE, SignalAction.MODIFY, SignalAction.PARTIAL_CLOSE]:
            logger.debug(f"Action {signal.action} doesn't need symbol resolution")
            return signal
        
        logger.info(f"🔍 Resolving symbol from context for {signal.action} command")
        
        # Try to extract symbol from the raw message
        extracted_symbol = self._extract_symbol_from_message(signal.raw_message)
        if extracted_symbol:
            logger.info(f"✅ Extracted symbol from message: {extracted_symbol}")
            signal.symbol = extracted_symbol
            return signal
        
        # Step 1: Try AI-based context resolution
        if self.ai_client:
            ai_resolved_symbol = await self._resolve_with_ai(signal, channel_id)
            if ai_resolved_symbol:
                logger.info(f"🤖 AI resolved symbol: {ai_resolved_symbol}")
                signal.symbol = ai_resolved_symbol
                return signal
        
        # Step 2: Fallback to database query
        logger.debug("AI resolution failed, falling back to database query")
        open_positions = await self._get_open_positions(channel_id=channel_id)
        
        if not open_positions:
            logger.warning(f"⚠️ No open positions found to resolve context for channel {channel_id}")
            return signal
        
        # Strategy: Use the most recent open position
        most_recent = max(open_positions, key=lambda p: p.get('opened_at', datetime.min))
        resolved_symbol = most_recent.get('symbol')
        
        if resolved_symbol:
            logger.info(f"✅ Resolved symbol from most recent position: {resolved_symbol}")
            logger.debug(f"   Position opened at: {most_recent.get('opened_at')}")
            signal.symbol = resolved_symbol
        else:
            logger.warning("⚠️ Could not resolve symbol from context")
        
        return signal
    
    async def resolve_symbol_for_command(
        self,
        command_text: str,
        action: SignalAction,
        channel_id: str
    ) -> Optional[str]:
        """
        Resolve symbol for a command that mentions it
        
        Examples:
        - "close gold" → "XAUUSD"
        - "set BE on EURUSD" → "EURUSD"
        - "take 50% from the gold trade" → "XAUUSD"
        
        Args:
            command_text: The command text
            action: The action type
            channel_id: Channel ID
            
        Returns:
            Resolved symbol or None
        """
        # Extract symbol mention from text
        symbol = self._extract_symbol_from_message(command_text)
        if symbol:
            return symbol
        
        # Get open positions (filtered by channel)
        open_positions = await self._get_open_positions(channel_id=channel_id)
        
        if not open_positions:
            return None
        
        # If single open position, use it
        if len(open_positions) == 1:
            resolved = open_positions[0].get('symbol')
            logger.info(f"✅ Single open position, using: {resolved}")
            return resolved
        
        # Multiple positions - use most recent
        most_recent = max(open_positions, key=lambda p: p.get('opened_at', datetime.min))
        resolved = most_recent.get('symbol')
        logger.info(f"✅ Multiple positions, using most recent: {resolved}")
        return resolved
    
    def _extract_symbol_from_message(self, message: str) -> Optional[str]:
        """
        Extract symbol from message text
        
        Looks for common symbol names and converts them to proper symbols
        """
        if not message:
            return None
        
        msg_upper = message.upper()
        
        # Comprehensive symbol mapping (same as in IntegratedProcessor)
        symbol_patterns = {
            # Precious Metals
            'GOLD': 'XAUUSD', 'XAU': 'XAUUSD', 'XAUUSD': 'XAUUSD',
            'SILVER': 'XAGUSD', 'XAG': 'XAGUSD', 'XAGUSD': 'XAGUSD',
            
            # Major Forex Pairs
            'EURUSD': 'EURUSD', 'EUR/USD': 'EURUSD', 'EUR': 'EURUSD',
            'GBPUSD': 'GBPUSD', 'GBP/USD': 'GBPUSD', 'GBP': 'GBPUSD', 'CABLE': 'GBPUSD',
            'USDJPY': 'USDJPY', 'USD/JPY': 'USDJPY', 'JPY': 'USDJPY',
            'AUDUSD': 'AUDUSD', 'AUD/USD': 'AUDUSD', 'AUD': 'AUDUSD', 'AUSSIE': 'AUDUSD',
            'NZDUSD': 'NZDUSD', 'NZD/USD': 'NZDUSD', 'NZD': 'NZDUSD', 'KIWI': 'NZDUSD',
            'USDCAD': 'USDCAD', 'USD/CAD': 'USDCAD', 'CAD': 'USDCAD', 'LOONIE': 'USDCAD',
            'USDCHF': 'USDCHF', 'USD/CHF': 'USDCHF', 'CHF': 'USDCHF', 'SWISSY': 'USDCHF',
            
            # Cross Pairs
            'EURGBP': 'EURGBP', 'EUR/GBP': 'EURGBP',
            'EURJPY': 'EURJPY', 'EUR/JPY': 'EURJPY',
            'GBPJPY': 'GBPJPY', 'GBP/JPY': 'GBPJPY',
            'AUDJPY': 'AUDJPY', 'AUD/JPY': 'AUDJPY',
            
            # Indices
            'US30': 'US30', 'DOW': 'US30', 'DJIA': 'US30', 'DOW JONES': 'US30',
            'NAS100': 'NAS100', 'NASDAQ': 'NAS100', 'NDX': 'NAS100',
            'US500': 'US500', 'SPX': 'US500', 'S&P': 'US500', 'SP500': 'US500',
            
            # Commodities
            'OIL': 'USOIL', 'CRUDE': 'USOIL', 'WTI': 'USOIL', 'USOIL': 'USOIL',
            'BRENT': 'UKOIL', 'UKOIL': 'UKOIL',
            
            # Crypto
            'BTC': 'BTCUSD', 'BITCOIN': 'BTCUSD', 'BTCUSD': 'BTCUSD',
            'ETH': 'ETHUSD', 'ETHEREUM': 'ETHUSD', 'ETHUSD': 'ETHUSD',
        }
        
        # Sort by length (longer first to avoid partial matches)
        sorted_patterns = sorted(symbol_patterns.items(), key=lambda x: len(x[0]), reverse=True)
        
        for pattern, symbol in sorted_patterns:
            if pattern in msg_upper:
                logger.debug(f"Matched symbol pattern: {pattern} → {symbol}")
                return symbol
        
        return None
    
    async def _get_open_positions(self, channel_id: Optional[str] = None) -> List[Dict]:
        """
        Get currently open positions from database
        
        Args:
            channel_id: Optional channel ID to filter positions by specific channel
        
        Returns:
            List of open position dictionaries with symbol, opened_at, etc.
        """
        try:
            # Query database for open positions (filtered by channel if provided)
            positions = await db_service.get_open_positions(channel_id=channel_id)
            
            if not positions:
                logger.debug(f"No open positions in database{' for channel ' + channel_id if channel_id else ''}")
                return []
            
            logger.debug(f"Found {len(positions)} open positions{' for channel ' + channel_id if channel_id else ''}")
            return positions
            
        except Exception as e:
            logger.error(f"Error fetching open positions: {e}")
            return []
    
    async def get_position_by_symbol(self, symbol: str, channel_id: Optional[str] = None) -> Optional[Dict]:
        """
        Get specific open position by symbol
        
        Args:
            symbol: Symbol to look for (e.g., "XAUUSD")
            channel_id: Optional channel ID to filter by specific channel
            
        Returns:
            Position dict or None
        """
        try:
            positions = await self._get_open_positions(channel_id=channel_id)
            
            # Find position matching symbol
            for pos in positions:
                if pos.get('symbol') == symbol:
                    return pos
            
            logger.debug(f"No open position found for {symbol}{' in channel ' + channel_id if channel_id else ''}")
            return None
            
        except Exception as e:
            logger.error(f"Error finding position for {symbol}: {e}")
            return None
    
    def update_recent_symbols(self, channel_id: str, symbol: str):
        """
        Track recently mentioned symbols per channel
        
        Args:
            channel_id: Channel ID
            symbol: Symbol that was mentioned
        """
        if symbol:
            if symbol not in self.recent_symbols_cache[channel_id]:
                self.recent_symbols_cache[channel_id].append(symbol)
                # Keep only last 10 symbols
                self.recent_symbols_cache[channel_id] = self.recent_symbols_cache[channel_id][-10:]
                logger.debug(f"Updated recent symbols for {channel_id}: {symbol}")
    
    def add_to_conversation_history(self, channel_id: str, message: str, signal_info: Optional[Dict] = None):
        """
        Add message to conversation history for AI context
        
        Args:
            channel_id: Channel ID
            message: Message text
            signal_info: Optional signal info (action, symbol, etc.)
        """
        history_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "message": message,
            "signal": signal_info
        }
        
        self.conversation_history[channel_id].append(history_entry)
        
        # Keep only last 20 messages
        self.conversation_history[channel_id] = self.conversation_history[channel_id][-20:]
    
    async def _resolve_with_ai(self, signal: TradingSignal, channel_id: str) -> Optional[str]:
        """
        Use AI to resolve symbol from conversation context
        
        Args:
            signal: Signal with missing symbol
            channel_id: Channel ID
            
        Returns:
            Resolved symbol or None
        """
        try:
            # Get recent conversation history
            history = self.conversation_history.get(channel_id, [])[-10:]  # Last 10 messages
            
            # Get open positions (filtered by channel)
            open_positions = await self._get_open_positions(channel_id=channel_id)
            
            if not open_positions:
                logger.debug(f"No open positions for AI context in channel {channel_id}")
                return None
            
            # Build context prompt
            context_prompt = self._build_ai_context_prompt(
                current_message=signal.raw_message,
                action=signal.action,
                conversation_history=history,
                open_positions=open_positions
            )
            
            # Determine which model to use based on client base_url
            model = "gpt-4o-mini"  # Default to OpenAI
            if hasattr(self.ai_client, 'base_url') and 'deepseek' in str(self.ai_client.base_url).lower():
                model = "deepseek-chat"  # Use DeepSeek model
            
            # Call AI
            response = self.ai_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a trading assistant that resolves which trade a user is referring to based on conversation context."},
                    {"role": "user", "content": context_prompt}
                ],
                temperature=0.1
            )

            try:
                from ai.cost_tracker import cost_tracker
                usage = getattr(response, 'usage', None)
                if usage:
                    provider = 'deepseek' if 'deepseek' in model else 'openai'
                    cost_tracker.record(
                        caller='context_resolution',
                        provider=provider,
                        model=model,
                        prompt_tokens=getattr(usage, 'prompt_tokens', 0) or 0,
                        completion_tokens=getattr(usage, 'completion_tokens', 0) or 0,
                    )
            except Exception as _exc:
                logger.debug(f"Suppressed exception: {_exc!r}")

            content = response.choices[0].message.content.strip()
            
            # Parse response (expecting just symbol or "NONE")
            if content and content != "NONE" and len(content) <= 10:
                # Normalize symbol
                normalized = self._normalize_symbol_name(content)
                logger.debug(f"AI context resolution: {content} → {normalized}")
                return normalized
            
            logger.debug(f"AI could not resolve symbol: {content}")
            return None
            
        except Exception as e:
            logger.error(f"AI context resolution error: {e}")
            return None
    
    def _build_ai_context_prompt(
        self,
        current_message: str,
        action: SignalAction,
        conversation_history: List[Dict],
        open_positions: List[Dict]
    ) -> str:
        """Build prompt for AI context resolution"""
        
        # Format open positions
        positions_str = "\n".join([
            f"- {p['symbol']}: {p.get('order_type', 'BUY')} opened at {p.get('opened_at', 'Unknown')}"
            for p in open_positions
        ])
        
        # Format conversation history
        history_str = "\n".join([
            f"[{h['timestamp'][:19]}] {h['message'][:100]}"
            for h in conversation_history
        ]) if conversation_history else "No recent conversation"
        
        prompt = f"""Based on the conversation context and open positions, determine which trade the user is referring to.

CURRENT COMMAND:
"{current_message}"
Action: {action.value if action else 'UNKNOWN'}

OPEN POSITIONS:
{positions_str if positions_str else "No open positions"}

RECENT CONVERSATION:
{history_str}

TASK:
Return ONLY the symbol (e.g., "XAUUSD", "EURUSD") that the command refers to.
If you cannot determine with confidence, return "NONE".
If the user says "gold" or "Gold", return "XAUUSD".
If the user says "euro" or "EUR", return "EURUSD".

Your response (symbol only or "NONE"):"""
        
        return prompt
    
    def _normalize_symbol_name(self, symbol: str) -> str:
        """Normalize symbol name from AI response (shared canonical implementation)"""
        from src.utils.symbols import normalize_symbol
        return normalize_symbol(symbol)


# Singleton instance (will be initialized with AI client by signal service)
trade_context_manager = TradeContextManager()
