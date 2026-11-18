import { NextResponse } from 'next/server'
import { auth } from '@clerk/nextjs/server'
import { requireOwner } from '@/lib/auth'

const PYTHON_API_URL = process.env.PYTHON_API_URL || 'http://localhost:8001'

// VAPID public key the browser needs to create a push subscription.
// The keypair is owned by the bot (src/services/event_pusher.py).
export async function GET() {
  const denied = await requireOwner()
  if (denied) return denied

  const { userId } = await auth()
  if (!userId) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }
  try {
    const response = await fetch(`${PYTHON_API_URL}/api/push/vapid-public-key`, { cache: 'no-store' })
    if (!response.ok) {
      return NextResponse.json({ error: 'Push service unavailable' }, { status: 502 })
    }
    return NextResponse.json(await response.json())
  } catch (error) {
    console.error('Failed to fetch VAPID key:', error)
    return NextResponse.json({ error: 'Bot API unreachable' }, { status: 502 })
  }
}
