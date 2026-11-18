'use client'

import React, { useState, useEffect, useCallback, useMemo } from 'react'
import { cn, formatDate } from '@/lib/utils'
import {
  BookOpen, Search, TrendingUp, TrendingDown, ChevronDown, ChevronRight,
  X, Tag, MessageSquare, Loader2, AlertCircle, Brain, BarChart3, Trophy,
  Target, Filter, CheckCircle2, Circle, Percent, RefreshCw, EyeOff, Eye,
  Clock, Layers, Download, Calendar, Activity, Zap, ArrowRight,
} from 'lucide-react'
import TelegramText from '@/components/TelegramText'

// ─── Module-level client cache ─────────────────────────────────────────────────
const _cache = new Map<string, { data: unknown; ts: number }>()

async function cachedFetch<T>(url: string, ttlMs = 30_000): Promise<T> {
  const hit = _cache.get(url)
  if (hit && Date.now() - hit.ts < ttlMs) return hit.data as T
  const res = await fetch(url)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const data = await res.json()
  _cache.set(url, { data, ts: Date.now() })
  return data as T
}

function bustCache(urlPart: string) {
  for (const k of _cache.keys()) {
    if (k.includes(urlPart)) _cache.delete(k)
  }
}

// ─── Types ─────────────────────────────────────────────────────────────────────
type TradeAction = {
  id: string
  createdAt: string
  actionType: string
  success: boolean
  oldStopLoss?: number | null
  newStopLoss?: number | null
  oldTakeProfit?: number | null
  newTakeProfit?: number | null
  currentPrice?: number | null
  profitPips?: number | null
  triggeredBy: string
}

type TradeRaw = {
  id: string
  symbol: string
  action: string
  lotSize: number
  entryPrice: number | null
  stopLoss: number | null
  takeProfit: number | null
  closePrice: number | null
  profitLoss: number | null
  profitLossPips: number | null
  status: string
  createdAt: string
  executedAt: string | null
  closedAt: string | null
  magicNumber: number | null
  tpLevel: number | null
  isMultiTp: boolean
  tradeActions?: TradeAction[]
  signal: {
    channelName?: string | null
    rawMessage?: string | null
    riskRewardRatio?: number | null
    riskAmount?: number | null
    riskPercent?: number | null
  } | null
}

type JournalEntry = { notes: string; tags: string[] }

type TradeGroup = {
  groupKey: string
  magicNumber: number | null
  trades: TradeRaw[]
  symbol: string
  action: string
  primaryId: string
  entryPrice: number | null
  stopLoss: number | null
  status: string
  totalPnl: number | null
  totalPnlPips: number | null
  totalLots: number
  legCount: number
  createdAt: string
  executedAt: string | null
  closedAt: string | null
  channelName: string | null
  rawMessage: string | null
  riskRewardRatio: number | null
  riskAmount: number | null
  riskPercent: number | null
  allActions: TradeAction[]
}

type FilterTab = 'triggered' | 'all' | 'closed' | 'open' | 'tagged' | 'untagged'
type DatePreset = 'all' | '7d' | '30d' | '90d' | 'month'
type TagType = 'WIN' | 'LOSS' | 'BREAKEVEN' | 'SCALP' | 'NEWS' | 'FOMC' | 'TECHNICAL' | 'EMOTIONAL'

type Insight = {
  id: string
  type: 'tip' | 'warning' | 'success' | 'info'
  icon: string
  title: string
  body: string
}

// ─── Constants ─────────────────────────────────────────────────────────────────
const UNTRIGGERED = new Set(['PENDING', 'CANCELLED', 'FAILED'])

const ALL_TAGS: TagType[] = ['WIN', 'LOSS', 'BREAKEVEN', 'SCALP', 'NEWS', 'FOMC', 'TECHNICAL', 'EMOTIONAL']

const TAG_STYLE: Record<TagType, { pill: string; dot: string }> = {
  WIN:       { pill: 'bg-success/10 text-success border-emerald-200',        dot: 'bg-emerald-500' },
  LOSS:      { pill: 'bg-destructive/10 text-destructive border-rose-200',   dot: 'bg-rose-500' },
  BREAKEVEN: { pill: 'bg-amber-50 text-amber-700 border-amber-200',          dot: 'bg-amber-400' },
  SCALP:     { pill: 'bg-sky-50 text-sky-700 border-sky-200',                dot: 'bg-sky-500' },
  NEWS:      { pill: 'bg-violet-50 text-violet-700 border-violet-200',       dot: 'bg-violet-500' },
  FOMC:      { pill: 'bg-red-50 text-destructive border-red-200',            dot: 'bg-red-500' },
  TECHNICAL: { pill: 'bg-indigo-50 text-indigo-700 border-indigo-200',       dot: 'bg-indigo-500' },
  EMOTIONAL: { pill: 'bg-orange-50 text-orange-700 border-orange-200',       dot: 'bg-orange-400' },
}

const STATUS_PRIORITY: Record<string, number> = {
  EXECUTED: 6, OPEN: 6, EXECUTING: 5, CLOSED: 4, FAILED: 3, CANCELLED: 2, PENDING: 1,
}

const ACTION_TYPE_LABEL: Record<string, string> = {
  OPEN: 'Opened', CLOSE: 'Closed', MODIFY_SL: 'SL Modified', MODIFY_TP: 'TP Modified',
  PARTIAL_CLOSE: 'Partial Close', TRAILING_STOP: 'Trailing Stop', BREAKEVEN: 'Breakeven',
  AUTO_TP: 'Auto TP', AUTO_PARTIAL: 'Auto Partial',
}

// ─── Utilities ─────────────────────────────────────────────────────────────────
function formatPnl(val: number): string {
  const abs = Math.abs(val)
  const fmt = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 }).format(abs)
  return val >= 0 ? `+${fmt}` : `-${fmt}`
}

function formatPrice(val: number | null | undefined): string {
  if (val == null) return '—'
  return val > 100 ? val.toFixed(2) : val.toFixed(5)
}

function getOutcome(pnl: number | null): 'win' | 'loss' | 'breakeven' | null {
  if (pnl === null) return null
  if (pnl > 0.005) return 'win'
  if (pnl < -0.005) return 'loss'
  return 'breakeven'
}

