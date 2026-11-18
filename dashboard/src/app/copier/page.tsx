'use client'

import { useState, useEffect, useCallback, useRef, type ReactNode } from 'react'
import Link from 'next/link'
import { toast } from 'sonner'
import {
  Copy,
  Server,
  MonitorSmartphone,
  CheckCircle2,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  RefreshCw,
  Trash2,
  KeyRound,
  Activity,
  WifiOff,
  ArrowRightLeft,
} from 'lucide-react'
import MobilePageHeader from '@/components/MobilePageHeader'
import { Button } from '@/components/ui/button'
import type { CopierAccountView, CopierItem, SyncStatus, SyncCell } from '@/lib/copier'

interface CopierResponse {
  generatedAt: string
  master: {
    login: string
    server: string | null
    company: string | null
    currency: string | null
    leverage: number | null
    balance: number | null
    equity: number | null
    margin: number | null
    freeMargin: number | null
    profit: number | null
    generatedAt: string
  } | null
  masterError: string | null
  items: CopierItem[]
  accounts: CopierAccountView[]
}

interface EventRow {
  id: string
  createdAt: string
  type: string
  symbol: string | null
  masterTicket: string | null
  mirrorTicket: string | null
  message: string
}

const REFRESH_MS = 5000

const STATUS_META: Record<SyncStatus, { label: string; className: string }> = {
  SYNCED: { label: 'Synced', className: 'text-success bg-success/10 border-success/25' },
  DRIFT: { label: 'Drift', className: 'text-gold bg-gold/10 border-gold/30' },
  AWAITING_FILL: { label: 'Awaiting fill', className: 'text-primary bg-primary/10 border-primary/25' },
  MISSING: { label: 'Missing', className: 'text-destructive bg-destructive/10 border-destructive/25' },
  SKIPPED: { label: 'Skipped', className: 'text-muted-foreground bg-muted border-border' },
  CLOSED: { label: 'Closed on mirror', className: 'text-muted-foreground bg-muted border-border' },
  DRY: { label: 'Dry run', className: 'text-gold bg-gold/10 border-gold/30' },
  UNKNOWN: { label: 'Unknown', className: 'text-muted-foreground bg-muted border-border' },
}

const CONNECTION_META = {
  online: { label: 'Online', dot: 'bg-success', text: 'text-success' },
  stale: { label: 'Stale', dot: 'bg-gold', text: 'text-gold' },
  offline: { label: 'Offline', dot: 'bg-destructive', text: 'text-destructive' },
} as const

const EVENT_TONE: Record<string, string> = {
  OPEN: 'text-success',
  FILL: 'text-success',
  PLACE: 'text-primary',
  ADOPT: 'text-primary',
  DRY: 'text-gold',
  CLOSE: 'text-foreground',
  PARTIAL: 'text-foreground',
  MODIFY: 'text-primary',
  CANCEL: 'text-foreground',
  SKIP: 'text-muted-foreground',
  ERROR: 'text-destructive',
  WARN: 'text-gold',
}

function money(v: number | null | undefined, currency?: string | null) {
  if (v === null || v === undefined) return '—'
  return `${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}${currency ? ` ${currency}` : ''}`
}

function price(v: number | null | undefined) {
  if (v === null || v === undefined || v === 0) return '—'
  return String(Number(v.toFixed(5)))
}

function lots(v: number | null | undefined) {
  if (v === null || v === undefined) return '—'
  return String(Number(v.toFixed(3)))
}

