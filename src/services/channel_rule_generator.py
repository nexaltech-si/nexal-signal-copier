"""
AI Channel Behavior Rule Generator
Turns a plain-English description into a channel rule draft (dashboard "Generate with AI").
Runs only on that explicit click, through the shared provider chain.
"""
import asyncio
import json
import re
from typing import Optional, Dict, Any
from loguru import logger

VALID_PATTERN_TYPES = ('REGEX', 'CONTAINS', 'EXACT', 'STARTS_WITH')
VALID_ACTION_TYPES = (
    'CLOSE', 'PARTIAL_CLOSE', 'MODIFY_SL', 'MODIFY_TP', 'BREAKEVEN',
    'LOCK_PROFIT', 'CANCEL', 'IGNORE', 'AI_MANAGED',
)

SYSTEM_PROMPT = """You configure reply rules for a Telegram signal-copying bot. When a provider replies to
one of their signals and the reply matches a rule's pattern, the bot treats the rule's action as the
owner's instruction for that trade (IGNORE drops the message entirely).

ACTION TYPES (actionParams in brackets):
- CLOSE: close the trade's positions and pending orders {}
- PARTIAL_CLOSE: close part of the position {"percentage": 50}
- MODIFY_SL: move stop loss to a fixed price {"sl_price": 1.0850}
- MODIFY_TP: move take profit to a fixed price {"tp_price": 1.0900}
- BREAKEVEN: move stop loss to entry {}
- LOCK_PROFIT: move stop loss into profit by N pips {"pips": 20}
- CANCEL: cancel pending orders {}
- IGNORE: the message is commentary/status — do nothing {}
- AI_MANAGED: no fixed action; the AI decides using the description as guidance {}

PATTERN TYPES: REGEX (case-insensitive by default; use alternation for synonyms), CONTAINS, EXACT, STARTS_WITH.
Prefer REGEX with word boundaries (\\b) so short words like "be" do not match inside other words.

CONDITIONS (optional, checked by the AI against live account state), e.g. {"min_profit_pips": 20}.
PRIORITY: 0-100, higher is checked first. Specific rules should outrank broad ones.

Example — "When they say tp hit or take profit hit, close 50%":
{"ruleName": "Close 50% on TP hit", "replyPattern": "\\\\b(tp\\\\s*\\\\d*\\\\s*hit|take profit hit)\\\\b",
 "patternType": "REGEX", "isCaseSensitive": false, "actionType": "PARTIAL_CLOSE",
 "actionParams": {"percentage": 50}, "conditions": {}, "priority": 10,
 "description": "Bank half the position when the provider reports a TP hit"}

Respond ONLY with one JSON object with exactly these keys:
ruleName, replyPattern, patternType, isCaseSensitive, actionType, actionParams, conditions, priority, description"""


class ChannelRuleGenerator:
    """AI-powered channel rule drafting"""

    def available(self) -> bool:
        from config import settings
        from ai.llm_client import first_available_provider
        return first_available_provider(settings, vision=False) is not None

    async def generate_rule(self, description: str) -> Optional[Dict[str, Any]]:
        """Draft a rule from a plain-English description, or None if the AI answer is unusable"""
        from config import settings
        from ai.llm_client import complete_with_fallback, provider_chain, extract_content, max_tokens_for

        def _call(client, model, provider):
            return client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": description},
                ],
                temperature=0.2,
                timeout=30.0,
                max_tokens=max_tokens_for(settings, provider, output_tokens=600),
            )

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: complete_with_fallback(
                settings,
                provider_chain(settings),
                _call,
                validate=lambda r: bool(extract_content(r).strip()),
                caller='rule_generation',
            ),
        )
        rule = self._parse_response(extract_content(response))
        if rule:
            logger.info(f"✅ Generated rule: {rule['ruleName']}")
        return rule

    @staticmethod
    def _parse_response(response: str) -> Optional[Dict[str, Any]]:
        """Validate the AI's JSON into a rule draft"""
        match = re.search(r'\{.*\}', response, re.DOTALL)
        if not match:
            logger.error(f"Rule generator returned no JSON: {response[:200]}")
            return None
        try:
            rule = json.loads(match.group(0))
        except json.JSONDecodeError as e:
            logger.error(f"Rule generator JSON error: {e}")
            return None

        if not rule.get('ruleName') or not rule.get('replyPattern'):
            logger.error("Rule generator omitted ruleName/replyPattern")
            return None
        if rule.get('patternType') not in VALID_PATTERN_TYPES:
            rule['patternType'] = 'REGEX'
        if rule.get('actionType') not in VALID_ACTION_TYPES:
            logger.error(f"Rule generator returned unsupported action: {rule.get('actionType')}")
            return None
        if rule['patternType'] == 'REGEX':
            try:
                re.compile(rule['replyPattern'])
            except re.error as e:
                logger.error(f"Rule generator returned invalid regex {rule['replyPattern']!r}: {e}")
                return None
        rule['isCaseSensitive'] = bool(rule.get('isCaseSensitive', False))
        rule['actionParams'] = rule.get('actionParams') if isinstance(rule.get('actionParams'), dict) else {}
        rule['conditions'] = rule.get('conditions') if isinstance(rule.get('conditions'), dict) else {}
        try:
            rule['priority'] = max(0, min(100, int(rule.get('priority', 0))))
        except (TypeError, ValueError):
            rule['priority'] = 0
        rule['description'] = str(rule.get('description') or '')
        return rule


# Singleton instance
channel_rule_generator = ChannelRuleGenerator()
