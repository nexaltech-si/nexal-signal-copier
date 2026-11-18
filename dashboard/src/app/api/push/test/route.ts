import { NextResponse } from 'next/server'
import { auth } from '@clerk/nextjs/server'
import { requireOwner } from '@/lib/auth'

const PYTHON_API_URL = process.env.PYTHON_API_URL || 'http://localhost:8001'

// Sends a test notification through the full pipeline (inbox + live + push).
export async function POST() {
  const denied = await requireOwner()
  if (denied) return denied

  const { userId } = await auth()
  if (!userId) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }
  try {
    const response = await fetch(`${PYTHON_API_URL}/api/push/test`, { method: 'POST' })
    if (!response.ok) {
      return NextResponse.json({ error: 'Push service unavailable' }, { status: 502 })
    }
    return NextResponse.json(await response.json())
  } catch (error) {
    console.error('Failed to send test push:', error)
    return NextResponse.json({ error: 'Bot API unreachable' }, { status: 502 })
  }
}
