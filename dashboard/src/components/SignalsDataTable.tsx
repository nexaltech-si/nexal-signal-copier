'use client'

import React, { useState, useEffect } from 'react'
import Link from 'next/link'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog, DialogContent, DialogDescription,
  DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import {
  ShieldCheck,
  ShieldAlert,
  Loader2,
  Search,
  Filter,
  LayoutGrid,
  Table2,
  TrendingUp,
  TrendingDown,
  Zap,
  Clock,
  ExternalLink,
  Trash2,
  Brain,
  ChevronsUpDown,
  ChevronUp,
  ChevronDown as ChevronDownIcon,
  AlertTriangle,
  AlertCircle,
} from 'lucide-react'
import { formatDate, getStatusColor, formatCurrency, cn } from '@/lib/utils'
import type { SignalWithTrades } from '@/lib/types'
import SignalCard from '@/components/SignalCard'

interface SignalsDataTableProps {
  signals: SignalWithTrades[]
  onSignalVerified?: () => void
  onSignalDeleted?: () => void
}

type ViewMode = 'grid' | 'table'
type SortKey = 'createdAt' | 'symbol' | 'confidence' | 'totalPnL'
type SortDir = 'asc' | 'desc'

const AI_VERIFICATION_TYPES = ['All', 'TRADE_SIGNAL', 'INFO_MESSAGE', 'REPLY', 'WRONG_EXECUTION', 'UNCLEAR', 'Unverified']
const STATUS_FILTERS = ['All', 'PENDING', 'VALIDATED', 'EXECUTED', 'CLOSED', 'REJECTED', 'FAILED']

function getVerificationInfo(signal: SignalWithTrades) {
  if (!signal.aiVerified) return { label: 'Unverified', color: 'bg-muted text-muted-foreground', icon: ShieldAlert }
  const map: Record<string, { label: string; color: string }> = {
    TRADE_SIGNAL: { label: 'Signal', color: 'bg-success/10 text-success border border-success/20' },
    INFO_MESSAGE: { label: 'Info', color: 'bg-primary/10 text-primary border border-primary/20' },
    REPLY: { label: 'Reply', color: 'bg-gold/10 text-gold border border-gold/20' },
    WRONG_EXECUTION: { label: 'Wrong', color: 'bg-destructive/10 text-destructive border border-destructive/20' },
    UNCLEAR: { label: 'Unclear', color: 'bg-destructive/10 text-destructive border border-destructive/20' },
    IMAGE_ONLY: { label: 'Image Only', color: 'bg-muted text-muted-foreground border border-border' },
  }
  const info = map[signal.aiVerificationType || 'UNCLEAR'] || map.UNCLEAR
  return { ...info, icon: signal.aiVerificationType === 'TRADE_SIGNAL' ? ShieldCheck : ShieldAlert }
}

