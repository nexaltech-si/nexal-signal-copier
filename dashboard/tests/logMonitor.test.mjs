// Log monitor (src/lib/logMonitor.ts). Run: npm test
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { parseLogContent, signatureOf, classify, buildMonitor, isOpen } from '../src/lib/logMonitor.ts'

const NOW = Date.parse('2026-10-13T18:40:00Z')

const LOG = `2026-10-13 18:30:00.100 | ERROR    | 🔑 deepseek AUTH ERROR (401): Invalid or expired API key. Detail: {'message': 'Your api key: ****8b0 is invalid (request_id: 4fe9a1-77)'}
2026-10-13 18:30:00.200 | WARNING  | 🔁 Provider 'deepseek' failed — falling back to next provider
2026-10-13 18:31:00.100 | ERROR    | 🔑 deepseek AUTH ERROR (401): Invalid or expired API key. Detail: {'message': 'Your api key: ****8b0 is invalid (request_id: 9ab3c2-11)'}
2026-10-13 18:32:00.000 | WARNING  | Edited message already processed - ignoring
2026-10-13 18:33:00.000 | WARNING  | Trade 48ecb2e0... position 21779557... NOT FOUND in MT5 - checking lifecycle
2026-10-13 18:34:00.000 | WARNING  | Trade ba32ac6e... position 21783927... NOT FOUND in MT5 - checking lifecycle
2026-10-13 18:35:00.000 | ERROR    | Unhandled exception in handler
Traceback (most recent call last):
  File "main.py", line 1, in <module>
ValueError: boom
2026-10-13 18:36:00.000 | INFO     | ✅ Trade executed
`

test('continuation lines attach to the previous entry', () => {
  const entries = parseLogContent(LOG, 'trading_bot_2026-10-13.log')
  assert.equal(entries.length, 8)
  const crash = entries.find((e) => e.message.startsWith('Unhandled'))
  assert.match(crash.details, /ValueError: boom/)
  assert.equal(crash.file, 'trading_bot_2026-10-13.log')
})

test('signature collapses ids, numbers and request ids', () => {
  const [a, b] = parseLogContent(LOG).filter((e) => e.message.includes('AUTH ERROR'))
  assert.equal(signatureOf(a.message), signatureOf(b.message))
  assert.equal(
    signatureOf('Trade 48ecb2e0... position 21779557... NOT FOUND in MT5'),
    signatureOf('Trade ba32ac6e... position 21783927... NOT FOUND in MT5'),
  )
  assert.notEqual(signatureOf('deepseek failed'), signatureOf('openai failed'))
})

test('rules classify without AI', () => {
  assert.equal(classify('🔑 deepseek AUTH ERROR (401): Invalid or expired API key', 'ERROR').kind, 'action')
  assert.equal(classify('Edited message already processed - ignoring', 'WARNING').kind, 'noise')
  assert.equal(classify('⚠️ Bot is already stopping...', 'WARNING').category, 'bot-lifecycle')
  assert.equal(classify('❌ Failed to extract signal: No trading symbol found (e.g. XAUUSD, EURUSD)', 'WARNING').kind, 'noise')
  assert.equal(classify('Something new and unknown', 'ERROR').kind, 'action')
  assert.equal(classify('Something new and unknown', 'WARNING').kind, 'watch')
})

test('noise never drives status or totals', () => {
  const noiseOnly = parseLogContent('2026-10-13 18:32:00.000 | WARNING  | Edited message already processed - ignoring\n')
  const m = buildMonitor(noiseOnly, { now: NOW })
  assert.equal(m.status, 'ok')
  assert.equal(m.totals.warnings24h, 0)
  assert.equal(m.issues[0].kind, 'noise')
  assert.equal(isOpen(m.issues[0]), false)
})

