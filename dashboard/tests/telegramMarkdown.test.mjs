// Telegram (Telethon) markdown parser (src/lib/telegramMarkdown.ts). Run: npm test
// Inputs are real messages from the signals / signal_replies / analytics tables.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { parseTelegramMarkdown, telegramPlainText } from '../src/lib/telegramMarkdown.ts'

const spans = (input) => {
  const { text, entities } = parseTelegramMarkdown(input)
  return entities.map((e) => [e.type, text.slice(e.offset, e.offset + e.length), ...(e.url ? [e.url] : [])])
}

test('bold with a space before the closing marker (CommonMark rejects this)', () => {
  const raw = '**GOLD SELL NOW **\n** @ 4167**\n\n**TP : 4150**\n**SL : 4190**'
  assert.equal(telegramPlainText(raw), 'GOLD SELL NOW \n @ 4167\n\nTP : 4150\nSL : 4190')
  assert.deepEqual(spans(raw), [['bold', 'GOLD SELL NOW '], ['bold', ' @ 4167'], ['bold', 'TP : 4150'], ['bold', 'SL : 4190']])
})

test('bold spanning blank lines', () => {
  const raw = '**GOLD BUY NOW \n @ 4184\nMORE BUY @ 4175\n\nTP : 4195\n\nSL : 4168**'
  assert.deepEqual(spans(raw), [['bold', 'GOLD BUY NOW \n @ 4184\nMORE BUY @ 4175\n\nTP : 4195\n\nSL : 4168']])
})

test('__ is italic, links keep their label, formatting inside links', () => {
  assert.deepEqual(spans('**Score:** 78/100\n\n__Signal #161__'), [['bold', 'Score:'], ['italic', 'Signal #161']])
  assert.deepEqual(spans('🎯\n[#Sniper_Entry!](http://t.me/pro4ex)☄️'), [['link', '#Sniper_Entry!', 'http://t.me/pro4ex']])
  assert.deepEqual(spans('[**big**](https://x.y)'), [['link', 'big', 'https://x.y'], ['bold', 'big']])
})

test('code is literal; nested bold inside italic', () => {
  assert.deepEqual(spans('```The first public signal completed 100 pips.```'), [['pre', 'The first public signal completed 100 pips.']])
  assert.deepEqual(spans('`a**b**`'), [['code', 'a**b**']])
  assert.deepEqual(spans('__x **y** z__'), [['italic', 'x y z'], ['bold', 'y']])
})

test('unpaired and truncated markers never leak as stars', () => {
  assert.equal(telegramPlainText('✅**GOLD SIGNAL*...'), '✅GOLD SIGNAL...')
  assert.equal(telegramPlainText('**done ** ~ *...'), 'done  ~ ...')
  assert.equal(telegramPlainText('No trade*'), 'No trade*') // a real single star stays
  assert.equal(telegramPlainText('**open bold never closed'), 'open bold never closed')
})
