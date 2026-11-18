import { NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'

// CFTC TFF (Traders in Financial Futures) - forex pairs
const CFTC_TFF_URL = 'https://publicreporting.cftc.gov/resource/gpe5-46if.json'

// CFTC Legacy Futures Only - commodities (Gold, Silver)
const CFTC_LEGACY_URL = 'https://publicreporting.cftc.gov/resource/6dca-aqww.json'

// TFF forex markets
const FOREX_MARKETS: Record<string, string> = {
  'EURO FX - CHICAGO MERCANTILE EXCHANGE': 'EUR',
  'JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE': 'JPY',
  'BRITISH POUND - CHICAGO MERCANTILE EXCHANGE': 'GBP',
  'SWISS FRANC - CHICAGO MERCANTILE EXCHANGE': 'CHF',
  'CANADIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE': 'CAD',
  'AUSTRALIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE': 'AUD',
  'NEW ZEALAND DOLLAR - CHICAGO MERCANTILE EXCHANGE': 'NZD',
  'MEXICAN PESO - CHICAGO MERCANTILE EXCHANGE': 'MXN',
}

// Legacy commodity markets (Gold & Silver on COMEX)
const COMMODITY_MARKETS: Record<string, string> = {
  'GOLD - COMMODITY EXCHANGE INC.': 'GOLD',
  'SILVER - COMMODITY EXCHANGE INC.': 'SILVER',
}

export interface COTRecord {
  currency: string
  marketName: string
  reportDate: string
  category: 'forex' | 'commodity'
  // Speculator / Non-Commercial (used for Legacy commodities)
  nonCommLong: number
  nonCommShort: number
  nonCommNet: number
  // Asset Manager / institutional (TFF forex)
  assetMgrLong: number
  assetMgrShort: number
  assetMgrNet: number
  // Leveraged Funds / hedge funds (TFF forex) — also Non-Commercial for Legacy
  levFundsLong: number
  levFundsShort: number
  levFundsNet: number
  // Open Interest
  openInterest: number
  // Derived
  sentiment: 'bullish' | 'bearish' | 'neutral'
  netChangeWeek: number | null
}

// In-memory cache: 1 hour TTL
let cache: { data: COTRecord[]; fetchedAt: number } | null = null
const CACHE_TTL_MS = 60 * 60 * 1000

function groupByMarket(rows: Record<string, string>[]): Record<string, Record<string, string>[]> {
  const grouped: Record<string, Record<string, string>[]> = {}
  for (const row of rows) {
    const name = row['market_and_exchange_names']
    if (!grouped[name]) grouped[name] = []
    grouped[name].push(row)
  }
  return grouped
}

function parseTFFRecord(
  marketName: string,
  rows: Record<string, string>[]
): COTRecord {
  rows.sort((a, b) =>
    new Date(b['report_date_as_yyyy_mm_dd']).getTime() -
    new Date(a['report_date_as_yyyy_mm_dd']).getTime()
  )
  const latest = rows[0]
  const prev = rows[1] ?? null

  const levLong = parseInt(latest['lev_money_positions_long'] ?? '0', 10)
  const levShort = parseInt(latest['lev_money_positions_short'] ?? '0', 10)
  const levNet = levLong - levShort
  const prevLevNet = prev
    ? parseInt(prev['lev_money_positions_long'] ?? '0', 10) -
      parseInt(prev['lev_money_positions_short'] ?? '0', 10)
    : null

  const assetLong = parseInt(latest['asset_mgr_positions_long'] ?? '0', 10)
  const assetShort = parseInt(latest['asset_mgr_positions_short'] ?? '0', 10)
  const openInterest = parseInt(latest['open_interest_all'] ?? '0', 10)

  let sentiment: 'bullish' | 'bearish' | 'neutral' = 'neutral'
  if (levNet > openInterest * 0.03) sentiment = 'bullish'
  else if (levNet < -(openInterest * 0.03)) sentiment = 'bearish'

  return {
    currency: FOREX_MARKETS[marketName] ?? marketName,
    marketName,
    reportDate: latest['report_date_as_yyyy_mm_dd'],
    category: 'forex',
    nonCommLong: 0,
    nonCommShort: 0,
    nonCommNet: 0,
    assetMgrLong: assetLong,
    assetMgrShort: assetShort,
    assetMgrNet: assetLong - assetShort,
    levFundsLong: levLong,
    levFundsShort: levShort,
    levFundsNet: levNet,
    openInterest,
    sentiment,
    netChangeWeek: prevLevNet !== null ? levNet - prevLevNet : null,
  }
}

function parseLegacyRecord(
  marketName: string,
  rows: Record<string, string>[]
): COTRecord {
  rows.sort((a, b) =>
    new Date(b['report_date_as_yyyy_mm_dd']).getTime() -
    new Date(a['report_date_as_yyyy_mm_dd']).getTime()
  )
  const latest = rows[0]
  const prev = rows[1] ?? null

  // Legacy uses noncomm_positions_long/short for speculators
  const ncLong = parseInt(latest['noncomm_positions_long_all'] ?? '0', 10)
  const ncShort = parseInt(latest['noncomm_positions_short_all'] ?? '0', 10)
  const ncNet = ncLong - ncShort
  const prevNcNet = prev
    ? parseInt(prev['noncomm_positions_long_all'] ?? '0', 10) -
      parseInt(prev['noncomm_positions_short_all'] ?? '0', 10)
    : null

  const openInterest = parseInt(latest['open_interest_all'] ?? '0', 10)

  let sentiment: 'bullish' | 'bearish' | 'neutral' = 'neutral'
  if (ncNet > openInterest * 0.03) sentiment = 'bullish'
  else if (ncNet < -(openInterest * 0.03)) sentiment = 'bearish'

  return {
    currency: COMMODITY_MARKETS[marketName] ?? marketName,
    marketName,
    reportDate: latest['report_date_as_yyyy_mm_dd'],
    category: 'commodity',
    nonCommLong: ncLong,
    nonCommShort: ncShort,
    nonCommNet: ncNet,
    assetMgrLong: 0,
    assetMgrShort: 0,
    assetMgrNet: 0,
    levFundsLong: ncLong,
    levFundsShort: ncShort,
    levFundsNet: ncNet,
    openInterest,
    sentiment,
    netChangeWeek: prevNcNet !== null ? ncNet - prevNcNet : null,
  }
}

function buildSoqlUrl(baseUrl: string, marketNames: string[], selectFields: string[], limit: number): string {
  // Use IN() operator — more reliable than chained OR with URLSearchParams encoding
  const inList = marketNames.map(n => `'${n.replace(/'/g, "''")}'`).join(',')
  const where = `market_and_exchange_names IN(${inList})`
  // Build URL manually to avoid URLSearchParams double-encoding single quotes
  const qs = [
    `$where=${encodeURIComponent(where)}`,
    `$order=${encodeURIComponent('report_date_as_yyyy_mm_dd DESC')}`,
    `$limit=${limit}`,
    `$select=${encodeURIComponent(selectFields.join(','))}`,
  ].join('&')
  return `${baseUrl}?${qs}`
}

export async function GET() {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    if (cache && Date.now() - cache.fetchedAt < CACHE_TTL_MS) {
      return NextResponse.json({ data: cache.data, cachedAt: new Date(cache.fetchedAt).toISOString() })
    }

    const forexNames = Object.keys(FOREX_MARKETS)
    const commodityNames = Object.keys(COMMODITY_MARKETS)

    const tffUrl = buildSoqlUrl(CFTC_TFF_URL, forexNames, [
      'market_and_exchange_names',
      'report_date_as_yyyy_mm_dd',
      'asset_mgr_positions_long',
      'asset_mgr_positions_short',
      'lev_money_positions_long',
      'lev_money_positions_short',
      'open_interest_all',
    ], forexNames.length * 2)

    const legacyUrl = buildSoqlUrl(CFTC_LEGACY_URL, commodityNames, [
      'market_and_exchange_names',
      'report_date_as_yyyy_mm_dd',
      'noncomm_positions_long_all',
      'noncomm_positions_short_all',
      'open_interest_all',
    ], commodityNames.length * 2)

    const [tffRes, legacyRes] = await Promise.all([
      fetch(tffUrl, { headers: { 'Accept': 'application/json' }, cache: 'no-store' }),
      fetch(legacyUrl, { headers: { 'Accept': 'application/json' }, cache: 'no-store' }),
    ])

    if (!tffRes.ok) {
      const body = await tffRes.text()
      throw new Error(`CFTC TFF API error ${tffRes.status}: ${body.slice(0, 300)}`)
    }
    if (!legacyRes.ok) {
      const body = await legacyRes.text()
      throw new Error(`CFTC Legacy API error ${legacyRes.status}: ${body.slice(0, 300)}`)
    }

    const tffRaw = await tffRes.json() as Record<string, string>[]
    const legacyRaw = await legacyRes.json() as Record<string, string>[]

    const result: COTRecord[] = []

    // Process TFF forex records
    const tffGrouped = groupByMarket(tffRaw)
    for (const [marketName, rows] of Object.entries(tffGrouped)) {
      if (FOREX_MARKETS[marketName]) {
        result.push(parseTFFRecord(marketName, rows))
      }
    }

    // Process Legacy commodity records (Gold, Silver)
    const legacyGrouped = groupByMarket(legacyRaw)
    for (const [marketName, rows] of Object.entries(legacyGrouped)) {
      if (COMMODITY_MARKETS[marketName]) {
        result.push(parseLegacyRecord(marketName, rows))
      }
    }

    // Sort: commodities first (GOLD, SILVER), then forex alphabetically
    result.sort((a, b) => {
      if (a.category !== b.category) return a.category === 'commodity' ? -1 : 1
      return a.currency.localeCompare(b.currency)
    })

    cache = { data: result, fetchedAt: Date.now() }
    return NextResponse.json({ data: result, cachedAt: new Date(cache.fetchedAt).toISOString() })
  } catch (error) {
    console.error('[COT API]', error)
    return NextResponse.json(
      { error: error instanceof Error ? error.message : 'Failed to fetch COT data' },
      { status: 500 }
    )
  }
}
