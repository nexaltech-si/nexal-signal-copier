import { NextResponse } from 'next/server'
import { checkAuthorization, requireOwner } from '@/lib/auth'
import { getActiveProvider } from '@/lib/provider'

// Force dynamic to avoid caching
export const dynamic = 'force-dynamic'

/**
 * Performance Analytics API Endpoint
 * Fetches comprehensive performance metrics directly from MetaStats REST API
 */

const token = process.env.METAAPI_TOKEN
const accountId = process.env.METAAPI_ACCOUNT_ID
const METASTATS_API_URL = 'https://metastats-api-v1.london.agiliumtrade.ai'
const mt5RestUrl = process.env.MT5_REST_API_URL || 'http://mt5:5001'
const mt5RestApiKey = process.env.MT5_REST_API_KEY || ''


/**
 * Fetch performance metrics from MT5 REST API (self-hosted)
 */
async function fetchMT5RestMetrics(): Promise<Response> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (mt5RestApiKey) {
    headers['X-API-Key'] = mt5RestApiKey
  }

  // Fetch account_stats from MT5 REST API (last 90 days)
  const fromDate = new Date(Date.now() - 90 * 24 * 60 * 60 * 1000).toISOString()
  const toDate = new Date().toISOString()

  const [statsRes, accountRes] = await Promise.allSettled([
    fetch(`${mt5RestUrl}/account_stats?from_date=${fromDate}&to_date=${toDate}`, { headers, cache: 'no-store' }),
    fetch(`${mt5RestUrl}/account_info`, { headers, cache: 'no-store' }),
  ])

  const stats = statsRes.status === 'fulfilled' && statsRes.value.ok
    ? await statsRes.value.json()
    : { total_trades: 0, wins: 0, losses: 0, win_rate: 0, total_profit: 0, profit_factor: null }

  const account = accountRes.status === 'fulfilled' && accountRes.value.ok
    ? await accountRes.value.json()
    : { balance: 0, equity: 0 }

  const transformedMetrics = {
    balance: account.balance || 0,
    equity: account.equity || 0,
    profit: stats.total_profit || 0,
    gain: account.balance > 0 ? ((stats.total_profit || 0) / account.balance) * 100 : 0,
    totalTrades: stats.total_trades || 0,
    wonTrades: stats.win_rate || 0,
    profitFactor: stats.profit_factor || 0,
    maxDrawdown: 0,
    sharpeRatio: 0,
    sortinoRatio: 0,
    expectancy: stats.total_trades > 0 ? (stats.total_profit || 0) / stats.total_trades : 0,
    dailyGrowth: 0,
    monthlyGrowth: 0,
    cagr: 0,
    lastUpdateTime: new Date().toISOString(),
    tradeDuration: { avgInHours: 0, minInHours: 0, maxInHours: 0 },
    source: 'mt5rest',
    grossProfit: stats.gross_profit || 0,
    grossLoss: stats.gross_loss || 0,
    avgWin: stats.avg_win || 0,
    avgLoss: stats.avg_loss || 0,
  }

  return NextResponse.json(transformedMetrics)
}

