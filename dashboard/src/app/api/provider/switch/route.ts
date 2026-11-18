import { NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'
import { invalidateActiveProvider } from '@/lib/provider'

export const dynamic = 'force-dynamic'

const PYTHON_API_URL = process.env.PYTHON_API_URL || 'http://localhost:8001'

/**
 * POST /api/provider/switch  { provider: 'metaapi' | 'mt5rest' }
 * Hot-switches the bot's trading provider (no restart). Owner-only.
 * MetaAPI and MT5 REST are different accounts: the bot refuses (409) while any bot trade is open.
 */
export async function POST(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  const body = await request.json().catch(() => ({}))
  const provider = String(body?.provider ?? '').toLowerCase().trim()
  if (provider !== 'metaapi' && provider !== 'mt5rest') {
    return NextResponse.json({ error: "provider must be 'metaapi' or 'mt5rest'" }, { status: 400 })
  }

  try {
    const res = await fetch(`${PYTHON_API_URL}/api/provider/switch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider }),
      cache: 'no-store',
      signal: AbortSignal.timeout(240_000), // the bot allows up to 180 s for the new provider to connect
    })
    const data = await res.json().catch(() => null)
    invalidateActiveProvider()
    if (!res.ok) {
      return NextResponse.json({ error: data?.detail || `Bot returned HTTP ${res.status}` }, { status: res.status === 409 ? 409 : 502 })
    }
    return NextResponse.json(data)
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : 'Bot unreachable' }, { status: 502 })
  }
}
