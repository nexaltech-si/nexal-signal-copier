"""
Shared LLM client factory + multi-provider fallback.

Extracted from TradingBrain._build_client() so the Trading Brain, the
IntegratedProcessor (text/intent) and the ImageSignalExtractor (vision) can all
use the same provider-selection logic — and, crucially, automatically fail over
to the next configured provider when one is rate-limited, out of quota, or
misconfigured.

The fallback chain is `[primary provider] + FALLBACK_AI_PROVIDERS`, de-duplicated
and with providers that have no API key skipped.
"""
from typing import Optional, List, Callable, Any
from openai import OpenAI
from loguru import logger

from ai.api_error_handler import log_api_error


def _norm(provider) -> str:
    """Normalise a provider value (handles enums) to a lowercase string."""
    if hasattr(provider, 'value'):
        provider = provider.value
    return str(provider or 'openai').lower().strip()


def build_llm_client_for(config, provider) -> Optional[OpenAI]:
    """
    Build an OpenAI-compatible client for a SPECIFIC provider name.

    Returns None when the provider has no API key or fails to initialise.
    """
    provider = _norm(provider)
    try:
        if provider == 'deepseek' and getattr(config, 'deepseek_api_key', None):
            return OpenAI(
                api_key=config.deepseek_api_key,
                base_url=getattr(config, 'deepseek_api_url', None) or "https://api.deepseek.com",
            )
        if provider == 'gemini' and getattr(config, 'gemini_api_key', None):
            return OpenAI(
                api_key=config.gemini_api_key,
                base_url='https://generativelanguage.googleapis.com/v1beta/openai/',
            )
        if provider == 'openrouter' and getattr(config, 'openrouter_api_key', None):
            return OpenAI(
                api_key=config.openrouter_api_key,
                base_url=getattr(config, 'openrouter_base_url', 'https://openrouter.ai/api/v1'),
            )
        if provider == 'perplexity' and getattr(config, 'perplexity_api_key', None):
            return OpenAI(
                api_key=config.perplexity_api_key,
                base_url=getattr(config, 'perplexity_base_url', 'https://api.perplexity.ai'),
            )
        if provider == 'minimax' and getattr(config, 'minimax_api_key', None):
            return OpenAI(
                api_key=config.minimax_api_key,
                base_url=getattr(config, 'minimax_base_url', 'https://api.minimax.io/v1'),
            )
        if provider == 'qwen' and getattr(config, 'qwen_api_key', None):
            return OpenAI(
                api_key=config.qwen_api_key,
                base_url=getattr(config, 'qwen_base_url', 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1'),
            )
        if provider == 'openai' and getattr(config, 'openai_api_key', None):
            return OpenAI(api_key=config.openai_api_key)
    except Exception as e:
        logger.error(f"❌ LLM client init failed for '{provider}': {e}")
    return None


def get_model_for(config, provider, vision: bool = False) -> str:
    """Get the text (or vision) model name for a specific provider."""
    provider = _norm(provider)
    if vision:
        mapping = {
            'openai':     ('openai_vision_model', 'gpt-4o-mini'),
            'gemini':     ('gemini_vision_model', 'gemini-2.5-flash'),
            'openrouter': ('openrouter_vision_model', 'qwen/qwen2.5-vl-72b-instruct'),
            'perplexity': ('perplexity_vision_model', 'sonar-pro'),
            'minimax':    ('minimax_vision_model', 'MiniMax-M3'),
            'qwen':       ('qwen_vision_model', 'qwen-vl-max'),
            # NOTE: deepseek is intentionally absent here — its chat completions
            # endpoint rejects image_url content outright (400 error on every call).
            # provider_chain() filters it out of the vision chain for the same reason.
        }
    else:
        mapping = {
            'openai':     ('openai_model', 'gpt-4o-mini'),
            'deepseek':   ('deepseek_model', 'deepseek-chat'),
            'gemini':     ('gemini_model', 'gemini-2.5-flash'),
            'openrouter': ('openrouter_model', 'qwen/qwen2.5-vl-72b-instruct'),
            'perplexity': ('perplexity_model', 'sonar-pro'),
            'minimax':    ('minimax_model', 'MiniMax-M2.7'),
            'qwen':       ('qwen_model', 'qwen-plus'),
        }
    attr, default = mapping.get(provider, ('openai_model', 'gpt-4o-mini'))
    return getattr(config, attr, default)


def safe_temperature(model: str, temperature: float) -> float:
    """
    o1/o3-style models only accept temperature=1 (they ignore the parameter
    and raise a BadRequestError for any other value).  Return 1.0 for those
    models, the requested value for everything else.
    """
    _O_SERIES = ('o1-', 'o1 ', '/o1', 'o3-', 'o3 ', '/o3')
    if any(p in model.lower() for p in _O_SERIES):
        return 1.0
    return temperature


# Providers whose API rejects an uncapped request outright (e.g. OpenRouter
# defaults an omitted max_tokens to the model's full context window and 402s
# if the account can't afford that many tokens). Capping per-model "thinking
# budget" guesses are unreliable — reasoning models vary wildly in how many
# hidden tokens they burn — so these providers get a generous flat ceiling
# instead, just large enough that no real response gets truncated.
_TOKEN_CAPPED_PROVIDERS = {'openrouter': 8000}


def max_tokens_for(config, provider: str, output_tokens: int, vision: bool = False) -> Optional[int]:
    """
    Return the max_tokens value to pass for this provider, or None to omit the
    parameter entirely and let the model stop on its own.

    Most providers should run uncapped — the model knows when it's done, and
    a fixed cap can truncate a thinking-heavy model before it ever writes a
    visible answer. Only providers in _TOKEN_CAPPED_PROVIDERS get a flat
    ceiling, because their API requires some cap to avoid a hard error.

    `output_tokens` is unused for the capped case (the ceiling is provider-wide,
    not per-call) and kept only so call sites stay self-documenting about how
    much output they expect.
    """
    return _TOKEN_CAPPED_PROVIDERS.get(_norm(provider))


# Providers whose chat completions endpoint cannot accept image content at all.
# Even if one of these ends up in `provider` (DB/dashboard) or FALLBACK_AI_PROVIDERS
# (shared between the text and vision chains), it must never be tried for a vision
# call — it fails every request with a 400 ("unknown variant `image_url`").
_VISION_INCAPABLE_PROVIDERS = {'deepseek'}


def provider_chain(config, vision: bool = False) -> List[str]:
    """
    Ordered list of providers to try: primary first, then FALLBACK_AI_PROVIDERS.

    De-duplicated, preserving order. Providers without an API key are still
    listed here; complete_with_fallback() skips them when the client can't build.
    For vision calls, providers known to lack image support are filtered out
    entirely (see _VISION_INCAPABLE_PROVIDERS).
    """
    if vision:
        primary = getattr(config, 'vision_provider', getattr(config, 'provider', 'openai'))
    else:
        primary = getattr(config, 'primary_ai_provider', 'openai')
    chain = [_norm(primary)]

    fallbacks = getattr(config, 'fallback_providers', None) or []
    for p in fallbacks:
        chain.append(_norm(p))

    seen, out = set(), []
    for p in chain:
        if not p or p in seen:
            continue
        if vision and p in _VISION_INCAPABLE_PROVIDERS:
            continue
        seen.add(p)
        out.append(p)
    return out


def first_available_provider(config, vision: bool = False) -> Optional[str]:
    """
    Return the first provider in the (vision) chain that has a buildable client,
    or None when no provider in the chain has an API key.

    This is the single source of truth for "is AI available?" gates — it walks
    the SAME ordered chain that complete_with_fallback() uses, so a gate built on
    it can never reject a request that the engine would actually have served via
    a fallback provider.
    """
    for provider in provider_chain(config, vision=vision):
        if build_llm_client_for(config, provider) is not None:
            return provider
    return None


def list_models_for(config, provider: str) -> Optional[List[str]]:
    """
    Fetch the live list of model IDs the provider's API currently serves.

    Returns None when the provider has no key, has no /v1/models endpoint
    (e.g. Perplexity returns 404), or the call otherwise fails — callers
    should treat None as "couldn't check", not "no models".
    """
    client = build_llm_client_for(config, provider)
    if client is None:
        return None
    try:
        return [m.id for m in client.models.list().data]
    except Exception as e:
        logger.debug(f"list_models_for('{provider}') unavailable: {e}")
        return None


def validate_configured_models(config) -> List[str]:
    """
    Cross-check every provider's configured text/vision model against that
    provider's live model list. Returns a list of human-readable warning
    strings — empty when everything checks out (or every provider's models
    endpoint is unreachable/unsupported, in which case nothing is flagged
    rather than raising false positives).

    A model ID is considered valid if it appears in the live list verbatim,
    or after stripping a "models/" prefix (Gemini) — providers are otherwise
    free-form strings, so this stays a substring-tolerant best-effort check.
    """
    warnings: List[str] = []
    checked_providers = set()

    for vision in (False, True):
        for provider in provider_chain(config, vision=vision):
            key = (provider, vision)
            if key in checked_providers:
                continue
            checked_providers.add(key)

            configured = get_model_for(config, provider, vision=vision)
            if not configured:
                continue

            live = list_models_for(config, provider)
            if live is None:
                continue  # provider has no key, or no models endpoint — can't check

            live_norm = {m.split('/')[-1] if m.startswith('models/') else m for m in live}
            if configured not in live_norm and configured not in live:
                kind = 'vision' if vision else 'text'
                warnings.append(
                    f"{provider} {kind} model '{configured}' not found in live model list "
                    f"({len(live)} models available, e.g. {live[:3]})"
                )
    return warnings


def _is_retryable(e: Exception) -> bool:
    """A provider error worth failing over to the next provider for."""
    try:
        import openai
        if isinstance(e, (
            openai.RateLimitError,        # 429 / quota / billing cap
            openai.AuthenticationError,   # 401 bad key
            openai.PermissionDeniedError, # 403
            openai.NotFoundError,         # 404 bad model
            openai.BadRequestError,       # 400 bad params/model on this provider
            openai.APITimeoutError,
            openai.APIConnectionError,
            openai.InternalServerError,
        )):
            return True
    except ImportError:
        pass
    s = str(e).lower()
    return any(k in s for k in (
        'timeout', 'timed out', 'connection', '429', 'rate', 'quota',
        'billing', 'balance', 'credit', 'unavailable', 'exhausted',
    ))


def _describe_empty(response) -> str:
    """
    Best-effort explanation for why a completion came back with no usable content —
    e.g. a safety block or the model exhausting its token budget on reasoning before
    writing an answer. Falls back to a generic note when no detail is available.
    """
    try:
        choice = response.choices[0]
        finish_reason = getattr(choice, 'finish_reason', None)
        if finish_reason and finish_reason != 'stop':
            return f"finish_reason={finish_reason}"
    except Exception as _exc:
        logger.debug(f"Suppressed exception: {_exc!r}")
    return "no content in response"


def complete_with_fallback(
    config,
    providers: List[str],
    make_call: Callable[[OpenAI, str, str], Any],
    *,
    vision: bool = False,
    validate: Optional[Callable[[Any], bool]] = None,
    log=logger,
    caller: str = 'unknown',
    latency_ms: Optional[int] = None,
) -> Any:
    """
    Run a chat completion against the first working provider in `providers`.

    `make_call(client, model, provider)` performs the actual SDK call and returns
    its response. On a retryable provider error (rate-limit/quota/auth/bad-model/
    connection) — or when `validate(response)` returns False (e.g. empty content)
    — the next provider is tried. Raises the last error if every provider fails.

    Synchronous: callers in async code should wrap this in run_in_executor.

    `caller` is a short identifier of the calling function used for cost reports.
    `latency_ms` is the wall-clock time of the call in milliseconds (optional).
    """
    last_exc: Optional[Exception] = None
    attempted = 0

    for provider in providers:
        client = build_llm_client_for(config, provider)
        if client is None:
            continue  # no key / unsupported — skip silently
        model = get_model_for(config, provider, vision=vision)
        attempted += 1
        try:
            response = make_call(client, model, provider)
        except Exception as e:
            last_exc = e
            log_api_error(e, provider, log)
            if not _is_retryable(e):
                raise
            log.warning(f"🔁 Provider '{provider}' failed — falling back to next provider")
            continue

        if validate is not None and not validate(response):
            last_exc = RuntimeError(f"{provider} returned empty/invalid completion")
            log.warning(
                f"🔁 Provider '{provider}' (model={model}) returned empty result "
                f"({_describe_empty(response)}) — falling back to next provider"
            )
            continue

        if attempted > 1:
            log.success(f"✅ Recovered via fallback provider '{provider}'")

        # Track token usage and cost
        try:
            from ai.cost_tracker import cost_tracker
            usage = getattr(response, 'usage', None)
            if usage:
                cost_tracker.record(
                    caller=caller,
                    provider=provider,
                    model=model,
                    prompt_tokens=getattr(usage, 'prompt_tokens', 0) or 0,
                    completion_tokens=getattr(usage, 'completion_tokens', 0) or 0,
                    latency_ms=latency_ms,
                    vision=vision,
                )
        except Exception as _exc:
            logger.debug(f"Suppressed exception: {_exc!r}")

        return response

    if last_exc:
        raise last_exc
    raise RuntimeError("No AI provider available (no API keys configured)")


def extract_content(response) -> str:
    """
    Extract text content from a chat completion response.

    Reasoning models (DeepSeek-R1, deepseek-v4-flash, o1, etc.) store their
    chain-of-thought in `reasoning_content` and the final answer in `content`.
    When `content` is None or empty — which happens when the model exhausts its
    token budget on thinking, or when the provider uses a different field name —
    fall back to `reasoning_content` so we never silently lose the response.
    """
    msg = response.choices[0].message
    content = getattr(msg, 'content', None) or ''
    if not content.strip():
        content = getattr(msg, 'reasoning_content', None) or ''
    return content


def build_llm_client(config) -> Optional[OpenAI]:
    """
    Build a client for the configured primary provider, falling back to OpenAI
    if the primary has no key. (Back-compat for TradingBrain / MarketAnalyzer.)
    """
    provider = getattr(config, 'primary_ai_provider', 'openai')
    client = build_llm_client_for(config, provider)
    if client is not None:
        return client
    return build_llm_client_for(config, 'openai')


def get_llm_model(config) -> str:
    """Get the model name for the configured primary provider. (Back-compat.)"""
    return get_model_for(config, getattr(config, 'primary_ai_provider', 'openai'))
