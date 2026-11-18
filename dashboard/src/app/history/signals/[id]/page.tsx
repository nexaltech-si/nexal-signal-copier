'use client'

import { useState, useEffect, use } from 'react'
import Link from 'next/link'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { formatDate, getStatusColor, formatCurrency } from '@/lib/utils'
import SignalChart from '@/components/SignalChart'
import ChannelTimelineChart from '@/components/ChannelTimelineChart'
import {
  ArrowLeft,
  TrendingUp,
  TrendingDown,
  Clock,
  MessageSquare,
  ShieldCheck,
  ShieldAlert,
  Loader2,
  Activity,
  Zap,
  Hash,
  Radio,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Info,
  Send,
  ImageIcon,
  X,
  BarChart3,
  ChevronDown,
  ChevronRight as ChevronRightIcon,
  Cpu,
} from 'lucide-react'
import TelegramText from '@/components/TelegramText'

export default function SignalDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const resolvedParams = use(params)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [signal, setSignal] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [verifying, setVerifying] = useState(false)
  const [imageOpen, setImageOpen] = useState(false)
  const [timelineOpen, setTimelineOpen] = useState(false)

  useEffect(() => {
    fetch(`/api/signals/${resolvedParams.id}`)
      .then(res => {
        if (!res.ok) throw new Error('Signal not found')
        return res.json()
      })
      .then(data => { setSignal(data); setLoading(false) })
      .catch(err => { setError(err.message); setLoading(false) })
  }, [resolvedParams.id])

  const verifySignal = async () => {
    setVerifying(true)
    try {
      const response = await fetch('/api/signals/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ signalId: signal.id }),
      })
      if (!response.ok) throw new Error('Verification failed')
      const res = await fetch(`/api/signals/${resolvedParams.id}`)
      const data = await res.json()
      setSignal(data)
    } catch {
      alert('Failed to verify signal')
    } finally {
      setVerifying(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="flex items-center gap-3 text-muted-foreground/70">
          <Loader2 className="h-5 w-5 animate-spin" />
          <span>Loading signal details...</span>
        </div>
      </div>
    )
  }

  if (error || !signal) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4">
        <AlertTriangle className="h-10 w-10 text-destructive" />
        <p className="text-muted-foreground">{error || 'Signal not found'}</p>
        <Link href="/history">
          <Button variant="outline" size="sm">
            <ArrowLeft className="h-3.5 w-3.5 mr-1.5" />
            Back to History
          </Button>
        </Link>
      </div>
    )
  }

  const isBuy = signal.orderType?.toUpperCase().includes('BUY')
  const totalPnL = signal.trades?.reduce((sum: number, t: { profitLoss: number | null }) => sum + (t.profitLoss || 0), 0) || 0
  const isProblematic = signal.aiVerificationType === 'UNCLEAR' || signal.aiVerificationType === 'WRONG_EXECUTION'

  // Parse TP levels
  let tpLevels: number[] = []
  try { if (signal.takeProfit) tpLevels = JSON.parse(signal.takeProfit) } catch { /* ignore */ }

  // Parse planData from JSON string
  let parsedPlanData: { primary: { entryMin: number; entryMax: number; sl?: number; tps?: number[]; slCondition?: string; orderType?: string }; fallback?: { entryMin: number; entryMax: number; sl?: number; tps?: number[]; slCondition?: string; orderType?: string } } | null = null
  if (signal.planData) {
    try { parsedPlanData = JSON.parse(signal.planData) } catch { /* ignore */ }
  }

  // Derive effective entry price for chart (midpoint of range, or single price)
  const hasEntryRange = signal.entryRangeMin != null && signal.entryRangeMax != null && signal.entryRangeMin !== signal.entryRangeMax;

  const getVerificationColor = () => {
    const map: Record<string, string> = {
      TRADE_SIGNAL: 'text-success bg-success/10 border-success/30',
      INFO_MESSAGE: 'text-primary bg-primary/10 border-primary/30',
      REPLY: 'text-gold bg-gold/10 border-gold/30',
      WRONG_EXECUTION: 'text-destructive bg-destructive/10 border-destructive/30',
      UNCLEAR: 'text-destructive bg-destructive/10 border-destructive/30',
      IMAGE_ONLY: 'text-muted-foreground bg-muted border-border',
    }
    return map[signal.aiVerificationType] || 'text-muted-foreground bg-muted border-border'
  }

  const verificationLabels: Record<string, string> = {
    TRADE_SIGNAL: 'Trade Signal',
    INFO_MESSAGE: 'Info Only',
    REPLY: 'Reply/Update',
    WRONG_EXECUTION: 'Wrong Execution',
    UNCLEAR: 'Unclear',
    IMAGE_ONLY: 'Image Only',
  }

  return (
    <div className="flex min-h-full flex-col pt-[80px] md:pt-0 pb-24 md:pb-0">

      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <header className="sticky top-[80px] md:top-0 z-40 w-full tech-header">
        <div className="max-w-[1400px] mx-auto px-4 md:px-6">

          {/* Mobile: two-row layout */}
          <div className="flex md:hidden flex-col py-1.5 gap-1">
            <div className="flex items-center gap-2 h-9">
              <Link href="/history">
                <div className="flex items-center justify-center w-7 h-7 rounded-full bg-muted hover:bg-primary/10 transition-colors cursor-pointer group">
                  <ArrowLeft className="h-3.5 w-3.5 text-muted-foreground group-hover:text-primary" />
                </div>
              </Link>
              <div className={`flex items-center justify-center w-6 h-6 rounded-md flex-shrink-0 ${isBuy ? 'bg-success/10' : 'bg-destructive/10'}`}>
                {isBuy ? <TrendingUp className="h-3 w-3 text-success" /> : <TrendingDown className="h-3 w-3 text-destructive" />}
              </div>
              <h1 className="text-sm font-bold text-foreground truncate flex-1 min-w-0">{signal.symbol}</h1>
              {signal.hasImage && (
                <button
                  onClick={() => setImageOpen(true)}
                  className="flex items-center gap-1.5 text-xs text-primary hover:text-primary/80 font-medium bg-primary/10 hover:bg-primary/15 border border-primary/30 rounded-md px-2.5 py-1 transition-colors shrink-0"
                >
                  <ImageIcon className="h-3.5 w-3.5" />
                  Image
                </button>
              )}
            </div>
            <div className="flex items-center gap-1.5 pb-1">
              <Badge variant="outline" className="text-[10px] h-5 border-border">{signal.orderType}</Badge>
              <Badge className={`${getStatusColor(signal.status)} text-[10px] h-5`}>{signal.status}</Badge>
              {signal.aiVerified && (
                <Badge className={`${getVerificationColor()} text-[10px] h-5 border`}>
                  <ShieldCheck className="h-2.5 w-2.5 mr-0.5" />
                  {verificationLabels[signal.aiVerificationType] || signal.aiVerificationType}
                </Badge>
              )}
            </div>
          </div>

          {/* Desktop: single-row layout */}
          <div className="hidden md:flex h-12 items-center gap-3">
            <Link href="/history">
              <div className="flex items-center justify-center w-7 h-7 rounded-full bg-muted hover:bg-primary/10 transition-colors cursor-pointer group mr-1">
                <ArrowLeft className="h-3.5 w-3.5 text-muted-foreground group-hover:text-primary" />
              </div>
            </Link>
            <div className={`flex items-center justify-center w-6 h-6 rounded-md flex-shrink-0 ${isBuy ? 'bg-success/10' : 'bg-destructive/10'}`}>
              {isBuy ? <TrendingUp className="h-3 w-3 text-success" /> : <TrendingDown className="h-3 w-3 text-destructive" />}
            </div>
            <h1 className="text-sm font-bold text-foreground truncate">{signal.symbol}</h1>
            <Badge variant="outline" className="text-[10px] h-5 flex-shrink-0 border-border">{signal.orderType}</Badge>
            <Badge className={`${getStatusColor(signal.status)} text-[10px] h-5 flex-shrink-0`}>{signal.status}</Badge>
            {signal.aiVerified && (
              <Badge className={`${getVerificationColor()} text-[10px] h-5 flex-shrink-0 border`}>
                <ShieldCheck className="h-2.5 w-2.5 mr-0.5" />
                {verificationLabels[signal.aiVerificationType] || signal.aiVerificationType}
              </Badge>
            )}
            {signal.hasImage && (
              <button
                onClick={() => setImageOpen(true)}
                className="ml-auto flex items-center gap-1.5 text-xs text-primary hover:text-primary/80 font-medium bg-primary/10 hover:bg-primary/15 border border-primary/30 rounded-md px-2.5 py-1 transition-colors"
              >
                <ImageIcon className="h-3.5 w-3.5" />
                Image
              </button>
            )}
          </div>

        </div>
      </header>

      {/* ── Content ────────────────────────────────────────────────────────── */}
      <div className="flex-1 px-4 md:px-6 py-4 max-w-[1400px] mx-auto w-full">

        {/* Alert banner */}
        {isProblematic && (
          <div className="flex items-center gap-3 p-3 rounded-xl bg-destructive/10 border border-destructive/30 mb-4">
            <AlertTriangle className="h-5 w-5 text-destructive flex-shrink-0" />
            <div>
              <p className="text-sm font-semibold text-destructive">This signal may have issues</p>
              <p className="text-xs text-destructive">AI flagged as {signal.aiVerificationType?.toLowerCase().replace(/_/g, ' ')}</p>
            </div>
          </div>
        )}

        {/* ── Chart ──────────────────────────────────────────────────────── */}
        <div className="mb-4">
          <SignalChart
            symbol={signal.symbol}
            signalTime={Math.floor(new Date(signal.createdAt).getTime() / 1000)}
            signalPrice={hasEntryRange ? (signal.entryRangeMin! + signal.entryRangeMax!) / 2 : (signal.entryPrice ?? undefined)}
            signalType={isBuy ? 'BUY' : 'SELL'}
            entryRangeMin={signal.entryRangeMin ?? undefined}
            entryRangeMax={signal.entryRangeMax ?? undefined}
            stopLoss={signal.stopLoss ?? undefined}
            takeProfitLevels={tpLevels.length > 0 ? tpLevels : undefined}
            planData={parsedPlanData}
          />
        </div>

        {/* ── 2-column main grid ─────────────────────────────────────────── */}
        <div className="grid lg:grid-cols-5 gap-4 mb-4">

          {/* Left col (3/5): Raw message + rejection reason */}
          <div className="lg:col-span-3 flex flex-col gap-3">

            {/* Rejection reason */}
            {signal.rejectionReason && (
              <div className="rounded-xl bg-destructive/10 border border-destructive/30 overflow-hidden">
                <div className="flex items-start gap-3 p-3">
                  <XCircle className="h-4 w-4 text-destructive flex-shrink-0 mt-0.5" />
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-semibold text-destructive mb-0.5">Rejected</p>
                    <p className="text-sm text-destructive break-words">{signal.rejectionReason}</p>
                  </div>
                </div>
                {/* Show the image inline when present so the rejection can be verified visually */}
                {signal.hasImage && signal.rejectionReason?.includes('Vision:') && (
                  <div className="border-t border-destructive/20 bg-black/20 px-3 pb-3 pt-2">
                    <p className="text-[10px] font-semibold text-destructive/80 uppercase tracking-wider mb-2">
                      Image the AI evaluated (check if rejection is correct)
                    </p>
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={`/api/signals/${resolvedParams.id}/image`}
                      alt="Signal image evaluated by AI"
                      className="max-w-full max-h-72 object-contain rounded-lg border border-destructive/20"
                    />
                    <p className="text-[10px] text-destructive/60 mt-1.5">
                      If this image shows a valid new signal, the AI may have incorrectly judged it as already-triggered. You can override by clicking the chart image button above.
                    </p>
                  </div>
                )}
              </div>
            )}

            {/* Raw message */}
            <div className="tech-card rounded-xl overflow-hidden">
              <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border bg-muted/50">
                <MessageSquare className="h-3.5 w-3.5 text-primary" />
                <span className="text-xs font-semibold text-foreground/80">Original Signal Message</span>
                <span className="ml-auto text-[10px] text-muted-foreground/70">{formatDate(signal.createdAt)}</span>
              </div>
              <TelegramText text={signal.rawMessage} className="bg-muted/60 text-foreground/90 p-4 text-sm leading-relaxed max-h-72 overflow-auto border-t border-border" />
            </div>

            {/* Raw AI extraction response — collapsed by default */}
            {signal.aiRawResponse && (
              <details className="tech-card rounded-xl overflow-hidden group">
                <summary className="flex items-center gap-2 px-4 py-2.5 border-b border-border bg-muted/50 cursor-pointer select-none list-none">
                  <Cpu className="h-3.5 w-3.5 text-primary" />
                  <span className="text-xs font-semibold text-foreground/80">AI Response (raw)</span>
                  <ChevronDown className="ml-auto h-3.5 w-3.5 text-muted-foreground/70 transition-transform group-open:rotate-180" />
                </summary>
                <pre className="whitespace-pre-wrap font-mono bg-muted/60 text-foreground/90 p-4 text-xs leading-relaxed max-h-96 overflow-auto border-t border-border">
{signal.aiRawResponse}
                </pre>
              </details>
            )}

            {/* Signal info tags */}
            <div className="flex flex-wrap gap-2">
              {signal.riskPercent && (
                <div className="flex items-center gap-1.5 bg-card border border-border rounded-lg px-2.5 py-1.5 text-xs shadow-sm">
                  <span className="text-muted-foreground/70">Risk:</span>
                  <span className="font-semibold text-foreground/90">{signal.riskPercent.toFixed(2)}%</span>
                  {signal.riskAmount && <span className="text-muted-foreground/70">(${signal.riskAmount.toFixed(2)})</span>}
                </div>
              )}
              {signal.riskRewardRatio && (
                <div className="flex items-center gap-1.5 bg-card border border-border rounded-lg px-2.5 py-1.5 text-xs shadow-sm">
                  <span className="text-muted-foreground/70">R:R</span>
                  <span className="font-semibold text-foreground/90">1:{signal.riskRewardRatio.toFixed(2)}</span>
                </div>
              )}
              <div className="flex items-center gap-1.5 bg-card border border-border rounded-lg px-2.5 py-1.5 text-xs shadow-sm">
                <Zap className="h-3 w-3 text-gold" />
                <span className="text-muted-foreground/70">Confidence:</span>
                <span className="font-semibold text-gold">{(signal.confidence * 100).toFixed(0)}%</span>
              </div>
              <div className="flex items-center gap-1.5 bg-card border border-border rounded-lg px-2.5 py-1.5 text-xs shadow-sm">
                <Hash className="h-3 w-3 text-muted-foreground/70" />
                <span className="text-muted-foreground/70">Msg:</span>
                <span className="font-semibold font-mono text-foreground/90">{signal.messageId}</span>
              </div>
              {signal.forwardedMsgId && (
                <div className="flex items-center gap-1.5 bg-card border border-border rounded-lg px-2.5 py-1.5 text-xs shadow-sm">
                  <Send className="h-3 w-3 text-primary" />
                  <span className="text-muted-foreground/70">Forwarded:</span>
                  <span className="font-semibold font-mono text-primary">{signal.forwardedMsgId}</span>
                </div>
              )}
              <div className="flex items-center gap-1.5 bg-card border border-border rounded-lg px-2.5 py-1.5 text-xs shadow-sm">
                <Radio className="h-3 w-3 text-muted-foreground/70" />
                <span className="font-semibold text-foreground/90">{signal.channelName || signal.channelId}</span>
              </div>
              {(() => {
                const lots = signal.trades?.reduce((s: number, t: {lotSize: number}) => s + (t.lotSize || 0), 0)
                const v = lots || signal.calculatedLotSize || signal.lotSize
                return v ? (
                  <div className="flex items-center gap-1.5 bg-card border border-border rounded-lg px-2.5 py-1.5 text-xs shadow-sm">
                    <span className="text-muted-foreground/70">Lots:</span>
                    <span className="font-semibold text-foreground/90">{v.toFixed(2)}</span>
                  </div>
                ) : null
              })()}
            </div>
          </div>

          {/* Right col (2/5): Key metrics + AI verification */}
          <div className="lg:col-span-2 flex flex-col gap-3">

            {/* Key metrics 2×2 grid */}
            <div className="grid grid-cols-2 gap-3">
              <div className="tech-card rounded-xl p-3">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70 mb-1">Entry {hasEntryRange ? 'Range' : 'Price'}</p>
                {hasEntryRange ? (
                  <div className="space-y-0.5">
                    <p className="text-xs font-bold font-mono text-foreground">{signal.entryRangeMin!.toFixed(5)} – {signal.entryRangeMax!.toFixed(5)}</p>
                    <p className="text-[10px] text-muted-foreground/70">Mid: {((signal.entryRangeMin! + signal.entryRangeMax!) / 2).toFixed(5)}</p>
                  </div>
                ) : (
                  <p className="text-base font-bold font-mono text-foreground">{signal.entryPrice?.toFixed(5) || '—'}</p>
                )}
              </div>
              <div className="tech-card rounded-xl p-3">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70 mb-1">Stop Loss</p>
                <p className="text-base font-bold font-mono text-destructive">
                  {signal.stopLoss?.toFixed(5) || '—'}
                  {signal.stopLossPips && <span className="text-xs font-normal text-muted-foreground/70 ml-1">({signal.stopLossPips.toFixed(1)}p)</span>}
                </p>
              </div>
              <div className="tech-card rounded-xl p-3">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70 mb-1">
                  Take Profit{tpLevels.length > 1 ? 's' : ''}
                </p>
                {tpLevels.length > 0 ? (
                  <div className="space-y-0.5">
                    {tpLevels.map((tp, i) => (
                      <p key={i} className="text-sm font-bold font-mono text-success">
                        <span className="text-[10px] font-normal text-muted-foreground/70 mr-1">TP{i+1}</span>
                        {Number(tp).toFixed(5)}
                      </p>
                    ))}
                  </div>
                ) : (
                  <p className="text-base font-bold text-muted-foreground/50">—</p>
                )}
                {signal.takeProfitPips && <p className="text-[10px] text-muted-foreground/70 mt-0.5">({signal.takeProfitPips.toFixed(1)}p)</p>}
              </div>
              <div className={`rounded-xl border shadow-sm p-3 ${totalPnL > 0 ? 'bg-success/10 border-success/30' : totalPnL < 0 ? 'bg-destructive/10 border-destructive/30' : 'bg-card border-border'}`}>
                <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70 mb-1">Total P/L</p>
                <p className={`text-base font-bold ${totalPnL >= 0 ? 'text-success' : 'text-destructive'}`}>
                  {signal.trades?.length > 0 ? formatCurrency(totalPnL) : '—'}
                </p>
              </div>
            </div>

            {/* Plan Data - Multi-entry trading plan */}
            {parsedPlanData && (
              <div className="tech-card rounded-xl overflow-hidden">
                <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border bg-muted/50">
                  <Zap className="h-3.5 w-3.5 text-purple-500" />
                  <span className="text-xs font-semibold text-foreground/80">Trading Plan</span>
                  <Badge variant="outline" className="text-[10px] h-4 ml-auto border-purple-300 text-purple-600">Plan</Badge>
                </div>
                <div className="px-4 py-3 space-y-3">
                  {/* Primary Entry */}
                  <div className="bg-purple-50 dark:bg-purple-950/20 border border-purple-200 dark:border-purple-800 rounded-lg p-3">
                    <div className="flex items-center gap-2 mb-2">
                      <div className="w-2 h-2 rounded-full bg-purple-500" />
                      <span className="text-xs font-bold text-purple-700 dark:text-purple-300">PRIMARY ENTRY</span>
                      {parsedPlanData.primary.orderType && (
                        <Badge className="text-[10px] h-4 bg-purple-100 dark:bg-purple-900 text-purple-700 dark:text-purple-300">
                          {parsedPlanData.primary.orderType}
                        </Badge>
                      )}
                    </div>
                    <div className="grid grid-cols-2 gap-2 text-xs">
                      <div>
                        <span className="text-muted-foreground/70">Entry: </span>
                        <span className="font-mono font-semibold text-foreground">
                          {parsedPlanData.primary.entryMin === parsedPlanData.primary.entryMax
                            ? parsedPlanData.primary.entryMin.toFixed(5)
                            : `${parsedPlanData.primary.entryMin.toFixed(5)} – ${parsedPlanData.primary.entryMax.toFixed(5)}`}
                        </span>
                      </div>
                      {parsedPlanData.primary.sl && (
                        <div>
                          <span className="text-muted-foreground/70">SL: </span>
                          <span className="font-mono font-semibold text-destructive">{parsedPlanData.primary.sl.toFixed(5)}</span>
                          {parsedPlanData.primary.slCondition && (
                            <span className="text-[10px] text-muted-foreground/50 ml-1">({parsedPlanData.primary.slCondition})</span>
                          )}
                        </div>
                      )}
                    </div>
                    {parsedPlanData.primary.tps && parsedPlanData.primary.tps.length > 0 && (
                      <div className="mt-1.5 pt-1.5 border-t border-purple-200/50 dark:border-purple-800/50">
                        <span className="text-[10px] text-muted-foreground/70">TPs: </span>
                        {parsedPlanData.primary.tps.map((tp, i) => (
                          <span key={i} className="font-mono text-xs text-success ml-1">
                            TP{i+1}: {tp.toFixed(5)}{i < parsedPlanData.primary.tps!.length - 1 ? ',' : ''}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Fallback Entry */}
                  {parsedPlanData.fallback && (
                    <div className="bg-amber-50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-800 rounded-lg p-3">
                      <div className="flex items-center gap-2 mb-2">
                        <div className="w-2 h-2 rounded-full bg-amber-500" />
                        <span className="text-xs font-bold text-amber-700 dark:text-amber-300">FALLBACK ENTRY</span>
                        {parsedPlanData.fallback.orderType && (
                          <Badge className="text-[10px] h-4 bg-amber-100 dark:bg-amber-900 text-amber-700 dark:text-amber-300">
                            {parsedPlanData.fallback.orderType}
                          </Badge>
                        )}
                      </div>
                      <div className="grid grid-cols-2 gap-2 text-xs">
                        <div>
                          <span className="text-muted-foreground/70">Entry: </span>
                          <span className="font-mono font-semibold text-foreground">
                            {parsedPlanData.fallback.entryMin === parsedPlanData.fallback.entryMax
                              ? parsedPlanData.fallback.entryMin.toFixed(5)
                              : `${parsedPlanData.fallback.entryMin.toFixed(5)} – ${parsedPlanData.fallback.entryMax.toFixed(5)}`}
                          </span>
                        </div>
                        {parsedPlanData.fallback.sl && (
                          <div>
                            <span className="text-muted-foreground/70">SL: </span>
                            <span className="font-mono font-semibold text-destructive">{parsedPlanData.fallback.sl.toFixed(5)}</span>
                            {parsedPlanData.fallback.slCondition && (
                              <span className="text-[10px] text-muted-foreground/50 ml-1">({parsedPlanData.fallback.slCondition})</span>
                            )}
                          </div>
                        )}
                      </div>
                      {parsedPlanData.fallback.tps && parsedPlanData.fallback.tps.length > 0 && (
                        <div className="mt-1.5 pt-1.5 border-t border-amber-200/50 dark:border-amber-800/50">
                          <span className="text-[10px] text-muted-foreground/70">TPs: </span>
                          {parsedPlanData.fallback.tps.map((tp, i) => (
                            <span key={i} className="font-mono text-xs text-success ml-1">
                              TP{i+1}: {tp.toFixed(5)}{i < parsedPlanData.fallback!.tps!.length - 1 ? ',' : ''}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* AI Verification */}
            <div className="tech-card rounded-xl overflow-hidden">
              <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border bg-muted/50">
                {signal.aiVerified
                  ? <ShieldCheck className="h-3.5 w-3.5 text-success" />
                  : <ShieldAlert className="h-3.5 w-3.5 text-gold" />}
                <span className="text-xs font-semibold text-foreground/80">AI Verification</span>
              </div>
              <div className="px-4 py-3">
                {signal.aiVerified ? (
                  <div className="space-y-2">
                    <div className="flex items-center gap-2 flex-wrap">
                      <Badge className={`${getVerificationColor()} text-xs flex items-center gap-1 border`}>
                        {signal.aiVerificationType === 'TRADE_SIGNAL'
                          ? <ShieldCheck className="h-3 w-3" />
                          : <ShieldAlert className="h-3 w-3" />}
                        {verificationLabels[signal.aiVerificationType] || signal.aiVerificationType}
                      </Badge>
                      {signal.aiVerificationScore && (
                        <span className="text-xs text-muted-foreground/70">
                          Score: {Math.round(signal.aiVerificationScore * 100)}%
                        </span>
                      )}
                    </div>
                    {signal.aiVerificationNotes && (
                      <p className="text-xs text-muted-foreground bg-muted/50 p-3 rounded-lg leading-relaxed border border-border/50">
                        {signal.aiVerificationNotes}
                      </p>
                    )}
                  </div>
                ) : (
                  <div className="flex flex-col gap-3">
                    <span className="text-sm text-muted-foreground/70">Not yet verified by AI</span>
                    <Button size="sm" variant="outline" onClick={verifySignal} disabled={verifying} className="h-7 text-xs">
                      {verifying
                        ? <><Loader2 className="h-3 w-3 mr-1 animate-spin" />Verifying...</>
                        : <><ShieldCheck className="h-3 w-3 mr-1" />Verify with AI</>}
                    </Button>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* ── Trades section ─────────────────────────────────────────────── */}
        {signal.trades?.length > 0 && (
          <div className="tech-card rounded-xl overflow-hidden mb-4">
            <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border bg-muted/50">
              <Activity className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="text-xs font-semibold text-foreground/80">Trades ({signal.trades.length})</span>
              {totalPnL !== 0 && (
                <span className={`ml-auto text-xs font-bold ${totalPnL >= 0 ? 'text-success' : 'text-destructive'}`}>
                  {totalPnL >= 0 ? '+' : ''}{formatCurrency(totalPnL)} total
                </span>
              )}
            </div>
            <div className="divide-y divide-slate-100">
              {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
              {signal.trades.map((trade: any, idx: number) => (
                <Link key={trade.id} href={`/history/trades/${trade.id}`}>
                  <div className="flex items-center justify-between px-4 py-3 hover:bg-muted/50 transition-colors cursor-pointer">
                    <div className="flex items-center gap-3 flex-wrap min-w-0">
                      <span className="text-xs font-medium text-muted-foreground/70 shrink-0">#{idx + 1}</span>
                      <div className={`flex items-center justify-center w-5 h-5 rounded shrink-0 ${trade.action?.toUpperCase().includes('BUY') ? 'bg-success/10' : 'bg-destructive/10'}`}>
                        {trade.action?.toUpperCase().includes('BUY')
                          ? <TrendingUp className="h-3 w-3 text-success" />
                          : <TrendingDown className="h-3 w-3 text-destructive" />}
                      </div>
                      <span className="font-mono text-xs font-semibold text-foreground">{trade.action}</span>
                      <span className="text-xs text-muted-foreground/70">{trade.lotSize.toFixed(2)} lots</span>
                      {trade.tpLevel && <Badge variant="outline" className="text-[10px] h-4 px-1 border-border">TP{trade.tpLevel}</Badge>}
                      {trade.positionId && <span className="text-[10px] font-mono text-muted-foreground/70">#{trade.positionId}</span>}
                    </div>
                    <div className="flex items-center gap-3 shrink-0 pl-3">
                      <Badge className={`${getStatusColor(trade.status)} text-[10px] h-5`}>{trade.status}</Badge>
                      {trade.tradeActions?.length > 0 && (
                        <div className="flex items-center gap-0.5 text-muted-foreground/70 text-[10px]">
                          <Activity className="h-3 w-3" />{trade.tradeActions.length}
                        </div>
                      )}
                      {trade.profitLoss !== null && (
                        <span className={`text-sm font-bold ${Number(trade.profitLoss) >= 0 ? 'text-success' : 'text-destructive'}`}>
                          {formatCurrency(Number(trade.profitLoss))}
                        </span>
                      )}
                      <span className="text-[10px] text-muted-foreground/70">{formatDate(trade.createdAt)}</span>
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          </div>
        )}

        {/* ── Timeline ───────────────────────────────────────────────────── */}
        <div className="tech-card rounded-xl overflow-hidden">
          <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border bg-muted/50">
            <Clock className="h-3.5 w-3.5 text-gold" />
            <span className="text-xs font-semibold text-foreground/80">Timeline</span>
          </div>
          <div className="px-5 py-4">
            <div className="space-y-0 border-l-2 border-border ml-2">

              {/* Signal received */}
              <div className="relative pl-6 pb-4">
                <div className="absolute -left-[9px] top-0 h-4 w-4 rounded-full bg-primary border-2 border-card flex items-center justify-center">
                  <Radio className="h-2 w-2 text-primary-foreground" />
                </div>
                <div className="text-xs">
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className="font-semibold text-primary">Signal Received</span>
                    <span className="text-muted-foreground/70">{formatDate(signal.createdAt)}</span>
                  </div>
                  <p className="text-muted-foreground">{signal.symbol} {signal.orderType} from {signal.channelName || signal.channelId}</p>
                </div>
              </div>

              {/* Trades */}
              {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
              {signal.trades?.map((trade: any, idx: number) => (
                <div key={`trade-${trade.id}`} className="relative pl-6 pb-4">
                  <div className="absolute -left-[9px] top-0 h-4 w-4 rounded-full bg-success border-2 border-card flex items-center justify-center">
                    <TrendingUp className="h-2 w-2 text-white" />
                  </div>
                  <div className="text-xs">
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className="font-semibold text-success">
                        Trade {idx + 1} {trade.status === 'EXECUTED' ? 'Opened' : trade.status === 'CLOSED' ? 'Completed' : 'Created'}
                      </span>
                      <span className="text-muted-foreground/70">{formatDate(trade.createdAt)}</span>
                    </div>
                    <p className="text-muted-foreground">
                      {trade.action} {trade.lotSize.toFixed(2)} lots
                      {trade.tpLevel && ` (TP${trade.tpLevel})`}
                      {trade.profitLoss !== null && (
                        <span className={`ml-1.5 font-bold ${trade.profitLoss >= 0 ? 'text-success' : 'text-destructive'}`}>
                          {formatCurrency(trade.profitLoss)}
                        </span>
                      )}
                    </p>
                  </div>
                </div>
              ))}

              {/* Replies */}
              {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
              {signal.replies?.map((reply: any) => (
                <div key={reply.id} className="relative pl-6 pb-4">
                  <div className={`absolute -left-[9px] top-0 h-4 w-4 rounded-full border-2 border-card flex items-center justify-center ${
                    reply.actionSuccess ? 'bg-success' : reply.actionTaken ? 'bg-gold' : 'bg-muted-foreground'
                  }`}>
                    <MessageSquare className="h-2 w-2 text-white" />
                  </div>
                  <div className="text-xs">
                    <div className="flex items-center gap-2 mb-1 flex-wrap">
                      <span className={`font-semibold ${reply.actionSuccess ? 'text-success' : reply.actionTaken ? 'text-gold' : 'text-muted-foreground'}`}>
                        {reply.username ? `@${reply.username}` : 'User'} Reply
                      </span>
                      <span className="text-muted-foreground/70">{formatDate(reply.createdAt)}</span>
                      {reply.aiParsed && <Badge variant="secondary" className="text-[10px] h-4">🤖 AI</Badge>}
                      {reply.actionSuccess && <Badge className="text-[10px] h-4 bg-success text-success-foreground">✓ Done</Badge>}
                      {!reply.actionTaken && !reply.processingError && (
                        <Badge variant="secondary" className="text-[10px] h-4">
                          <Info className="h-2.5 w-2.5 mr-0.5" /> No Action
                        </Badge>
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
                        {reply.actionResult && (
                          <p className={reply.actionSuccess ? 'text-success' : 'text-gold'}>{reply.actionResult}</p>
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
                      <div className="mt-1 p-2 rounded-lg bg-destructive/10 border border-destructive/30 text-destructive text-xs">
                        ❌ {reply.processingError}
                      </div>
                    )}
                  </div>
                </div>
              ))}

              {(!signal.replies || signal.replies.length === 0) && (!signal.trades || signal.trades.length === 0) && (
                <div className="relative pl-6 pb-2">
                  <div className="absolute -left-[9px] top-0 h-4 w-4 rounded-full bg-muted border-2 border-card" />
                  <p className="text-xs text-muted-foreground/70 italic">No interactions yet</p>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* ── Channel Timeline ────────────────────────────────────────────── */}
        {signal.channelId && (
          <div className="tech-card rounded-xl overflow-hidden mt-4">
            <button
              onClick={() => setTimelineOpen(!timelineOpen)}
              className="w-full flex items-center gap-2 px-4 py-2.5 border-b border-border bg-muted/50 hover:bg-muted/80 transition-colors"
            >
              <BarChart3 className="h-3.5 w-3.5 text-primary" />
              <span className="text-xs font-semibold text-foreground/80">
                Channel Signal Timeline — {signal.channelName || signal.channelId}
              </span>
              <span className="ml-auto text-[10px] text-muted-foreground/60">
                Click to {timelineOpen ? 'collapse' : 'expand'} — see how all signals from this channel performed
              </span>
              {timelineOpen
                ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground flex-shrink-0" />
                : <ChevronRightIcon className="h-3.5 w-3.5 text-muted-foreground flex-shrink-0" />}
            </button>
            {timelineOpen && (
              <div className="p-3">
                <ChannelTimelineChart
                  channelId={signal.channelId}
                  channelName={signal.channelName || undefined}
                  symbol={signal.symbol}
                  height={380}
                />
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── Image modal ──────────────────────────────────────────────────── */}
      {imageOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm" onClick={() => setImageOpen(false)}>
          <div className="relative max-w-4xl max-h-[90vh] w-full mx-4" onClick={e => e.stopPropagation()}>
            <div className="bg-card rounded-xl shadow-2xl overflow-hidden">
              <div className="flex items-center justify-between px-4 py-3 border-b border-border">
                <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                  <ImageIcon className="h-4 w-4 text-primary" />Signal Image
                </div>
                <button onClick={() => setImageOpen(false)} className="p-1.5 rounded-lg hover:bg-muted transition-colors">
                  <X className="h-4 w-4 text-muted-foreground" />
                </button>
              </div>
              <div className="p-3 bg-muted/50 flex items-center justify-center min-h-48 max-h-[80vh] overflow-auto">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={`/api/signals/${resolvedParams.id}/image`} alt="Signal image" className="max-w-full max-h-[75vh] object-contain rounded-lg" />
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
