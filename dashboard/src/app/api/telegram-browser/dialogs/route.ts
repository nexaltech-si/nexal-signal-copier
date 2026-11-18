import { NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'

export const dynamic = 'force-dynamic'

const PYTHON_API_URL = process.env.PYTHON_API_URL || 'http://localhost:8001'

export async function GET() {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const response = await fetch(`${PYTHON_API_URL}/api/telegram-browser/dialogs`, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
      cache: 'no-store',
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
    console.error('Error fetching Telegram dialogs:', error)
    return NextResponse.json(
      { success: false, error: error instanceof Error ? error.message : 'Failed to fetch dialogs' },
      { status: 500 }
    )
  }
}
