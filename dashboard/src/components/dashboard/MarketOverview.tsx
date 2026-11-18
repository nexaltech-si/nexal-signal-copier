'use client'

import { BarChart3, TrendingUp, TrendingDown, Minus } from 'lucide-react'
import { cn } from '@/lib/utils'
import WidgetCard from './WidgetCard'
import { useLivePrices, priceDecimals } from './useLivePrices'
import { InstrumentSymbol } from '@/components/InstrumentSymbol'

const MARKETS: { symbol: string; label: string }[] = [
  { symbol: 'XAUUSD', label: 'Gold' },
  { symbol: 'XAGUSD', label: 'Silver' },
  { symbol: 'EURUSD', label: 'EUR/USD' },
  { symbol: 'GBPUSD', label: 'GBP/USD' },
  { symbol: 'USDJPY', label: 'USD/JPY' },
]

export default function MarketOverview() {
  const { prices, loading } = useLivePrices(MARKETS.map((m) => m.symbol))

  return (
    <WidgetCard title="Market Overview" icon={<BarChart3 className="h-4 w-4" />}>
      <div className="space-y-1">
        {MARKETS.map(({ symbol, label }) => {
          const p = prices[symbol]
          const up = (p?.changePct ?? 0) > 0
          const down = (p?.changePct ?? 0) < 0
          const Icon = up ? TrendingUp : down ? TrendingDown : Minus
          return (
            <div
              key={symbol}
              className="flex items-center justify-between py-2 border-b border-border/40 last:border-0"
            >
              <div className="flex items-center gap-2 min-w-0">
                <InstrumentSymbol symbol={symbol} size="sm" />
                <div className="min-w-0">
                  <div className="text-xs font-bold text-foreground truncate">{label}</div>
                  <div className="text-[10px] text-muted-foreground/60 font-mono">{symbol}</div>
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <span className="text-xs font-semibold tabular-nums text-foreground font-mono">
                  {p?.price != null ? p.price.toFixed(priceDecimals(symbol)) : loading ? '…' : '—'}
                </span>
                <span
                  className={cn(
                    'flex items-center gap-0.5 text-[11px] font-bold tabular-nums w-16 justify-end',
                    up ? 'text-success' : down ? 'text-destructive' : 'text-muted-foreground/60',
                  )}
                >
                  <Icon className="h-3 w-3" />
                  {p?.changePct != null
                    ? `${up ? '+' : ''}${p.changePct.toFixed(2)}%`
                    : ''}
                </span>
              </div>
            </div>
          )
        })}
      </div>
    </WidgetCard>
  )
}
