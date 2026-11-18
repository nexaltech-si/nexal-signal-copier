"""
AI Trading Brain
Persistent LLM conversation that reviews signals and manages positions.

When BRAIN_BASE_URL is set (pointing to Hermes Agent), uses the Hermes
/v1/responses API with server-side conversation state. The bot sends only
the new message each turn; Hermes maintains the full conversation history.

For all other providers (OpenAI, DeepSeek) uses /v1/chat/completions with
client-side history — the same approach used by the rest of the bot.
"""
import re
import asyncio
import aiohttp
from typing import Optional, List, Dict
from datetime import datetime
from loguru import logger
from src.utils.tasks import spawn


from src.models.brain_decision import BrainDecision, BrainAction
from ai.llm_client import build_llm_client


class TradingBrain:
    """
    Maintains a session-long conversation with an LLM.

    Hermes mode (BRAIN_BASE_URL set):
      - Uses POST /v1/responses with a named conversation.
      - Hermes stores the full history server-side; we only send the new
        message each turn, exactly like a human typing into a chat window.

    Non-Hermes mode (OpenAI / DeepSeek):
      - Uses POST /v1/chat/completions with client-side history list.
    """

    def __init__(self, config):
        self.config = config

        # Hermes server-side session
        self._conversation_id: Optional[str] = None
        self._instructions: Optional[str] = None
        self._pending_context: List[str] = []   # buffered notifications → sent on next call

        # Non-Hermes client-side history
        self._history: List[Dict] = []

        self._last_position_review: Dict[str, datetime] = {}

        # Lazy OpenAI client for non-Hermes providers
        self._client = None
        self._client_fingerprint = None

        # Emit the "brain unavailable" warning at most once per session
        self._unavailable_warned: bool = False

        if not self.enabled:
            logger.info("🧠 Trading Brain disabled (ENABLE_TRADING_BRAIN=false)")
        elif self._use_hermes_api:
            logger.success(f"🧠 Trading Brain ready → Hermes /v1/responses ({self.model})")
        else:
            client = self._get_client()
            if client:
                logger.success(f"🧠 Trading Brain ready → {self.model}")
            else:
                logger.warning("⚠️ Trading Brain: No LLM client — will APPROVE all signals until configured")

    # ── Live properties (hot-reload safe) ────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return getattr(self.config, 'enable_trading_brain', True)

    @property
    def temperature(self) -> float:
        return getattr(self.config, 'brain_temperature', 0.3)

    @property
    def max_history(self) -> int:
        return getattr(self.config, 'brain_max_history_messages', 60)

    @property
    def position_review_interval(self) -> int:
        return getattr(self.config, 'brain_position_review_interval', 30)

    @property
    def send_images(self) -> bool:
        return getattr(self.config, 'brain_send_images', True)

    @property
    def model(self) -> str:
        explicit = getattr(self.config, 'brain_model', '') or ''
        if explicit:
            return explicit
        provider = getattr(self.config, 'primary_ai_provider', 'openai')
        if hasattr(provider, 'value'):
            provider = provider.value
        if provider == 'deepseek':
            return getattr(self.config, 'deepseek_model', 'deepseek-chat')
        if provider == 'minimax':
            return getattr(self.config, 'minimax_model', 'MiniMax-M2.7')
        if provider == 'qwen':
            return getattr(self.config, 'qwen_model', 'qwen-plus')
        if provider == 'gemini':
            return getattr(self.config, 'gemini_vision_model', 'gemini-2.5-flash')
        if provider == 'openrouter':
            return getattr(self.config, 'openrouter_model', 'qwen/qwen2.5-vl-72b-instruct')
        if provider == 'perplexity':
            return getattr(self.config, 'perplexity_model', 'sonar-pro')
        return getattr(self.config, 'openai_model', 'gpt-4o')

    @property
    def _use_hermes_api(self) -> bool:
        """True when a custom Hermes/Responses endpoint is configured."""
        return bool(getattr(self.config, 'brain_base_url', None))

    # ── Lazy OpenAI client (non-Hermes only) ─────────────────────────────────

    def _connection_fingerprint(self) -> tuple:
        return (
            getattr(self.config, 'openai_api_key', None),
            getattr(self.config, 'deepseek_api_key', None),
            getattr(self.config, 'gemini_api_key', None),
            getattr(self.config, 'openrouter_api_key', None),
            getattr(self.config, 'perplexity_api_key', None),
            getattr(self.config, 'minimax_api_key', None),
            getattr(self.config, 'qwen_api_key', None),
            getattr(self.config, 'primary_ai_provider', 'openai'),
        )

    def _get_client(self):
        fp = self._connection_fingerprint()
        if self._client is not None and fp == self._client_fingerprint:
            return self._client
        self._client = self._build_client()
        self._client_fingerprint = fp
        return self._client

    def _build_client(self):
        return build_llm_client(self.config)

    # ── Session lifecycle ────────────────────────────────────────────────────

    def start_session(self, account_info=None):
        """
        Build the system prompt and start the conversation.
        Must be called once after the trading provider connects.
        """
        if not self.enabled:
            return

        self._instructions = self._build_system_prompt(account_info)

        if self._use_hermes_api:
            # Unique conversation name per trading session — Hermes chains all
            # messages under this name and stores the history server-side.
            session_key = datetime.now().strftime("%Y%m%d-%H%M")
            self._conversation_id = f"trading-{session_key}"
            self._history = []
            self._pending_context = []
            logger.success(f"🧠 Hermes session started: {self._conversation_id}")
        else:
            # Non-Hermes: history list starts with the system message
            self._history = [{"role": "system", "content": self._instructions}]
            logger.success("🧠 Trading Brain session started")

    def _build_system_prompt(self, account_info) -> str:
        from config import settings
        balance = getattr(account_info, 'balance', 10000.0) if account_info else 10000.0
        equity = getattr(account_info, 'equity', balance) if account_info else balance

        return f"""You are an expert forex and gold trading analyst. You are the autonomous brain of an algorithmic trading bot running a live account.

Your responsibilities:
1. Review every incoming trading signal and decide: APPROVE, REJECT, or MODIFY it.
2. Monitor open positions and recommend management actions when asked.
3. Maintain awareness of everything that happened this trading session.

CURRENT ACCOUNT:
- Balance: ${balance:,.2f} | Equity: ${equity:,.2f}
- Max risk per trade: {settings.max_risk_per_trade_percent}%
- Max open positions: {settings.max_open_positions}
- Daily drawdown limit: {settings.daily_drawdown_limit_percent}%
- Lot limits: {settings.min_lot_size} – {settings.max_lot_size}

RULES:
- Never risk more than {settings.max_risk_per_trade_percent}% of account per trade
- Avoid entering within 15 minutes of high-impact news
- If SL/TP placement is invalid or risk is excessive, MODIFY or REJECT
- Keep reasoning concise — 1-3 sentences before the decision block

SIGNAL REVIEW — always end your response with exactly one of:
DECISION: APPROVE
or
DECISION: REJECT
or
DECISION: MODIFY
entry: <price> | sl: <price> | tp1: <price> | lot: <size>

POSITION REVIEW — always end your response with ACTION lines:
ACTION: HOLD
or one or more of:
ACTION: MODIFY_SL value=<price>
ACTION: MODIFY_TP value=<price>
ACTION: PARTIAL_CLOSE percentage=<number>
ACTION: CLOSE"""

    # ── Signal review ────────────────────────────────────────────────────────

    async def review_signal(
        self,
        signal,
        account_info=None,
        news_events: Optional[List[Dict]] = None
    ) -> BrainDecision:
        """
        Review a TradingSignal before execution.
        When the brain is unavailable or errors, the fallback behavior is governed
        by BRAIN_UNAVAILABLE_ACTION: APPROVE (default), REJECT, APPROVAL
        (route the signal through the manual approval queue), or PIPELINE
        (skip the brain entirely and let the rest of the configured pipeline —
        risk manager, signal validator, approval rules — decide, exactly as if
        the brain were disabled).
        """
        if not self._ready():
            self._warn_unavailable_once()
            return self._unavailable_decision("Brain unavailable")
        try:
            msg = self._format_signal_message(signal, account_info, news_events)
            image_data = getattr(signal, 'image_data', None) if self.send_images else None
            response = await self._call_brain(msg, image_data=image_data)
            decision = self._parse_signal_decision(response, signal)
            logger.info(f"🧠 Signal decision: {decision.verdict} — {decision.reason[:100]}")
            return decision
        except Exception as e:
            err_desc = str(e) or type(e).__name__
            logger.error(f"❌ Trading Brain signal review error: {err_desc}", exc_info=True)
            return self._unavailable_decision(f"Brain error: {err_desc}")

    @property
    def unavailable_action(self) -> str:
        action = str(getattr(self.config, 'brain_unavailable_action', 'APPROVE') or 'APPROVE').upper()
        return action if action in ('APPROVE', 'REJECT', 'APPROVAL', 'PIPELINE') else 'APPROVE'

    def _unavailable_decision(self, cause: str) -> BrainDecision:
        """Build the fallback decision when the brain can't review a signal."""
        action = self.unavailable_action
        if action == 'REJECT':
            return BrainDecision(
                verdict="REJECT",
                reason=f"{cause} — rejected (BRAIN_UNAVAILABLE_ACTION=REJECT)"
            )
        if action == 'APPROVAL':
            return BrainDecision(
                verdict="APPROVE",
                reason=f"{cause} — routed to manual approval (BRAIN_UNAVAILABLE_ACTION=APPROVAL)",
                force_approval=True,
            )
        if action == 'PIPELINE':
            return BrainDecision(
                verdict="APPROVE",
                reason=f"{cause} — using pipeline as configured (BRAIN_UNAVAILABLE_ACTION=PIPELINE)",
            )
        return BrainDecision(verdict="APPROVE", reason=f"{cause} — fallback approval")

    def _warn_unavailable_once(self) -> None:
        """Loudly surface brain unavailability — log + one-time Telegram notification."""
        if self._unavailable_warned:
            return
        self._unavailable_warned = True
        action = self.unavailable_action
        logger.warning(
            f"⚠️ Trading Brain is unavailable — fallback action: {action}. "
            "Check ENABLE_TRADING_BRAIN, BRAIN_BASE_URL, and your AI provider keys."
        )
        try:
            from src.integrations.telegram.unified_sender import notification_sender
            spawn(notification_sender.send_message(
                "⚠️ <b>Trading Brain unavailable</b>\n"
                f"Signals are handled with fallback action: <b>{action}</b>\n"
                "Check ENABLE_TRADING_BRAIN, BRAIN_BASE_URL and AI provider keys, "
                "or set BRAIN_UNAVAILABLE_ACTION to REJECT/APPROVAL for stricter handling, "
                "or PIPELINE to defer to your configured pipeline as-is.",
                category='errors'
            ))
        except Exception as e:
            logger.debug(f"Could not send brain-unavailable notification: {e}")

    # ── Position review ──────────────────────────────────────────────────────

    async def review_position(
        self,
        trade: Dict,
        position: Dict,
        account_info=None,
        news_events: Optional[List[Dict]] = None
    ) -> List[BrainAction]:
        """Review an open position. Rate-limited to once per brain_position_review_interval."""
        if not self._ready():
            return [BrainAction(action="HOLD", reason="Brain unavailable")]

        position_id = position.get('id', '')
        last = self._last_position_review.get(position_id)
        if last and (datetime.now() - last).total_seconds() < self.position_review_interval:
            return []

        try:
            msg = self._format_position_message(trade, position, account_info, news_events)
            response = await self._call_brain(msg)
            actions = self._parse_position_actions(response)
            self._last_position_review[position_id] = datetime.now()

            summary = ", ".join(a.action for a in actions)
            logger.info(f"🧠 Position {position_id[:8]}... → {summary}")
            return actions
        except Exception as e:
            logger.error(f"❌ Trading Brain position review error: {e}", exc_info=True)
            return []

    # ── Conversation notifications ───────────────────────────────────────────

    def notify_trade_executed(self, signal, result):
        """Log trade execution into the conversation so the brain remembers it."""
        if not self.enabled:
            return
        symbol = getattr(signal, 'symbol', '?') or '?'
        order_type = getattr(getattr(signal, 'order_type', None), 'value', '?')
        lot = getattr(signal, 'lot_size', '?')
        entry = getattr(result, 'entry_price', None) or getattr(signal, 'entry_price', 'market')
        pos_id = getattr(result, 'position_id', None) or 'pending'
        self._queue_context(
            f"✅ Trade executed: {symbol} {order_type} {lot} lots @ {entry} | Position: {pos_id}"
        )

    def notify_trade_rejected(self, signal, reason: str):
        """Log a non-brain rejection (risk, news, drawdown) into the conversation."""
        if not self.enabled:
            return
        symbol = getattr(signal, 'symbol', '?') or '?'
        self._queue_context(f"❌ Trade rejected for {symbol}: {reason}")

    def notify_position_closed(self, position_id: str, symbol: str, profit: float, profit_pips: float):
        """Log position closure so the brain tracks session P&L."""
        if not self.enabled:
            return
        direction = "profit" if profit >= 0 else "loss"
        self._queue_context(
            f"🔒 Closed: {symbol} {position_id[:8]}... "
            f"${profit:+.2f} ({profit_pips:+.1f} pips) — {direction}"
        )
        self._last_position_review.pop(position_id, None)

    async def handle_reply(
        self,
        reply_text: str,
        context: Optional[str] = None,
        image_data: Optional[bytes] = None,
    ) -> str:
        """
        Feed a Telegram reply into the brain's conversation.
        The brain already knows full session context, so it can resolve
        'close half' or 'move SL to breakeven' without keyword matching.
        Any image attached to the reply (e.g. a profit screenshot) is sent
        along with the text, same as for new signals.
        """
        if not self._ready():
            return ""
        try:
            user_msg = f"{context}\n\nUser reply: {reply_text}" if context else f"User reply: {reply_text}"
            img = image_data if self.send_images else None
            return await self._call_brain(user_msg, image_data=img)
        except Exception as e:
            logger.error(f"❌ Trading Brain reply error: {e}", exc_info=True)
            return ""

    # ── Internal routing ─────────────────────────────────────────────────────

    def _ready(self) -> bool:
        if not self.enabled:
            return False
        if self._use_hermes_api:
            return self._conversation_id is not None
        return self._get_client() is not None and len(self._history) > 0

    def _queue_context(self, msg: str):
        """
        Buffer a notification event so it reaches the brain on the next call.

        Hermes: events are prepended to the next /v1/responses input — they
        appear in the server-side conversation without needing a separate request.

        Non-Hermes: events are appended directly to the client-side history list.
        """
        if self._use_hermes_api:
            self._pending_context.append(msg)
        else:
            self._history.append({"role": "user", "content": msg})

    def _image_data_url(self, image_data: bytes) -> str:
        import base64
        b64 = base64.b64encode(image_data).decode('utf-8')
        return f"data:image/jpeg;base64,{b64}"

    async def _call_brain(self, user_message: str, image_data: Optional[bytes] = None) -> str:
        """
        Route to Hermes /v1/responses or /v1/chat/completions with retry.

        When image_data is provided, it's sent alongside the text as a vision
        content block, so the brain sees the same chart/screenshot a human
        reviewer would.

        Retries up to 3 times on transient errors (rate-limit 429, timeouts,
        connection drops).  Permanent errors (401, 402, 404) raise immediately.
        """
        max_attempts = 3
        last_exc: Exception = RuntimeError("unreachable")

        for attempt in range(max_attempts):
            try:
                if self._use_hermes_api:
                    return await self._call_hermes_responses(user_message, image_data=image_data)
                else:
                    # For chat completions we mutate history before the call.
                    # Only append the user message on the first attempt; on retries
                    # it is already the last entry in history.
                    if attempt == 0:
                        if image_data:
                            content = [
                                {"type": "text", "text": user_message},
                                {"type": "image_url", "image_url": {"url": self._image_data_url(image_data)}},
                            ]
                        else:
                            content = user_message
                        self._history.append({"role": "user", "content": content})
                        self._trim_history()
                    response = await self._call_chat_completions()
                    self._history.append({"role": "assistant", "content": response})
                    return response

            except Exception as exc:
                last_exc = exc
                err_str = str(exc)
                is_retryable = (
                    '429' in err_str
                    or 'rate' in err_str.lower()
                    or 'timeout' in err_str.lower()
                    or 'timed out' in err_str.lower()
                    or 'connection' in err_str.lower()
                    or 'temporarily' in err_str.lower()
                )
                if not is_retryable or attempt == max_attempts - 1:
                    # Non-retryable or exhausted — roll back pending user message
                    # from non-Hermes history so the next real call isn't confused.
                    if not self._use_hermes_api and self._history and self._history[-1].get("role") == "user":
                        self._history.pop()
                    raise

                wait = 2 ** attempt  # 1 s, 2 s
                logger.warning(
                    f"⚠️ Brain API transient error (attempt {attempt + 1}/{max_attempts}): "
                    f"{exc} — retrying in {wait}s"
                )
                await asyncio.sleep(wait)

        raise last_exc  # unreachable but satisfies type checker

    async def _call_hermes_responses(self, user_message: str, image_data: Optional[bytes] = None) -> str:
        """
        POST to Hermes /v1/responses.

        Hermes stores the full conversation server-side under self._conversation_id.
        We only send the new message (plus any buffered context events). When an
        image is attached, `input` switches from a plain string to the Responses
        API's multimodal message-array form (input_text + input_image blocks).
        """
        # Prepend any queued notifications (trade executed, closed, etc.)
        if self._pending_context:
            prefix = "\n".join(self._pending_context) + "\n\n"
            full_input_text = prefix + user_message
            self._pending_context.clear()
        else:
            full_input_text = user_message

        if image_data:
            full_input = [{
                "role": "user",
                "content": [
                    {"type": "input_text", "text": full_input_text},
                    {"type": "input_image", "image_url": self._image_data_url(image_data)},
                ],
            }]
        else:
            full_input = full_input_text

        # Normalise base URL: strip trailing /v1 since we build the full path
        base_url = (getattr(self.config, 'brain_base_url', '') or '').rstrip('/')
        if base_url.endswith('/v1'):
            base_url = base_url[:-3]

        api_key = (
            getattr(self.config, 'brain_api_key', None) or
            getattr(self.config, 'openai_api_key', None) or
            'hermes'
        )

        payload = {
            "model": self.model,
            "input": full_input,
            "instructions": self._instructions,
            "store": True,
            "conversation": self._conversation_id,
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        timeout = aiohttp.ClientTimeout(total=600)  # 10 min — no more 2-min cut-offs
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{base_url}/v1/responses",
                json=payload,
                headers=headers,
            ) as resp:
                if resp.status >= 400:
                    try:
                        err_body = await resp.json()
                    except Exception:
                        err_body = await resp.text()
                    status = resp.status
                    if status == 401:
                        logger.error(f"🔑 Hermes/Brain AUTH ERROR (401): Invalid API key. Detail: {err_body}")
                    elif status == 402:
                        logger.error(f"💳 Hermes/Brain BALANCE ERROR (402): Insufficient credits. Detail: {err_body}")
                    elif status == 429:
                        logger.warning(f"⏱️ Hermes/Brain RATE LIMITED (429): {err_body}")
                    elif status == 404:
                        logger.error(f"❓ Hermes/Brain NOT FOUND (404): Model or endpoint missing. Detail: {err_body}")
                    else:
                        logger.error(f"🌐 Hermes/Brain API ERROR (HTTP {status}): {err_body}")
                    resp.raise_for_status()

                try:
                    data = await resp.json()
                except Exception as json_err:
                    raw = await resp.text()
                    logger.error(f"❌ Hermes/Brain: failed to parse JSON response: {json_err} | raw: {raw[:500]}")
                    raise

                try:
                    from ai.cost_tracker import cost_tracker
                    usage = data.get('usage', {}) or {}
                    prompt_tokens = usage.get('input_tokens') or usage.get('prompt_tokens') or 0
                    completion_tokens = usage.get('output_tokens') or usage.get('completion_tokens') or 0
                    if prompt_tokens or completion_tokens:
                        cost_tracker.record(
                            caller='brain_hermes',
                            provider='hermes',
                            model=self.model,
                            prompt_tokens=prompt_tokens,
                            completion_tokens=completion_tokens,
                        )
                except Exception as _exc:
                    logger.debug(f"Suppressed exception: {_exc!r}")

                return self._extract_responses_text(data)

    def _extract_responses_text(self, data: dict) -> str:
        """
        Extract assistant text from a Hermes /v1/responses response object.

        When Hermes used MCP tools autonomously, the output array also contains
        function_call / function_call_output items.  We build a clean action
        summary and append it to the text so callers (parsers, loggers) can see
        exactly what the brain did without having to re-inspect the raw payload.
        """
        text = ""
        for item in data.get("output", []):
            if item.get("type") == "message":
                for block in item.get("content", []):
                    if block.get("type") == "output_text":
                        text = block["text"]
                        break

        if not text:
            text = data.get("output_text", "") or ""

        mcp_summary = self._build_mcp_action_summary(data.get("output", []))
        if mcp_summary:
            separator = "\n\n" if text else ""
            text = text + separator + mcp_summary

        return text or str(data)

    def _build_mcp_action_summary(self, output_items: list) -> str:
        """
        Parse function_call / function_call_output pairs from a Hermes output array
        and return a human-readable summary of every MCP tool the brain invoked.

        Format per tool call:
          🔧 Brain called `tool_name`(arg1=v1, ...) → <result>
        """
        if not output_items:
            return ""

        # Index outputs by call_id so we can pair them with their calls
        outputs_by_call_id: Dict[str, str] = {}
        for item in output_items:
            if item.get("type") in ("function_call_output", "tool_result"):
                cid = item.get("call_id") or item.get("id", "")
                raw_out = item.get("output") or item.get("content") or ""
                if isinstance(raw_out, list):
                    # content-block list → join text blocks
                    raw_out = " ".join(
                        b.get("text", "") for b in raw_out if isinstance(b, dict)
                    )
                outputs_by_call_id[cid] = str(raw_out)[:200]

        lines = []
        for item in output_items:
            if item.get("type") not in ("function_call", "tool_use"):
                continue
            name = item.get("name") or item.get("tool_name") or "unknown_tool"
            call_id = item.get("call_id") or item.get("id", "")

            # Format arguments
            raw_args = item.get("arguments") or item.get("input") or {}
            if isinstance(raw_args, str):
                try:
                    import json as _json
                    raw_args = _json.loads(raw_args)
                except Exception:
                    raw_args = {"raw": raw_args}
            if isinstance(raw_args, dict):
                args_str = ", ".join(f"{k}={v}" for k, v in raw_args.items())
            else:
                args_str = str(raw_args)

            result = outputs_by_call_id.get(call_id, "")
            result_str = f" → {result}" if result else ""
            lines.append(f"🔧 Brain called `{name}`({args_str}){result_str}")

        if not lines:
            return ""

        return "— MCP actions taken —\n" + "\n".join(lines)

    async def _call_chat_completions(self) -> str:
        """Call /v1/chat/completions with the full client-side history (non-Hermes)."""
        client = self._get_client()
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: client.chat.completions.create(
                model=self.model,
                messages=self._history,
                temperature=self.temperature,
                timeout=300.0,  # 5 min — no more 45s cut-offs
            )
        )
        try:
            from ai.cost_tracker import cost_tracker
            usage = getattr(response, 'usage', None)
            if usage:
                provider = str(getattr(self.config, 'primary_ai_provider', 'openai')).lower()
                cost_tracker.record(
                    caller='brain_review',
                    provider=provider,
                    model=self.model,
                    prompt_tokens=getattr(usage, 'prompt_tokens', 0) or 0,
                    completion_tokens=getattr(usage, 'completion_tokens', 0) or 0,
                )
        except Exception as _exc:
            logger.debug(f"Suppressed exception: {_exc!r}")
        from ai.llm_client import extract_content
        return extract_content(response)

    def _trim_history(self):
        if len(self._history) > self.max_history + 1:
            system = self._history[0]
            self._history = [system] + self._history[-(self.max_history):]

    # ── Message formatters ───────────────────────────────────────────────────

    def _format_signal_message(self, signal, account_info, news_events) -> str:
        lines = ["🔔 NEW SIGNAL"]
        channel = getattr(signal, 'channel_name', None)
        if channel:
            lines.append(f"Channel: {channel}")
        raw = getattr(signal, 'raw_message', None)
        if raw:
            lines.append(f'Message: "{raw}"')
        if self.send_images and getattr(signal, 'image_data', None):
            lines.append("(Chart/screenshot image attached below — inspect it as part of your review)")

        details = []
        if getattr(signal, 'symbol', None):
            details.append(f"Symbol: {signal.symbol}")
        order_type = getattr(getattr(signal, 'order_type', None), 'value', None)
        if order_type:
            details.append(f"Direction: {order_type}")
        if getattr(signal, 'entry_price', None):
            details.append(f"Entry: {signal.entry_price}")
        elif getattr(signal, 'entry_range_min', None) and getattr(signal, 'entry_range_max', None):
            details.append(f"Entry range: {signal.entry_range_min}–{signal.entry_range_max}")
        if getattr(signal, 'stop_loss', None):
            details.append(f"SL: {signal.stop_loss}")
        tp = getattr(signal, 'take_profit', None) or []
        if tp:
            details.append(f"TP: {' / '.join(str(t) for t in tp)}")
        if getattr(signal, 'lot_size', None):
            details.append(f"Lot: {signal.lot_size}")
        if details:
            lines.append("Extracted: " + " | ".join(details))

        if account_info:
            balance = getattr(account_info, 'balance', '?')
            equity = getattr(account_info, 'equity', '?')
            open_pos = getattr(account_info, 'open_positions', '?')
            lines.append(f"Account: ${balance:,.2f} balance | ${equity:,.2f} equity | {open_pos} open positions")

        if news_events:
            news_lines = []
            for ev in news_events[:5]:
                name = ev.get('name') or ev.get('event', '?')
                currency = ev.get('currency', '?')
                impact = ev.get('impact', '?')
                minutes = ev.get('minutes_away', '?')
                news_lines.append(f"  ⚠️ {name} ({currency}) [{impact}] — {minutes} min")
            if news_lines:
                lines.append("Upcoming news:\n" + "\n".join(news_lines))

        lines.append("→ What's your decision?")
        return "\n".join(lines)

    def _format_position_message(self, trade: Dict, position: Dict, account_info, news_events) -> str:
        symbol = position.get('symbol') or trade.get('symbol', '?')
        pos_type = 'BUY' if position.get('type') == 'POSITION_TYPE_BUY' else 'SELL'
        volume = position.get('volume') or trade.get('volume', '?')
        open_price = position.get('openPrice') or trade.get('entryPrice', '?')
        current_price = position.get('currentPrice', '?')
        sl = position.get('stopLoss') or trade.get('stopLoss', '?')
        tp = position.get('takeProfit') or trade.get('takeProfit', '?')
        profit = position.get('profit', 0)

        from src.utils.pip_utils import get_pip_size
        pip_val = get_pip_size(symbol)
        try:
            pips = (float(current_price) - float(open_price)) / pip_val
            if pos_type == 'SELL':
                pips = -pips
        except Exception:
            pips = 0

        lines = [
            f"📊 POSITION UPDATE — {symbol} {pos_type} {volume} lots",
            f"Entry: {open_price} → Now: {current_price} ({pips:+.1f} pips, ${profit:+.2f})",
            f"SL: {sl} | TP: {tp}",
        ]

        if news_events:
            news_lines = []
            for ev in news_events[:3]:
                name = ev.get('name') or ev.get('event', '?')
                currency = ev.get('currency', '?')
                impact = ev.get('impact', '?')
                minutes = ev.get('minutes_away', '?')
                news_lines.append(f"  ⚠️ {name} ({currency}) [{impact}] — {minutes} min")
            if news_lines:
                lines.append("Upcoming news:\n" + "\n".join(news_lines))

        lines.append("→ Any action needed?")
        return "\n".join(lines)

    # ── Response parsers ─────────────────────────────────────────────────────

    def _parse_signal_decision(self, response: str, signal) -> BrainDecision:
        upper = response.upper()

        if 'DECISION: REJECT' in upper:
            verdict = 'REJECT'
        elif 'DECISION: MODIFY' in upper:
            verdict = 'MODIFY'
        elif 'DECISION: APPROVE' in upper:
            verdict = 'APPROVE'
        else:
            # Structured DECISION: block missing — default to APPROVE.
            # We do NOT scan for loose words like REJECT/AVOID/SKIP because normal
            # market-analysis commentary triggers false rejections (e.g. "avoid adding
            # risk here", "skip this session"). Log the raw response for debugging.
            logger.warning(
                f"⚠️ Brain response missing DECISION: block — defaulting to APPROVE. "
                f"Raw response: {response[:300]!r}"
            )
            verdict = 'APPROVE'

        parts = re.split(r'DECISION:', response, maxsplit=1, flags=re.IGNORECASE)
        reason = parts[0].strip()[:2000] if len(parts) > 1 else response.strip()[:2000]
        if not reason:
            reason = "No reason provided"

        if verdict == 'MODIFY':
            entry = self._extract_num(response, r'entry')
            sl = self._extract_num(response, r'sl')
            lot = self._extract_num(response, r'lot')

            modified_tp = []
            for pat in (r'tp1', r'tp2', r'tp3', r'tp4', r'tp'):
                v = self._extract_num(response, pat)
                if v is not None and v not in modified_tp:
                    modified_tp.append(v)

            original_tp = getattr(signal, 'take_profit', None) or []
            return BrainDecision(
                verdict=verdict,
                reason=reason,
                modified_entry=entry if entry is not None else getattr(signal, 'entry_price', None),
                modified_sl=sl if sl is not None else getattr(signal, 'stop_loss', None),
                modified_tp=modified_tp if modified_tp else (original_tp or None),
                modified_lot=lot if lot is not None else getattr(signal, 'lot_size', None),
            )

        return BrainDecision(verdict=verdict, reason=reason)

    def _parse_position_actions(self, response: str) -> List[BrainAction]:
        actions = []
        for line in response.splitlines():
            stripped = line.strip()
            upper = stripped.upper()
            if not upper.startswith('ACTION:'):
                continue
            body = upper[len('ACTION:'):].strip()
            reason = self._extract_inline_reason(stripped)

            if body.startswith('HOLD'):
                actions.append(BrainAction(action='HOLD', reason=reason))
            elif body.startswith('CLOSE'):
                actions.append(BrainAction(action='CLOSE', reason=reason))
            elif body.startswith('MODIFY_SL'):
                val = self._extract_num(stripped, r'value')
                actions.append(BrainAction(action='MODIFY_SL', value=val, reason=reason))
            elif body.startswith('MODIFY_TP'):
                val = self._extract_num(stripped, r'value')
                actions.append(BrainAction(action='MODIFY_TP', value=val, reason=reason))
            elif body.startswith('PARTIAL_CLOSE'):
                pct = self._extract_num(stripped, r'percentage')
                actions.append(BrainAction(action='PARTIAL_CLOSE', percentage=pct or 50, reason=reason))

        return actions if actions else [BrainAction(action='HOLD', reason='No explicit action')]

    def _extract_num(self, text: str, param: str) -> Optional[float]:
        pattern = rf'{param}\s*[=:]\s*([0-9]+\.?[0-9]*)'
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
        return None

    def _extract_inline_reason(self, line: str) -> str:
        m = re.search(r'#\s*(.+)$', line)
        return m.group(1).strip() if m else ""


# Module-level singleton — initialized with settings at import time.
# start_session() must be called after account_info is available.
from config import settings as _settings
trading_brain = TradingBrain(_settings)
