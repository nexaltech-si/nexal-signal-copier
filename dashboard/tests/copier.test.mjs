// Trade Copier view model (src/lib/copier.ts). Run: npm test
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { buildCopierView, connectionOf, syncCell } from '../src/lib/copier.ts'

const NOW = Date.parse('2026-10-13T12:00:00Z')

const master = {
  version: 4,
  generatedAt: '2026-10-13T12:00:00Z',
  master: { login: '1', server: 'Demo', company: null, currency: 'USD', leverage: 100, balance: 1000, equity: 1000, margin: 0, freeMargin: 1000, profit: 0 },
  positions: [
    { ticket: '101', symbol: 'EURUSD', rawSymbol: 'EURUSD.r', side: 'BUY', volume: 1, openPrice: 1.1, currentPrice: 1.1, sl: 1.09, tp: 1.12, profit: 0, magic: 0, ageMinutes: 1, tradeId: 't1', signalId: 's1', channel: null },
    { ticket: '102', symbol: 'XAUUSD', rawSymbol: 'XAUUSD', side: 'SELL', volume: 1, openPrice: 2400, currentPrice: 2400, sl: 2410, tp: 2380, profit: 0, magic: 0, ageMinutes: 1, tradeId: null, signalId: null, channel: null },
    { ticket: '103', symbol: 'GBPUSD', rawSymbol: 'GBPUSD', side: 'BUY', volume: 1, openPrice: 1.3, currentPrice: 1.3, sl: 1.29, tp: null, profit: 0, magic: 0, ageMinutes: 1, tradeId: null, signalId: null, channel: null },
  ],
  orders: [
    { ticket: '201', symbol: 'USDJPY', rawSymbol: 'USDJPY', type: 'BUY_LIMIT', volume: 1, price: 150, sl: 149, tp: 152, magic: 0, ageMinutes: 1, tradeId: null, signalId: null, channel: null },
  ],
}

const link = (master, state, extra = {}) => ({ master, mirror: `m${master}`, state, symbol: 'X', side: 'BUY', volume: 0.5, price: 1, sl: 1, tp: 1, profit: 2, inSync: true, note: null, ...extra })

function account(links, lastSeenAt = new Date(NOW - 5000)) {
  return {
    id: 'a1', keyLabel: 'Customer', keyActive: true, login: '555', server: 'Mirror', broker: null, name: null,
    currency: 'USD', leverage: 100, eaVersion: '2.00', mode: 'LIVE', halted: false, sizing: 'RISK 1.00%',
    pollSeconds: 5, reportSeconds: 15, balance: 500, equity: 500, margin: 0, freeMargin: 500,
    lastSeenAt, lastIp: null, feedOk: true, pollFailures: 0, lastError: null, events24h: 0,
    links: JSON.stringify(links),
  }
}

test('connection: online within 3x the report interval, stale up to 5 min, then offline', () => {
  assert.equal(connectionOf(new Date(NOW - 40_000), 15, NOW), 'online')
  assert.equal(connectionOf(new Date(NOW - 50_000), 15, NOW), 'stale')
  assert.equal(connectionOf(new Date(NOW - 301_000), 15, NOW), 'offline')
  assert.equal(connectionOf(new Date(NOW - 25_000), null, NOW), 'online')
})

test('per-ticket sync states', () => {
  const view = buildCopierView(master, [account([
    link('101', 'OPEN'),
    link('102', 'OPEN', { inSync: false, note: 'SL differs' }),
    // 103 missing entirely
    link('201', 'PENDING'),
    link('999', 'OPEN'), // master no longer has it -> closing
    link('998', 'DONE'), // finished links don't count as closing
  ])], NOW)

  const a = view.accounts[0]
  assert.equal(a.cells['101'].status, 'SYNCED')
  assert.equal(a.cells['102'].status, 'DRIFT')
  assert.equal(a.cells['102'].note, 'SL differs')
  assert.equal(a.cells['103'].status, 'MISSING')
  assert.equal(a.cells['201'].status, 'SYNCED')
  assert.deepEqual(a.closing.map((l) => l.master), ['999'])
  assert.equal(a.synced, 2)
  assert.equal(a.issues, 3) // drift + missing + closing
  assert.equal(a.mirrorPositions, 3)
  assert.equal(a.links, undefined)
})

test('master filled but mirror pending is awaiting fill; skipped/done/dry pass through', () => {
  assert.equal(syncCell('POSITION', link('1', 'PENDING'), 'online').status, 'AWAITING_FILL')
  assert.equal(syncCell('ORDER', link('1', 'PENDING'), 'online').status, 'SYNCED')
  assert.equal(syncCell('POSITION', link('1', 'SKIPPED', { note: 'stale' }), 'online').status, 'SKIPPED')
  assert.equal(syncCell('POSITION', link('1', 'DONE'), 'online').status, 'CLOSED')
  assert.equal(syncCell('POSITION', link('1', 'DRY'), 'online').status, 'DRY')
  const wait = syncCell('POSITION', link('1', 'WAIT', { note: 'spread too wide' }), 'online')
  assert.deepEqual([wait.status, wait.note], ['MISSING', 'spread too wide'])
})

test('offline accounts report unknown, not missing', () => {
  const view = buildCopierView(master, [account([], new Date(NOW - 3_600_000))], NOW)
  assert.equal(view.accounts[0].connection, 'offline')
  assert.equal(view.accounts[0].cells['101'].status, 'UNKNOWN')
  assert.equal(view.accounts[0].issues, 0)
})

test('no master snapshot: no cells and nothing flagged as closing', () => {
  const view = buildCopierView(null, [account([link('101', 'OPEN')])], NOW)
  assert.deepEqual(view.items, [])
  assert.deepEqual(view.accounts[0].cells, {})
  assert.deepEqual(view.accounts[0].closing, [])
})

test('malformed links JSON is treated as no links', () => {
  const view = buildCopierView(master, [{ ...account([]), links: '{oops' }], NOW)
  assert.equal(view.accounts[0].cells['101'].status, 'MISSING')
})
