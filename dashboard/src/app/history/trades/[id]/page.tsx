'use client'

import { useState, useEffect, use } from 'react'
import Link from 'next/link'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { formatDate, getStatusColor, formatCurrency, formatPips } from '@/lib/utils'
import {
  ArrowLeft,
  TrendingUp,
  TrendingDown,
  Clock,
  MessageSquare,
  Loader2,
  Activity,
  Brain,
  Sparkles,
  AlertTriangle,
  AlertCircle,
  Hash,
  Radio,
  CheckCircle2,
  XCircle,
  Edit,
  Scissors,
  X,
  Info,
  RefreshCw,
  Database,
} from 'lucide-react'
import TelegramText from '@/components/TelegramText'

export default function TradeDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const resolvedParams = use(params)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [trade, setTrade] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [lifecycleData, setLifecycleData] = useState<any>(null)
  const [lifecycleLoading, setLifecycleLoading] = useState(false)
  const [lifecycleError, setLifecycleError] = useState<string | null>(null)

  const fetchLifecycle = async () => {
    if (!trade?.positionId) { setLifecycleError('Trade has no position ID'); return }
    setLifecycleLoading(true); setLifecycleError(null)
    try {
      const response = await fetch(`/api/trades/${resolvedParams.id}/lifecycle`)
      if (!response.ok) throw new Error('Failed to fetch lifecycle data')
      setLifecycleData(await response.json())
    } catch (err) {
      setLifecycleError(err instanceof Error ? err.message : 'Failed to fetch lifecycle')
    } finally {
      setLifecycleLoading(false)
    }
  }

  useEffect(() => {
    fetch(`/api/trades/${resolvedParams.id}`)
      .then(res => { if (!res.ok) throw new Error('Trade not found'); return res.json() })
      .then(data => { setTrade(data); setLoading(false) })
      .catch(err => { setError(err.message); setLoading(false) })
  }, [resolvedParams.id])

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="flex items-center gap-3 text-muted-foreground/70">
          <Loader2 className="h-5 w-5 animate-spin" />
          <span>Loading trade details...</span>
        </div>
      </div>
    )
  }

  if (error || !trade) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4">
        <AlertTriangle className="h-10 w-10 text-destructive" />
        <p className="text-muted-foreground">{error || 'Trade not found'}</p>
        <Link href="/history">
          <Button variant="outline" size="sm">
            <ArrowLeft className="h-3.5 w-3.5 mr-1.5" />
            Back to History
          </Button>
        </Link>
      </div>
    )
  }

  const isBuy = trade.action?.toUpperCase().includes('BUY')
  const hasAI = trade.marketAnalyses && trade.marketAnalyses.length > 0
  const latestAnalysis = hasAI ? trade.marketAnalyses[0] : null
  const pnl = trade.profitLoss !== null && trade.profitLoss !== undefined ? Number(trade.profitLoss) : null
  const pips = trade.profitLossPips !== null && trade.profitLossPips !== undefined ? Number(trade.profitLossPips) : null

  const getActionIcon = (actionType: string) => {
    switch (actionType) {
      case 'CLOSE': return <X className="h-3 w-3" />
      case 'PARTIAL_CLOSE': case 'AUTO_PARTIAL': return <Scissors className="h-3 w-3" />
      case 'MODIFY_SL': case 'MODIFY_TP': return <Edit className="h-3 w-3" />
      case 'TRAILING_STOP': case 'BREAKEVEN': return <TrendingUp className="h-3 w-3" />
      default: return <Activity className="h-3 w-3" />
    }
  }

  const getActionColor = (actionType: string) => {
    const m: Record<string, string> = {
      CLOSE: 'bg-destructive/10 text-destructive border border-destructive/20',
      PARTIAL_CLOSE: 'bg-gold/10 text-gold border border-gold/20',
      AUTO_PARTIAL: 'bg-gold/10 text-gold border border-gold/20',
      MODIFY_SL: 'bg-gold/10 text-gold border border-gold/20',
      MODIFY_TP: 'bg-primary/10 text-primary border border-primary/20',
      TRAILING_STOP: 'bg-success/10 text-success border border-success/20',
      BREAKEVEN: 'bg-success/10 text-success border border-success/20',
      AUTO_TP: 'bg-accent text-muted-foreground border border-border',
    }
    return m[actionType] || 'bg-muted text-foreground/80'
  }

  const getTriggerColor = (triggeredBy: string) => {
    const m: Record<string, string> = {
      telegram_reply: 'bg-primary/10 text-primary border border-primary/20',
      telegram_message: 'bg-primary/10 text-primary border border-primary/20',
      system: 'bg-muted text-muted-foreground',
      auto_trailing: 'bg-success/10 text-success border border-success/20',
      auto_breakeven: 'bg-gold/10 text-gold border border-gold/20',
      auto_tp: 'bg-accent text-muted-foreground border border-border',
      auto_position_monitor: 'bg-accent text-foreground/80 border border-border',
      manual: 'bg-gold/10 text-gold border border-gold/20',
    }
    return m[triggeredBy] || m.system
  }

  return (
    <div className="flex min-h-full flex-col pt-[80px] md:pt-0 pb-24 md:pb-0">

      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <header className="sticky top-[80px] md:top-0 z-40 w-full tech-header">
        <div className="flex h-12 items-center px-4 md:px-6 gap-3 max-w-[1400px] mx-auto">
          <Link href={trade.signal ? `/history/signals/${trade.signal.id}` : '/history'}>
            <div className="flex items-center justify-center w-7 h-7 rounded-full bg-muted hover:bg-primary/10 transition-colors cursor-pointer group mr-1">
              <ArrowLeft className="h-3.5 w-3.5 text-muted-foreground group-hover:text-primary" />
            </div>
          </Link>
          <div className={`flex items-center justify-center w-6 h-6 rounded-md flex-shrink-0 ${isBuy ? 'bg-success/10' : 'bg-destructive/10'}`}>
            {isBuy ? <TrendingUp className="h-3 w-3 text-success" /> : <TrendingDown className="h-3 w-3 text-destructive" />}
          </div>
          <h1 className="text-sm font-bold text-foreground truncate">{trade.symbol}</h1>
          <Badge variant="outline" className="text-[10px] h-5 flex-shrink-0 border-border">{trade.action}</Badge>
          <Badge className={`${getStatusColor(trade.status)} text-[10px] h-5 flex-shrink-0`}>{trade.status}</Badge>
          {trade.tpLevel && (
            <Badge variant="outline" className="text-[10px] h-5 bg-primary/10 text-primary border-primary/30 flex-shrink-0">TP{trade.tpLevel}</Badge>
          )}
          {pnl !== null && (
            <span className={`ml-auto text-sm font-bold ${pnl >= 0 ? 'text-success' : 'text-destructive'}`}>
              {formatCurrency(pnl)}
            </span>
          )}
        </div>
      </header>

      {/* ── Content ────────────────────────────────────────────────────────── */}
      <div className="flex-1 px-4 md:px-6 py-4 max-w-[1400px] mx-auto w-full space-y-4">

        {/* Error alert */}
        {trade.executionError && (
          <div className="flex items-start gap-3 p-3 rounded-xl bg-destructive/10 border border-destructive/30">
            <AlertCircle className="h-5 w-5 text-destructive flex-shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-semibold text-destructive">Execution Error</p>
              <p className="text-sm text-destructive">{trade.executionError}</p>
            </div>
          </div>
        )}

        {/* ── Key metrics row ─────────────────────────────────────────────── */}
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
          <div className="tech-card rounded-xl p-3">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70 mb-1">Entry</p>
            <p className="text-base font-bold font-mono text-foreground">{trade.entryPrice?.toFixed(5) || '—'}</p>
          </div>
          <div className="tech-card rounded-xl p-3">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70 mb-1">Close</p>
            <p className="text-base font-bold font-mono text-foreground">{trade.closePrice?.toFixed(5) || '—'}</p>
          </div>
          <div className="tech-card rounded-xl p-3">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70 mb-1">Stop Loss</p>
            <p className="text-base font-bold font-mono text-destructive">{trade.stopLoss?.toFixed(5) || '—'}</p>
          </div>
          <div className="tech-card rounded-xl p-3">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70 mb-1">Take Profit</p>
            <p className="text-base font-bold font-mono text-success">{trade.takeProfit?.toFixed(5) || '—'}</p>
          </div>
          <div className="tech-card rounded-xl p-3">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70 mb-1">Lot Size</p>
            <p className="text-base font-bold font-mono text-foreground">{trade.lotSize.toFixed(2)}</p>
          </div>
          {pnl !== null ? (
            <div className={`rounded-xl border shadow-sm p-3 ${pnl >= 0 ? 'bg-success/10 border-success/30' : 'bg-destructive/10 border-destructive/30'}`}>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70 mb-1">P / L</p>
              <p className={`text-base font-bold ${pnl >= 0 ? 'text-success' : 'text-destructive'}`}>
                {formatCurrency(pnl)}
              </p>
              {pips !== null && (
                <p className={`text-xs ${pips >= 0 ? 'text-success' : 'text-destructive'}`}>{formatPips(pips)}</p>
              )}
            </div>
          ) : (
            <div className="tech-card rounded-xl p-3">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70 mb-1">P / L</p>
              <p className="text-base font-bold text-muted-foreground/50">—</p>
            </div>
          )}
        </div>

        {/* ── Position info strip ────────────────────────────────────────── */}
        <div className="flex flex-wrap gap-2">
          <div className="flex items-center gap-1.5 bg-card border border-border rounded-lg px-2.5 py-1.5 text-xs shadow-sm">
            <span className="text-muted-foreground/70">Lots:</span>
            <span className="font-semibold text-foreground/90">{trade.lotSize.toFixed(2)}</span>
          </div>
          {trade.orderId && (
            <div className="flex items-center gap-1.5 bg-card border border-border rounded-lg px-2.5 py-1.5 text-xs shadow-sm">
              <Hash className="h-3 w-3 text-muted-foreground/70" />
              <span className="text-muted-foreground/70">Order:</span>
              <span className="font-mono font-semibold text-foreground/90">{trade.orderId}</span>
            </div>
          )}
          {trade.positionId && (
            <div className="flex items-center gap-1.5 bg-card border border-border rounded-lg px-2.5 py-1.5 text-xs shadow-sm">
              <span className="text-muted-foreground/70">Position:</span>
              <span className="font-mono font-semibold text-foreground/90">{trade.positionId}</span>
            </div>
          )}
          <div className="flex items-center gap-1.5 bg-card border border-border rounded-lg px-2.5 py-1.5 text-xs shadow-sm">
            <Clock className="h-3 w-3 text-muted-foreground/70" />
            <span className="text-muted-foreground/70">Created:</span>
            <span className="font-semibold text-foreground/90">{formatDate(trade.createdAt)}</span>
          </div>
          {trade.executedAt && (
            <div className="flex items-center gap-1.5 bg-card border border-border rounded-lg px-2.5 py-1.5 text-xs shadow-sm">
              <CheckCircle2 className="h-3 w-3 text-success" />
              <span className="text-muted-foreground/70">Executed:</span>
              <span className="font-semibold text-foreground/90">{formatDate(trade.executedAt)}</span>
            </div>
          )}
          {trade.closedAt && (
            <div className="flex items-center gap-1.5 bg-card border border-border rounded-lg px-2.5 py-1.5 text-xs shadow-sm">
              <XCircle className="h-3 w-3 text-muted-foreground/70" />
              <span className="text-muted-foreground/70">Closed:</span>
              <span className="font-semibold text-foreground/90">{formatDate(trade.closedAt)}</span>
            </div>
          )}
        </div>

        {/* ── 2-column main grid ─────────────────────────────────────────── */}
        <div className="grid lg:grid-cols-2 gap-4">

          {/* Left column: Trade actions */}
          <div className="flex flex-col gap-3">

            {/* Trade actions */}
            {trade.tradeActions && trade.tradeActions.length > 0 && (
              <div className="tech-card rounded-xl overflow-hidden">
                <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border bg-muted/50">
                  <Activity className="h-3.5 w-3.5 text-muted-foreground" />
                  <span className="text-xs font-semibold text-foreground/80">Trade Actions ({trade.tradeActions.length})</span>
                </div>
                <div className="divide-y divide-border max-h-[500px] overflow-y-auto">
                  {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                  {trade.tradeActions.map((action: any) => {
                    const userCommand = action.details?.match(/User reply: "([^"]+)"/)?.[1]
                    return (
                      <div key={action.id} className="px-4 py-3">
                        <div className="flex flex-wrap items-center gap-2 mb-2">
                          <Badge className={`${getActionColor(action.actionType)} text-[10px] flex items-center gap-0.5 h-5`}>
                            {getActionIcon(action.actionType)}
                            {action.actionType.replace(/_/g, ' ')}
                          </Badge>
                          <Badge variant={action.success ? 'default' : 'destructive'} className="text-[10px] h-5">
                            {action.success ? '✓ Success' : '✗ Failed'}
                          </Badge>
                          <Badge className={`${getTriggerColor(action.triggeredBy)} text-[10px] h-5`}>
                            {action.triggeredBy.replace(/_/g, ' ')}
                          </Badge>
                          <span className="ml-auto text-[10px] text-muted-foreground/70">{formatDate(action.createdAt)}</span>
                        </div>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs font-mono">
                          {action.oldStopLoss !== null && action.newStopLoss !== null && (
                            <div>
                              <span className="text-muted-foreground/70 font-sans">SL: </span>
                              <span className="text-muted-foreground/70">{action.oldStopLoss.toFixed(5)}</span>
                              <span className="mx-1 text-muted-foreground/50">→</span>
                              <span className="text-gold font-semibold">{action.newStopLoss.toFixed(5)}</span>
                            </div>
                          )}
                          {action.oldTakeProfit !== null && action.newTakeProfit !== null && (
                            <div>
                              <span className="text-muted-foreground/70 font-sans">TP: </span>
                              <span className="text-muted-foreground/70">{action.oldTakeProfit.toFixed(5)}</span>
                              <span className="mx-1 text-muted-foreground/50">→</span>
                              <span className="text-primary font-semibold">{action.newTakeProfit.toFixed(5)}</span>
                            </div>
                          )}
                          {action.currentPrice !== null && (
                            <div>
                              <span className="text-muted-foreground/70 font-sans">Price: </span>
                              <span>{action.currentPrice.toFixed(5)}</span>
                            </div>
                          )}
                          {action.profitPips !== null && action.profitPips !== undefined && (
                            <div>
                              <span className="text-muted-foreground/70 font-sans">Pips: </span>
                              <span className={action.profitPips >= 0 ? 'text-success' : 'text-destructive'}>
                                {action.profitPips >= 0 ? '+' : ''}{action.profitPips.toFixed(1)}
                              </span>
                            </div>
                          )}
                        </div>
                        {userCommand && (
                          <div className="mt-2 text-xs font-mono bg-muted/50 border border-border px-2 py-1 rounded inline-block text-foreground/80">
                            &quot;{userCommand}&quot;
                          </div>
                        )}
                        {action.details && !userCommand && (
                          <p className="mt-1 text-[10px] text-muted-foreground/70">{action.details}</p>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {/* Trade Lifecycle (MT5) */}
            <div className="tech-card rounded-xl overflow-hidden">
              <div className="flex items-center justify-between px-4 py-2.5 border-b border-border bg-muted/50">
                <div className="flex items-center gap-2">
                  <Database className="h-3.5 w-3.5 text-primary" />
                  <span className="text-xs font-semibold text-foreground/80">Trade Lifecycle</span>
                  <Badge variant="outline" className="text-[10px] h-4 bg-primary/10 text-primary border-primary/30">MT5 API</Badge>
                </div>
                <Button onClick={fetchLifecycle} disabled={lifecycleLoading || !trade?.positionId} size="sm" variant="outline" className="h-7 text-xs">
                  {lifecycleLoading ? <Loader2 className="h-3 w-3 mr-1 animate-spin" /> : <RefreshCw className="h-3 w-3 mr-1" />}
                  {lifecycleData ? 'Refresh' : 'Load'}
                </Button>
              </div>
              <div className="px-4 py-3">
                {lifecycleLoading && (
                  <div className="flex items-center gap-2 text-sm text-muted-foreground/70 py-4">
                    <Loader2 className="h-4 w-4 animate-spin" />Loading lifecycle data...
                  </div>
                )}
                {lifecycleError && (
                  <div className="flex items-start gap-2 p-3 rounded-lg bg-destructive/10 border border-destructive/30">
                    <AlertCircle className="h-4 w-4 text-destructive flex-shrink-0 mt-0.5" />
                    <p className="text-sm text-destructive">{lifecycleError}</p>
                  </div>
                )}
                {lifecycleData && !lifecycleLoading && (
                  <div className="space-y-3">
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
                      <div className="bg-muted/50 rounded-lg border border-border px-3 py-2">
                        <p className="text-[10px] text-muted-foreground/70 uppercase tracking-wider mb-0.5">Status</p>
                        <p className="font-semibold text-foreground/90">{lifecycleData.status || 'N/A'}</p>
                      </div>
                      <div className={`rounded-lg border px-3 py-2 ${Number(lifecycleData.summary?.net_pnl) >= 0 ? 'bg-success/10 border-success/30' : 'bg-destructive/10 border-destructive/30'}`}>
                        <p className="text-[10px] text-muted-foreground/70 uppercase tracking-wider mb-0.5">Net P&L</p>
                        <p className={`font-bold ${Number(lifecycleData.summary?.net_pnl) >= 0 ? 'text-success' : 'text-destructive'}`}>
                          ${lifecycleData.summary?.net_pnl?.toFixed(2) || '0.00'}
                        </p>
                      </div>
                      <div className="bg-muted/50 rounded-lg border border-border px-3 py-2">
                        <p className="text-[10px] text-muted-foreground/70 uppercase tracking-wider mb-0.5">Entry</p>
                        <p className="font-mono font-semibold text-foreground/90">{lifecycleData.summary?.entry_price?.toFixed(5) || 'N/A'}</p>
                      </div>
                      <div className="bg-muted/50 rounded-lg border border-border px-3 py-2">
                        <p className="text-[10px] text-muted-foreground/70 uppercase tracking-wider mb-0.5">Exit</p>
                        <p className="font-mono font-semibold text-foreground/90">{lifecycleData.summary?.exit_price?.toFixed(5) || 'N/A'}</p>
                      </div>
                    </div>
                    {lifecycleData.deals && lifecycleData.deals.length > 0 && (
                      <div>
                        <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70 mb-2">Deals ({lifecycleData.deals.length})</p>
                        <div className="space-y-1">
                          {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                          {lifecycleData.deals.map((deal: any, i: number) => (
                            <div key={i} className="grid grid-cols-2 md:grid-cols-5 gap-2 px-3 py-2 rounded-lg bg-muted/50 border border-border/50 text-xs">
                              <div className="col-span-2 md:col-span-1 flex items-center gap-1.5">
                                <Badge variant="outline" className="text-[10px] h-4">{deal.entry === 0 ? 'ENTRY' : 'EXIT'}</Badge>
                                <span className="text-muted-foreground">{deal.type}</span>
                              </div>
                              <div><span className="text-muted-foreground/70">Price: </span><span className="font-mono">{deal.price?.toFixed(5)}</span></div>
                              <div><span className="text-muted-foreground/70">Vol: </span><span className="font-medium">{deal.volume}</span></div>
                              <div><span className={`font-bold ${Number(deal.profit) >= 0 ? 'text-success' : 'text-destructive'}`}>${deal.profit?.toFixed(2)}</span></div>
                              <div className="text-muted-foreground/70">{deal.time ? new Date(deal.time).toLocaleString() : ''}</div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
                {!lifecycleData && !lifecycleLoading && !lifecycleError && (
                  <p className="text-sm text-muted-foreground/70 py-4">Click &quot;Load&quot; to fetch complete trade lifecycle from MT5 API</p>
                )}
              </div>
            </div>
          </div>

          {/* Right column: AI analysis + Original signal */}
          <div className="flex flex-col gap-3">

            {/* AI Market Analysis */}
            {latestAnalysis && (
              <div className="tech-card rounded-xl overflow-hidden">
                <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border bg-muted/50">
                  <Brain className="h-3.5 w-3.5 text-primary" />
                  <span className="text-xs font-semibold text-foreground/80">AI Market Analysis</span>
                  <Badge variant="outline" className="text-[10px] h-4">
                    {Math.round(Number(latestAnalysis.confidence) * 100)}% confidence
                  </Badge>
                  <span className="ml-auto text-[10px] text-muted-foreground/70">{formatDate(latestAnalysis.createdAt)}</span>
                </div>
                <div className="px-4 py-3">
                  <div className="flex items-center gap-3 mb-3 text-xs flex-wrap">
                    <div className="flex items-center gap-1.5 bg-muted/50 border border-border rounded-lg px-2.5 py-1.5">
                      {(latestAnalysis.trend ?? '').toLowerCase().includes('up')
                        ? <TrendingUp className="h-3.5 w-3.5 text-success" />
                        : <TrendingDown className="h-3.5 w-3.5 text-destructive" />}
                      <span className="font-semibold text-foreground/80">{(latestAnalysis.trend ?? '').replace('_', ' ')}</span>
                    </div>
                    <div className="bg-muted/50 border border-border rounded-lg px-2.5 py-1.5">
                      <span className="text-muted-foreground/70">Volatility: </span><span className="font-semibold text-foreground/80">{latestAnalysis.volatility ?? 'N/A'}</span>
                    </div>
                    <div className="bg-muted/50 border border-border rounded-lg px-2.5 py-1.5">
                      <span className="text-muted-foreground/70">Momentum: </span><span className="font-semibold text-foreground/80">{latestAnalysis.momentum ?? 'N/A'}</span>
                    </div>
                  </div>
                  <div className="space-y-1.5">
                    {latestAnalysis.recommendBreakeven && (
                      <div className="flex items-center gap-2 text-xs bg-amber-500/10 border border-amber-500/30 px-3 py-2 rounded-lg">
                        <Sparkles className="h-3.5 w-3.5 text-amber-400 shrink-0" />
                        <span className="font-medium text-amber-300">Move to breakeven recommended</span>
                        {latestAnalysis.actionTaken && <Badge className="text-[10px] bg-emerald-600 text-white h-4 ml-auto">Done</Badge>}
                      </div>
                    )}
                    {latestAnalysis.recommendTpAdjustment && (
                      <div className="flex items-center gap-2 text-xs bg-emerald-500/10 border border-emerald-500/30 px-3 py-2 rounded-lg">
                        <Sparkles className="h-3.5 w-3.5 text-emerald-400 shrink-0" />
                        <span className="font-medium text-emerald-300">Extend TP {latestAnalysis.recommendTpDirection}</span>
                        {latestAnalysis.actionTaken && <Badge className="text-[10px] bg-emerald-600 text-white h-4 ml-auto">Done</Badge>}
                      </div>
                    )}
                    {latestAnalysis.recommendReducePosition && (
                      <div className="flex items-center gap-2 text-xs bg-amber-500/10 border border-amber-500/30 px-3 py-2 rounded-lg">
                        <Sparkles className="h-3.5 w-3.5 text-amber-400 shrink-0" />
                        <span className="font-medium text-amber-300">Reduce position size</span>
                        {latestAnalysis.actionTaken && <Badge className="text-[10px] bg-emerald-600 text-white h-4 ml-auto">Done</Badge>}
                      </div>
                    )}
                    {latestAnalysis.recommendTightStop && (
                      <div className="flex items-center gap-2 text-xs bg-destructive/10 border border-destructive/30 px-3 py-2 rounded-lg">
                        <Sparkles className="h-3.5 w-3.5 text-destructive shrink-0" />
                        <span className="font-medium text-destructive">Tighten stop loss</span>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* Original signal */}
            {trade.signal && (
              <div className="tech-card rounded-xl overflow-hidden">
                <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border bg-muted/50">
                  <MessageSquare className="h-3.5 w-3.5 text-primary" />
                  <span className="text-xs font-semibold text-foreground/80">Linked Signal</span>
                  <Link href={`/history/signals/${trade.signal.id}`}>
                    <Badge variant="outline" className="text-[10px] h-4 cursor-pointer hover:bg-primary/10 border-border">
                      View Signal →
                    </Badge>
                  </Link>
                </div>
                <div className="px-4 py-3 space-y-3">
                  <div className="flex flex-wrap gap-2 text-xs">
                    <div className="flex items-center gap-1 bg-muted/50 border border-border rounded-lg px-2 py-1">
                      <Hash className="h-3 w-3 text-muted-foreground/70" />
                      <span className="text-muted-foreground">Msg: </span>
                      <span className="font-mono font-semibold text-foreground/80">{trade.signal.messageId}</span>
                    </div>
                    <div className="flex items-center gap-1 bg-muted/50 border border-border rounded-lg px-2 py-1">
                      <Radio className="h-3 w-3 text-muted-foreground/70" />
                      <span className="font-semibold text-foreground/80">{trade.signal.channelName || trade.signal.channelId}</span>
                    </div>
                    <Badge className={`${getStatusColor(trade.signal.status)} text-[10px]`}>{trade.signal.status}</Badge>
                  </div>
                  <TelegramText text={trade.signal.rawMessage} className="bg-muted/60 text-foreground/90 p-4 rounded-lg text-sm leading-relaxed max-h-52 overflow-auto border border-border" />

                  {/* Related trades from same signal */}
                  {trade.signal.trades && trade.signal.trades.length > 1 && (
                    <div className="pt-2 border-t border-border/50">
                      <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70 mb-2">
                        Related Trades ({trade.signal.trades.length})
                      </p>
                      <div className="space-y-1">
                        {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                        {trade.signal.trades.map((t: any) => (
                          <Link key={t.id} href={`/history/trades/${t.id}`}>
                            <div className={`flex items-center justify-between px-2.5 py-2 rounded-lg text-xs cursor-pointer transition-colors ${
                              t.id === trade.id ? 'bg-primary/10 border border-primary/20' : 'bg-muted/50 hover:bg-primary/10 border border-transparent'
                            }`}>
                              <div className="flex items-center gap-2">
                                <Badge variant="outline" className="text-[10px] h-4">{t.action}</Badge>
                                <Badge className={`${getStatusColor(t.status)} text-[10px] h-4`}>{t.status}</Badge>
                                {t.tpLevel && <Badge variant="outline" className="text-[10px] h-4">TP{t.tpLevel}</Badge>}
                                <span className="font-mono text-muted-foreground">{t.lotSize.toFixed(2)} lots</span>
                                {t.id === trade.id && <span className="text-[10px] text-primary font-semibold">← current</span>}
                              </div>
                              {t.profitLoss !== null && (
                                <span className={`font-bold ${t.profitLoss >= 0 ? 'text-success' : 'text-destructive'}`}>
                                  {formatCurrency(t.profitLoss)}
                                </span>
                              )}
                            </div>
                          </Link>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* ── Signal Replies Timeline ─────────────────────────────────────── */}
        {trade.signalReplies && trade.signalReplies.length > 0 && (
          <div className="tech-card rounded-xl overflow-hidden">
            <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border bg-muted/50">
              <Clock className="h-3.5 w-3.5 text-gold" />
              <span className="text-xs font-semibold text-foreground/80">Signal Replies ({trade.signalReplies.length})</span>
            </div>
            <div className="px-5 py-4">
              <div className="space-y-0 border-l-2 border-border ml-2">
                {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                {trade.signalReplies.map((reply: any) => (
                  <div key={reply.id} className="relative pl-6 pb-4">
                    <div className={`absolute -left-[9px] top-0 h-4 w-4 rounded-full border-2 border-card flex items-center justify-center ${
                      reply.actionSuccess ? 'bg-emerald-500' : reply.actionTaken ? 'bg-amber-500' : 'bg-violet-500'
                    }`}>
                      <MessageSquare className="h-2 w-2 text-white" />
                    </div>
                    <div className="text-xs">
                      <div className="flex items-center gap-2 mb-1 flex-wrap">
                        <span className="font-semibold text-foreground/80">{reply.username ? `@${reply.username}` : 'User'}</span>
                        <span className="text-muted-foreground/70">{formatDate(reply.createdAt)}</span>
                        {reply.aiParsed && <Badge variant="secondary" className="text-[10px] h-4">🤖 AI</Badge>}
                        {reply.actionSuccess && <Badge className="text-[10px] h-4 bg-emerald-600 text-white">✓ Done</Badge>}
                        {!reply.actionTaken && !reply.processingError && (
                          <Badge variant="secondary" className="text-[10px] h-4"><Info className="h-2.5 w-2.5 mr-0.5" /> No Action</Badge>
                        )}
                      </div>
                      <TelegramText text={reply.replyText} className="bg-muted/50 border border-border p-2 rounded-lg mb-1 text-foreground/80" />
                      {reply.actionTaken && (
                        <div className="space-y-0.5 text-muted-foreground">
                          {reply.actionType && (
                            <div className="flex items-center gap-1">
                              <CheckCircle2 className="h-3 w-3 text-success" />
                              <span className="font-medium text-foreground/80">{reply.actionType}</span>
                            </div>
                          )}
                          {reply.actionResult && <p className={reply.actionSuccess ? 'text-success' : 'text-gold'}>{reply.actionResult}</p>}
                          {(reply.positionsClosed > 0 || reply.ordersCancelled > 0) && (
                            <div className="flex gap-3">
                              {reply.positionsClosed > 0 && <span>🔴 Closed: {reply.positionsClosed}</span>}
                              {reply.ordersCancelled > 0 && <span>❌ Cancelled: {reply.ordersCancelled}</span>}
                            </div>
                          )}
                        </div>
                      )}
                      {reply.processingError && (
                        <div className="mt-1 p-2 rounded-lg bg-destructive/10 border border-destructive/30 text-destructive text-xs">{reply.processingError}</div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
