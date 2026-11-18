'use client'

import { useState } from 'react'
import Link from 'next/link'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { formatDate, getStatusColor, formatCurrency } from '@/lib/utils'
import {
  TrendingUp,
  TrendingDown,
  Clock,
  MessageSquare,
  ShieldCheck,
  ShieldAlert,
  ExternalLink,
  Zap,
  ChevronDown,
  ChevronRight,
  ArrowRight,
  CheckCircle2,
  Info,
  Activity,
  Trash2,
  Loader2,
  Brain,
  Sparkles,
  AlertTriangle,
  AlertCircle,
  ImageIcon,
  X,
} from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import type { SignalWithTrades } from '@/lib/types'
import TelegramText from '@/components/TelegramText'

interface SignalCardProps {
  signal: SignalWithTrades
  compact?: boolean
  defaultExpanded?: boolean
  onSignalDeleted?: () => void
}

export default function SignalCard({ signal, compact = false, defaultExpanded = false, onSignalDeleted }: SignalCardProps) {
  const [expanded, setExpanded] = useState(defaultExpanded)
  const [isDeleting, setIsDeleting] = useState(false)
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [isImageOpen, setIsImageOpen] = useState(false)
  const hasImage = !!(signal as SignalWithTrades & { hasImage?: boolean }).hasImage
  const totalPnL = signal.trades.reduce((sum, t) => sum + (t.profitLoss || 0), 0)
  const isBuy = signal.orderType?.toUpperCase().includes('BUY')
  const isProblematic = signal.aiVerificationType === 'UNCLEAR' || signal.aiVerificationType === 'WRONG_EXECUTION'
  const hasReplies = signal.replies && signal.replies.length > 0
  const repliesWithActions = signal.replies?.filter(r => r.actionTaken) || []
  const totalTradeActions = signal.trades.reduce((sum, t) => sum + (t.tradeActions?.length || 0), 0)
  
  // Get all market analyses from trades
  const allMarketAnalyses = signal.trades.flatMap(t => t.marketAnalyses || [])
  const hasMarketAnalysis = allMarketAnalyses.length > 0
  const latestMarketAnalysis = hasMarketAnalysis ? allMarketAnalyses[0] : null
  
  const hasExpandableContent = hasReplies || signal.trades.length > 0 || signal.rawMessage || hasMarketAnalysis

  const getVerificationInfo = () => {
    if (!signal.aiVerified) {
      return { label: 'Unverified', color: 'bg-muted text-muted-foreground dark:bg-muted dark:text-muted-foreground/70', icon: ShieldAlert }
    }
    const map: Record<string, { label: string; color: string }> = {
      TRADE_SIGNAL: { label: 'Trade Signal', color: 'bg-success/10 text-success border border-success/20 dark:bg-emerald-900/40 dark:text-success/70' },
      INFO_MESSAGE: { label: 'Info Only', color: 'bg-primary/10 text-primary border border-primary/20 dark:bg-sky-900/40 dark:text-sky-300' },
      REPLY: { label: 'Reply', color: 'bg-gold/10 text-gold border border-gold/20 dark:bg-amber-900/40 dark:text-amber-300' },
      WRONG_EXECUTION: { label: 'Wrong Exec', color: 'bg-destructive/10 text-destructive border border-destructive/20 dark:bg-rose-900/40 dark:text-destructive/70' },
      UNCLEAR: { label: 'Unclear', color: 'bg-destructive/10 text-destructive border border-destructive/20 dark:bg-rose-900/40 dark:text-destructive/70' },
      IMAGE_ONLY: { label: 'Image Only', color: 'bg-muted text-muted-foreground border border-border dark:bg-slate-800/60 dark:text-slate-300' },
    }
    const info = map[signal.aiVerificationType || 'UNCLEAR'] || map.UNCLEAR
    return { ...info, icon: signal.aiVerificationType === 'TRADE_SIGNAL' ? ShieldCheck : ShieldAlert }
  }

  const verification = getVerificationInfo()
  const VerifIcon = verification.icon

  const handleDeleteClick = (e: React.MouseEvent) => {
    e.stopPropagation()
    setDeleteError(null)
    setIsDeleteDialogOpen(true)
  }

  const confirmDelete = async () => {
    setIsDeleting(true)
    setDeleteError(null)
    try {
      const response = await fetch(`/api/signals/${signal.id}`, {
        method: 'DELETE',
      })
      
      if (!response.ok) {
        throw new Error('Failed to delete signal')
      }
      
      setIsDeleteDialogOpen(false)
      if (onSignalDeleted) {
        onSignalDeleted()
      }
    } catch (error) {
      console.error('Error deleting signal:', error)
      setDeleteError('Failed to delete signal. Please try again.')
    } finally {
      setIsDeleting(false)
    }
  }

  return (
    <div
      className={`relative rounded-lg border transition-all duration-150 ${
        isProblematic ? 'border-rose-300 bg-destructive/10/40' : 'border-border bg-card'
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
                <span className="font-bold text-sm text-foreground tracking-tight">{signal.symbol}</span>
                <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-4 font-semibold border-border text-foreground/80">
                  {signal.orderType}
                </Badge>
              </div>
              {!compact && signal.channelName && (
                <span className="text-[10px] text-muted-foreground truncate block max-w-[120px] md:max-w-[140px] font-medium">
                  {signal.channelName}
                </span>
              )}
            </div>
          </div>

          <div className="flex flex-col md:flex-row items-end md:items-center gap-1 md:gap-1.5 flex-shrink-0">
            <Badge className={`${getStatusColor(signal.status)} text-[10px] px-1.5 py-0 h-4 font-semibold`}>
              {signal.status}
            </Badge>
            <Badge className={`${verification.color} text-[10px] px-1.5 py-0 h-4 flex items-center gap-0.5 font-semibold`}>
              <VerifIcon className="h-2.5 w-2.5" />
              {verification.label}
            </Badge>
            {hasImage && (
              <Button
                variant="ghost"
                size="sm"
                onClick={(e) => { e.stopPropagation(); setIsImageOpen(true) }}
                className="h-6 w-6 p-0 hover:bg-primary/10 hover:text-primary"
                title="View signal image"
              >
                <ImageIcon className="h-3 w-3" />
              </Button>
            )}
            <Button
              variant="ghost"
              size="sm"
              onClick={handleDeleteClick}
              disabled={isDeleting}
              className="h-6 w-6 p-0 hover:bg-destructive/10 hover:text-destructive"
              title="Delete signal and all related data"
            >
              {isDeleting ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Trash2 className="h-3 w-3" />
              )}
            </Button>
          </div>
        </div>

        <div className="flex items-center gap-3 text-xs flex-wrap">
          {(signal.entryPrice || signal.entryRangeMin || signal.entryRangeMax) && (
            <div className="flex items-center gap-1">
              <span className="text-muted-foreground font-medium">Entry</span>
              {signal.entryRangeMin && signal.entryRangeMax ? (
                <span className="font-mono font-semibold text-foreground">
                  {signal.entryRangeMin.toFixed(5)} – {signal.entryRangeMax.toFixed(5)}
                </span>
              ) : signal.entryRangeMin || signal.entryRangeMax ? (
                <span className="font-mono font-semibold text-foreground">
                  {(signal.entryRangeMin ?? signal.entryRangeMax)!.toFixed(5)}
                </span>
              ) : (
                <span className="font-mono font-semibold text-foreground">{signal.entryPrice!.toFixed(5)}</span>
              )}
            </div>
          )}
          {signal.stopLoss && (
            <div className="flex items-center gap-1">
              <span className="text-muted-foreground font-medium">SL</span>
              <span className="font-mono font-semibold text-destructive">{signal.stopLoss.toFixed(5)}</span>
            </div>
          )}
          {signal.riskRewardRatio && (
            <div className="flex items-center gap-1">
              <span className="text-muted-foreground font-medium">R:R</span>
              <span className="font-mono font-semibold text-foreground">1:{signal.riskRewardRatio.toFixed(1)}</span>
            </div>
          )}
          {signal.confidence && (
            <div className="flex items-center gap-1">
              <Zap className="h-3 w-3 text-gold" />
              <span className="font-semibold text-foreground">{(signal.confidence * 100).toFixed(0)}%</span>
            </div>
          )}
        </div>

        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 sm:gap-0 mt-2 pt-2 border-t border-border">
          <div className="flex items-center gap-3 text-xs">
            {signal.trades.length > 0 ? (
              <div className="flex items-center gap-1">
                <span className="text-muted-foreground">{signal.trades.length} trade{signal.trades.length > 1 ? 's' : ''}</span>
                {totalPnL !== 0 && (
                  <span className={`font-bold ${totalPnL >= 0 ? 'text-success' : 'text-destructive'}`}>
                    {totalPnL >= 0 ? '+' : ''}${totalPnL.toFixed(2)}
                  </span>
                )}
              </div>
            ) : (
              <span className="text-muted-foreground text-[10px]">No trades</span>
            )}
            {hasReplies && (
              <div className="flex items-center gap-0.5 text-muted-foreground">
                <MessageSquare className="h-3 w-3" />
                <span className="text-[10px]">{signal.replies!.length} {repliesWithActions.length > 0 && `(${repliesWithActions.length} acted)`}</span>
              </div>
            )}
            {totalTradeActions > 0 && (
              <div className="flex items-center gap-0.5 text-muted-foreground">
                <Activity className="h-3 w-3" />
                <span className="text-[10px]">{totalTradeActions} actions</span>
              </div>
            )}
            {hasMarketAnalysis && (
              <div className="flex items-center gap-0.5 text-primary dark:text-sky-400">
                <Brain className="h-3 w-3" />
                <span className="text-[10px]">AI</span>
              </div>
            )}
          </div>

          <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
            <Clock className="h-2.5 w-2.5" />
            <span>{formatDate(signal.createdAt)}</span>
            <Link
              href={`/history/signals/${signal.id}`}
              onClick={(e) => e.stopPropagation()}
              className="ml-1 text-primary hover:text-primary/80 transition-colors"
              title="View full details"
            >
              <ExternalLink className="h-3 w-3" />
            </Link>
          </div>
        </div>
      </div>

      {/* Expanded content: Timeline with messages, bot responses, and replies */}
      {expanded && (
        <div className="border-t bg-muted/10 px-3.5 pb-3.5">
          <div className="space-y-0 border-l-2 border-muted ml-3 mt-3">

            {/* Original Signal Message */}
            <div className="relative pl-5 pb-3">
              <div className="absolute -left-[7px] top-1 h-3 w-3 rounded-full bg-sky-500 border-2 border-card" />
              <div className="text-xs">
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-semibold text-sky-700 dark:text-sky-300">Signal Received</span>
                  <span className="text-muted-foreground">{formatDate(signal.createdAt)}</span>
                </div>
                <TelegramText text={signal.rawMessage} className="bg-card p-2.5 rounded-lg text-[11px] leading-relaxed max-h-32 overflow-auto border border-border/50" />
                {hasImage && (
                  <button
                    onClick={() => setIsImageOpen(true)}
                    className="mt-2 flex items-center gap-1.5 text-xs text-primary hover:text-sky-700 font-medium"
                  >
                    <ImageIcon className="h-3.5 w-3.5" />
                    View attached image
                  </button>
                )}
              </div>
            </div>

            {/* Bot Response - Trades Created */}
            {signal.trades.length > 0 && (
              <div className="relative pl-5 pb-3">
                <div className="absolute -left-[7px] top-1 h-3 w-3 rounded-full bg-emerald-500 border-2 border-card" />
                <div className="text-xs">
                  <div className="flex items-center gap-2 mb-1">
                    <ArrowRight className="h-3 w-3 text-success" />
                    <span className="font-semibold text-success dark:text-success/70">Bot Response</span>
                    <span className="text-muted-foreground">{formatDate(signal.trades[0]?.createdAt || signal.createdAt)}</span>
                  </div>
                  <div className="space-y-1">
                    {signal.trades.map((trade, idx) => (
                      <Link key={trade.id} href={`/history/trades/${trade.id}`}>
                        <div className="flex items-center justify-between bg-card p-2 rounded-lg border border-border/50 hover:bg-muted/30 transition-colors cursor-pointer">
                          <div className="flex items-center gap-2">
                            <span className="font-medium">Trade {idx + 1}:</span>
                            <span className="font-mono">{trade.symbol} {trade.action} {trade.lotSize} lots</span>
                            {trade.tpLevel && <Badge variant="outline" className="text-[10px] h-3.5 px-1">TP{trade.tpLevel}</Badge>}
                            {trade.positionId && <span className="text-muted-foreground font-mono">Pos: {trade.positionId}</span>}
                          </div>
                          <div className="flex items-center gap-2">
                            <Badge className={`${getStatusColor(trade.status)} text-[10px] h-3.5 px-1`}>{trade.status}</Badge>
                            {trade.profitLoss !== null && (
                              <span className={`font-bold ${trade.profitLoss >= 0 ? 'text-success' : 'text-destructive'}`}>
                                {formatCurrency(trade.profitLoss)}
                              </span>
                            )}
                          </div>
                        </div>
                      </Link>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* AI Market Analysis */}
            {latestMarketAnalysis && (() => {
              const hasRecommendations =
                latestMarketAnalysis.recommendBreakeven ||
                latestMarketAnalysis.recommendTpAdjustment ||
                latestMarketAnalysis.recommendReducePosition ||
                latestMarketAnalysis.recommendTightStop
              
              if (!hasRecommendations) return null

              return (
                <div className="relative pl-5 pb-3">
                  <div className="absolute -left-[7px] top-1 h-3 w-3 rounded-full bg-sky-500 border-2 border-card" />
                  <div className="p-2.5 rounded-lg bg-primary/8/50 dark:bg-sky-950/10 border border-sky-200 dark:border-sky-800">
                    <div className="flex items-center gap-2 mb-2 text-xs">
                      <Brain className="h-3.5 w-3.5 text-primary" />
                      <span className="font-semibold text-sky-900 dark:text-sky-100">AI Market Analysis</span>
                      <Badge variant="outline" className="text-[10px] h-3.5 px-1">
                        {Math.round(Number(latestMarketAnalysis.confidence) * 100)}%
                      </Badge>
                      <span className="text-muted-foreground">
                        {(latestMarketAnalysis.trend ?? '').replace('_', ' ')} · Vol: {latestMarketAnalysis.volatility ?? 'N/A'}
                      </span>
                    </div>
                    <div className="space-y-1">
                      {latestMarketAnalysis.recommendBreakeven && (
                        <div className="flex items-center gap-2 text-xs bg-gold/10/60 dark:bg-amber-900/20 px-2 py-1 rounded">
                          <Sparkles className="h-3 w-3 text-gold" />
                          <span className="font-medium">🛡️ Move to breakeven</span>
                        </div>
                      )}
                      {latestMarketAnalysis.recommendTpAdjustment && (
                        <div className="flex items-center gap-2 text-xs bg-success/10/60 dark:bg-emerald-900/20 px-2 py-1 rounded">
                          <Sparkles className="h-3 w-3 text-success" />
                          <span className="font-medium">🎯 Extend TP {latestMarketAnalysis.recommendTpDirection}</span>
                        </div>
                      )}
                      {latestMarketAnalysis.recommendReducePosition && (
                        <div className="flex items-center gap-2 text-xs bg-orange-100/60 dark:bg-orange-900/20 px-2 py-1 rounded">
                          <Sparkles className="h-3 w-3 text-orange-600" />
                          <span className="font-medium">📉 Reduce position</span>
                        </div>
                      )}
                      {latestMarketAnalysis.recommendTightStop && (
                        <div className="flex items-center gap-2 text-xs bg-destructive/10/60 dark:bg-rose-900/20 px-2 py-1 rounded">
                          <Sparkles className="h-3 w-3 text-destructive" />
                          <span className="font-medium">⚠️ Tighten stop loss</span>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )
            })()}

            {/* Replies & Actions */}
            {signal.replies && signal.replies.map((reply) => (
              <div key={reply.id} className="relative pl-5 pb-3">
                <div className={`absolute -left-[7px] top-1 h-3 w-3 rounded-full border-2 border-card ${
                  reply.actionSuccess ? 'bg-emerald-500' : reply.actionTaken ? 'bg-amber-500' : 'bg-violet-500'
                }`} />
                <div className="text-xs">
                  <div className="flex items-center gap-2 mb-1 flex-wrap">
                    <MessageSquare className="h-3 w-3 text-muted-foreground" />
                    <span className={`font-semibold ${
                      reply.actionSuccess ? 'text-success dark:text-success/70'
                      : reply.actionTaken ? 'text-gold dark:text-amber-300'
                      : 'text-violet-700 dark:text-violet-300'
                    }`}>
                      {reply.username ? `@${reply.username}` : 'User'} Reply
                    </span>
                    <span className="text-muted-foreground">{formatDate(reply.createdAt)}</span>
                    {reply.aiParsed && <Badge variant="secondary" className="text-[10px] h-3.5 px-1">🤖 AI</Badge>}
                    {reply.actionSuccess && <Badge className="text-[10px] h-3.5 px-1 bg-emerald-600 text-white">✓ Done</Badge>}
                    {!reply.actionTaken && !reply.processingError && (
                      <Badge variant="secondary" className="text-[10px] h-3.5 px-1">
                        <Info className="h-2 w-2 mr-0.5" /> No Action
                      </Badge>
                    )}
                  </div>
                  <TelegramText text={reply.replyText} className="bg-card p-2 rounded-lg border border-border/50 text-[11px] mb-1" />
                  {reply.actionTaken && (
                    <div className="space-y-0.5 text-muted-foreground ml-1">
                      {reply.actionType && (
                        <div className="flex items-center gap-1">
                          <CheckCircle2 className="h-3 w-3 text-success" />
                          <span className="font-medium text-foreground">{reply.actionType}</span>
                        </div>
                      )}
                      {reply.actionResult && (
                        <p className={reply.actionSuccess ? 'text-success' : 'text-gold'}>
                          {reply.actionResult}
                        </p>
                      )}
                      {(reply.positionsClosed > 0 || reply.ordersCancelled > 0) && (
                        <div className="flex gap-3">
                          {reply.positionsClosed > 0 && <span>🔴 Closed: {reply.positionsClosed}</span>}
                          {reply.ordersCancelled > 0 && <span>❌ Cancelled: {reply.ordersCancelled}</span>}
                        </div>
                      )}
                    </div>
                  )}
                  {reply.processingError && (
                    <div className="mt-1 p-1.5 rounded bg-destructive/10 dark:bg-rose-950/20 text-destructive text-[10px]">
                      ❌ {reply.processingError}
                    </div>
                  )}
                </div>
              </div>
            ))}

            {/* No interactions placeholder */}
            {(!signal.replies || signal.replies.length === 0) && signal.trades.length === 0 && (
              <div className="relative pl-5 pb-2">
                <div className="absolute -left-[7px] top-1 h-3 w-3 rounded-full bg-muted border-2 border-card" />
                <p className="text-xs text-muted-foreground italic">No interactions yet</p>
              </div>
            )}
          </div>

          {/* View full details link */}
          <div className="mt-2 flex justify-end">
            <Link href={`/history/signals/${signal.id}`}>
              <Button variant="ghost" size="sm" className="h-6 text-xs px-2 text-primary">
                View full details
                <ExternalLink className="h-3 w-3 ml-1" />
              </Button>
            </Link>
          </div>
        </div>
      )}

      {/* Signal Image Modal */}
      {isImageOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
          onClick={() => setIsImageOpen(false)}
        >
          <div
            className="relative max-w-3xl max-h-[90vh] w-full mx-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="bg-card rounded-xl shadow-2xl overflow-hidden">
              <div className="flex items-center justify-between px-4 py-2.5 border-b">
                <div className="flex items-center gap-2 text-sm font-semibold text-foreground/90">
                  <ImageIcon className="h-4 w-4 text-primary" />
                  Signal Image — {signal.symbol} {signal.orderType}
                </div>
                <button
                  onClick={() => setIsImageOpen(false)}
                  className="p-1 rounded hover:bg-muted transition-colors"
                >
                  <X className="h-4 w-4 text-muted-foreground" />
                </button>
              </div>
              <div className="p-2 flex items-center justify-center bg-muted/50 max-h-[80vh] overflow-auto">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={`/api/signals/${signal.id}/image`}
                  alt={`Signal image for ${signal.symbol}`}
                  className="max-w-full max-h-[75vh] object-contain rounded"
                />
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Dialog */}
      <Dialog open={isDeleteDialogOpen} onOpenChange={setIsDeleteDialogOpen}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <div className="flex items-center gap-3 mb-2">
              <div className="w-10 h-10 rounded-full bg-destructive/10 flex items-center justify-center">
                <AlertTriangle className="h-6 w-6 text-destructive" />
              </div>
              <DialogTitle className="text-xl">Delete Signal?</DialogTitle>
            </div>
            <DialogDescription className="text-muted-foreground py-2">
              Are you sure you want to delete this signal and all related data? 
              <span className="block mt-2 font-semibold text-destructive">This action cannot be undone.</span>
            </DialogDescription>
          </DialogHeader>
          
          <div className="bg-muted/50 p-4 rounded-lg border border-border mt-2">
            <h4 className="text-xs font-bold text-foreground/80 uppercase tracking-wider mb-2">Items to be deleted:</h4>
            <ul className="space-y-1.5">
              <li className="flex items-center gap-2 text-xs text-muted-foreground">
                <div className="w-1 h-1 rounded-full bg-muted" />
                Signal message and history
              </li>
              <li className="flex items-center gap-2 text-xs text-muted-foreground">
                <div className="w-1 h-1 rounded-full bg-muted" />
                All associated trades ({signal.trades.length})
              </li>
              <li className="flex items-center gap-2 text-xs text-muted-foreground">
                <div className="w-1 h-1 rounded-full bg-muted" />
                Trade actions and market analyses
              </li>
              <li className="flex items-center gap-2 text-xs text-muted-foreground">
                <div className="w-1 h-1 rounded-full bg-muted" />
                User replies and bot responses
              </li>
            </ul>
          </div>

          {deleteError && (
            <div className="bg-destructive/10 border border-rose-200 text-destructive text-xs p-3 rounded-lg flex items-start gap-2 mt-2">
              <AlertCircle className="h-4 w-4 flex-shrink-0 mt-0.5" />
              <span>{deleteError}</span>
            </div>
          )}

          <DialogFooter className="mt-4 gap-2 sm:gap-0">
            <Button
              variant="outline"
              onClick={() => setIsDeleteDialogOpen(false)}
              disabled={isDeleting}
              className="font-bold"
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={(e) => {
                e.preventDefault();
                confirmDelete();
              }}
              disabled={isDeleting}
              className="font-bold bg-rose-600 hover:bg-rose-700"
            >
              {isDeleting ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Deleting...
                </>
              ) : (
                'Delete Signal'
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
