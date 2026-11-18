import { NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'
import { getActiveProvider } from '@/lib/provider'

export const dynamic = 'force-dynamic'

export async function POST(request: Request) {
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

    const body = await request.json().catch(() => ({}))

    const headers: HeadersInit = { 'Content-Type': 'application/json' }
    if (mt5RestApiKey) headers['X-API-Key'] = mt5RestApiKey

    const response = await fetch(`${mt5RestUrl}/close_losing`, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
    })

    if (!response.ok) {
      const error = await response.json()
      return NextResponse.json(error, { status: response.status })
    }

    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error('Error closing losing positions:', error)
    return NextResponse.json({ error: 'Failed to close positions' }, { status: 500 })
  }
}
