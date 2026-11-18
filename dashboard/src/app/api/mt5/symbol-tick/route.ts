import { NextRequest, NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'
import { getActiveProvider } from '@/lib/provider'

export const dynamic = 'force-dynamic'

export async function GET(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const { searchParams } = new URL(request.url)
    const symbol = searchParams.get('symbol')

    if (!symbol) {
      return NextResponse.json(
        { error: 'Symbol parameter required' },
        { status: 400 }
      )
    }

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

    const response = await fetch(`${mt5RestUrl}/symbol_info_tick/${encodeURIComponent(symbol)}`, {
      method: 'GET',
      headers,
    })

    if (!response.ok) {
      const error = await response.json().catch(() => ({ error: 'Upstream error' }))
      return NextResponse.json(error, { status: response.status })
    }

    const data = await response.json()

    return NextResponse.json({
      symbol,
      ask: data.ask ?? 0,
      bid: data.bid ?? 0,
      last: data.last ?? 0,
      time: data.time ?? 0,
      time_msc: data.time_msc ?? 0,
      flags: data.flags ?? 0,
      volume: data.volume ?? 0,
      volume_real: data.volume_real ?? 0,
    })
  } catch (error) {
    console.error('Error fetching symbol tick:', error)
    return NextResponse.json(
      { error: 'Failed to fetch symbol tick' },
      { status: 500 }
    )
  }
}
