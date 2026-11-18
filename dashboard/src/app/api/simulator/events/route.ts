import { NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'

export const dynamic = 'force-dynamic'
const API = process.env.PYTHON_API_URL || 'http://localhost:8001'

/**
 * Proxy the Python backend's SSE stream to the browser.
 * The frontend connects to /api/simulator/events (same origin) —
 * it never touches the backend URL directly.
 */
export async function GET() {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const upstream = await fetch(`${API}/api/simulator/events`, {
      headers: { Accept: 'text/event-stream' },
      // Required for Node.js streaming fetch
      // @ts-ignore
      duplex: 'half',
    })

    if (!upstream.ok || !upstream.body) {
      return NextResponse.json({ error: 'Backend unavailable' }, { status: 502 })
    }

    return new Response(upstream.body, {
      status: 200,
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache, no-transform',
        'Connection': 'keep-alive',
        'X-Accel-Buffering': 'no',
      },
    })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 502 })
  }
}
