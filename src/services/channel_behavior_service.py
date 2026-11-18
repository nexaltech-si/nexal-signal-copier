"""
Channel Behavior Service
Matches replies against the owner's per-channel rules and learns message patterns.

Rules are created/edited by the dashboard (Prisma, same DB). They are read fresh on
every match so an edit, disable or delete applies to the very next message.

How a matched rule is applied (see message_handler / reply_handler_service):
- IGNORE: the message is dropped before any trade handling.
- Any other action: passed to the reply AI as the owner's instruction for this
  channel (rule_guidance). The AI still sees live account state and decides the
  final action; if no AI provider is reachable the rule's action runs directly
  (rule_command_kwargs).
"""
import re
import hashlib
import json
from typing import Optional, Dict, List
from datetime import datetime
from loguru import logger

from src.core.prisma_client import prisma_client


# Rule actionType -> reply-AI actions that carry it out. AI_MANAGED has no fixed
# action: the AI decides, using the rule's description as guidance.
RULE_ACTIONS: Dict[str, tuple] = {
    'CLOSE': ('close', 'close_all', 'close_by_symbol'),
    'PARTIAL_CLOSE': ('partial_close',),
    'MODIFY_SL': ('modify_sl',),
    'MODIFY_TP': ('modify_tp',),
    'BREAKEVEN': ('breakeven',),
    'LOCK_PROFIT': ('lock_profit',),
    'CANCEL': ('cancel_orders',),
    'AI_MANAGED': (),
}


