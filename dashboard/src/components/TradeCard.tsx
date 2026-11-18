'use client'

import { useState } from 'react'
import Link from 'next/link'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { formatDate, formatCurrency, getStatusColor } from '@/lib/utils'
import {
  TrendingUp,
  TrendingDown,
  Clock,
  Activity,
  Brain,
  ExternalLink,
  AlertCircle,
  ChevronDown,
  ChevronRight,
  MessageSquare,
  Sparkles,
  Edit,
  Scissors,
  X,
} from 'lucide-react'
import type { TradeWithRelations } from '@/lib/types'
import TelegramText from '@/components/TelegramText'

interface TradeCardProps {
  trade: TradeWithRelations
  compact?: boolean
  defaultExpanded?: boolean
}

export default function TradeCard({ trade, compact = false, defaultExpanded = false }: TradeCardProps) {
  const [expanded, setExpanded] = useState(defaultExpanded)
  const isBuy = trade.action?.toUpperCase().includes('BUY')
  const hasAI = trade.marketAnalyses && trade.marketAnalyses.length > 0
  const latestAnalysis = hasAI ? trade.marketAnalyses[0] : null
  const actionCount = trade.tradeActions?.length || 0
  const hasError = !!trade.executionError
  const hasExpandableContent = actionCount > 0 || hasAI || trade.signal || hasError

  const getActionIcon = (actionType: string) => {
    switch (actionType) {
      case 'CLOSE': return <X className="h-3 w-3" />
      case 'PARTIAL_CLOSE':
      case 'AUTO_PARTIAL': return <Scissors className="h-3 w-3" />
      case 'MODIFY_SL':
      case 'MODIFY_TP': return <Edit className="h-3 w-3" />
      case 'TRAILING_STOP':
      case 'BREAKEVEN': return <TrendingUp className="h-3 w-3" />
      default: return <Activity className="h-3 w-3" />
    }
  }

  const getActionColor = (actionType: string) => {
    const colors: Record<string, string> = {
      CLOSE: 'bg-destructive/10 text-destructive border border-destructive/20 dark:bg-rose-900/30 dark:text-destructive/70',
      PARTIAL_CLOSE: 'bg-gold/10 text-gold border border-gold/20 dark:bg-amber-900/30 dark:text-amber-300',
      AUTO_PARTIAL: 'bg-gold/10 text-gold border border-gold/20 dark:bg-amber-900/30 dark:text-amber-300',
      MODIFY_SL: 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300',
      MODIFY_TP: 'bg-primary/10 text-primary border border-primary/20 dark:bg-sky-900/30 dark:text-sky-300',
      TRAILING_STOP: 'bg-success/10 text-success border border-success/20 dark:bg-emerald-900/30 dark:text-success/70',
      BREAKEVEN: 'bg-success/10 text-success border border-success/20 dark:bg-emerald-900/30 dark:text-success/70',
      AUTO_TP: 'bg-accent text-muted-foreground border border-border dark:bg-violet-900/30 dark:text-violet-300',
    }
    return colors[actionType] || 'bg-muted text-foreground/80'
  }

  const getTriggerColor = (triggeredBy: string) => {
    const colors: Record<string, string> = {
      telegram_reply: 'bg-primary/10 text-primary border border-primary/20 dark:bg-sky-900/30 dark:text-sky-300',
      telegram_message: 'bg-cyan-100 text-cyan-700 dark:bg-cyan-900/30 dark:text-cyan-300',
      system: 'bg-muted text-foreground/80 dark:bg-muted/30 dark:text-muted-foreground/50',
      auto_trailing: 'bg-success/10 text-success border border-success/20 dark:bg-emerald-900/30 dark:text-success/70',
      auto_breakeven: 'bg-gold/10 text-gold border border-gold/20 dark:bg-amber-900/30 dark:text-amber-300',
      auto_tp: 'bg-accent text-muted-foreground border border-border dark:bg-violet-900/30 dark:text-violet-300',
      auto_position_monitor: 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-300',
      manual: 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300',
    }
    return colors[triggeredBy] || colors.system
  }

  return (
    <div
      className={`relative rounded-lg border transition-all duration-150 ${
        hasError ? 'border-rose-300 bg-destructive/10/40' : 'border-border bg-card'
      } ${expanded ? 'shadow-md' : 'hover:shadow-sm hover:border-border'}`}
    >
      <div className="p-3">
        <div className="flex items-start md:items-center justify-between gap-2 mb-2">
          <div className="flex items-center gap-2 min-w-0 flex-1">
            {hasExpandableContent && (
              <button
                onClick={(e) => { e.preventDefault(); setExpanded(!expanded) }}
                className="flex items-center justify-center w-5 h-5 rounded hover:bg-muted transition-colors flex-shrink-0"
              >
                {expanded ? (
                  <ChevronDown className="h-3.5 w-3.5 text-muted-foreground/70" />
                ) : (
                  <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/70" />
                )}
              </button>
            )}

            <div className={`flex items-center justify-center w-7 h-7 rounded-md ${
              isBuy ? 'bg-success/10' : 'bg-destructive/10'
            }`}>
              {isBuy ? (
                <TrendingUp className="h-4 w-4 text-success" />
              ) : (
                <TrendingDown className="h-4 w-4 text-destructive" />
              )}
            </div>

            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="font-bold text-sm text-foreground tracking-tight">{trade.symbol}</span>
                <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-4 font-semibold border-border text-foreground/80">
                  {trade.action}
                </Badge>
                {trade.tpLevel && (
                  <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-4 font-semibold bg-primary/8 text-sky-700 border-sky-300">
                    TP{trade.tpLevel}
                  </Badge>
                )}
                {trade.entryLeg != null && trade.entryLeg > 1 && (
                  <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-4 font-semibold bg-amber-500/10 text-amber-700 border-amber-300">
                    Entry {trade.entryLeg}
                  </Badge>
                )}
              </div>
              {!compact && (
                <span className="text-[10px] text-muted-foreground font-medium">
                  {trade.lotSize.toFixed(2)} lots
                  {trade.positionId && <span className="ml-1.5 font-mono">#{trade.positionId}</span>}
                </span>
              )}
            </div>
          </div>

          <div className="flex items-center gap-1.5 flex-shrink-0">
            <Badge className={`${getStatusColor(trade.status)} text-xs px-2.5 py-0.5 font-semibold whitespace-nowrap`}>
              {trade.status}
            </Badge>
            {hasError && (
              <AlertCircle className="h-3.5 w-3.5 text-destructive" />
            )}
          </div>
        </div>

        <div className="flex items-center gap-3 text-xs flex-wrap">
          <div className="flex items-center gap-1">
            <span className="text-muted-foreground font-medium">Entry</span>
            <span className="font-mono font-semibold text-foreground">{trade.entryPrice?.toFixed(5) || '—'}</span>
          </div>
          {trade.status === 'CLOSED' && trade.closePrice && (
            <div className="flex items-center gap-1">
              <span className="text-muted-foreground font-medium">Close</span>
              <span className="font-mono font-semibold text-foreground">{trade.closePrice.toFixed(5)}</span>
            </div>
          )}
          <div className="flex items-center gap-1">
            <span className="text-muted-foreground font-medium">SL</span>
            <span className="font-mono font-semibold text-destructive">{trade.stopLoss?.toFixed(5) || '—'}</span>
          </div>
          <div className="flex items-center gap-1">
            <span className="text-muted-foreground font-medium">TP</span>
            <span className="font-mono font-semibold text-success">{trade.takeProfit?.toFixed(5) || '—'}</span>
          </div>
        </div>

        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 sm:gap-0 mt-2 pt-2 border-t border-border">
          <div className="flex items-center gap-3 text-xs">
            {trade.profitLoss !== null && trade.profitLoss !== undefined && (
              <div className={`flex items-center gap-1 font-bold text-sm ${
                Number(trade.profitLoss) >= 0 ? 'text-success' : 'text-destructive'
              }`}>
                {formatCurrency(Number(trade.profitLoss))}
                {trade.profitLossPips !== null && trade.profitLossPips !== undefined && (
                  <span className="text-[10px] font-normal text-muted-foreground ml-0.5">
                    ({Number(trade.profitLossPips) >= 0 ? '+' : ''}{Number(trade.profitLossPips).toFixed(1)}p)
                  </span>
                )}
              </div>
            )}
            {actionCount > 0 && (
              <div className="flex items-center gap-0.5 text-muted-foreground">
                <Activity className="h-3 w-3" />
                <span className="text-[10px]">{actionCount} actions</span>
              </div>
            )}
            {hasAI && (
              <div className="flex items-center gap-0.5 text-primary dark:text-sky-400">
                <Brain className="h-3 w-3" />
                <span className="text-[10px]">AI</span>
              </div>
            )}
          </div>

          <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
            <Clock className="h-2.5 w-2.5" />
            <span>{formatDate(trade.createdAt)}</span>
            <Link
              href={`/history/trades/${trade.id}`}
              onClick={(e) => e.stopPropagation()}
              className="ml-1 text-primary hover:text-primary/80 transition-colors"
              title="View full details"
            >
              <ExternalLink className="h-3 w-3" />
            </Link>
          </div>
        </div>
      </div>

      {/* Expanded content */}
      {expanded && (
        <div className="border-t bg-muted/10 px-3.5 pb-3.5 space-y-3 pt-3">

          {/* Execution Error */}
          {hasError && (
            <div className="flex items-start gap-2 p-2.5 rounded-lg bg-destructive/10 dark:bg-rose-950/20 border border-rose-200 dark:border-rose-800 text-xs">
              <AlertCircle className="h-3.5 w-3.5 text-destructive flex-shrink-0 mt-0.5" />
              <div>
                <span className="font-semibold text-destructive dark:text-destructive/70">Execution Error: </span>
                <span className="text-destructive dark:text-destructive/80">{trade.executionError}</span>
              </div>
            </div>
          )}

          {/* AI Market Analysis */}
          {latestAnalysis && (() => {
            const hasRecommendations =
              latestAnalysis.recommendBreakeven ||
              latestAnalysis.recommendTpAdjustment ||
              latestAnalysis.recommendReducePosition ||
              latestAnalysis.recommendTightStop
            
            if (!hasRecommendations) return null

            return (
              <div className="p-2.5 rounded-lg bg-primary/8/50 dark:bg-sky-950/10 border border-sky-200 dark:border-sky-800">
                <div className="flex items-center gap-2 mb-2 text-xs">
                  <Brain className="h-3.5 w-3.5 text-primary" />
                  <span className="font-semibold text-sky-900 dark:text-sky-100">AI Analysis</span>
                  <Badge variant="outline" className="text-[10px] h-3.5 px-1">
                    {Math.round(Number(latestAnalysis.confidence) * 100)}%
                  </Badge>
                  <span className="text-muted-foreground">
                    {(latestAnalysis.trend ?? '').replace('_', ' ')} · Vol: {latestAnalysis.volatility ?? 'N/A'}
                  </span>
                </div>
                <div className="space-y-1">
                  {latestAnalysis.recommendBreakeven && (
                    <div className="flex items-center gap-2 text-xs bg-gold/10/60 dark:bg-amber-900/20 px-2 py-1 rounded">
                      <Sparkles className="h-3 w-3 text-gold" />
                      <span className="font-medium">🛡️ Move to breakeven</span>
                      {latestAnalysis.actionTaken && latestAnalysis.actionType === 'AI_BREAKEVEN' && (
                        <Badge className="text-[10px] bg-emerald-600 text-white h-3.5 px-1">✅ Done</Badge>
                      )}
                    </div>
                  )}
                  {latestAnalysis.recommendTpAdjustment && (
                    <div className="flex items-center gap-2 text-xs bg-success/10/60 dark:bg-emerald-900/20 px-2 py-1 rounded">
                      <Sparkles className="h-3 w-3 text-success" />
                      <span className="font-medium">🎯 Extend TP {latestAnalysis.recommendTpDirection}</span>
                      {latestAnalysis.actionTaken && latestAnalysis.actionType === 'AI_TP_EXTENSION' && (
                        <Badge className="text-[10px] bg-emerald-600 text-white h-3.5 px-1">✅ Done</Badge>
                      )}
                    </div>
                  )}
                  {latestAnalysis.recommendReducePosition && (
                    <div className="flex items-center gap-2 text-xs bg-orange-100/60 dark:bg-orange-900/20 px-2 py-1 rounded">
                      <Sparkles className="h-3 w-3 text-orange-600" />
                      <span className="font-medium">📉 Reduce position</span>
                      {latestAnalysis.actionTaken && latestAnalysis.actionType === 'AI_PARTIAL_CLOSE' && (
                        <Badge className="text-[10px] bg-emerald-600 text-white h-3.5 px-1">✅ Done</Badge>
                      )}
                    </div>
                  )}
                  {latestAnalysis.recommendTightStop && (
                    <div className="flex items-center gap-2 text-xs bg-destructive/10/60 dark:bg-rose-900/20 px-2 py-1 rounded">
                      <Sparkles className="h-3 w-3 text-destructive" />
                      <span className="font-medium">⚠️ Tighten stop loss</span>
                    </div>
                  )}
                </div>
              </div>
            )
          })()}

          {/* Trade Actions */}
          {actionCount > 0 && (
            <div>
              <div className="flex items-center gap-2 text-xs font-semibold mb-2">
                <Activity className="h-3.5 w-3.5 text-muted-foreground" />
                Trade Actions ({actionCount})
              </div>
              <div className="space-y-1.5">
                {trade.tradeActions!.map((action) => {
                  const userReplyMatch = action.details?.match(/User reply: "([^"]+)"/)
                  const userCommand = userReplyMatch ? userReplyMatch[1] : null

                  return (
                    <div key={action.id} className="p-2 rounded-lg bg-card border border-border/50 text-xs">
                      <div className="flex items-center justify-between mb-1">
                        <div className="flex items-center gap-1.5">
                          <Badge className={`${getActionColor(action.actionType)} text-[10px] flex items-center gap-0.5 h-4 px-1`}>
                            {getActionIcon(action.actionType)}
                            {action.actionType.replace(/_/g, ' ')}
                          </Badge>
                          <Badge variant={action.success ? 'default' : 'destructive'} className="text-[10px] h-4 px-1">
                            {action.success ? '✓' : '✗'}
                          </Badge>
                          <Badge className={`${getTriggerColor(action.triggeredBy)} text-[10px] h-4 px-1`}>
                            {action.triggeredBy.replace(/_/g, ' ')}
                          </Badge>
                        </div>
                        <span className="text-[10px] text-muted-foreground">{formatDate(action.createdAt)}</span>
                      </div>
                      <div className="flex items-center gap-3 text-[10px]">
                        {(action.oldStopLoss !== null && action.newStopLoss !== null) && (
                          <span>
                            SL: <span className="text-muted-foreground font-mono">{action.oldStopLoss.toFixed(5)}</span>
                            <span className="mx-0.5">→</span>
                            <span className="font-mono text-orange-600 font-medium">{action.newStopLoss.toFixed(5)}</span>
                          </span>
                        )}
                        {(action.oldTakeProfit !== null && action.newTakeProfit !== null) && (
                          <span>
                            TP: <span className="text-muted-foreground font-mono">{action.oldTakeProfit.toFixed(5)}</span>
                            <span className="mx-0.5">→</span>
                            <span className="font-mono text-primary font-medium">{action.newTakeProfit.toFixed(5)}</span>
                          </span>
                        )}
                        {action.profitPips !== null && action.profitPips !== undefined && (
                          <span className={action.profitPips >= 0 ? 'text-success' : 'text-destructive'}>
                            {action.profitPips >= 0 ? '+' : ''}{action.profitPips.toFixed(1)} pips
                          </span>
                        )}
                      </div>
                      {userCommand && (
                        <div className="mt-1 font-mono bg-muted/40 px-1.5 py-0.5 rounded inline-block text-[10px]">
                          &quot;{userCommand}&quot;
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Original Signal */}
          {trade.signal && (
            <div>
              <div className="flex items-center gap-2 text-xs font-semibold mb-2">
                <MessageSquare className="h-3.5 w-3.5 text-primary" />
                Original Signal
                <Link href={`/history/signals/${trade.signal.id}`} onClick={(e) => e.stopPropagation()}>
                  <Badge variant="outline" className="text-[10px] h-3.5 px-1 cursor-pointer hover:bg-muted">
                    View →
                  </Badge>
                </Link>
              </div>
              <TelegramText text={trade.signal.rawMessage} className="bg-card p-2.5 rounded-lg text-[11px] leading-relaxed max-h-28 overflow-auto border border-border/50" />
              <div className="mt-1 flex gap-3 text-[10px] text-muted-foreground">
                <span>Channel: {trade.signal.channelName || trade.signal.channelId}</span>
                <span>Msg #{trade.signal.messageId}</span>
              </div>
            </div>
          )}

          {/* View full details link */}
          <div className="flex justify-end">
            <Link href={`/history/trades/${trade.id}`}>
              <Button variant="ghost" size="sm" className="h-6 text-xs px-2 text-primary">
                View full details
                <ExternalLink className="h-3 w-3 ml-1" />
              </Button>
            </Link>
          </div>
        </div>
      )}
    </div>
  )
}
