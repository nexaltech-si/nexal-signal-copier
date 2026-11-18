'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue, SelectGroup, SelectLabel } from '@/components/ui/select'
import { ChevronLeft, ChevronRight, Download, Play, Square, Workflow } from 'lucide-react'
import { cn } from '@/lib/utils'
import FlowReplayChart, { type ChartBar } from '@/components/FlowReplayChart'
import TelegramText from '@/components/TelegramText'
import TgWallpaper, { WALLPAPER_PRESETS } from '@/components/TgWallpaper'
import { DateSeparator, ReplyPreview, TgAvatar, timeStr } from '@/components/TelegramBrowser'

// Flow Replay: a channel's real messages replayed through the bot's real logic
// against a simulated broker. Left: the chat. Right: what the bot understood
// and did for the selected message, and what the market did until the next one.

// Telegram ids are numbers; Discord ids are text (too large for a JavaScript number)
interface Channel { id: number | string; name: string; source?: 'telegram' | 'discord'; label?: string; group?: string }
interface Parsed {
  symbol: string | null; side: string | null; entry: number | null; entries: number[] | null
  zone: [number, number] | null; sl: number | null; tps: number[]; instant: boolean; plan: boolean
}
interface SetupRow {
  ticket: number; state: 'open' | 'pending'; symbol: string; side: string; lots: number
  entry: number; sl: number | null; tp: number | null; pnl: number | null; signal: number
}
interface MarketEvent { time: string; text: string; by: 'broker' | 'bot' | 'note' }
interface Execution {
  time: string; ticket: number; signal: number; symbol: string; side: string | null
  kind: 'entry' | 'exit'; how: string; lots: number; price: number; pnl: number | null
}
interface FlowChart { type: 'chart'; symbol: string; minutes_per_bar: number; bars: ChartBar[] }
interface FlowClock { type: 'clock'; symbol: string; offset_hours: number; source: string; follows_new_york_close: boolean }
interface Counts { messages: number; signals: number; acted: number; ignored: number; review: number }
interface FlowMessage {
  type: 'message'; index: number; total: number; id: number; date: string; text: string
  reply_to: number | null; edited: boolean; media: boolean; intent: string | null
  event?: 'post' | 'edit' | 'delete'; target?: number | null
  parsed: Parsed[]; not_parsed: string | null
  relation: { to_message: number; why: string } | null
  command: { target_message: number | null; success: boolean; ignored: boolean; result: string } | null
  ai_action: { action: string | null; value: number | null; percentage: number | null } | null
  outcome: string; detail: string | null; actions: string[]; notes: string[]; review: string[]
  prices: Record<string, { bid: number; ask: number }>; setup: SetupRow[]; realized: number; counts: Counts
  executions?: Execution[]
}
interface FlowMarket {
  type: 'market'; after_message: number | null; events: MarketEvent[]; setup: SetupRow[]; realized: number
  executions?: Execution[]
}
interface FlowSummary {
  type: 'summary'; counts: Counts; realized: number; floating: number; open: SetupRow[]
  signals: { message: number; symbol: string; side: string; status: string; trades: number; pnl: number }[]
  settings: Record<string, string | number | boolean>
  executions?: Execution[]
}
type FlowEvent = FlowMessage | FlowMarket | FlowSummary | FlowChart | FlowClock
  | { type: 'started'; messages: number; channel: string; runner: boolean; risk_percent: number; ai: string }
  | { type: 'fetched'; messages: number } | { type: 'error'; error: string }

const OUTCOME_STYLE: Record<string, string> = {
  ENTERED: 'bg-emerald-500/15 text-emerald-400',
  MERGED: 'bg-emerald-500/15 text-emerald-400',
  UPDATED: 'bg-sky-500/15 text-sky-400',
  CLOSED: 'bg-sky-500/15 text-sky-400',
  CANCELLED: 'bg-amber-500/15 text-amber-400',
  PLAN: 'bg-violet-500/15 text-violet-400',
  REJECTED: 'bg-rose-500/15 text-rose-400',
  'NEEDS APPROVAL': 'bg-amber-500/15 text-amber-400',
  'NO ACTION': 'bg-muted text-muted-foreground',
  SKIPPED: 'bg-muted text-muted-foreground',
}
const OUTCOME_DOT: Record<string, string> = {
  ENTERED: 'bg-emerald-400', MERGED: 'bg-emerald-400', UPDATED: 'bg-sky-400', CLOSED: 'bg-sky-400',
  CANCELLED: 'bg-amber-400', PLAN: 'bg-violet-400', REJECTED: 'bg-rose-400',
}
const INTENT_STYLE: Record<string, string> = {
  SIGNAL: 'bg-primary/15 text-primary',
  COMMAND: 'bg-amber-500/15 text-amber-400',
  REPLY: 'bg-amber-500/15 text-amber-400',
  STATUS: 'bg-muted text-muted-foreground',
  NOT_TRADING: 'bg-muted text-muted-foreground',
}