function ago(sec: number) {
  if (sec < 60) return `${sec}s ago`
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`
  return `${Math.floor(sec / 86400)}d ago`
}

function pnlClass(v: number | null | undefined) {
  if (!v) return 'text-muted-foreground'
  return v > 0 ? 'text-success' : 'text-destructive'
}

function StatusPill({ status }: { status: SyncStatus }) {
  const meta = STATUS_META[status]
  return (
    <span className={`inline-flex items-center text-[11px] font-bold rounded-full border px-2 py-0.5 whitespace-nowrap ${meta.className}`}>
      {meta.label}
    </span>
  )
}

function Metric({ label, value, className }: { label: string; value: ReactNode; className?: string }) {
  return (
    <div className="min-w-0">
      <p className="tech-label">{label}</p>
      <p className={`text-sm font-bold tabular-nums truncate mt-0.5 ${className ?? ''}`}>{value}</p>
    </div>
  )
}

export default function CopierPage() {
  const [data, setData] = useState<CopierResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [tab, setTab] = useState<Record<string, 'sync' | 'events'>>({})
  const [events, setEvents] = useState<Record<string, EventRow[]>>({})
  const inFlight = useRef(false)

  const load = useCallback(async () => {
    if (inFlight.current) return
    inFlight.current = true
    try {
      const res = await fetch('/api/copier', { cache: 'no-store' })
      const body = await res.json()
      if (!res.ok) throw new Error(body.error || `HTTP ${res.status}`)
      setData(body)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load')
    } finally {
      inFlight.current = false
      setLoading(false)
    }
  }, [])

  const loadEvents = useCallback(async (id: string) => {
    try {
      const res = await fetch(`/api/copier/${id}/events?limit=100`, { cache: 'no-store' })
      const body = await res.json()
      if (!res.ok) throw new Error(body.error || `HTTP ${res.status}`)
      setEvents((prev) => ({ ...prev, [id]: body.events ?? [] }))
    } catch (err) {
      toast.error('Failed to load events', { description: err instanceof Error ? err.message : undefined })
    }
  }, [])

  useEffect(() => {
    load()
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') load()
    }, REFRESH_MS)
    return () => clearInterval(timer)
  }, [load])

  // Keep an open events tab live along with the rest of the page.
  useEffect(() => {
    for (const [id, t] of Object.entries(tab)) {
      if (t === 'events' && expanded.has(id)) loadEvents(id)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.generatedAt])

  function toggle(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function showTab(id: string, t: 'sync' | 'events') {
    setTab((prev) => ({ ...prev, [id]: t }))
    if (t === 'events') loadEvents(id)
  }

  async function forget(account: CopierAccountView) {
    if (!confirm(`Remove ${account.keyLabel} · ${account.login} from this list? It reappears if its EA reports again.`)) return
    const res = await fetch(`/api/copier/${account.id}`, { method: 'DELETE' })
    if (res.ok) {
      toast.success('Account removed')
      load()
    } else {
      toast.error('Failed to remove account')
    }
  }

  const accounts = data?.accounts ?? []
  const online = accounts.filter((a) => a.connection === 'online').length
  const synced = accounts.reduce((n, a) => n + a.synced, 0)
  const issues = accounts.filter((a) => a.connection !== 'offline').reduce((n, a) => n + a.issues, 0)
  const master = data?.master

  return (
    <div className="flex min-h-full flex-col">
      <MobilePageHeader
        title="Trade Copier"
        subtitle="Master → mirror accounts"
        hidden
        icon={<Copy className="w-5 h-5" />}
      />

      <header className="hidden md:flex sticky top-0 z-40 w-full tech-header">
        <div className="max-w-[1400px] w-full mx-auto flex h-14 items-center justify-between px-6 gap-3">
          <div className="flex items-center gap-3">
            <div className="p-1.5 rounded-lg bg-primary/10 border border-primary/20">
              <Copy className="h-5 w-5 text-primary" />
            </div>
            <div className="flex flex-col">
              <h1 className="text-sm font-bold text-foreground leading-none">Trade Copier</h1>
              <p className="text-[10px] text-[#6b7288] font-bold uppercase tracking-wider mt-1">
                Master → mirror accounts · live sync
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[11px] text-muted-foreground font-medium hidden lg:inline">
              Auto-refresh every {REFRESH_MS / 1000}s
            </span>
            <Button variant="outline" size="sm" onClick={load} className="font-semibold">
              <RefreshCw className="w-3.5 h-3.5 mr-1" /> Refresh
            </Button>
          </div>
        </div>
      </header>

      <div className="flex-1 px-3 md:px-6 py-3 md:py-5">
        <div className="max-w-[1400px] mx-auto space-y-4">
          {error && (
            <div className="tech-card border-destructive/40 px-4 py-3 text-sm text-destructive flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 shrink-0" /> {error}
            </div>
          )}

          {/* Stat strip */}
          <div className="tech-card grid grid-cols-2 lg:grid-cols-4 divide-y lg:divide-y-0 lg:divide-x divide-border overflow-hidden">
            <StatTile
              label="Master"
              value={master ? 'Live' : loading ? '…' : 'Unavailable'}
              tone={master ? 'success' : loading ? 'muted' : 'destructive'}
              icon={Server}
            />
            <StatTile label="Mirrors online" value={`${online} / ${accounts.length}`} tone={online > 0 ? 'success' : 'muted'} icon={MonitorSmartphone} />
            <StatTile label="Synced tickets" value={String(synced)} tone="primary" icon={CheckCircle2} />
            <StatTile label="Open issues" value={String(issues)} tone={issues > 0 ? 'destructive' : 'muted'} icon={AlertTriangle} />
          </div>

          {/* Master card */}
          <div className="tech-card overflow-hidden">
            <div className="flex items-center justify-between gap-3 px-4 sm:px-5 py-3.5 border-b border-border">
              <div className="min-w-0">
                <h2 className="text-sm font-bold flex items-center gap-2">
                  <Server className="h-3.5 w-3.5" /> Master account
                </h2>
                <p className="text-xs text-muted-foreground font-medium mt-0.5 truncate">
                  {master
                    ? `${master.login} · ${master.server ?? ''}${master.company ? ` · ${master.company}` : ''}`
                    : 'The account every mirror copies'}
                </p>
              </div>
              {master && (
                <span className="inline-flex items-center gap-1.5 text-[11px] font-bold text-success shrink-0">
                  <span className="w-1.5 h-1.5 rounded-full bg-success animate-pulse" /> Snapshot live
                </span>
              )}
            </div>
            {master ? (
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4 px-4 sm:px-5 py-4">
                <Metric label="Balance" value={money(master.balance, master.currency)} />
                <Metric label="Equity" value={money(master.equity, master.currency)} />
                <Metric label="Floating P/L" value={money(master.profit)} className={pnlClass(master.profit)} />
                <Metric label="Margin" value={money(master.margin)} />
                <Metric label="Positions" value={data?.items.filter((i) => i.kind === 'POSITION').length ?? 0} />
                <Metric label="Pending orders" value={data?.items.filter((i) => i.kind === 'ORDER').length ?? 0} />
              </div>
            ) : (
              <div className="px-4 sm:px-5 py-4 text-sm flex items-start gap-2 text-destructive">
                <WifiOff className="h-4 w-4 mt-0.5 shrink-0" />
                <div>
                  <p className="font-semibold">{loading ? 'Loading…' : 'Master snapshot unavailable'}</p>
                  {data?.masterError && <p className="text-xs text-muted-foreground mt-0.5 break-words">{data.masterError}</p>}
                  {!loading && (
                    <p className="text-xs text-muted-foreground mt-1">
                      Mirror EAs hold their positions and take no action until the snapshot is back.
                    </p>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Accounts */}
          <div className="tech-card overflow-hidden">
            <div className="flex items-center justify-between gap-3 px-4 sm:px-5 py-3.5 border-b border-border">
              <div className="min-w-0">
                <h2 className="text-sm font-bold flex items-center gap-2">
                  <ArrowRightLeft className="h-3.5 w-3.5" /> Mirror accounts
                </h2>
                <p className="text-xs text-muted-foreground font-medium mt-0.5 hidden sm:block">
                  Every terminal running the copier EA, as it last reported in
                </p>
              </div>
              <Link href="/settings/api-keys" className="text-xs font-semibold text-primary hover:underline inline-flex items-center gap-1 shrink-0">
                <KeyRound className="h-3 w-3" /> API keys
              </Link>
            </div>

            {loading && !data ? (
              <div className="py-16 flex flex-col items-center justify-center gap-2 text-muted-foreground">
                <div className="h-5 w-5 rounded-full border-2 border-primary/30 border-t-primary animate-spin" />
                <p className="text-sm font-medium">Loading accounts…</p>
              </div>
            ) : accounts.length === 0 ? (
              <EmptyState />
            ) : (
              <div className="divide-y divide-border">
                {accounts.map((a) => {
                  const conn = CONNECTION_META[a.connection]
                  const open = expanded.has(a.id)
                  const t = tab[a.id] ?? 'sync'
                  return (
                    <div key={a.id}>
                      <button
                        onClick={() => toggle(a.id)}
                        className="w-full text-left px-4 sm:px-5 py-3.5 hover:bg-accent/40 transition-colors"
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className={`w-2 h-2 rounded-full shrink-0 ${conn.dot} ${a.connection === 'online' ? 'animate-pulse' : ''}`} />
                              <span className="text-sm font-bold truncate">{a.keyLabel}</span>
                              <span className={`text-[11px] font-bold ${conn.text}`}>{conn.label}</span>
                              <ModeBadge mode={a.mode} halted={a.halted} />
                              {!a.keyActive && (
                                <span className="text-[10px] font-bold rounded border px-1.5 py-0.5 text-destructive border-destructive/30 bg-destructive/10">
                                  KEY INACTIVE
                                </span>
                              )}
                              {!a.feedOk && (
                                <span className="text-[10px] font-bold rounded border px-1.5 py-0.5 text-destructive border-destructive/30 bg-destructive/10">
                                  FEED ERROR
                                </span>
                              )}
                            </div>
                            <p className="text-xs text-muted-foreground font-medium mt-1 truncate">
                              {a.login} · {a.server}
                              {a.broker ? ` · ${a.broker}` : ''}
                              {a.eaVersion ? ` · EA v${a.eaVersion}` : ''}
                            </p>
                          </div>
                          <div className="flex items-center gap-3 shrink-0">
                            <SyncSummary account={a} itemCount={data?.items.length ?? 0} hasMaster={!!master} />
                            {open ? <ChevronUp className="h-4 w-4 text-muted-foreground" /> : <ChevronDown className="h-4 w-4 text-muted-foreground" />}
                          </div>
                        </div>

                        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mt-3">
                          <Metric label="Balance" value={money(a.balance, a.currency)} />
                          <Metric label="Equity" value={money(a.equity, a.currency)} />
                          <Metric label="Copied P/L" value={money(a.mirrorProfit)} className={pnlClass(a.mirrorProfit)} />
                          <Metric label="Positions / orders" value={`${a.mirrorPositions} / ${a.mirrorOrders}`} />
                          <Metric label="Sizing" value={a.sizing ?? '—'} />
                          <Metric label="Last seen" value={ago(a.lastSeenAgoSec)} className={conn.text} />
                        </div>

                        {a.lastError && (
                          <p className="text-xs text-destructive mt-2 flex items-start gap-1.5 break-words">
                            <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" /> {a.lastError}
                          </p>
                        )}
                      </button>

                      {open && (
                        <div className="px-4 sm:px-5 pb-4">
                          <div className="flex items-center justify-between gap-2 mb-3">
                            <div className="flex items-center gap-1">
                              {(['sync', 'events'] as const).map((k) => (
                                <button
                                  key={k}
                                  onClick={() => showTab(a.id, k)}
                                  className={`px-2.5 py-1 rounded-md text-[11px] font-semibold transition-colors ${
                                    t === k ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground hover:bg-accent'
                                  }`}
                                >
                                  {k === 'sync' ? 'Position sync' : `Activity (${a.events24h} / 24h)`}
                                </button>
                              ))}
                            </div>
                            <div className="flex items-center gap-3">
                              <span className="text-[11px] text-muted-foreground hidden sm:inline">
                                {a.lastIp ? `from ${a.lastIp} · ` : ''}poll {a.pollSeconds ?? '?'}s
                                {a.pollFailures > 0 ? ` · ${a.pollFailures} failed polls` : ''}
                              </span>
                              <Button variant="ghost" size="sm" className="h-7 text-xs text-muted-foreground" onClick={() => forget(a)}>
                                <Trash2 className="w-3 h-3 mr-1" /> Remove
                              </Button>
                            </div>
                          </div>
                          {t === 'sync' ? (
                            <SyncTable account={a} items={data?.items ?? []} hasMaster={!!master} />
                          ) : (
                            <EventsList rows={events[a.id]} />
                          )}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function StatTile({ label, value, icon: Icon, tone }: { label: string; value: string; icon: typeof Server; tone: 'success' | 'muted' | 'destructive' | 'primary' }) {
  const toneClasses = {
    success: 'bg-success/10 text-success',
    muted: 'bg-muted text-muted-foreground',
    destructive: 'bg-destructive/10 text-destructive',
    primary: 'bg-primary/10 text-primary',
  }
  return (
    <div className="flex items-center gap-3 p-4">
      <div className={`p-2 rounded-lg shrink-0 ${toneClasses[tone]}`}>
        <Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0">
        <p className="text-xl font-black tabular-nums leading-none truncate">{value}</p>
        <p className="tech-label mt-1">{label}</p>
      </div>
    </div>
  )
}

function ModeBadge({ mode, halted }: { mode: string | null; halted: boolean }) {
  if (halted) {
    return (
      <span className="text-[10px] font-bold rounded border px-1.5 py-0.5 text-destructive border-destructive/30 bg-destructive/10">
        HALTED · daily loss
      </span>
    )
  }
  if (mode === 'LIVE') {
    return <span className="text-[10px] font-bold rounded border px-1.5 py-0.5 text-success border-success/30 bg-success/10">LIVE</span>
  }
  return <span className="text-[10px] font-bold rounded border px-1.5 py-0.5 text-gold border-gold/30 bg-gold/10">DRY RUN</span>
}

function SyncSummary({ account, itemCount, hasMaster }: { account: CopierAccountView; itemCount: number; hasMaster: boolean }) {
  if (!hasMaster || account.connection === 'offline') {
    return <span className="text-[11px] font-bold text-muted-foreground">Sync unknown</span>
  }
  if (account.issues > 0) {
    return (
      <span className="inline-flex items-center gap-1 text-[11px] font-bold text-gold">
        <AlertTriangle className="h-3.5 w-3.5" /> {account.issues} issue{account.issues === 1 ? '' : 's'}
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 text-[11px] font-bold text-success">
      <CheckCircle2 className="h-3.5 w-3.5" /> {itemCount === 0 ? 'In sync · master flat' : `${account.synced}/${itemCount} synced`}
    </span>
  )
}

function SyncTable({ account, items, hasMaster }: { account: CopierAccountView; items: CopierItem[]; hasMaster: boolean }) {
  if (!hasMaster) {
    return <p className="text-sm text-muted-foreground py-3">Master snapshot unavailable — sync can&apos;t be compared right now.</p>
  }
  if (items.length === 0 && account.closing.length === 0) {
    return <p className="text-sm text-muted-foreground py-3">The master has no open positions or pending orders.</p>
  }
  return (
    <div className="rounded-lg border border-border overflow-x-auto">
      <table className="w-full text-xs min-w-[760px]">
        <thead className="bg-muted/50 text-muted-foreground">
          <tr className="text-left">
            <th className="px-3 py-2 font-semibold">Master ticket</th>
            <th className="px-3 py-2 font-semibold">Symbol</th>
            <th className="px-3 py-2 font-semibold">Side</th>
            <th className="px-3 py-2 font-semibold text-right">Lots M → C</th>
            <th className="px-3 py-2 font-semibold text-right">SL M → C</th>
            <th className="px-3 py-2 font-semibold text-right">TP M → C</th>
            <th className="px-3 py-2 font-semibold text-right">Copy P/L</th>
            <th className="px-3 py-2 font-semibold">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {items.map((item) => {
            const cell: SyncCell = account.cells[item.ticket] ?? { status: 'UNKNOWN', note: null, mirror: null }
            const m = cell.mirror
            return (
              <tr key={item.ticket} className="align-top">
                <td className="px-3 py-2 font-mono tabular-nums">
                  {item.ticket}
                  {item.manual && <span className="ml-1.5 text-[10px] text-muted-foreground font-sans">manual</span>}
                </td>
                <td className="px-3 py-2 font-semibold">{item.symbol}</td>
                <td className={`px-3 py-2 font-semibold ${item.side.startsWith('BUY') ? 'text-success' : 'text-destructive'}`}>
                  {item.side.replace('_', ' ')}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {lots(item.volume)} <span className="text-muted-foreground">→</span> {m ? lots(m.volume) : '—'}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {price(item.sl)} <span className="text-muted-foreground">→</span> {m ? price(m.sl) : '—'}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {price(item.tp)} <span className="text-muted-foreground">→</span> {m ? price(m.tp) : '—'}
                </td>
                <td className={`px-3 py-2 text-right tabular-nums ${pnlClass(m?.profit)}`}>{m ? money(m.profit) : '—'}</td>
                <td className="px-3 py-2">
                  <StatusPill status={cell.status} />
                  {cell.note && <p className="text-[11px] text-muted-foreground mt-1 max-w-[260px] break-words">{cell.note}</p>}
                </td>
              </tr>
            )
          })}
          {account.closing.map((l) => (
            <tr key={`closing-${l.master}`} className="align-top bg-gold/5">
              <td className="px-3 py-2 font-mono tabular-nums">{l.master}</td>
              <td className="px-3 py-2 font-semibold">{l.symbol ?? '—'}</td>
              <td className="px-3 py-2">{l.side ?? '—'}</td>
              <td className="px-3 py-2 text-right tabular-nums">— <span className="text-muted-foreground">→</span> {lots(l.volume)}</td>
              <td className="px-3 py-2 text-right tabular-nums">— <span className="text-muted-foreground">→</span> {price(l.sl)}</td>
              <td className="px-3 py-2 text-right tabular-nums">— <span className="text-muted-foreground">→</span> {price(l.tp)}</td>
              <td className={`px-3 py-2 text-right tabular-nums ${pnlClass(l.profit)}`}>{money(l.profit)}</td>
              <td className="px-3 py-2">
                <span className="inline-flex items-center text-[11px] font-bold rounded-full border px-2 py-0.5 text-gold bg-gold/10 border-gold/30">
                  Closing
                </span>
                <p className="text-[11px] text-muted-foreground mt-1 max-w-[260px]">
                  {l.note ?? 'Gone from the master — the EA is confirming before it closes'}
                </p>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function EventsList({ rows }: { rows: EventRow[] | undefined }) {
  if (!rows) return <p className="text-sm text-muted-foreground py-3">Loading…</p>
  if (rows.length === 0) return <p className="text-sm text-muted-foreground py-3">No activity reported yet.</p>
  return (
    <div className="rounded-lg border border-border divide-y divide-border max-h-[420px] overflow-y-auto">
      {rows.map((e) => (
        <div key={e.id} className="px-3 py-2 text-xs flex items-start gap-3">
          <span className="text-muted-foreground tabular-nums shrink-0 w-[70px]">
            {new Date(e.createdAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
          </span>
          <span className={`font-bold shrink-0 w-[58px] ${EVENT_TONE[e.type] ?? 'text-foreground'}`}>{e.type}</span>
          <span className="min-w-0 break-words">
            {e.symbol && <span className="font-semibold mr-1">{e.symbol}</span>}
            {e.message}
            {e.masterTicket && <span className="text-muted-foreground"> · master #{e.masterTicket}</span>}
          </span>
        </div>
      ))}
    </div>
  )
}

function EmptyState() {
  return (
    <div className="py-14 px-6 flex flex-col items-center justify-center gap-3 text-center">
      <div className="p-3 rounded-full bg-primary/10 border border-primary/20">
        <Activity className="h-6 w-6 text-primary" />
      </div>
      <div className="space-y-1.5 max-w-md">
        <p className="text-sm font-bold text-foreground">No mirror accounts have reported in yet</p>
        <ol className="text-xs text-muted-foreground text-left list-decimal pl-5 space-y-1">
          <li>
            Issue a key on the{' '}
            <Link href="/settings/api-keys" className="text-primary font-semibold hover:underline">
              API Keys
            </Link>{' '}
            page.
          </li>
          <li>Attach NexalSignalMirrorEA v2 to any chart on the mirror account, with that key and this dashboard&apos;s URL.</li>
          <li>Whitelist the URL under Tools → Options → Expert Advisors → Allow WebRequest.</li>
        </ol>
        <p className="text-xs text-muted-foreground">It appears here within one report interval (15s by default).</p>
      </div>
    </div>
  )
}
