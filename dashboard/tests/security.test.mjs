// Security regression tests (SECURITY_AUDIT.md findings H-03, H-04, M-08).
// Run: npm test   (Node >= 22.18 — imports the .ts helper via type stripping)
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { generateKeyPairSync, createSign } from 'node:crypto'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'
import { isOwner } from '../src/lib/owner.ts'

const require = createRequire(import.meta.url)
const { isOwnerRequest, sessionTokenFromCookies } = require('../vnc-auth.js')
const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')

// ── H-04: owner gate ─────────────────────────────────────────────────────────

test('isOwner only accepts the configured owner and fails closed', () => {
  assert.equal(isOwner('user_owner', 'user_owner'), true)
  assert.equal(isOwner('user_other', 'user_owner'), false)
  assert.equal(isOwner(null, 'user_owner'), false)
  assert.equal(isOwner('', 'user_owner'), false)
  assert.equal(isOwner('user_owner', undefined), false)
  assert.equal(isOwner('user_owner', ''), false)
})

// Routes that authenticate by other means. Adding one here is a security decision.
const PUBLIC_ROUTES = new Set([
  'src/app/api/ea/signals/route.ts',
  'src/app/api/ea/mirror/route.ts',
  'src/app/api/ea/report/route.ts',
])

function routeFiles(dir) {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) return routeFiles(p)
    return name === 'route.ts' ? [p] : []
  })
}

