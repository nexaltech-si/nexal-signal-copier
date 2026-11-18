'use client'

import { useEffect, useState } from 'react'

export interface LivePrice {
  symbol: string
  price: number | null
  changePct: number | null
}

/**
 * Fetches the last close + previous close for each symbol from /api/candles
 * (per-symbol, as the API expects) and derives a % change. Fully defensive:
 * any failing symbol simply yields nulls so widgets never break the page.
 */
export function useLivePrices(symbols: string[], intervalMs = 30000) {
  const [prices, setPrices] = useState<Record<string, LivePrice>>({})
  const [loading, setLoading] = useState(true)

  const key = symbols.join(',')

  useEffect(() => {
    let cancelled = false

    async function fetchOne(symbol: string): Promise<LivePrice> {
      try {
        const res = await fetch(
          `/api/candles?symbol=${encodeURIComponent(symbol)}&timeframe=M15&bars=2`,
        )
        if (!res.ok) throw new Error('bad status')
        const data = await res.json()
        if (!Array.isArray(data) || data.length === 0) {
          return { symbol, price: null, changePct: null }
        }
        const last = data[data.length - 1]
        const prev = data.length > 1 ? data[data.length - 2] : null
        const price = typeof last?.close === 'number' ? last.close : null
        let changePct: number | null = null
        if (price != null && prev?.close) {
          changePct = ((price - prev.close) / prev.close) * 100
        }
        return { symbol, price, changePct }
      } catch {
        return { symbol, price: null, changePct: null }
      }
    }

    async function run() {
      const results = await Promise.all(symbols.map(fetchOne))
      if (cancelled) return
      const map: Record<string, LivePrice> = {}
      results.forEach((r) => (map[r.symbol] = r))
      setPrices(map)
      setLoading(false)
    }

    run()
    const id = setInterval(run, intervalMs)
    return () => {
      cancelled = true
      clearInterval(id)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, intervalMs])

  return { prices, loading }
}

export function priceDecimals(symbol: string) {
  if (symbol.includes('XAU') || symbol.includes('XAG')) return 2
  if (symbol.includes('JPY')) return 3
  if (symbol.includes('BTC') || symbol.includes('USOIL') || symbol.includes('OIL')) return 2
  return 4
}
