'use client'

import { useState, useEffect, useCallback } from 'react'
import { TrendingUp, TrendingDown, Minus, RefreshCw } from 'lucide-react'
import { cn } from '@/lib/utils'

interface TickerPrice {
  symbol: string
  bid: number
  ask: number
  change: number
  changePct: number
  high: number
  low: number
}

const DEFAULT_SYMBOLS = ['XAUUSD', 'EURUSD', 'USDJPY', 'GBPUSD', 'USDCAD', 'AUDUSD']

export default function MarketTicker() {
  const [prices, setPrices] = useState<Record<string, TickerPrice>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchPrices = useCallback(async () => {
    try {
      const res = await fetch(`/api/candles?symbols=${DEFAULT_SYMBOLS.join(',')}&timeframe=M1&bars=1`)
      if (!res.ok) throw new Error('Failed to fetch')
      setError(null)
    } catch {
      setError('Offline')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchPrices()
    const interval = setInterval(fetchPrices, 30000)
    return () => clearInterval(interval)
  }, [fetchPrices])

  // Also listen for MT5 SSE updates
  useEffect(() => {
    const handleTick = (e: CustomEvent) => {
      if (e.detail?.symbol && e.detail?.bid) {
        setPrices(prev => ({
          ...prev,
          [e.detail.symbol]: {
            ...(prev[e.detail.symbol] || {}),
            symbol: e.detail.symbol,
            bid: e.detail.bid,
            ask: e.detail.ask || e.detail.bid,
          } as TickerPrice
        }))
      }
    }
    window.addEventListener('mt5-tick' as any, handleTick as any)
    return () => window.removeEventListener('mt5-tick' as any, handleTick as any)
  }, [])

  if (loading) {
    return (
      <div className="bg-card rounded-xl border border-border p-3 shadow-sm">
        <div className="flex items-center gap-2 text-xs text-muted-foreground/70">
          <RefreshCw className="h-3 w-3 animate-spin" />
          Loading markets...
        </div>
      </div>
    )
  }

  return (
    <div className="tech-card rounded-xl overflow-hidden">
      <div className="flex items-center gap-4 px-3 py-1.5 border-b border-border/50 overflow-x-auto scrollbar-none">
        {DEFAULT_SYMBOLS.map(sym => {
          const p = prices[sym]
          return (
            <div key={sym} className="flex items-center gap-2 py-1 flex-shrink-0">
              <span className="text-[11px] font-bold text-foreground/80">{sym}</span>
              {p ? (
                <>
                  <span className="text-[11px] font-semibold tabular-nums text-foreground">
                    {p.bid?.toFixed(sym === 'XAUUSD' ? 2 : sym === 'USDJPY' ? 3 : 5)}
                  </span>
                  <span className={cn(
                    'text-[10px] font-bold tabular-nums',
                    p.change > 0 ? 'text-success' : p.change < 0 ? 'text-destructive' : 'text-muted-foreground/70'
                  )}>
                    {p.change > 0 ? '+' : ''}{p.changePct?.toFixed(2)}%
                  </span>
                </>
              ) : (
                <span className="text-[10px] text-muted-foreground/70">—</span>
              )}
            </div>
          )
        })}
        {error && (
          <span className="text-[10px] text-gold font-medium ml-auto flex-shrink-0">{error}</span>
        )}
      </div>
    </div>
  )
}
