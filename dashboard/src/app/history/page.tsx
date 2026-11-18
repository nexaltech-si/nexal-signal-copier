'use client'

import { useState, useEffect, useCallback } from 'react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { ChevronLeft, ChevronRight, History, CalendarIcon, RotateCcw, SlidersHorizontal, Trash2, AlertTriangle, RefreshCw } from 'lucide-react'
import { Calendar } from '@/components/ui/calendar'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import { format } from 'date-fns'
import { type DateRange } from 'react-day-picker'
import {
  Dialog, DialogContent, DialogDescription,
  DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { useToast } from '@/hooks/use-toast'
import SignalsTable from '@/components/SignalsTable'
import TradesTable from '@/components/TradesTable'
import TradeActionsTable from '@/components/TradeActionsTable'
import MobilePageHeader from '@/components/MobilePageHeader'

const ITEMS_PER_PAGE = 20

// ─── Sidebar filter label ─────────────────────────────────────────────────────
function FilterLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70 mb-1.5">
      {children}
    </p>
  )
}

export default function HistoryPage() {
  const [activeTab, setActiveTab] = useState('signals')

  const [signalsPage, setSignalsPage] = useState(1)
  const [tradesPage, setTradesPage] = useState(1)
  const [actionsPage, setActionsPage] = useState(1)

  const [signals, setSignals] = useState<any[]>([])
  const [trades, setTrades] = useState<any[]>([])
  const [actions, setActions] = useState<any[]>([])

  const [totalSignals, setTotalSignals] = useState(0)
  const [filteredSignalTotal, setFilteredSignalTotal] = useState(0)
  const [totalTrades, setTotalTrades] = useState(0)
  const [totalActions, setTotalActions] = useState(0)

  const [loading, setLoading] = useState(false)

  // Signals filters
  const [signalSymbolFilter, setSignalSymbolFilter] = useState('')
  const [signalChannelFilter, setSignalChannelFilter] = useState('')
  const [signalVerificationFilter, setSignalVerificationFilter] = useState('')
  const [signalStatusFilter, setSignalStatusFilter] = useState('')
  const [signalDateRange, setSignalDateRange] = useState<DateRange | undefined>(() => {
    const now = new Date()
    const from = new Date(now)
    from.setDate(from.getDate() - 90)
    return { from, to: now }
  })

  // Trades filters
  const [symbolFilter, setSymbolFilter] = useState('')
  const [channelFilter, setChannelFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [outcomeFilter, setOutcomeFilter] = useState('')

  // Actions filters
  const [actionSymbolFilter, setActionSymbolFilter] = useState('')
  const [actionTypeFilter, setActionTypeFilter] = useState('')
  const [triggeredByFilter, setTriggeredByFilter] = useState('')

  const [filtersLoaded, setFiltersLoaded] = useState(false)

  // Cleanup dialog state
  const [cleanupOpen, setCleanupOpen] = useState(false)
  const [cleanupStatus, setCleanupStatus] = useState('')
  const [cleanupCount, setCleanupCount] = useState<number | null>(null)
  const [cleanupCountLoading, setCleanupCountLoading] = useState(false)
  const [cleanupConfirm, setCleanupConfirm] = useState(false)
  const [cleanupDeleting, setCleanupDeleting] = useState(false)
  const { toast } = useToast()

  // Filter options
  const [availableSymbols, setAvailableSymbols] = useState<string[]>([])
  const [availableChannels, setAvailableChannels] = useState<{ id: string; name: string }[]>([])
  const [availableActionTypes, setAvailableActionTypes] = useState<string[]>([])
  const [availableTriggeredBy, setAvailableTriggeredBy] = useState<string[]>([])
  const [availableStatuses, setAvailableStatuses] = useState<string[]>([])
  const [availableSignalStatuses, setAvailableSignalStatuses] = useState<string[]>([])

  // Load filters from localStorage
  useEffect(() => {
    setSymbolFilter(localStorage.getItem('tradesSymbolFilter') || '')
    setChannelFilter(localStorage.getItem('tradesChannelFilter') || '')
    setStatusFilter(localStorage.getItem('tradesStatusFilter') || '')
    setOutcomeFilter(localStorage.getItem('tradesOutcomeFilter') || '')
    setSignalSymbolFilter(localStorage.getItem('signalsSymbolFilter') || '')
    setSignalChannelFilter(localStorage.getItem('signalsChannelFilter') || '')
    setSignalVerificationFilter(localStorage.getItem('signalsVerificationFilter') || '')
    setSignalStatusFilter(localStorage.getItem('signalsStatusFilter') || '')
    setActionSymbolFilter(localStorage.getItem('actionsSymbolFilter') || '')
    setActionTypeFilter(localStorage.getItem('actionsActionTypeFilter') || '')
    setTriggeredByFilter(localStorage.getItem('actionsTriggeredByFilter') || '')
    setFiltersLoaded(true)
  }, [])

  // Persist filters
  useEffect(() => {
    if (!filtersLoaded) return
    localStorage.setItem('tradesSymbolFilter', symbolFilter)
    localStorage.setItem('tradesChannelFilter', channelFilter)
    localStorage.setItem('tradesStatusFilter', statusFilter)
    localStorage.setItem('tradesOutcomeFilter', outcomeFilter)
    localStorage.setItem('signalsSymbolFilter', signalSymbolFilter)
    localStorage.setItem('signalsChannelFilter', signalChannelFilter)
    localStorage.setItem('signalsVerificationFilter', signalVerificationFilter)
    localStorage.setItem('signalsStatusFilter', signalStatusFilter)
    localStorage.setItem('actionsSymbolFilter', actionSymbolFilter)
    localStorage.setItem('actionsActionTypeFilter', actionTypeFilter)
    localStorage.setItem('actionsTriggeredByFilter', triggeredByFilter)
  }, [symbolFilter, channelFilter, statusFilter, outcomeFilter, signalSymbolFilter, signalChannelFilter, signalVerificationFilter, signalStatusFilter, actionSymbolFilter, actionTypeFilter, triggeredByFilter, filtersLoaded])

  useEffect(() => {
    fetch('/api/filter-options')
      .then(r => r.json())
      .then(data => {
        setAvailableSymbols(data.symbols || [])
        setAvailableChannels(data.channels || [])
        setAvailableActionTypes(data.actionTypes || [])
        setAvailableTriggeredBy(data.triggeredBy || [])
        setAvailableStatuses(data.tradeStatuses || [])
        setAvailableSignalStatuses(data.signalStatuses || [])
      })
      .catch(console.error)
  }, [])

  // ── Data fetching ────────────────────────────────────────────────────────────

  const fetchSignals = useCallback(() => {
    if (!filtersLoaded) return
    setLoading(true)
    const p = new URLSearchParams({
      limit: ITEMS_PER_PAGE.toString(),
      offset: ((signalsPage - 1) * ITEMS_PER_PAGE).toString(),
    })
    if (signalSymbolFilter) p.append('symbol', signalSymbolFilter)
    if (signalChannelFilter) p.append('channel', signalChannelFilter)
    if (signalVerificationFilter) p.append('verification', signalVerificationFilter)
    if (signalStatusFilter) p.append('status', signalStatusFilter)
    if (signalDateRange?.from) p.append('dateFrom', signalDateRange.from.toISOString())
    if (signalDateRange?.to) p.append('dateTo', signalDateRange.to.toISOString())
    fetch(`/api/signals?${p}`)
      .then(r => r.json())
      .then(data => {
        if (data && Array.isArray(data.signals)) {
          setSignals(data.signals)
          setFilteredSignalTotal(data.total ?? data.signals.length)
        } else if (Array.isArray(data)) {
          setSignals(data)
          setFilteredSignalTotal(data.length)
        } else {
          setSignals([])
          setFilteredSignalTotal(0)
        }
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [signalsPage, signalSymbolFilter, signalChannelFilter, signalVerificationFilter, signalStatusFilter, signalDateRange, filtersLoaded])

  useEffect(() => { fetchSignals() }, [fetchSignals])

  useEffect(() => {
    if (!filtersLoaded) return
    setLoading(true)
    const p = new URLSearchParams({
      limit: ITEMS_PER_PAGE.toString(),
      offset: ((tradesPage - 1) * ITEMS_PER_PAGE).toString(),
    })
    if (symbolFilter) p.append('symbol', symbolFilter)
    if (channelFilter) p.append('channel', channelFilter)
    if (statusFilter) p.append('status', statusFilter)
    if (outcomeFilter) p.append('outcome', outcomeFilter)
    fetch(`/api/trades?${p}`)
      .then(r => r.json())
      .then(data => { setTrades(Array.isArray(data) ? data : []); setLoading(false) })
      .catch(() => setLoading(false))
  }, [tradesPage, symbolFilter, channelFilter, statusFilter, outcomeFilter, filtersLoaded])

  useEffect(() => {
    if (!filtersLoaded) return
    setLoading(true)
    const p = new URLSearchParams({
      limit: ITEMS_PER_PAGE.toString(),
      offset: ((actionsPage - 1) * ITEMS_PER_PAGE).toString(),
    })
    if (actionSymbolFilter) p.append('symbol', actionSymbolFilter)
    if (actionTypeFilter) p.append('actionType', actionTypeFilter)
    if (triggeredByFilter) p.append('triggeredBy', triggeredByFilter)
    fetch(`/api/trade-actions?${p}`)
      .then(r => r.json())
      .then(data => { setActions(Array.isArray(data) ? data : []); setLoading(false) })
      .catch(() => setLoading(false))
  }, [actionsPage, actionSymbolFilter, actionTypeFilter, triggeredByFilter, filtersLoaded])

  useEffect(() => {
    fetch('/api/stats')
      .then(r => r.json())
      .then(data => {
        setTotalSignals(data.totalSignals || 0)
        setTotalTrades(data.totalTrades || 0)
        setTotalActions(data.totalActions || 0)
      })
  }, [])

  // ── Cleanup handlers ─────────────────────────────────────────────────────────

  async function handleCleanupStatusChange(status: string) {
    setCleanupStatus(status)
    setCleanupConfirm(false)
    setCleanupCount(null)
    if (!status) return
    setCleanupCountLoading(true)
    try {
      const res = await fetch(`/api/signals/count?status=${encodeURIComponent(status)}`)
      const data = await res.json()
      setCleanupCount(data.count ?? 0)
    } catch {
      setCleanupCount(null)
    } finally {
      setCleanupCountLoading(false)
    }
  }

  async function handleCleanupDelete() {
    if (!cleanupConfirm) { setCleanupConfirm(true); return }
    setCleanupDeleting(true)
    try {
      const res = await fetch('/api/signals/bulk-delete-by-status', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: cleanupStatus }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error || 'Delete failed')
      toast({ title: `Deleted ${data.deleted} signal${data.deleted !== 1 ? 's' : ''} with status "${cleanupStatus}"` })
      setCleanupOpen(false)
      setCleanupStatus('')
      setCleanupCount(null)
      setCleanupConfirm(false)
      // Refresh signals data and stats
      setSignalsPage(1)
      fetchSignals()
      fetch('/api/stats').then(r => r.json()).then(data => {
        setTotalSignals(data.totalSignals || 0)
      })
    } catch (e: unknown) {
      toast({
        title: 'Delete failed',
        description: e instanceof Error ? e.message : 'Unknown error',
        variant: 'destructive',
      })
    } finally {
      setCleanupDeleting(false)
    }
  }

  function openCleanup() {
    setCleanupStatus('')
    setCleanupCount(null)
    setCleanupConfirm(false)
    setCleanupOpen(true)
  }

  // ── Resets ────────────────────────────────────────────────────────────────────

  const resetSignalFilters = () => {
    setSignalSymbolFilter(''); setSignalChannelFilter('')
    setSignalVerificationFilter(''); setSignalStatusFilter('')
    const now = new Date()
    const from = new Date(now); from.setDate(from.getDate() - 90)
    setSignalDateRange({ from, to: now })
    setSignalsPage(1)
  }
  const resetTradeFilters = () => {
    setSymbolFilter(''); setChannelFilter(''); setStatusFilter(''); setOutcomeFilter('')
    setTradesPage(1)
  }
  const resetActionFilters = () => {
    setActionSymbolFilter(''); setActionTypeFilter(''); setTriggeredByFilter('')
    setActionsPage(1)
  }

  const defaultDateFrom = (() => { const d = new Date(); d.setDate(d.getDate() - 90); return d })()
  const signalDateIsCustom = signalDateRange
    ? (signalDateRange.from && Math.abs(signalDateRange.from.getTime() - defaultDateFrom.getTime()) > 86400000)
      || (signalDateRange.to && Math.abs(signalDateRange.to.getTime() - new Date().getTime()) > 86400000)
    : false
  const signalHasFilters = !!(signalSymbolFilter || signalChannelFilter || signalVerificationFilter || signalStatusFilter || signalDateIsCustom)
  const tradeHasFilters = !!(symbolFilter || channelFilter || statusFilter || outcomeFilter)
  const actionHasFilters = !!(actionSymbolFilter || actionTypeFilter || triggeredByFilter)

  // ── Pagination ────────────────────────────────────────────────────────────────

  function PaginationControls({
    currentPage, totalItems, onPageChange,
  }: { currentPage: number; totalItems: number; onPageChange: (p: number) => void }) {
    const totalPages = Math.ceil(totalItems / ITEMS_PER_PAGE)
    return (
      <div className="flex items-center justify-between pt-3 mt-3 border-t border-border">
        <p className="text-xs text-muted-foreground/70 font-medium">
          Page {currentPage} of {totalPages || 1} · {totalItems} total
        </p>
        <div className="flex gap-1.5">
          <Button
            variant="outline" size="sm"
            onClick={() => onPageChange(currentPage - 1)}
            disabled={currentPage === 1 || loading}
            className="h-7 px-2.5 text-xs border-border hover:bg-muted/50"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
            <span className="hidden sm:inline ml-1">Prev</span>
          </Button>
          <Button
            variant="outline" size="sm"
            onClick={() => onPageChange(currentPage + 1)}
            disabled={currentPage >= totalPages || loading}
            className="h-7 px-2.5 text-xs border-border hover:bg-muted/50"
          >
            <span className="hidden sm:inline mr-1">Next</span>
            <ChevronRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    )
  }

  // ── Sidebar filter sections ───────────────────────────────────────────────────

  function SignalFilterSidebar() {
    return (
      <div className="space-y-5">
        <div>
          <FilterLabel>Symbol</FilterLabel>
          <Select value={signalSymbolFilter || 'all'} onValueChange={v => { setSignalSymbolFilter(v === 'all' ? '' : v); setSignalsPage(1) }}>
            <SelectTrigger className="h-8 text-xs border-border bg-card"><SelectValue placeholder="All symbols" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All symbols</SelectItem>
              {availableSymbols.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div>
          <FilterLabel>Channel</FilterLabel>
          <Select value={signalChannelFilter || 'all'} onValueChange={v => { setSignalChannelFilter(v === 'all' ? '' : v); setSignalsPage(1) }}>
            <SelectTrigger className="h-8 text-xs border-border bg-card"><SelectValue placeholder="All channels" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All channels</SelectItem>
              {availableChannels.map(c => <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div>
          <FilterLabel>AI Verification</FilterLabel>
          <Select value={signalVerificationFilter || 'all'} onValueChange={v => { setSignalVerificationFilter(v === 'all' ? '' : v); setSignalsPage(1) }}>
            <SelectTrigger className="h-8 text-xs border-border bg-card"><SelectValue placeholder="All signals" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All signals</SelectItem>
              <SelectItem value="unverified">Unverified</SelectItem>
              <SelectItem value="verified">Verified (Any)</SelectItem>
              <SelectItem value="TRADE_SIGNAL">✅ Trade Signal</SelectItem>
              <SelectItem value="INFO_MESSAGE">ℹ️ Info Only</SelectItem>
              <SelectItem value="REPLY">💬 Reply/Update</SelectItem>
              <SelectItem value="WRONG_EXECUTION">❌ Wrong Execution</SelectItem>
              <SelectItem value="UNCLEAR">❓ Unclear</SelectItem>
              <SelectItem value="IMAGE_ONLY">🖼️ Image Only</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div>
          <FilterLabel>Status</FilterLabel>
          <Select value={signalStatusFilter || 'all'} onValueChange={v => { setSignalStatusFilter(v === 'all' ? '' : v); setSignalsPage(1) }}>
            <SelectTrigger className="h-8 text-xs border-border bg-card"><SelectValue placeholder="All statuses" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              {availableSignalStatuses.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div>
          <FilterLabel>Date Range</FilterLabel>
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="outline" className="w-full justify-start text-left font-normal h-8 text-xs border-border bg-card">
                <CalendarIcon className="mr-1.5 h-3 w-3 shrink-0 text-muted-foreground/70" />
                <span className="truncate">
                  {signalDateRange?.from
                    ? signalDateRange.to
                      ? `${format(signalDateRange.from, 'MMM d')} – ${format(signalDateRange.to, 'MMM d')}`
                      : format(signalDateRange.from, 'MMM d, y')
                    : 'Select range'}
                </span>
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-auto p-0" align="start">
              <Calendar
                mode="range"
                defaultMonth={signalDateRange?.from}
                selected={signalDateRange}
                onSelect={range => { setSignalDateRange(range); setSignalsPage(1) }}
                numberOfMonths={2}
              />
            </PopoverContent>
          </Popover>
        </div>

        {/* Database cleanup */}
        <div className="pt-2 border-t border-border">
          <FilterLabel>Database Cleanup</FilterLabel>
          <button
            onClick={openCleanup}
            className="w-full flex items-center justify-center gap-1.5 h-8 rounded-md text-xs font-semibold text-destructive border border-destructive/30 bg-destructive/5 hover:bg-destructive/10 transition-colors"
          >
            <Trash2 className="h-3.5 w-3.5" />
            Delete by Status
          </button>
        </div>
      </div>
    )
  }

  function TradeFilterSidebar() {
    return (
      <div className="space-y-5">
        <div>
          <FilterLabel>Symbol</FilterLabel>
          <Select value={symbolFilter || 'all'} onValueChange={v => { setSymbolFilter(v === 'all' ? '' : v); setTradesPage(1) }}>
            <SelectTrigger className="h-8 text-xs border-border bg-card"><SelectValue placeholder="All symbols" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All symbols</SelectItem>
              {availableSymbols.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div>
          <FilterLabel>Channel</FilterLabel>
          <Select value={channelFilter || 'all'} onValueChange={v => { setChannelFilter(v === 'all' ? '' : v); setTradesPage(1) }}>
            <SelectTrigger className="h-8 text-xs border-border bg-card"><SelectValue placeholder="All channels" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All channels</SelectItem>
              {availableChannels.map(c => <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div>
          <FilterLabel>Status</FilterLabel>
          <Select value={statusFilter || 'all'} onValueChange={v => { setStatusFilter(v === 'all' ? '' : v); setTradesPage(1) }}>
            <SelectTrigger className="h-8 text-xs border-border bg-card"><SelectValue placeholder="All statuses" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              {availableStatuses.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div>
          <FilterLabel>Outcome</FilterLabel>
          <Select value={outcomeFilter || 'all'} onValueChange={v => { setOutcomeFilter(v === 'all' ? '' : v); setTradesPage(1) }}>
            <SelectTrigger className="h-8 text-xs border-border bg-card"><SelectValue placeholder="All outcomes" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All outcomes</SelectItem>
              <SelectItem value="win">Win (Profit)</SelectItem>
              <SelectItem value="loss">Loss</SelectItem>
              <SelectItem value="breakeven">Breakeven</SelectItem>
            </SelectContent>
          </Select>
        </div>

      </div>
    )
  }

  function ActionFilterSidebar() {
    return (
      <div className="space-y-5">
        <div>
          <FilterLabel>Symbol</FilterLabel>
          <Select value={actionSymbolFilter || 'all'} onValueChange={v => { setActionSymbolFilter(v === 'all' ? '' : v); setActionsPage(1) }}>
            <SelectTrigger className="h-8 text-xs border-border bg-card"><SelectValue placeholder="All symbols" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All symbols</SelectItem>
              {availableSymbols.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div>
          <FilterLabel>Action Type</FilterLabel>
          <Select value={actionTypeFilter || 'all'} onValueChange={v => { setActionTypeFilter(v === 'all' ? '' : v); setActionsPage(1) }}>
            <SelectTrigger className="h-8 text-xs border-border bg-card"><SelectValue placeholder="All types" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All types</SelectItem>
              {availableActionTypes.map(t => <SelectItem key={t} value={t}>{t.replace(/_/g, ' ')}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div>
          <FilterLabel>Triggered By</FilterLabel>
          <Select value={triggeredByFilter || 'all'} onValueChange={v => { setTriggeredByFilter(v === 'all' ? '' : v); setActionsPage(1) }}>
            <SelectTrigger className="h-8 text-xs border-border bg-card"><SelectValue placeholder="All sources" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All sources</SelectItem>
              {availableTriggeredBy.map(s => <SelectItem key={s} value={s}>{s.replace(/_/g, ' ')}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
      </div>
    )
  }

  const currentHasFilters = activeTab === 'signals' ? signalHasFilters : activeTab === 'trades' ? tradeHasFilters : actionHasFilters
  const currentReset = activeTab === 'signals' ? resetSignalFilters : activeTab === 'trades' ? resetTradeFilters : resetActionFilters

  // ── Render ────────────────────────────────────────────────────────────────────

  return (
    <div className="flex min-h-full flex-col">
      <MobilePageHeader
        title="History"
        subtitle="Full Archive"
        hidden
        icon={<History className="h-5 w-5 text-primary" />}
      />

      {/* Desktop page header */}
      <header className="hidden md:flex sticky top-0 z-40 w-full tech-header">
        <div className="max-w-[1800px] w-full mx-auto flex h-14 items-center px-6 gap-3">
          <div className="p-1.5 rounded-lg bg-primary/10 border border-primary/20">
            <History className="h-5 w-5 text-primary" />
          </div>
          <div>
            <h1 className="text-sm font-bold text-foreground leading-none">History</h1>
            <p className="text-[10px] text-[#697188] font-semibold uppercase tracking-wider mt-0.5">Full Archive</p>
          </div>
        </div>
      </header>

      <Tabs value={activeTab} onValueChange={setActiveTab} className="flex-1 flex flex-col">

        {/* ── Tabs bar ──────────────────────────────────────────────────────── */}
        <div className="sticky top-14 z-30 hidden md:block bg-card border-b border-border">
          <div className="max-w-[1800px] mx-auto px-6 flex items-center gap-0">
            <TabsList className="h-10 bg-transparent gap-0 p-0 rounded-none">
              {[
                { value: 'signals', label: 'Signals', count: totalSignals },
                { value: 'trades', label: 'Trades', count: totalTrades },
                { value: 'actions', label: 'Actions', count: totalActions },
              ].map(tab => (
                <TabsTrigger
                  key={tab.value}
                  value={tab.value}
                  className="h-10 px-5 text-xs font-semibold rounded-none border-b-2 border-transparent
                    text-[#697188] data-[state=active]:text-primary data-[state=active]:border-primary
                    data-[state=active]:bg-transparent hover:text-foreground transition-colors"
                >
                  {tab.label}
                  <span className="ml-2 text-[10px] font-bold text-muted-foreground/70 tabular-nums">
                    {tab.count.toLocaleString()}
                  </span>
                </TabsTrigger>
              ))}
            </TabsList>
          </div>
        </div>

        {/* Mobile tabs */}
        <div className="md:hidden sticky top-0 z-30 bg-card border-b border-border px-3 pt-2">
          <TabsList className="grid w-full grid-cols-3 h-9 bg-muted rounded-xl">
            <TabsTrigger value="signals" className="text-xs font-bold rounded-lg data-[state=active]:bg-card data-[state=active]:text-primary data-[state=active]:shadow-sm">
              Signals ({totalSignals})
            </TabsTrigger>
            <TabsTrigger value="trades" className="text-xs font-bold rounded-lg data-[state=active]:bg-card data-[state=active]:text-primary data-[state=active]:shadow-sm">
              Trades ({totalTrades})
            </TabsTrigger>
            <TabsTrigger value="actions" className="text-xs font-bold rounded-lg data-[state=active]:bg-card data-[state=active]:text-primary data-[state=active]:shadow-sm">
              Acts ({totalActions})
            </TabsTrigger>
          </TabsList>
        </div>

        {/* ── Main body: sidebar + content ──────────────────────────────────── */}
        <div className="flex flex-1 max-w-[1800px] mx-auto w-full">

          {/* ── Filter sidebar (lg+) ─────────────────────────────────────────── */}
          <aside className="hidden lg:flex flex-col w-56 shrink-0 border-r border-border bg-card sticky top-24 self-start h-[calc(100vh-6rem)] overflow-y-auto">
            <div className="flex items-center justify-between px-4 pt-4 pb-3 border-b border-border">
              <div className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
                <SlidersHorizontal className="h-3.5 w-3.5 text-muted-foreground/70" />
                Filters
              </div>
              {currentHasFilters && (
                <button
                  onClick={currentReset}
                  className="flex items-center gap-1 text-[10px] text-primary hover:text-primary/80 font-semibold transition-colors"
                >
                  <RotateCcw className="h-2.5 w-2.5" />
                  Reset
                </button>
              )}
            </div>
            <div className="p-4">
              {activeTab === 'signals' && <SignalFilterSidebar />}
              {activeTab === 'trades' && <TradeFilterSidebar />}
              {activeTab === 'actions' && <ActionFilterSidebar />}
            </div>
          </aside>

          {/* ── Content area ────────────────────────────────────────────────── */}
          <div className="flex-1 min-w-0 flex flex-col">

            {/* Mobile filter strip */}
            <div className="lg:hidden px-3 pt-2 pb-2.5 border-b border-border bg-card">
              <div className="flex items-center gap-1.5 mb-1.5">
                <SlidersHorizontal className="h-3 w-3 text-muted-foreground/70 shrink-0" />
                <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70">Filters</span>
                {currentHasFilters && (
                  <button onClick={currentReset} className="ml-auto h-6 px-2 text-[10px] text-primary font-semibold border border-primary/30 rounded-md bg-primary/5 hover:bg-primary/10 transition-colors flex items-center gap-1">
                    <RotateCcw className="h-2.5 w-2.5" />
                    Reset
                  </button>
                )}
                {activeTab === 'signals' && (
                  <button
                    onClick={openCleanup}
                    className={`h-6 px-2 text-[10px] text-destructive font-semibold border border-destructive/30 rounded-md bg-destructive/5 hover:bg-destructive/10 transition-colors flex items-center gap-1 ${currentHasFilters ? '' : 'ml-auto'}`}
                  >
                    <Trash2 className="h-2.5 w-2.5" />
                    Cleanup
                  </button>
                )}
              </div>
              <div className="flex flex-wrap gap-1.5">
                {activeTab === 'signals' && (
                  <>
                    <Select value={signalSymbolFilter || 'all'} onValueChange={v => { setSignalSymbolFilter(v === 'all' ? '' : v); setSignalsPage(1) }}>
                      <SelectTrigger className="h-7 text-[10px] border-border bg-card flex-1 min-w-[90px] max-w-[130px]"><SelectValue placeholder="Symbol" /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All symbols</SelectItem>
                        {availableSymbols.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                      </SelectContent>
                    </Select>
                    <Select value={signalVerificationFilter || 'all'} onValueChange={v => { setSignalVerificationFilter(v === 'all' ? '' : v); setSignalsPage(1) }}>
                      <SelectTrigger className="h-7 text-[10px] border-border bg-card flex-1 min-w-[100px] max-w-[150px]"><SelectValue placeholder="Verification" /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All</SelectItem>
                        <SelectItem value="unverified">Unverified</SelectItem>
                        <SelectItem value="TRADE_SIGNAL">✅ Trade Signal</SelectItem>
                        <SelectItem value="INFO_MESSAGE">ℹ️ Info Only</SelectItem>
                      </SelectContent>
                    </Select>
                    <Select value={signalStatusFilter || 'all'} onValueChange={v => { setSignalStatusFilter(v === 'all' ? '' : v); setSignalsPage(1) }}>
                      <SelectTrigger className="h-7 text-[10px] border-border bg-card flex-1 min-w-[90px] max-w-[130px]"><SelectValue placeholder="Status" /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All statuses</SelectItem>
                        {availableSignalStatuses.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </>
                )}
                {activeTab === 'trades' && (
                  <>
                    <Select value={symbolFilter || 'all'} onValueChange={v => { setSymbolFilter(v === 'all' ? '' : v); setTradesPage(1) }}>
                      <SelectTrigger className="h-7 text-[10px] border-border bg-card flex-1 min-w-[90px] max-w-[130px]"><SelectValue placeholder="Symbol" /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All symbols</SelectItem>
                        {availableSymbols.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                      </SelectContent>
                    </Select>
                    <Select value={statusFilter || 'all'} onValueChange={v => { setStatusFilter(v === 'all' ? '' : v); setTradesPage(1) }}>
                      <SelectTrigger className="h-7 text-[10px] border-border bg-card flex-1 min-w-[90px] max-w-[130px]"><SelectValue placeholder="Status" /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All statuses</SelectItem>
                        {availableStatuses.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                      </SelectContent>
                    </Select>
                    <Select value={outcomeFilter || 'all'} onValueChange={v => { setOutcomeFilter(v === 'all' ? '' : v); setTradesPage(1) }}>
                      <SelectTrigger className="h-7 text-[10px] border-border bg-card flex-1 min-w-[90px] max-w-[130px]"><SelectValue placeholder="Outcome" /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All outcomes</SelectItem>
                        <SelectItem value="win">Win</SelectItem>
                        <SelectItem value="loss">Loss</SelectItem>
                      </SelectContent>
                    </Select>
                  </>
                )}
                {activeTab === 'actions' && (
                  <>
                    <Select value={actionSymbolFilter || 'all'} onValueChange={v => { setActionSymbolFilter(v === 'all' ? '' : v); setActionsPage(1) }}>
                      <SelectTrigger className="h-7 text-[10px] border-border bg-card flex-1 min-w-[90px] max-w-[130px]"><SelectValue placeholder="Symbol" /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All symbols</SelectItem>
                        {availableSymbols.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                      </SelectContent>
                    </Select>
                    <Select value={actionTypeFilter || 'all'} onValueChange={v => { setActionTypeFilter(v === 'all' ? '' : v); setActionsPage(1) }}>
                      <SelectTrigger className="h-7 text-[10px] border-border bg-card flex-1 min-w-[100px] max-w-[160px]"><SelectValue placeholder="Type" /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All types</SelectItem>
                        {availableActionTypes.map(t => <SelectItem key={t} value={t}>{t.replace(/_/g, ' ')}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </>
                )}
              </div>
            </div>

            {/* ── Tab content ──────────────────────────────────────────────── */}
            <div className="flex-1 p-3 md:p-5">
              <TabsContent value="signals" className="mt-0">
                <SignalsTable signals={signals} onSignalVerified={fetchSignals} onSignalDeleted={fetchSignals} />
                <PaginationControls currentPage={signalsPage} totalItems={filteredSignalTotal} onPageChange={setSignalsPage} />
              </TabsContent>

              <TabsContent value="trades" className="mt-0">
                <TradesTable trades={trades} />
                <PaginationControls currentPage={tradesPage} totalItems={totalTrades} onPageChange={setTradesPage} />
              </TabsContent>

              <TabsContent value="actions" className="mt-0">
                <TradeActionsTable actions={actions} />
                <PaginationControls currentPage={actionsPage} totalItems={totalActions} onPageChange={setActionsPage} />
              </TabsContent>
            </div>
          </div>
        </div>
      </Tabs>

      {/* Cleanup dialog */}
      <Dialog open={cleanupOpen} onOpenChange={open => { setCleanupOpen(open); if (!open) { setCleanupStatus(''); setCleanupCount(null); setCleanupConfirm(false) } }}>
        <DialogContent className="sm:max-w-[420px]">
          <DialogHeader>
            <div className="flex items-center gap-3 mb-1">
              <div className="w-9 h-9 rounded-full bg-destructive/10 flex items-center justify-center shrink-0">
                <Trash2 className="h-4 w-4 text-destructive" />
              </div>
              <div>
                <DialogTitle>Delete Signals by Status</DialogTitle>
                <DialogDescription className="text-xs mt-0.5">
                  Permanently removes all signals (and their linked trades) with the selected status.
                </DialogDescription>
              </div>
            </div>
          </DialogHeader>

          <div className="space-y-4 py-1">
            <div>
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1.5">Select Status</p>
              <Select
                value={cleanupStatus || 'none'}
                onValueChange={v => handleCleanupStatusChange(v === 'none' ? '' : v)}
              >
                <SelectTrigger className="h-9 text-sm border-border bg-card">
                  <SelectValue placeholder="Choose a status…" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none" disabled>Choose a status…</SelectItem>
                  {availableSignalStatuses.map(s => (
                    <SelectItem key={s} value={s}>{s}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {cleanupStatus && (
              <div className={`rounded-lg border p-3 text-sm flex items-start gap-2.5 ${
                cleanupConfirm
                  ? 'bg-destructive/10 border-destructive/30 text-destructive'
                  : 'bg-muted border-border text-muted-foreground'
              }`}>
                {cleanupCountLoading ? (
                  <RefreshCw className="h-4 w-4 animate-spin mt-0.5 shrink-0" />
                ) : (
                  <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
                )}
                <span>
                  {cleanupCountLoading
                    ? 'Counting matching trades…'
                    : cleanupCount === null
                      ? 'Unable to fetch count.'
                      : cleanupCount === 0
                        ? `No signals found with status "${cleanupStatus}".`
                        : cleanupConfirm
                          ? `Are you sure? This will permanently delete ${cleanupCount} signal${cleanupCount !== 1 ? 's' : ''} with status "${cleanupStatus}" and all linked trades. This cannot be undone.`
                          : `${cleanupCount} signal${cleanupCount !== 1 ? 's' : ''} with status "${cleanupStatus}" will be permanently deleted (including linked trades).`
                  }
                </span>
              </div>
            )}
          </div>

          <DialogFooter className="gap-2 pt-1">
            <Button
              variant="outline"
              onClick={() => { setCleanupOpen(false); setCleanupStatus(''); setCleanupCount(null); setCleanupConfirm(false) }}
              disabled={cleanupDeleting}
              className="text-xs"
            >
              Cancel
            </Button>
            <Button
              onClick={handleCleanupDelete}
              disabled={!cleanupStatus || cleanupCount === 0 || cleanupCountLoading || cleanupDeleting}
              className={`text-xs text-white ${cleanupConfirm ? 'bg-destructive hover:bg-destructive/90' : 'bg-rose-600 hover:bg-rose-700'}`}
            >
              {cleanupDeleting
                ? <><RefreshCw className="h-3.5 w-3.5 animate-spin mr-1.5" />Deleting…</>
                : cleanupConfirm
                  ? <><AlertTriangle className="h-3.5 w-3.5 mr-1.5" />Confirm Delete</>
                  : <><Trash2 className="h-3.5 w-3.5 mr-1.5" />Delete {cleanupCount !== null && cleanupCount > 0 ? `(${cleanupCount})` : ''}</>
              }
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
