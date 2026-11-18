'use client'

import { useState, useEffect, useCallback } from 'react'
import {
  Shield,
  TrendingDown,
  AlertTriangle,
  Activity,
  BarChart3,
  Layers,
} from 'lucide-react'
import { cn, formatCurrency } from '@/lib/utils'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface AccountInfo {
  balance: number
  equity: number
  margin: number
  margin_level: number
  profit: number
}

interface Position {
  ticket: number
  symbol: string
  type: 'BUY' | 'SELL' | 0 | 1
  volume: number
  profit: number
  price_open: number
  price_current: number
}

interface DrawdownData {
  liveDrawdown: {
    drawdownPercent: number
    balance: number
    equity: number
    drawdownAmount: number
    isInDrawdown: boolean
  } | null
  limits: {
    daily: number
    overall: number
  } | null
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

/** Convert MT5 position type number to string */
function posTypeLabel(t: number | string): string {
  if (t === 0 || t === 'BUY') return 'BUY'
  return 'SELL'
}

/** Conic-gradient for the margin-level gauge ring */
function marginGradient(pct: number): string {
  // Clamp between 0 and 1000 % for visual
  const clamped = Math.min(1000, Math.max(0, pct))
  const angle = (clamped / 1000) * 360
  //  green > 300, amber 100-300, red < 100
  const hue =
    pct >= 300 ? 142
    : pct >= 100 ? 38
    : 0
  return `conic-gradient(hsl(${hue} 76% 50%) ${angle}deg, hsl(${hue} 20% 85%) ${angle}deg)`
}

function marginColor(pct: number): string {
  if (pct >= 300) return 'text-success'
  if (pct >= 100) return 'text-gold'
  return 'text-destructive'
}

function marginBg(pct: number): string {
  if (pct >= 300) return 'bg-emerald-500/10'
  if (pct >= 100) return 'bg-amber-500/10'
  return 'bg-rose-500/10'
}

function drawdownColor(pct: number): string {
  if (pct <= 0) return 'text-success'
  if (pct < 1.5) return 'text-gold'
  return 'text-destructive'
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function RiskOverview() {
  const [account, setAccount] = useState<AccountInfo | null>(null)
  const [positions, setPositions] = useState<Position[]>([])
  const [drawdown, setDrawdown] = useState<DrawdownData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  /* ---- fetch all data in parallel ---- */
  const fetchAll = useCallback(async () => {
    try {
      const [acctRes, posRes, ddRes] = await Promise.allSettled([
        fetch('/api/mt5/account', { cache: 'no-store' }),
        fetch('/api/mt5/positions', { cache: 'no-store' }),
        fetch('/api/drawdown?limit=1', { cache: 'no-store' }),
      ])

      // Account
      if (acctRes.status === 'fulfilled' && acctRes.value.ok) {
        const json = await acctRes.value.json()
        setAccount({
          balance: json.balance ?? 0,
          equity: json.equity ?? 0,
          margin: json.margin ?? 0,
          margin_level: json.margin_level ?? json.marginLevel ?? 0,
          profit: json.profit ?? 0,
        })
      }

      // Positions
      if (posRes.status === 'fulfilled' && posRes.value.ok) {
        const json = await posRes.value.json()
        const list: Position[] = Array.isArray(json)
          ? json
          : json.positions ?? json.data ?? []
        setPositions(list)
      }

      // Drawdown
      if (ddRes.status === 'fulfilled' && ddRes.value.ok) {
        const json = await ddRes.value.json()
        if (json.success && json.data) {
          setDrawdown({
            liveDrawdown: json.data.liveDrawdown ?? null,
            limits: json.data.limits ?? null,
          })
        }
      }

      setError(null)
    } catch {
      setError('Failed to load risk metrics')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchAll()
    const interval = setInterval(fetchAll, 10_000)
    return () => clearInterval(interval)
  }, [fetchAll])

  /* ---- derived values ---- */
  const totalExposure = positions.reduce((s, p) => s + (p.volume ?? 0), 0)
  const activeCount = positions.length
  const unrealizedPnL = account ? account.equity - account.balance : 0
  const isProfitable = unrealizedPnL >= 0
  const equityPct =
    account && account.balance > 0
      ? (account.equity / account.balance) * 100
      : 100

  const dailyDdPct = drawdown?.liveDrawdown?.drawdownPercent ?? 0
  const dailyDdLimit = drawdown?.limits?.daily ?? 3

  /* ---- loading state ---- */
  if (loading) {
    return (
      <div className="glass-morphism rounded-2xl p-5">
        <div className="flex items-center gap-2 text-xs text-muted-foreground/70">
          <Activity className="h-3 w-3 animate-spin" />
          Loading risk metrics…
        </div>
      </div>
    )
  }

  /* ---- error state ---- */
  if (error && !account && positions.length === 0) {
    return (
      <div className="glass-morphism rounded-2xl p-5">
        <div className="flex items-center gap-2 text-xs text-destructive/80">
          <AlertTriangle className="h-3 w-3" />
          {error}
        </div>
      </div>
    )
  }

  /* ================================================================ */
  /*  RENDER                                                           */
  /* ================================================================ */
  return (
    <div className="glass-morphism rounded-2xl overflow-hidden">
      {/* Header with subtle glow */}
      <div className="relative px-5 pt-4 pb-3 border-b border-white/5">
        <div className="glow-effect" />
        <div className="relative z-10 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-lg bg-primary/10">
              <Shield className="h-4 w-4 text-primary" />
            </div>
            <div>
              <h3 className="text-[11px] font-bold text-white/80 uppercase tracking-[0.04em]">
                Risk Overview
              </h3>
              <p className="text-[9px] text-white/40 font-medium mt-0.5">
                Real-time metrics
              </p>
            </div>
          </div>

          {/* Live dot */}
          <div className="flex items-center gap-1.5">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
            </span>
            <span className="text-[9px] font-bold text-success/80/80 uppercase tracking-wider">
              Live
            </span>
          </div>
        </div>
      </div>

      <div className="p-5 space-y-5">
        {/* ----- Row 1: Balance vs Equity ----- */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] font-bold text-white/50 uppercase tracking-wider">
              Balance vs Equity
            </span>
            <span
              className={cn(
                'text-[10px] font-bold tabular-nums',
                isProfitable ? 'text-success/80' : 'text-destructive/80',
              )}
            >
              {isProfitable ? '+' : ''}
              {formatCurrency(unrealizedPnL)} unrealized
            </span>
          </div>

          <div className="space-y-1.5">
            {/* Balance row */}
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-white/60 font-semibold">
                Balance
              </span>
              <span className="text-sm font-bold text-white tabular-nums">
                {formatCurrency(account?.balance ?? 0)}
              </span>
            </div>

            {/* Equity bar */}
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-white/60 font-semibold">
                Equity
              </span>
              <span
                className={cn(
                  'text-sm font-bold tabular-nums',
                  isProfitable ? 'text-success/80' : 'text-destructive/80',
                )}
              >
                {formatCurrency(account?.equity ?? 0)}
              </span>
            </div>

            {/* Visual bar */}
            <div className="relative h-2.5 w-full rounded-full overflow-hidden bg-white/5">
              {/* Background track showing 100 % = balance */}
              <div
                className="absolute inset-y-0 left-0 rounded-full bg-white/10"
                style={{ width: '100%' }}
              />
              {/* Equity indicator */}
              <div
                className={cn(
                  'absolute inset-y-0 left-0 rounded-full transition-all duration-700',
                  isProfitable
                    ? 'bg-gradient-to-r from-primary/60 to-emerald-500/60'
                    : 'bg-gradient-to-r from-primary/60 to-rose-500/60',
                )}
                style={{ width: `${Math.min(equityPct, 100)}%` }}
              />
            </div>

            {/* Sub-labels */}
            <div className="flex justify-between text-[9px] text-white/30 font-medium">
              <span>{formatCurrency(account?.balance ?? 0)}</span>
              <span className={isProfitable ? 'text-success/80/60' : 'text-destructive/80/60'}>
                {equityPct.toFixed(1)}%
              </span>
            </div>
          </div>
        </div>

        {/* ----- Row 2: Margin Level Gauge + Exposure + Positions ----- */}
        <div className="grid grid-cols-2 gap-4">
          {/* Margin Level Gauge */}
          <div>
            <div className="flex items-center justify-between mb-2.5">
              <span className="text-[10px] font-bold text-white/50 uppercase tracking-wider flex items-center gap-1.5">
                <Layers className="h-3 w-3" />
                Margin Level
              </span>
            </div>

            <div className="flex items-center gap-3">
              {/* Ring gauge */}
              <div className="relative shrink-0">
                <svg className="w-14 h-14 -rotate-90" viewBox="0 0 56 56">
                  <circle
                    cx="28"
                    cy="28"
                    r="23"
                    fill="none"
                    stroke="rgba(255,255,255,0.06)"
                    strokeWidth="5"
                  />
                  <circle
                    cx="28"
                    cy="28"
                    r="23"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="5"
                    strokeLinecap="round"
                    strokeDasharray={`${Math.min((account?.margin_level ?? 0) / 1000, 1) * 144.5} 144.5`}
                    className={marginColor(account?.margin_level ?? 0)}
                  />
                </svg>
                <div className="absolute inset-0 flex items-center justify-center">
                  <span
                    className={cn(
                      'text-[11px] font-black tabular-nums',
                      marginColor(account?.margin_level ?? 0),
                    )}
                  >
                    {account?.margin_level != null
                      ? account.margin_level.toFixed(0)
                      : '—'}
                  </span>
                </div>
              </div>

              {/* Label */}
              <div className="min-w-0">
                <span
                  className={cn(
                    'text-[10px] font-bold px-1.5 py-0.5 rounded-full',
                    marginBg(account?.margin_level ?? 0),
                    marginColor(account?.margin_level ?? 0),
                  )}
                >
                  {account?.margin_level != null
                    ? account.margin_level >= 300
                      ? 'Safe'
                      : account.margin_level >= 100
                        ? 'Caution'
                        : 'Critical'
                    : '—'}
                </span>
                {account?.margin != null && (
                  <p className="text-[9px] text-white/30 font-medium mt-1 truncate">
                    Margin {formatCurrency(account.margin)}
                  </p>
                )}
              </div>
            </div>
          </div>

          {/* Total Exposure */}
          <div>
            <div className="flex items-center justify-between mb-2.5">
              <span className="text-[10px] font-bold text-white/50 uppercase tracking-wider flex items-center gap-1.5">
                <BarChart3 className="h-3 w-3" />
                Exposure
              </span>
            </div>
            <div className="flex flex-col">
              <span className="text-xl font-black text-white tabular-nums leading-none">
                {totalExposure.toFixed(2)}
              </span>
              <span className="text-[9px] text-white/30 font-medium mt-1">
                Total lots
              </span>
            </div>
          </div>
        </div>

        {/* ----- Row 3: Active Positions + Daily Drawdown ----- */}
        <div className="grid grid-cols-2 gap-4 pt-2">
          {/* Active Positions */}
          <div className="bg-white/5 rounded-xl p-3 border border-white/5">
            <div className="flex items-center justify-between mb-2">
              <span className="text-[9px] font-bold text-white/40 uppercase tracking-wider flex items-center gap-1">
                <Activity className="h-3 w-3" />
                Active
              </span>
              {activeCount > 0 && (
                <span className="relative flex h-1.5 w-1.5">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-500" />
                </span>
              )}
            </div>
            <span className="text-xl font-black text-white tabular-nums leading-none">
              {activeCount}
            </span>
            <span className="text-[9px] text-white/30 font-medium block mt-1">
              {activeCount === 1 ? 'position' : 'positions'}
            </span>
          </div>

          {/* Daily Drawdown */}
          <div className={cn(
            'rounded-xl p-3 border',
            dailyDdPct >= dailyDdLimit * 0.8
              ? 'bg-rose-500/10 border-rose-500/20'
              : dailyDdPct > 0
                ? 'bg-amber-500/10 border-amber-500/20'
                : 'bg-emerald-500/10 border-emerald-500/20',
          )}>
            <div className="flex items-center justify-between mb-2">
              <span className="text-[9px] font-bold text-white/40 uppercase tracking-wider flex items-center gap-1">
                <TrendingDown className="h-3 w-3" />
                Daily DD
              </span>
              {dailyDdPct >= dailyDdLimit * 0.8 && (
                <AlertTriangle className="h-3 w-3 text-destructive/80 animate-pulse" />
              )}
            </div>
            <span
              className={cn(
                'text-xl font-black tabular-nums leading-none',
                drawdownColor(dailyDdPct),
              )}
            >
              {dailyDdPct.toFixed(2)}%
            </span>
            <span className="text-[9px] text-white/30 font-medium block mt-1">
              of {dailyDdLimit}% limit
            </span>
            {/* Mini progress bar */}
            <div className="mt-2 h-1 w-full bg-white/5 rounded-full overflow-hidden">
              <div
                className={cn(
                  'h-full rounded-full transition-all duration-500',
                  dailyDdPct >= dailyDdLimit * 0.8
                    ? 'bg-rose-500'
                    : dailyDdPct > 0
                      ? 'bg-amber-500'
                      : 'bg-emerald-500',
                )}
                style={{
                  width: `${Math.min((dailyDdPct / dailyDdLimit) * 100, 100)}%`,
                }}
              />
            </div>
          </div>
        </div>

        {/* ----- Positions detail (if any) ----- */}
        {activeCount > 0 && (
          <div className="pt-2 border-t border-white/5">
            <div className="flex items-center gap-3 text-[9px] font-bold text-white/30 uppercase tracking-wider mb-2">
              <span className="flex-1">Symbol</span>
              <span className="w-10 text-right">Type</span>
              <span className="w-14 text-right">Volume</span>
              <span className="w-20 text-right">P&L</span>
            </div>
            <div className="space-y-1 max-h-[160px] overflow-y-auto scrollbar-thin">
              {positions.slice(0, 20).map((p) => (
                <div
                  key={p.ticket}
                  className="flex items-center gap-3 text-[11px] font-semibold text-white/70"
                >
                  <span className="flex-1 truncate">{p.symbol}</span>
                  <span
                    className={cn(
                      'w-10 text-right text-[9px] font-bold',
                      posTypeLabel(p.type) === 'BUY'
                        ? 'text-success/80'
                        : 'text-destructive/80',
                    )}
                  >
                    {posTypeLabel(p.type)}
                  </span>
                  <span className="w-14 text-right tabular-nums">
                    {p.volume?.toFixed(2)}
                  </span>
                  <span
                    className={cn(
                      'w-20 text-right tabular-nums font-bold',
                      (p.profit ?? 0) >= 0 ? 'text-success/80' : 'text-destructive/80',
                    )}
                  >
                    {(p.profit ?? 0) >= 0 ? '+' : ''}
                    {formatCurrency(p.profit ?? 0)}
                  </span>
                </div>
              ))}
            </div>
            {positions.length > 20 && (
              <p className="text-[9px] text-white/20 font-medium text-center mt-2">
                +{positions.length - 20} more
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
