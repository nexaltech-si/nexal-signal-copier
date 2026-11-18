import { NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'

export const dynamic = 'force-dynamic'

const PYTHON_API_URL = process.env.PYTHON_API_URL || 'http://localhost:8001'

// Proxies the dashboard's "which instrument is this?" clarification answer to the
// Python backend, which resolves the pending signal and places it if valid.
export async function POST(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const body = await request.json()

    const response = await fetch(`${PYTHON_API_URL}/api/telegram-browser/resolve-symbol`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })

    if (!response.ok) {
      const error = await response.text()
      return NextResponse.json(
        { ok: false, message: `Backend error: ${error}` },
        { status: response.status }
      )
    }

    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error('Error resolving Telegram signal symbol:', error)
    return NextResponse.json(
      { ok: false, message: error instanceof Error ? error.message : 'Failed to resolve symbol' },
      { status: 500 }
    )
  }
}
