'use client'

import React, { useState, useMemo } from 'react'
import Link from 'next/link'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { cn, formatCurrency, getStatusColor } from '@/lib/utils'
import {
  AlertCircle,
  Search,
  TrendingUp,
  TrendingDown,
  LayoutGrid,
  Table2,
  ChevronsUpDown,
  ChevronUp,
  ChevronDown,
  ExternalLink,
  Brain,
  Activity,
} from 'lucide-react'
import type { TradeWithRelations } from '@/lib/types'
import TradeCard from '@/components/TradeCard'

const STATUS_FILTERS = ['All', 'PENDING', 'EXECUTING', 'EXECUTED', 'CLOSED', 'REJECTED', 'FAILED']
const ACTION_FILTERS = ['All', 'BUY', 'SELL', 'BUY_LIMIT', 'SELL_LIMIT', 'BUY_STOP', 'SELL_STOP']

type ViewMode = 'cards' | 'table'
type SortKey = 'createdAt' | 'symbol' | 'profitLoss' | 'status'
type SortDir = 'asc' | 'desc'

const VIEW_KEY = 'tradesViewMode'

interface TradesDataTableProps {
  trades: TradeWithRelations[]
}

function SortIcon({ k, sortKey, sortDir }: { k: SortKey; sortKey: SortKey; sortDir: SortDir }) {
  if (sortKey !== k) return <ChevronsUpDown className="h-3 w-3 text-muted-foreground/70 ml-1 inline" />
  return sortDir === 'asc'
    ? <ChevronUp className="h-3 w-3 text-primary ml-1 inline" />
    : <ChevronDown className="h-3 w-3 text-primary ml-1 inline" />
}

