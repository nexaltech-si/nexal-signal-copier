'use client'

import { useState } from 'react'
import Link from 'next/link'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogDescription,
  DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import {
  ShieldCheck, ShieldAlert, Loader2, TrendingUp, TrendingDown,
  ChevronDown, ChevronRight, ImageIcon, Trash2,
  AlertTriangle, AlertCircle, MessageSquare, ExternalLink, X, Zap,
  Hash, CalendarDays, Radio,
} from 'lucide-react'
import type { SignalWithTrades } from '@/lib/types'
import { formatDate, getStatusColor, formatCurrency } from '@/lib/utils'
import TelegramText from '@/components/TelegramText'

interface SignalsTableProps {
  signals: SignalWithTrades[]
  onSignalVerified?: () => void
  onSignalDeleted?: () => void
}

// ── Verification badge ─────────────────────────────────────────────────────────
function VerifBadge({ signal }: { signal: SignalWithTrades }) {
  if (!signal.aiVerified) {
    return (
      <span className="inline-flex items-center gap-0.5 text-[10px] font-medium text-muted-foreground/70">
        <ShieldAlert className="h-2.5 w-2.5" /> Unverified
      </span>
    )
  }
  const map: Record<string, { label: string; cls: string }> = {
    TRADE_SIGNAL: { label: 'Signal', cls: 'text-success bg-success/10 border-emerald-200' },
    INFO_MESSAGE: { label: 'Info', cls: 'text-sky-700 bg-primary/8 border-sky-200' },
    REPLY:        { label: 'Reply', cls: 'text-gold bg-gold/10 border-amber-200' },
    WRONG_EXECUTION: { label: 'Wrong', cls: 'text-destructive bg-destructive/10 border-rose-200' },
    UNCLEAR:      { label: 'Unclear', cls: 'text-destructive bg-destructive/10 border-rose-200' },
    IMAGE_ONLY:   { label: 'Image Only', cls: 'text-muted-foreground bg-muted border-border' },
  }
  const info = map[signal.aiVerificationType || 'UNCLEAR'] || map.UNCLEAR
  return (
    <span className={`inline-flex items-center gap-0.5 text-[10px] font-semibold px-1.5 py-0.5 rounded-full border ${info.cls}`}>
      <ShieldCheck className="h-2.5 w-2.5" />
      {info.label}
    </span>
  )
}

// ── Column header ──────────────────────────────────────────────────────────────
const COL = 'py-2.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70 select-none'

