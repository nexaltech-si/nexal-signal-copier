'use client'

import { useState, useEffect, useRef, useCallback, useMemo, type ReactNode } from 'react'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import MobilePageHeader from '@/components/MobilePageHeader'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue, SelectGroup, SelectLabel } from '@/components/ui/select'
import {
  FlaskConical,
  Play,
  Square,
  RefreshCw,
  Trash2,
  ChevronDown,
  ChevronUp,
  Download,
  Brain,
  TrendingUp,
  Activity,
  MessageSquare,
  Zap,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Clock,
  BarChart3,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import SimulatorTimelineChart, { SimTrade } from '@/components/SimulatorTimelineChart'
import TelegramText from '@/components/TelegramText'

// ── Types ────────────────────────────────────────────────────────────────────

interface Channel {
  /** Telegram ids are numbers; Discord ids are text (too large for a JavaScript number). */
  id: number | string
  name: string
  source?: 'telegram' | 'discord'
  /** Discord only: short name for the list, and the header (server · category) it is listed under. */
  label?: string
  group?: string
  enabled?: boolean
}

interface SimStatus {
  status: 'idle' | 'running' | 'cancelled' | 'complete' | 'error'
  has_client: boolean
  progress: {
    channel_name?: string
    current?: number
    total?: number
    started_at?: string
  }
  error?: string | null
  last_results?: SimSummary
}

interface SimSummary {
  channel_name: string
  total_messages: number
  reply_messages: number
  plain_command_count: number
  intent_signal_count: number
  intent_command_count: number
  intent_status_count: number
  intent_non_trading_count: number
  ai_extracted_count: number
  pattern_extracted_count: number
  image_extracted_count: number
  fused_extracted_count: number
  failed_extraction_count: number
  prefiltered_count: number
  commands_processed: number
  plan_signals: number
  open_signals: number
  close_signals: number
  modify_signals: number
  partial_close_signals: number
  context_resolved_count: number
  brain_reviewed_count: number
  brain_approved: number
  brain_rejected: number
  brain_modified: number
  ai_accuracy: number
  pattern_accuracy: number
  total_extracted: number
  symbol_distribution: Record<string, number>
  common_errors: Record<string, number>
}

interface LiveTrade {
  message_id: number
  timestamp: string
  intent?: string
  intent_source?: string
  extraction_method?: string
  symbol?: string
  action?: string
  command_action?: string
  has_image: boolean
  is_reply: boolean
  reply_to_message_id?: number
  brain_verdict?: string
  extraction_error?: string
  original_message: string
  ai_order_type?: string
  ai_entry?: number | null
  ai_sl?: number | null
  ai_tp?: number[] | null
  command_value?: number | null
  command_percentage?: number | null
  // Reply replay through the live ReplyHandlerService (simulated broker)
  reply_state?: string | null
  reply_ai_action?: string | null
  reply_broker_calls?: string[]
  reply_result?: string | null
  reply_state_after?: string | null
}

type LogFilter = 'all' | 'signals' | 'replies' | 'acted' | 'skipped'

interface WsEvent {
  type: string
  current?: number
  total?: number
  trade?: LiveTrade
  summary?: SimSummary
  error?: string
  status?: string
  has_client?: boolean
  progress?: Record<string, unknown>
}

interface SavedResult {
  filename: string
  size_bytes: number
  modified_at: string
}

// SSE endpoint — same-origin, proxied through Next.js
const SSE_URL = '/api/simulator/events'

const STATUS_COLORS: Record<string, string> = {
  idle: 'bg-muted text-muted-foreground',
  running: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
  complete: 'bg-green-500/15 text-green-400 border-green-500/30',
  cancelled: 'bg-yellow-500/15 text-yellow-500 border-yellow-500/30',
  error: 'bg-red-500/15 text-red-400 border-red-500/30',
}

const METHOD_COLORS: Record<string, string> = {
  ai: 'bg-purple-500/20 text-purple-300',
  image_vision: 'bg-cyan-500/20 text-cyan-300',
  fused: 'bg-teal-500/20 text-teal-300',
  pattern: 'bg-orange-500/20 text-orange-300',
  command: 'bg-blue-500/20 text-blue-300',
  prefiltered: 'bg-muted text-muted-foreground',
  failed: 'bg-red-500/20 text-red-400',
  split_post_attached: 'bg-teal-500/15 text-teal-300',
  album_part: 'bg-muted text-muted-foreground',
  split_post_ignored: 'bg-muted text-muted-foreground',
  skipped_status: 'bg-muted text-muted-foreground',
  skipped_not_trading: 'bg-muted text-muted-foreground',
}

const METHOD_LABELS: Record<string, string> = {
  image_vision: 'vision',
  split_post_attached: 'chart linked',
  split_post_ignored: 'chart skip',
  album_part: 'album part',
  skipped_status: 'status',
  skipped_not_trading: 'not trading',
}

const INTENT_COLORS: Record<string, string> = {
  SIGNAL: 'text-green-400',
  COMMAND: 'text-blue-400',
  STATUS: 'text-yellow-400',
  NOT_TRADING: 'text-muted-foreground',
  SPLIT_POST: 'text-teal-400',
  ALBUM_PART: 'text-muted-foreground',
}

// Simulated broker call → colour (first word of "close 34567-0", "BE 34581-0 → 4165.25", …)
const BROKER_COLORS: Record<string, string> = {
  close: 'text-red-400 bg-red-500/10 border-red-500/20',
  partial: 'text-orange-300 bg-orange-500/10 border-orange-500/20',
  BE: 'text-emerald-300 bg-emerald-500/10 border-emerald-500/20',
  SL: 'text-yellow-300 bg-yellow-500/10 border-yellow-500/20',
  TP: 'text-sky-300 bg-sky-500/10 border-sky-500/20',
  cancel: 'text-zinc-300 bg-zinc-500/10 border-zinc-500/20',
  OPEN: 'text-green-300 bg-green-500/10 border-green-500/20',
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtDate(iso: string) {
  return new Date(iso).toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

function pct(n: number, total: number) {
  if (!total) return '0.0'
  return ((n / total) * 100).toFixed(1)
}

function brokerKind(call: string) {
  return call.split(' ')[0]
}

function isManaged(t: LiveTrade) {
  // a reply, or a standalone command/status applied to the latest active signal
  return t.intent_source === 'reply_ai' || t.intent_source === 'standalone_ai'
}

function matchesFilter(t: LiveTrade, f: LogFilter) {
  switch (f) {
    case 'signals': return !t.is_reply && t.intent === 'SIGNAL' && !!t.symbol
    case 'replies': return t.is_reply || isManaged(t)
    case 'acted': return (t.reply_broker_calls?.length ?? 0) > 0
    case 'skipped': return !t.symbol && !t.reply_ai_action && !(t.reply_broker_calls?.length)
    default: return true
  }
}

function replyStats(trades: LiveTrade[]) {
  const replies = trades.filter(t => isManaged(t))
  const calls = replies.flatMap(t => t.reply_broker_calls ?? [])
  const count = (k: string) => calls.filter(c => brokerKind(c) === k).length
  return {
    replies: replies.length,
    acted: replies.filter(t => !!t.reply_ai_action).length,
    noAction: replies.filter(t => !t.reply_ai_action).length,
    closes: count('close'),
    partials: count('partial'),
    stops: count('BE') + count('SL'),
    cancels: count('cancel'),
    chartsLinked: trades.filter(t => t.extraction_method === 'split_post_attached').length,
  }
}

// ── StatCard ─────────────────────────────────────────────────────────────────

function StatCard({ label, value, sub, color }: {
  label: string
  value: string | number
  sub?: string
  color?: string
}) {
  return (
    <div className="bg-card border border-border rounded-lg p-3">
      <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className={cn('text-xl font-black mt-1', color || 'text-foreground')}>{value}</p>
      {sub && <p className="text-[10px] text-muted-foreground mt-0.5">{sub}</p>}
    </div>
  )
}

// ── TradeRow ─────────────────────────────────────────────────────────────────

function DetailBlock({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div className={cn('rounded-md border border-border/60 bg-background/40 p-2 min-w-0', className)}>
      <p className="text-[9px] font-black uppercase tracking-wider text-muted-foreground mb-1">{label}</p>
      <div className="text-[11px] text-foreground/90 break-words">{children}</div>
    </div>
  )
}

function TradeRow({ trade, idx }: { trade: LiveTrade; idx: number }) {
  const [expanded, setExpanded] = useState(false)
  const method = trade.extraction_method || 'unknown'
  const symbol = trade.symbol || '—'
  const isPlainCmd = trade.intent_source === 'plain_command'
  const isReplay = isManaged(trade)
  const isStandalone = trade.intent_source === 'standalone_ai'
  const calls = trade.reply_broker_calls ?? []
  const action = isReplay
    ? (trade.reply_ai_action || 'no action')
    : (trade.action || trade.command_action || '—')
  const isSignal = !trade.is_reply && trade.intent === 'SIGNAL' && !!trade.symbol

  return (
    <div className={cn(
      'border-b border-border/50 last:border-0',
      trade.is_reply ? 'bg-blue-500/[0.03]' : '',
      calls.length > 0 ? 'bg-amber-500/[0.04]' : '',
      trade.extraction_error && !trade.is_reply && !isSignal ? 'opacity-60' : '',
    )}>
      <div
        className="flex items-center gap-2 py-1.5 px-3 hover:bg-muted/30 cursor-pointer text-xs"
        onClick={() => setExpanded(v => !v)}
      >
        <span className="text-muted-foreground w-8 text-right shrink-0 font-mono">{idx}</span>

        {/* intent with reply indicator */}
        <span className={cn('w-[76px] shrink-0 text-[10px] font-bold flex items-center gap-0.5', INTENT_COLORS[trade.intent || ''] || 'text-muted-foreground')}>
          {trade.is_reply && (
            <span className="text-blue-400 font-black" title={`Reply to #${trade.reply_to_message_id}`}>↩</span>
          )}
          {isStandalone ? 'CMD' : trade.is_reply ? 'REPLY' : trade.intent === 'SPLIT_POST' ? 'CHART' : trade.intent === 'ALBUM_PART' ? 'ALBUM' : trade.intent || '?'}
        </span>

        {/* method / plain-command / reply-AI badge */}
        <span className={cn(
          'rounded px-1.5 py-0.5 text-[9px] font-bold uppercase w-[84px] shrink-0 text-center truncate',
          isReplay
            ? 'bg-indigo-500/20 text-indigo-300'
            : isPlainCmd ? 'bg-emerald-500/20 text-emerald-300' : (METHOD_COLORS[method] || 'bg-muted text-muted-foreground'),
        )}>
          {isReplay ? 'reply AI' : `${isPlainCmd ? '⚡ ' : ''}${METHOD_LABELS[method] || method}`}
        </span>

        <span className="font-bold text-foreground w-[60px] shrink-0 truncate">{symbol}</span>
        <span className={cn(
          'w-[96px] shrink-0 truncate',
          isReplay && trade.reply_ai_action ? 'text-indigo-300 font-bold' : 'text-muted-foreground',
          isSignal && trade.ai_order_type === 'BUY' ? 'text-green-400 font-bold' : '',
          isSignal && trade.ai_order_type === 'SELL' ? 'text-red-400 font-bold' : '',
        )}>
          {isSignal && trade.ai_order_type ? trade.ai_order_type : action}
        </span>

        {calls.length > 0 && (
          <span className="text-[9px] font-black uppercase px-1.5 py-0.5 rounded border shrink-0 text-amber-300 bg-amber-500/10 border-amber-500/20"
                title={calls.join('\n')}>
            {calls.length} broker {calls.length === 1 ? 'call' : 'calls'}
          </span>
        )}
        {trade.brain_verdict && (
          <span className={cn('text-[9px] font-black uppercase px-1 rounded', {
            'text-green-400 bg-green-500/10': trade.brain_verdict === 'APPROVE',
            'text-red-400 bg-red-500/10': trade.brain_verdict === 'REJECT',
            'text-yellow-400 bg-yellow-500/10': trade.brain_verdict === 'MODIFY',
          })}>
            {trade.brain_verdict}
          </span>
        )}
        {trade.has_image && <span className="text-[9px] text-cyan-400 shrink-0">IMG</span>}

        <TelegramText text={trade.original_message} inline className="flex-1 min-w-0 truncate text-muted-foreground text-[10px]" />
        <span className="text-muted-foreground/50 text-[9px] shrink-0">
          {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
        </span>
      </div>

      {expanded && (
        <div className="px-3 pb-3 pt-2 bg-muted/20 border-t border-border/30 space-y-2">
          <div className="text-[10px] text-muted-foreground">
            {trade.timestamp && <span className="text-foreground/60 font-mono">[{fmtDate(trade.timestamp)}] </span>}
            <span className="font-mono">#{trade.message_id}</span>
            {trade.is_reply && trade.reply_to_message_id && (
              <span className="text-blue-400"> ↩ reply to #{trade.reply_to_message_id}</span>
            )}
            {isStandalone && trade.reply_to_message_id && (
              <span className="text-indigo-300"> · standalone message — applied to latest active signal #{trade.reply_to_message_id}</span>
            )}
          </div>
          <div className="text-[11px] text-foreground/80 whitespace-pre-wrap">
            <TelegramText text={trade.original_message} className="inline font-sans" />
          </div>

          {isSignal && (
            <div className="grid grid-cols-3 gap-2">
              <DetailBlock label="Entry">{trade.ai_entry ?? 'market'}</DetailBlock>
              <DetailBlock label="Stop loss">{trade.ai_sl ?? '—'}</DetailBlock>
              <DetailBlock label="Take profit">{trade.ai_tp?.length ? trade.ai_tp.join(' / ') : '—'}</DetailBlock>
            </div>
          )}

          {isReplay && (
            <div className="grid grid-cols-1 md:grid-cols-4 gap-2">
              <DetailBlock label="Account before">{trade.reply_state || '—'}</DetailBlock>
              <DetailBlock label="AI decision">
                <span className={trade.reply_ai_action ? 'text-indigo-300 font-bold' : 'text-muted-foreground'}>
                  {trade.reply_ai_action || 'no action'}
                </span>
                {trade.command_percentage ? <span className="text-muted-foreground"> · {trade.command_percentage}%</span> : null}
                {trade.command_value ? <span className="text-muted-foreground"> · {trade.command_value}</span> : null}
              </DetailBlock>
              <DetailBlock label="Broker (simulated — not sent)">
                {calls.length === 0 ? (
                  <span className="text-muted-foreground">nothing sent</span>
                ) : (
                  <div className="flex flex-wrap gap-1">
                    {calls.map((c, i) => (
                      <span key={i} className={cn('px-1.5 py-0.5 rounded border text-[10px] font-mono',
                        BROKER_COLORS[brokerKind(c)] || 'text-muted-foreground border-border')}>
                        {c}
                      </span>
                    ))}
                  </div>
                )}
              </DetailBlock>
              <DetailBlock label="Account after">{trade.reply_state_after || trade.reply_state || '—'}</DetailBlock>
            </div>
          )}

          {trade.reply_result && (
            <div className="text-[10px] text-muted-foreground">Handler: {trade.reply_result}</div>
          )}
          {trade.extraction_error && (
            <div className="text-[10px] text-red-400">{isSignal ? 'Note' : 'Reason'}: {trade.extraction_error}</div>
          )}
          {isPlainCmd && trade.command_action && (
            <div className="text-[10px] text-emerald-400">⚡ Plain command (zero AI): {trade.command_action}</div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Main Page ────────────────────────────────────────────────────────────────

export default function SimulatorPage() {
  // Config
  const [channels, setChannels] = useState<Channel[]>([])
  const [selectedChannelId, setSelectedChannelId] = useState<string>('')
  const [selectedChannelName, setSelectedChannelName] = useState<string>('')
  const [startDate, setStartDate] = useState(() => {
    const d = new Date(); d.setDate(d.getDate() - 30)
    return d.toISOString().slice(0, 10)
  })
  const [endDate, setEndDate] = useState(() => new Date().toISOString().slice(0, 10))
  const [limit, setLimit] = useState('1000')
  const [enableBrain, setEnableBrain] = useState(false)

  // Runtime state
  const [simStatus, setSimStatus] = useState<SimStatus | null>(null)
  const [liveLog, setLiveLog] = useState<LiveTrade[]>([])
  const [liveSummary, setLiveSummary] = useState<SimSummary | null>(null)
  const [wsConnected, setWsConnected] = useState(false)
  const [isStarting, setIsStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Full accumulated trade list for timeline chart (no 500-entry cap)
  const [allSimTrades, setAllSimTrades] = useState<SimTrade[]>([])
  // Trades loaded from a saved result file
  const [loadedResultTrades, setLoadedResultTrades] = useState<SimTrade[] | null>(null)
  const [loadedResultName, setLoadedResultName] = useState<string | null>(null)
  const [timelineOpen, setTimelineOpen] = useState(true)
  const [logFilter, setLogFilter] = useState<LogFilter>('all')
  // A saved result opened in the log (replaces the live stream until cleared)
  const [loadedLog, setLoadedLog] = useState<LiveTrade[] | null>(null)

  // Saved results
  const [savedResults, setSavedResults] = useState<SavedResult[]>([])
  const [showResults, setShowResults] = useState(false)

  const esRef = useRef<EventSource | null>(null)
  const logEndRef = useRef<HTMLDivElement | null>(null)

  // Auto-scroll log
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [liveLog])

  // Load channels — Telegram dialogs cache plus the Discord channels the bot can read
  useEffect(() => {
    fetch('/api/simulator/channels')
      .then(r => r.json())
      .then(d => {
        const list: Channel[] = (d.channels || []).map((ch: any) => ({
          id: ch.id,
          name: ch.source === 'discord' ? `Discord · ${ch.name}` : ch.name,
          source: ch.source === 'discord' ? 'discord' : 'telegram',
          label: ch.label,
          group: ch.group,
        }))
        setChannels(list)
      })
      .catch(() => {})
  }, [])

  // Load initial status
  useEffect(() => {
    fetch('/api/simulator/status')
      .then(r => r.json())
      .then(d => setSimStatus(d))
      .catch(() => {})
  }, [])

  // SSE connection — same-origin, no direct backend exposure
  useEffect(() => {
    function connect() {
      if (esRef.current) esRef.current.close()

      const es = new EventSource(SSE_URL)
      esRef.current = es

      es.onopen = () => setWsConnected(true)
      es.onerror = () => {
        setWsConnected(false)
        es.close()
        setTimeout(connect, 3000)
      }
      es.onmessage = (ev) => {
        try {
          const event: WsEvent = JSON.parse(ev.data)
          handleWsEvent(event)
        } catch {}
      }
    }
    connect()
    return () => esRef.current?.close()
  }, [])

  const handleWsEvent = useCallback((event: WsEvent) => {
    switch (event.type) {
      case 'status_snapshot':
        setSimStatus(event as unknown as SimStatus)
        if ((event as any).last_results) setLiveSummary((event as any).last_results)
        break
      case 'simulation_started':
        setLiveLog([])
        setLoadedLog(null)
        setAllSimTrades([])
        setLoadedResultTrades(null)
        setLoadedResultName(null)
        setLiveSummary(null)
        setError(null)
        break
      case 'message_processed':
        if (event.trade) {
          setLiveLog(prev => [...prev.slice(-499), event.trade!])
          // accumulate ALL trades for the timeline (no cap)
          setAllSimTrades((prev: SimTrade[]) => [...prev, event.trade as unknown as SimTrade])
        }
        setSimStatus(prev => prev ? {
          ...prev,
          status: 'running',
          progress: {
            ...prev.progress,
            current: event.current,
            total: event.total,
          }
        } : prev)
        break
      case 'simulation_complete':
        setSimStatus(prev => prev ? { ...prev, status: 'complete' } : prev)
        if (event.summary) setLiveSummary(event.summary)
        loadSavedResults()
        break
      case 'simulation_cancelled':
        setSimStatus(prev => prev ? { ...prev, status: 'cancelled' } : prev)
        break
      case 'simulation_error':
        setSimStatus(prev => prev ? { ...prev, status: 'error', error: event.error } : prev)
        setError(event.error || 'Unknown error')
        break
      case 'ping':
        break
    }
  }, [])

  const loadSavedResults = useCallback(() => {
    fetch('/api/simulator/results')
      .then(r => r.json())
      .then(d => setSavedResults(d.results || []))
      .catch(() => {})
  }, [])

  useEffect(() => { loadSavedResults() }, [loadSavedResults])

  const handleRun = async () => {
    if (!selectedChannelId) { setError('Select a channel first.'); return }
    setIsStarting(true)
    setError(null)
    try {
      const res = await fetch('/api/simulator/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          // Discord ids stay text: Number() would round them
          ...(channels.find(c => String(c.id) === selectedChannelId)?.source === 'discord'
            ? { channel_id: selectedChannelId, source: 'discord' }
            : { channel_id: Number(selectedChannelId) }),
          channel_name: selectedChannelName,
          start_date: new Date(startDate).toISOString(),
          end_date: new Date(endDate + 'T23:59:59').toISOString(),
          limit: Number(limit),
          enable_brain: enableBrain,
        }),
      })
      const data = await res.json()
      if (!res.ok) setError(data.detail || data.error || 'Failed to start')
    } catch (err) {
      setError(String(err))
    } finally {
      setIsStarting(false)
    }
  }

  const handleStop = async () => {
    await fetch('/api/simulator/stop', { method: 'POST' })
  }

  const handleDeleteResult = async (filename: string) => {
    await fetch(`/api/simulator/results/${filename}`, { method: 'DELETE' })
    loadSavedResults()
  }

  const handleLoadResultForTimeline = async (filename: string) => {
    try {
      const res = await fetch(`/api/simulator/results/${filename}`)
      if (!res.ok) return
      const resp = await res.json()
      // API wraps result in { ok, data: {...} }; fall back to root for direct JSON
      const data = resp.data ?? resp
      const trades: SimTrade[] = (data.trades || []).map((t: any) => ({
        ...t,
        ai_symbol: t.ai_symbol || t.pattern_symbol,
        ai_action: t.ai_action || t.pattern_action,
        ai_order_type: t.ai_order_type || t.pattern_order_type,
        ai_entry: t.ai_entry ?? t.pattern_entry,
        ai_sl: t.ai_sl ?? t.pattern_sl,
        ai_tp: t.ai_tp ?? t.pattern_tp,
      }))
      setLoadedResultTrades(trades)
      setLoadedResultName(filename)
      setLoadedLog((data.trades || []).map((t: any) => ({
        ...t,
        symbol: t.ai_symbol || t.pattern_symbol,
        action: t.ai_action || t.pattern_action,
        ai_order_type: t.ai_order_type || t.pattern_order_type,
        ai_entry: t.ai_entry ?? t.pattern_entry,
        ai_sl: t.ai_sl ?? t.pattern_sl,
        ai_tp: t.ai_tp ?? t.pattern_tp,
      })))
      setLogFilter('all')
      setAllSimTrades([])
      setTimelineOpen(true)
    } catch { /* ignore */ }
  }

  const isRunning = simStatus?.status === 'running'
  const progress = simStatus?.progress
  const progressPct = progress?.total ? Math.round((progress.current || 0) / progress.total * 100) : 0
  const summary = liveSummary || simStatus?.last_results
  const logSource = loadedLog ?? liveLog
  const visibleLog = useMemo(() => logSource.filter(t => matchesFilter(t, logFilter)), [logSource, logFilter])
  const rstats = useMemo(() => replyStats(loadedLog ?? (allSimTrades as unknown as LiveTrade[])), [loadedLog, allSimTrades])

  const statusLabel = simStatus?.status || 'idle'

  return (
    <div className="flex flex-col min-h-full">
      <MobilePageHeader
        title="Simulator"
        subtitle="Signal Pipeline"
        hidden
        icon={<FlaskConical className="h-5 w-5" />}
      />

      {/* Desktop header */}
      <header className="hidden md:flex sticky top-0 z-40 w-full tech-header">
        <div className="max-w-[1800px] w-full mx-auto flex h-14 items-center px-6 gap-3">
          <div className="p-1.5 rounded-lg bg-primary/10 border border-primary/20">
            <FlaskConical className="h-5 w-5 text-primary" />
          </div>
          <div className="flex flex-col">
            <h1 className="text-sm font-bold text-foreground leading-none">Signal Simulator</h1>
            <p className="text-[10px] text-[#6b7288] font-bold uppercase tracking-wider mt-1">
              Replays real channel history through the live bot code — signals, replies &amp; charts
            </p>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <div className="text-[10px] font-bold px-2 py-1 rounded border text-amber-300 bg-amber-500/10 border-amber-500/20"
                 title="Replies run through the real reply handler and AI against a simulated broker built from MT5 candles. No order is sent.">
              Dry run · nothing sent to MT5
            </div>
            <div className={cn(
              'flex items-center gap-1.5 px-2 py-1 rounded-full text-[10px] font-bold uppercase border',
              STATUS_COLORS[statusLabel],
            )}>
              <span className={cn('w-1.5 h-1.5 rounded-full', {
                'bg-blue-400 animate-pulse': isRunning,
                'bg-green-400': statusLabel === 'complete',
                'bg-yellow-400': statusLabel === 'cancelled',
                'bg-red-400': statusLabel === 'error',
                'bg-muted-foreground': statusLabel === 'idle',
              })} />
              {statusLabel}
            </div>
            <div className={cn(
              'text-[10px] font-bold px-2 py-1 rounded border',
              wsConnected
                ? 'text-green-400 bg-green-500/10 border-green-500/20'
                : 'text-red-400 bg-red-500/10 border-red-500/20',
            )}>
              WS {wsConnected ? 'live' : 'off'}
            </div>
            {simStatus && !simStatus.has_client && (
              <div className="text-[10px] text-yellow-500 bg-yellow-500/10 border border-yellow-500/20 px-2 py-1 rounded">
                No shared client — will use .env credentials
              </div>
            )}
          </div>
        </div>
      </header>

      <div className="flex-1 px-3 md:px-6 py-4 space-y-4 max-w-[1800px] mx-auto w-full">

        {/* ── Control Panel ───────────────────────────────────────────────── */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

          {/* Config card */}
          <Card className="lg:col-span-2 p-4 border-border bg-card">
            <h2 className="text-xs font-black uppercase tracking-wider text-foreground mb-3 flex items-center gap-2">
              <Activity className="w-3.5 h-3.5 text-primary" />
              Configuration
            </h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {/* Channel */}
              <div className="sm:col-span-2">
                <label className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-1 block">
                  Channel
                </label>
                <Select
                  value={selectedChannelId}
                  onValueChange={(v) => {
                    setSelectedChannelId(v)
                    const ch = channels.find(c => String(c.id) === v)
                    setSelectedChannelName(ch?.name || '')
                  }}
                >
                  <SelectTrigger className="h-9 text-xs">
                    <SelectValue placeholder="Select a Telegram or Discord channel…" />
                  </SelectTrigger>
                  <SelectContent>
                    {(() => {
                      // Telegram channels first, then the selected Discord channels under their server · category
                      const groups: string[] = []
                      channels.forEach(c => { if (c.group && !groups.includes(c.group)) groups.push(c.group) })
                      return (
                        <>
                          {channels.filter(c => !c.group).map(c => (
                            <SelectItem key={String(c.id)} value={String(c.id)} className="text-xs">{c.name}</SelectItem>
                          ))}
                          {groups.map(group => (
                            <SelectGroup key={group}>
                              <SelectLabel className="pt-2 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">{group}</SelectLabel>
                              {channels.filter(c => c.group === group).map(c => (
                                <SelectItem key={String(c.id)} value={String(c.id)} className="text-xs">{c.label ?? c.name}</SelectItem>
                              ))}
                            </SelectGroup>
                          ))}
                        </>
                      )
                    })()}
                  </SelectContent>
                </Select>
              </div>

              {/* Start date */}
              <div>
                <label className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-1 block">
                  Start Date
                </label>
                <Input
                  type="date"
                  value={startDate}
                  onChange={e => setStartDate(e.target.value)}
                  className="h-9 text-xs"
                />
              </div>

              {/* End date */}
              <div>
                <label className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-1 block">
                  End Date
                </label>
                <Input
                  type="date"
                  value={endDate}
                  onChange={e => setEndDate(e.target.value)}
                  className="h-9 text-xs"
                />
              </div>

              {/* Limit */}
              <div>
                <label className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-1 block">
                  Message Limit
                </label>
                <Select value={limit} onValueChange={setLimit}>
                  <SelectTrigger className="h-9 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {['100', '250', '500', '1000', '2000', '5000'].map(v => (
                      <SelectItem key={v} value={v} className="text-xs">{Number(v).toLocaleString()} messages</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* Brain toggle */}
              <div className="flex flex-col justify-end">
                <label className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-1 block">
                  TradingBrain Review
                </label>
                <button
                  onClick={() => setEnableBrain(v => !v)}
                  className={cn(
                    'h-9 px-3 rounded-md border text-xs font-bold flex items-center gap-2 transition-colors',
                    enableBrain
                      ? 'bg-purple-500/15 border-purple-500/30 text-purple-300'
                      : 'bg-muted border-border text-muted-foreground',
                  )}
                >
                  <Brain className="w-3.5 h-3.5" />
                  {enableBrain ? 'Enabled (costs API calls)' : 'Disabled'}
                </button>
              </div>
            </div>

            {/* Actions */}
            <div className="flex gap-2 mt-4">
              <Button
                size="sm"
                onClick={handleRun}
                disabled={isRunning || isStarting || !selectedChannelId}
                className="h-8 text-xs font-bold uppercase"
              >
                {isStarting ? (
                  <RefreshCw className="w-3.5 h-3.5 mr-1.5 animate-spin" />
                ) : (
                  <Play className="w-3.5 h-3.5 mr-1.5" />
                )}
                {isStarting ? 'Starting…' : 'Run Simulation'}
              </Button>
              {isRunning && (
                <Button
                  size="sm"
                  variant="destructive"
                  onClick={handleStop}
                  className="h-8 text-xs font-bold uppercase"
                >
                  <Square className="w-3.5 h-3.5 mr-1.5" />
                  Stop
                </Button>
              )}
            </div>

            {error && (
              <div className="mt-3 p-2 rounded bg-red-500/10 border border-red-500/20 text-xs text-red-400 flex items-start gap-2">
                <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                {error}
              </div>
            )}
          </Card>

          {/* Progress card */}
          <Card className="p-4 border-border bg-card">
            <h2 className="text-xs font-black uppercase tracking-wider text-foreground mb-3 flex items-center gap-2">
              <Zap className="w-3.5 h-3.5 text-primary" />
              Progress
            </h2>

            {isRunning && progress ? (
              <div className="space-y-3">
                <div className="flex justify-between text-[10px] text-muted-foreground font-bold">
                  <span>{progress.channel_name}</span>
                  <span>{progress.current?.toLocaleString()} / {progress.total?.toLocaleString()}</span>
                </div>
                <div className="h-2 bg-muted rounded-full overflow-hidden">
                  <div
                    className="h-full bg-primary transition-all duration-200 rounded-full"
                    style={{ width: `${progressPct}%` }}
                  />
                </div>
                <p className="text-center text-lg font-black text-foreground">{progressPct}%</p>
                {progress.started_at && (
                  <p className="text-[10px] text-muted-foreground text-center">
                    Started {fmtDate(progress.started_at)}
                  </p>
                )}
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center h-24 text-muted-foreground">
                {statusLabel === 'complete' ? (
                  <>
                    <CheckCircle2 className="w-8 h-8 text-green-400 mb-1" />
                    <p className="text-xs font-bold text-green-400">Complete</p>
                  </>
                ) : statusLabel === 'error' ? (
                  <>
                    <XCircle className="w-8 h-8 text-red-400 mb-1" />
                    <p className="text-xs font-bold text-red-400">Error</p>
                  </>
                ) : statusLabel === 'cancelled' ? (
                  <>
                    <Square className="w-8 h-8 text-yellow-400 mb-1" />
                    <p className="text-xs font-bold text-yellow-400">Cancelled</p>
                  </>
                ) : (
                  <>
                    <Clock className="w-8 h-8 mb-1" />
                    <p className="text-xs font-bold">Idle</p>
                  </>
                )}
              </div>
            )}
          </Card>
        </div>

        {/* ── Stats Summary ────────────────────────────────────────────────── */}
        {summary && (
          <div className="space-y-3">
            <h2 className="text-xs font-black uppercase tracking-wider text-muted-foreground flex items-center gap-2">
              <TrendingUp className="w-3.5 h-3.5" />
              Results — {summary.channel_name}
            </h2>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 xl:grid-cols-8 gap-2">
              <StatCard label="Messages" value={summary.total_messages.toLocaleString()} sub={`${summary.reply_messages ?? 0} replies`} />
              <StatCard label="Signals" value={summary.intent_signal_count} sub={`${pct(summary.intent_signal_count, summary.total_messages)}%`} color="text-green-400" />
              <StatCard label="Commands" value={summary.intent_command_count} sub={`${summary.plain_command_count ?? 0} zero-AI`} color="text-blue-400" />
              <StatCard label="Extracted" value={summary.total_extracted} sub={`AI ${summary.ai_accuracy}% / Pat ${summary.pattern_accuracy}%`} color="text-primary" />
              <StatCard label="AI" value={summary.ai_extracted_count} sub={`${summary.ai_accuracy}%`} color="text-purple-400" />
              <StatCard label="Pattern" value={summary.pattern_extracted_count} sub={`${summary.pattern_accuracy}%`} color="text-orange-400" />
              <StatCard label="Vision" value={summary.image_extracted_count} color="text-cyan-400" />
              <StatCard label="Failed" value={summary.failed_extraction_count} sub={`${pct(summary.failed_extraction_count, summary.total_messages)}%`} color="text-red-400" />
              <StatCard label="OPEN" value={summary.open_signals} color="text-green-400" />
              <StatCard label="CLOSE" value={summary.close_signals} color="text-red-400" />
              <StatCard label="MODIFY" value={summary.modify_signals} color="text-yellow-400" />
              <StatCard label="Plans" value={summary.plan_signals} color="text-teal-400" />
              <StatCard label="Context Res." value={summary.context_resolved_count} />
              {summary.brain_reviewed_count > 0 && (
                <>
                  <StatCard label="Brain Reviewed" value={summary.brain_reviewed_count} color="text-purple-400" />
                  <StatCard label="Brain Approved" value={summary.brain_approved} color="text-green-400" />
                  <StatCard label="Brain Rejected" value={summary.brain_rejected} color="text-red-400" />
                </>
              )}
            </div>

            {rstats.replies > 0 && (
              <div>
                <p className="text-[10px] font-black uppercase tracking-wider text-muted-foreground mb-2 flex items-center gap-1.5">
                  <MessageSquare className="w-3 h-3" /> Replies — live reply AI vs simulated account
                </p>
                <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-2">
                  <StatCard label="Replies" value={rstats.replies} />
                  <StatCard label="AI acted" value={rstats.acted} sub={`${pct(rstats.acted, rstats.replies)}%`} color="text-indigo-300" />
                  <StatCard label="No action" value={rstats.noAction} sub="status · chatter" />
                  <StatCard label="Closes" value={rstats.closes} color="text-red-400" />
                  <StatCard label="Partials" value={rstats.partials} color="text-orange-300" />
                  <StatCard label="BE / SL moves" value={rstats.stops} color="text-emerald-300" />
                  <StatCard label="Cancels" value={rstats.cancels} sub="stale pending" color="text-zinc-300" />
                  <StatCard label="Charts linked" value={rstats.chartsLinked} sub="text + image posts" color="text-teal-300" />
                </div>
              </div>
            )}

            {/* Symbol distribution */}
            {Object.keys(summary.symbol_distribution).length > 0 && (
              <Card className="p-3 border-border bg-card">
                <p className="text-[10px] font-black uppercase tracking-wider text-muted-foreground mb-2">Symbol Distribution</p>
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(summary.symbol_distribution)
                    .sort((a, b) => b[1] - a[1])
                    .map(([sym, cnt]) => (
                      <div key={sym} className="flex items-center gap-1 bg-muted rounded px-2 py-1 text-[10px]">
                        <span className="font-bold text-foreground">{sym}</span>
                        <span className="text-muted-foreground">{cnt}</span>
                      </div>
                    ))}
                </div>
              </Card>
            )}

            {/* Common errors */}
            {Object.keys(summary.common_errors).length > 0 && (
              <Card className="p-3 border-border bg-card">
                <p className="text-[10px] font-black uppercase tracking-wider text-muted-foreground mb-2 flex items-center gap-1">
                  <AlertTriangle className="w-3 h-3 text-yellow-400" /> Common Errors
                </p>
                <div className="space-y-1">
                  {Object.entries(summary.common_errors)
                    .sort((a, b) => b[1] - a[1])
                    .slice(0, 5)
                    .map(([err, cnt]) => (
                      <div key={err} className="flex items-start gap-2 text-[10px]">
                        <span className="font-black text-red-400 w-6 shrink-0">{cnt}×</span>
                        <span className="text-muted-foreground">{err}</span>
                      </div>
                    ))}
                </div>
              </Card>
            )}
          </div>
        )}

        {/* ── Message Log ───────────────────────────────────────────────────── */}
        <Card className="border-border bg-card overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 border-b border-border">
            <h2 className="text-xs font-black uppercase tracking-wider text-foreground flex items-center gap-2">
              <MessageSquare className="w-3.5 h-3.5 text-primary" />
              {loadedLog ? 'Saved Run' : 'Live Log'}
              <span className="text-muted-foreground font-normal normal-case">
                ({visibleLog.length}{logFilter !== 'all' ? ` of ${logSource.length}` : ''} messages{loadedLog && loadedResultName ? ` · ${loadedResultName}` : ''})
              </span>
            </h2>
            <div className="flex flex-wrap items-center gap-1">
              {([
                ['all', 'All'],
                ['signals', 'Signals'],
                ['replies', 'Replies'],
                ['acted', 'Broker calls'],
                ['skipped', 'Skipped'],
              ] as [LogFilter, string][]).map(([key, label]) => (
                <button
                  key={key}
                  onClick={() => setLogFilter(key)}
                  className={cn(
                    'h-6 px-2 rounded-md text-[10px] font-bold border transition-colors',
                    logFilter === key
                      ? 'bg-primary/15 border-primary/30 text-primary'
                      : 'bg-muted/40 border-border text-muted-foreground hover:text-foreground',
                  )}
                >
                  {label}
                </button>
              ))}
              {(loadedLog || liveLog.length > 0) && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 text-[10px] text-muted-foreground"
                  onClick={() => (loadedLog ? setLoadedLog(null) : setLiveLog([]))}
                >
                  {loadedLog ? 'Back to live' : 'Clear'}
                </Button>
              )}
            </div>
          </div>

          {/* Header row */}
          <div className="flex items-center gap-2 px-3 py-1.5 bg-muted/30 text-[9px] font-black uppercase tracking-wider text-muted-foreground border-b border-border">
            <span className="w-8 text-right">#</span>
            <span className="w-[76px]">Type</span>
            <span className="w-[84px]">Handled by</span>
            <span className="w-[60px]">Symbol</span>
            <span className="w-[96px]">Decision</span>
            <span className="flex-1">Message</span>
          </div>

          <div className="max-h-[560px] overflow-y-auto font-mono">
            {visibleLog.length === 0 ? (
              <div className="flex items-center justify-center h-24 text-muted-foreground text-xs">
                {isRunning ? (
                  <span className="flex items-center gap-2">
                    <RefreshCw className="w-3.5 h-3.5 animate-spin" /> Waiting for messages…
                  </span>
                ) : logSource.length > 0 ? 'Nothing matches this filter' : 'Start a simulation, or open a saved run below'}
              </div>
            ) : (
              <>
                {visibleLog.map((t, i) => (
                  <TradeRow key={`${t.message_id}-${i}`} trade={t} idx={i + 1} />
                ))}
                {!loadedLog && <div ref={logEndRef} />}
              </>
            )}
          </div>
        </Card>

        {/* ── Signal Timeline Chart ────────────────────────────────────────── */}
        {(allSimTrades.length > 0 || loadedResultTrades) && (
          <Card className="border-border bg-card overflow-hidden">
            <div
              className="flex items-center justify-between px-3 py-2 border-b border-border cursor-pointer"
              onClick={() => setTimelineOpen((v: boolean) => !v)}
            >
              <h2 className="text-xs font-black uppercase tracking-wider text-foreground flex items-center gap-2">
                <BarChart3 className="w-3.5 h-3.5 text-primary" />
                Signal Timeline
                <span className="text-muted-foreground font-normal">
                  {loadedResultName
                    ? `— ${loadedResultName}`
                    : `(${allSimTrades.filter((t: SimTrade) => t.intent === 'SIGNAL').length} signals from live run)`
                  }
                </span>
              </h2>
              {timelineOpen
                ? <ChevronUp className="w-4 h-4 text-muted-foreground" />
                : <ChevronDown className="w-4 h-4 text-muted-foreground" />
              }
            </div>
            {timelineOpen && (
              <div className="p-3">
                <SimulatorTimelineChart
                  trades={loadedResultTrades ?? allSimTrades}
                  height={420}
                />
              </div>
            )}
          </Card>
        )}

        {/* ── Saved Results ────────────────────────────────────────────────── */}
        <Card className="border-border bg-card">
          <div
            className="flex items-center justify-between px-4 py-3 cursor-pointer"
            onClick={() => { setShowResults(v => !v); if (!showResults) loadSavedResults() }}
          >
            <h2 className="text-xs font-black uppercase tracking-wider text-foreground flex items-center gap-2">
              <Download className="w-3.5 h-3.5 text-primary" />
              Saved Results
              <span className="text-muted-foreground font-normal">({savedResults.length})</span>
            </h2>
            {showResults ? <ChevronUp className="w-4 h-4 text-muted-foreground" /> : <ChevronDown className="w-4 h-4 text-muted-foreground" />}
          </div>

          {showResults && (
            <div className="border-t border-border">
              {savedResults.length === 0 ? (
                <p className="text-xs text-muted-foreground text-center py-6">No saved results yet</p>
              ) : (
                <div className="divide-y divide-border">
                  {savedResults.map(r => (
                    <div key={r.filename} className="flex items-center justify-between px-4 py-2.5 hover:bg-muted/20">
                      <div>
                        <p className="text-xs font-bold text-foreground">{r.filename}</p>
                        <p className="text-[10px] text-muted-foreground">
                          {fmtDate(r.modified_at)} · {(r.size_bytes / 1024).toFixed(1)} KB
                        </p>
                      </div>
                      <div className="flex gap-2">
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 text-[10px] text-primary"
                          onClick={() => handleLoadResultForTimeline(r.filename)}
                          title="Open this run in the message log and the timeline chart"
                        >
                          <BarChart3 className="w-3 h-3 mr-1" />
                          Open
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 text-[10px]"
                          onClick={() => window.open(`/api/simulator/results/${r.filename}`, '_blank')}
                        >
                          <Download className="w-3 h-3 mr-1" />
                          JSON
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 text-[10px] text-red-400 hover:text-red-300"
                          onClick={() => handleDeleteResult(r.filename)}
                        >
                          <Trash2 className="w-3 h-3" />
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </Card>

      </div>
    </div>
  )
}
