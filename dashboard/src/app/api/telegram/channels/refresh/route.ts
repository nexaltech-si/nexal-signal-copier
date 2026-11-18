import { NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'

export const dynamic = 'force-dynamic'

const PYTHON_API_URL = process.env.PYTHON_API_URL || 'http://localhost:8001'

/**
 * Force refresh all channels from Telegram
 */
export async function POST() {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const response = await fetch(`${PYTHON_API_URL}/api/telegram/channels/refresh`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
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
    console.error('Error refreshing channels:', error)
    return NextResponse.json(
      { 
        success: false, 
        error: error instanceof Error ? error.message : 'Failed to refresh channels'
      },
      { status: 500 }
    )
  }
}
