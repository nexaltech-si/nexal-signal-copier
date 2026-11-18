import { NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'
import { getActiveProvider } from '@/lib/provider'

export const dynamic = 'force-dynamic'
export const revalidate = 0

export async function GET(request: Request) {
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

    const { searchParams } = new URL(request.url)
    const from_date = searchParams.get('from_date') || new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString()
    const to_date = searchParams.get('to_date') || new Date().toISOString()

    const headers: HeadersInit = { 'Content-Type': 'application/json' }
    if (mt5RestApiKey) headers['X-API-Key'] = mt5RestApiKey

    const response = await fetch(`${mt5RestUrl}/account_stats?from_date=${from_date}&to_date=${to_date}`, {
      headers,
      cache: 'no-store',
    })

    if (!response.ok) {
      const error = await response.json()
      return NextResponse.json(error, { status: response.status })
    }
    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error('Error fetching MT5 stats:', error)
    return NextResponse.json({ error: 'Failed to fetch stats' }, { status: 500 })
  }
}
