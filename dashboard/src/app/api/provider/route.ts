import { NextResponse } from 'next/server'
import { getActiveProvider } from '@/lib/provider'
import { requireOwner } from '@/lib/auth'

export const dynamic = 'force-dynamic'

export async function GET(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  const tradingProvider = await getActiveProvider()
  const ismt5rest = tradingProvider === 'mt5rest'

  const mt5RestUrl = process.env.MT5_REST_API_URL || 'http://mt5:5001'
  const mt5RestApiKey = process.env.MT5_REST_API_KEY || ''
  const metaapiAccountId = process.env.METAAPI_ACCOUNT_ID || ''

  // Build live account snapshot when mt5rest
  let liveAccount: Record<string, number> | null = null
  if (ismt5rest) {
    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (mt5RestApiKey) headers['X-API-Key'] = mt5RestApiKey

      const res = await fetch(`${mt5RestUrl}/account_info`, { headers, cache: 'no-store' })
      if (res.ok) {
        const data = await res.json()
        liveAccount = {
          balance: data.balance ?? 0,
          equity: data.equity ?? 0,
          margin: data.margin ?? 0,
          freeMargin: data.margin_free ?? 0,
          leverage: data.leverage ?? 0,
        }
      }
    } catch {
      // best-effort
    }
  }

  // Live status from the bot (health, streaming, failover, last switch) - null if unreachable
  let bot: Record<string, unknown> | null = null
  try {
    const res = await fetch(`${process.env.PYTHON_API_URL || 'http://localhost:8001'}/api/provider`, {
      cache: 'no-store',
      signal: AbortSignal.timeout(3_000),
    })
    if (res.ok) bot = await res.json()
  } catch {
    // bot unreachable
  }

  return NextResponse.json({
    bot,
    provider: tradingProvider,
    label: ismt5rest ? 'MT5 REST API' : 'MetaAPI Cloud SDK',
    ismt5rest,
    accountId: ismt5rest ? undefined : metaapiAccountId,
    features: {
      cloudTrackers: !ismt5rest,
      metaStats: !ismt5rest,
      localDrawdown: true,
      liveEquity: true,
    },
    liveAccount,
  })
}
