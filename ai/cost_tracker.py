"""
Local AI cost and token tracker.

Records every LLM call made by the bot — which function called it, which
provider/model was used, how many tokens were consumed, and the estimated
cost in USD.  Data is persisted to data/ai_costs.json so reports survive
restarts.  The singleton is thread-safe and never raises; tracking failures
are silently swallowed so they never break the calling code.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

# ─── Pricing constants: USD per 1 million tokens ──────────────────────────────
# fmt: off
PRICING: Dict[str, Dict[str, Dict[str, float]]] = {
    'openai': {
        'gpt-4o':                   {'input': 2.50,  'output': 10.00},
        'gpt-4o-mini':              {'input': 0.15,  'output': 0.60 },
        'gpt-4o-2024-11-20':        {'input': 2.50,  'output': 10.00},
        'gpt-4o-2024-08-06':        {'input': 2.50,  'output': 10.00},
        'gpt-4-turbo':              {'input': 10.00, 'output': 30.00},
        'gpt-4':                    {'input': 30.00, 'output': 60.00},
        'gpt-3.5-turbo':            {'input': 0.50,  'output': 1.50 },
        'o1':                       {'input': 15.00, 'output': 60.00},
        'o1-mini':                  {'input': 3.00,  'output': 12.00},
        'o1-preview':               {'input': 15.00, 'output': 60.00},
        'o3':                       {'input': 10.00, 'output': 40.00},
        'o3-mini':                  {'input': 1.10,  'output': 4.40 },
        'o4-mini':                  {'input': 1.10,  'output': 4.40 },
    },
    'deepseek': {
        'deepseek-chat':            {'input': 0.27,  'output': 1.10 },
        'deepseek-reasoner':        {'input': 0.55,  'output': 2.19 },
        'deepseek-coder':           {'input': 0.14,  'output': 0.28 },
        'deepseek-v4':              {'input': 0.27,  'output': 1.10 },
        'deepseek-v3':              {'input': 0.27,  'output': 1.10 },
    },
    'gemini': {
        'gemini-2.5-pro':           {'input': 1.25,  'output': 10.00},
        'gemini-2.5-flash':         {'input': 0.15,  'output': 0.60 },
        'gemini-2.0-flash':         {'input': 0.10,  'output': 0.40 },
        'gemini-2.0-flash-lite':    {'input': 0.075, 'output': 0.30 },
        'gemini-1.5-pro':           {'input': 1.25,  'output': 5.00 },
        'gemini-1.5-flash':         {'input': 0.075, 'output': 0.30 },
    },
    'openrouter': {
        'qwen/qwen2.5-vl-72b-instruct': {'input': 0.40, 'output': 0.40},
        'qwen/qwen2.5-72b-instruct':    {'input': 0.35, 'output': 0.40},
        'meta-llama/llama-3.3-70b-instruct': {'input': 0.12, 'output': 0.30},
        'mistralai/mistral-large':      {'input': 2.00, 'output': 6.00},
        'anthropic/claude-3.5-sonnet':  {'input': 3.00, 'output': 15.00},
        'anthropic/claude-3-haiku':     {'input': 0.25, 'output': 1.25},
        'google/gemini-2.0-flash':      {'input': 0.10, 'output': 0.40},
        'openai/gpt-4o':                {'input': 2.50, 'output': 10.00},
        'openai/gpt-4o-mini':           {'input': 0.15, 'output': 0.60},
        'deepseek/deepseek-chat':       {'input': 0.27, 'output': 1.10},
        'deepseek/deepseek-r1':         {'input': 0.55, 'output': 2.19},
    },
    'perplexity': {
        'sonar-pro':                {'input': 3.00,  'output': 15.00},
        'sonar':                    {'input': 1.00,  'output': 1.00 },
        'sonar-reasoning-pro':      {'input': 2.00,  'output': 8.00 },
        'sonar-reasoning':          {'input': 1.00,  'output': 5.00 },
        'sonar-deep-research':      {'input': 2.00,  'output': 8.00 },
    },
    'minimax': {
        'MiniMax-VL-01':            {'input': 0.10,  'output': 0.10 },
        'MiniMax-M2.7':             {'input': 0.10,  'output': 0.10 },
        'minimax-text-01':          {'input': 0.30,  'output': 1.10 },
        'abab6.5-chat':             {'input': 0.10,  'output': 0.10 },
    },
    'qwen': {
        'qwen-plus':                {'input': 0.50,  'output': 1.50 },
        'qwen-max':                 {'input': 1.60,  'output': 6.40 },
        'qwen-vl-max':              {'input': 2.00,  'output': 6.00 },
        'qwen-turbo':               {'input': 0.06,  'output': 0.18 },
        'qwen2.5-72b-instruct':     {'input': 0.35,  'output': 0.40 },
        'qwen2.5-vl-72b-instruct':  {'input': 0.40,  'output': 0.40 },
    },
    'hermes': {
        # Hermes is a self-hosted wrapper; cost depends on the underlying model.
        # Default to zero so tracked calls still appear in function reports.
    },
}
# fmt: on

# Human-readable labels for internal caller IDs
CALLER_LABELS: Dict[str, str] = {
    'classify_intent':    'Intent Classification',
    'signal_extraction':  'Signal Extraction (Text)',
    'vision_classify':    'Vision: Image Classification',
    'vision_extraction':  'Vision: Signal Extraction',
    'vision_manual':      'Vision: Manual Trade (Telegram page)',
    'trade_command':      'Trade Command Parsing',
    'brain_review':       'Trading Brain (Chat)',
    'brain_hermes':       'Trading Brain (Hermes)',
    'market_analysis':    'Market Analysis (LLM)',
    'rule_generation':    'Channel Rule Generation',
    'context_resolution': 'Symbol Context Resolution',
    'tp_detection':       'TP Hit Detection',
}


def _data_path() -> str:
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, 'data', 'ai_costs.json')


def estimate_cost(provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Return estimated cost in USD. Returns 0.0 when pricing is unknown."""
    provider_prices = PRICING.get(provider.lower(), {})
    model_prices = provider_prices.get(model)
    if not model_prices:
        # Prefix/substring match (handles versioned model names like gpt-4o-2024-xx)
        ml = model.lower()
        for key, prices in provider_prices.items():
            if ml.startswith(key.lower()) or key.lower() in ml:
                model_prices = prices
                break
    if not model_prices:
        return 0.0
    cost = (prompt_tokens * model_prices['input'] + completion_tokens * model_prices['output']) / 1_000_000
    return round(cost, 8)


