"""
Shared helper for logging AI provider API errors with full detail.

Works with any logger (standard logging or loguru) — just pass the module
logger in. Extracts status code, error type, and response body from OpenAI
SDK exceptions so the log file shows exactly what the API returned.
"""
from __future__ import annotations
from typing import Any


def log_api_error(e: Exception, provider: str, logger: Any) -> None:
    """
    Log an AI API exception with full context.

    Handles OpenAI SDK exception hierarchy (used by DeepSeek, Perplexity,
    Gemini, OpenRouter, OpenAI — all OpenAI-compatible providers).
    Falls back to generic logging for non-SDK errors (network, timeout, etc.).
    """
    try:
        import openai

        if isinstance(e, openai.AuthenticationError):
            logger.error(
                f"🔑 {provider} AUTH ERROR (401): Invalid or expired API key. "
                f"Check your API key in settings. Detail: {_body(e)}"
            )

        elif isinstance(e, openai.PermissionDeniedError):
            logger.error(
                f"🚫 {provider} PERMISSION DENIED (403): "
                f"Key lacks access to this resource. Detail: {_body(e)}"
            )

        elif isinstance(e, openai.NotFoundError):
            logger.error(
                f"❓ {provider} NOT FOUND (404): Model or endpoint not found. "
                f"Check your model name in settings. Detail: {_body(e)}"
            )

        elif isinstance(e, openai.RateLimitError):
            body = _body(e)
            # Quota exhaustion arrives as a 429 with specific messages
            body_str = str(body).lower()
            if any(kw in body_str for kw in ("insufficient_quota", "quota", "billing", "balance", "credits", "credit")):
                logger.error(
                    f"💳 {provider} QUOTA/BALANCE ERROR (429): "
                    f"Insufficient credits or quota exhausted. Top up your account. "
                    f"Detail: {body}"
                )
            else:
                logger.warning(
                    f"⏱️ {provider} RATE LIMITED (429): Too many requests. "
                    f"Detail: {body}"
                )

        elif isinstance(e, openai.BadRequestError):
            logger.error(
                f"⚠️ {provider} BAD REQUEST (400): Invalid request parameters. "
                f"Detail: {_body(e)}"
            )

        elif isinstance(e, openai.InternalServerError):
            logger.error(
                f"💥 {provider} SERVER ERROR ({_status(e)}): Provider-side error. "
                f"Detail: {_body(e)}"
            )

        elif isinstance(e, openai.APIStatusError):
            # Catch-all for other HTTP status errors
            logger.error(
                f"🌐 {provider} API ERROR (HTTP {_status(e)}): {_body(e)}"
            )

        elif isinstance(e, openai.APITimeoutError):
            logger.warning(
                f"⏰ {provider} TIMEOUT: Request timed out. "
                f"Provider may be slow or unreachable."
            )

        elif isinstance(e, openai.APIConnectionError):
            logger.error(
                f"🔌 {provider} CONNECTION ERROR: Cannot reach API endpoint. "
                f"Check network / base URL. Detail: {e}"
            )

        else:
            # Not an OpenAI SDK error — generic fallback with full traceback
            logger.error(
                f"❌ {provider} unexpected error: {type(e).__name__}: {e}",
                exc_info=True
            )

    except ImportError:
        # openai not installed — generic fallback
        logger.error(
            f"❌ {provider} error: {type(e).__name__}: {e}",
            exc_info=True
        )


def _body(e: Exception) -> Any:
    """Extract parsed response body from an OpenAI SDK exception."""
    body = getattr(e, "body", None)
    if body:
        return body
    # Fallback: try to get the message attribute
    return getattr(e, "message", str(e))


def _status(e: Exception) -> int:
    """Extract HTTP status code from an OpenAI SDK exception."""
    return getattr(e, "status_code", 0)