function tradeDuration(g: TradeGroup): string | null {
  const start = g.executedAt || g.createdAt
  if (!g.closedAt) return null
  const ms = new Date(g.closedAt).getTime() - new Date(start).getTime()
  const h = Math.floor(ms / 3_600_000)
  const m = Math.floor((ms % 3_600_000) / 60_000)
  if (h >= 24) return `${Math.floor(h / 24)}d ${h % 24}h`
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

// BUG FIX: include symbol in key to prevent cross-symbol magic number merges
function mergeByMagicNumber(trades: TradeRaw[]): TradeGroup[] {
  const groups = new Map<string, TradeRaw[]>()
  for (const t of trades) {
    const key = t.magicNumber != null
      ? `m_${t.magicNumber}_${t.symbol}`   // symbol-scoped — prevents cross-symbol merges
      : `t_${t.id}`
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(t)
  }

  return Array.from(groups.entries()).map(([gk, ts]) => {
    const sorted = [...ts].sort((a, b) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime())
    const primary = sorted[0]

    const hasPnl = ts.some(t => t.profitLoss !== null)
    const totalPnl = hasPnl ? ts.reduce((s, t) => s + (t.profitLoss != null ? Number(t.profitLoss) : 0), 0) : null
    const hasPips = ts.some(t => t.profitLossPips !== null)
    const totalPnlPips = hasPips ? ts.reduce((s, t) => s + (t.profitLossPips != null ? Number(t.profitLossPips) : 0), 0) : null

    const status = ts.reduce((best, t) =>
      (STATUS_PRIORITY[t.status] || 0) > (STATUS_PRIORITY[best] || 0) ? t.status : best
    , primary.status)

    const executed = sorted.find(t => t.executedAt)
    const closedAt = ts.every(t => t.closedAt != null)
      ? ts.map(t => t.closedAt!).sort().at(-1) || null
      : null

    const allActions = ts.flatMap(t => t.tradeActions || [])
      .sort((a, b) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime())

    return {
      groupKey: gk,
      magicNumber: primary.magicNumber,
      trades: sorted,
      symbol: primary.symbol,
      action: primary.action,
      primaryId: primary.id,
      entryPrice: executed?.entryPrice ?? primary.entryPrice,
      stopLoss: primary.stopLoss,
      status,
      totalPnl,
      totalPnlPips,
      totalLots: ts.reduce((s, t) => s + t.lotSize, 0),
      legCount: ts.length,
      createdAt: primary.createdAt,
      executedAt: executed?.executedAt ?? null,
      closedAt,
      channelName: primary.signal?.channelName || null,
      rawMessage: primary.signal?.rawMessage || null,
      riskRewardRatio: primary.signal?.riskRewardRatio || null,
      riskAmount: primary.signal?.riskAmount || null,
      riskPercent: primary.signal?.riskPercent || null,
      allActions,
    }
  }).sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())
}

function groupByDate(groups: TradeGroup[]): { date: string; groups: TradeGroup[] }[] {
  const map = new Map<string, TradeGroup[]>()
  for (const g of groups) {
    const key = new Date(g.createdAt).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
    if (!map.has(key)) map.set(key, [])
    map.get(key)!.push(g)
  }
  return Array.from(map.entries()).map(([date, groups]) => ({ date, groups }))
}

function applyDatePreset(groups: TradeGroup[], preset: DatePreset): TradeGroup[] {
  if (preset === 'all') return groups
  const now = new Date()
  let from: Date
  if (preset === '7d') from = new Date(now.getTime() - 7 * 86_400_000)
  else if (preset === '30d') from = new Date(now.getTime() - 30 * 86_400_000)
  else if (preset === '90d') from = new Date(now.getTime() - 90 * 86_400_000)
  else from = new Date(now.getFullYear(), now.getMonth(), 1)
  return groups.filter(g => new Date(g.createdAt) >= from)
}