export default function SignalsDataTable({ signals, onSignalVerified, onSignalDeleted }: SignalsDataTableProps) {
  const [viewMode, setViewMode] = useState<ViewMode>('grid')
  const [verifyingSignals, setVerifyingSignals] = useState<Set<string>>(new Set())
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('All')
  const [aiFilter, setAiFilter] = useState('All')
  const [sortKey, setSortKey] = useState<SortKey>('createdAt')
  const [sortDir, setSortDir] = useState<SortDir>('desc')
  const [mounted, setMounted] = useState(false)
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

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

  // Load persisted view mode
  useEffect(() => {
    const saved = localStorage.getItem('signalsViewMode') as ViewMode | null
    if (saved === 'table' || saved === 'grid') setViewMode(saved)
    setMounted(true)
  }, [])

  const setView = (mode: ViewMode) => {
    setViewMode(mode)
    localStorage.setItem('signalsViewMode', mode)
  }

  const verifyAllSignals = async () => {
    const unverifiedSignals = signals.filter(s => !s.aiVerified)
    if (unverifiedSignals.length === 0) { alert('All signals are already verified!'); return }
    if (!confirm(`Verify ${unverifiedSignals.length} signals with AI?`)) return
    const signalIds = unverifiedSignals.map(s => s.id)
    signalIds.forEach(id => setVerifyingSignals(prev => new Set(prev).add(id)))
    try {
      const response = await fetch('/api/signals/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ signalIds }),
      })
      if (!response.ok) throw new Error('Batch verification failed')
      if (onSignalVerified) onSignalVerified()
    } catch (error) {
      console.error('Error verifying signals:', error)
      alert('Failed to verify some signals. Please try again.')
    } finally {
      setVerifyingSignals(new Set())
    }
  }

  const filtered = signals
    .filter(signal => {
      const q = search.toLowerCase()
      const matchSearch = !q ||
        signal.symbol.toLowerCase().includes(q) ||
        signal.orderType?.toLowerCase().includes(q) ||
        signal.channelName?.toLowerCase().includes(q) ||
        signal.rawMessage?.toLowerCase().includes(q)
      const matchStatus = statusFilter === 'All' || signal.status === statusFilter
      const matchAi = aiFilter === 'All' ||
        (aiFilter === 'Unverified' && !signal.aiVerified) ||
        signal.aiVerificationType === aiFilter
      return matchSearch && matchStatus && matchAi
    })
    .sort((a, b) => {
      let va: number | string = 0
      let vb: number | string = 0
      if (sortKey === 'createdAt') { va = new Date(a.createdAt).getTime(); vb = new Date(b.createdAt).getTime() }
      else if (sortKey === 'symbol') { va = a.symbol; vb = b.symbol }
      else if (sortKey === 'confidence') { va = a.confidence ?? 0; vb = b.confidence ?? 0 }
      else if (sortKey === 'totalPnL') {
        va = a.trades.reduce((s, t) => s + (t.profitLoss || 0), 0)
        vb = b.trades.reduce((s, t) => s + (t.profitLoss || 0), 0)
      }
      if (va < vb) return sortDir === 'asc' ? -1 : 1
      if (va > vb) return sortDir === 'asc' ? 1 : -1
      return 0
    })

  const unverifiedCount = signals.filter(s => !s.aiVerified).length

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir('desc') }
  }

  const SortIcon = ({ k }: { k: SortKey }) => {
    if (sortKey !== k) return <ChevronsUpDown className="h-3 w-3 opacity-30" />
    return sortDir === 'asc'
      ? <ChevronUp className="h-3 w-3 text-[#cc785c]" />
      : <ChevronDownIcon className="h-3 w-3 text-[#cc785c]" />
  }

  if (!mounted) return null

  return (
    <Card className="border shadow-sm bg-card">
      {/* Header */}
      <CardHeader className="pb-3 px-3 md:px-4 pt-3 border-b bg-muted/40">
        <div className="flex flex-col gap-2.5 sm:flex-row sm:items-center sm:justify-between">
          {/* Left: title + counts */}
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-bold text-foreground">Signals</span>
            <Badge variant="secondary" className="text-xs font-semibold bg-border text-foreground/80">
              {filtered.length} / {signals.length}
            </Badge>
            {unverifiedCount > 0 && (
              <Badge variant="outline" className="text-xs font-semibold text-gold border-amber-400 bg-gold/10">
                {unverifiedCount} unverified
              </Badge>
            )}
          </div>

          {/* Right: controls */}
          <div className="flex items-center gap-1.5 flex-wrap">
            {/* Search */}
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground/70" />
              <Input
                placeholder="Search..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="h-8 pl-8 text-xs w-36 md:w-44 border-border focus:border-primary"
              />
            </div>

            {/* Filters */}
            <div className="flex items-center gap-1">
              <Filter className="h-3 w-3 text-muted-foreground/70" />
              <select
                value={statusFilter}
                onChange={e => setStatusFilter(e.target.value)}
                className="h-8 text-xs border border-border rounded px-2 bg-card font-medium text-foreground/80 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
              >
                {STATUS_FILTERS.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
              <select
                value={aiFilter}
                onChange={e => setAiFilter(e.target.value)}
                className="h-8 text-xs border border-border rounded px-2 bg-card font-medium text-foreground/80 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
              >
                {AI_VERIFICATION_TYPES.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>

            {/* Verify all */}
            {unverifiedCount > 0 && (
              <Button
                size="sm"
                variant="outline"
                onClick={verifyAllSignals}
                disabled={verifyingSignals.size > 0}
                className="h-8 text-xs font-semibold border-border hover:bg-muted"
              >
                {verifyingSignals.size > 0 ? (
                  <><Loader2 className="h-3 w-3 mr-1.5 animate-spin" />Verifying...</>
                ) : (
                  <><ShieldCheck className="h-3 w-3 mr-1.5" />Verify All</>
                )}
              </Button>
            )}

            {/* View toggle */}
            <div className="flex items-center rounded-md border border-border overflow-hidden bg-card">
              <button
                onClick={() => setView('grid')}
                title="Grid view"
                className={cn(
                  'flex items-center justify-center h-8 w-8 transition-colors',
                  viewMode === 'grid'
                    ? 'bg-primary/10 text-primary'
                    : 'text-muted-foreground/70 hover:bg-muted/50'
                )}
              >
                <LayoutGrid className="h-3.5 w-3.5" />
              </button>
              <button
                onClick={() => setView('table')}
                title="Table view"
                className={cn(
                  'flex items-center justify-center h-8 w-8 transition-colors',
                  viewMode === 'table'
                    ? 'bg-primary/10 text-primary'
                    : 'text-muted-foreground/70 hover:bg-muted/50'
                )}
              >
                <Table2 className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        </div>
      </CardHeader>

      <CardContent className="px-3 md:px-4 pb-3 pt-3">
        {filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-14 text-center">
            <div className="w-12 h-12 rounded-full bg-muted flex items-center justify-center mb-3">
              <Search className="h-5 w-5 text-muted-foreground/70" />
            </div>
            <p className="text-sm font-semibold text-foreground/80">
              {signals.length === 0 ? 'No signals yet' : 'No results match your filters'}
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              {signals.length === 0 ? 'Signals will appear here as they arrive.' : 'Try adjusting your search or filters.'}
            </p>
          </div>
        ) : viewMode === 'grid' ? (
          // ── GRID VIEW ──
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-2.5">
            {filtered.map((signal) => (
              <SignalCard
                key={signal.id}
                signal={signal}
                compact
                onSignalDeleted={onSignalDeleted}
              />
            ))}
          </div>
        ) : (
          // ── TABLE VIEW ──
          <div className="overflow-x-auto -mx-1">
            <table className="w-full text-xs min-w-[700px]">
              <thead>
                <tr className="bg-muted/50 border-b border-border">
                  <th className="px-3 py-2.5 text-left">
                    <button
                      onClick={() => toggleSort('symbol')}
                      className="flex items-center gap-1 font-bold text-muted-foreground uppercase tracking-wider text-[10px] hover:text-primary transition-colors"
                    >
                      Symbol <SortIcon k="symbol" />
                    </button>
                  </th>
                  <th className="px-3 py-2.5 text-left font-bold text-muted-foreground uppercase tracking-wider text-[10px]">
                    Entry / SL
                  </th>
                  <th className="px-3 py-2.5 text-right">
                    <button
                      onClick={() => toggleSort('confidence')}
                      className="flex items-center gap-1 font-bold text-muted-foreground uppercase tracking-wider text-[10px] hover:text-primary transition-colors ml-auto"
                    >
                      Conf <SortIcon k="confidence" />
                    </button>
                  </th>
                  <th className="px-3 py-2.5 text-left font-bold text-muted-foreground uppercase tracking-wider text-[10px]">
                    Status
                  </th>
                  <th className="px-3 py-2.5 text-left font-bold text-muted-foreground uppercase tracking-wider text-[10px]">
                    AI
                  </th>
                  <th className="px-3 py-2.5 text-right">
                    <button
                      onClick={() => toggleSort('totalPnL')}
                      className="flex items-center gap-1 font-bold text-muted-foreground uppercase tracking-wider text-[10px] hover:text-primary transition-colors ml-auto"
                    >
                      P&amp;L <SortIcon k="totalPnL" />
                    </button>
                  </th>
                  <th className="px-3 py-2.5 text-right">
                    <button
                      onClick={() => toggleSort('createdAt')}
                      className="flex items-center gap-1 font-bold text-muted-foreground uppercase tracking-wider text-[10px] hover:text-primary transition-colors ml-auto"
                    >
                      Date <SortIcon k="createdAt" />
                    </button>
                  </th>
                  <th className="px-3 py-2.5 w-16" />
                </tr>
              </thead>
              <tbody className="divide-y divide-[#e6dfd8]">
                {filtered.map((signal) => {
                  const isBuy = signal.orderType?.toUpperCase().includes('BUY')
                  const totalPnL = signal.trades.reduce((sum, t) => sum + (t.profitLoss || 0), 0)
                  const verification = getVerificationInfo(signal)
                  const VerifIcon = verification.icon
                  const isProblematic = signal.aiVerificationType === 'UNCLEAR' || signal.aiVerificationType === 'WRONG_EXECUTION'

                  return (
                    <tr
                      key={signal.id}
                      className={cn(
                        'group hover:bg-muted/50 transition-colors',
                        isProblematic && 'bg-destructive/10/40'
                      )}
                    >
                      {/* Symbol + direction */}
                      <td className="px-3 py-2.5">
                        <div className="flex items-center gap-2">
                          <div className={cn(
                            'flex items-center justify-center w-6 h-6 rounded flex-shrink-0',
                            isBuy ? 'bg-success/10 text-success' : 'bg-destructive/10 text-destructive'
                          )}>
                            {isBuy
                              ? <TrendingUp className="h-3.5 w-3.5" />
                              : <TrendingDown className="h-3.5 w-3.5" />}
                          </div>
                          <div className="min-w-0">
                            <div className="font-bold text-foreground text-xs">{signal.symbol}</div>
                            <div className="text-[10px] text-muted-foreground font-medium">{signal.orderType}</div>
                          </div>
                        </div>
                      </td>

                      {/* Entry / SL */}
                      <td className="px-3 py-2.5">
                        <div className="font-mono text-foreground">
                          {signal.entryRangeMin && signal.entryRangeMax
                            ? `${signal.entryRangeMin.toFixed(5)} – ${signal.entryRangeMax.toFixed(5)}`
                            : signal.entryRangeMin ?? signal.entryRangeMax
                            ? (signal.entryRangeMin ?? signal.entryRangeMax)!.toFixed(5)
                            : signal.entryPrice
                            ? signal.entryPrice.toFixed(5)
                            : '—'}
                        </div>
                        {signal.stopLoss && (
                          <div className="font-mono text-[10px] text-destructive">
                            SL {signal.stopLoss.toFixed(5)}
                          </div>
                        )}
                        {signal.riskRewardRatio && (
                          <div className="text-[10px] text-muted-foreground">R:R 1:{signal.riskRewardRatio.toFixed(1)}</div>
                        )}
                      </td>

                      {/* Confidence */}
                      <td className="px-3 py-2.5 text-right">
                        {signal.confidence ? (
                          <div className="flex flex-col items-end gap-1">
                            <div className="flex items-center gap-1">
                              <Zap className="h-3 w-3 text-gold" />
                              <span className="font-bold text-[#141413]">
                                {(signal.confidence * 100).toFixed(0)}%
                              </span>
                            </div>
                            <div className="w-14 h-1 bg-border rounded-full overflow-hidden">
                              <div
                                className={cn(
                                  'h-full rounded-full',
                                  signal.confidence >= 0.7 ? 'bg-emerald-500' :
                                  signal.confidence >= 0.4 ? 'bg-amber-400' : 'bg-rose-500'
                                )}
                                style={{ width: `${signal.confidence * 100}%` }}
                              />
                            </div>
                          </div>
                        ) : (
                          <span className="text-[#8e8b82]">—</span>
                        )}
                      </td>

                      {/* Status */}
                      <td className="px-3 py-2.5">
                        <Badge className={`${getStatusColor(signal.status)} text-[10px] px-1.5 py-0 h-4 font-semibold`}>
                          {signal.status}
                        </Badge>
                        {signal.trades.length > 0 && (
                          <div className="text-[10px] text-muted-foreground mt-0.5">
                            {signal.trades.length} trade{signal.trades.length > 1 ? 's' : ''}
                          </div>
                        )}
                      </td>

                      {/* AI verification */}
                      <td className="px-3 py-2.5">
                        <Badge className={`${verification.color} text-[10px] px-1.5 py-0 h-4 flex items-center gap-0.5 font-semibold w-fit`}>
                          <VerifIcon className="h-2.5 w-2.5" />
                          {verification.label}
                        </Badge>
                        {signal.aiVerified && (
                          <div className="flex items-center gap-0.5 text-[10px] text-muted-foreground mt-0.5">
                            <Brain className="h-2.5 w-2.5" />
                            AI
                          </div>
                        )}
                      </td>

                      {/* P&L */}
                      <td className="px-3 py-2.5 text-right">
                        {signal.trades.length > 0 ? (
                          <span className={cn(
                            'font-bold tabular-nums',
                            totalPnL > 0 ? 'text-success' :
                            totalPnL < 0 ? 'text-destructive' : 'text-muted-foreground'
                          )}>
                            {totalPnL > 0 ? '+' : ''}{formatCurrency(totalPnL)}
                          </span>
                        ) : (
                          <span className="text-[#8e8b82]">—</span>
                        )}
                      </td>

                      {/* Date */}
                      <td className="px-3 py-2.5 text-right">
                        <div className="flex items-center justify-end gap-1 text-muted-foreground">
                          <Clock className="h-2.5 w-2.5" />
                          <span className="text-[10px]">{formatDate(signal.createdAt)}</span>
                        </div>
                      </td>

                      {/* Actions */}
                      <td className="px-3 py-2.5">
                        <div className="flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                          <Link href={`/history/signals/${signal.id}`} onClick={e => e.stopPropagation()}>
                            <Button variant="ghost" size="sm" className="h-6 w-6 p-0 hover:bg-muted text-muted-foreground">
                              <ExternalLink className="h-3 w-3" />
                            </Button>
                          </Link>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-6 w-6 p-0 hover:bg-destructive/10 hover:text-destructive text-muted-foreground/70"
                            title="Delete signal"
                            onClick={() => { setDeleteConfirmId(signal.id); setDeleteError(null) }}
                          >
                            <Trash2 className="h-3 w-3" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>

      {/* Delete confirmation dialog */}
      {(() => {
        const signalToDelete = deleteConfirmId ? filtered.find(s => s.id === deleteConfirmId) ?? signals.find(s => s.id === deleteConfirmId) : null
        return (
          <Dialog open={!!deleteConfirmId} onOpenChange={open => { if (!open) setDeleteConfirmId(null) }}>
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
                    All associated trades ({signalToDelete?.trades.length ?? 0})
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
                <Button variant="outline" onClick={() => setDeleteConfirmId(null)} disabled={isDeleting} className="font-bold">
                  Cancel
                </Button>
                <Button
                  variant="destructive"
                  onClick={() => deleteConfirmId && doDelete(deleteConfirmId)}
                  disabled={isDeleting}
                  className="font-bold bg-rose-600 hover:bg-rose-700"
                >
                  {isDeleting ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Deleting...</> : 'Delete Signal'}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        )
      })()}
    </Card>
  )
}
