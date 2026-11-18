import { NextRequest } from 'next/server'
import Redis from 'ioredis'
import { requireOwner } from '@/lib/auth'

export const dynamic = 'force-dynamic'

let redis: Redis | null = null

function getRedisClient(): Redis {
  if (!redis) {
    const redisUrl = process.env.REDIS_URL || 'redis://redis:6379'
    redis = new Redis(redisUrl, {
      retryStrategy: (times) => Math.min(times * 50, 2000),
      maxRetriesPerRequest: 1,
    })
    redis.on('error', () => { /* suppress unhandled error events */ })
  }
  return redis
}

// Broker renames whole instruments, not just a suffix (e.g. USOIL is quoted as
// USOUSD). This hits MT5 REST directly, so it needs the same override the
// Python side reads from MT5_SYMBOL_OVERRIDES — kept in sync manually since
// the two runtimes don't share config parsing.
const SYMBOL_OVERRIDES: Record<string, string> = (process.env.MT5_SYMBOL_OVERRIDES || 'USOIL:USOUSD')
  .split(',')
  .reduce((acc, pair) => {
    const [canonical, broker] = pair.split(':').map((s) => s.trim())
    if (canonical && broker) acc[canonical.toUpperCase()] = broker
    return acc
  }, {} as Record<string, string>)

export async function GET(request: NextRequest) {
  const denied = await requireOwner()
  if (denied) return denied

  const { searchParams } = new URL(request.url)
  const rawSymbol = searchParams.get('symbol') || 'XAUUSD'
  const symbol = SYMBOL_OVERRIDES[rawSymbol.toUpperCase()] || rawSymbol
  const timeframe = searchParams.get('timeframe') || 'M15'
  const start = searchParams.get('start')
  const end = searchParams.get('end')
  // live=true bypasses Redis so the current forming candle stays fresh
  const live = searchParams.get('live') === 'true'

  // A valid start/end window means we can ask MT5 for exactly that range instead
  // of guessing a bar count.
  const startMs = start ? new Date(start).getTime() : NaN
  const endMs = end ? new Date(end).getTime() : NaN
  const hasRange = !Number.isNaN(startMs) && !Number.isNaN(endMs) && endMs > startMs

  // Bar-count mode (no usable range given): default to a much larger window than
  // before so charts show real history, capped at the MT5 REST server's max (10000).
  const bars = Math.min(Math.max(parseInt(searchParams.get('bars') || '2000'), 1), 10000)

  const mt5RestUrl = process.env.MT5_REST_API_URL || 'http://mt5:5001'
  const mt5RestApiKey = process.env.MT5_REST_API_KEY || ''

  const headers: HeadersInit = { 'Content-Type': 'application/json' }
  if (mt5RestApiKey) headers['X-API-Key'] = mt5RestApiKey

  const upstreamUrl = hasRange && !live
    ? `${mt5RestUrl}/fetch_data_range?symbol=${symbol}&timeframe=${timeframe}&from_date=${encodeURIComponent(new Date(startMs).toISOString())}&to_date=${encodeURIComponent(new Date(endMs).toISOString())}`
    : `${mt5RestUrl}/fetch_data_pos?symbol=${symbol}&timeframe=${timeframe}&num_bars=${bars}`

  // Non-live: serve from Redis cache (15s TTL keeps data fresh enough for history)
  if (!live) {
    const redis = getRedisClient()
    const cacheKey = hasRange
      ? `candles:${symbol}:${timeframe}:${startMs}:${endMs}`
      : `candles:${symbol}:${timeframe}:${bars}`
    try {
      const cached = await redis.get(cacheKey)
      if (cached) {
        const parsed: unknown[] = JSON.parse(cached)
        return new Response(JSON.stringify(parsed), {
          headers: { 'Content-Type': 'application/json', 'X-Cache': 'HIT' },
        })
      }
    } catch { /* fall through to MT5 */ }

    // Cache miss — fetch from MT5 and cache the result
    try {
      const response = await fetch(upstreamUrl, { headers })
      if (!response.ok) throw new Error(`MT5 error: ${response.statusText}`)
      const data = await response.json()
      try {
        await redis.setex(cacheKey, 15, JSON.stringify(data))
      } catch { /* non-fatal */ }
      return new Response(JSON.stringify(data), {
        headers: { 'Content-Type': 'application/json', 'X-Cache': 'MISS' },
      })
    } catch (error) {
      return new Response(
        JSON.stringify({ error: error instanceof Error ? error.message : 'Failed to fetch candle data' }),
        { status: 500, headers: { 'Content-Type': 'application/json' } }
      )
    }
  }

  // live=true — always hit MT5 directly, no cache read or write
  try {
    const response = await fetch(upstreamUrl, { headers })
    if (!response.ok) throw new Error(`MT5 error: ${response.statusText}`)
    const data = await response.json()
    return new Response(JSON.stringify(data), {
      headers: { 'Content-Type': 'application/json', 'X-Cache': 'LIVE' },
    })
  } catch (error) {
    return new Response(
      JSON.stringify({ error: error instanceof Error ? error.message : 'Failed to fetch live candle data' }),
      { status: 500, headers: { 'Content-Type': 'application/json' } }
    )
  }
}