function exportCSV(groups: TradeGroup[], entries: Record<string, JournalEntry>) {
  const hdr = ['Date', 'Symbol', 'Action', 'Status', 'Entry', 'SL', 'Lots', 'P&L USD', 'P&L Pips', 'R:R', 'Risk %', 'Duration', 'Tags', 'Notes']
  const rows = groups.map(g => [
    new Date(g.createdAt).toLocaleDateString(),
    g.symbol, g.action, g.status,
    formatPrice(g.entryPrice), formatPrice(g.stopLoss),
    g.totalLots.toFixed(2),
    g.totalPnl?.toFixed(2) || '',
    g.totalPnlPips?.toFixed(1) || '',
    g.riskRewardRatio ? g.riskRewardRatio.toFixed(2) : '',
    g.riskPercent ? g.riskPercent.toFixed(1) + '%' : '',
    tradeDuration(g) || '',
    (entries[g.primaryId]?.tags || []).join('; '),
    entries[g.primaryId]?.notes || '',
  ])
  const csv = [hdr, ...rows].map(r => r.map(c => `"${String(c ?? '').replace(/"/g, '""')}"`).join(',')).join('\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = `trade-journal-${new Date().toISOString().slice(0, 10)}.csv`; a.click()
  URL.revokeObjectURL(url)
}

// ─── AI Insight engine ─────────────────────────────────────────────────────────
function computeInsights(triggered: TradeGroup[], entries: Record<string, JournalEntry>): Insight[] {
  const insights: Insight[] = []
  const withPnl = triggered.filter(g => g.totalPnl !== null && Math.abs(g.totalPnl!) > 0.005)
  if (withPnl.length < 3) return []

  const wins = withPnl.filter(g => g.totalPnl! > 0)
  const winRate = wins.length / withPnl.length

  if (winRate >= 0.65) {
    insights.push({ id: 'wr_hi', type: 'success', icon: '🏆', title: `${Math.round(winRate * 100)}% Win Rate`, body: `${wins.length}W / ${withPnl.length - wins.length}L — strong performance across ${withPnl.length} trades.` })
  } else if (winRate < 0.40 && withPnl.length >= 5) {
    insights.push({ id: 'wr_lo', type: 'warning', icon: '⚠️', title: `${Math.round(winRate * 100)}% Win Rate`, body: 'Below 40% — review entry criteria and risk-reward ratio.' })
  }

  // Tag correlation: show best/worst setup by tag win rate
  const tagStats = new Map<string, { w: number; n: number }>()
  for (const g of withPnl) {
    const e = entries[g.primaryId]
    for (const tag of (e?.tags || [])) {
      const s = tagStats.get(tag) || { w: 0, n: 0 }
      s.n++
      if (g.totalPnl! > 0) s.w++
      tagStats.set(tag, s)
    }
  }
  const qualified = [...tagStats.entries()].filter(([, v]) => v.n >= 3)
  if (qualified.length >= 2) {
    const sorted = qualified.sort(([, a], [, b]) => b.w / b.n - a.w / a.n)
    const [bestTag, bestData] = sorted[0]
    const [worstTag, worstData] = sorted.at(-1)!
    const bestWr = Math.round(bestData.w / bestData.n * 100)
    const worstWr = Math.round(worstData.w / worstData.n * 100)
    if (bestWr >= 60 && bestTag !== worstTag) {
      insights.push({ id: 'tag_best', type: 'tip', icon: '⚡', title: `Best: ${bestTag} (${bestWr}% WR)`, body: `Your ${bestTag} trades win ${bestWr}% vs ${worstTag} at ${worstWr}%. Double down on your edge.` })
    }
  } else {
    // Fall back to symbol analysis
    const symMap = new Map<string, { w: number; n: number }>()
    for (const g of withPnl) {
      const s = symMap.get(g.symbol) || { w: 0, n: 0 }
      s.n++; if (g.totalPnl! > 0) s.w++
      symMap.set(g.symbol, s)
    }
    const q = [...symMap.entries()].filter(([, v]) => v.n >= 3)
    if (q.length > 0) {
      const [sym, d] = q.sort(([, a], [, b]) => b.w / b.n - a.w / a.n)[0]
      const wr = Math.round(d.w / d.n * 100)
      if (wr >= 60) insights.push({ id: 'best_sym', type: 'tip', icon: '⚡', title: `Best: ${sym} (${wr}% WR)`, body: `${wr}% win rate on ${sym} across ${d.n} trades — your edge pair.` })
    }
  }

  // Trend: recent 5 vs previous 5
  if (withPnl.length >= 10) {
    const r5 = withPnl.slice(0, 5).filter(g => g.totalPnl! > 0).length / 5
    const p5 = withPnl.slice(5, 10).filter(g => g.totalPnl! > 0).length / 5
    const diff = r5 - p5
    if (diff >= 0.2) {
      insights.push({ id: 'trend_up', type: 'success', icon: '📈', title: 'Improving Form', body: `Recent 5-trade WR is ${Math.round(diff * 100)}pp higher than the previous 5.` })
    } else if (diff <= -0.2) {
      insights.push({ id: 'trend_dn', type: 'warning', icon: '📉', title: 'Declining Form', body: `WR down ${Math.round(Math.abs(diff) * 100)}pp vs previous 5 trades. Review setups.` })
    }
  }

  // Streak
  let streak = 0, sType: 'win' | 'loss' | null = null
  for (const g of withPnl) {
    const isW = g.totalPnl! > 0
    if (sType === null) { sType = isW ? 'win' : 'loss'; streak = 1 }
    else if ((sType === 'win') === isW) streak++
    else break
  }
  if (streak >= 3 && sType === 'loss') {
    insights.push({ id: 'streak_l', type: 'warning', icon: '🔴', title: `${streak}-Trade Loss Streak`, body: 'Consider reducing size or pausing to reset mentally.' })
  } else if (streak >= 3 && sType === 'win') {
    insights.push({ id: 'streak_w', type: 'success', icon: '🔥', title: `${streak}-Trade Win Streak`, body: 'Stay disciplined — stick to the plan that is working.' })
  }

  // Journal habit
  const journaled = triggered.filter(g => {
    const e = entries[g.primaryId]
    return e && ((e.notes?.trim().length ?? 0) > 0 || (e.tags?.length ?? 0) > 0)
  }).length
  const jPct = triggered.length > 0 ? journaled / triggered.length : 0
  if (jPct < 0.3 && triggered.length >= 5) {
    insights.push({ id: 'j_low', type: 'info', icon: '📓', title: 'Journal More Trades', body: `Only ${Math.round(jPct * 100)}% annotated. Notes accelerate pattern recognition.` })
  } else if (jPct >= 0.8 && triggered.length >= 5) {
    insights.push({ id: 'j_hi', type: 'success', icon: '✅', title: 'Excellent Journaling', body: `${Math.round(jPct * 100)}% of trades annotated — consistency that compounds.` })
  }

  return insights.slice(0, 4)
}

// ─── TagPill ───────────────────────────────────────────────────────────────────
function TagPill({ tag, onRemove, small }: { tag: string; onRemove?: () => void; small?: boolean }) {
  const s = TAG_STYLE[tag as TagType] || { pill: 'bg-muted text-muted-foreground border-border', dot: 'bg-muted' }
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-full border font-semibold', small ? 'text-[10px] px-2 h-5' : 'text-xs px-2.5 py-0.5', s.pill)}>
      <span className={cn('w-1.5 h-1.5 rounded-full flex-shrink-0', s.dot)} />
      {tag}
      {onRemove && (
        <button onClick={e => { e.stopPropagation(); onRemove() }} className="ml-0.5 hover:opacity-60">
          <X className="h-2.5 w-2.5" />
        </button>
      )}
    </span>
  )
}

// ─── Status badge ──────────────────────────────────────────────────────────────
function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    EXECUTED: 'text-primary bg-primary/10 border-[#c5d3ff]',
    OPEN:     'text-primary bg-primary/10 border-[#c5d3ff]',
    EXECUTING:'text-amber-700 bg-amber-50 border-amber-200',
    CLOSED:   'text-muted-foreground bg-muted/50 border-border',
    CANCELLED:'text-muted-foreground/60 bg-muted/30 border-border',
    FAILED:   'text-destructive bg-destructive/10 border-rose-200',
    PENDING:  'text-muted-foreground/60 bg-muted/30 border-border',
  }
  return (
    <span className={cn('text-[10px] font-bold px-1.5 py-0.5 rounded-md border uppercase tracking-wide', styles[status] || styles.PENDING)}>
      {status === 'EXECUTED' ? 'OPEN' : status}
    </span>
  )
}

