'use client'

import { PieChart } from 'lucide-react'
import WidgetCard from './WidgetCard'

interface TradingOverviewProps {
  activeTrades: number
  totalTrades: number
  closedTrades: number
  totalSignals: number
  winRate: number
  /** Symbol → open-trade count, for the donut breakdown. */
  openBySymbol: { symbol: string; count: number }[]
}

const DONUT_COLORS = [
  'hsl(var(--primary))',
  'hsl(var(--success))',
  'hsl(var(--gold))',
  'hsl(var(--destructive))',
  'hsl(var(--muted-foreground))',
]

export default function TradingOverview({
  activeTrades,
  totalTrades,
  closedTrades,
  totalSignals,
  winRate,
  openBySymbol,
}: TradingOverviewProps) {
  const totalOpen = openBySymbol.reduce((s, x) => s + x.count, 0)

  // Build SVG donut segments.
  const radius = 42
  const circumference = 2 * Math.PI * radius
  let offset = 0
  const segments = (totalOpen > 0 ? openBySymbol : []).map((s, i) => {
    const frac = s.count / totalOpen
    const seg = {
      symbol: s.symbol,
      color: DONUT_COLORS[i % DONUT_COLORS.length],
      dash: frac * circumference,
      gap: circumference - frac * circumference,
      rotation: (offset / circumference) * 360,
      pct: frac * 100,
    }
    offset += frac * circumference
    return seg
  })

  const rows = [
    { label: 'Open Trades', value: activeTrades },
    { label: 'Closed Trades', value: closedTrades },
    { label: 'Total Signals', value: totalSignals },
    { label: 'Win Rate', value: `${winRate.toFixed(0)}%` },
  ]

  return (
    <WidgetCard
      title="Trading Overview"
      icon={<PieChart className="h-4 w-4" />}
      actionLabel="All trading"
      actionHref="/history"
    >
      <div className="flex items-center gap-5">
        <div className="relative h-[110px] w-[110px] shrink-0">
          <svg viewBox="0 0 100 100" className="h-full w-full -rotate-90">
            <circle
              cx="50"
              cy="50"
              r={radius}
              fill="none"
              stroke="hsl(var(--border))"
              strokeWidth="12"
            />
            {segments.map((seg) => (
              <circle
                key={seg.symbol}
                cx="50"
                cy="50"
                r={radius}
                fill="none"
                stroke={seg.color}
                strokeWidth="12"
                strokeDasharray={`${seg.dash} ${seg.gap}`}
                strokeDashoffset={-((seg.rotation / 360) * circumference)}
                strokeLinecap="butt"
              />
            ))}
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className="text-lg font-black text-foreground tabular-nums leading-none">
              {totalOpen}
            </span>
            <span className="tech-label mt-0.5">Open</span>
          </div>
        </div>

        <div className="flex-1 min-w-0">
          {totalOpen > 0 ? (
            <div className="space-y-1.5 mb-3">
              {segments.slice(0, 4).map((seg) => (
                <div key={seg.symbol} className="flex items-center gap-2 text-[11px]">
                  <span
                    className="h-2 w-2 rounded-full shrink-0"
                    style={{ backgroundColor: seg.color }}
                  />
                  <span className="text-foreground font-semibold truncate flex-1">
                    {seg.symbol}
                  </span>
                  <span className="text-muted-foreground tabular-nums">
                    {seg.pct.toFixed(0)}%
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-xs text-muted-foreground/70 mb-3">No open exposure</div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 mt-3 pt-3 border-t border-border/50">
        {rows.map((r) => (
          <div key={r.label} className="flex items-center justify-between">
            <span className="tech-label">{r.label}</span>
            <span className="text-xs font-bold text-foreground tabular-nums">{r.value}</span>
          </div>
        ))}
      </div>
    </WidgetCard>
  )
}
