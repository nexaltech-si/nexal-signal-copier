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

    const response = await fetch(`${mt5RestUrl}/symbol_info/${symbol}`, {
      method: 'GET',
      headers,
    })

    if (!response.ok) {
      const error = await response.json()
      return NextResponse.json(error, { status: response.status })
    }

    const data = await response.json()
    
    // Extract relevant lot size information
    const symbolInfo = {
      symbol: data.symbol || symbol,
      volumeMin: data.trade_volume_min || data.volume_min || 0.01,
      volumeMax: data.trade_volume_max || data.volume_max || 100,
      volumeStep: data.trade_volume_step || data.volume_step || 0.01,
      digits: data.digits || 5,
      point: data.point || 0.00001,
      tickSize: data.trade_tick_size || data.tick_size || 0.00001,
    }

    return NextResponse.json(symbolInfo)
  } catch (error) {
    console.error('Error fetching symbol info:', error)
    return NextResponse.json(
      { error: 'Failed to fetch symbol info' },
      { status: 500 }
    )
  }
}