const money = (v: number | null | undefined) =>
  v == null ? '—' : `${v >= 0 ? '+' : '−'}$${Math.abs(v).toFixed(2)}`
const price = (v: number | null | undefined) => (v == null ? '—' : String(v))
const clock = (iso: string) =>
  new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
const clockSec = (iso: string) =>
  new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
const utcOffsetLabel = (hours: number) => `UTC${hours >= 0 ? '+' : '−'}${Math.abs(hours)}`
const localInput = (d: Date) =>
  new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16)

function Tag({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <span className={cn('inline-flex items-center rounded-md px-1.5 py-0.5 text-[10px] font-bold tracking-wide', className)}>
      {children}
    </span>
  )
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-border bg-card p-4">
      <h4 className="mb-2.5 text-[11px] font-bold tracking-[0.13em] text-muted-foreground">{title}</h4>
      {children}
    </section>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[130px_1fr] gap-2 py-0.5 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <div className="min-w-0">{children}</div>
    </div>
  )
}

function SetupTable({ rows }: { rows: SetupRow[] }) {
  if (!rows.length) return <p className="text-sm text-muted-foreground">Nothing open.</p>
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-border text-left text-[10px] tracking-wider text-muted-foreground">
            <th className="px-1.5 py-1.5 font-semibold">ORDER</th>
            <th className="px-1.5 py-1.5 font-semibold">LOTS</th>
            <th className="px-1.5 py-1.5 font-semibold">ENTRY</th>
            <th className="px-1.5 py-1.5 font-semibold">SL</th>
            <th className="px-1.5 py-1.5 font-semibold">TP</th>
            <th className="px-1.5 py-1.5 font-semibold">STATE</th>
            <th className="px-1.5 py-1.5 font-semibold">P/L</th>
          </tr>
        </thead>
        <tbody className="font-mono">
          {rows.map(r => (
            <tr key={r.ticket} className="border-b border-border/50">
              <td className="px-1.5 py-1.5">
                {r.symbol} {r.side}
                {r.tp == null && <span className="ml-1.5 font-sans text-[10px] font-bold text-amber-400">RUNNER</span>}
                <span className="ml-1.5 font-sans text-[10px] text-muted-foreground">signal #{r.signal}</span>
              </td>
              <td className="px-1.5 py-1.5">{r.lots.toFixed(2)}</td>
              <td className="px-1.5 py-1.5">{price(r.entry)}</td>
              <td className="px-1.5 py-1.5">{price(r.sl)}</td>
              <td className={cn('px-1.5 py-1.5', r.tp == null && 'text-amber-400')}>{r.tp == null ? 'none' : r.tp}</td>
              <td className={cn('px-1.5 py-1.5', r.state === 'open' ? 'text-emerald-400' : 'text-amber-400')}>{r.state}</td>
              <td className={cn('px-1.5 py-1.5', r.pnl == null ? 'text-muted-foreground' : r.pnl >= 0 ? 'text-emerald-400' : 'text-rose-400')}>
                {money(r.pnl)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function FlowReplayPage() {
  const [channels, setChannels] = useState<Channel[]>([])
  const [channelId, setChannelId] = useState('')
  const [manualId, setManualId] = useState('')
  const [start, setStart] = useState(() => { const d = new Date(); d.setHours(d.getHours() - 12); return localInput(d) })
  const [end, setEnd] = useState(() => localInput(new Date()))
  const [limit, setLimit] = useState('300')
  const [runner, setRunner] = useState('live')
  const [status, setStatus] = useState('idle')
  const [error, setError] = useState<string | null>(null)
  const [events, setEvents] = useState<FlowEvent[]>([])
  const [selected, setSelected] = useState<number | null>(null)
  const [follow, setFollow] = useState(true)
  const seen = useRef(0)
  const chatRef = useRef<HTMLDivElement>(null)
  // the Telegram page's chat look, always on its dark wallpaper
  const wallpaper = WALLPAPER_PRESETS.find(p => p.id === 'night') ?? WALLPAPER_PRESETS[0]

  useEffect(() => {
    fetch('/api/simulator/channels').then(r => r.json())
      .then(d => setChannels((d.channels || []).map((c: Channel) => ({
        id: c.id,
        name: c.source === 'discord' ? `Discord · ${c.name}` : c.name,
        source: c.source === 'discord' ? 'discord' : 'telegram',
        label: c.label,
        group: c.group,
      }))))
      .catch(() => {})
  }, [])

  const poll = useCallback(async () => {
    try {
      const res = await fetch(`/api/simulator/flow/state?since=${seen.current}`, { cache: 'no-store' })
      if (!res.ok) return
      const data = await res.json()
      if (data.total < seen.current) { seen.current = 0; setEvents([]); return }   // a new run started elsewhere
      if (data.events?.length) {
        seen.current = data.total
        setEvents(prev => [...prev, ...data.events])
      }
      setStatus(data.status)
      setError(data.error || null)
    } catch { /* the next poll tries again */ }
  }, [])

  useEffect(() => { poll() }, [poll])
  useEffect(() => {
    if (status !== 'running' && status !== 'fetching') return
    const timer = setInterval(poll, 1000)
    return () => clearInterval(timer)
  }, [status, poll])

  const messages = useMemo(() => events.filter((e): e is FlowMessage => e.type === 'message'), [events])
  const marketAfter = useMemo(() => {
    const map = new Map<number, FlowMarket[]>()
    for (const e of events) {
      if (e.type === 'market' && e.after_message != null) {
        map.set(e.after_message, [...(map.get(e.after_message) || []), e])
      }
    }
    return map
  }, [events])
  const summary = useMemo(() => events.find((e): e is FlowSummary => e.type === 'summary') || null, [events])
  const started = useMemo(() => events.find(e => e.type === 'started') as Extract<FlowEvent, { type: 'started' }> | undefined, [events])
  const byId = useMemo(() => new Map(messages.map(m => [m.id, m])), [messages])
  const executions = useMemo(() => events.flatMap(e =>
    (e.type === 'message' || e.type === 'market' || e.type === 'summary') ? (e.executions || []) : []), [events])
  const charts = useMemo(() => new Map(events.filter((e): e is FlowChart => e.type === 'chart').map(c => [c.symbol, c])), [events])
  const clocks = useMemo(() => new Map(events.filter((e): e is FlowClock => e.type === 'clock').map(c => [c.symbol, c])), [events])
  const last = messages[messages.length - 1]
  const current = (selected != null ? byId.get(selected) : undefined) || last
  // the setup the selected message belongs to: its own signal, the signal it follows up, or the one it manages
  const setupId = current
    ? current.relation?.to_message ?? current.command?.target_message
      ?? (current.event && current.event !== 'post' ? current.target ?? null : null)
      ?? (current.parsed.length || executions.some(e => e.signal === current.id) ? current.id : null)
    : null
  const setupExecutions = useMemo(
    () => (setupId == null ? [] : executions.filter(e => e.signal === setupId)), [executions, setupId])
  const setupView = useMemo(() => {
    if (setupId == null || !setupExecutions.length) return null
    const symbol = setupExecutions[0].symbol
    const related = messages.filter(m =>
      m.id === setupId || m.relation?.to_message === setupId || m.command?.target_message === setupId)
    // levels: the last time the setup had orders, plus the levels the channel gave
    let sl: number | null = null        // the stop the channel gave
    let slNow: number | null = null     // where the stop stood last (break-even, trailed, moved)
    const tps = new Set<number>()
    for (const m of related) {
      for (const p of m.parsed) { if (p.sl != null) sl = p.sl; p.tps.forEach(t => tps.add(t)) }
      for (const r of m.setup) if (r.signal === setupId && r.sl != null) slNow = r.sl
    }
    if (sl == null) { sl = slNow; slNow = null }
    const pip = setupExecutions[0].price > 500 ? 1 : 0.001
    if (slNow != null && sl != null && Math.abs(slNow - sl) < pip) slNow = null    // only the spread allowance apart
    const entries = Array.from(new Set(setupExecutions.filter(e => e.kind === 'entry').map(e => e.price)))
    const times = [...setupExecutions.map(e => e.time), ...related.map(m => m.date)].map(t => new Date(t).getTime())
    const pad = 20 * 60000
    const side = setupExecutions[0].side === 'BUY'
    return {
      symbol,
      from: new Date(Math.min(...times) - pad).toISOString(),
      to: new Date(Math.max(...times) + pad).toISOString(),
      levels: { sl, slNow, tps: Array.from(tps).sort((a, b) => (side ? a - b : b - a)), entries },
      marks: related.filter(m => m.outcome !== 'NO ACTION' && m.outcome !== 'SKIPPED').map(m => ({
        time: m.date,
        label: `#${m.id}${m.id === setupId ? '' : ` ${m.outcome.toLowerCase()}`}`,
      })),
      pnl: setupExecutions.reduce((sum, e) => sum + (e.pnl || 0), 0),
    }
  }, [setupId, setupExecutions, messages])
  const localOffset = -new Date().getTimezoneOffset() / 60
  const counts = summary?.counts || last?.counts
  const realized = summary?.realized ?? last?.realized ?? 0
  const running = status === 'running' || status === 'fetching'
  const channelTitle = started?.channel || channels.find(c => String(c.id) === channelId)?.name || ''

  useEffect(() => {
    if (follow && last) {
      setSelected(last.id)
      chatRef.current?.scrollTo({ top: chatRef.current.scrollHeight, behavior: 'smooth' })
    }
  }, [last, follow])

  const run = async () => {
    const id = channelId === 'manual' ? manualId.trim() : channelId
    if (!id) { setError('Choose a channel first.'); return }
    const chosen = channels.find(c => String(c.id) === id)
    const name = chosen?.name || id
    // A Discord id stays text (Number() would round it). A typed-in id of 17+ digits is a Discord one.
    const discord = chosen ? chosen.source === 'discord' : /^\d{17,}$/.test(id)
    seen.current = 0
    setEvents([]); setSelected(null); setFollow(true); setError(null)
    const res = await fetch('/api/simulator/flow/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...(discord ? { channel_id: id, source: 'discord' } : { channel_id: Number(id) }), channel_name: name,
        start_date: new Date(start).toISOString(), end_date: new Date(end).toISOString(),
        limit: Number(limit) || 300,
        runner: runner === 'live' ? null : runner === 'on',
      }),
    })
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      setError(data.detail || data.error || 'The replay could not be started.')
      return
    }
    setStatus('fetching')
  }

  const stop = async () => { await fetch('/api/simulator/flow/stop', { method: 'POST' }); poll() }

  const step = (delta: number) => {
    if (!current) return
    const next = messages[messages.findIndex(m => m.id === current.id) + delta]
    if (next) { setFollow(false); setSelected(next.id) }
  }

  const exportReport = async () => {
    const name = `flow-replay-${new Date().toISOString().slice(0, 16).replace(/[:T]/g, '-')}.json`
    const blob = new Blob([JSON.stringify(events, null, 2)], { type: 'application/json' })

    // An app installed to the Home Screen cannot download a blob: iOS opens it in
    // a browser sheet that fails with "WebKitBlobResource error 1". Hand the file
    // to the share sheet there instead (Save to Files, AirDrop, …).
    const installed = window.matchMedia('(display-mode: standalone)').matches
      || (navigator as Navigator & { standalone?: boolean }).standalone === true
    if (installed && typeof navigator.share === 'function') {
      const file = new File([blob], name, { type: 'application/json' })
      if (navigator.canShare?.({ files: [file] })) {
        try {
          await navigator.share({ files: [file], title: name })
          return
        } catch (e) {
          if ((e as Error)?.name === 'AbortError') return   // closed the share sheet
        }
      }
    }

    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = name
    document.body.appendChild(a)
    a.click()
    a.remove()
    // Not at once: Safari reads the blob after the click returns.
    setTimeout(() => URL.revokeObjectURL(url), 60_000)
  }

  const stats: [string, string, string?][] = [
    ['MESSAGES', counts ? `${counts.messages}${last ? ` / ${last.total}` : ''}` : '—'],
    ['SIGNALS', counts ? String(counts.signals) : '—'],
    ['COMMANDS ACTED ON', counts ? String(counts.acted) : '—'],
    ['IGNORED (CHATTER)', counts ? String(counts.ignored) : '—'],
    ['SIMULATED P/L', counts ? money(realized + (summary?.floating || 0)) : '—',
      realized + (summary?.floating || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'],
    ['NEEDS REVIEW', counts ? String(counts.review) : '—', counts?.review ? 'text-amber-400' : undefined],
  ]

  return (
    // Below lg the page scrolls as a whole, clear of the app's fixed top bar and
    // bottom navigation; from lg up it is one fixed screen with two scrolling panes.
    <div className="flex flex-col pt-[76px] pb-24 md:pt-0 md:pb-0 lg:h-[calc(100vh-1rem)]">
      {/* Controls */}
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <div className="mr-auto flex w-full items-center gap-3 lg:w-auto">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/15 text-primary">
            <Workflow className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-lg font-bold leading-tight">Flow Replay</h1>
            <p className="text-[11px] tracking-[0.12em] text-muted-foreground">
              REAL CHANNEL MESSAGES · REAL BOT LOGIC · SIMULATED BROKER
            </p>
          </div>
        </div>
        <Select value={channelId} onValueChange={setChannelId}>
          <SelectTrigger className="h-9 w-full sm:w-56"><SelectValue placeholder="Channel" /></SelectTrigger>
          <SelectContent>
            {(() => {
                      // Telegram channels first, then the selected Discord channels under their server · category
                      const groups: string[] = []
                      channels.forEach(c => { if (c.group && !groups.includes(c.group)) groups.push(c.group) })
                      return (
                        <>
                          {channels.filter(c => !c.group).map(c => (
                            <SelectItem key={String(c.id)} value={String(c.id)}>{c.name}</SelectItem>
                          ))}
                          {groups.map(group => (
                            <SelectGroup key={group}>
                              <SelectLabel className="pt-2 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">{group}</SelectLabel>
                              {channels.filter(c => c.group === group).map(c => (
                                <SelectItem key={String(c.id)} value={String(c.id)}>{c.label ?? c.name}</SelectItem>
                              ))}
                            </SelectGroup>
                          ))}
                        </>
                      )
                    })()}
            <SelectItem value="manual">Enter a channel id…</SelectItem>
          </SelectContent>
        </Select>
        {channelId === 'manual' && (
          <Input className="h-9 w-full sm:w-44" placeholder="-100… or Discord channel id" value={manualId} onChange={e => setManualId(e.target.value)} />
        )}
        <Input className="h-9 min-w-0 flex-1 sm:w-48 sm:flex-none" type="datetime-local" value={start} onChange={e => setStart(e.target.value)} aria-label="From" />
        <Input className="h-9 min-w-0 flex-1 sm:w-48 sm:flex-none" type="datetime-local" value={end} onChange={e => setEnd(e.target.value)} aria-label="To" />
        <Input className="h-9 w-20" type="number" min={1} max={2000} value={limit} onChange={e => setLimit(e.target.value)} aria-label="Maximum messages" />
        <Select value={runner} onValueChange={setRunner}>
          <SelectTrigger className="h-9 min-w-0 flex-1 sm:w-40 sm:flex-none"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="live">Runner: as live</SelectItem>
            <SelectItem value="on">Runner: on</SelectItem>
            <SelectItem value="off">Runner: off</SelectItem>
          </SelectContent>
        </Select>
        {running
          ? <Button variant="destructive" className="h-9" onClick={stop}><Square className="mr-1.5 h-4 w-4" />Stop</Button>
          : <Button className="h-9" onClick={run}><Play className="mr-1.5 h-4 w-4" />Replay</Button>}
      </div>

      {/* Totals */}
      <div className="grid grid-cols-2 gap-2 border-b border-border px-4 py-3 md:grid-cols-6">
        {stats.map(([label, value, tone]) => (
          <div key={label} className="rounded-xl border border-border bg-card px-3 py-2">
            <div className="text-[10px] tracking-[0.12em] text-muted-foreground">{label}</div>
            <div className={cn('font-mono text-xl font-bold', tone)}>{value}</div>
          </div>
        ))}
      </div>

      {error && <div className="border-b border-rose-500/30 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">{error}</div>}

      {/* Chat | result */}
      <div className="grid grid-cols-1 lg:min-h-0 lg:flex-1 lg:grid-cols-[44%_56%]">
        {/* The chat, drawn like the Telegram page */}
        <div className="flex h-[65vh] flex-col border-b border-border lg:h-auto lg:min-h-0 lg:border-b-0 lg:border-r">
          {(started || messages.length > 0) && (
            <div className="flex shrink-0 items-center gap-2.5 border-b border-border/30 bg-card/70 px-4 py-2.5 backdrop-blur-sm">
              <TgAvatar name={channelTitle || '?'} size={36} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold leading-tight">{channelTitle}</p>
                <p className="text-xs leading-tight text-muted-foreground">
                  {last ? `${last.index} of ${last.total} messages replayed` : 'replay'}
                </p>
              </div>
            </div>
          )}
          <div className="relative min-h-0 flex-1 overflow-hidden">
            <TgWallpaper preset={wallpaper} className="pointer-events-none absolute inset-0 -z-0" />
            <div ref={chatRef} className="relative z-[1] h-full overflow-y-auto px-2 py-2 md:px-4">
              {!messages.length && (
                <p className="mt-10 text-center text-sm text-muted-foreground">
                  {status === 'fetching' ? 'Reading the channel…'
                    : running ? 'Starting the replay…'
                    : 'Choose a channel and a period, then press Replay. Nothing is sent to your account.'}
                </p>
              )}
              {messages.map((m, i) => {
                const newDay = i === 0 || new Date(messages[i - 1].date).toDateString() !== new Date(m.date).toDateString()
                const quoted = m.reply_to != null ? byId.get(m.reply_to) : undefined
                const active = current?.id === m.id
                return (
                  <div key={m.id}>
                    {newDay && <DateSeparator iso={m.date} />}
                    <div className="group mb-2 flex items-start gap-2" data-msg-id={m.id}>
                      <div
                        role="button"
                        tabIndex={0}
                        onClick={() => { setFollow(false); setSelected(m.id) }}
                        onKeyDown={e => { if (e.key === 'Enter') { setFollow(false); setSelected(m.id) } }}
                        className={cn(
                          'tg-bubble tg-bubble-accent relative w-fit min-w-[150px] max-w-full cursor-pointer overflow-hidden',
                          'rounded-2xl rounded-tl-md transition-shadow sm:max-w-[82%]',
                          active && 'ring-2 ring-primary ring-offset-2 ring-offset-background/60',
                        )}
                      >
                        {m.reply_to != null && (
                          <div className="pl-3.5 pr-3 pt-2.5">
                            <ReplyPreview
                              reply={{ id: m.reply_to, text: quoted?.text ?? null, sender_name: channelTitle || null,
                                has_media: !!quoted?.media, media_type: quoted?.media ? 'photo' : null }}
                              onJump={id => { if (byId.has(id)) { setFollow(false); setSelected(id) } }}
                            />
                          </div>
                        )}
                        <div className="px-3.5 pb-2 pt-2.5">
                          {m.event === 'delete' && (
                            <p className="text-xs font-semibold text-rose-400">🗑 Channel deleted message #{m.target}</p>
                          )}
                          {m.event === 'edit' && (
                            <p className="mb-1 text-xs font-semibold text-amber-400">✏️ Channel edited message #{m.target} to:</p>
                          )}
                          {m.event === 'delete' ? null : m.text
                            ? <TelegramText text={m.text} className="tg-message text-sm leading-relaxed" />
                            : <p className="text-xs italic text-muted-foreground">{m.media ? '📷 Photo' : 'Empty message'}</p>}
                          <div className="mt-1 flex flex-wrap items-center justify-end gap-2">
                            {m.intent && <Tag className={INTENT_STYLE[m.intent] || 'bg-muted text-muted-foreground'}>{m.intent.replace('_', ' ')}</Tag>}
                            {m.relation && <Tag className="bg-primary/15 text-primary">FOLLOW-UP</Tag>}
                            {m.edited && <span className="text-[11px] text-muted-foreground/70">edited</span>}
                            <span className="text-[11px] leading-none text-muted-foreground/70">#{m.id}</span>
                            <span className="text-[11px] tabular-nums leading-none text-muted-foreground/70">{timeStr(m.date)}</span>
                          </div>
                        </div>
                      </div>
                      <div className="flex shrink-0 flex-col items-start gap-1 pt-2">
                        <span className="rounded-md bg-background/90 shadow-sm backdrop-blur-sm">
                          <Tag className={OUTCOME_STYLE[m.outcome] || 'bg-muted text-muted-foreground'}>{m.outcome}</Tag>
                        </span>
                        {m.review.length > 0 && (
                          <span className="rounded-md bg-background/90 shadow-sm backdrop-blur-sm">
                            <Tag className="bg-amber-500/15 text-amber-400">REVIEW</Tag>
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>

        <div className="space-y-3 px-4 py-4 lg:min-h-0 lg:overflow-y-auto">
          {!current && summary == null && (
            <p className="mt-10 text-center text-sm text-muted-foreground">
              The result for each message appears here: what the bot understood, what it sent to the broker,
              and what the market did until the next message.
            </p>
          )}
          {current && (
            <>
              <Panel title={`MESSAGE #${current.id} · WHAT THE BOT UNDERSTOOD`}>
                <Row label="Read as">
                  {current.intent
                    ? <Tag className={INTENT_STYLE[current.intent] || 'bg-muted text-muted-foreground'}>{current.intent.replace('_', ' ')}</Tag>
                    : <span className="text-muted-foreground">{current.detail || 'not classified'}</span>}
                </Row>
                {current.parsed.map((p, i) => (
                  <Row key={i} label={p.plan ? 'Plan' : 'Signal'}>
                    <span className="font-mono">
                      {p.symbol} {p.side}
                      {p.instant ? ' · enter now' : ''}
                      {p.zone ? ` · zone ${p.zone[0]}–${p.zone[1]}` : p.entries?.length ? ` · entries ${p.entries.join(' / ')}` : p.entry != null ? ` · entry ${p.entry}` : ''}
                      {` · SL ${p.sl ?? 'none'}`}
                      {` · TP ${p.tps.length ? p.tps.join(' / ') : 'none'}`}
                    </span>
                  </Row>
                ))}
                {current.not_parsed && <Row label="Not a trade"><span className="text-muted-foreground">{current.not_parsed}</span></Row>}
                {current.relation && (
                  <Row label="Belongs to">
                    <button type="button" className="font-semibold text-primary underline-offset-2 hover:underline"
                      onClick={() => { setFollow(false); setSelected(current.relation!.to_message) }}>
                      #{current.relation.to_message}
                    </button>
                    <span className="text-muted-foreground"> — {current.relation.why}; </span>
                    <span className="text-emerald-400">same signal, no second trade</span>
                  </Row>
                )}
                {current.command && (
                  <Row label="Manages">
                    {current.command.target_message != null && (
                      <button type="button" className="font-semibold text-primary underline-offset-2 hover:underline"
                        onClick={() => { setFollow(false); setSelected(current.command!.target_message!) }}>
                        #{current.command.target_message}
                      </button>
                    )}
                    {current.ai_action?.action && (
                      <span className="ml-2 font-mono text-xs">
                        {current.ai_action.action}
                        {current.ai_action.value != null ? ` ${current.ai_action.value}` : ''}
                        {current.ai_action.percentage != null ? ` ${current.ai_action.percentage}%` : ''}
                      </span>
                    )}
                    {current.command.ignored && <span className="ml-2 text-muted-foreground">no action needed</span>}
                  </Row>
                )}
                {Object.keys(current.prices).length > 0 && (
                  <Row label="Price then">
                    <span className="font-mono text-xs">
                      {Object.entries(current.prices).map(([s, q]) => `${s} ${q.bid} / ${q.ask}`).join('   ')}
                    </span>
                  </Row>
                )}
              </Panel>

              <Panel title="WHAT THE BOT DID">
                {!current.actions.length && !current.notes.length && (
                  <p className="text-sm text-muted-foreground">
                    {current.command?.result || current.detail || 'Nothing sent to the broker.'}
                  </p>
                )}
                {current.actions.map((line, i) => (
                  <div key={i} className="flex items-start gap-2 py-0.5 text-sm">
                    <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-emerald-400" />
                    <span className="font-mono text-[13px]">{line}</span>
                  </div>
                ))}
                {current.notes.map((line, i) => (
                  <div key={`n${i}`} className="flex items-start gap-2 py-0.5 text-sm text-muted-foreground">
                    <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-muted-foreground/50" />
                    <span>{line}</span>
                  </div>
                ))}
                {current.review.map((line, i) => (
                  <div key={`r${i}`} className="mt-1.5 rounded-lg border border-amber-500/30 bg-amber-500/10 px-2.5 py-1.5 text-sm text-amber-300">
                    Needs review: {line}
                  </div>
                ))}
              </Panel>

              <Panel title="OPEN AFTER THIS MESSAGE">
                <SetupTable rows={current.setup} />
              </Panel>

              {setupView && (
                <Panel title={`SETUP #${setupId} · EXECUTIONS`}>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-b border-border text-left text-[10px] tracking-wider text-muted-foreground">
                          <th className="px-1.5 py-1.5 font-semibold">TIME</th>
                          <th className="px-1.5 py-1.5 font-semibold">EVENT</th>
                          <th className="px-1.5 py-1.5 font-semibold">ORDER</th>
                          <th className="px-1.5 py-1.5 font-semibold">LOTS</th>
                          <th className="px-1.5 py-1.5 font-semibold">PRICE</th>
                          <th className="px-1.5 py-1.5 font-semibold">P/L</th>
                        </tr>
                      </thead>
                      <tbody className="font-mono">
                        {setupExecutions.map((e, i) => (
                          <tr key={i} className="border-b border-border/50">
                            <td className="px-1.5 py-1.5">{clockSec(e.time)}</td>
                            <td className="px-1.5 py-1.5 font-sans">
                              <span className={cn('mr-1.5 inline-block h-2 w-2 rounded-full',
                                e.kind === 'entry' ? 'bg-primary' : (e.pnl ?? 0) >= 0 ? 'bg-emerald-400' : 'bg-rose-400')} />
                              {e.kind === 'entry' ? `${e.side} entry — ${e.how}` : `Exit — ${e.how}`}
                            </td>
                            <td className="px-1.5 py-1.5 text-muted-foreground">#{e.ticket}</td>
                            <td className="px-1.5 py-1.5">{e.lots.toFixed(2)}</td>
                            <td className="px-1.5 py-1.5">{e.price}</td>
                            <td className={cn('px-1.5 py-1.5', e.pnl == null ? 'text-muted-foreground' : e.pnl >= 0 ? 'text-emerald-400' : 'text-rose-400')}>
                              {money(e.pnl)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <p className="mt-2 text-xs text-muted-foreground">
                    Result of this setup so far:{' '}
                    <span className={cn('font-mono', setupView.pnl >= 0 ? 'text-emerald-400' : 'text-rose-400')}>{money(setupView.pnl)}</span>
                  </p>
                </Panel>
              )}

              {setupView && (
                <Panel title={`SETUP #${setupId} · ${setupView.symbol} CHART, ENTRY TO EXIT`}>
                  {charts.get(setupView.symbol)?.bars.length ? (
                    <FlowReplayChart
                      bars={charts.get(setupView.symbol)!.bars}
                      executions={setupExecutions}
                      messages={setupView.marks}
                      levels={setupView.levels}
                      from={setupView.from}
                      to={setupView.to}
                    />
                  ) : (
                    <p className="text-sm text-muted-foreground">
                      {summary ? 'No price history was available for this instrument.' : 'The chart is drawn when the replay has finished.'}
                    </p>
                  )}
                  <p className="mt-2 text-xs text-muted-foreground">
                    Times are your local time ({utcOffsetLabel(localOffset)}), the same clock as the chat.
                    {clocks.get(setupView.symbol) && (
                      <> Broker server clock: {utcOffsetLabel(clocks.get(setupView.symbol)!.offset_hours)} — {clocks.get(setupView.symbol)!.source}
                        {clocks.get(setupView.symbol)!.offset_hours !== 0 && '; the price bars were moved to real time before the replay'}.
                      </>
                    )}
                    {(charts.get(setupView.symbol)?.minutes_per_bar || 1) > 1 &&
                      ` One candle is ${charts.get(setupView.symbol)!.minutes_per_bar} minutes.`}
                  </p>
                </Panel>
              )}

              {(marketAfter.get(current.id) || []).length > 0 && (
                <Panel title="WHAT HAPPENED NEXT (PRICE REPLAY UNTIL THE NEXT MESSAGE)">
                  {(marketAfter.get(current.id) || []).flatMap(m => m.events).map((e, i) => (
                    <div key={i} className={cn('flex items-start gap-2 py-0.5 text-sm', e.by === 'note' && 'text-muted-foreground')}>
                      <span className={cn('mt-1.5 h-2 w-2 shrink-0 rounded-full',
                        e.by === 'broker' ? 'bg-primary' : e.by === 'bot' ? 'bg-emerald-400' : 'bg-muted-foreground/50')} />
                      <span className="shrink-0 font-mono text-xs text-muted-foreground">{clock(e.time)}</span>
                      <span className={e.by === 'note' ? '' : 'font-mono text-[13px]'}>{e.text}</span>
                    </div>
                  ))}
                </Panel>
              )}
            </>
          )}

          {summary && (
            <Panel title="RESULT OF THE REPLAY">
              <Row label="Closed P/L"><span className={cn('font-mono', summary.realized >= 0 ? 'text-emerald-400' : 'text-rose-400')}>{money(summary.realized)}</span></Row>
              <Row label="Still open"><span className="font-mono">{summary.open.length} order(s), {money(summary.floating)} floating</span></Row>
              <div className="mt-2 overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-border text-left text-[10px] tracking-wider text-muted-foreground">
                      <th className="px-1.5 py-1.5 font-semibold">SIGNAL</th>
                      <th className="px-1.5 py-1.5 font-semibold">INSTRUMENT</th>
                      <th className="px-1.5 py-1.5 font-semibold">TRADES</th>
                      <th className="px-1.5 py-1.5 font-semibold">STATUS</th>
                      <th className="px-1.5 py-1.5 font-semibold">P/L</th>
                    </tr>
                  </thead>
                  <tbody className="font-mono">
                    {summary.signals.map(sig => (
                      <tr key={sig.message} className="cursor-pointer border-b border-border/50 hover:bg-muted/40"
                        onClick={() => { setFollow(false); setSelected(sig.message) }}>
                        <td className="px-1.5 py-1.5 text-primary">#{sig.message}</td>
                        <td className="px-1.5 py-1.5">{sig.symbol} {sig.side}</td>
                        <td className="px-1.5 py-1.5">{sig.trades}</td>
                        <td className="px-1.5 py-1.5">{sig.status}</td>
                        <td className={cn('px-1.5 py-1.5', sig.pnl >= 0 ? 'text-emerald-400' : 'text-rose-400')}>{money(sig.pnl)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
          )}
        </div>
      </div>

      {/* Position in the replay */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-border px-4 py-2 text-xs text-muted-foreground">
        <Button variant="ghost" size="sm" className="h-7 px-2" onClick={() => step(-1)} aria-label="Previous message"><ChevronLeft className="h-4 w-4" /></Button>
        <Button variant="ghost" size="sm" className="h-7 px-2" onClick={() => step(1)} aria-label="Next message"><ChevronRight className="h-4 w-4" /></Button>
        <span className="font-mono">
          {current ? `message ${current.index} / ${current.total}` : status}
        </span>
        <div className="relative order-last h-1.5 basis-full rounded bg-muted sm:order-none sm:flex-1 sm:basis-0">
          {last && <div className="absolute inset-y-0 left-0 rounded bg-primary/60" style={{ width: `${(last.index / last.total) * 100}%` }} />}
          {messages.filter(m => OUTCOME_DOT[m.outcome] || m.review.length).map(m => (
            <button key={m.id} type="button" title={`#${m.id} ${m.outcome}`}
              onClick={() => { setFollow(false); setSelected(m.id) }}
              className={cn('absolute -top-1 h-3.5 w-1 rounded', m.review.length ? 'bg-amber-400' : OUTCOME_DOT[m.outcome])}
              style={{ left: `${(m.index / m.total) * 100}%` }} />
          ))}
        </div>
        <span className="min-w-0 flex-1 sm:flex-none">
          {status === 'fetching' ? 'reading the channel' : status === 'running' ? 'replaying'
            : status === 'done' ? 'finished' : status}
          {started ? ` · AI ${started.ai} · risk ${started.risk_percent}% · runner ${started.runner ? 'on' : 'off'}` : ''}
        </span>
        <Button variant="outline" size="sm" className="h-7 shrink-0" disabled={!events.length} onClick={exportReport}>
          <Download className="mr-1.5 h-3.5 w-3.5" />Export
        </Button>
      </div>
    </div>
  )
}