class CostTracker:
    """Thread-safe singleton that persists every AI call to data/ai_costs.json."""

    _instance: Optional['CostTracker'] = None
    _init_lock = threading.Lock()

    def __new__(cls) -> 'CostTracker':
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._lock = threading.Lock()
                    inst._records: List[Dict[str, Any]] = []
                    inst._path = _data_path()
                    inst._load()
                    cls._instance = inst
        return cls._instance

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        try:
            if os.path.exists(self._path):
                with open(self._path, 'r') as f:
                    data = json.load(f)
                self._records = data.get('records', [])
        except Exception:
            self._records = []

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, 'w') as f:
                json.dump({'records': self._records}, f, separators=(',', ':'))
        except Exception:
            pass

    # ── Public API ────────────────────────────────────────────────────────────

    def record(
        self,
        caller: str,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: Optional[int] = None,
        vision: bool = False,
    ) -> None:
        """Record a completed LLM call. Never raises."""
        try:
            cost = estimate_cost(provider, model, prompt_tokens, completion_tokens)
            entry: Dict[str, Any] = {
                'ts': datetime.now(timezone.utc).isoformat(),
                'caller': caller,
                'provider': provider,
                'model': model,
                'prompt_tokens': prompt_tokens,
                'completion_tokens': completion_tokens,
                'total_tokens': prompt_tokens + completion_tokens,
                'cost_usd': cost,
                'vision': vision,
            }
            if latency_ms is not None:
                entry['latency_ms'] = latency_ms
            with self._lock:
                self._records.append(entry)
                self._save()
        except Exception:
            pass

    def get_report(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Return a structured report aggregated by function, provider, and model.

        start_date / end_date: ISO date strings (YYYY-MM-DD), inclusive.
        Omit both to include all records.
        """
        with self._lock:
            records = list(self._records)

        # Filter by date range
        if start_date or end_date:
            filtered = []
            for r in records:
                ts = r.get('ts', '')[:10]
                if start_date and ts < start_date:
                    continue
                if end_date and ts > end_date:
                    continue
                filtered.append(r)
            records = filtered

        # Aggregation helpers
        def _blank() -> Dict[str, Any]:
            return {'calls': 0, 'prompt_tokens': 0, 'completion_tokens': 0,
                    'total_tokens': 0, 'cost_usd': 0.0, 'vision_calls': 0}

        def _add(acc: Dict, r: Dict) -> None:
            acc['calls'] += 1
            acc['prompt_tokens'] += r.get('prompt_tokens', 0)
            acc['completion_tokens'] += r.get('completion_tokens', 0)
            acc['total_tokens'] += r.get('total_tokens', 0)
            acc['cost_usd'] += r.get('cost_usd', 0.0)
            if r.get('vision'):
                acc['vision_calls'] += 1

        by_function: Dict[str, Dict] = {}
        by_provider: Dict[str, Dict] = {}
        by_model: Dict[str, Dict] = {}
        totals = _blank()

        for r in records:
            caller = (r.get('caller') or 'unknown').strip() or 'unknown'
            provider = (r.get('provider') or 'unknown').strip() or 'unknown'
            model = (r.get('model') or 'unknown').strip() or 'unknown'

            if caller not in by_function:
                by_function[caller] = {**_blank(), 'label': CALLER_LABELS.get(caller, caller)}
            if provider not in by_provider:
                by_provider[provider] = _blank()
            if model not in by_model:
                by_model[model] = {**_blank(), 'provider': provider}

            _add(by_function[caller], r)
            _add(by_provider[provider], r)
            _add(by_model[model], r)
            _add(totals, r)

        # Add avg tokens per call
        for group in list(by_function.values()) + list(by_provider.values()) + list(by_model.values()):
            calls = group['calls']
            group['avg_tokens_per_call'] = round(group['total_tokens'] / calls, 1) if calls else 0

        totals['cost_usd'] = round(totals['cost_usd'], 8)

        # Normalize the recent slice the same way as the aggregate buckets so the
        # log and the totals agree (e.g. empty provider -> 'unknown').
        recent = []
        for r in records[-50:][::-1]:  # last 50, newest first
            recent.append({
                **r,
                'caller': (r.get('caller') or 'unknown').strip() or 'unknown',
                'provider': (r.get('provider') or 'unknown').strip() or 'unknown',
                'model': (r.get('model') or 'unknown').strip() or 'unknown',
            })

        return {
            'summary': totals,
            'by_function': by_function,
            'by_provider': by_provider,
            'by_model': by_model,
            'recent': recent,
            'total_records': len(records),
            'pricing': PRICING,
            'caller_labels': CALLER_LABELS,
        }

    def reset(self) -> None:
        """Clear all records."""
        with self._lock:
            self._records = []
            self._save()


# Module-level singleton
cost_tracker = CostTracker()
