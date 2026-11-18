'use client'

import Link from 'next/link'
import { cn } from '@/lib/utils'
import type { TradeWithRelations } from '@/lib/types'
import WidgetCard, { WidgetEmpty } from './WidgetCard'
import { InstrumentSymbol } from '@/components/InstrumentSymbol'

interface ActiveTradeCardProps {
  trades: TradeWithRelations[]
}

function priceDecimals(symbol: string) {
  if (symbol.includes('XAU') || symbol.includes('XAG')) return 2
  if (symbol.includes('JPY')) return 3
  if (symbol.includes('BTC') || symbol.includes('USOIL')) return 2
  return 5
}

function fmt(value: number | null | undefined, symbol: string) {
  if (value == null) return '—'
  return value.toFixed(priceDecimals(symbol))
}

/** Highlights the most recent live trade, matching the mockup's Active Trade card. */
export default function ActiveTradeCard({ trades }: ActiveTradeCardProps) {
  const active = trades.filter(
    (t) => t.status === 'EXECUTED' || t.status === 'EXECUTING' || t.status === 'PENDING',
  )

  if (active.length === 0) {
    return (
      <WidgetCard title="Active Trade" actionLabel="View all trades" actionHref="/history">
        <WidgetEmpty message="No active trades right now" />
      </WidgetCard>
    )
  }

  const trade = active[0]
  const isBuy = (trade.action || '').toUpperCase() === 'BUY'

  // Latest known market price for this trade, else fall back to entry.
  const latestAnalysis = trade.marketAnalyses?.[0]
  const currentPrice = latestAnalysis?.currentPrice ?? trade.entryPrice ?? null

  const entry = trade.entryPrice
  const pl = trade.profitLoss
  const plPositive = (pl ?? 0) >= 0

  // Take-profit progress: how far current price has travelled from entry to TP.
  let tpProgress: number | null = null
  if (entry != null && trade.takeProfit != null && currentPrice != null) {
    const span = trade.takeProfit - entry
    if (span !== 0) {
      tpProgress = Math.max(
        0,
        Math.min(100, ((currentPrice - entry) / span) * 100),
      )
    }
  }

  return (
    <WidgetCard title="Active Trade" actionLabel="View all trades" actionHref="/history">
      {/* Header row: symbol + direction */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2.5">
          <InstrumentSymbol symbol={trade.symbol} size="md" />
          <div>
            <div className="text-base font-black text-foreground leading-none">
              {trade.symbol}
            </div>
            <div className="text-[10px] text-muted-foreground font-semibold mt-1">
              {active.length > 1 ? `+${active.length - 1} more active` : 'Live position'}
            </div>
          </div>
        </div>
        <span
          className={cn(
            'text-[11px] font-black px-2.5 py-1 rounded-md border',
            isBuy
              ? 'bg-success/10 border-success/25 text-success'
              : 'bg-destructive/10 border-destructive/25 text-destructive',
          )}
        >
          {isBuy ? 'BUY' : 'SELL'}
        </span>
      </div>

      {/* Price grid */}
      <div className="grid grid-cols-3 gap-3 mb-4">
        {([
          { label: 'Entry Price', value: fmt(entry, trade.symbol) },
          {
            label: 'Current Price',
            value: fmt(currentPrice, trade.symbol),
            tone: 'primary',
          },
          {
            label: 'P/L',
            value: pl != null ? `${plPositive ? '+' : ''}${pl.toFixed(2)}` : '—',
            tone: plPositive ? 'success' : 'destructive',
          },
          { label: 'Stop Loss', value: fmt(trade.stopLoss, trade.symbol), tone: 'destructive' },
          { label: 'Take Profit', value: fmt(trade.takeProfit, trade.symbol), tone: 'success' },
          { label: 'Lots', value: trade.lotSize != null ? trade.lotSize.toFixed(2) : '—' },
        ] as { label: string; value: string; tone?: 'primary' | 'success' | 'destructive' }[]).map(({ label, value, tone }) => (
          <div key={label}>
            <div className="tech-label mb-1">{label}</div>
            <div
              className={cn(
                'text-sm font-bold tabular-nums font-mono',
                tone === 'primary' && 'text-primary',
                tone === 'success' && 'text-success',
                tone === 'destructive' && 'text-destructive',
                !tone && 'text-foreground',
              )}
            >
              {value}
            </div>
          </div>
        ))}
      </div>

      {/* TP progress */}
      {tpProgress != null && (
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <span className="tech-label">Take Profit Progress</span>
            <span className="text-[11px] font-bold text-primary tabular-nums">
              {tpProgress.toFixed(0)}%
            </span>
          </div>
          <div className="w-full h-2 bg-border rounded-full overflow-hidden">
            <div
              className="h-full rounded-full bg-primary transition-all shadow-[0_0_6px_hsl(var(--primary)/0.6)]"
              style={{ width: `${tpProgress}%` }}
            />
          </div>
        </div>
      )}

      {/*
        The live-trade page matches on the MT5 position id (its ticket), NOT the
        DB UUID — so link with trade.positionId. When a trade isn't executed yet
        it has no positionId, so fall back to the trade history detail page.
      */}
      <Link
        href={trade.positionId ? `/livetrade/${trade.positionId}` : `/history/trades/${trade.id}`}
        className="mt-4 inline-flex items-center justify-center w-full h-9 rounded-lg bg-primary/10 border border-primary/20 text-primary text-xs font-bold hover:bg-primary/15 transition-colors"
      >
        View Analysis
      </Link>
    </WidgetCard>
  )
}
