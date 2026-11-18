import { NextRequest, NextResponse } from 'next/server'
import { validateApiKey, recordUsage, clientIp } from '@/lib/apiKeys'

export type EaAuth =
  | { ok: true; apiKey: { id: string; label: string }; ip: string | null; userAgent: string | null }
  | { ok: false; response: NextResponse }

/**
 * Per-customer X-EA-Key check for the public copier routes (/api/ea/mirror,
 * /api/ea/report) — same rules as /api/ea/signals: unknown keys go to the
 * server console only, revoked/expired ones are logged against their key.
 */
export async function authenticateEa(request: NextRequest, endpoint: string): Promise<EaAuth> {
  const ip = clientIp(request)
  const userAgent = request.headers.get('user-agent')
  const validation = await validateApiKey(request.headers.get('x-ea-key'))

  if (!validation.ok) {
    if (validation.reason === 'revoked' || validation.reason === 'expired') {
      await recordUsage({ apiKeyId: validation.apiKey.id, ip, userAgent, endpoint, status: validation.reason })
    } else {
      console.warn(`[ea] ${endpoint}: rejected unknown key from ${ip ?? 'unknown ip'}`)
    }
    return { ok: false, response: NextResponse.json({ error: `Key ${validation.reason}` }, { status: 403 }) }
  }

  await recordUsage({ apiKeyId: validation.apiKey.id, ip, userAgent, endpoint, status: 'ok' })
  return { ok: true, apiKey: validation.apiKey, ip, userAgent }
}
