// Channel rules (src/lib/channelRules.ts). Run: npm test
// Matching cases mirror tests/test_channel_rules.py so the dashboard tester and the bot agree.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  matchesRule, firstMatch, patternError, paramsSummary, cleanParams, patternToRegex, suggestedAction,
} from '../src/lib/channelRules.ts'

const rule = (over = {}) => ({
  id: 'r1', channelId: '-1001', channelTitle: null, ruleName: 'BE now', isEnabled: true, priority: 0,
  replyPattern: '\\bbe now\\b|breakeven', patternType: 'REGEX', isCaseSensitive: false,
  actionType: 'BREAKEVEN', actionParams: {}, conditions: {}, matchCount: 0, successCount: 0,
  lastMatchedAt: null, lastUsedAt: null, description: null,
  createdAt: '2026-10-13T00:00:00Z', updatedAt: '2026-10-13T00:00:00Z',
  ...over,
})

test('pattern matching mirrors the bot', () => {
  const cases = [
    ['Move SL - BE NOW', rule(), true],
    ['bee nowhere', rule(), false],
    ['TP1 Hit +40', rule({ replyPattern: 'tp1 hit', patternType: 'CONTAINS' }), true],
    ['  done  ', rule({ replyPattern: 'DONE', patternType: 'EXACT' }), true],
    ['done +50', rule({ replyPattern: 'DONE', patternType: 'EXACT' }), false],
    ['Close now', rule({ replyPattern: 'close', patternType: 'STARTS_WITH' }), true],
    ['Close now', rule({ replyPattern: 'close', patternType: 'STARTS_WITH', isCaseSensitive: true }), false],
    ['+abc pips', rule({ replyPattern: '\\+\\D+ pips' }), true],
    ['anything', rule({ replyPattern: '(unclosed' }), false],
    // Telegram markdown markers are ignored (real reply: "~ Set **B.E** Now")
    ['~ Set **BE** Now - Booked Max Profits!', rule(), true],
    ['[**BE now**](http://t.me/x)', rule(), true],
  ]
  for (const [text, r, expected] of cases) assert.equal(matchesRule(text, r), expected, `${text} / ${r.replyPattern}`)
})

test('firstMatch follows priority, then age, and skips disabled rules and other channels', () => {
  const rules = [
    rule({ id: 'low', priority: 1, replyPattern: 'be' , createdAt: '2026-10-01T00:00:00Z' }),
    rule({ id: 'high-off', priority: 9, replyPattern: 'be', isEnabled: false }),
    rule({ id: 'other', priority: 50, replyPattern: 'be', channelId: '-1002' }),
    rule({ id: 'mid-new', priority: 5, replyPattern: 'be', createdAt: '2026-10-12T00:00:00Z' }),
    rule({ id: 'mid-old', priority: 5, replyPattern: 'be', createdAt: '2026-10-02T00:00:00Z' }),
  ]
  assert.equal(firstMatch('be now', '-1001', rules).id, 'mid-old')
  assert.equal(firstMatch('nothing', '-1001', rules), null)
})

test('patternError explains bad regexes only', () => {
  assert.equal(patternError('a|b', 'REGEX'), null)
  assert.ok(patternError('(a', 'REGEX'))
  assert.equal(patternError('(a', 'CONTAINS'), null)
  assert.equal(patternError('  ', 'CONTAINS'), 'Pattern is required')
})

test('params are summarised and cleaned to what the action uses', () => {
  assert.equal(paramsSummary('PARTIAL_CLOSE', {}), '50%')
  assert.equal(paramsSummary('MODIFY_SL', { sl_price: 4120.5 }), 'SL 4120.5')
  assert.equal(paramsSummary('MODIFY_SL', {}), 'SL from message')
  assert.equal(paramsSummary('CLOSE', {}), null)
  assert.deepEqual(cleanParams('PARTIAL_CLOSE', { percentage: '30', sl_price: 1 }), { percentage: 30 })
  assert.deepEqual(cleanParams('MODIFY_SL', { sl_price: '' }), {})
})

test('learned patterns become matching regexes', () => {
  const re = new RegExp(patternToRegex('Close at {number}.50 now (+{number} pips)'), 'i')
  assert.ok(re.test('close at 4120.50 now (+1200 pips)'))
  const learned = '**XAUUSD again tp-hit locked +{number} pips** running "Nice Move"! ✅** 🕯Super Shr*...'
  const fromLearned = new RegExp(patternToRegex(learned), 'i')
  assert.ok(matchesRule('**XAUUSD again tp-hit locked +2300 pips** running "Nice Move"! ✅** 🕯Super Shrap Entry', { replyPattern: fromLearned.source, patternType: 'REGEX', isCaseSensitive: false }))
  assert.equal(suggestedAction('CLOSE'), 'CLOSE')
  assert.equal(suggestedAction('MODIFY'), 'AI_MANAGED')
})
