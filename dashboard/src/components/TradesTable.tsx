'use client'

import { useState } from 'react'
import Link from 'next/link'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  TrendingUp, TrendingDown, ChevronDown, ChevronRight,
  AlertCircle, ExternalLink, Activity, Brain, MessageSquare,
  Edit, Scissors, X, Sparkles,
} from 'lucide-react'
import type { TradeWithRelations } from '@/lib/types'
import { formatDate, formatCurrency, getStatusColor } from '@/lib/utils'
import TelegramText from '@/components/TelegramText'

interface TradesTableProps {
  trades: TradeWithRelations[]
}

// ── Column header ──────────────────────────────────────────────────────────────
const COL = 'py-2.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70 select-none'

function getActionIcon(type: string) {
  switch (type) {
    case 'CLOSE': return <X className="h-3 w-3" />
    case 'PARTIAL_CLOSE': case 'AUTO_PARTIAL': return <Scissors className="h-3 w-3" />
    case 'MODIFY_SL': case 'MODIFY_TP': return <Edit className="h-3 w-3" />
    default: return <Activity className="h-3 w-3" />
  }
}

function getActionColor(type: string) {
  const m: Record<string, string> = {
    CLOSE: 'bg-destructive/10 text-destructive border border-destructive/20',
    PARTIAL_CLOSE: 'bg-gold/10 text-gold border border-gold/20',
    AUTO_PARTIAL: 'bg-gold/10 text-gold border border-gold/20',
    MODIFY_SL: 'bg-orange-100 text-orange-700',
    MODIFY_TP: 'bg-primary/10 text-primary border border-primary/20',
    TRAILING_STOP: 'bg-success/10 text-success border border-success/20',
    BREAKEVEN: 'bg-success/10 text-success border border-success/20',
    AUTO_TP: 'bg-accent text-muted-foreground border border-border',
  }
  return m[type] || 'bg-muted text-foreground/80'
}

