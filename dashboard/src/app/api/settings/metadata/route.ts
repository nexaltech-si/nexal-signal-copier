import { NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'

export const dynamic = 'force-dynamic'

/**
 * GET /api/settings/metadata
 * Get settings metadata (descriptions, categories, types) from cache
 * This is cached on the server side to avoid database queries
 */
export async function GET() {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const pythonApiUrl = process.env.PYTHON_API_URL || 'http://localhost:8001'
    const response = await fetch(`${pythonApiUrl}/api/settings/metadata`, { cache: 'no-store' })

    if (!response.ok) {
      throw new Error(`Failed to fetch settings metadata from the bot API (HTTP ${response.status})`)
    }

    const data = await response.json()

    return NextResponse.json(data)
  } catch (error) {
    console.error('Error fetching settings metadata:', error)
    return NextResponse.json(
      { 
        error: 'Failed to fetch settings metadata',
        message: error instanceof Error ? error.message : 'Unknown error'
      },
      { status: 500 }
    )
  }
}