export default function SignalsTable({ signals, onSignalVerified, onSignalDeleted }: SignalsTableProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [verifyingSignals, setVerifyingSignals] = useState<Set<string>>(new Set())
  const [imageOpenId, setImageOpenId] = useState<string | null>(null)
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const unverifiedCount = signals.filter(s => !s.aiVerified).length

  const verifyAll = async () => {
    const ids = signals.filter(s => !s.aiVerified).map(s => s.id)
    if (!ids.length) return
    if (!confirm(`Verify ${ids.length} signals with DeepSeek AI?`)) return
    ids.forEach(id => setVerifyingSignals(prev => new Set(prev).add(id)))
    try {
      const res = await fetch('/api/signals/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ signalIds: ids }),
      })
      if (!res.ok) throw new Error()
      onSignalVerified?.()
    } catch {
      alert('Failed to verify some signals.')
    } finally {
      setVerifyingSignals(new Set())
    }
  }

  const doDelete = async (id: string) => {
    setIsDeleting(true)
    setDeleteError(null)
    try {
      const res = await fetch(`/api/signals/${id}`, { method: 'DELETE' })
      if (!res.ok) throw new Error()
      setDeleteConfirmId(null)
      onSignalDeleted?.()
    } catch {
      setDeleteError('Failed to delete signal. Please try again.')
    } finally {
      setIsDeleting(false)
    }
  }

  // ── Empty state ──────────────────────────────────────────────────────────────
  if (signals.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-muted-foreground/70">
        <div className="w-12 h-12 rounded-full bg-muted flex items-center justify-center mb-3">
          <TrendingUp className="h-6 w-6 text-muted-foreground/70" />
        </div>
        <p className="text-sm font-medium text-muted-foreground">No signals found</p>
        <p className="text-xs mt-1">Try adjusting your filters or date range</p>
      </div>
    )
  }

  return (
    <>
      <div className="rounded-xl border border-border overflow-hidden bg-card shadow-sm">

        {/* ── Table toolbar ──────────────────────────────────────────────────── */}
        <div className="flex items-center justify-between px-4 py-2.5 bg-muted/50 border-b border-border">
          <div className="flex items-center gap-2.5">
            <span className="text-xs font-semibold text-foreground">{signals.length} signals</span>
            {unverifiedCount > 0 && (
              <span className="text-[10px] font-semibold text-gold bg-gold/10 border border-amber-200 px-2 py-0.5 rounded-full">
                {unverifiedCount} unverified
              </span>
            )}
          </div>
          {unverifiedCount > 0 && (
            <Button
              size="sm" variant="outline"
              onClick={verifyAll}
              disabled={verifyingSignals.size > 0}
              className="h-7 text-xs border-border hover:bg-primary/10 text-foreground"
            >
              {verifyingSignals.size > 0
                ? <><Loader2 className="h-3 w-3 mr-1 animate-spin" />Verifying…</>
                : <><ShieldCheck className="h-3 w-3 mr-1" />Verify All ({unverifiedCount})</>
              }
            </Button>
          )}
        </div>

        {/* ── Column headers (desktop) ───────────────────────────────────────── */}
        <div
          className="hidden md:grid items-center px-3 border-b border-border bg-muted/50"
          style={{ gridTemplateColumns: '28px 28px minmax(110px,1fr) 60px 94px 72px 92px 84px 96px 52px' }}
        >
          <div className={COL} />
          <div className={COL} />
          <div className={`${COL} px-1`}>Symbol</div>
          <div className={`${COL} px-1`}>Type</div>
          <div className={`${COL} px-1`}>Entry</div>
          <div className={`${COL} px-1`}>SL</div>
          <div className={`${COL} px-1`}>Status</div>
          <div className={`${COL} px-1`}>Verif.</div>
          <div className={`${COL} px-1`}>Date</div>
          <div className={COL} />
        </div>

        {/* ── Rows ──────────────────────────────────────────────────────────── */}
        <div className="divide-y divide-slate-200">
          {signals.map((signal) => {
            const isBuy = signal.orderType?.toUpperCase().includes('BUY')
            const isExpanded = expandedId === signal.id
            const hasImage = !!(signal as SignalWithTrades & { hasImage?: boolean }).hasImage
            const totalPnL = signal.trades.reduce((s, t) => s + (t.profitLoss || 0), 0)
            const hasReplies = !!(signal.replies?.length)
            const isProblematic = signal.aiVerificationType === 'UNCLEAR' || signal.aiVerificationType === 'WRONG_EXECUTION'

            // Parse TP levels from JSON string
            let tpLevels: number[] = []
            try {
              if (signal.takeProfit) tpLevels = JSON.parse(signal.takeProfit)
            } catch { /* ignore */ }

            return (
              <div key={signal.id} className={isProblematic ? 'bg-destructive/10/30' : ''}>

                {/* ── Desktop row ──────────────────────────────────────────── */}
                <div
                  className={`hidden md:grid items-center px-3 h-11 cursor-pointer select-none transition-colors duration-100
                    ${isExpanded ? 'bg-primary/5' : 'hover:bg-muted/50'}`}
                  style={{ gridTemplateColumns: '28px 28px minmax(110px,1fr) 60px 94px 72px 92px 84px 96px 52px' }}
                  onClick={() => setExpandedId(isExpanded ? null : signal.id)}
                >
                  {/* Expand chevron */}
                  <div className="flex items-center justify-center">
                    {isExpanded
                      ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                      : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/70" />}
                  </div>

                  {/* Direction icon */}
                  <div className={`flex items-center justify-center w-6 h-6 rounded ${isBuy ? 'bg-success/10' : 'bg-destructive/10'}`}>
                    {isBuy
                      ? <TrendingUp className="h-3.5 w-3.5 text-success" />
                      : <TrendingDown className="h-3.5 w-3.5 text-destructive" />}
                  </div>

                  {/* Symbol + meta */}
                  <div className="px-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="font-semibold text-xs text-foreground truncate">{signal.symbol}</span>
                      {signal.trades.length > 0 && (
                        <span className="text-[10px] text-muted-foreground/70 shrink-0">{signal.trades.length}t</span>
                      )}
                      {totalPnL !== 0 && (
                        <span className={`text-[10px] font-bold shrink-0 ${totalPnL >= 0 ? 'text-success' : 'text-destructive'}`}>
                          {totalPnL >= 0 ? '+' : ''}{totalPnL.toFixed(2)}
                        </span>
                      )}
                    </div>
                    {signal.channelName && (
                      <span className="text-[10px] text-muted-foreground/70 block truncate leading-none mt-0.5">{signal.channelName}</span>
                    )}
                  </div>

                  {/* Order type */}
                  <div className="px-1">
                    <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${isBuy ? 'text-success bg-success/10' : 'text-destructive bg-destructive/10'}`}>
                      {signal.orderType}
                    </span>
                  </div>

                  {/* Entry */}
                  <div className="px-1">
                    <span className="font-mono text-xs text-foreground">
                      {signal.entryRangeMin && signal.entryRangeMax
                        ? `${signal.entryRangeMin.toFixed(5)}–${signal.entryRangeMax.toFixed(5)}`
                        : signal.entryPrice
                        ? signal.entryPrice.toFixed(5)
                        : <span className="text-muted-foreground/50">—</span>}
                    </span>
                  </div>

                  {/* SL */}
                  <div className="px-1">
                    <span className="font-mono text-xs text-destructive">
                      {signal.stopLoss ? signal.stopLoss.toFixed(5) : <span className="text-muted-foreground/50">—</span>}
                    </span>
                  </div>

                  {/* Status */}
                  <div className="px-1">
                    <Badge className={`${getStatusColor(signal.status)} text-[10px] px-1.5 py-0 h-[18px] font-semibold`}>
                      {signal.status}
                    </Badge>
                  </div>

                  {/* Verification */}
                  <div className="px-1">
                    <VerifBadge signal={signal} />
                  </div>

                  {/* Date */}
                  <div className="px-1">
                    <span className="text-[10px] text-muted-foreground/70 whitespace-nowrap">{formatDate(signal.createdAt)}</span>
                  </div>

                  {/* Quick actions */}
                  <div className="flex items-center gap-0.5 justify-end" onClick={e => e.stopPropagation()}>
                    {hasImage && (
                      <button
                        onClick={() => setImageOpenId(signal.id)}
                        className="p-1 rounded hover:bg-primary/10 text-sky-400 hover:text-primary transition-colors"
                        title="View image"
                      >
                        <ImageIcon className="h-3 w-3" />
                      </button>
                    )}
                    <button
                      onClick={() => { setDeleteConfirmId(signal.id); setDeleteError(null) }}
                      className="p-1 rounded hover:bg-destructive/10 text-muted-foreground/50 hover:text-destructive transition-colors"
                      title="Delete"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </div>
                </div>

                {/* ── Mobile row ───────────────────────────────────────────── */}
                <div
                  className="md:hidden p-3 cursor-pointer active:bg-muted/50"
                  onClick={() => setExpandedId(isExpanded ? null : signal.id)}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <div className={`flex items-center justify-center w-7 h-7 rounded-md shrink-0 ${isBuy ? 'bg-success/10' : 'bg-destructive/10'}`}>
                        {isBuy ? <TrendingUp className="h-4 w-4 text-success" /> : <TrendingDown className="h-4 w-4 text-destructive" />}
                      </div>
                      <div className="min-w-0">
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <span className="font-bold text-sm text-foreground">{signal.symbol}</span>
                          <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${isBuy ? 'text-success bg-success/10' : 'text-destructive bg-destructive/10'}`}>
                            {signal.orderType}
                          </span>
                        </div>
                        {signal.channelName && (
                          <span className="text-[10px] text-muted-foreground/70 block">{signal.channelName}</span>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      <Badge className={`${getStatusColor(signal.status)} text-[10px] px-1.5 py-0 h-4 font-semibold`}>{signal.status}</Badge>
                      {isExpanded ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" /> : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/70" />}
                    </div>
                  </div>
                  <div className="flex items-center gap-3 text-xs mt-1.5 flex-wrap">
                    {(signal.entryRangeMin || signal.entryPrice) && (
                      <span><span className="text-muted-foreground/70">Entry </span>
                        <span className="font-mono font-semibold">
                          {signal.entryRangeMin && signal.entryRangeMax
                            ? `${signal.entryRangeMin.toFixed(5)}–${signal.entryRangeMax.toFixed(5)}`
                            : signal.entryPrice?.toFixed(5)}
                        </span>
                      </span>
                    )}
                    {signal.stopLoss && (
                      <span><span className="text-muted-foreground/70">SL </span><span className="font-mono font-semibold text-destructive">{signal.stopLoss.toFixed(5)}</span></span>
                    )}
                    {totalPnL !== 0 && (
                      <span className={`font-bold ${totalPnL >= 0 ? 'text-success' : 'text-destructive'}`}>
                        {totalPnL >= 0 ? '+' : ''}${totalPnL.toFixed(2)}
                      </span>
                    )}
                  </div>
                </div>

                {/* ── Expanded detail panel ─────────────────────────────────── */}
                {isExpanded && (
                  <div className="border-t border-border bg-muted/50 px-4 md:px-5 py-4">

                    {/* ── Stats strip ───────────────────────────────────────── */}
                    <div className="flex items-center gap-5 flex-wrap mb-4 pb-3 border-b border-border">
                      {(signal.entryRangeMin || signal.entryPrice) && (
                        <div>
                          <p className="text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/70 mb-0.5">Entry</p>
                          <p className="font-mono text-xs font-semibold text-foreground">
                            {signal.entryRangeMin && signal.entryRangeMax
                              ? `${signal.entryRangeMin.toFixed(5)} – ${signal.entryRangeMax.toFixed(5)}`
                              : signal.entryPrice?.toFixed(5)}
                          </p>
                        </div>
                      )}
                      {signal.stopLoss && (
                        <div>
                          <p className="text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/70 mb-0.5">Stop Loss</p>
                          <p className="font-mono text-xs font-semibold text-destructive">{signal.stopLoss.toFixed(5)}</p>
                        </div>
                      )}
                      {tpLevels.map((tp, i) => (
                        <div key={i}>
                          <p className="text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/70 mb-0.5">TP{i + 1}</p>
                          <p className="font-mono text-xs font-semibold text-success">{Number(tp).toFixed(5)}</p>
                        </div>
                      ))}
                      {signal.riskRewardRatio && (
                        <div>
                          <p className="text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/70 mb-0.5">R:R</p>
                          <p className="font-mono text-xs font-semibold text-foreground">1:{signal.riskRewardRatio.toFixed(1)}</p>
                        </div>
                      )}
                      {signal.confidence > 0 && (
                        <div>
                          <p className="text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/70 mb-0.5">Confidence</p>
                          <div className="flex items-center gap-1">
                            <Zap className="h-3 w-3 text-gold" />
                            <p className="text-xs font-bold text-gold">{(signal.confidence * 100).toFixed(0)}%</p>
                          </div>
                        </div>
                      )}
                      {totalPnL !== 0 && (
                        <div>
                          <p className="text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/70 mb-0.5">Total P&L</p>
                          <p className={`text-xs font-bold ${totalPnL >= 0 ? 'text-success' : 'text-destructive'}`}>
                            {totalPnL >= 0 ? '+' : ''}{formatCurrency(totalPnL)}
                          </p>
                        </div>
                      )}
                      <div className="ml-auto">
                        <VerifBadge signal={signal} />
                      </div>
                    </div>

                    {/* ── Main 3-column grid ─────────────────────────────────── */}
                    <div className="grid xl:grid-cols-3 lg:grid-cols-2 gap-4">

                      {/* Col 1: Raw message */}
                      <div className="flex flex-col gap-2">
                        <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70">Raw Message</p>
                        <TelegramText text={signal.rawMessage} className="bg-[#181715] text-[#e2e0db] p-3 rounded-lg text-[11px] leading-relaxed flex-1 max-h-52 overflow-auto border border-[#252320]" />
                        {hasImage && (
                          <button
                            onClick={() => setImageOpenId(signal.id)}
                            className="flex items-center gap-1.5 text-xs text-primary hover:text-sky-700 font-medium"
                          >
                            <ImageIcon className="h-3.5 w-3.5" />
                            View attached image
                          </button>
                        )}
                      </div>

                      {/* Col 2: Trades */}
                      <div className="flex flex-col gap-2">
                        <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70">
                          Trades {signal.trades.length > 0 ? `(${signal.trades.length})` : ''}
                        </p>
                        {signal.trades.length > 0 ? (
                          <div className="space-y-1">
                            {signal.trades.map((trade, idx) => (
                              <Link key={trade.id} href={`/history/trades/${trade.id}`}>
                                <div className="flex items-center justify-between bg-card px-2.5 py-2 rounded-lg border border-border hover:bg-primary/10 transition-colors text-xs cursor-pointer">
                                  <div className="flex items-center gap-2">
                                    <span className="text-[10px] font-semibold text-muted-foreground/70">#{idx + 1}</span>
                                    <span className="font-mono text-foreground">{trade.action}</span>
                                    <span className="text-[10px] text-muted-foreground/70">{trade.lotSize}L</span>
                                    {trade.tpLevel && <Badge variant="outline" className="text-[10px] h-3.5 px-1 border-border">TP{trade.tpLevel}</Badge>}
                                  </div>
                                  <div className="flex items-center gap-2">
                                    <Badge className={`${getStatusColor(trade.status)} text-[10px] h-3.5 px-1`}>{trade.status}</Badge>
                                    {trade.profitLoss !== null && (
                                      <span className={`font-bold text-[11px] ${Number(trade.profitLoss) >= 0 ? 'text-success' : 'text-destructive'}`}>
                                        {formatCurrency(Number(trade.profitLoss))}
                                      </span>
                                    )}
                                  </div>
                                </div>
                              </Link>
                            ))}
                          </div>
                        ) : (
                          <div className="flex-1 flex items-center justify-center bg-card rounded-lg border border-border py-6">
                            <p className="text-xs text-muted-foreground/70">No trades executed</p>
                          </div>
                        )}
                      </div>

                      {/* Col 3: Replies + Signal metadata */}
                      <div className="flex flex-col gap-3">
                        {hasReplies && (
                          <div className="flex flex-col gap-1.5">
                            <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70 flex items-center gap-1">
                              <MessageSquare className="h-3 w-3" />
                              Replies ({signal.replies!.length})
                              {signal.replies!.filter(r => r.actionTaken).length > 0 && (
                                <span className="text-success font-semibold ml-0.5">
                                  · {signal.replies!.filter(r => r.actionTaken).length} acted
                                </span>
                              )}
                            </p>
                            <div className="space-y-1">
                              {signal.replies!.slice(0, 4).map(reply => (
                                <div key={reply.id} className="bg-card rounded-lg border border-border px-2.5 py-1.5 text-xs">
                                  <div className="flex items-center justify-between gap-2 mb-0.5">
                                    <span className="font-medium text-foreground/80 truncate">
                                      {reply.username || `User ${reply.userId}`}
                                    </span>
                                    <span className="text-[10px] text-muted-foreground/70 shrink-0">{formatDate(reply.createdAt)}</span>
                                  </div>
                                  {reply.replyText && (
                                    <TelegramText text={reply.replyText} inline className="text-[11px] text-muted-foreground truncate" />
                                  )}
                                  {reply.actionTaken && (
                                    <span className="text-[10px] font-semibold text-success">→ {reply.actionType}</span>
                                  )}
                                </div>
                              ))}
                              {signal.replies!.length > 4 && (
                                <p className="text-[10px] text-muted-foreground/70 text-center">+{signal.replies!.length - 4} more</p>
                              )}
                            </div>
                          </div>
                        )}

                        {/* Signal metadata */}
                        <div className="flex flex-col gap-1.5">
                          <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70">Signal Info</p>
                          <div className="bg-card rounded-lg border border-border divide-y divide-slate-100">
                            {signal.channelName && (
                              <div className="flex items-center justify-between px-3 py-2">
                                <span className="text-[10px] text-muted-foreground/70 flex items-center gap-1"><Radio className="h-2.5 w-2.5" />Channel</span>
                                <span className="text-[11px] font-medium text-foreground/80 truncate ml-4 max-w-[140px]">{signal.channelName}</span>
                              </div>
                            )}
                            <div className="flex items-center justify-between px-3 py-2">
                              <span className="text-[10px] text-muted-foreground/70 flex items-center gap-1"><Hash className="h-2.5 w-2.5" />Message</span>
                              <span className="text-[11px] font-mono font-medium text-foreground/80">#{signal.messageId}</span>
                            </div>
                            <div className="flex items-center justify-between px-3 py-2">
                              <span className="text-[10px] text-muted-foreground/70 flex items-center gap-1"><CalendarDays className="h-2.5 w-2.5" />Received</span>
                              <span className="text-[11px] text-foreground/80">{formatDate(signal.createdAt)}</span>
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>

                    {/* Footer */}
                    <div className="flex items-center justify-between mt-4 pt-3 border-t border-border">
                      <button
                        onClick={() => { setDeleteConfirmId(signal.id); setDeleteError(null) }}
                        className="flex items-center gap-1.5 text-xs text-muted-foreground/70 hover:text-destructive font-medium transition-colors"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                        Delete signal
                      </button>
                      <Link href={`/history/signals/${signal.id}`}>
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

      {/* ── Image modal ──────────────────────────────────────────────────────── */}
      {imageOpenId && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm"
          onClick={() => setImageOpenId(null)}
        >
          <div className="relative max-w-4xl max-h-[90vh] w-full mx-4" onClick={e => e.stopPropagation()}>
            <div className="bg-card rounded-xl shadow-2xl overflow-hidden">
              <div className="flex items-center justify-between px-4 py-3 border-b border-border">
                <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                  <ImageIcon className="h-4 w-4 text-primary" />
                  Signal Image
                </div>
                <button onClick={() => setImageOpenId(null)} className="p-1.5 rounded-lg hover:bg-muted transition-colors">
                  <X className="h-4 w-4 text-muted-foreground" />
                </button>
              </div>
              <div className="p-3 bg-muted/50 flex items-center justify-center min-h-48 max-h-[80vh] overflow-auto">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={`/api/signals/${imageOpenId}/image`}
                  alt="Signal image"
                  className="max-w-full max-h-[75vh] object-contain rounded-lg"
                />
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Delete confirmation ───────────────────────────────────────────────── */}
      <Dialog open={!!deleteConfirmId} onOpenChange={open => { if (!open) setDeleteConfirmId(null) }}>
        <DialogContent className="sm:max-w-[400px]">
          <DialogHeader>
            <div className="flex items-center gap-3 mb-1">
              <div className="w-10 h-10 rounded-full bg-destructive/10 flex items-center justify-center shrink-0">
                <AlertTriangle className="h-5 w-5 text-destructive" />
              </div>
              <DialogTitle>Delete Signal?</DialogTitle>
            </div>
            <DialogDescription>
              This will permanently delete the signal and all related trades, actions, and replies. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          {deleteError && (
            <div className="bg-destructive/10 border border-rose-200 text-destructive text-xs p-3 rounded-lg flex items-start gap-2">
              <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
              {deleteError}
            </div>
          )}
          <DialogFooter className="gap-2 sm:gap-2">
            <Button variant="outline" onClick={() => setDeleteConfirmId(null)} disabled={isDeleting} className="border-border">
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => deleteConfirmId && doDelete(deleteConfirmId)}
              disabled={isDeleting}
              className="bg-rose-600 hover:bg-rose-700"
            >
              {isDeleting ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Deleting…</> : 'Delete Signal'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
