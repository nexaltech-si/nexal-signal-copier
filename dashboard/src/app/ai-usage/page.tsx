'use client'

import React, { useState, useEffect, useCallback, useMemo } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import MobilePageHeader from '@/components/MobilePageHeader'
import { cn } from '@/lib/utils'
import {
  RefreshCw,
  Cpu,
  DollarSign,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  ExternalLink,
  ChevronDown,
  ChevronUp,
  Loader2,
  TrendingUp,
  Zap,
  WifiOff,
  BarChart3,
  Trash2,
  Eye,
  MessageSquare,
  Brain,
  Layers,
  Activity,
} from 'lucide-react'

// ─── Provider API types ───────────────────────────────────────────────────────

interface ModelBreakdown {
  inputTokens: number
  outputTokens: number
  requests: number
  cost: number
}

interface ProviderResult {
  provider: string
  supported: boolean
  reason?: string
  error?: string | null
  totalCost: number
  totalInputTokens: number
  totalOutputTokens: number
  totalRequests: number
  byModel: Record<string, ModelBreakdown>
  balance?: number | null
  currency?: string
  grantedBalance?: number | null
  toppedUpBalance?: number | null
  isAvailable?: boolean
  creditLimit?: number | null
  isFreeTier?: boolean
}

interface ProviderApiData {
  startDate: string
  endDate: string
  totalCost: number
  providers: ProviderResult[]
}

// ─── Local tracking types ─────────────────────────────────────────────────────

interface FunctionStat {
  label: string
  calls: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cost_usd: number
  avg_tokens_per_call: number
  vision_calls: number
}

interface GroupStat {
  calls: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cost_usd: number
  avg_tokens_per_call: number
  vision_calls?: number
  provider?: string
}

interface RecentRecord {
  ts: string
  caller: string
  provider: string
  model: string
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cost_usd: number
  latency_ms?: number
  vision?: boolean
}

interface LocalUsageData {
  summary: {
    calls: number
    prompt_tokens: number
    completion_tokens: number
    total_tokens: number
    cost_usd: number
    vision_calls: number
  }
  by_function: Record<string, FunctionStat>
  by_provider: Record<string, GroupStat>
  by_model: Record<string, GroupStat & { provider: string }>
  recent: RecentRecord[]
  total_records: number
  caller_labels: Record<string, string>
}

// ─── Provider metadata ────────────────────────────────────────────────────────

const PROVIDER_META: Record<string, {
  label: string
  color: string
  bg: string
  ring: string
  dashboardUrl: string
}> = {
  openai:     { label: 'OpenAI',     color: 'text-emerald-600 dark:text-emerald-400', bg: 'bg-emerald-50 dark:bg-emerald-500/10',  ring: 'ring-emerald-200 dark:ring-emerald-500/20', dashboardUrl: 'https://platform.openai.com/usage' },
  openrouter: { label: 'OpenRouter', color: 'text-violet-700 dark:text-violet-400',  bg: 'bg-violet-50 dark:bg-violet-500/10',   ring: 'ring-violet-200 dark:ring-violet-500/20',  dashboardUrl: 'https://openrouter.ai/activity' },
  deepseek:   { label: 'DeepSeek',   color: 'text-blue-600 dark:text-blue-400',    bg: 'bg-blue-50 dark:bg-blue-500/10',     ring: 'ring-blue-200 dark:ring-blue-500/20',    dashboardUrl: 'https://platform.deepseek.com/usage' },
  gemini:     { label: 'Gemini',     color: 'text-amber-600 dark:text-amber-400',   bg: 'bg-amber-50 dark:bg-amber-500/10',    ring: 'ring-amber-200 dark:ring-amber-500/20',   dashboardUrl: 'https://aistudio.google.com/app/billing' },
  perplexity: { label: 'Perplexity', color: 'text-cyan-600 dark:text-cyan-400',    bg: 'bg-cyan-50 dark:bg-cyan-500/10',     ring: 'ring-cyan-200 dark:ring-cyan-500/20',    dashboardUrl: 'https://www.perplexity.ai/settings/api' },
  minimax:    { label: 'MiniMax',    color: 'text-rose-600 dark:text-rose-400',    bg: 'bg-rose-50 dark:bg-rose-500/10',     ring: 'ring-rose-200 dark:ring-rose-500/20',    dashboardUrl: '' },
  qwen:       { label: 'Qwen',       color: 'text-orange-600 dark:text-orange-400',  bg: 'bg-orange-50 dark:bg-orange-500/10',   ring: 'ring-orange-200 dark:ring-orange-500/20',  dashboardUrl: '' },
  hermes:     { label: 'Hermes',     color: 'text-purple-600 dark:text-purple-400',  bg: 'bg-purple-50 dark:bg-purple-500/10',   ring: 'ring-purple-200 dark:ring-purple-500/20',  dashboardUrl: '' },
  ollama:     { label: 'Ollama',     color: 'text-slate-600 dark:text-slate-300',   bg: 'bg-slate-50 dark:bg-slate-500/10',    ring: 'ring-slate-200 dark:ring-slate-500/20',   dashboardUrl: '' },
}

