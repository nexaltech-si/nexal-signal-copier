import { NextRequest, NextResponse } from 'next/server'
import { validateApiKey, recordUsage, clientIp } from '@/lib/apiKeys'

export const dynamic = 'force-dynamic'

const PYTHON_API_URL = process.env.PYTHON_API_URL || 'http://localhost:8001'
const ENDPOINT = '/api/ea/signals'

/**
 * Public, per-customer-key-protected proxy for the MT5 mirror-execution feed.
 *
 * Consumed by mt5/EA/NexalSignalMirrorEA.mq5, which DOES place real orders —
 * on OTHER ("mirror") MT5 accounts, mirroring trades your primary account
 * already has running. This route itself only ever reads from the backend
 * and returns that data verbatim; it has no way to place an order on its
 * own. The order placement happens on whichever machine holds a valid key
 * and runs the EA — so treat every issued key as trade-placement
 * credentials, not just a read key, when deciding who gets one.
 *
 * KEY MODEL (replaces the old single static EA_PUBLIC_API_KEY)
 * -----------------------------------------------------------------
 * Keys are issued, tracked, expired and revoked from the admin-only
 * /settings/api-keys page (backed by the ApiKey/ApiKeyUsage tables — see
 * src/lib/apiKeys.ts). Each request here is looked up by key hash, checked
 * for revocation/expiry, and logged (ip, user agent, status) against that
 * specific key — that's what powers the connection/usage stats in the admin
 * page. A key that fails validation is rejected before this route ever
 * talks to the backend.
 *
 * The Python backend (trading-bot:8001) is only bound to 127.0.0.1 on the
 * host and never exposed to the internet — only this dashboard is, via
 * Traefik. This route is the ONLY thing that talks to the backend for this
 * feed, using the backend's own separate internal secret (EA_API_KEY, never
 * sent to or accepted from the internet) — a customer's key never reaches
 * the backend at all.
 *
 * This route is exempted from Clerk auth in middleware.ts (it must be
 * reachable by a machine that can't complete a browser sign-in); the
 * per-key check below is this route's actual authentication.
 */
export async function GET(request: NextRequest) {
  const ip = clientIp(request)
  const userAgent = request.headers.get('user-agent')
  const providedKey = request.headers.get('x-ea-key')

  const validation = await validateApiKey(providedKey)
  if (!validation.ok) {
    if (validation.reason === 'revoked' || validation.reason === 'expired') {
      // A known key, rejected — log it against that key's own history so the
      // admin can see "someone is still trying this one" in the stats page.
      await recordUsage({
        apiKeyId: validation.apiKey.id,
        ip,
        userAgent,
        endpoint: ENDPOINT,
        status: validation.reason,
      })
    } else {
      // Completely unrecognized key — nothing to attach a log row to (see
      // src/lib/apiKeys.ts). Server console only.
      console.warn(`[ea-signals] rejected unknown key from ${ip ?? 'unknown ip'}`)
    }
    return NextResponse.json({ error: `Key ${validation.reason}` }, { status: 403 })
  }

  const internalKey = process.env.EA_API_KEY
  if (!internalKey) {
    return NextResponse.json(
      { error: 'EA feed disabled: EA_API_KEY is not configured on the backend' },
      { status: 503 }
    )
  }

  const { searchParams } = new URL(request.url)
  const upstream = new URL(`${PYTHON_API_URL}${ENDPOINT}`)
  const hours = searchParams.get('hours')
  const limit = searchParams.get('limit')
  if (hours) upstream.searchParams.set('hours', hours)
  if (limit) upstream.searchParams.set('limit', limit)

  try {
    const response = await fetch(upstream.toString(), {
      method: 'GET',
      headers: { 'X-EA-Key': internalKey },
      cache: 'no-store',
    })

    const body = await response.text()

    await recordUsage({
      apiKeyId: validation.apiKey.id,
      ip,
      userAgent,
      endpoint: ENDPOINT,
      status: 'ok',
    })

    return new NextResponse(body, {
      status: response.status,
      headers: { 'Content-Type': 'text/plain; charset=utf-8' },
    })
  } catch (error) {
    console.error('Error proxying EA signal feed:', error)
    return NextResponse.json(
      { error: error instanceof Error ? error.message : 'Failed to reach backend' },
      { status: 502 }
    )
  }
}