export default function TradesDataTable({ trades }: TradesDataTableProps) {
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('All')
  const [actionFilter, setActionFilter] = useState('All')
  const [viewMode, setViewMode] = useState<ViewMode>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem(VIEW_KEY)
      if (saved === 'cards' || saved === 'table') return saved
    }
    return 'cards'
  })
  const [sortKey, setSortKey] = useState<SortKey>('createdAt')
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  const changeView = (mode: ViewMode) => {
    setViewMode(mode)
    localStorage.setItem(VIEW_KEY, mode)
  }

  const toggleSort = (k: SortKey) => {
    if (sortKey === k) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(k); setSortDir('asc') }
  }

  if (!Array.isArray(trades)) {
    return (
      <Card className="col-span-4">
        <CardContent>
          <div className="flex items-center justify-center py-8 text-destructive">
            <AlertCircle className="h-5 w-5 mr-2" />
            <span>Error loading trades. Please refresh the page.</span>
          </div>
        </CardContent>
      </Card>
    )
  }

  const filteredTrades = useMemo(() => {
    const q = search.toLowerCase()
    const filtered = trades.filter(trade => {
      const matchSearch = !q ||
        trade.symbol.toLowerCase().includes(q) ||
        trade.action.toLowerCase().includes(q) ||
        (trade.orderId?.toString() || '').includes(q) ||
        (trade.positionId?.toString() || '').includes(q)
      const matchStatus = statusFilter === 'All' || trade.status === statusFilter
      const matchAction = actionFilter === 'All' || trade.action === actionFilter
      return matchSearch && matchStatus && matchAction
    })

    filtered.sort((a, b) => {
      let cmp = 0
      if (sortKey === 'createdAt') cmp = new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime()
      else if (sortKey === 'symbol') cmp = a.symbol.localeCompare(b.symbol)
      else if (sortKey === 'profitLoss') cmp = (Number(a.profitLoss) || 0) - (Number(b.profitLoss) || 0)
      else if (sortKey === 'status') cmp = a.status.localeCompare(b.status)
      return sortDir === 'asc' ? cmp : -cmp
    })

    return filtered
  }, [trades, search, statusFilter, actionFilter, sortKey, sortDir])

  const activeTrades = trades.filter(t => t.status === 'EXECUTING' || t.status === 'PENDING').length

  return (
    <Card className="border shadow-sm bg-card">
      <CardHeader className="pb-3 px-3 md:px-4 pt-3 border-b bg-muted/40">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold text-foreground">Trades</span>
            <Badge variant="secondary" className="text-xs font-semibold bg-border text-foreground/80">
              {filteredTrades.length} / {trades.length}
            </Badge>
            {activeTrades > 0 && (
              <Badge className="text-[10px] font-bold bg-success/10 text-success border border-success/20 border-0 flex items-center gap-1">
                <span className="relative flex h-1.5 w-1.5">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-500" />
                </span>
                {activeTrades} live
              </Badge>
            )}
          </div>

          <div className="flex items-center gap-1.5 flex-wrap">
            {/* Search */}
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground/70" />
              <Input
                placeholder="Search..."
                value={search}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setSearch(e.target.value)}
                className="h-8 pl-8 text-xs w-36 md:w-44 border-border focus:border-primary"
              />
            </div>

            {/* Status filter */}
            <select
              value={statusFilter}
              onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setStatusFilter(e.target.value)}
              className="h-8 text-xs border border-border rounded-md px-2 bg-card font-medium text-foreground/80 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
            >
              {STATUS_FILTERS.map(s => <option key={s} value={s}>{s}</option>)}
            </select>

            {/* Action filter */}
            <select
              value={actionFilter}
              onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setActionFilter(e.target.value)}
              className="h-8 text-xs border border-border rounded-md px-2 bg-card font-medium text-foreground/80 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
            >
              {ACTION_FILTERS.map(s => <option key={s} value={s}>{s}</option>)}
            </select>

            {/* View toggle */}
            <div className="flex items-center rounded-md border border-border overflow-hidden bg-card">
              <button
                onClick={() => changeView('cards')}
                className={cn(
                  "flex items-center justify-center px-2 h-8 transition-colors",
                  viewMode === 'cards' ? "bg-primary/10 text-primary" : "text-muted-foreground/70 hover:bg-muted/50"
                )}
                title="Grid view"
              >
                <LayoutGrid className="h-3.5 w-3.5" />
              </button>
              <button
                onClick={() => changeView('table')}
                className={cn(
                  "flex items-center justify-center px-2 h-8 transition-colors",
                  viewMode === 'table' ? "bg-primary/10 text-primary" : "text-muted-foreground/70 hover:bg-muted/50"
                )}
                title="Table view"
              >
                <Table2 className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        </div>
      </CardHeader>

      <CardContent className="px-3 md:px-4 pb-3 pt-3">
        {filteredTrades.length === 0 ? (
          <div className="text-center text-muted-foreground py-12">
            <p className="text-sm font-medium">{trades.length === 0 ? 'No trades found' : 'No results match your filters'}</p>
          </div>
        ) : viewMode === 'cards' ? (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-2.5">
            {filteredTrades.map((trade) => (
              <TradeCard key={trade.id} trade={trade} compact />
            ))}
          </div>
        ) : (
          /* Table view */
          <div className="overflow-x-auto -mx-3 md:-mx-4">
            <table className="w-full min-w-[700px]">
              <thead>
                <tr className="bg-muted/50 border-b border-border">
                  <th className="text-left px-4 py-2.5 font-bold text-muted-foreground uppercase tracking-wider text-[10px]">
                    <button onClick={() => toggleSort('symbol')} className="flex items-center hover:text-primary transition-colors">
                      Symbol <SortIcon k="symbol" sortKey={sortKey} sortDir={sortDir} />
                    </button>
                  </th>
                  <th className="text-left px-4 py-2.5 font-bold text-muted-foreground uppercase tracking-wider text-[10px]">
                    Entry / SL / TP
                  </th>
                  <th className="text-left px-4 py-2.5 font-bold text-muted-foreground uppercase tracking-wider text-[10px]">
                    <button onClick={() => toggleSort('status')} className="flex items-center hover:text-primary transition-colors">
                      Status <SortIcon k="status" sortKey={sortKey} sortDir={sortDir} />
                    </button>
                  </th>
                  <th className="text-right px-4 py-2.5 font-bold text-muted-foreground uppercase tracking-wider text-[10px]">
                    <button onClick={() => toggleSort('profitLoss')} className="flex items-center ml-auto hover:text-primary transition-colors">
                      P/L <SortIcon k="profitLoss" sortKey={sortKey} sortDir={sortDir} />
                    </button>
                  </th>
                  <th className="text-left px-4 py-2.5 font-bold text-muted-foreground uppercase tracking-wider text-[10px]">
                    <button onClick={() => toggleSort('createdAt')} className="flex items-center hover:text-primary transition-colors">
                      Date <SortIcon k="createdAt" sortKey={sortKey} sortDir={sortDir} />
                    </button>
                  </th>
                  <th className="text-right px-4 py-2.5 font-bold text-muted-foreground uppercase tracking-wider text-[10px]">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {filteredTrades.map((trade) => {
                  const isBuy = trade.action?.toUpperCase().includes('BUY')
                  const pnl = Number(trade.profitLoss)
                  const hasPnl = trade.profitLoss !== null && trade.profitLoss !== undefined
                  const hasAI = trade.marketAnalyses && trade.marketAnalyses.length > 0
                  const actionCount = trade.tradeActions?.length || 0

                  return (
                    <tr key={trade.id} className="group hover:bg-muted/50 transition-colors">
                      {/* Symbol + direction */}
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <div className={cn(
                            "w-6 h-6 rounded-md flex items-center justify-center flex-shrink-0",
                            isBuy ? "bg-success/10" : "bg-destructive/10"
                          )}>
                            {isBuy
                              ? <TrendingUp className="h-3.5 w-3.5 text-success" />
                              : <TrendingDown className="h-3.5 w-3.5 text-destructive" />
                            }
                          </div>
                          <div>
                            <div className="font-bold text-sm text-foreground">{trade.symbol}</div>
                            <div className="text-[10px] text-muted-foreground font-medium">{trade.action} · {trade.lotSize.toFixed(2)}L</div>
                          </div>
                        </div>
                      </td>

                      {/* Entry/SL/TP */}
                      <td className="px-4 py-3">
                        <div className="space-y-0.5 font-mono text-[11px]">
                          <div className="text-foreground/80"><span className="text-muted-foreground/70 font-sans">E</span> {trade.entryPrice?.toFixed(5) || '—'}</div>
                          <div className="text-destructive"><span className="text-muted-foreground/70 font-sans">SL</span> {trade.stopLoss?.toFixed(5) || '—'}</div>
                          <div className="text-success"><span className="text-muted-foreground/70 font-sans">TP</span> {trade.takeProfit?.toFixed(5) || '—'}</div>
                        </div>
                      </td>

                      {/* Status */}
                      <td className="px-4 py-3">
                        <Badge className={cn(getStatusColor(trade.status), "text-xs px-2.5 py-0.5 font-bold whitespace-nowrap")}>
                          {trade.status}
                        </Badge>
                        <div className="flex items-center gap-1.5 mt-1">
                          {hasAI && (
                            <span className="flex items-center gap-0.5 text-[9px] text-primary font-bold">
                              <Brain className="h-2.5 w-2.5" /> AI
                            </span>
                          )}
                          {actionCount > 0 && (
                            <span className="flex items-center gap-0.5 text-[9px] text-muted-foreground font-bold">
                              <Activity className="h-2.5 w-2.5" /> {actionCount}
                            </span>
                          )}
                          {trade.tpLevel && (
                            <span className="text-[9px] font-bold text-primary">TP{trade.tpLevel}</span>
                          )}
                        </div>
                      </td>

                      {/* P/L */}
                      <td className="px-4 py-3 text-right">
                        {hasPnl ? (
                          <div className={cn("font-bold text-sm tabular-nums", pnl >= 0 ? "text-success" : "text-destructive")}>
                            {formatCurrency(pnl)}
                            {trade.profitLossPips !== null && trade.profitLossPips !== undefined && (
                              <div className="text-[9px] font-normal text-muted-foreground/70">
                                {Number(trade.profitLossPips) >= 0 ? '+' : ''}{Number(trade.profitLossPips).toFixed(1)}p
                              </div>
                            )}
                          </div>
                        ) : (
                          <span className="text-muted-foreground/50 text-sm">—</span>
                        )}
                      </td>

                      {/* Date */}
                      <td className="px-4 py-3">
                        <div className="text-[11px] text-muted-foreground font-medium whitespace-nowrap">
                          {new Date(trade.createdAt).toLocaleDateString()}
                        </div>
                        <div className="text-[10px] text-muted-foreground/70">
                          {new Date(trade.createdAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                        </div>
                      </td>

                      {/* Actions */}
                      <td className="px-4 py-3 text-right">
                        <Link
                          href={`/history/trades/${trade.id}`}
                          className="opacity-0 group-hover:opacity-100 transition-opacity inline-flex items-center gap-1 text-[10px] font-bold text-primary hover:text-primary/80 bg-primary/10 px-2 py-1 rounded-md"
                        >
                          View <ExternalLink className="h-2.5 w-2.5" />
                        </Link>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
