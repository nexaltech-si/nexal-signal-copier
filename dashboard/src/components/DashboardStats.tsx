'use client'

import { TrendingUp, Activity, DollarSign, Zap, BarChart3, ArrowUpRight, ArrowDownRight } from 'lucide-react'
import { formatCurrency, cn } from '@/lib/utils'

interface DashboardStatsProps {
  stats: {
    totalSignals: number
    totalTrades: number
    activeTrades: number
    closedTrades: number
    totalActions: number
    totalProfitLoss: number
    winRate: number
  }
  recentPLHistory?: number[]
  recentSignalHistory?: number[]
  signalsDelta?: number
  tradesDelta?: number
  winRateDelta?: number
  recentActions?: { type: string; symbol: string; at: string }[]
}

function DeltaBadge({ delta }: { delta: number }) {
  if (delta === 0) return null
  const up = delta > 0
  return (
    <span className={cn(
      'text-[9px] font-bold flex items-center gap-0.5',
      up ? 'text-success' : 'text-destructive'
    )}>
      {up ? <ArrowUpRight className="h-2.5 w-2.5" /> : <ArrowDownRight className="h-2.5 w-2.5" />}
      {Math.abs(delta)}
    </span>
  )
}

export default function DashboardStats({
  stats,
  recentPLHistory,
  recentSignalHistory,
  signalsDelta = 0,
  tradesDelta = 0,
  winRateDelta = 0,
  recentActions,
}: DashboardStatsProps) {
  const isPositive = stats.totalProfitLoss >= 0
  const winRateGood = stats.winRate >= 50
  const winRatePct = Math.min(100, Math.max(0, stats.winRate))

  // TODO: replace with real history endpoint when available
  const plHistory = recentPLHistory ?? [0.3, 0.45, 0.35, 0.6, 0.55, 0.75, isPositive ? 0.9 : 0.2]
  const signalHistory = recentSignalHistory ?? [0.4, 0.5, 0.6, 0.45, 0.7, 0.8, 0.75]

  return (
    <>
      {/* ── Mobile Hero ── */}
      <section className="md:hidden tech-card rounded-[22px] p-5 mb-1 relative z-10 overflow-hidden">
        {/* Top accent line */}
        <div className={cn(
          "absolute top-0 left-0 right-0 h-[2px]",
          isPositive
            ? "bg-gradient-to-r from-transparent via-success/60 to-transparent"
            : "bg-gradient-to-r from-transparent via-destructive/60 to-transparent"
        )} />

        <div className="flex justify-between items-start mb-[10px]">
          <div className="flex flex-col gap-[3px]">
            <div className="tech-label mb-1">P/L Overview</div>
            <div className={cn(
              "text-[32px] font-black leading-none tracking-[-0.05em] tabular-nums font-mono",
              isPositive ? "text-success" : "text-destructive"
            )}>
              {formatCurrency(stats.totalProfitLoss)}
            </div>
            <div className={cn(
              "text-[11px] font-semibold flex items-center gap-1",
              isPositive ? "text-success" : "text-destructive"
            )}>
              {isPositive
                ? <ArrowUpRight className="h-3 w-3" />
                : <ArrowDownRight className="h-3 w-3" />}
              {isPositive ? 'Profit' : 'Loss'}
            </div>
          </div>
          <div className={cn(
            "w-[38px] h-[38px] rounded-[11px] flex items-center justify-center border",
            isPositive
              ? "bg-success/10 border-success/20 text-success"
              : "bg-destructive/10 border-destructive/20 text-destructive"
          )}>
            <DollarSign className="w-[20px] h-[20px]" />
          </div>
        </div>

        <div className="grid grid-cols-4 gap-2 mt-4">
          {[
            { label: 'Signals', value: stats.totalSignals },
            { label: 'Trades', value: stats.totalTrades, sub: stats.activeTrades > 0 ? `${stats.activeTrades} live` : null },
            {
              label: 'Win',
              value: `${stats.winRate.toFixed(1)}%`,
              accent: winRateGood ? 'success' : 'destructive',
            },
            { label: 'Acts', value: stats.totalActions },
          ].map(({ label, value, sub, accent }) => (
            <div
              key={label}
              className={cn(
                "bg-accent/50 border border-border/60 rounded-[16px] p-3",
                accent === 'success' && "bg-success/5 border-success/20",
                accent === 'destructive' && "bg-destructive/5 border-destructive/20",
              )}
            >
              <div className="tech-label mb-1">{label}</div>
              <div className={cn(
                "text-[17px] font-black leading-none tracking-[-0.04em] tabular-nums font-mono mb-1",
                accent === 'success' && "text-success",
                accent === 'destructive' && "text-destructive",
                !accent && "text-foreground"
              )}>{value}</div>
              {sub && <div className="text-[9px] font-bold text-primary animate-data-blink">{sub}</div>}
            </div>
          ))}
        </div>
      </section>

      {/* ── Desktop Grid ── */}
      <div className="hidden md:grid gap-3 grid-cols-2 md:grid-cols-3 lg:grid-cols-5 mb-6">

        {/* P/L Card */}
        <div className={cn(
          "tech-card rounded-xl p-4 relative overflow-hidden",
          isPositive ? "tech-card-emerald" : "tech-card-rose"
        )}>
          <div className="flex items-center justify-between mb-3">
            <div className={cn(
              "p-2 rounded-lg border",
              isPositive
                ? "bg-success/10 border-success/20"
                : "bg-destructive/10 border-destructive/20"
            )}>
              <DollarSign className={cn("h-4 w-4", isPositive ? "text-success" : "text-destructive")} />
            </div>
            <span className={cn(
              "flex items-center gap-0.5 text-[10px] font-bold px-2 py-0.5 rounded-full border",
              isPositive
                ? "bg-success/10 border-success/20 text-success"
                : "bg-destructive/10 border-destructive/20 text-destructive"
            )}>
              {isPositive
                ? <ArrowUpRight className="h-3 w-3" />
                : <ArrowDownRight className="h-3 w-3" />}
              {isPositive ? 'Profit' : 'Loss'}
            </span>
          </div>
          <div className={cn(
            "text-xl font-black tracking-tight tabular-nums font-mono",
            isPositive ? "text-success" : "text-destructive"
          )}>
            {formatCurrency(stats.totalProfitLoss)}
          </div>
          <div className="tech-label mt-1">Total P/L</div>
          {plHistory.length > 1 && (
            <svg
              viewBox={`0 0 ${plHistory.length - 1} 1`}
              preserveAspectRatio="none"
              className="w-full h-6 mt-2"
            >
              <polyline
                points={plHistory.map((v, i) => `${i},${1 - v}`).join(' ')}
                fill="none"
                stroke={isPositive ? 'hsl(var(--success))' : 'hsl(var(--destructive))'}
                strokeWidth="0.08"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          )}
        </div>

        {/* Win Rate Card */}
        <div className="tech-card tech-card-blue rounded-xl p-4">
          <div className="flex items-center justify-between mb-3">
            <div className="p-2 rounded-lg bg-primary/10 border border-primary/20">
              <BarChart3 className="h-4 w-4 text-primary" />
            </div>
            <span className={cn(
              "text-[10px] font-bold px-2 py-0.5 rounded-full border",
              winRateGood
                ? "bg-success/10 border-success/20 text-success"
                : "bg-gold/10 border-gold/20 text-gold"
            )}>
              {winRateGood ? 'Good' : 'Low'}
            </span>
          </div>
          <div className={cn(
            "text-xl font-black tracking-tight tabular-nums font-mono",
            winRateGood ? "text-success" : "text-gold"
          )}>
            {stats.winRate.toFixed(1)}%
          </div>
          <div className="tech-label mt-1 mb-2">Win Rate</div>
          <DeltaBadge delta={winRateDelta} />
          {/* Neon progress bar */}
          <div className="w-full h-2.5 bg-border rounded-full overflow-hidden mt-1">
            <div
              className={cn(
                "h-full rounded-full transition-all flex items-center justify-end pr-1.5",
                winRateGood ? "bg-success shadow-[0_0_6px_rgba(36,200,122,0.6)]" : "bg-gold shadow-[0_0_6px_rgba(251,191,36,0.5)]"
              )}
              style={{ width: `${winRatePct}%` }}
            >
              {winRatePct > 30 && (
                <span className="text-[8px] font-black text-white/80">
                  {stats.winRate.toFixed(0)}%
                </span>
              )}
            </div>
          </div>
          <div className="flex justify-between text-[9px] text-muted-foreground/60 font-mono font-semibold mt-1">
            <span>0</span><span>50</span><span>100</span>
          </div>
        </div>

        {/* Signals Card */}
        <div className="tech-card rounded-xl p-4">
          <div className="flex items-center justify-between mb-3">
            <div className="p-2 rounded-lg bg-primary/10 border border-primary/20">
              <Activity className="h-4 w-4 text-primary" />
            </div>
          </div>
          <div className="text-xl font-black tracking-tight text-foreground tabular-nums font-mono">
            {stats.totalSignals}
          </div>
          <div className="tech-label mt-1">Signals</div>
          <DeltaBadge delta={signalsDelta} />
          {signalHistory.length > 1 && (
            <svg
              viewBox={`0 0 ${signalHistory.length - 1} 1`}
              preserveAspectRatio="none"
              className="w-full h-5 mt-2"
            >
              <polyline
                points={signalHistory.map((v, i) => `${i},${1 - v}`).join(' ')}
                fill="none"
                stroke="hsl(var(--primary))"
                strokeWidth="0.08"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          )}
        </div>

        {/* Trades Card */}
        <div className="tech-card rounded-xl p-4">
          <div className="flex items-center justify-between mb-3">
            <div className="p-2 rounded-lg bg-primary/10 border border-primary/20">
              <TrendingUp className="h-4 w-4 text-primary" />
            </div>
            {stats.activeTrades > 0 && (
              <span className="flex items-center gap-1.5 text-[10px] font-bold px-2 py-0.5 rounded-full bg-primary/10 border border-primary/20 text-primary">
                <span className="relative flex h-1.5 w-1.5">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75" />
                  <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-primary" />
                </span>
                {stats.activeTrades} live
              </span>
            )}
          </div>
          <div className="text-xl font-black tracking-tight text-foreground tabular-nums font-mono">
            {stats.totalTrades}
          </div>
          <div className="tech-label mt-1">Total Trades</div>
          <DeltaBadge delta={tradesDelta} />
          {stats.closedTrades > 0 && (
            <div className="flex items-center gap-3 mt-2 pt-2 border-t border-border/50">
              <div className="text-[9px] text-muted-foreground font-mono font-semibold">
                <span className="text-foreground font-bold">{stats.closedTrades}</span> closed
              </div>
              {stats.activeTrades > 0 && (
                <div className="text-[9px] text-primary font-mono font-semibold">
                  <span className="font-bold">{stats.activeTrades}</span> active
                </div>
              )}
            </div>
          )}
        </div>

        {/* Actions Card */}
        <div className="tech-card tech-card-gold rounded-xl p-4">
          <div className="flex items-center justify-between mb-3">
            <div className="p-2 rounded-lg bg-gold/10 border border-gold/20">
              <Zap className="h-4 w-4 text-gold" />
            </div>
          </div>
          <div className="text-xl font-black tracking-tight text-foreground tabular-nums font-mono">
            {stats.totalActions}
          </div>
          <div className="tech-label mt-1">AI Actions</div>
          <div className="text-[9px] text-muted-foreground font-medium mt-1">
            Trade modifications
          </div>
          {recentActions && recentActions.length > 0 && (
            <div className="mt-2 pt-2 border-t border-border/50 space-y-1">
              {recentActions.slice(0, 2).map((a, i) => (
                <div key={i} className="flex items-center gap-1.5 text-[9px] text-muted-foreground font-mono">
                  <span className="text-gold font-bold">{a.type}</span>
                  <span>{a.symbol}</span>
                  <span className="ml-auto opacity-50">{a.at}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  )
}
