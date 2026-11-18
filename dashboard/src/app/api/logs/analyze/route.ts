import { NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'

const BOT_API_URL = process.env.PYTHON_API_URL || 'http://localhost:8001'

// Sends grouped issues to the bot, which runs them through its AI provider fallback chain.
export async function POST(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const body = await request.json()
    const res = await fetch(`${BOT_API_URL}/api/logs/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      cache: 'no-store',
      signal: AbortSignal.timeout(180_000),
    })
    const data = await res.json().catch(() => ({ detail: res.statusText }))
    if (!res.ok) return NextResponse.json({ error: data.detail || 'AI analysis failed' }, { status: res.status })
    return NextResponse.json(data)
  } catch (error) {
    console.error('Error analyzing logs:', error)
    return NextResponse.json({ error: 'Bot unreachable — is it running?' }, { status: 502 })
  }
}
