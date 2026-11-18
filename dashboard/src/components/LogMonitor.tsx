'use client'

import { useState, useEffect, useCallback, useMemo } from 'react'
import Link from 'next/link'
import { formatDistanceToNowStrict } from 'date-fns'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { useToast } from '@/hooks/use-toast'
import { entryTime, isOpen, type IssueKind, type LogIssue, type MonitorSummary } from '@/lib/logMonitor'
import {
  Activity, AlertTriangle, BellOff, Bot, Check, ChevronDown, ChevronRight,
  ExternalLink, RefreshCw, RotateCcw, Sparkles, Trash2, XCircle, CheckCircle2, Search,
} from 'lucide-react'
import Markdown from '@/components/Markdown'

interface MonitorData extends MonitorSummary {
  botOnline: boolean
  files: { name: string; size: number; modified: string }[]
  totalBytes: number
}

interface Finding {
  title: string
  issueIds?: string[]
  cause?: string
  fix?: string
  urgency?: 'now' | 'soon' | 'later' | 'noise'
}

interface Analysis {
  provider?: string
  model?: string
  scope: string
  analysis: { summary: string; severity?: string | null; findings: Finding[] }
}

type IssueFilter = 'open' | 'noise' | 'resolved' | 'all'

const FILTER_LABEL: Record<IssueFilter, string> = { open: 'Needs attention', noise: 'Noise', resolved: 'Fixed / muted', all: 'All' }

const POLL_MS = 30_000

const ago = (ts: string | null) => (ts ? `${formatDistanceToNowStrict(entryTime(ts))} ago` : '—')
const agoIso = (iso: string | null) => (iso ? `${formatDistanceToNowStrict(new Date(iso))} ago` : '—')
const isError = (level: string) => level === 'ERROR' || level === 'CRITICAL'

function formatBytes(n: number) {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

function toDigest(issues: LogIssue[]) {
  return issues.slice(0, 40).map((i) => ({
    id: i.id,
    level: i.level,
    count: i.count,
    firstSeen: i.firstSeen,
    lastSeen: i.lastSeen,
    sample: i.sample,
    samples: i.samples,
    details: i.details,
    hint: i.hint ? `${i.hint.title} — ${i.hint.fix}` : undefined,
  }))
}

const STATUS_STYLE = {
  ok: { label: 'Healthy', icon: CheckCircle2, cls: 'text-emerald-500 bg-emerald-500/10 border-emerald-500/30' },
  warning: { label: 'Warnings', icon: AlertTriangle, cls: 'text-amber-500 bg-amber-500/10 border-amber-500/30' },
  critical: { label: 'Errors', icon: XCircle, cls: 'text-red-500 bg-red-500/10 border-red-500/30' },
} as const

const KIND_STYLE: Record<IssueKind, { label: string; cls: string }> = {
  action: { label: 'Action needed', cls: 'bg-red-500 text-white' },
  watch: { label: 'Watch', cls: 'bg-amber-500 text-black' },
  noise: { label: 'Noise', cls: 'bg-muted text-muted-foreground' },
}

const isResolved = (i: LogIssue) => i.muted || i.acknowledged

const URGENCY_STYLE: Record<string, string> = {
  now: 'bg-red-500 text-white',
  soon: 'bg-amber-500 text-black',
  later: 'bg-blue-500 text-white',
  noise: 'bg-muted text-muted-foreground',
}

function Sparkline({ hourly, error }: { hourly: number[]; error: boolean }) {
  const max = Math.max(1, ...hourly)
  return (
    <div className="flex items-end gap-px h-5 w-[96px]" title="Occurrences per hour, last 24h">
      {hourly.map((n, i) => (
        <div
          key={i}
          className={cn('flex-1 rounded-[1px]', n === 0 ? 'bg-muted' : error ? 'bg-red-500/80' : 'bg-amber-500/80')}
          style={{ height: n === 0 ? 2 : `${Math.max(15, (n / max) * 100)}%` }}
        />
      ))}
    </div>
  )
}

function Stat({ label, value, tone }: { label: string; value: string | number; tone?: 'red' | 'amber' }) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">{label}</span>
      <span className={cn(
        'text-lg font-bold tabular-nums leading-tight',
        tone === 'red' && 'text-red-500',
        tone === 'amber' && 'text-amber-500',
      )}>{value}</span>
    </div>
  )
}