test('every API handler re-checks the owner as its first statement', () => {
  const offenders = []
  let checked = 0
  for (const file of routeFiles(join(ROOT, 'src/app/api'))) {
    const rel = relative(ROOT, file)
    if (PUBLIC_ROUTES.has(rel)) continue
    const src = readFileSync(file, 'utf8')
    for (const m of src.matchAll(/export async function (GET|POST|PUT|PATCH|DELETE)\s*\(/g)) {
      checked++
      // body starts at the first "{" after the parameter list
      let i = m.index + m[0].length, depth = 1
      while (depth) { depth += src[i] === '(' ? 1 : src[i] === ')' ? -1 : 0; i++ }
      const body = src.slice(src.indexOf('{', i) + 1).trimStart()
      const guarded =
        body.startsWith('const denied = await requireOwner()') ||
        body.startsWith('const { authorized, response } = await checkAuthorization()')
      if (!guarded) offenders.push(`${rel} ${m[1]}`)
    }
  }
  assert.ok(checked > 100, `expected >100 handlers, scanned ${checked}`)
  assert.deepEqual(offenders, [], 'handlers without an owner check')
})

test('public EA route authenticates with a per-customer API key', () => {
  const src = readFileSync(join(ROOT, 'src/app/api/ea/signals/route.ts'), 'utf8')
  assert.match(src, /validateApiKey\(/)
  assert.match(src, /if \(!validation\.ok\)/)
})

test('public copier routes authenticate with a per-customer API key first', () => {
  for (const rel of ['src/app/api/ea/mirror/route.ts', 'src/app/api/ea/report/route.ts']) {
    const body = readFileSync(join(ROOT, rel), 'utf8').split(/export async function (?:GET|POST)\s*\([^)]*\)\s*\{/)[1]
    assert.ok(body.trimStart().startsWith('const auth = await authenticateEa(request, ENDPOINT)\n  if (!auth.ok) return auth.response'), rel)
  }
  const helper = readFileSync(join(ROOT, 'src/lib/eaAuth.ts'), 'utf8')
  assert.match(helper, /validateApiKey\(request\.headers\.get\('x-ea-key'\)\)/)
  assert.match(helper, /if \(!validation\.ok\)/)
})

test('middleware public allowlist is exactly the expected set and enforces the owner', () => {
  const src = readFileSync(join(ROOT, 'src/middleware.ts'), 'utf8')
  const list = src.match(/isPublicRoute = createRouteMatcher\(\[([^\]]*)\]\)/)[1]
  const routes = [...list.matchAll(/'([^']+)'/g)].map((m) => m[1]).sort()
  assert.deepEqual(routes, [
    '/api/ea/mirror', '/api/ea/report', '/api/ea/signals', '/manifest.json', '/sign-in(.*)', '/sign-up(.*)',
  ])
  assert.match(src, /if \(!isOwner\(session\.userId\)\)/)
})

// ── H-03: /vnc-proxy session verification ────────────────────────────────────

const { privateKey, publicKey } = generateKeyPairSync('rsa', { modulusLength: 2048 })
const other = generateKeyPairSync('rsa', { modulusLength: 2048 })
const PEM = publicKey.export({ type: 'spki', format: 'pem' })
const ENV = {
  AUTHORIZED_USER_ID: 'user_owner',
  CLERK_JWT_KEY: PEM,
  DASHBOARD_DOMAIN: 'dash.example.test',
}

const b64url = (v) => Buffer.from(typeof v === 'string' ? v : JSON.stringify(v)).toString('base64url')
function jwt(claims = {}, key = privateKey) {
  const now = Math.floor(Date.now() / 1000)
  const payload = { sub: 'user_owner', iat: now - 5, nbf: now - 5, exp: now + 60, azp: 'https://dash.example.test', sid: 'sess_1', ...claims }
  const input = `${b64url({ alg: 'RS256', typ: 'JWT', kid: 'test' })}.${b64url(payload)}`
  return `${input}.${createSign('RSA-SHA256').update(input).sign(key).toString('base64url')}`
}
const req = (cookie) => ({ headers: { cookie } })

test('VNC proxy accepts a valid owner session', async () => {
  assert.equal(await isOwnerRequest(req(`__session=${jwt()}`), { env: ENV }), true)
  assert.equal(await isOwnerRequest(req(`foo=1; __session_abc123=${jwt()}`), { env: ENV }), true)
})

test('VNC proxy rejects the forged cookies the old check accepted', async () => {
  for (const cookie of ['__session=x', '__client_uat=1', '__session=', '', 'a__session=x']) {
    assert.equal(await isOwnerRequest(req(cookie), { env: ENV }), false, cookie)
  }
  assert.equal(await isOwnerRequest({ headers: {} }, { env: ENV }), false)
})

test('VNC proxy rejects non-owner, expired, foreign-signed and wrong-party tokens', async () => {
  const now = Math.floor(Date.now() / 1000)
  const cases = {
    'other user': jwt({ sub: 'user_attacker' }),
    expired: jwt({ exp: now - 3600, iat: now - 7200, nbf: now - 7200 }),
    'signed by another key': jwt({}, other.privateKey),
    'other authorized party': jwt({ azp: 'https://evil.example.test' }),
    'alg none': `${b64url({ alg: 'none', typ: 'JWT' })}.${b64url({ sub: 'user_owner', exp: now + 60 })}.`,
  }
  for (const [name, token] of Object.entries(cases)) {
    assert.equal(await isOwnerRequest(req(`__session=${token}`), { env: ENV }), false, name)
  }
})

test('VNC proxy fails closed without AUTHORIZED_USER_ID', async () => {
  const env = { ...ENV, AUTHORIZED_USER_ID: '' }
  assert.equal(await isOwnerRequest(req(`__session=${jwt()}`), { env }), false)
})

test('session cookie parsing prefers __session and ignores look-alikes', () => {
  assert.equal(sessionTokenFromCookies('x__session=bad; __session=good'), 'good')
  assert.equal(sessionTokenFromCookies('__session_suffix=tok'), 'tok')
  assert.equal(sessionTokenFromCookies('__client_uat=1'), null)
})

// ── H-05: internal API token ─────────────────────────────────────────────────

const { resolveInternalToken, withInternalToken } = await import('../src/lib/internalApi.ts')

test('internal token: explicit value wins, else HMAC of SETTINGS_ENCRYPTION_KEY, else null', () => {
  assert.equal(resolveInternalToken({ INTERNAL_API_TOKEN: 'abc', SETTINGS_ENCRYPTION_KEY: 'k' }), 'abc')
  // Same value as src/api/internal_auth.py derives — keeps Python and TS in sync.
  assert.equal(resolveInternalToken({ SETTINGS_ENCRYPTION_KEY: 'test-key' }),
    '4c329da08d8da817aa949ef00c80a801d729afcc43966111ef0520a38e555b5d')
  assert.equal(resolveInternalToken({}), null)
})

test('internal token is attached only to the bot API origin', async () => {
  const seen = []
  const fake = async (input, init) => { seen.push([String(input instanceof Request ? input.url : input), new Headers(init?.headers)]); return new Response('ok') }
  const f = withInternalToken(fake, 'http://trading-bot:8001', 'secret')

  await f('http://trading-bot:8001/api/settings', { headers: { 'Content-Type': 'application/json' } })
  await f(new URL('http://trading-bot:8001/api/plans'))
  await f(new Request('http://trading-bot:8001/api/x', { headers: { a: '1' } }))
  await f('https://api.deepseek.com/v1/chat')
  await f('http://trading-bot:8002/other-port')
  await f('http://mt5:5001/order')

  const tok = seen.map(([, h]) => h.get('x-internal-token'))
  assert.deepEqual(tok, ['secret', 'secret', 'secret', null, null, null])
  assert.equal(seen[0][1].get('content-type'), 'application/json')
  assert.equal(seen[2][1].get('a'), '1')
})

// ── M-08: untrusted Telegram media ───────────────────────────────────────────

const { safeImageType, imageResponseHeaders } = await import('../src/lib/safeImage.ts')

test('only raster image types are served from Telegram media', () => {
  for (const t of ['image/jpeg', 'image/png', 'image/gif', 'image/webp', 'IMAGE/PNG', 'image/jpeg; charset=binary']) {
    assert.ok(safeImageType(t), t)
  }
  for (const t of ['image/svg+xml', 'text/html', 'application/xhtml+xml', 'image/svg', 'application/octet-stream', '', null]) {
    assert.equal(safeImageType(t), null, String(t))
  }
})

test('image responses are private, nosniff and sandboxed', () => {
  const h = imageResponseHeaders('image/png', 60)
  assert.equal(h['Cache-Control'], 'private, max-age=60')
  assert.equal(h['X-Content-Type-Options'], 'nosniff')
  assert.match(h['Content-Security-Policy'], /sandbox/)
})
