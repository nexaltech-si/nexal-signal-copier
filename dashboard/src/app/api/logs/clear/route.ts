import { NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'

const BOT_API_URL = process.env.PYTHON_API_URL || 'http://localhost:8001'

// The dashboard's logs mount is read-only, so the bot deletes/truncates its own files.
// Body: { scope: 'old' | 'all' | 'file', file? }
export async function POST(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const body = await request.json()
    const res = await fetch(`${BOT_API_URL}/api/logs/clear`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      cache: 'no-store',
    })
    const data = await res.json().catch(() => ({ detail: res.statusText }))
    if (!res.ok) return NextResponse.json({ error: data.detail || 'Failed to clear logs' }, { status: res.status })
    return NextResponse.json(data)
  } catch (error) {
    console.error('Error clearing logs:', error)
    return NextResponse.json({ error: 'Bot unreachable — is it running?' }, { status: 502 })
  }
}
