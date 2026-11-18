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
    const magic = searchParams.get('magic')
    const symbol = searchParams.get('symbol')
    const from_date = searchParams.get('from_date')
    const to_date = searchParams.get('to_date')

    const headers: HeadersInit = { 'Content-Type': 'application/json' }
    if (mt5RestApiKey) headers['X-API-Key'] = mt5RestApiKey

    // Build URL - only add date parameters if explicitly provided
    let url = `${mt5RestUrl}/trade_search`
    const params: string[] = []
    if (from_date) params.push(`from_date=${from_date}`)
    if (to_date) params.push(`to_date=${to_date}`)
    if (magic) params.push(`magic=${magic}`)
    if (symbol) params.push(`symbol=${symbol}`)
    if (params.length > 0) url += `?${params.join('&')}`

    const response = await fetch(url, {
      headers,
      cache: 'no-store',
    })

    if (!response.ok) {
      const error = await response.json()
      return NextResponse.json(error, { status: response.status })
    }
    const data = await response.json()
    
    // Transform MT5 REST API format to dashboard format
    const trades = (data.trades || []).map((trade: any) => ({
      ticket: trade.ticket,
      symbol: trade.symbol,
      type: trade.type === 'BUY' ? 0 : trade.type === 'SELL' ? 1 : parseInt(trade.type) || 0,
      volume: trade.volume,
      price_open: trade.entry_price || 0,
      price_close: trade.exit_price || 0,
      profit: trade.profit || trade.net_pnl || 0,
      time_open: trade.entry_time || null,
      time_close: trade.exit_time || null,
      magic: trade.magic || 0,
      comment: trade.status || ''
    }))
    
    return NextResponse.json(trades)
  } catch (error) {
    console.error('Error fetching trade history:', error)
    return NextResponse.json({ error: 'Failed to fetch history' }, { status: 500 })
  }
}
