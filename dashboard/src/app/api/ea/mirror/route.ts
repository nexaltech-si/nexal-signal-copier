import { NextRequest, NextResponse } from 'next/server'
import { authenticateEa } from '@/lib/eaAuth'

export const dynamic = 'force-dynamic'

const PYTHON_API_URL = process.env.PYTHON_API_URL || 'http://localhost:8001'
const ENDPOINT = '/api/ea/mirror'

/**
 * Public, per-customer-key-protected proxy for the trade-copier snapshot:
 * the master MT5 account's live positions and pending orders, consumed by
 * mt5/EA/NexalSignalMirrorEA.mq5 v2+, which opens, modifies, partially closes,
 * closes and cancels on its own account to match. Treat every issued key as
 * trade-control credentials.
 *
 * Status codes are passed through untouched — in particular the backend's 503
 * ("snapshot can't be trusted right now"), which the EA must read as "no
 * information" and never as "master is flat". See src/api/ea_mirror_router.py.
 *
 * Exempt from Clerk in middleware.ts; the key check below is the auth.
 */
export async function GET(request: NextRequest) {
  const auth = await authenticateEa(request, ENDPOINT)
  if (!auth.ok) return auth.response

  const internalKey = process.env.EA_API_KEY
  if (!internalKey) {
    return NextResponse.json(
      { error: 'EA feed disabled: EA_API_KEY is not configured on the backend' },
      { status: 503 }
    )
  }

  try {
    const response = await fetch(`${PYTHON_API_URL}${ENDPOINT}`, {
      headers: { 'X-EA-Key': internalKey },
      cache: 'no-store',
    })
    return new NextResponse(await response.text(), {
      status: response.status,
      headers: { 'Content-Type': 'text/plain; charset=utf-8' },
    })
  } catch (error) {
    console.error('Error proxying EA mirror snapshot:', error)
    return NextResponse.json({ error: 'Failed to reach backend' }, { status: 502 })
  }
}
