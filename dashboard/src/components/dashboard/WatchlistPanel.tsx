'use client'

import { Eye, TrendingUp, TrendingDown, Minus } from 'lucide-react'
import { cn } from '@/lib/utils'
import WidgetCard from './WidgetCard'
import { useLivePrices, priceDecimals } from './useLivePrices'
import { InstrumentSymbol } from '@/components/InstrumentSymbol'

const WATCHLIST = ['EURUSD', 'GBPUSD', 'USDJPY', 'USOIL', 'BTCUSD', 'XAUUSD']

export default function WatchlistPanel() {
  const { prices, loading } = useLivePrices(WATCHLIST)

  return (
    <WidgetCard title="Watchlist" icon={<Eye className="h-4 w-4" />}>
      <div className="space-y-1">
        {WATCHLIST.map((symbol) => {
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
                <span className="text-xs font-bold text-foreground font-mono">{symbol}</span>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <span className="text-xs font-semibold tabular-nums text-foreground font-mono">
                  {p?.price != null ? p.price.toFixed(priceDecimals(symbol)) : loading ? '…' : '—'}
                </span>
                <span
                  className={cn(
                    'flex items-center gap-0.5 text-[11px] font-bold tabular-nums w-14 justify-end',
                    up ? 'text-success' : down ? 'text-destructive' : 'text-muted-foreground/60',
                  )}
                >
                  <Icon className="h-3 w-3" />
                  {p?.changePct != null ? `${up ? '+' : ''}${p.changePct.toFixed(2)}%` : ''}
                </span>
              </div>
            </div>
          )
        })}
      </div>
    </WidgetCard>
  )
}
