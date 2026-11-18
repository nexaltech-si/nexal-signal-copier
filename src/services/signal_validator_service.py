"""
Signal Validator Service
Calls the external Signal Validator API before trade execution.
Supports timeout handling, fail-open on unreachable API, and execution policy.
"""
from dataclasses import dataclass, field
from typing import Optional, List, Any
from loguru import logger

from config import settings


@dataclass
class SignalValidationResult:
    """Result from the Signal Validator API"""
    verdict: str = "UNAVAILABLE"       # VALID, WARN, INVALID, UNAVAILABLE
    score: Optional[float] = None
    trade_type: Optional[str] = None   # scalp, intraday, long_term
    rr_tp1: Optional[float] = None
    rr_tp2: Optional[float] = None
    sl_pips: Optional[float] = None
    atr: Optional[float] = None
    regime_label: Optional[str] = None
    zone: Optional[Any] = None
    issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    is_unavailable: bool = False
    blocked_by_policy: bool = False
    block_reason: str = ""

    @property
    def verdict_emoji(self) -> str:
        if self.is_unavailable:
            return "⚠️"
        return {"VALID": "✅", "WARN": "⚠️", "INVALID": "❌"}.get(self.verdict, "❓")


class SignalValidatorService:
    """
    Calls external Signal Validator API and applies execution policy.

    Execution policies:
      ALL        — all verdicts pass (fail-open, no blocking)
      VALID_WARN — block INVALID only
      VALID_ONLY — block WARN and INVALID
    """

    def _build_request_body(self, signal) -> Optional[dict]:
        """Build the API request body from a TradingSignal. Returns None if signal can't be mapped."""
        from src.models.enums import OrderType

        # Determine direction
        getattr(signal, 'action', None)
        order_type = getattr(signal, 'order_type', None)

        if order_type == OrderType.BUY:
            direction = "LONG"
        elif order_type == OrderType.SELL:
            direction = "SHORT"
        else:
            logger.warning("⚠️ Signal Validator: cannot determine direction (no order_type), skipping")
            return None

        pair = signal.symbol
        entry = signal.entry_price
        sl = signal.stop_loss

        if not pair or not entry or not sl:
            logger.warning("⚠️ Signal Validator: missing pair/entry/sl — skipping validation")
            return None

        take_profits = signal.take_profit or []
        if len(take_profits) >= 2:
            tp1 = take_profits[0]
            tp2 = take_profits[1]
        elif len(take_profits) == 1:
            tp1 = take_profits[0]
            # Extrapolate: tp2 = tp1 + (tp1 - entry)
            tp2 = round(tp1 + (tp1 - entry), 5)
            logger.debug(f"📐 Single-TP signal: extrapolated tp2={tp2} from tp1={tp1}, entry={entry}")
        else:
            logger.warning("⚠️ Signal Validator: no take profit levels — skipping validation")
            return None

        return {
            "pair": pair,
            "direction": direction,
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
        }

    def _apply_policy(self, result: SignalValidationResult) -> SignalValidationResult:
        """Apply the execution policy and set blocked_by_policy / block_reason."""
        if result.is_unavailable:
            return result

        policy = settings.signal_validator_execution_policy.upper()
        verdict = result.verdict.upper()

        if policy == "ALL":
            pass  # nothing blocked
        elif policy == "VALID_WARN":
            if verdict == "INVALID":
                result.blocked_by_policy = True
                issues_text = "; ".join(result.issues) if result.issues else "signal failed validation"
                result.block_reason = f"Signal Validator returned INVALID: {issues_text}"
        elif policy == "VALID_ONLY":
            if verdict in ("INVALID", "WARN"):
                result.blocked_by_policy = True
                if verdict == "INVALID":
                    issues_text = "; ".join(result.issues) if result.issues else "signal failed validation"
                    result.block_reason = f"Signal Validator returned INVALID: {issues_text}"
                else:
                    warnings_text = "; ".join(result.warnings) if result.warnings else "signal has warnings"
                    result.block_reason = f"Signal Validator returned WARN (policy=VALID_ONLY): {warnings_text}"
        else:
            logger.warning(f"⚠️ Unknown SIGNAL_VALIDATOR_EXECUTION_POLICY='{policy}', defaulting to VALID_WARN")
            if verdict == "INVALID":
                result.blocked_by_policy = True
                result.block_reason = "Signal Validator returned INVALID"

        return result

    async def validate(self, signal) -> SignalValidationResult:
        """
        Validate a trading signal against the external API.

        Returns a SignalValidationResult. Never raises — on any error or
        timeout returns an UNAVAILABLE result (fail-open).
        """
        if not settings.enable_signal_validator:
            logger.debug("🔕 Signal Validator disabled (ENABLE_SIGNAL_VALIDATOR=false)")
            return SignalValidationResult(verdict="UNAVAILABLE", is_unavailable=True)

        if not settings.signal_validator_api_key:
            logger.warning("⚠️ Signal Validator: no API key configured — skipping")
            return SignalValidationResult(verdict="UNAVAILABLE", is_unavailable=True)

        body = self._build_request_body(signal)
        if body is None:
            return SignalValidationResult(verdict="UNAVAILABLE", is_unavailable=True)

        url = f"{settings.signal_validator_url.rstrip('/')}/validate/signal"
        headers = {
            "X-API-Key": settings.signal_validator_api_key,
            "Content-Type": "application/json",
        }

        logger.info(f"🔍 Signal Validator: calling {url} for {body['pair']} {body['direction']}")

        try:
            import httpx
            async with httpx.AsyncClient(timeout=settings.signal_validator_timeout_seconds) as client:
                response = await client.post(url, json=body, headers=headers)

            if response.status_code != 200:
                try:
                    err_body = response.json()
                except Exception:
                    err_body = response.text
                status = response.status_code
                if status == 401:
                    logger.error(f"🔑 Signal Validator AUTH ERROR (401): Invalid API key. Detail: {err_body}")
                elif status == 402:
                    logger.error(f"💳 Signal Validator BALANCE ERROR (402): Insufficient credits. Detail: {err_body}")
                elif status == 429:
                    logger.warning(f"⏱️ Signal Validator RATE LIMITED (429): {err_body}")
                elif status == 404:
                    logger.error(f"❓ Signal Validator NOT FOUND (404): Check validator URL. Detail: {err_body}")
                else:
                    logger.warning(f"⚠️ Signal Validator: HTTP {status} — {err_body}")
                return SignalValidationResult(verdict="UNAVAILABLE", is_unavailable=True)

            try:
                data = response.json()
            except Exception as json_err:
                logger.error(
                    f"❌ Signal Validator: failed to parse JSON response: {json_err} | raw: {response.text[:500]}"
                )
                return SignalValidationResult(verdict="UNAVAILABLE", is_unavailable=True)
            regime = data.get("regime") or {}
            result = SignalValidationResult(
                verdict=data.get("verdict", "UNAVAILABLE"),
                score=data.get("score"),
                trade_type=data.get("trade_type"),
                rr_tp1=data.get("rr_tp1"),
                rr_tp2=data.get("rr_tp2"),
                sl_pips=data.get("sl_pips"),
                atr=data.get("atr"),
                regime_label=regime.get("label") if isinstance(regime, dict) else None,
                zone=data.get("zone"),
                issues=data.get("issues") or [],
                warnings=data.get("warnings") or [],
                is_unavailable=False,
            )

            logger.info(
                f"✅ Signal Validator response: verdict={result.verdict} score={result.score} "
                f"trade_type={result.trade_type}"
            )
            if result.issues:
                logger.warning(f"   Issues: {result.issues}")
            if result.warnings:
                logger.warning(f"   Warnings: {result.warnings}")

            return self._apply_policy(result)

        except httpx.TimeoutException:
            logger.warning(
                f"⏱️ Signal Validator: request timed out after {settings.signal_validator_timeout_seconds}s "
                f"— proceeding without validation (fail-open)"
            )
            return SignalValidationResult(verdict="UNAVAILABLE", is_unavailable=True)

        except httpx.ConnectError as e:
            logger.warning(
                f"🔌 Signal Validator: cannot reach {settings.signal_validator_url} ({e}) "
                f"— proceeding without validation (fail-open)"
            )
            return SignalValidationResult(verdict="UNAVAILABLE", is_unavailable=True)

        except Exception:
            logger.error("❌ Signal Validator: unexpected error — proceeding without validation", exc_info=True)
            return SignalValidationResult(verdict="UNAVAILABLE", is_unavailable=True)


# Singleton
signal_validator_service = SignalValidatorService()
