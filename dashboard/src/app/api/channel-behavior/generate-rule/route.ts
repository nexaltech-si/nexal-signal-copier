import { NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'

const PYTHON_API_URL = process.env.PYTHON_API_URL || 'http://localhost:8001'

export async function POST(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const body = await request.json()
    const response = await fetch(`${PYTHON_API_URL}/api/channel-behavior/generate-rule`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!response.ok) {
      const error = await response.json()
      return NextResponse.json(error, { status: response.status })
    }
    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error('Error generating channel rule:', error)
    return NextResponse.json({ error: 'Bot API unreachable' }, { status: 502 })
  }
}
