import { NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'

export const dynamic = 'force-dynamic'

const PYTHON_API_URL = process.env.PYTHON_API_URL || 'http://localhost:8001'

// action -> bot endpoint (src/api/telegram_auth_router.py) and the one body field it takes.
const STEPS = {
  'send-code': { path: '/api/telegram/auth/send-code', field: 'phone' },
  code: { path: '/api/telegram/auth/code', field: 'code' },
  password: { path: '/api/telegram/auth/password', field: 'password' },
  cancel: { path: '/api/telegram/auth/cancel', field: null },
  'sign-out': { path: '/api/telegram/auth/sign-out', field: null },
} as const

type Step = keyof typeof STEPS

/**
 * Telegram login / sign-out from the Connections page. Owner-only. The code and
 * 2FA password are forwarded to the bot over the internal network and never
 * logged or stored here — don't add logging of the request body.
 */
export async function POST(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  const body = await request.json().catch(() => null)
  const action = body?.action as Step
  if (!action || !(action in STEPS)) {
    return NextResponse.json({ error: 'Unknown action' }, { status: 400 })
  }
  const { path, field } = STEPS[action]
  const value = field ? body?.[field] : undefined
  if (field && typeof value !== 'string') {
    return NextResponse.json({ error: `Missing ${field}` }, { status: 400 })
  }

  try {
    const res = await fetch(`${PYTHON_API_URL}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(field ? { [field]: value } : {}),
      cache: 'no-store',
      signal: AbortSignal.timeout(60_000),
    })
    const data = await res.json().catch(() => null)
    if (!res.ok) {
      return NextResponse.json({ error: data?.detail || `Bot returned HTTP ${res.status}` }, { status: res.status === 400 ? 400 : 502 })
    }
    return NextResponse.json(data, { headers: { 'Cache-Control': 'no-store' } })
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : 'Bot unreachable' }, { status: 502 })
  }
}