class ChannelBehaviorService:
    """Per-channel reply rules and message-pattern learning"""

    async def ensure_initialized(self):
        """Ensure Prisma client is initialized before operations"""
        if not prisma_client.is_connected:
            await prisma_client.initialize()

    async def get_rules_for_channel(self, channel_id: str) -> List[Dict]:
        """Enabled rules for a channel, highest priority first"""
        try:
            await self.ensure_initialized()
            rules = await prisma_client.client.channelbehaviorrule.find_many(
                where={'channelId': channel_id, 'isEnabled': True},
                order=[{'priority': 'desc'}, {'createdAt': 'asc'}]
            )
            return [
                {
                    'id': rule.id,
                    'channelId': rule.channelId,
                    'ruleName': rule.ruleName,
                    'priority': rule.priority,
                    'replyPattern': rule.replyPattern,
                    'patternType': rule.patternType,
                    'isCaseSensitive': rule.isCaseSensitive,
                    'actionType': rule.actionType,
                    'actionParams': _load_json(rule.actionParams),
                    'conditions': _load_json(rule.conditions),
                    'description': rule.description,
                }
                for rule in rules
            ]
        except Exception as e:
            logger.error(f"Error getting rules for channel {channel_id}: {e}")
            return []

    async def match_rule(self, channel_id: str, text: str) -> Optional[Dict]:
        """First enabled rule whose pattern matches the text (counts the match)"""
        for rule in await self.get_rules_for_channel(channel_id):
            if self.matches(text, rule):
                await self._bump(rule['id'], {'matchCount': {'increment': 1}, 'lastMatchedAt': datetime.now()})
                logger.info(f"🎯 Channel rule '{rule['ruleName']}' ({rule['actionType']}) matched: {text[:60]}")
                return rule
        return None

    @staticmethod
    def matches(text: str, rule: Dict) -> bool:
        """Does the text match the rule's pattern? Telegram markdown markers are ignored."""
        text = plain_text(text)
        pattern = rule['replyPattern'] or ''
        pattern_type = rule['patternType']
        if not pattern:
            return False
        if pattern_type == 'REGEX':
            flags = 0 if rule['isCaseSensitive'] else re.IGNORECASE
            try:
                return bool(re.search(pattern, text, flags))
            except re.error:
                logger.warning(f"Invalid regex in rule '{rule.get('ruleName')}': {pattern}")
                return False
        if not rule['isCaseSensitive']:
            text, pattern = text.lower(), pattern.lower()
        text, pattern = text.strip(), pattern.strip()
        if pattern_type == 'CONTAINS':
            return pattern in text
        if pattern_type == 'EXACT':
            return text == pattern
        if pattern_type == 'STARTS_WITH':
            return text.startswith(pattern)
        logger.warning(f"Unknown pattern type: {pattern_type}")
        return False

    async def record_success(self, rule_id: str):
        """A matched rule's action was carried out successfully"""
        await self._bump(rule_id, {'successCount': {'increment': 1}, 'lastUsedAt': datetime.now()})

    async def _bump(self, rule_id: str, data: Dict):
        try:
            await self.ensure_initialized()
            await prisma_client.client.channelbehaviorrule.update(where={'id': rule_id}, data=data)
        except Exception as e:
            logger.error(f"Error updating rule stats: {e}")

    @staticmethod
    def rule_guidance(rule: Dict) -> str:
        """The matched rule as an instruction block for the reply AI"""
        actions = RULE_ACTIONS.get(rule['actionType'], ())
        lines = [f"Channel rule set by the account owner (this message matched it): \"{rule['ruleName']}\""]
        lines.append(f"- Owner wants action: {actions[0]}" if actions else "- Owner wants: AI decides, guided by the note below")
        if rule.get('actionParams'):
            lines.append(f"- Parameters: {json.dumps(rule['actionParams'])}")
        if rule.get('conditions'):
            lines.append(f"- Only when: {json.dumps(rule['conditions'])}")
        if rule.get('description'):
            lines.append(f"- Owner's note: {rule['description']}")
        return "\n".join(lines)

    @staticmethod
    def expected_actions(rule: Dict) -> tuple:
        """Reply-AI actions that count as following the rule (empty = any action)"""
        return RULE_ACTIONS.get(rule['actionType'], ())

    @staticmethod
    def rule_command_kwargs(rule: Dict) -> Optional[Dict]:
        """TradeCommand kwargs that carry out the rule directly (used when no AI is reachable)"""
        actions = RULE_ACTIONS.get(rule['actionType'])
        if not actions:
            return None
        params = rule.get('actionParams') or {}
        action = actions[0]
        if action == 'partial_close':
            return {'action': action, 'percentage': float(params.get('percentage') or 50)}
        if action == 'modify_sl':
            price = params.get('sl_price')
            return {'action': action, 'value': float(price)} if price else None
        if action == 'modify_tp':
            price = params.get('tp_price')
            return {'action': action, 'value': float(price)} if price else None
        if action == 'lock_profit':
            return {'action': action, 'value': float(params.get('pips') or 20)}
        return {'action': action}

    async def track_message_pattern(
        self,
        channel_id: str,
        message_text: str,
        message_type: str,
        symbol: Optional[str] = None,
        action: Optional[str] = None
    ):
        """Count a message pattern for the dashboard's analytics and rule suggestions"""
        try:
            await self.ensure_initialized()
            pattern = self._simplify_pattern(message_text)
            await prisma_client.client.channelbehavioranalytics.upsert(
                where={
                    'channelId_messagePattern': {
                        'channelId': channel_id,
                        'messagePattern': pattern
                    }
                },
                data={
                    'create': {
                        'channelId': channel_id,
                        'messageType': message_type,
                        'messagePattern': pattern,
                        'fullTextHash': hashlib.md5(message_text.encode(), usedforsecurity=False).hexdigest(),
                        'symbol': symbol,
                        'action': action,
                        'hasPips': 'pips' in message_text.lower(),
                        'hasPrice': bool(re.search(r'\d+\.\d+', message_text))
                    },
                    'update': {
                        'occurrenceCount': {'increment': 1},
                        'confidenceScore': {'increment': 0.1}
                    }
                }
            )
        except Exception as e:
            logger.error(f"Error tracking message pattern: {e}")

    @staticmethod
    def _simplify_pattern(text: str) -> str:
        """Collapse prices/large numbers so repeats of the same message group together"""
        pattern = re.sub(r'\d{4,}', '{number}', text)
        pattern = re.sub(r'\d+\.\d{4}', '{price}', pattern)
        pattern = re.sub(r'\s+', ' ', pattern).strip()
        if len(pattern) > 200:
            pattern = pattern[:200] + "..."
        return pattern


_MD_LINK = re.compile(r'\[([^\]\n]+)\]\(([^)\s]+)\)')
_MD_MARKER = re.compile(r'```|\*\*|__|~~|\|\||`')


def plain_text(text: str) -> str:
    """Telegram (Telethon) markdown → plain text, so "Set **BE** Now" matches "be now".
    Mirrored by stripMarkers in dashboard/src/lib/channelRules.ts."""
    return _MD_MARKER.sub('', _MD_LINK.sub(r'\1', text or ''))


def _load_json(raw: Optional[str]) -> Dict:
    try:
        value = json.loads(raw) if raw else {}
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


# Singleton instance
channel_behavior_service = ChannelBehaviorService()