// ─── Caller icons ─────────────────────────────────────────────────────────────

const CALLER_ICONS: Record<string, React.ReactNode> = {
  classify_intent:    <MessageSquare className="h-3.5 w-3.5" />,
  signal_extraction:  <Zap className="h-3.5 w-3.5" />,
  vision_classify:    <Eye className="h-3.5 w-3.5" />,
  vision_extraction:  <Eye className="h-3.5 w-3.5" />,
  vision_manual:      <Eye className="h-3.5 w-3.5" />,
  trade_command:      <Layers className="h-3.5 w-3.5" />,
  brain_review:       <Brain className="h-3.5 w-3.5" />,
  brain_hermes:       <Brain className="h-3.5 w-3.5" />,
  market_analysis:    <BarChart3 className="h-3.5 w-3.5" />,
  rule_generation:    <Layers className="h-3.5 w-3.5" />,
  context_resolution: <MessageSquare className="h-3.5 w-3.5" />,
  tp_detection:       <CheckCircle2 className="h-3.5 w-3.5" />,
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const fmtCost = (n: number) => {
  if (n === 0) return '$0.00'
  if (n < 0.000001) return `$${n.toFixed(8)}`
  if (n < 0.001) return `$${n.toFixed(6)}`
  if (n < 1) return `$${n.toFixed(4)}`
  return `$${n.toFixed(2)}`
}

const fmtTokens = (n: number) =>
  n >= 1_000_000 ? `${(n / 1_000_000).toFixed(2)}M`
  : n >= 1_000   ? `${(n / 1_000).toFixed(1)}K`
  : String(n)

function today()        { return new Date().toISOString().slice(0, 10) }
function daysAgo(n: number) {
  const d = new Date(); d.setDate(d.getDate() - n)
  return d.toISOString().slice(0, 10)
}

const PRESETS = [
  { label: 'Today',   start: () => today(),     end: () => today() },
  { label: '7 days',  start: () => daysAgo(6),  end: () => today() },
  { label: '30 days', start: () => daysAgo(29), end: () => today() },
]

// ─── Stat tile ────────────────────────────────────────────────────────────────

function StatTile({ label, value, icon, bg, color }: {
  label: string; value: string; icon: React.ReactNode; bg: string; color: string
}) {
  return (
    <div className="rounded-2xl border border-border/50 bg-card shadow-sm p-4 flex items-center gap-3">
      <div className={cn('w-9 h-9 rounded-xl flex items-center justify-center shrink-0', bg)}>{icon}</div>
      <div className="min-w-0">
        <p className="text-[9px] font-bold text-muted-foreground/70 uppercase tracking-wider">{label}</p>
        <p className={cn('text-[16px] font-black leading-tight mt-0.5 truncate', color)}>{value}</p>
      </div>
    </div>
  )
}

// ─── Cost bar ─────────────────────────────────────────────────────────────────

function CostBar({ value, max, color }: { value: number; max: number; color: string }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0
  return (
    <div className="h-1 bg-muted/60 rounded-full overflow-hidden mt-1">
      <div className={cn('h-full rounded-full transition-all', color)} style={{ width: `${pct}%` }} />
    </div>
  )
}

// ─── Provider card (enhanced with local data) ─────────────────────────────────

function ProviderCard({
  p,
  localStat,
  provider,
}: {
  p: ProviderResult | null
  localStat: GroupStat | null
  provider: string
}) {
  const [expanded, setExpanded] = useState(false)
  const prov = provider || p?.provider || ''
  const fallbackLabel = prov ? prov.charAt(0).toUpperCase() + prov.slice(1) : 'Unknown'
  const meta = PROVIDER_META[prov] ?? { label: fallbackLabel, color: 'text-foreground/80', bg: 'bg-muted/50', ring: 'ring-border', dashboardUrl: '' }
  const modelEntries = p ? Object.entries(p.byModel).sort((a, b) => b[1].cost - a[1].cost) : []

  const hasApiData = p?.supported && !p?.error && (p?.totalInputTokens > 0 || p?.totalCost > 0)
  const hasLocalData = localStat && localStat.calls > 0

  const statusIcon = !p?.supported
    ? <WifiOff className="h-3.5 w-3.5 text-muted-foreground/50" />
    : p?.error
    ? <XCircle className="h-3.5 w-3.5 text-destructive/70" />
    : <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />

  return (
    <Card className={cn('border shadow-sm rounded-2xl overflow-hidden bg-card ring-1', meta.ring)}>
      <CardHeader className={cn('py-3.5 px-5 border-b border-border/50', meta.bg)}>
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <div className={cn('w-7 h-7 rounded-lg flex items-center justify-center text-[11px] font-black ring-1', meta.bg, meta.color, meta.ring)}>
              {meta.label.slice(0, 2).toUpperCase()}
            </div>
            <div>
              <CardTitle className="text-[13px] font-black text-foreground/90">{meta.label}</CardTitle>
              <div className="flex items-center gap-1 mt-0.5">
                {statusIcon}
                <span className="text-[10px] font-semibold text-muted-foreground/70">
                  {!p?.supported ? (p?.reason ?? 'No usage API') : p?.error ? p.error : 'Connected'}
                </span>
              </div>
            </div>
          </div>
          {meta.dashboardUrl && (
            <a href={meta.dashboardUrl} target="_blank" rel="noopener noreferrer"
              className="text-[10px] font-bold text-muted-foreground/50 hover:text-foreground/80 flex items-center gap-0.5 transition-colors">
              Dashboard <ExternalLink className="h-2.5 w-2.5" />
            </a>
          )}
        </div>
      </CardHeader>

      <CardContent className="p-4 space-y-3">

        {/* API cost / balance */}
        {hasApiData ? (
          <div className="grid grid-cols-2 gap-2">
            {p!.totalCost > 0 && (
              <div className="rounded-xl bg-muted/50 border border-border/50 p-2.5">
                <p className="text-[9px] font-bold text-muted-foreground/60 uppercase tracking-wider mb-0.5">API Cost</p>
                <p className={cn('text-base font-black', meta.color)}>{fmtCost(p!.totalCost)}</p>
              </div>
            )}
            {p!.balance !== null && p!.balance !== undefined && (
              <div className={cn('rounded-xl border p-2.5', (p!.balance ?? 0) < 1 ? 'bg-red-50 border-red-100 dark:bg-red-500/10 dark:border-red-500/20' : 'bg-muted/50 border-border/50')}>
                <p className="text-[9px] font-bold text-muted-foreground/60 uppercase tracking-wider mb-0.5">Balance</p>
                <p className={cn('text-base font-black', (p!.balance ?? 0) < 1 ? 'text-destructive' : meta.color)}>
                  {p!.currency && p!.currency !== 'USD' ? `${p!.currency} ` : '$'}{Number(p!.balance ?? 0).toFixed(2)}
                </p>
                {(p!.balance ?? 0) < 1 && (
                  <p className="text-[9px] text-destructive font-bold mt-0.5 flex items-center gap-0.5">
                    <AlertTriangle className="h-2.5 w-2.5" /> Low balance
                  </p>
                )}
              </div>
            )}
          </div>
        ) : p?.error ? (
          <div className="rounded-xl bg-red-50 border border-red-100 dark:bg-red-500/10 dark:border-red-500/20 p-2.5">
            <p className="text-[11px] text-destructive font-medium">{p.error}</p>
          </div>
        ) : null}

        {/* Token stats from API */}
        {hasApiData && (p!.totalInputTokens > 0 || p!.totalOutputTokens > 0) && (
          <div className="grid grid-cols-3 gap-1.5 text-center">
            {[
              { label: 'Requests', value: p!.totalRequests.toLocaleString() },
              { label: 'Input',    value: fmtTokens(p!.totalInputTokens) },
              { label: 'Output',   value: fmtTokens(p!.totalOutputTokens) },
            ].map(s => (
              <div key={s.label} className="rounded-lg bg-muted/40 border border-border/40 py-1.5">
                <p className="text-[8px] font-bold text-muted-foreground/60 uppercase tracking-wider">{s.label}</p>
                <p className="text-[12px] font-black text-foreground/70 mt-0.5">{s.value}</p>
              </div>
            ))}
          </div>
        )}

        {/* OpenRouter credit bar */}
        {prov === 'openrouter' && p?.creditLimit !== null && p?.creditLimit !== undefined && (
          <div className="space-y-1">
            <div className="flex justify-between text-[9px] font-semibold text-muted-foreground/70">
              <span>Credits used</span>
              <span>{fmtCost(p.totalCost)} / {p.creditLimit ? fmtCost(p.creditLimit) : '∞'}</span>
            </div>
            {p.creditLimit && (
              <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                <div className={cn('h-full rounded-full', meta.color.replace('text-', 'bg-'))}
                  style={{ width: `${Math.min(100, (p.totalCost / p.creditLimit) * 100)}%` }} />
              </div>
            )}
            {p.isFreeTier && <Badge className="text-[9px] bg-violet-50 text-violet-700 border-violet-100 dark:bg-violet-500/10 dark:text-violet-400 dark:border-violet-500/20">Free Tier</Badge>}
          </div>
        )}

        {/* DeepSeek balance breakdown */}
        {prov === 'deepseek' && p?.grantedBalance !== null && p?.grantedBalance !== undefined && (
          <div className="grid grid-cols-2 gap-1.5 text-center text-[9px]">
            <div className="rounded-lg bg-muted/40 border border-border/40 p-2">
              <p className="text-muted-foreground/60 font-bold uppercase tracking-wide">Granted</p>
              <p className="font-black text-foreground/70 mt-0.5">{p.currency} {Number(p.grantedBalance ?? 0).toFixed(4)}</p>
            </div>
            <div className="rounded-lg bg-muted/40 border border-border/40 p-2">
              <p className="text-muted-foreground/60 font-bold uppercase tracking-wide">Topped Up</p>
              <p className="font-black text-foreground/70 mt-0.5">{p.currency} {Number(p.toppedUpBalance ?? 0).toFixed(4)}</p>
            </div>
          </div>
        )}

        {/* Local tracking data (for providers with no API or to supplement) */}
        {hasLocalData && (
          <div className={cn('rounded-xl border p-3 space-y-1.5', hasApiData ? 'bg-muted/30 border-border/40' : 'bg-muted/50 border-border/50')}>
            <p className="text-[9px] font-black text-muted-foreground/60 uppercase tracking-wider flex items-center gap-1">
              <Activity className="h-2.5 w-2.5" />
              {hasApiData ? 'Bot-tracked usage' : 'Local bot tracking'}
            </p>
            <div className="grid grid-cols-3 gap-1.5 text-center">
              {[
                { label: 'Calls',   value: localStat!.calls.toLocaleString() },
                { label: 'Input',   value: fmtTokens(localStat!.prompt_tokens) },
                { label: 'Output',  value: fmtTokens(localStat!.completion_tokens) },
              ].map(s => (
                <div key={s.label}>
                  <p className="text-[8px] font-bold text-muted-foreground/50 uppercase">{s.label}</p>
                  <p className="text-[12px] font-black text-foreground/70">{s.value}</p>
                </div>
              ))}
            </div>
            <p className={cn('text-[13px] font-black', meta.color)}>{fmtCost(localStat!.cost_usd)}</p>
          </div>
        )}

        {/* No data at all */}
        {!hasApiData && !hasLocalData && (
          <div className="rounded-xl bg-muted/40 border border-border/40 p-3 text-center">
            <p className="text-[11px] text-muted-foreground/60 font-medium">
              {!p?.supported ? (p?.reason ?? 'No usage API') : 'No usage data for this period'}
            </p>
            {meta.dashboardUrl && !p?.supported && (
              <a href={meta.dashboardUrl} target="_blank" rel="noopener noreferrer"
                className="text-[10px] font-bold text-primary hover:underline mt-1 flex items-center justify-center gap-1">
                View in dashboard <ExternalLink className="h-2.5 w-2.5" />
              </a>
            )}
          </div>
        )}

        {/* Model breakdown (API data) */}
        {modelEntries.length > 0 && (
          <div>
            <button onClick={() => setExpanded(v => !v)}
              className="flex items-center gap-1.5 text-[10px] font-bold text-muted-foreground/60 hover:text-foreground/80 transition-colors">
              {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
              {modelEntries.length} model{modelEntries.length > 1 ? 's' : ''}
            </button>
            {expanded && (
              <div className="mt-2 space-y-1.5 animate-in fade-in duration-200">
                {modelEntries.map(([model, stats]) => (
                  <div key={model} className="flex items-center justify-between gap-2 py-1.5 border-b border-border/40 last:border-0">
                    <div className="min-w-0">
                      <p className="text-[11px] font-bold text-foreground/80 truncate">{model}</p>
                      <p className="text-[9px] text-muted-foreground/60 font-medium">
                        {stats.requests} req · {fmtTokens(stats.inputTokens)} in · {fmtTokens(stats.outputTokens)} out
                      </p>
                    </div>
                    <p className={cn('text-[12px] font-black shrink-0', meta.color)}>{fmtCost(stats.cost)}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ─── Function breakdown row ────────────────────────────────────────────────────

function FunctionRow({ id, stat, maxCost }: { id: string; stat: FunctionStat; maxCost: number }) {
  const icon = CALLER_ICONS[id] ?? <Cpu className="h-3.5 w-3.5" />
  const pct = maxCost > 0 ? (stat.cost_usd / maxCost) * 100 : 0

  return (
    <div className="flex items-center gap-3 px-4 py-3">
      <div className="w-7 h-7 rounded-lg bg-primary/10 flex items-center justify-center text-primary shrink-0">
        {icon}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2">
          <p className="text-[11px] font-bold text-foreground/80 truncate">{stat.label}</p>
          <p className="text-[12px] font-black text-emerald-600 dark:text-emerald-400 shrink-0">{fmtCost(stat.cost_usd)}</p>
        </div>
        <div className="h-1 bg-muted/60 rounded-full overflow-hidden mt-1.5">
          <div className="h-full bg-primary/40 rounded-full transition-all" style={{ width: `${pct}%` }} />
        </div>
        <p className="text-[9px] text-muted-foreground/50 font-medium mt-1">
          {stat.calls} calls · {fmtTokens(stat.prompt_tokens)} in · {fmtTokens(stat.completion_tokens)} out
          {stat.vision_calls > 0 && <span className="text-primary/60"> · {stat.vision_calls} vision</span>}
          {' · '}{fmtTokens(stat.avg_tokens_per_call)}/call
        </p>
      </div>
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export function AIUsageContent({ asTab = false }: { asTab?: boolean }) {
  const [providerData, setProviderData] = useState<ProviderApiData | null>(null)
  const [localData, setLocalData] = useState<LocalUsageData | null>(null)
  const [loading, setLoading] = useState(true)
  const [resetting, setResetting] = useState(false)
  const [presetIdx, setPresetIdx] = useState(0)
  const [customStart, setCustomStart] = useState(today())
  const [customEnd, setCustomEnd] = useState(today())
  const [useCustom, setUseCustom] = useState(false)
  const [showRecent, setShowRecent] = useState(false)

  const getRange = useCallback(() => {
    if (useCustom) return { start: customStart, end: customEnd }
    return { start: PRESETS[presetIdx].start(), end: PRESETS[presetIdx].end() }
  }, [presetIdx, useCustom, customStart, customEnd])

  const load = useCallback(async () => {
    setLoading(true)
    const { start, end } = getRange()
    try {
      const [provRes, localRes] = await Promise.allSettled([
        fetch(`/api/ai/usage?start=${start}&end=${end}`).then(r => r.json()),
        fetch(`/api/ai/local-usage?start=${start}&end=${end}`).then(r => r.json()),
      ])
      if (provRes.status === 'fulfilled') setProviderData(provRes.value)
      if (localRes.status === 'fulfilled' && !localRes.value.error) setLocalData(localRes.value)
    } finally {
      setLoading(false)
    }
  }, [getRange])

  useEffect(() => { load() }, [load])

  const handleReset = async () => {
    if (!confirm('Clear all local AI cost records? This cannot be undone.')) return
    setResetting(true)
    try {
      await fetch('/api/ai/local-usage/reset', { method: 'POST' })
      await load()
    } finally {
      setResetting(false)
    }
  }

  // All providers to show — every known provider from PROVIDER_META, unioned
  // with the API provider list + any local-only provider keys.
  const allProviders = useMemo(() => {
    const seen = new Set<string>()
    const list: string[] = []
    for (const k of Object.keys(PROVIDER_META)) { seen.add(k); list.push(k) }
    for (const p of providerData?.providers ?? []) {
      if (!seen.has(p.provider)) { seen.add(p.provider); list.push(p.provider) }
    }
    for (const k of Object.keys(localData?.by_provider ?? {})) {
      if (!seen.has(k)) { seen.add(k); list.push(k) }
    }
    return list
  }, [providerData, localData])

  const functionEntries = useMemo(() =>
    Object.entries(localData?.by_function ?? {}).sort((a, b) => b[1].cost_usd - a[1].cost_usd),
    [localData])

  const modelEntries = useMemo(() =>
    Object.entries(localData?.by_model ?? {}).sort((a, b) => b[1].cost_usd - a[1].cost_usd),
    [localData])

  const maxFunctionCost = functionEntries[0]?.[1]?.cost_usd ?? 0

  const totalLocal = localData?.summary
  const totalApiCost = providerData?.providers.reduce((s, p) => s + (p.totalCost ?? 0), 0) ?? 0

  return (
    <div className={asTab ? 'flex flex-col pb-10' : 'flex min-h-full flex-col pb-10'}>
      {!asTab && <MobilePageHeader title="AI Usage" subtitle="Cost & Token Tracking" hidden icon={<Cpu className="h-5 w-5 text-primary" />} />}

      {!asTab && (
        <header className="hidden md:flex sticky top-0 z-40 w-full tech-header">
          <div className="max-w-[1800px] w-full mx-auto flex h-14 items-center px-6 gap-3">
            <div className="p-1.5 rounded-lg bg-primary/10 border border-primary/20">
              <Cpu className="h-5 w-5 text-primary" />
            </div>
            <div className="flex flex-col flex-1">
              <h1 className="text-sm font-bold text-foreground leading-none">AI Usage</h1>
              <p className="text-[10px] text-[#6b7288] font-bold uppercase tracking-wider mt-1">Cost & Token Tracking</p>
            </div>
            <Button variant="outline" size="sm" onClick={load} disabled={loading} className="h-8 gap-1.5 text-xs font-bold">
              <RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
              Refresh
            </Button>
          </div>
        </header>
      )}

      <div className="flex-1 px-3 md:px-6 py-4 md:py-6 max-w-[1800px] mx-auto w-full space-y-6">

        {/* Date range + controls */}
        <div className="flex flex-wrap items-center gap-2">
          {PRESETS.map((preset, i) => (
            <button key={preset.label}
              onClick={() => { setPresetIdx(i); setUseCustom(false) }}
              className={cn(
                'px-3 py-1.5 rounded-full text-[11px] font-bold border transition-colors',
                !useCustom && presetIdx === i
                  ? 'bg-primary text-white border-primary'
                  : 'bg-card text-muted-foreground border-border hover:border-primary/40'
              )}>
              {preset.label}
            </button>
          ))}
          <div className="flex items-center gap-1.5 ml-1">
            <input type="date" value={customStart}
              onChange={e => { setCustomStart(e.target.value); setUseCustom(true) }}
              className="h-8 rounded-lg border border-border px-2 text-xs font-semibold text-foreground/80 bg-card focus:outline-none focus:ring-1 focus:ring-primary" />
            <span className="text-[11px] text-muted-foreground/60 font-bold">–</span>
            <input type="date" value={customEnd}
              onChange={e => { setCustomEnd(e.target.value); setUseCustom(true) }}
              className="h-8 rounded-lg border border-border px-2 text-xs font-semibold text-foreground/80 bg-card focus:outline-none focus:ring-1 focus:ring-primary" />
          </div>
        </div>

        {/* Loading */}
        {loading && (
          <div className="flex items-center justify-center py-20">
            <div className="flex flex-col items-center gap-3">
              <Loader2 className="h-7 w-7 animate-spin text-primary" />
              <p className="text-[11px] font-bold text-muted-foreground/60 uppercase tracking-wider">Fetching usage data…</p>
            </div>
          </div>
        )}

        {!loading && (
          <>
            {/* ── Summary bar ────────────────────────────────────────────────── */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <StatTile
                label="Bot Cost (local)"
                value={fmtCost(totalLocal?.cost_usd ?? 0)}
                icon={<DollarSign className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />}
                bg="bg-emerald-50 dark:bg-emerald-500/10" color="text-emerald-700 dark:text-emerald-400"
              />
              <StatTile
                label="Total Bot Calls"
                value={(totalLocal?.calls ?? 0).toLocaleString()}
                icon={<Zap className="h-4 w-4 text-primary" />}
                bg="bg-primary/10" color="text-primary"
              />
              <StatTile
                label="Input Tokens"
                value={fmtTokens(totalLocal?.prompt_tokens ?? 0)}
                icon={<TrendingUp className="h-4 w-4 text-muted-foreground" />}
                bg="bg-muted/60" color="text-foreground/80"
              />
              <StatTile
                label="Output Tokens"
                value={fmtTokens(totalLocal?.completion_tokens ?? 0)}
                icon={<TrendingUp className="h-4 w-4 text-amber-500 dark:text-amber-400" />}
                bg="bg-amber-50 dark:bg-amber-500/10" color="text-amber-700 dark:text-amber-400"
              />
            </div>

            {/* ── Function breakdown (local tracker) ─────────────────────────── */}
            <div>
              <div className="flex items-center justify-between mb-3">
                <div>
                  <h2 className="text-[11px] font-black text-muted-foreground/70 uppercase tracking-widest">Function Breakdown</h2>
                  <p className="text-[10px] text-muted-foreground/50 mt-0.5">Cost attributed per bot function — {localData?.total_records ?? 0} total records</p>
                </div>
                <div className="flex items-center gap-2">
                  <Button variant="ghost" size="sm" onClick={handleReset} disabled={resetting}
                    className="h-7 gap-1 text-[11px] font-bold text-destructive/60 hover:text-destructive px-2">
                    <Trash2 className="h-3 w-3" />
                    Reset
                  </Button>
                </div>
              </div>

              {functionEntries.length === 0 ? (
                <div className="rounded-2xl border border-border/50 bg-card p-8 text-center">
                  <Cpu className="h-8 w-8 text-muted-foreground/30 mx-auto mb-3" />
                  <p className="text-[13px] font-bold text-muted-foreground/60">No calls recorded yet</p>
                  <p className="text-[11px] text-muted-foreground/40 mt-1">Usage is tracked automatically as the bot processes signals and commands.</p>
                </div>
              ) : (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  {/* Function list */}
                  <Card className="rounded-2xl border shadow-sm">
                    <CardContent className="p-0">
                      <div className="divide-y divide-border/40">
                        {functionEntries.map(([id, stat]) => (
                          <FunctionRow key={id} id={id} stat={stat} maxCost={maxFunctionCost} />
                        ))}
                      </div>
                    </CardContent>
                  </Card>

                  {/* By model */}
                  <div className="space-y-4">
                    <Card className="rounded-2xl border shadow-sm">
                      <CardHeader className="py-3 px-4 border-b border-border/50">
                        <CardTitle className="text-[12px] font-black text-foreground/80">By Model</CardTitle>
                      </CardHeader>
                      <CardContent className="p-0">
                        <div className="divide-y divide-border/40">
                          {modelEntries.map(([model, stat]) => {
                            const meta = PROVIDER_META[stat.provider] ?? { color: 'text-foreground/80', bg: 'bg-muted/50', label: stat.provider }
                            return (
                              <div key={model} className="flex items-center gap-3 px-4 py-2.5">
                                <div className="flex-1 min-w-0">
                                  <p className="text-[11px] font-bold text-foreground/80 truncate">{model}</p>
                                  <p className="text-[9px] text-muted-foreground/50 font-medium">
                                    {stat.calls} calls · {meta.label ?? stat.provider} · {fmtTokens(stat.total_tokens)} tok
                                  </p>
                                </div>
                                <p className={cn('text-[12px] font-black shrink-0', meta.color)}>{fmtCost(stat.cost_usd)}</p>
                              </div>
                            )
                          })}
                        </div>
                      </CardContent>
                    </Card>

                    {/* Vision vs text split */}
                    {(totalLocal?.vision_calls ?? 0) > 0 && (
                      <Card className="rounded-2xl border shadow-sm">
                        <CardHeader className="py-3 px-4 border-b border-border/50">
                          <CardTitle className="text-[12px] font-black text-foreground/80">Vision vs Text</CardTitle>
                        </CardHeader>
                        <CardContent className="p-4 space-y-2">
                          {[
                            { label: 'Vision calls', value: totalLocal?.vision_calls ?? 0, total: totalLocal?.calls ?? 0, color: 'bg-primary/50' },
                            { label: 'Text calls',   value: (totalLocal?.calls ?? 0) - (totalLocal?.vision_calls ?? 0), total: totalLocal?.calls ?? 0, color: 'bg-amber-400/50' },
                          ].map(row => (
                            <div key={row.label}>
                              <div className="flex justify-between text-[10px] font-semibold text-muted-foreground/70 mb-1">
                                <span className="flex items-center gap-1">
                                  {row.label === 'Vision calls' && <Eye className="h-2.5 w-2.5" />}
                                  {row.label}
                                </span>
                                <span>{row.value.toLocaleString()} / {row.total.toLocaleString()}</span>
                              </div>
                              <div className="h-1.5 bg-muted/60 rounded-full overflow-hidden">
                                <div className={cn('h-full rounded-full', row.color)}
                                  style={{ width: `${row.total > 0 ? (row.value / row.total) * 100 : 0}%` }} />
                              </div>
                            </div>
                          ))}
                        </CardContent>
                      </Card>
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* ── Recent call log ─────────────────────────────────────────────── */}
            {(localData?.recent.length ?? 0) > 0 && (
              <div>
                <button onClick={() => setShowRecent(v => !v)}
                  className="flex items-center gap-1.5 text-[10px] font-bold text-muted-foreground/60 hover:text-foreground/80 transition-colors mb-2">
                  {showRecent ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                  Recent calls log — {localData!.total_records} total, showing last {localData!.recent.length}
                </button>
                {showRecent && (
                  <Card className="rounded-2xl border shadow-sm overflow-hidden">
                    <div className="overflow-x-auto">
                      <table className="w-full text-[10px]">
                        <thead className="bg-muted/40 border-b border-border/50">
                          <tr>
                            {['Time', 'Function', 'Provider', 'Model', 'In', 'Out', 'Cost', 'ms'].map(h => (
                              <th key={h} className="px-3 py-2 text-left font-black text-muted-foreground/60 uppercase tracking-wider whitespace-nowrap">{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-border/40">
                          {localData!.recent.map((r, i) => {
                            const meta = PROVIDER_META[r.provider]
                            return (
                              <tr key={i} className="hover:bg-muted/20 transition-colors">
                                <td className="px-3 py-1.5 text-muted-foreground/50 whitespace-nowrap">
                                  {new Date(r.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                                </td>
                                <td className="px-3 py-1.5 font-semibold text-foreground/70 whitespace-nowrap">
                                  <span className="flex items-center gap-1">
                                    {r.vision && <Eye className="h-2.5 w-2.5 text-primary/60" />}
                                    {localData!.caller_labels[r.caller] ?? r.caller}
                                  </span>
                                </td>
                                <td className={cn('px-3 py-1.5 font-bold', meta?.color ?? 'text-muted-foreground/60')}>{r.provider}</td>
                                <td className="px-3 py-1.5 text-muted-foreground/60 max-w-[120px] truncate">{r.model}</td>
                                <td className="px-3 py-1.5 text-muted-foreground/60">{fmtTokens(r.prompt_tokens)}</td>
                                <td className="px-3 py-1.5 text-muted-foreground/60">{fmtTokens(r.completion_tokens)}</td>
                                <td className="px-3 py-1.5 font-black text-emerald-600 dark:text-emerald-400">{fmtCost(r.cost_usd)}</td>
                                <td className="px-3 py-1.5 text-muted-foreground/40">{r.latency_ms ?? '—'}</td>
                              </tr>
                            )
                          })}
                        </tbody>
                      </table>
                    </div>
                  </Card>
                )}
              </div>
            )}

            {/* ── Provider cards ──────────────────────────────────────────────── */}
            <div>
              <div className="flex items-center justify-between mb-3">
                <div>
                  <h2 className="text-[11px] font-black text-muted-foreground/70 uppercase tracking-widest">Providers</h2>
                  <p className="text-[10px] text-muted-foreground/50 mt-0.5">
                    API data where available · local bot tracking fills in the rest
                    {totalApiCost > 0 && <span> · API total: {fmtCost(totalApiCost)}</span>}
                  </p>
                </div>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                {allProviders.map(prov => {
                  const apiEntry = providerData?.providers.find(p => p.provider === prov) ?? null
                  const localStat = localData?.by_provider[prov] ?? null
                  return (
                    <ProviderCard key={prov} p={apiEntry} localStat={localStat} provider={prov} />
                  )
                })}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

export default function AIUsagePage() {
  return <AIUsageContent />
}