test('groups issues and goes critical on a recent action item', () => {
  const m = buildMonitor(parseLogContent(LOG), { now: NOW })
  const auth = m.issues.find((i) => i.category === 'ai-provider' && i.kind === 'action')
  assert.equal(auth.count, 2)
  assert.equal(auth.hint.href, '/settings/api-keys')
  assert.equal(auth.hourly[23], 2)
  assert.equal(m.issues.filter((i) => i.category === 'trade-sync').length, 1)
  assert.equal(m.status, 'critical')
  assert.equal(m.issues[0].kind, 'action')
  assert.equal(m.totals.errors24h, 3)
})

test('acknowledged issues stay quiet until they recur', () => {
  const entries = parseLogContent(LOG)
  const sig = signatureOf(entries[0].message)
  const crashSig = signatureOf('Unhandled exception in handler')
  const fallbackSig = signatureOf(entries[1].message)
  const mtSig = signatureOf(entries[4].message)

  const acked = { at: '2026-10-13T18:31:30Z' }
  const all = { [crashSig]: { at: '2026-10-13T18:39:00Z' }, [fallbackSig]: { at: '2026-10-13T18:39:00Z', muted: true }, [mtSig]: { at: '2026-10-13T18:39:00Z' } }

  const m1 = buildMonitor(entries, { now: NOW, acks: { ...all, [sig]: { at: '2026-10-13T18:39:00Z' } } })
  assert.equal(m1.status, 'ok')
  assert.equal(m1.totals.errors24h, 0)

  // Fixed at 18:31:30, but the 18:31 error was before that and nothing came after → still fixed.
  const m2 = buildMonitor(entries, { now: NOW, acks: { ...all, [sig]: acked } })
  assert.equal(m2.issues.find((i) => i.signature === sig).acknowledged, true)

  // Fixed at 18:30:30, then it happened again at 18:31 → reopened.
  const m3 = buildMonitor(entries, { now: NOW, acks: { ...all, [sig]: { at: '2026-10-13T18:30:30Z' } } })
  const auth = m3.issues.find((i) => i.signature === sig)
  assert.equal(auth.acknowledged, false)
  assert.equal(auth.newSinceAck, 1)
  assert.equal(m3.status, 'critical')
})

test('entries older than 24h are ignored', () => {
  const old = parseLogContent('2026-10-11 10:00:00.000 | ERROR    | ancient failure\n')
  const m = buildMonitor(old, { now: NOW })
  assert.equal(m.issues.length, 0)
  assert.equal(m.lastEntryAt, '2026-10-11T10:00:00.000Z')
})

test('MT5 rule needs a failure word', () => {
  assert.equal(classify('MT5 bridge connection failed: refused', 'ERROR').category, 'mt5')
  assert.equal(classify('Failed to place order on MT5', 'ERROR').category, 'mt5')
  assert.equal(classify('Mapped XAUUSD to MT5 symbol XAUUSD.r', 'WARNING').category, 'other')
})

test('a broker rejection is not reported as the bridge being down', () => {
  const title = (m) => classify(m, 'ERROR').hint?.title
  // 2026-10-19: breakeven refused with retcode 10025 was tagged "MT5 bridge problem — check VNC"
  assert.equal(title('MT5 REST API 500 on POST /modify_sl_tp: {"error":"Modify SL/TP failed","mt5_error":"Invalid stops","retcode":10016}'), 'MT5 refused the request')
  assert.equal(title('Failed to move 2207813284 to breakeven: MT5 REST API 500 on /modify_sl_tp: Invalid stops'), 'MT5 refused the request')
  assert.equal(title('MT5 REST API connection error: Cannot connect to host mt5:5001'), 'MT5 bridge problem')
  assert.equal(title('Failed to fetch positions: MT5 REST API 503 on /get_positions: MT5 not connected'), 'MT5 bridge problem')
})

test('rejected internal API calls are a security watch item', () => {
  const c = classify('🚫 Internal API: rejected POST /api/logs/clear from 172.25.0.3', 'WARNING')
  assert.equal(c.category, 'security')
  assert.equal(c.kind, 'watch')
})