export default function LogMonitor({ onShowInLogs }: { onShowInLogs: (search: string) => void }) {
  const { toast } = useToast()
  const [data, setData] = useState<MonitorData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [filter, setFilter] = useState<IssueFilter>('open')
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [analyzing, setAnalyzing] = useState<string | null>(null)
  const [question, setQuestion] = useState('')
  const [clearing, setClearing] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/logs/monitor', { cache: 'no-store' })
      const body = await res.json()
      if (!res.ok) throw new Error(body.error || 'Failed to load monitor')
      setData(body)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(() => { if (!document.hidden) load() }, POLL_MS)
    return () => clearInterval(t)
  }, [load])

  const issues = useMemo(() => {
    const all = data?.issues ?? []
    switch (filter) {
      case 'open': return all.filter(isOpen)
      case 'noise': return all.filter((i) => i.kind === 'noise' && !isResolved(i))
      case 'resolved': return all.filter(isResolved)
      default: return all
    }
  }, [data, filter])

  const counts = useMemo(() => {
    const all = data?.issues ?? []
    return {
      open: all.filter(isOpen).length,
      noise: all.filter((i) => i.kind === 'noise' && !isResolved(i)).length,
      resolved: all.filter(isResolved).length,
      all: all.length,
    }
  }, [data])

  const issueById = useMemo(() => new Map((data?.issues ?? []).map((i) => [i.id, i])), [data])

  const setIssueState = async (signatures: string[], action: 'ack' | 'mute' | 'reopen') => {
    try {
      for (const signature of signatures) {
        const res = await fetch('/api/logs/monitor', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ signature, action }),
        })
        if (!res.ok) throw new Error((await res.json()).error || 'Failed')
      }
      await load()
    } catch (e) {
      toast({ title: 'Could not update issue', description: String(e), variant: 'destructive' })
    }
  }

  const analyze = async (target: LogIssue[], scope: string) => {
    if (target.length === 0) {
      toast({ title: 'Nothing to analyze', description: 'There are no issues in this view.' })
      return
    }
    setAnalyzing(scope)
    try {
      const res = await fetch('/api/logs/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ issues: toDigest(target), question: question.trim() || undefined }),
      })
      const body = await res.json()
      if (!res.ok) throw new Error(body.error || 'AI analysis failed')
      setAnalysis({ ...body, scope })
    } catch (e) {
      toast({ title: 'AI analysis failed', description: e instanceof Error ? e.message : String(e), variant: 'destructive' })
    } finally {
      setAnalyzing(null)
    }
  }

  const clearLogs = async (scope: 'old' | 'all') => {
    const msg = scope === 'old'
      ? 'Delete all log files older than today? Today\'s log is kept.'
      : 'Delete ALL log history, including today\'s log? This cannot be undone.'
    if (!confirm(msg)) return
    setClearing(true)
    try {
      const res = await fetch('/api/logs/clear', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scope }),
      })
      const body = await res.json()
      if (!res.ok) throw new Error(body.error || 'Failed')
      toast({
        title: 'Logs cleaned',
        description: `${body.deleted.length} deleted, ${body.truncated.length} emptied, ${formatBytes(body.freedBytes)} freed`,
      })
      if (scope === 'all') setAnalysis(null)
      await load()
    } catch (e) {
      toast({ title: 'Could not clear logs', description: e instanceof Error ? e.message : String(e), variant: 'destructive' })
    } finally {
      setClearing(false)
    }
  }

  const toggle = (id: string) => setExpanded((s) => {
    const n = new Set(s)
    if (n.has(id)) n.delete(id)
    else n.add(id)
    return n
  })

  if (!data) {
    return (
      <Card className="p-8 text-center text-muted-foreground">
        {error ? <p className="text-destructive font-semibold">Error: {error}</p> : (
          <><RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2" /><p className="font-semibold">Scanning logs…</p></>
        )}
      </Card>
    )
  }

  const status = STATUS_STYLE[data.status]
  const StatusIcon = status.icon
  const openIssues = (data.issues ?? []).filter(isOpen)
  const oldFiles = data.files.length - 1

  return (
    <div className="space-y-3">
      {/* Health strip */}
      <Card className="p-4 bg-card border-border shadow-sm">
        <div className="flex flex-col lg:flex-row lg:items-center gap-4">
          <div className="flex items-center gap-3 min-w-0">
            <div className={cn('flex items-center gap-2 px-3 py-1.5 rounded-lg border font-bold text-sm', status.cls)}>
              <StatusIcon className="h-4 w-4" />
              {status.label}
            </div>
            <div className="min-w-0">
              <p className="text-sm font-semibold text-foreground truncate">{data.statusReason}</p>
              <p className="text-[11px] text-muted-foreground flex items-center gap-2 flex-wrap">
                <span className={cn('inline-flex items-center gap-1', data.botOnline ? 'text-emerald-500' : 'text-red-500')}>
                  <Bot className="h-3 w-3" />{data.botOnline ? 'Bot online' : 'Bot offline'}
                </span>
                <span>· last log {agoIso(data.lastEntryAt)}</span>
                <span>· checked {agoIso(data.generatedAt)}</span>
              </p>
            </div>
          </div>
          <div className="grid grid-cols-4 gap-4 lg:ml-auto">
            <Stat label="Errors 1h" value={data.totals.errors1h} tone={data.totals.errors1h ? 'red' : undefined} />
            <Stat label="Errors 24h" value={data.totals.errors24h} tone={data.totals.errors24h ? 'red' : undefined} />
            <Stat label="Warn 1h" value={data.totals.warnings1h} tone={data.totals.warnings1h ? 'amber' : undefined} />
            <Stat label="Warn 24h" value={data.totals.warnings24h} tone={data.totals.warnings24h ? 'amber' : undefined} />
          </div>
        </div>

        <div className="mt-4 pt-3 border-t border-border flex flex-col md:flex-row md:items-center gap-2">
          <div className="relative flex-1">
            <Sparkles className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-primary" />
            <Input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') analyze(openIssues, 'All open issues') }}
              placeholder="Optional: ask the AI something specific about these logs…"
              className="pl-8 h-9 text-xs"
            />
          </div>
          <Button size="sm" className="h-9 text-xs font-bold" disabled={!!analyzing} onClick={() => analyze(openIssues, 'All open issues')}>
            {analyzing === 'All open issues' ? <RefreshCw className="w-3.5 h-3.5 mr-1.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5 mr-1.5" />}
            Ask AI about {openIssues.length} open issue{openIssues.length === 1 ? '' : 's'}
          </Button>
          <Button variant="outline" size="sm" className="h-9 text-xs font-bold" onClick={load} disabled={loading}>
            <RefreshCw className={cn('w-3.5 h-3.5 mr-1.5', loading && 'animate-spin')} />Rescan
          </Button>
        </div>
        <p className="mt-1.5 text-[10px] text-muted-foreground">
          Issues are classified by built-in rules, no AI involved. The AI is only called when you press an Ask AI button, and only open issues are sent (secrets redacted).
        </p>
      </Card>

      {/* AI analysis */}
      {analysis && (
        <Card className="p-4 bg-card border-primary/30 shadow-sm">
          <div className="flex items-start gap-3">
            <Sparkles className="h-5 w-5 text-primary mt-0.5 flex-shrink-0" />
            <div className="flex-1 min-w-0 space-y-3">
              <div className="flex items-center gap-2 flex-wrap">
                <h3 className="text-sm font-bold">AI diagnosis</h3>
                <span className="text-[10px] text-muted-foreground font-semibold">
                  {analysis.scope} · {analysis.provider}{analysis.model ? ` / ${analysis.model}` : ''}
                </span>
                {analysis.analysis.severity && (
                  <span className={cn('text-[10px] font-black uppercase px-2 py-0.5 rounded-full',
                    { critical: 'bg-red-500 text-white', high: 'bg-red-500/80 text-white', medium: 'bg-amber-500 text-black', low: 'bg-blue-500 text-white', ok: 'bg-emerald-500 text-white' }[analysis.analysis.severity] ?? 'bg-muted')}>
                    {analysis.analysis.severity}
                  </span>
                )}
                <button className="ml-auto text-[10px] text-muted-foreground hover:text-foreground font-semibold" onClick={() => setAnalysis(null)}>Dismiss</button>
              </div>
              <Markdown content={analysis.analysis.summary} className="text-sm text-foreground leading-relaxed break-words" />
              {analysis.analysis.findings.map((f, idx) => {
                const linked = (f.issueIds ?? []).map((id) => issueById.get(id)).filter((i): i is LogIssue => !!i)
                return (
                  <div key={idx} className="rounded-lg border border-border p-3 space-y-1.5 bg-muted/20">
                    <div className="flex items-center gap-2 flex-wrap">
                      {f.urgency && (
                        <span className={cn('text-[9px] font-black uppercase px-1.5 py-0.5 rounded', URGENCY_STYLE[f.urgency] ?? 'bg-muted')}>{f.urgency}</span>
                      )}
                      <span className="text-xs font-bold">{f.title}</span>
                      {linked.length > 0 && (
                        <span className="text-[10px] text-muted-foreground">{linked.reduce((n, i) => n + i.count, 0)} occurrences</span>
                      )}
                    </div>
                    {f.cause && <div className="text-xs text-muted-foreground"><span className="font-bold text-foreground">Cause</span><Markdown content={f.cause} className="leading-relaxed break-words" /></div>}
                    {f.fix && <div className="text-xs text-muted-foreground"><span className="font-bold text-foreground">Fix</span><Markdown content={f.fix} className="leading-relaxed break-words" /></div>}
                    {linked.length > 0 && (
                      <div className="flex gap-2 pt-1">
                        {f.urgency === 'noise' ? (
                          <Button variant="outline" size="sm" className="h-7 text-[10px] font-bold" onClick={() => setIssueState(linked.map((i) => i.signature), 'mute')}>
                            <BellOff className="w-3 h-3 mr-1" />Mute {linked.length === 1 ? 'this' : `these ${linked.length}`}
                          </Button>
                        ) : (
                          <Button variant="outline" size="sm" className="h-7 text-[10px] font-bold" onClick={() => setIssueState(linked.map((i) => i.signature), 'ack')}>
                            <Check className="w-3 h-3 mr-1" />Mark fixed
                          </Button>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        </Card>
      )}

      {/* Issues */}
      <Card className="p-0 bg-card border-border shadow-sm overflow-hidden">
        <div className="flex items-center gap-1 px-3 py-2 border-b border-border flex-wrap">
          <Activity className="h-4 w-4 text-primary mr-1" />
          <span className="text-xs font-bold mr-2">Issues · last 24h</span>
          {(['open', 'noise', 'resolved', 'all'] as IssueFilter[]).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={cn(
                'px-2.5 py-1 rounded-md text-[11px] font-semibold transition-colors',
                filter === f ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {FILTER_LABEL[f]} <span className="tabular-nums opacity-70">{counts[f]}</span>
            </button>
          ))}
        </div>

        {issues.length === 0 ? (
          <div className="py-10 text-center text-muted-foreground">
            <CheckCircle2 className="h-8 w-8 mx-auto mb-2 text-emerald-500" />
            <p className="text-sm font-semibold">{filter === 'open' ? 'Nothing needs attention — all clear.' : 'Nothing here.'}</p>
          </div>
        ) : (
          <div className="divide-y divide-border">
            {issues.map((issue) => {
              const open = expanded.has(issue.id)
              const err = isError(issue.level)
              return (
                <div key={issue.id} className={cn('px-3 py-2.5', (isResolved(issue) || issue.kind === 'noise') && 'opacity-60')}>
                  <div className="flex items-start gap-2">
                    <button onClick={() => toggle(issue.id)} className="mt-0.5 text-muted-foreground hover:text-foreground">
                      {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                    </button>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className={cn('text-[9px] font-black uppercase px-1.5 py-0.5 rounded', KIND_STYLE[issue.kind].cls)}>
                          {KIND_STYLE[issue.kind].label}
                        </span>
                        <span className={cn('text-[9px] font-bold uppercase', err ? 'text-red-500' : 'text-amber-500')}>{issue.level}</span>
                        <span className="text-[9px] font-bold uppercase text-muted-foreground">{issue.category.replace('-', ' ')}</span>
                        <span className="text-xs font-bold tabular-nums">×{issue.count}</span>
                        {issue.hint && <span className="text-xs font-bold text-foreground">{issue.hint.title}</span>}
                        {issue.newSinceAck > 0 && (
                          <span className="text-[9px] font-black uppercase px-1.5 py-0.5 rounded bg-red-500/15 text-red-500">
                            Recurred ×{issue.newSinceAck} after fix
                          </span>
                        )}
                        {issue.muted && <span className="text-[9px] font-bold uppercase text-muted-foreground">muted</span>}
                        {issue.acknowledged && <span className="text-[9px] font-bold uppercase text-emerald-500">fixed</span>}
                      </div>
                      <p className="font-mono text-[11px] text-foreground mt-1 break-words line-clamp-2">{issue.sample}</p>
                      <p className="text-[10px] text-muted-foreground mt-1">
                        last {ago(issue.lastSeen)} · first {ago(issue.firstSeen)}
                      </p>
                    </div>
                    <div className="hidden sm:flex flex-col items-end gap-1.5 flex-shrink-0">
                      <Sparkline hourly={issue.hourly} error={err} />
                      <div className="flex gap-1">
                        <Button variant="ghost" size="sm" className="h-6 px-2 text-[10px] font-bold" disabled={!!analyzing} onClick={() => analyze([issue], 'One issue')} title="Ask AI about this issue">
                          {analyzing === 'One issue' ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Sparkles className="w-3 h-3" />}
                        </Button>
                        {issue.muted || issue.acknowledged ? (
                          <Button variant="ghost" size="sm" className="h-6 px-2 text-[10px] font-bold" onClick={() => setIssueState([issue.signature], 'reopen')} title="Reopen">
                            <RotateCcw className="w-3 h-3" />
                          </Button>
                        ) : (
                          <>
                            <Button variant="ghost" size="sm" className="h-6 px-2 text-[10px] font-bold" onClick={() => setIssueState([issue.signature], 'ack')} title="Mark fixed — reappears if it happens again">
                              <Check className="w-3 h-3" />
                            </Button>
                            <Button variant="ghost" size="sm" className="h-6 px-2 text-[10px] font-bold" onClick={() => setIssueState([issue.signature], 'mute')} title="Mute — expected noise, never alert">
                              <BellOff className="w-3 h-3" />
                            </Button>
                          </>
                        )}
                      </div>
                    </div>
                  </div>

                  {open && (
                    <div className="ml-6 mt-2 space-y-2">
                      {issue.hint && (
                        <div className="rounded-md border border-primary/20 bg-primary/5 p-2.5 text-xs">
                          <span className="font-bold">Suggested fix: </span>{issue.hint.fix}
                          {issue.hint.href && (
                            <Link href={issue.hint.href} className="ml-2 inline-flex items-center gap-1 text-primary font-bold hover:underline">
                              Open <ExternalLink className="h-3 w-3" />
                            </Link>
                          )}
                        </div>
                      )}
                      {issue.samples.length > 1 && (
                        <div className="space-y-1">
                          <p className="text-[10px] font-bold uppercase text-muted-foreground">Variants</p>
                          {issue.samples.map((s, i) => <p key={i} className="font-mono text-[11px] break-words">{s}</p>)}
                        </div>
                      )}
                      {issue.details && (
                        <pre className="font-mono text-[10px] bg-muted/50 rounded p-2 overflow-x-auto max-h-64 whitespace-pre">{issue.details}</pre>
                      )}
                      <div className="flex gap-2 sm:hidden">
                        <Button variant="outline" size="sm" className="h-7 text-[10px]" onClick={() => analyze([issue], 'One issue')}><Sparkles className="w-3 h-3 mr-1" />Ask AI</Button>
                        {issue.muted || issue.acknowledged ? (
                          <Button variant="outline" size="sm" className="h-7 text-[10px]" onClick={() => setIssueState([issue.signature], 'reopen')}><RotateCcw className="w-3 h-3 mr-1" />Reopen</Button>
                        ) : (
                          <>
                            <Button variant="outline" size="sm" className="h-7 text-[10px]" onClick={() => setIssueState([issue.signature], 'ack')}><Check className="w-3 h-3 mr-1" />Fixed</Button>
                            <Button variant="outline" size="sm" className="h-7 text-[10px]" onClick={() => setIssueState([issue.signature], 'mute')}><BellOff className="w-3 h-3 mr-1" />Mute</Button>
                          </>
                        )}
                      </div>
                      <button
                        className="text-[11px] text-primary font-semibold hover:underline inline-flex items-center gap-1"
                        onClick={() => onShowInLogs(issue.sample.slice(0, 60))}
                      >
                        <Search className="h-3 w-3" />Show every occurrence in raw logs
                      </button>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </Card>

      {/* Storage / cleanup */}
      <Card className="p-4 bg-card border-border shadow-sm">
        <div className="flex flex-col md:flex-row md:items-center gap-3">
          <div className="flex-1">
            <p className="text-xs font-bold">Log storage</p>
            <p className="text-[11px] text-muted-foreground">
              {data.files.length} file{data.files.length === 1 ? '' : 's'} · {formatBytes(data.totalBytes)} · files older than 7 days are deleted automatically
            </p>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" className="h-8 text-xs font-bold" disabled={clearing || oldFiles <= 0} onClick={() => clearLogs('old')}>
              <Trash2 className="w-3.5 h-3.5 mr-1.5" />Delete old files{oldFiles > 0 ? ` (${oldFiles})` : ''}
            </Button>
            <Button variant="outline" size="sm" className="h-8 text-xs font-bold text-red-500 border-red-500/40 hover:bg-red-500/10" disabled={clearing || data.totalBytes === 0} onClick={() => clearLogs('all')}>
              <Trash2 className="w-3.5 h-3.5 mr-1.5" />Clear everything
            </Button>
          </div>
        </div>
      </Card>
    </div>
  )
}
