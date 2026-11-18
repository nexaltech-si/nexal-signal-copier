import { NextResponse } from 'next/server'
import type { ReloadSettingsResponse } from '@/lib/types/settings'
import { requireOwner } from '@/lib/auth'

export const dynamic = 'force-dynamic'

const PYTHON_API_URL = process.env.PYTHON_API_URL || 'http://localhost:8001'

/**
 * POST /api/settings/reload
 * Reload settings from database (hot reload)
 */
export async function POST() {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const response = await fetch(`${PYTHON_API_URL}/api/settings/reload`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
    })

    if (!response.ok) {
      throw new Error(`Python API returned ${response.status}`)
    }

    const data: ReloadSettingsResponse = await response.json()

    return NextResponse.json(data)
  } catch (error) {
    console.error('Error reloading settings:', error)
    return NextResponse.json(
      {
        success: false,
        message: 'Failed to reload settings',
        error: error instanceof Error ? error.message : 'Unknown error'
      },
      { status: 500 }
    )
  }
}