export default function TradesTable({ trades }: TradesTableProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null)

  if (!Array.isArray(trades)) {
    return (
      <div className="flex items-center justify-center py-12 text-destructive text-sm gap-2">
        <AlertCircle className="h-5 w-5" />
        Error loading trades. Please refresh the page.
      </div>
    )
  }

  if (trades.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-muted-foreground/70">
        <div className="w-12 h-12 rounded-full bg-muted flex items-center justify-center mb-3">
          <TrendingUp className="h-6 w-6 text-muted-foreground/70" />
        </div>
        <p className="text-sm font-medium text-muted-foreground">No trades found</p>
        <p className="text-xs mt-1">Try adjusting your filters</p>
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-border overflow-hidden bg-card shadow-sm">

      {/* ── Toolbar ──────────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-muted/50 border-b border-border">
        <span className="text-xs font-semibold text-foreground">{trades.length} trades</span>
      </div>

      {/* ── Column headers (desktop) ──────────────────────────────────────────── */}
      <div
        className="hidden md:grid items-center px-3 border-b border-border bg-muted/50"
        style={{ gridTemplateColumns: '28px 28px minmax(100px,1fr) 60px 54px 94px 94px 84px 90px 90px 40px' }}
      >
        <div className={COL} />
        <div className={COL} />
        <div className={`${COL} px-1`}>Symbol</div>
        <div className={`${COL} px-1`}>Type</div>
        <div className={`${COL} px-1`}>Lots</div>
        <div className={`${COL} px-1`}>Entry</div>
        <div className={`${COL} px-1`}>Close</div>
        <div className={`${COL} px-1`}>P&amp;L</div>
        <div className={`${COL} px-1`}>Status</div>
        <div className={`${COL} px-1`}>Date</div>
        <div className={COL} />
      </div>

      {/* ── Rows ────────────────────────────────────────────────────────────── */}
      <div className="divide-y divide-slate-200">
        {trades.map((trade) => {
          const isBuy = trade.action?.toUpperCase().includes('BUY')
          const isExpanded = expandedId === trade.id
          const hasError = !!trade.executionError
          const actionCount = trade.tradeActions?.length || 0
          const latestAnalysis = trade.marketAnalyses?.[0] ?? null
          const hasExpandable = actionCount > 0 || latestAnalysis || trade.signal || hasError

          const pnl = trade.profitLoss !== null && trade.profitLoss !== undefined ? Number(trade.profitLoss) : null
          const pips = trade.profitLossPips !== null && trade.profitLossPips !== undefined ? Number(trade.profitLossPips) : null

          return (
            <div key={trade.id} className={hasError ? 'bg-destructive/10/20' : ''}>

              {/* ── Desktop row ──────────────────────────────────────────────── */}
              <div
                className={`hidden md:grid items-center px-3 h-11 cursor-pointer select-none transition-colors duration-100
                  ${isExpanded ? 'bg-primary/5' : 'hover:bg-muted/50'}`}
                style={{ gridTemplateColumns: '28px 28px minmax(100px,1fr) 60px 54px 94px 94px 84px 90px 90px 40px' }}
                onClick={() => setExpandedId(isExpanded ? null : trade.id)}
              >
                {/* Expand */}
                <div className="flex items-center justify-center">
                  {hasExpandable
                    ? isExpanded
                      ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                      : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/70" />
                    : null}
                </div>

                {/* Direction */}
                <div className={`flex items-center justify-center w-6 h-6 rounded ${isBuy ? 'bg-success/10' : 'bg-destructive/10'}`}>
                  {isBuy
                    ? <TrendingUp className="h-3.5 w-3.5 text-success" />
                    : <TrendingDown className="h-3.5 w-3.5 text-destructive" />}
                </div>

                {/* Symbol */}
                <div className="px-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="font-semibold text-xs text-foreground truncate">{trade.symbol}</span>
                    {trade.tpLevel && (
                      <Badge variant="outline" className="text-[10px] h-3.5 px-1 border-border shrink-0">TP{trade.tpLevel}</Badge>
                    )}
                    {hasError && <AlertCircle className="h-3 w-3 text-destructive shrink-0" />}
                  </div>
                  {trade.positionId && (
                    <span className="text-[10px] text-muted-foreground/70 font-mono block truncate leading-none mt-0.5">#{trade.positionId}</span>
                  )}
                </div>

                {/* Type */}
                <div className="px-1">
                  <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${isBuy ? 'text-success bg-success/10' : 'text-destructive bg-destructive/10'}`}>
                    {trade.action}
                  </span>
                </div>

                {/* Lots */}
                <div className="px-1">
                  <span className="font-mono text-xs text-foreground">{trade.lotSize.toFixed(2)}</span>
                </div>

                {/* Entry */}
                <div className="px-1">
                  <span className="font-mono text-xs text-foreground">
                    {trade.entryPrice ? trade.entryPrice.toFixed(5) : <span className="text-muted-foreground/50">—</span>}
                  </span>
                </div>

                {/* Close */}
                <div className="px-1">
                  <span className="font-mono text-xs text-foreground">
                    {trade.closePrice ? trade.closePrice.toFixed(5) : <span className="text-muted-foreground/50">—</span>}
                  </span>
                </div>

                {/* P&L */}
                <div className="px-1">
                  {pnl !== null ? (
                    <div>
                      <span className={`font-bold text-xs ${pnl >= 0 ? 'text-success' : 'text-destructive'}`}>
                        {formatCurrency(pnl)}
                      </span>
                      {pips !== null && (
                        <span className="text-[10px] text-muted-foreground/70 ml-0.5">
                          ({pips >= 0 ? '+' : ''}{pips.toFixed(1)}p)
                        </span>
                      )}
                    </div>
                  ) : (
                    <span className="text-muted-foreground/50 text-xs">—</span>
                  )}
                </div>

                {/* Status */}
                <div className="px-1">
                  <Badge className={`${getStatusColor(trade.status)} text-[10px] px-1.5 py-0 h-[18px] font-semibold`}>
                    {trade.status}
                  </Badge>
                </div>

                {/* Date */}
                <div className="px-1">
                  <span className="text-[10px] text-muted-foreground/70 whitespace-nowrap">{formatDate(trade.createdAt)}</span>
                </div>

                {/* Link */}
                <div className="flex justify-end" onClick={e => e.stopPropagation()}>
                  <Link href={`/history/trades/${trade.id}`} title="View full details">
                    <span className="p-1 rounded hover:bg-primary/10 transition-colors text-muted-foreground/50 hover:text-primary block">
                      <ExternalLink className="h-3 w-3" />
                    </span>
                  </Link>
                </div>
              </div>

              {/* ── Mobile row ───────────────────────────────────────────────── */}
              <div
                className="md:hidden p-3 cursor-pointer active:bg-muted/50"
                onClick={() => hasExpandable && setExpandedId(isExpanded ? null : trade.id)}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <div className={`flex items-center justify-center w-7 h-7 rounded-md shrink-0 ${isBuy ? 'bg-success/10' : 'bg-destructive/10'}`}>
                      {isBuy ? <TrendingUp className="h-4 w-4 text-success" /> : <TrendingDown className="h-4 w-4 text-destructive" />}
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <span className="font-bold text-sm text-foreground">{trade.symbol}</span>
                        <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${isBuy ? 'text-success bg-success/10' : 'text-destructive bg-destructive/10'}`}>
                          {trade.action}
                        </span>
                        <span className="text-[10px] text-muted-foreground/70">{trade.lotSize.toFixed(2)}L</span>
                      </div>
                      {trade.positionId && (
                        <span className="text-[10px] text-muted-foreground/70 font-mono">#{trade.positionId}</span>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <Badge className={`${getStatusColor(trade.status)} text-[10px] px-1.5 py-0 h-4 font-semibold`}>{trade.status}</Badge>
                    {hasExpandable && (
                      isExpanded
                        ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                        : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/70" />
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-3 text-xs mt-1.5 flex-wrap">
                  {trade.entryPrice && (
                    <span><span className="text-muted-foreground/70">Entry </span><span className="font-mono font-semibold">{trade.entryPrice.toFixed(5)}</span></span>
                  )}
                  {trade.closePrice && (
                    <span><span className="text-muted-foreground/70">Close </span><span className="font-mono font-semibold">{trade.closePrice.toFixed(5)}</span></span>
                  )}
                  {pnl !== null && (
                    <span className={`font-bold ${pnl >= 0 ? 'text-success' : 'text-destructive'}`}>
                      {formatCurrency(pnl)}
                    </span>
                  )}
                </div>
              </div>

              {/* ── Expanded detail ───────────────────────────────────────────── */}
              {isExpanded && (
                <div className="border-t border-border bg-muted/50 px-4 md:px-5 py-4">

                  {/* ── Stats strip ─────────────────────────────────────────── */}
                  <div className="flex items-center gap-5 flex-wrap mb-4 pb-3 border-b border-border">
                    {trade.entryPrice && (
                      <div>
                        <p className="text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/70 mb-0.5">Entry</p>
                        <p className="font-mono text-xs font-semibold text-foreground">{trade.entryPrice.toFixed(5)}</p>
                      </div>
                    )}
                    {trade.closePrice && (
                      <div>
                        <p className="text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/70 mb-0.5">Close</p>
                        <p className="font-mono text-xs font-semibold text-foreground">{trade.closePrice.toFixed(5)}</p>
                      </div>
                    )}
                    {trade.stopLoss && (
                      <div>
                        <p className="text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/70 mb-0.5">Stop Loss</p>
                        <p className="font-mono text-xs font-semibold text-destructive">{trade.stopLoss.toFixed(5)}</p>
                      </div>
                    )}
                    {trade.takeProfit && (
                      <div>
                        <p className="text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/70 mb-0.5">Take Profit</p>
                        <p className="font-mono text-xs font-semibold text-success">{trade.takeProfit.toFixed(5)}</p>
                      </div>
                    )}
                    {pnl !== null && (
                      <div>
                        <p className="text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/70 mb-0.5">P&L</p>
                        <p className={`text-xs font-bold ${pnl >= 0 ? 'text-success' : 'text-destructive'}`}>
                          {formatCurrency(pnl)}
                          {pips !== null && <span className="text-[10px] font-normal ml-1">({pips >= 0 ? '+' : ''}{pips.toFixed(1)}p)</span>}
                        </p>
                      </div>
                    )}
                    {trade.lotSize && (
                      <div>
                        <p className="text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/70 mb-0.5">Lot Size</p>
                        <p className="font-mono text-xs font-semibold text-foreground">{trade.lotSize.toFixed(2)}</p>
                      </div>
                    )}
                  </div>

                  {/* Execution error */}
                  {hasError && (
                    <div className="flex items-start gap-2 p-2.5 rounded-lg bg-destructive/10 border border-rose-200 text-xs mb-3">
                      <AlertCircle className="h-3.5 w-3.5 text-destructive shrink-0 mt-0.5" />
                      <span className="text-destructive">{trade.executionError}</span>
                    </div>
                  )}

                  {/* ── Main 3-column grid ──────────────────────────────────── */}
                  <div className="grid xl:grid-cols-3 lg:grid-cols-2 gap-4">

                    {/* Col 1: Trade actions */}
                    <div className="flex flex-col gap-2">
                      <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70 flex items-center gap-1">
                        <Activity className="h-3 w-3" />
                        Actions {actionCount > 0 ? `(${actionCount})` : ''}
                      </p>
                      {actionCount > 0 ? (
                        <div className="space-y-1">
                          {trade.tradeActions!.map(action => {
                            const cmd = action.details?.match(/User reply: "([^"]+)"/)?.[1]
                            return (
                              <div key={action.id} className="bg-card p-2 rounded-lg border border-border text-xs">
                                <div className="flex items-center justify-between mb-1">
                                  <div className="flex items-center gap-1.5">
                                    <Badge className={`${getActionColor(action.actionType)} text-[10px] flex items-center gap-0.5 h-4 px-1.5`}>
                                      {getActionIcon(action.actionType)}
                                      {action.actionType.replace(/_/g, ' ')}
                                    </Badge>
                                    <Badge variant={action.success ? 'default' : 'destructive'} className="text-[10px] h-4 px-1">
                                      {action.success ? '✓' : '✗'}
                                    </Badge>
                                  </div>
                                  <span className="text-[10px] text-muted-foreground/70">{formatDate(action.createdAt)}</span>
                                </div>
                                <div className="flex items-center gap-3 text-[10px] font-mono flex-wrap">
                                  {action.oldStopLoss !== null && action.newStopLoss !== null && (
                                    <span>SL: <span className="text-muted-foreground/70">{action.oldStopLoss.toFixed(5)}</span> → <span className="text-orange-600 font-semibold">{action.newStopLoss.toFixed(5)}</span></span>
                                  )}
                                  {action.oldTakeProfit !== null && action.newTakeProfit !== null && (
                                    <span>TP: <span className="text-muted-foreground/70">{action.oldTakeProfit.toFixed(5)}</span> → <span className="text-primary font-semibold">{action.newTakeProfit.toFixed(5)}</span></span>
                                  )}
                                  {action.profitPips !== null && action.profitPips !== undefined && (
                                    <span className={action.profitPips >= 0 ? 'text-success' : 'text-destructive'}>
                                      {action.profitPips >= 0 ? '+' : ''}{action.profitPips.toFixed(1)}p
                                    </span>
                                  )}
                                </div>
                                {cmd && (
                                  <div className="mt-1 font-mono bg-muted/50 px-1.5 py-0.5 rounded text-[10px] text-muted-foreground">
                                    &quot;{cmd}&quot;
                                  </div>
                                )}
                              </div>
                            )
                          })}
                        </div>
                      ) : (
                        <div className="flex-1 flex items-center justify-center bg-card rounded-lg border border-border py-6">
                          <p className="text-xs text-muted-foreground/70">No actions recorded</p>
                        </div>
                      )}
                    </div>

                    {/* Col 2: AI Analysis */}
                    <div className="flex flex-col gap-2">
                      <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70 flex items-center gap-1">
                        <Brain className="h-3 w-3" />
                        AI Analysis
                        {latestAnalysis && (
                          <Badge variant="outline" className="text-[10px] h-3.5 px-1 border-border ml-0.5">
                            {Math.round(Number(latestAnalysis.confidence) * 100)}%
                          </Badge>
                        )}
                      </p>
                      {latestAnalysis && (latestAnalysis.recommendBreakeven || latestAnalysis.recommendTpAdjustment || latestAnalysis.recommendReducePosition || latestAnalysis.recommendTightStop) ? (
                        <div className="space-y-1.5">
                          {latestAnalysis.recommendBreakeven && (
                            <div className="flex items-center gap-2 text-xs bg-gold/10 border border-amber-200 px-2.5 py-2 rounded-lg">
                              <Sparkles className="h-3 w-3 text-gold shrink-0" />
                              <span className="font-medium text-gold">Move to breakeven</span>
                            </div>
                          )}
                          {latestAnalysis.recommendTpAdjustment && (
                            <div className="flex items-center gap-2 text-xs bg-success/10 border border-emerald-200 px-2.5 py-2 rounded-lg">
                              <Sparkles className="h-3 w-3 text-success shrink-0" />
                              <span className="font-medium text-success">Extend TP {latestAnalysis.recommendTpDirection}</span>
                            </div>
                          )}
                          {latestAnalysis.recommendReducePosition && (
                            <div className="flex items-center gap-2 text-xs bg-orange-50 border border-orange-200 px-2.5 py-2 rounded-lg">
                              <Sparkles className="h-3 w-3 text-orange-600 shrink-0" />
                              <span className="font-medium text-orange-800">Reduce position size</span>
                            </div>
                          )}
                          {latestAnalysis.recommendTightStop && (
                            <div className="flex items-center gap-2 text-xs bg-destructive/10 border border-rose-200 px-2.5 py-2 rounded-lg">
                              <Sparkles className="h-3 w-3 text-destructive shrink-0" />
                              <span className="font-medium text-destructive">Tighten stop loss</span>
                            </div>
                          )}
                        </div>
                      ) : (
                        <div className="flex-1 flex items-center justify-center bg-card rounded-lg border border-border py-6">
                          <p className="text-xs text-muted-foreground/70">No AI recommendations</p>
                        </div>
                      )}
                    </div>

                    {/* Col 3: Original signal */}
                    <div className="flex flex-col gap-2">
                      <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70 flex items-center gap-1.5">
                        <MessageSquare className="h-3 w-3" />
                        Original Signal
                        {trade.signal && (
                          <Link href={`/history/signals/${trade.signal.id}`} onClick={e => e.stopPropagation()}>
                            <Badge variant="outline" className="text-[10px] h-3.5 px-1 cursor-pointer hover:bg-primary/10 border-border">
                              View →
                            </Badge>
                          </Link>
                        )}
                      </p>
                      {trade.signal ? (
                        <>
                          <TelegramText text={trade.signal.rawMessage} className="bg-[#181715] text-[#e2e0db] p-3 rounded-lg text-[11px] leading-relaxed max-h-48 overflow-auto border border-[#252320] flex-1" />
                          <p className="text-[10px] text-muted-foreground/70">
                            {trade.signal.channelName || trade.signal.channelId} · Msg #{trade.signal.messageId}
                          </p>
                        </>
                      ) : (
                        <div className="flex-1 flex items-center justify-center bg-card rounded-lg border border-border py-6">
                          <p className="text-xs text-muted-foreground/70">No linked signal</p>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Footer */}
                  <div className="flex justify-end mt-4 pt-3 border-t border-border">
                    <Link href={`/history/trades/${trade.id}`}>
                      <Button variant="ghost" size="sm" className="h-7 text-xs px-3 text-primary hover:text-primary/80 hover:bg-primary/10">
                        Full details
                        <ExternalLink className="h-3 w-3 ml-1" />
                      </Button>
                    </Link>
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
