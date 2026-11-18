"""
AI Processors Package
Exports the live AI processing components.

Note: the per-provider processors (OpenAI/DeepSeek/Gemini/Perplexity/Ollama/
OpenRouter) and EnhancedAIProcessor were removed — they were unused duplicates
of IntegratedProcessor, which handles all providers itself.
"""
from .base_processor import BaseAIProcessor
from .integrated_processor import IntegratedProcessor
from .trading_brain import TradingBrain, trading_brain

__all__ = [
    'BaseAIProcessor',
    'IntegratedProcessor',
    'TradingBrain',
    'trading_brain',
]
