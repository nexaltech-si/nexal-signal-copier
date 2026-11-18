import { NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'

export const dynamic = 'force-dynamic'

const PYTHON_API_URL = process.env.PYTHON_API_URL || 'http://localhost:8001'

export async function POST(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const body = await request.json()

    const response = await fetch(`${PYTHON_API_URL}/api/telegram-browser/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })

    if (!response.ok) {
      const error = await response.text()
      return NextResponse.json(
        { success: false, error: `Backend error: ${error}` },
        { status: response.status }
      )
    }

    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error('Error executing Telegram signal:', error)
    return NextResponse.json(
      { success: false, error: error instanceof Error ? error.message : 'Failed to execute signal' },
      { status: 500 }
    )
  }
}