export async function GET() {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    // Use MT5 REST API when it is the provider the bot is trading on right now
    const tradingProvider = await getActiveProvider()
    if (tradingProvider === 'mt5rest') {
      return await fetchMT5RestMetrics()
    }

    if (!token || !accountId) {
      return NextResponse.json(
        { 
          error: 'Configuration error',
          message: 'MetaAPI credentials not configured. Please set METAAPI_TOKEN and METAAPI_ACCOUNT_ID in environment variables.',
          service: 'offline'
        },
        { status: 503 }
      )
    }

    // Call MetaStats REST API directly
    const url = `${METASTATS_API_URL}/users/current/accounts/${accountId}/metrics`
    
    const response = await fetch(url, {
      method: 'GET',
      headers: {
        'auth-token': token,
        'Accept': 'application/json'
      },
      cache: 'no-store'
    })
    
    if (response.status === 202) {
      // Metrics calculation in progress
      return NextResponse.json(
        { 
          message: 'Metrics calculation in progress. Please try again in a moment.',
          status: 'pending'
        },
        { status: 202 }
      )
    }
    
    if (!response.ok) {
      const errorText = await response.text()
      console.error(`MetaStats API error: ${response.status} - ${errorText}`)
      
      return NextResponse.json(
        { 
          error: 'MetaStats API error',
          message: `API returned status ${response.status}`,
          service: 'error'
        },
        { status: response.status }
      )
    }
    
    const rawResponse = await response.json()
    
    // The data is nested under 'metrics' key
    const rawMetrics = rawResponse.metrics || rawResponse
    
    // Transform the MetaStats data to match frontend expectations
    const transformedMetrics = {
      balance: rawMetrics.balance || 0,
      equity: rawMetrics.equity || 0,
      profit: rawMetrics.profit || rawMetrics.absoluteGain || 0,
      gain: rawMetrics.gain || 0,
      totalTrades: rawMetrics.trades || 0,
      wonTrades: rawMetrics.wonTradesPercent || ((rawMetrics.wonTrades / rawMetrics.trades) * 100) || 0,
      profitFactor: rawMetrics.profitFactor || 0,
      maxDrawdown: rawMetrics.maxDrawdownPercent || rawMetrics.maxDrawdown || 0,
      sharpeRatio: rawMetrics.sharpeRatio || 0,
      sortinoRatio: rawMetrics.sortinoRatio || 0,
      expectancy: rawMetrics.expectancy || 0,
      dailyGrowth: rawMetrics.dailyGrowth || 0,
      monthlyGrowth: rawMetrics.monthlyGrowth || 0,
      cagr: rawMetrics.cagr || 0,
      lastUpdateTime: rawMetrics.lastUpdateTime || new Date().toISOString(),
      tradeDuration: rawMetrics.tradeDuration || {
        avgInHours: 0,
        minInHours: 0,
        maxInHours: 0
      },
      source: 'metaapi',
    }
    
    return NextResponse.json(transformedMetrics)
    
  } catch (error: unknown) {
    console.error('MetaStats API error:', error instanceof Error ? error.message : error)
    
    return NextResponse.json(
      { 
        error: 'Failed to fetch metrics',
        message: error instanceof Error ? error.message : 'Unable to fetch performance metrics from MetaAPI',
        service: 'error'
      },
      { status: 500 }
    )
  }
}

/**
 * Reset metrics cache (clears MetaAPI's cache)
 */
export async function DELETE() {
  const { authorized, response } = await checkAuthorization()
  if (!authorized) return response

  try {
    if (!token || !accountId) {
      return NextResponse.json(
        { error: 'Configuration error', service: 'offline' },
        { status: 503 }
      )
    }

    // Call MetaStats REST API to clear cache
    const url = `${METASTATS_API_URL}/users/current/accounts/${accountId}/metrics`
    
    const response = await fetch(url, {
      method: 'DELETE',
      headers: {
        'auth-token': token,
        'Accept': 'application/json'
      }
    })
    
    if (response.status === 204 || response.status === 200) {
      console.log('✅ Metrics cache cleared for account:', accountId)
      return NextResponse.json({ 
        success: true, 
        message: 'Cache cleared. Metrics will be recalculated on next request.' 
      })
    }
    
    const errorText = await response.text()
    console.error(`Failed to clear cache: ${response.status} - ${errorText}`)
    
    return NextResponse.json(
      { 
        error: 'Failed to reset cache',
        message: `API returned status ${response.status}`,
        service: 'error'
      },
      { status: response.status }
    )
    
  } catch (error: unknown) {
    console.warn('Reset metrics error:', error instanceof Error ? error.message : 'Unknown error')
    return NextResponse.json(
      { 
        error: 'Failed to reset cache',
        message: error instanceof Error ? error.message : 'Unable to reset metrics cache',
        service: 'error'
      },
      { status: 500 }
    )
  }
}