// ─── Multi-leg table ───────────────────────────────────────────────────────────
function LegsTable({ trades }: { trades: TradeRaw[] }) {
  return (
    <div className="rounded-lg border border-border/60 overflow-hidden">
      <div className="bg-muted/40 px-3 py-1.5 flex items-center gap-1.5">
        <Layers className="h-3 w-3 text-muted-foreground/70" />
        <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground/70">{trades.length} Legs</span>
      </div>
      <div className="divide-y divide-border/40">
        {trades.map((t, i) => {
          const pnl = t.profitLoss !== null ? Number(t.profitLoss) : null
          const hasPnl = pnl !== null && Math.abs(pnl) > 0.005
          return (
            <div key={t.id} className="flex items-center gap-3 px-3 py-2 text-[11px]">
              <span className="text-muted-foreground/50 w-8 flex-shrink-0 font-mono">TP{t.tpLevel ?? i + 1}</span>
              <span className="font-mono text-foreground/80 flex-1">{formatPrice(t.entryPrice)}</span>
              <span className="text-muted-foreground/70 tabular-nums">{t.lotSize.toFixed(2)}L</span>
              <StatusBadge status={t.status} />
              {hasPnl && (
                <span className={cn('font-bold tabular-nums ml-auto', pnl! >= 0 ? 'text-[#16b36a]' : 'text-[#df1414]')}>
                  {formatPnl(pnl!)}
                </span>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ─── Trade actions timeline ────────────────────────────────────────────────────
function ActionsTimeline({ actions }: { actions: TradeAction[] }) {
  if (actions.length === 0) return null
  return (
    <div className="rounded-lg border border-border/60 overflow-hidden">
      <div className="bg-muted/40 px-3 py-1.5 flex items-center gap-1.5">
        <Activity className="h-3 w-3 text-muted-foreground/70" />
        <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground/70">Trade Timeline</span>
      </div>
      <div className="divide-y divide-border/40 max-h-48 overflow-y-auto">
        {actions.map(a => (
          <div key={a.id} className="flex items-start gap-3 px-3 py-2">
            <span className="text-[10px] text-muted-foreground/50 font-mono flex-shrink-0 pt-0.5 w-10">
              {new Date(a.createdAt).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}
            </span>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5">
                <span className={cn('text-[10px] font-bold', a.success ? 'text-foreground/80' : 'text-destructive/80')}>
                  {ACTION_TYPE_LABEL[a.actionType] || a.actionType}
                </span>
                {!a.success && <span className="text-[9px] text-destructive/70">(failed)</span>}
              </div>
              {(a.oldStopLoss != null || a.newStopLoss != null) && (
                <div className="text-[10px] text-muted-foreground/60 font-mono flex items-center gap-1 mt-0.5">
                  SL: {formatPrice(a.oldStopLoss)}
                  <ArrowRight className="h-2.5 w-2.5" />
                  {formatPrice(a.newStopLoss)}
                </div>
              )}
              {(a.oldTakeProfit != null || a.newTakeProfit != null) && (
                <div className="text-[10px] text-muted-foreground/60 font-mono flex items-center gap-1 mt-0.5">
                  TP: {formatPrice(a.oldTakeProfit)}
                  <ArrowRight className="h-2.5 w-2.5" />
                  {formatPrice(a.newTakeProfit)}
                </div>
              )}
              {a.profitPips != null && (
                <span className="text-[10px] text-muted-foreground/50">{a.profitPips >= 0 ? '+' : ''}{a.profitPips.toFixed(1)}p at close</span>
              )}
            </div>
            <span className="text-[9px] text-muted-foreground/40 flex-shrink-0">{a.triggeredBy}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Signal info panel ─────────────────────────────────────────────────────────
function SignalInfo({ group }: { group: TradeGroup }) {
  const hasRisk = group.riskRewardRatio != null || group.riskAmount != null || group.riskPercent != null
  const hasMsg = !!group.rawMessage
  if (!hasRisk && !hasMsg) return null

  return (
    <div className="rounded-lg border border-border/60 overflow-hidden">
      <div className="bg-muted/40 px-3 py-1.5 flex items-center gap-1.5">
        <Zap className="h-3 w-3 text-muted-foreground/70" />
        <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground/70">Signal Context</span>
      </div>
      <div className="px-3 py-2.5 space-y-2">
        {hasRisk && (
          <div className="flex items-center gap-4 text-[11px]">
            {group.riskRewardRatio != null && (
              <div>
                <span className="text-muted-foreground/60">R:R  </span>
                <span className="font-bold text-foreground/80">1:{group.riskRewardRatio.toFixed(2)}</span>
              </div>
            )}
            {group.riskAmount != null && (
              <div>
                <span className="text-muted-foreground/60">Risk  </span>
                <span className="font-bold text-foreground/80">${group.riskAmount.toFixed(2)}</span>
              </div>
            )}
            {group.riskPercent != null && (
              <div>
                <span className="text-muted-foreground/60">Risk%  </span>
                <span className="font-bold text-foreground/80">{group.riskPercent.toFixed(1)}%</span>
              </div>
            )}
          </div>
        )}
        {hasMsg && (
          <TelegramText text={group.rawMessage} className="text-[10px] leading-relaxed text-muted-foreground/70 bg-muted/30 rounded-md px-2.5 py-2 max-h-28 overflow-y-auto" />
        )}
      </div>
    </div>
  )
}

// ─── Trade group row ───────────────────────────────────────────────────────────
function TradeGroupRow({ group, journal, onSave, saving }: {
  group: TradeGroup
  journal: JournalEntry
  onSave: (id: string, data: { notes?: string; tags?: string[] }) => void
  saving: boolean
}) {
  const [expanded, setExpanded] = useState(false)
  const [notes, setNotes] = useState(journal.notes || '')
  const [tags, setTags] = useState<string[]>(journal.tags || [])
  const [dirty, setDirty] = useState(false)

  useEffect(() => { setNotes(journal.notes || ''); setTags(journal.tags || []); setDirty(false) }, [journal.notes, journal.tags])

  const toggleTag = (tag: string) => {
    setTags(p => p.includes(tag) ? p.filter(t => t !== tag) : [...p, tag])
    setDirty(true)
  }

  const isBuy = group.action?.toUpperCase().includes('BUY')
  const hasPnl = group.totalPnl !== null && Math.abs(group.totalPnl) > 0.005
  const outcome = getOutcome(group.totalPnl)
  const isActive = group.status === 'EXECUTED' || group.status === 'OPEN' || group.status === 'EXECUTING'
  const isUntriggered = UNTRIGGERED.has(group.status)
  const hasContent = (notes.trim().length > 0) || tags.length > 0
  const duration = tradeDuration(group)

  return (
    <div className={cn(
      'rounded-xl border bg-card transition-all duration-150',
      isUntriggered ? 'opacity-55' : '',
      expanded ? 'border-primary/30 shadow-md' : 'border-border shadow-sm hover:shadow-md hover:border-border'
    )}>
      {/* ── Summary row ── */}
      <button onClick={() => setExpanded(!expanded)} className="w-full flex items-center gap-3 px-4 py-3 text-left">
        <div className={cn('w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0',
          isUntriggered ? 'bg-muted/50' : isBuy ? 'bg-success/10' : 'bg-destructive/10')}>
          {isUntriggered
            ? <Clock className="h-4 w-4 text-muted-foreground/40" />
            : isBuy
              ? <TrendingUp className="h-4 w-4 text-success" />
              : <TrendingDown className="h-4 w-4 text-destructive" />
          }
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="font-bold text-sm text-foreground">{group.symbol}</span>
            <span className={cn('text-[10px] font-bold px-1.5 py-0.5 rounded uppercase tracking-wide',
              isBuy ? 'text-success bg-success/10' : 'text-destructive bg-destructive/10')}>
              {group.action}
            </span>
            <StatusBadge status={group.status} />
            {group.legCount > 1 && (
              <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-md border border-primary/20 bg-primary/8 text-primary flex items-center gap-0.5">
                <Layers className="h-2.5 w-2.5" />{group.legCount}TP
              </span>
            )}
          </div>
          <div className="flex items-center gap-1.5 mt-0.5 flex-wrap">
            <span className="text-[10px] text-muted-foreground/70">{formatDate(group.createdAt)}</span>
            {group.channelName && (
              <><span className="text-muted-foreground/40">·</span>
              <span className="text-[10px] text-[#697188]">{group.channelName}</span></>
            )}
            <span className="text-muted-foreground/40">·</span>
            <span className="text-[10px] text-muted-foreground/70 font-mono">{group.totalLots.toFixed(2)}L</span>
            {duration && (
              <><span className="text-muted-foreground/40">·</span>
              <span className="text-[10px] text-muted-foreground/60 flex items-center gap-0.5">
                <Clock className="h-2.5 w-2.5" />{duration}
              </span></>
            )}
          </div>
        </div>

        {/* Entry + SL */}
        {group.entryPrice != null && (
          <div className="hidden sm:flex flex-col items-end flex-shrink-0">
            <span className="text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/50">Entry</span>
            <span className="text-[11px] font-mono font-bold text-foreground/80">{formatPrice(group.entryPrice)}</span>
            {group.stopLoss != null && (
              <span className="text-[9px] font-mono text-destructive/70">SL {formatPrice(group.stopLoss)}</span>
            )}
          </div>
        )}

        {/* R:R badge */}
        {group.riskRewardRatio != null && (
          <div className="hidden lg:flex flex-col items-center flex-shrink-0">
            <span className="text-[9px] text-muted-foreground/50 uppercase tracking-wide">R:R</span>
            <span className="text-[11px] font-bold text-foreground/70">1:{group.riskRewardRatio.toFixed(1)}</span>
          </div>
        )}

        {/* Tags preview */}
        {tags.length > 0 && (
          <div className="hidden md:flex items-center gap-1 flex-shrink-0">
            {tags.slice(0, 2).map(t => <TagPill key={t} tag={t} small />)}
            {tags.length > 2 && <span className="text-[10px] text-muted-foreground/70">+{tags.length - 2}</span>}
          </div>
        )}

        {/* P&L */}
        <div className="text-right flex-shrink-0 min-w-[78px]">
          {hasPnl ? (
            <div>
              <span className={cn('font-bold text-sm tabular-nums', group.totalPnl! >= 0 ? 'text-[#16b36a]' : 'text-[#df1414]')}>
                {formatPnl(group.totalPnl!)}
              </span>
              {group.totalPnlPips !== null && (
                <div className="text-[9px] text-muted-foreground/70 tabular-nums">
                  {group.totalPnlPips >= 0 ? '+' : ''}{group.totalPnlPips.toFixed(1)}p
                </div>
              )}
            </div>
          ) : isActive ? (
            <span className="text-[10px] font-bold text-primary/70 animate-pulse">Live</span>
          ) : (
            <span className="text-muted-foreground/40 text-sm">—</span>
          )}
        </div>

        {/* Journal dot + chevron */}
        <div className="flex items-center gap-1.5 flex-shrink-0">
          {hasContent
            ? <CheckCircle2 className="h-3.5 w-3.5 text-success hidden sm:block" />
            : <Circle className="h-3.5 w-3.5 text-muted-foreground/40 hidden sm:block" />
          }
          {expanded
            ? <ChevronDown className="h-4 w-4 text-primary" />
            : <ChevronRight className="h-4 w-4 text-muted-foreground/50" />
          }
        </div>
      </button>

      {/* ── Expanded editor ── */}
      {expanded && (
        <div className="border-t border-border/50 px-4 py-4 space-y-4 bg-muted/20 rounded-b-xl">
          {/* Mobile: entry details */}
          {group.entryPrice != null && (
            <div className="flex sm:hidden items-center gap-4 text-[11px] font-mono bg-card rounded-lg px-3 py-2 border border-border/50">
              <div><span className="text-muted-foreground/60 text-[9px] uppercase block">Entry</span><span className="font-bold">{formatPrice(group.entryPrice)}</span></div>
              {group.stopLoss != null && <div><span className="text-muted-foreground/60 text-[9px] uppercase block">SL</span><span className="text-destructive">{formatPrice(group.stopLoss)}</span></div>}
              {group.riskRewardRatio != null && <div><span className="text-muted-foreground/60 text-[9px] uppercase block">R:R</span><span>1:{group.riskRewardRatio.toFixed(1)}</span></div>}
            </div>
          )}

          {/* Signal context */}
          <SignalInfo group={group} />

          {/* Multi-leg table */}
          {group.legCount > 1 && <LegsTable trades={group.trades} />}

          {/* Trade actions timeline */}
          {group.allActions.length > 0 && <ActionsTimeline actions={group.allActions} />}

          {/* Tags */}
          <div>
            <label className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60 mb-2">
              <Tag className="h-3 w-3" /> Tags
            </label>
            <div className="flex flex-wrap gap-1.5">
              {ALL_TAGS.map(tag => {
                const sel = tags.includes(tag)
                const s = TAG_STYLE[tag]
                return (
                  <button key={tag} onClick={() => toggleTag(tag)}
                    className={cn('inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-all',
                      sel ? s.pill : 'border-border text-muted-foreground/60 bg-card hover:border-border hover:text-muted-foreground')}>
                    {sel && <span className={cn('w-1.5 h-1.5 rounded-full', s.dot)} />}
                    {tag}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Notes */}
          <div>
            <label className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60 mb-2">
              <MessageSquare className="h-3 w-3" /> Notes
            </label>
            <textarea
              placeholder="What was your reasoning? What did you learn? Any emotions involved?"
              value={notes}
              onChange={e => { setNotes(e.target.value); setDirty(true) }}
              className="w-full text-sm rounded-lg border border-border bg-card px-3 py-2 resize-y min-h-[80px] outline-none transition-colors text-foreground/80 placeholder:text-muted-foreground/40 focus:border-primary focus:ring-1 focus:ring-primary/20"
            />
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between gap-3">
            {outcome && hasPnl && !tags.includes(outcome === 'win' ? 'WIN' : outcome === 'loss' ? 'LOSS' : 'BREAKEVEN') ? (
              <div className="flex items-center gap-2 text-[10px] rounded-lg bg-primary/8 border border-primary/15 text-[#697188] px-3 py-1.5">
                <Brain className="h-3 w-3 flex-shrink-0 text-primary" />
                <span>Add the{' '}
                  <button onClick={() => toggleTag(outcome === 'win' ? 'WIN' : outcome === 'loss' ? 'LOSS' : 'BREAKEVEN')}
                    className="font-bold text-primary hover:underline">
                    {outcome.toUpperCase()}
                  </button>{' '}tag?
                </span>
              </div>
            ) : <div />}

            <button
              onClick={() => { onSave(group.primaryId, { notes, tags }); setDirty(false) }}
              disabled={saving}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-xs font-semibold transition-all disabled:opacity-60',
                hasContent || dirty
                  ? 'bg-primary text-white hover:bg-primary/90 shadow-sm'
                  : 'bg-muted text-muted-foreground/60 hover:bg-border'
              )}
            >
              {saving ? <><Loader2 className="h-3 w-3 animate-spin" />Saving…</> : <><BookOpen className="h-3 w-3" />Save Entry</>}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── AI Insights panel ─────────────────────────────────────────────────────────
function InsightsPanel({ insights }: { insights: Insight[] }) {
  if (insights.length === 0) return null
  const bgMap = { tip: 'bg-primary/6 border-primary/20', warning: 'bg-amber-50 border-amber-200/70', success: 'bg-success/6 border-success/20', info: 'bg-sky-50 border-sky-200/70' }
  const textMap = { tip: 'text-[#697188]', warning: 'text-amber-800', success: 'text-success', info: 'text-sky-700' }
  return (
    <div className="rounded-xl border border-border bg-card shadow-sm p-4 space-y-2.5">
      <div className="flex items-center gap-2 pb-2 border-b border-border/50">
        <Brain className="h-3.5 w-3.5 text-primary" />
        <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground/70">AI Insights</span>
      </div>
      {insights.map(ins => (
        <div key={ins.id} className={cn('rounded-lg border px-3 py-2.5 flex gap-2.5', bgMap[ins.type])}>
          <span className="text-sm flex-shrink-0 mt-0.5 leading-none">{ins.icon}</span>
          <div className={cn('min-w-0', textMap[ins.type])}>
            <div className="text-[11px] font-bold leading-none mb-0.5">{ins.title}</div>
            <div className="text-[10px] leading-relaxed opacity-80">{ins.body}</div>
          </div>
        </div>
      ))}
    </div>
  )
}

// ─── Stats sidebar ─────────────────────────────────────────────────────────────
function StatsPanel({ groups, entries }: { groups: TradeGroup[]; entries: Record<string, JournalEntry> }) {
  const s = useMemo(() => {
    const triggered = groups.filter(g => !UNTRIGGERED.has(g.status))
    const withPnl = triggered.filter(g => g.totalPnl !== null && Math.abs(g.totalPnl!) > 0.005)
    const wins = withPnl.filter(g => g.totalPnl! > 0)
    const losses = withPnl.filter(g => g.totalPnl! < 0)
    const totalPnl = withPnl.reduce((s, g) => s + g.totalPnl!, 0)
    const grossProfit = wins.reduce((s, g) => s + g.totalPnl!, 0)
    const grossLoss = Math.abs(losses.reduce((s, g) => s + g.totalPnl!, 0))
    const profitFactor = grossLoss > 0 ? grossProfit / grossLoss : wins.length > 0 ? Infinity : null
    const avgWin = wins.length > 0 ? grossProfit / wins.length : null
    const avgLoss = losses.length > 0 ? grossLoss / losses.length : null
    const ev = avgWin !== null && avgLoss !== null && withPnl.length > 0
      ? (wins.length / withPnl.length) * avgWin - (losses.length / withPnl.length) * avgLoss
      : null
    const winRate = withPnl.length > 0 ? Math.round(wins.length / withPnl.length * 100) : null
    const best = withPnl.length > 0 ? Math.max(...withPnl.map(g => g.totalPnl!)) : null
    const worst = withPnl.length > 0 ? Math.min(...withPnl.map(g => g.totalPnl!)) : null

    const journaled = triggered.filter(g => {
      const e = entries[g.primaryId]
      return e && ((e.notes?.trim().length ?? 0) > 0 || (e.tags?.length ?? 0) > 0)
    }).length

    // Tag analytics: win rate per tag
    const tagStats = new Map<string, { w: number; n: number }>()
    for (const g of withPnl) {
      const e = entries[g.primaryId]
      for (const tag of (e?.tags || [])) {
        const st = tagStats.get(tag) || { w: 0, n: 0 }
        st.n++; if (g.totalPnl! > 0) st.w++
        tagStats.set(tag, st)
      }
    }
    // Also count from all entries for frequency
    const tagFreq: Record<string, number> = {}
    for (const e of Object.values(entries)) {
      for (const t of (e.tags || [])) tagFreq[t] = (tagFreq[t] || 0) + 1
    }
    const topTags = Object.entries(tagFreq)
      .sort(([, a], [, b]) => b - a)
      .slice(0, 6)
      .map(([tag, count]) => ({ tag, count, stats: tagStats.get(tag) }))

    return { wins: wins.length, losses: losses.length, withPnl: withPnl.length, totalPnl, profitFactor, avgWin, avgLoss, ev, winRate, best, worst, journaled, triggered: triggered.length, topTags }
  }, [groups, entries])

  const jPct = s.triggered > 0 ? Math.round((s.journaled / s.triggered) * 100) : 0

  const Row = ({ icon, label, value, color }: { icon: React.ReactNode; label: string; value: string; color?: string }) => (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-1.5">
        <span className="text-muted-foreground/60">{icon}</span>
        <span className="text-xs text-[#697188]">{label}</span>
      </div>
      <span className={cn('text-sm font-bold tabular-nums', color || 'text-foreground')}>{value}</span>
    </div>
  )

  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-border bg-card shadow-sm p-4 space-y-3">
        <div className="flex items-center gap-2 pb-2 border-b border-border/50">
          <BarChart3 className="h-3.5 w-3.5 text-primary" />
          <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground/70">Performance</span>
        </div>
        {s.winRate !== null && (
          <Row icon={<Trophy className="h-3.5 w-3.5" />} label="Win Rate"
            value={`${s.winRate}%`} color={s.winRate >= 50 ? 'text-[#16b36a]' : 'text-[#df1414]'} />
        )}
        {s.withPnl > 0 && (
          <Row icon={<Target className="h-3.5 w-3.5" />} label="Total P&L"
            value={formatPnl(s.totalPnl)} color={s.totalPnl >= 0 ? 'text-[#16b36a]' : 'text-[#df1414]'} />
        )}
        {s.profitFactor !== null && (
          <Row icon={<Activity className="h-3.5 w-3.5" />} label="Profit Factor"
            value={s.profitFactor === Infinity ? '∞' : s.profitFactor.toFixed(2)}
            color={s.profitFactor >= 1.5 ? 'text-[#16b36a]' : s.profitFactor < 1 ? 'text-[#df1414]' : 'text-foreground'} />
        )}
        {s.ev !== null && (
          <Row icon={<Zap className="h-3.5 w-3.5" />} label="Exp. Value"
            value={formatPnl(s.ev)} color={s.ev >= 0 ? 'text-[#16b36a]' : 'text-[#df1414]'} />
        )}
        {s.withPnl > 0 && (
          <div className="flex items-center justify-between">
            <span className="text-xs text-[#697188]">W / L record</span>
            <span className="text-xs font-bold">
              <span className="text-[#16b36a]">{s.wins}W</span>
              <span className="text-muted-foreground/50 mx-0.5">/</span>
              <span className="text-[#df1414]">{s.losses}L</span>
            </span>
          </div>
        )}
        {s.avgWin !== null && s.avgLoss !== null && (
          <div className="flex items-center justify-between">
            <span className="text-xs text-[#697188]">Avg W / L</span>
            <span className="text-xs font-bold">
              <span className="text-[#16b36a]">+${s.avgWin.toFixed(2)}</span>
              <span className="text-muted-foreground/50 mx-0.5">/</span>
              <span className="text-[#df1414]">-${s.avgLoss.toFixed(2)}</span>
            </span>
          </div>
        )}
        {s.best !== null && s.best > 0.005 && (
          <Row icon={<TrendingUp className="h-3.5 w-3.5" />} label="Best" value={formatPnl(s.best)} color="text-[#16b36a]" />
        )}
        {s.worst !== null && s.worst < -0.005 && (
          <Row icon={<TrendingDown className="h-3.5 w-3.5" />} label="Worst" value={formatPnl(s.worst)} color="text-[#df1414]" />
        )}
        {s.withPnl === 0 && (
          <p className="text-xs text-muted-foreground/60 text-center py-2">No closed trades yet</p>
        )}
      </div>

      {/* Journaling progress */}
      <div className="rounded-xl border border-border bg-card shadow-sm p-4 space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Percent className="h-3.5 w-3.5 text-primary" />
            <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground/70">Journaling</span>
          </div>
          <span className="text-xs font-bold text-foreground">
            {s.journaled}<span className="font-normal text-muted-foreground/60">/{s.triggered}</span>
          </span>
        </div>
        <div className="w-full h-1.5 rounded-full bg-muted overflow-hidden">
          <div className={cn('h-full rounded-full transition-all duration-500', jPct >= 70 ? 'bg-[#16b36a]' : 'bg-primary')}
            style={{ width: `${jPct}%` }} />
        </div>
        <p className="text-[10px] text-muted-foreground/60">{jPct}% of triggered trades annotated</p>
      </div>

      {/* Tag analytics with win rates */}
      {s.topTags.length > 0 && (
        <div className="rounded-xl border border-border bg-card shadow-sm p-4 space-y-2">
          <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground/70">Tag Analytics</span>
          <div className="space-y-1.5 mt-1">
            {s.topTags.map(({ tag, count, stats }) => {
              const wr = stats && stats.n >= 2 ? Math.round(stats.w / stats.n * 100) : null
              return (
                <div key={tag} className="flex items-center gap-2">
                  <TagPill tag={tag} small />
                  <span className="text-[10px] text-muted-foreground/60 ml-auto">×{count}</span>
                  {wr !== null && (
                    <span className={cn('text-[10px] font-bold tabular-nums w-8 text-right', wr >= 50 ? 'text-[#16b36a]' : 'text-[#df1414]')}>
                      {wr}%
                    </span>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Filter tabs ───────────────────────────────────────────────────────────────
function FilterTabs({ active, onChange, counts }: {
  active: FilterTab
  onChange: (f: FilterTab) => void
  counts: Record<FilterTab, number>
}) {
  const tabs: { id: FilterTab; label: string }[] = [
    { id: 'triggered', label: 'Triggered' },
    { id: 'all', label: 'All' },
    { id: 'closed', label: 'Closed' },
    { id: 'open', label: 'Open' },
    { id: 'tagged', label: 'Tagged' },
    { id: 'untagged', label: 'Untagged' },
  ]
  return (
    <div className="flex items-center gap-1 flex-wrap">
      {tabs.map(tab => (
        <button key={tab.id} onClick={() => onChange(tab.id)}
          className={cn('inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all',
            active === tab.id ? 'bg-primary text-white shadow-sm' : 'bg-muted text-[#697188] hover:bg-border')}>
          {tab.label}
          <span className={cn('text-[10px] font-bold rounded-full px-1.5', active === tab.id ? 'bg-white/25 text-white' : 'bg-card text-muted-foreground/60')}>
            {counts[tab.id]}
          </span>
        </button>
      ))}
    </div>
  )
}

// ─── Date preset filter ────────────────────────────────────────────────────────
function DatePresetPicker({ active, onChange }: { active: DatePreset; onChange: (p: DatePreset) => void }) {
  const presets: { id: DatePreset; label: string }[] = [
    { id: 'all', label: 'All time' },
    { id: '7d', label: '7d' },
    { id: '30d', label: '30d' },
    { id: '90d', label: '90d' },
    { id: 'month', label: 'This month' },
  ]
  return (
    <div className="flex items-center gap-1">
      <Calendar className="h-3.5 w-3.5 text-muted-foreground/60 flex-shrink-0" />
      {presets.map(p => (
        <button key={p.id} onClick={() => onChange(p.id)}
          className={cn('px-2.5 py-1 rounded-md text-xs font-semibold transition-all',
            active === p.id ? 'bg-primary/15 text-primary' : 'text-muted-foreground/60 hover:bg-muted')}>
          {p.label}
        </button>
      ))}
    </div>
  )
}

// ─── Main ──────────────────────────────────────────────────────────────────────
export default function TradeJournal({ limit = 500 }: { limit?: number }) {
  const [trades, setTrades] = useState<TradeRaw[]>([])
  const [entries, setEntries] = useState<Record<string, JournalEntry>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<FilterTab>('triggered')
  const [datePreset, setDatePreset] = useState<DatePreset>('all')
  const [showUntriggered, setShowUntriggered] = useState(false)
  const [savingId, setSavingId] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)

  const load = useCallback(async (forceRefresh = false) => {
    try {
      if (forceRefresh) { bustCache('/api/trades'); bustCache('/api/trade-journal'); setRefreshing(true) }
      else setLoading(true)
      const [t, e] = await Promise.all([
        cachedFetch<TradeRaw[]>(`/api/trades?limit=${limit}`, forceRefresh ? 0 : 30_000),
        cachedFetch<Record<string, JournalEntry>>('/api/trade-journal', forceRefresh ? 0 : 60_000),
      ])
      setTrades(t); setEntries(e); setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load')
    } finally {
      setLoading(false); setRefreshing(false)
    }
  }, [limit])

  useEffect(() => { load() }, [load])

  const allGroups = useMemo(() => mergeByMagicNumber(trades), [trades])

  const baseGroups = useMemo(() => {
    let r = showUntriggered ? allGroups : allGroups.filter(g => !g.trades.every(t => UNTRIGGERED.has(t.status)))
    return applyDatePreset(r, datePreset)
  }, [allGroups, showUntriggered, datePreset])

  const triggeredGroups = useMemo(() => baseGroups.filter(g => !UNTRIGGERED.has(g.status)), [baseGroups])

  const isJournaled = useCallback((g: TradeGroup) => {
    const e = entries[g.primaryId]
    return e && ((e.notes?.trim().length ?? 0) > 0 || (e.tags?.length ?? 0) > 0)
  }, [entries])

  const tabCounts = useMemo<Record<FilterTab, number>>(() => ({
    triggered: triggeredGroups.length,
    all: baseGroups.length,
    closed: baseGroups.filter(g => g.status === 'CLOSED').length,
    open: baseGroups.filter(g => g.status === 'EXECUTED' || g.status === 'OPEN' || g.status === 'EXECUTING').length,
    tagged: triggeredGroups.filter(g => isJournaled(g)).length,
    untagged: triggeredGroups.filter(g => !isJournaled(g)).length,
  }), [baseGroups, triggeredGroups, isJournaled])

  const filtered = useMemo(() => {
    let r = baseGroups
    if (filter === 'triggered') r = triggeredGroups
    else if (filter === 'closed') r = r.filter(g => g.status === 'CLOSED')
    else if (filter === 'open') r = r.filter(g => g.status === 'EXECUTED' || g.status === 'OPEN' || g.status === 'EXECUTING')
    else if (filter === 'tagged') r = triggeredGroups.filter(g => isJournaled(g))
    else if (filter === 'untagged') r = triggeredGroups.filter(g => !isJournaled(g))
    if (search.trim()) {
      const q = search.toLowerCase()
      r = r.filter(g =>
        g.symbol.toLowerCase().includes(q) ||
        g.action.toLowerCase().includes(q) ||
        (g.channelName?.toLowerCase().includes(q) ?? false) ||
        // search across journal notes and tags
        (entries[g.primaryId]?.notes?.toLowerCase().includes(q) ?? false) ||
        (entries[g.primaryId]?.tags?.some(t => t.toLowerCase().includes(q)) ?? false)
      )
    }
    return r
  }, [baseGroups, triggeredGroups, filter, search, isJournaled, entries])

  const dateGroups = useMemo(() => groupByDate(filtered), [filtered])
  const insights = useMemo(() => computeInsights(triggeredGroups, entries), [triggeredGroups, entries])
  const journaledCount = useMemo(() => triggeredGroups.filter(g => isJournaled(g)).length, [triggeredGroups, isJournaled])

  const handleSave = useCallback(async (tradeId: string, data: { notes?: string; tags?: string[] }) => {
    setSavingId(tradeId)
    try {
      const res = await fetch(`/api/trades/${tradeId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
      if (!res.ok) throw new Error('Save failed')
      const result = await res.json()
      bustCache('/api/trade-journal')
      setEntries(prev => ({ ...prev, [tradeId]: { notes: result.notes || '', tags: result.tags || [] } }))
    } catch (err) { console.error(err) }
    finally { setSavingId(null) }
  }, [])

  const getJournal = (g: TradeGroup): JournalEntry => entries[g.primaryId] || { notes: '', tags: [] }

  const untriggeredCount = useMemo(() =>
    allGroups.length - allGroups.filter(g => !g.trades.every(t => UNTRIGGERED.has(t.status))).length,
  [allGroups])

  if (loading) return (
    <div className="flex items-center justify-center py-20 text-muted-foreground/60">
      <Loader2 className="h-5 w-5 animate-spin text-primary mr-2" />
      <span className="text-sm">Loading trades…</span>
    </div>
  )

  if (error) return (
    <div className="flex items-center justify-center py-16 gap-2 text-destructive">
      <AlertCircle className="h-5 w-5" />
      <span className="text-sm font-medium">{error}</span>
      <button onClick={() => load(true)} className="ml-2 text-xs underline">Retry</button>
    </div>
  )

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="flex items-center gap-2.5">
            <BookOpen className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-bold text-foreground">Trade Journal</h2>
            <span className="text-[11px] font-bold px-2.5 py-0.5 rounded-full bg-primary/10 text-primary border border-[#c5d3ff]">
              {journaledCount} journaled
            </span>
          </div>
          <p className="text-xs text-muted-foreground/60 mt-1">
            {triggeredGroups.length} triggered · {allGroups.length} total
            {allGroups.some(g => g.legCount > 1) ? ' · merged by magic number' : ''}
          </p>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {untriggeredCount > 0 && (
            <button onClick={() => setShowUntriggered(v => !v)}
              className={cn('inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border transition-all',
                showUntriggered ? 'bg-muted border-border text-[#697188]' : 'bg-muted/50 border-border/50 text-muted-foreground/50 hover:text-muted-foreground')}>
              {showUntriggered ? <Eye className="h-3 w-3" /> : <EyeOff className="h-3 w-3" />}
              {showUntriggered ? 'Hide' : `+${untriggeredCount}`} untriggered
            </button>
          )}
          <button onClick={() => exportCSV(filtered, entries)}
            className="h-9 px-3 inline-flex items-center gap-1.5 rounded-lg border border-border bg-card text-xs font-semibold text-muted-foreground/70 hover:text-foreground transition-colors">
            <Download className="h-3.5 w-3.5" /> Export
          </button>
          <button onClick={() => load(true)} disabled={refreshing}
            className="h-9 w-9 inline-flex items-center justify-center rounded-lg border border-border bg-card text-muted-foreground/60 hover:text-foreground transition-colors disabled:opacity-50">
            <RefreshCw className={cn('h-3.5 w-3.5', refreshing && 'animate-spin')} />
          </button>
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground/60" />
            <input placeholder="Symbol, tag, notes…" value={search} onChange={e => setSearch(e.target.value)}
              className="h-9 pl-8 pr-3 text-xs rounded-lg border border-border bg-card outline-none focus:border-primary focus:ring-1 focus:ring-primary/20 transition-colors w-44 text-foreground/80 placeholder:text-muted-foreground/40" />
          </div>
        </div>
      </div>

      {/* Date presets */}
      <DatePresetPicker active={datePreset} onChange={setDatePreset} />

      {/* Filter tabs */}
      <div className="flex items-center gap-2">
        <Filter className="h-3.5 w-3.5 text-muted-foreground/60 flex-shrink-0" />
        <FilterTabs active={filter} onChange={setFilter} counts={tabCounts} />
      </div>

      {/* Body */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-5">
        {/* Trade list */}
        <div className="lg:col-span-3 space-y-1">
          {filtered.length === 0 ? (
            <div className="rounded-xl border border-border bg-card shadow-sm py-16 text-center">
              <BookOpen className="h-8 w-8 mx-auto mb-3 text-muted-foreground/25" />
              <p className="text-sm font-semibold text-muted-foreground">
                {allGroups.length === 0 ? 'No trades yet' : 'No trades match this filter'}
              </p>
              <p className="text-xs text-muted-foreground/60 mt-1">
                {allGroups.length === 0 ? 'The bot will populate trades here once executed.' : 'Try a different filter, date range, or search.'}
              </p>
            </div>
          ) : (
            dateGroups.map(({ date, groups: dg }) => (
              <div key={date} className="mb-5 space-y-2">
                <div className="flex items-center gap-3 pt-1">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground/60 flex-shrink-0">{date}</span>
                  <div className="flex-1 h-px bg-muted" />
                  <span className="text-[10px] text-muted-foreground/50 flex-shrink-0">
                    {dg.length} trade{dg.length !== 1 ? 's' : ''}
                    {dg.some(g => g.legCount > 1) && ` · ${dg.reduce((s, g) => s + g.legCount, 0)} legs`}
                  </span>
                </div>
                {dg.map(group => (
                  <TradeGroupRow
                    key={group.groupKey}
                    group={group}
                    journal={getJournal(group)}
                    onSave={handleSave}
                    saving={savingId === group.primaryId}
                  />
                ))}
              </div>
            ))
          )}
        </div>

        {/* Sidebar */}
        <div className="lg:col-span-1 space-y-3">
          <InsightsPanel insights={insights} />
          <StatsPanel groups={baseGroups} entries={entries} />
        </div>
      </div>
    </div>
  )
}
