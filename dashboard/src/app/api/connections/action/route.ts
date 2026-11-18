import { NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'
import { CONNECTION_ACTIONS, type ConnectionAction } from '@/lib/types/connections'

export const dynamic = 'force-dynamic'

const PYTHON_API_URL = process.env.PYTHON_API_URL || 'http://localhost:8001'

const BOT_PATHS: Record<ConnectionAction, string> = {
  'bot.healthcheck': '/api/connections/health-check',
  'telegram.resync': '/api/connections/telegram/resync',
  'news.refresh': '/api/connections/news/refresh',
}

/** Runs one of the Connections page's buttons on the bot. Owner-only. */
export async function POST(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  const { action } = await request.json().catch(() => ({}))
  if (!CONNECTION_ACTIONS.includes(action)) {
    return NextResponse.json({ error: 'Unknown action' }, { status: 400 })
  }

  try {
    const res = await fetch(`${PYTHON_API_URL}${BOT_PATHS[action as ConnectionAction]}`, {
      method: 'POST',
      cache: 'no-store',
      signal: AbortSignal.timeout(60_000),
    })
    const body = await res.json().catch(() => null)
    if (!res.ok) return NextResponse.json({ error: body?.detail || `Bot returned HTTP ${res.status}` }, { status: 502 })
    return NextResponse.json(body)
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : 'Bot unreachable' }, { status: 502 })
  }
}
