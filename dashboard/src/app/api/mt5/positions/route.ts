import { NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'
import { getActiveProvider } from '@/lib/provider'

export const dynamic = 'force-dynamic'
export const revalidate = 0

export async function GET() {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const tradingProvider = await getActiveProvider()
    
    if (tradingProvider !== 'mt5rest') {
      return NextResponse.json(
        { error: 'MT5 REST provider not configured' },
        { status: 400 }
      )
    }

    const mt5RestUrl = process.env.MT5_REST_API_URL
    const mt5RestApiKey = process.env.MT5_REST_API_KEY

    if (!mt5RestUrl) {
      return NextResponse.json(
        { error: 'MT5_REST_API_URL not configured' },
        { status: 500 }
      )
    }

    const headers: HeadersInit = {
      'Content-Type': 'application/json',
    }
    if (mt5RestApiKey) {
      headers['X-API-Key'] = mt5RestApiKey
    }

    const response = await fetch(`${mt5RestUrl}/get_positions`, {
      headers,
      cache: 'no-store',
    })

    if (!response.ok) {
      throw new Error(`MT5 API error: ${response.statusText}`)
    }

    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error('Error fetching MT5 positions:', error)
    return NextResponse.json(
      { error: 'Failed to fetch positions' },
      { status: 500 }
    )
  }
}
