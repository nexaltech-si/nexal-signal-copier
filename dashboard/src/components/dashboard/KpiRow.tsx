'use client'

import { useEffect, useState } from 'react'
import {
  TrendingUp,
  TrendingDown,
  Percent,
  Activity,
  Wallet,
  BrainCircuit,
  DollarSign,
  ArrowUpRight,
  ArrowDownRight,
} from 'lucide-react'
import { formatCurrency, cn } from '@/lib/utils'

interface KpiRowProps {
  totalProfitLoss: number
  winRate: number
  activeTrades: number
  totalTrades: number
  /** 0..1 confidence from latest market analysis, if available (server-provided). */
  aiConfidence?: number | null
}

interface TradingAccount {
  balance: number
  equity: number
  freeMargin: number
  currency: string
}

/** Top KPI strip — mirrors the mockup's row of summary tiles. */
export default function KpiRow({
  totalProfitLoss,
  winRate,
  activeTrades,
  totalTrades,
  aiConfidence,
}: KpiRowProps) {
  const [account, setAccount] = useState<TradingAccount | null>(null)

  useEffect(() => {
    let cancelled = false
    fetch('/api/balances')
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!cancelled && data?.metaapi_trading) setAccount(data.metaapi_trading)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [])

  const plPositive = totalProfitLoss >= 0
  const winGood = winRate >= 50
  const confPct =
    aiConfidence != null ? Math.round(aiConfidence * 100) : null

  type Tile = {
    label: string
    value: string
    sub?: string
    icon: typeof TrendingUp
    tone: 'success' | 'destructive' | 'gold' | 'primary' | 'foreground'
  }

  const tiles: Tile[] = [
    {
      label: "Today's P/L",
      value: formatCurrency(totalProfitLoss),
      icon: plPositive ? TrendingUp : TrendingDown,
      tone: plPositive ? 'success' : 'destructive',
    },
    {
      label: 'Win Rate',
      value: `${winRate.toFixed(0)}%`,
      icon: Percent,
      tone: winGood ? 'success' : 'gold',
    },
    {
      label: 'Open Trades',
      value: String(activeTrades),
      sub: `${totalTrades} total`,
      icon: Activity,
      tone: 'primary',
    },
    {
      label: 'Account Balance',
      value: account
        ? formatCurrency(account.balance, account.currency)
        : '—',
      sub: account
        ? `Equity ${formatCurrency(account.equity, account.currency)}`
        : undefined,
      icon: Wallet,
      tone: 'foreground',
    },
    {
      label: 'AI Confidence',
      value: confPct != null ? `${confPct}%` : '—',
      sub:
        confPct != null
          ? confPct >= 70
            ? 'High'
            : confPct >= 40
              ? 'Medium'
              : 'Low'
          : undefined,
      icon: BrainCircuit,
      tone: confPct != null && confPct >= 70 ? 'success' : 'primary',
    },
  ]

  // ── Mobile hero tiles (the 4 small cards under the P/L headline) ──
  const heroTiles: {
    label: string
    value: string
    sub?: string | null
    accent?: 'success' | 'destructive'
  }[] = [
    {
      label: 'Win',
      value: `${winRate.toFixed(1)}%`,
      accent: winGood ? 'success' : 'destructive',
    },
    {
      label: 'Open',
      value: String(activeTrades),
      sub: activeTrades > 0 ? `${activeTrades} live` : null,
    },
    {
      label: 'Balance',
      value: account ? formatCurrency(account.balance, account.currency) : '—',
    },
    {
      label: 'AI',
      value: confPct != null ? `${confPct}%` : '—',
      accent: confPct != null && confPct >= 70 ? 'success' : undefined,
    },
  ]

  return (
    <>
      {/* ── Mobile Hero (restored single-card animated layout) ── */}
      <section className="md:hidden tech-card rounded-[22px] p-5 relative z-10 overflow-hidden">
        {/* Top accent line */}
        <div
          className={cn(
            'absolute top-0 left-0 right-0 h-[2px]',
            plPositive
              ? 'bg-gradient-to-r from-transparent via-success/60 to-transparent'
              : 'bg-gradient-to-r from-transparent via-destructive/60 to-transparent',
          )}
        />

        <div className="flex justify-between items-start mb-[10px]">
          <div className="flex flex-col gap-[3px]">
            <div className="tech-label mb-1">P/L Overview</div>
            <div
              className={cn(
                'text-[32px] font-black leading-none tracking-[-0.05em] tabular-nums font-mono',
                plPositive ? 'text-success' : 'text-destructive',
              )}
            >
              {formatCurrency(totalProfitLoss)}
            </div>
            <div
              className={cn(
                'text-[11px] font-semibold flex items-center gap-1',
                plPositive ? 'text-success' : 'text-destructive',
              )}
            >
              {plPositive ? (
                <ArrowUpRight className="h-3 w-3" />
              ) : (
                <ArrowDownRight className="h-3 w-3" />
              )}
              {plPositive ? 'Profit' : 'Loss'}
            </div>
          </div>
          <div
            className={cn(
              'w-[38px] h-[38px] rounded-[11px] flex items-center justify-center border',
              plPositive
                ? 'bg-success/10 border-success/20 text-success'
                : 'bg-destructive/10 border-destructive/20 text-destructive',
            )}
          >
            <DollarSign className="w-[20px] h-[20px]" />
          </div>
        </div>

        <div className="grid grid-cols-4 gap-2 mt-4">
          {heroTiles.map(({ label, value, sub, accent }) => (
            <div
              key={label}
              className={cn(
                'bg-accent/50 border border-border/60 rounded-[16px] p-3',
                accent === 'success' && 'bg-success/5 border-success/20',
                accent === 'destructive' && 'bg-destructive/5 border-destructive/20',
              )}
            >
              <div className="tech-label mb-1">{label}</div>
              <div
                className={cn(
                  'text-[15px] font-black leading-none tracking-[-0.04em] tabular-nums font-mono mb-1 truncate',
                  accent === 'success' && 'text-success',
                  accent === 'destructive' && 'text-destructive',
                  !accent && 'text-foreground',
                )}
              >
                {value}
              </div>
              {sub && (
                <div className="text-[9px] font-bold text-primary animate-data-blink">
                  {sub}
                </div>
              )}
            </div>
          ))}
        </div>
      </section>

      {/* ── Desktop grid ── */}
      <div className="hidden md:grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
      {tiles.map(({ label, value, sub, icon: Icon, tone }) => (
        <div key={label} className="tech-card rounded-xl p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="tech-label">{label}</span>
            <Icon
              className={cn(
                'h-4 w-4',
                tone === 'success' && 'text-success',
                tone === 'destructive' && 'text-destructive',
                tone === 'gold' && 'text-gold',
                tone === 'primary' && 'text-primary',
                tone === 'foreground' && 'text-muted-foreground',
              )}
            />
          </div>
          <div
            className={cn(
              'text-xl md:text-2xl font-black tracking-tight tabular-nums font-mono leading-none',
              tone === 'success' && 'text-success',
              tone === 'destructive' && 'text-destructive',
              tone === 'gold' && 'text-gold',
              (tone === 'primary' || tone === 'foreground') && 'text-foreground',
            )}
          >
            {value}
          </div>
          {sub && (
            <div className="text-[10px] text-muted-foreground font-semibold mt-1.5 truncate">
              {sub}
            </div>
          )}
        </div>
      ))}
      </div>
    </>
  )
}
