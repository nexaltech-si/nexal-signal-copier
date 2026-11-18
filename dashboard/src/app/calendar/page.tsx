'use client'

import { useState, useEffect, useCallback, useMemo } from 'react'
import {
  Calendar,
  RefreshCw,
  Filter,
  Globe,
  Loader2,
  Clock,
  CalendarDays,
  X,
  LayoutGrid,
  Table,
  Share2,
} from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import MobilePageHeader from '@/components/MobilePageHeader'
import { CurrencyFlag } from '@/components/InstrumentSymbol'
import ShareNewsDialog from '@/components/ShareNewsDialog'
import type { ShareEvent } from '@/lib/types/newsShare'

// ── Types ──────────────────────────────────────────────────────
type Currency = 'USD' | 'EUR' | 'GBP' | 'JPY' | 'AUD' | 'CAD' | 'NZD' | 'CHF'
type Importance = 'High' | 'Medium' | 'Low'
type DateFilter = 'all' | 'today' | 'week' | 'mon' | 'tue' | 'wed' | 'thu' | 'fri'
type ViewMode = 'table' | 'grid'

interface EconomicEvent {
  id: string
  date: string
  time: string
  currency: string
  event: string
  importance: Importance
  previous: string
  forecast: string
  actual: string
  localTime?: string
  localDate?: string
}

// ── Persisted filter shape ─────────────────────────────────────
interface SavedFilters {
  currencies: string[]
  importances: Importance[]
  dateFilter: DateFilter
  viewMode: ViewMode
}

const STORAGE_KEY = 'calendar_filters_v2'

function loadSavedFilters(): SavedFilters {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { currencies: [], importances: [], dateFilter: 'all', viewMode: 'table' }
    return JSON.parse(raw) as SavedFilters
  } catch {
    return { currencies: [], importances: [], dateFilter: 'all', viewMode: 'table' }
  }
}

function persistFilters(f: SavedFilters) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(f)) } catch { /* noop */ }
}

// CurrencyFlag is now imported from '@/components/InstrumentSymbol' (shared).

// ── Timezone / Date Helpers ────────────────────────────────────

function convertISOtoLocal(
  isoDateStr: string,
  userTz: string
): { localTime: string; localDate: string } {
  try {
    const d = new Date(isoDateStr)
    if (isNaN(d.getTime())) throw new Error('Invalid date')
    const fmt = new Intl.DateTimeFormat('en-CA', {
      timeZone: userTz,
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hour12: false,
    })
    const [localDate, localTime] = fmt.format(d).split(', ')
    return { localDate: localDate ?? '', localTime: localTime ?? '' }
  } catch {
    return { localDate: '', localTime: '' }
  }
}

function getTzAbbr(userTz: string): string {
  try {
    const parts = new Intl.DateTimeFormat('en-US', { timeZone: userTz, timeZoneName: 'short' }).formatToParts(new Date())
    return parts.find((p) => p.type === 'timeZoneName')?.value ?? userTz
  } catch { return userTz }
}

function getLocalDateStr(userTz: string): string {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: userTz, year: 'numeric', month: '2-digit', day: '2-digit',
  }).format(new Date())
}

/** Returns Mon–Sun date strings for the current calendar week in user's tz. */
function getCurrentWeekDates(userTz: string): Record<string, string> {
  const now = new Date()
  const weekdayName = new Intl.DateTimeFormat('en-US', { timeZone: userTz, weekday: 'long' }).format(now)
  const idx = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'].indexOf(weekdayName)
  const offsetToMonday = idx === 0 ? -6 : 1 - idx
  const nowMs = Date.now()
  const keys = ['mon','tue','wed','thu','fri','sat','sun'] as const
  const result: Record<string, string> = {}
  for (let i = 0; i < 7; i++) {
    result[keys[i]] = new Intl.DateTimeFormat('en-CA', {
      timeZone: userTz, year: 'numeric', month: '2-digit', day: '2-digit',
    }).format(new Date(nowMs + (offsetToMonday + i) * 86_400_000))
  }
  return result
}

// ── Constants ──────────────────────────────────────────────────
const ALL_CURRENCIES: Currency[] = ['USD', 'EUR', 'GBP', 'JPY', 'AUD', 'CAD', 'NZD', 'CHF']
const IMPORTANCE_LEVELS: Importance[] = ['High', 'Medium', 'Low']

const IMPORTANCE_CONFIG = {
  High:   { dot: 'bg-red-500',   bg: 'bg-red-50',   text: 'text-destructive',   label: 'High' },
  Medium: { dot: 'bg-amber-500', bg: 'bg-gold/10',  text: 'text-gold', label: 'Med'  },
  Low:    { dot: 'bg-gray-400',  bg: 'bg-gray-50',   text: 'text-gray-600',  label: 'Low'  },
}

const DATE_FILTER_OPTIONS: Array<{ key: DateFilter; label: string }> = [
  { key: 'all',   label: 'ALL'       },
  { key: 'today', label: 'Today'     },
  { key: 'week',  label: 'This Week' },
  { key: 'mon',   label: 'Mon'       },
  { key: 'tue',   label: 'Tue'       },
  { key: 'wed',   label: 'Wed'       },
  { key: 'thu',   label: 'Thu'       },
  { key: 'fri',   label: 'Fri'       },
]

// ── Raw event shape from API ───────────────────────────────────
interface RawNewsEvent {
  title?: string; newsTitle?: string
  country?: string; newsCountry?: string
  date?: string
  impact?: string; newsImpact?: string
  forecast?: string; previous?: string; actual?: string
}

function mapRawEvent(raw: RawNewsEvent, idx: number, userTz: string): EconomicEvent | null {
  const title    = raw.title    ?? raw.newsTitle   ?? ''
  const country  = raw.country  ?? raw.newsCountry ?? ''
  const isoDate  = raw.date     ?? ''
  const impact   = raw.impact   ?? raw.newsImpact  ?? 'Low'
  if (!isoDate) return null
  const { localDate, localTime } = convertISOtoLocal(isoDate, userTz)
  if (!localDate || !localTime) return null
  const importance: Importance = impact === 'High' ? 'High' : impact === 'Medium' ? 'Medium' : 'Low'
  return {
    id: String(idx), date: localDate, time: localTime,
    localDate, localTime, currency: country, event: title, importance,
    previous: raw.previous ?? '—', forecast: raw.forecast ?? '—', actual: raw.actual ?? '—',
  }
}

function groupByLocalDate(events: EconomicEvent[]): [string, EconomicEvent[]][] {
  const groups = new Map<string, EconomicEvent[]>()
  for (const ev of events) {
    const key = ev.localDate ?? ev.date
    const existing = groups.get(key) ?? []
    existing.push(ev)
    groups.set(key, existing)
  }
  return Array.from(groups.entries()).sort(([a], [b]) => a.localeCompare(b))
}

function formatDateLabel(dateStr: string, userTz: string): string {
  const fmt = new Intl.DateTimeFormat('en-CA', { timeZone: userTz, year: 'numeric', month: '2-digit', day: '2-digit' })
  if (dateStr === fmt.format(new Date()))                       return 'Today'
  if (dateStr === fmt.format(new Date(Date.now() + 86_400_000))) return 'Tomorrow'
  return new Date(dateStr + 'T00:00:00').toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' })
}

// ── Small reusable filter button ───────────────────────────────
function FilterBtn({
  active, onClick, children, className,
}: { active: boolean; onClick: () => void; children: React.ReactNode; className?: string }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'px-3 py-1.5 rounded-lg text-xs font-semibold transition-all select-none',
        active ? 'bg-primary text-white shadow-sm' : 'bg-muted text-muted-foreground hover:bg-border',
        className,
      )}
    >
      {children}
    </button>
  )
}

// ── Grid Event Card ────────────────────────────────────────────
function GridEventCard({ ev }: { ev: EconomicEvent }) {
  const cfg = IMPORTANCE_CONFIG[ev.importance]
  return (
    <Card className="border-border bg-card/90 backdrop-blur-[14px] overflow-hidden hover:shadow-md transition-shadow">
      <CardContent className="p-3 flex flex-col gap-2.5">
        {/* Top row: time + importance */}
        <div className="flex items-center justify-between">
          <span className="text-xs font-mono font-bold tabular-nums text-foreground">
            {ev.localTime ?? ev.time}
          </span>
          <Badge className={cn('border-0 px-1.5 py-0 text-[10px] font-bold', cfg.bg, cfg.text)}>
            <span className={cn('w-1.5 h-1.5 rounded-full mr-1 inline-block', cfg.dot)} />
            {cfg.label}
          </Badge>
        </div>

        {/* Currency with flag */}
        <div className="flex items-center gap-1.5">
          <CurrencyFlag currency={ev.currency} size={18} />
          <Badge className="font-mono text-[10px] bg-muted text-muted-foreground border-0 px-2 py-0.5 font-bold">
            {ev.currency}
          </Badge>
        </div>

        {/* Event title */}
        <p className="text-xs font-semibold text-foreground/90 leading-snug line-clamp-2 flex-1">
          {ev.event}
        </p>

        {/* Data row */}
        <div className="grid grid-cols-3 gap-1.5 pt-1 border-t border-border/50">
          <div className="flex flex-col gap-0.5">
            <span className="text-[9px] font-bold text-muted-foreground/60 uppercase tracking-wider">Prev</span>
            <span className="text-[11px] font-mono font-semibold tabular-nums text-muted-foreground">{ev.previous || '—'}</span>
          </div>
          <div className="flex flex-col gap-0.5">
            <span className="text-[9px] font-bold text-muted-foreground/60 uppercase tracking-wider">Fcst</span>
            <span className="text-[11px] font-mono font-semibold tabular-nums text-muted-foreground">{ev.forecast || '—'}</span>
          </div>
          <div className="flex flex-col gap-0.5">
            <span className="text-[9px] font-bold text-muted-foreground/60 uppercase tracking-wider">Act</span>
            <span className={cn(
              'text-[11px] font-mono font-bold tabular-nums',
              ev.actual === '—' ? 'text-muted-foreground/50' : 'text-primary'
            )}>
              {ev.actual || '—'}
            </span>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

// ── Component ──────────────────────────────────────────────────
export default function CalendarPage() {
  const [events,       setEvents]       = useState<EconomicEvent[]>([])
  const [loading,      setLoading]      = useState(true)
  const [initialLoad,  setInitialLoad]  = useState(true)
  const [filtersReady, setFiltersReady] = useState(false)

  // ── Filter state ─────────────────────────────────────────────
  const [selectedCurrencies,  setSelectedCurrencies]  = useState<string[]>([])
  const [selectedImportances, setSelectedImportances] = useState<Importance[]>([])
  const [dateFilter,           setDateFilter]          = useState<DateFilter>('all')
  const [viewMode,             setViewMode]            = useState<ViewMode>('table')

  const userTz     = useMemo(() => Intl.DateTimeFormat().resolvedOptions().timeZone, [])
  const tzAbbr     = useMemo(() => getTzAbbr(userTz), [userTz])
  const todayLocal = useMemo(() => getLocalDateStr(userTz), [userTz])
  const weekDates  = useMemo(() => getCurrentWeekDates(userTz), [userTz])

  // Load saved filters once on mount (client-only)
  useEffect(() => {
    const saved = loadSavedFilters()
    setSelectedCurrencies(saved.currencies)
    setSelectedImportances(saved.importances)
    setDateFilter(saved.dateFilter)
    setViewMode(saved.viewMode ?? 'table')
    setFiltersReady(true)
  }, [])

  // Persist filters whenever they change (after initial load)
  useEffect(() => {
    if (!filtersReady) return
    persistFilters({ currencies: selectedCurrencies, importances: selectedImportances, dateFilter, viewMode })
  }, [selectedCurrencies, selectedImportances, dateFilter, viewMode, filtersReady])

  // ── Load events ──────────────────────────────────────────────
  const loadEvents = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/news-calendar')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      const rawEvents: RawNewsEvent[] = Array.isArray(json.events) ? json.events : []
      const converted = rawEvents
        .map((raw, idx) => mapRawEvent(raw, idx, userTz))
        .filter((ev): ev is EconomicEvent => ev !== null)
      setEvents(converted)
    } catch (err) {
      console.error('Failed to load news calendar:', err)
      setEvents([])
    } finally {
      setLoading(false)
      setInitialLoad(false)
    }
  }, [userTz])

  useEffect(() => { loadEvents() }, [loadEvents])
  useEffect(() => {
    const id = setInterval(loadEvents, 60_000)
    return () => clearInterval(id)
  }, [loadEvents])

  // ── Toggle helpers ───────────────────────────────────────────
  const toggleCurrency = (cur: string) =>
    setSelectedCurrencies(prev => prev.includes(cur) ? prev.filter(c => c !== cur) : [...prev, cur])

  const toggleImportance = (imp: Importance) =>
    setSelectedImportances(prev => prev.includes(imp) ? prev.filter(i => i !== imp) : [...prev, imp])

  const resetAll = () => {
    setSelectedCurrencies([])
    setSelectedImportances([])
    setDateFilter('all')
  }

  // ── Filtering ────────────────────────────────────────────────
  const filteredEvents = useMemo(() => {
    return events.filter(ev => {
      if (selectedCurrencies.length  > 0 && !selectedCurrencies.includes(ev.currency))   return false
      if (selectedImportances.length > 0 && !selectedImportances.includes(ev.importance)) return false
      const evDate = ev.localDate ?? ev.date
      if (dateFilter === 'today' && evDate !== todayLocal)                         return false
      if (dateFilter === 'week'  && !Object.values(weekDates).includes(evDate))    return false
      if (['mon','tue','wed','thu','fri'].includes(dateFilter) && evDate !== weekDates[dateFilter]) return false
      return true
    })
  }, [events, selectedCurrencies, selectedImportances, dateFilter, todayLocal, weekDates])

  const grouped = useMemo(() => groupByLocalDate(filteredEvents), [filteredEvents])

  // ── Share ────────────────────────────────────────────────────
  const [shareOpen, setShareOpen] = useState(false)

  // Flatten the grouped events (same order + date labels as on screen) into the
  // shape the share dialog consumes.
  const shareEvents: ShareEvent[] = useMemo(
    () =>
      grouped.flatMap(([date, dateEvents]) =>
        dateEvents.map((ev) => ({
          time: ev.localTime ?? ev.time,
          currency: ev.currency,
          event: ev.event,
          importance: ev.importance,
          previous: ev.previous,
          forecast: ev.forecast,
          actual: ev.actual,
          dateKey: date,
          dateLabel: formatDateLabel(date, userTz),
        })),
      ),
    [grouped, userTz],
  )

  const sharePeriodLabel = useMemo(() => {
    const opt = DATE_FILTER_OPTIONS.find((o) => o.key === dateFilter)
    if (dateFilter === 'all') return 'Upcoming'
    return opt?.label ?? 'Events'
  }, [dateFilter])

  const activeFilterCount =
    (selectedCurrencies.length  > 0 ? 1 : 0) +
    (selectedImportances.length > 0 ? 1 : 0) +
    (dateFilter !== 'all'           ? 1 : 0)
  const hasActiveFilters = activeFilterCount > 0

  // ── Loading state ────────────────────────────────────────────
  if (initialLoad) {
    return (
      <div className="flex h-[calc(100vh-4rem)] items-center justify-center">
        <div className="animate-pulse flex flex-col items-center gap-4">
          <Calendar className="h-12 w-12 text-muted-foreground/20" />
          <p className="text-sm font-medium text-muted-foreground">Loading economic calendar...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col min-h-full pb-10">
      <MobilePageHeader
        title="Calendar"
        subtitle="Economic Events"
        hidden
        icon={<Calendar className="h-5 w-5 text-primary" />}
      />

      {/* Desktop Header */}
      <header className="hidden md:flex sticky top-0 z-40 w-full tech-header">
        <div className="max-w-[1800px] w-full mx-auto flex h-14 items-center px-6 gap-3">
          <div className="p-1.5 rounded-lg bg-primary/10 border border-primary/20">
            <Calendar className="h-5 w-5 text-primary" />
          </div>
          <div className="flex flex-col">
            <h1 className="text-sm font-bold text-foreground leading-none">Economic Calendar</h1>
            <p className="text-[10px] text-[#6b7288] font-bold uppercase tracking-wider mt-1">Events &amp; Releases</p>
          </div>
          <div className="flex items-center gap-1.5 ml-3 px-2 py-1 rounded-md bg-muted">
            <Clock className="h-3 w-3 text-muted-foreground/70" />
            <span className="text-[10px] font-semibold text-muted-foreground">Times in {tzAbbr}</span>
          </div>
          <div className="ml-auto flex items-center gap-2">
            {hasActiveFilters && (
              <>
                <Badge variant="secondary" className="text-[10px] font-bold px-2 py-0.5 border-0 bg-primary/10 text-primary">
                  {activeFilterCount} filter{activeFilterCount > 1 ? 's' : ''} active
                </Badge>
                <button
                  onClick={resetAll}
                  className="flex items-center gap-1 text-[10px] font-semibold text-muted-foreground/70 hover:text-muted-foreground transition-colors"
                >
                  <X className="h-3 w-3" /> Reset
                </button>
              </>
            )}
            <div className="h-4 w-px bg-muted mx-1" />
            {/* View toggle */}
            <div className="flex items-center rounded-lg border border-border overflow-hidden">
              <button
                onClick={() => setViewMode('table')}
                className={cn(
                  'flex items-center gap-1.5 px-2.5 py-1.5 text-[10px] font-semibold transition-colors',
                  viewMode === 'table' ? 'bg-primary text-white' : 'text-muted-foreground hover:bg-muted'
                )}
              >
                <Table className="h-3 w-3" />
                Table
              </button>
              <button
                onClick={() => setViewMode('grid')}
                className={cn(
                  'flex items-center gap-1.5 px-2.5 py-1.5 text-[10px] font-semibold transition-colors',
                  viewMode === 'grid' ? 'bg-primary text-white' : 'text-muted-foreground hover:bg-muted'
                )}
              >
                <LayoutGrid className="h-3 w-3" />
                Grid
              </button>
            </div>
            <div className="h-4 w-px bg-muted mx-1" />
            <Button
              variant="outline"
              size="sm"
              className="h-7 gap-1.5 text-[11px] font-semibold"
              onClick={() => setShareOpen(true)}
              disabled={filteredEvents.length === 0}
            >
              <Share2 className="h-3.5 w-3.5" />
              Share
            </Button>
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={loadEvents} disabled={loading}>
              <RefreshCw className={cn('h-3.5 w-3.5 text-muted-foreground/70', loading && 'animate-spin')} />
            </Button>
          </div>
        </div>
      </header>

      <main className="flex-1 px-3 md:px-4 py-4 md:py-6 space-y-4 md:space-y-6 max-w-[1800px] mx-auto w-full">

        {/* ── Currency Filter ─────────────────────────────────── */}
        <Card className="border-border bg-card/90 backdrop-blur-[14px]">
          <CardContent className="p-3 md:p-4">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <Globe className="h-4 w-4 text-primary" />
                <span className="text-xs font-bold text-muted-foreground uppercase tracking-wider">Currency</span>
                {selectedCurrencies.length > 0 && (
                  <Badge className="text-[10px] font-bold px-1.5 py-0 border-0 bg-primary/10 text-primary">
                    {selectedCurrencies.length} selected
                  </Badge>
                )}
              </div>
              {selectedCurrencies.length > 0 && (
                <button
                  onClick={() => setSelectedCurrencies([])}
                  className="text-[10px] font-semibold text-muted-foreground/70 hover:text-muted-foreground transition-colors flex items-center gap-0.5"
                >
                  <X className="h-3 w-3" /> Clear
                </button>
              )}
            </div>
            <div className="flex flex-wrap gap-1.5 md:gap-2">
              <FilterBtn active={selectedCurrencies.length === 0} onClick={() => setSelectedCurrencies([])}>
                ALL
              </FilterBtn>
              {ALL_CURRENCIES.map((cur) => (
                <FilterBtn
                  key={cur}
                  active={selectedCurrencies.includes(cur)}
                  onClick={() => toggleCurrency(cur)}
                  className="font-mono tabular-nums"
                >
                  <span className="flex items-center gap-1.5">
                    <CurrencyFlag currency={cur} size={14} />
                    {cur}
                  </span>
                </FilterBtn>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* ── Importance + Period in a 2-col grid on md+ ──────── */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 md:gap-4">

          {/* Importance Filter */}
          <Card className="border-border bg-card/90 backdrop-blur-[14px]">
            <CardContent className="p-3 md:p-4">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <Filter className="h-4 w-4 text-primary" />
                  <span className="text-xs font-bold text-muted-foreground uppercase tracking-wider">Importance</span>
                  {selectedImportances.length > 0 && (
                    <Badge className="text-[10px] font-bold px-1.5 py-0 border-0 bg-primary/10 text-primary">
                      {selectedImportances.length} selected
                    </Badge>
                  )}
                </div>
                {selectedImportances.length > 0 && (
                  <button
                    onClick={() => setSelectedImportances([])}
                    className="text-[10px] font-semibold text-muted-foreground/70 hover:text-muted-foreground transition-colors flex items-center gap-0.5"
                  >
                    <X className="h-3 w-3" /> Clear
                  </button>
                )}
              </div>
              <div className="flex flex-wrap gap-1.5 md:gap-2">
                <FilterBtn active={selectedImportances.length === 0} onClick={() => setSelectedImportances([])}>
                  ALL
                </FilterBtn>
                {IMPORTANCE_LEVELS.map((imp) => {
                  const cfg = IMPORTANCE_CONFIG[imp]
                  const active = selectedImportances.includes(imp)
                  return (
                    <FilterBtn key={imp} active={active} onClick={() => toggleImportance(imp)}>
                      <span className="flex items-center gap-1.5">
                        <span className={cn('w-2 h-2 rounded-full', active ? 'bg-card' : cfg.dot)} />
                        {imp}
                      </span>
                    </FilterBtn>
                  )
                })}
              </div>
            </CardContent>
          </Card>

          {/* Date / Period Filter */}
          <Card className="border-border bg-card/90 backdrop-blur-[14px]">
            <CardContent className="p-3 md:p-4">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <CalendarDays className="h-4 w-4 text-primary" />
                  <span className="text-xs font-bold text-muted-foreground uppercase tracking-wider">Period</span>
                </div>
                {dateFilter !== 'all' && (
                  <button
                    onClick={() => setDateFilter('all')}
                    className="text-[10px] font-semibold text-muted-foreground/70 hover:text-muted-foreground transition-colors flex items-center gap-0.5"
                  >
                    <X className="h-3 w-3" /> Clear
                  </button>
                )}
              </div>
              <div className="flex flex-wrap gap-1.5 md:gap-2">
                {DATE_FILTER_OPTIONS.map(({ key, label }) => (
                  <FilterBtn key={key} active={dateFilter === key} onClick={() => setDateFilter(key)}>
                    {label}
                  </FilterBtn>
                ))}
              </div>
              {dateFilter !== 'all' && dateFilter !== 'today' && dateFilter !== 'week' && (
                <p className="mt-2 text-[10px] text-muted-foreground/70 font-medium">
                  Showing {weekDates[dateFilter]}
                </p>
              )}
            </CardContent>
          </Card>
        </div>

        {/* ── Mobile controls bar ──────────────────────────────── */}
        <div className="md:hidden flex items-center justify-between px-1">
          {hasActiveFilters ? (
            <span className="text-[10px] font-semibold text-muted-foreground">
              {activeFilterCount} filter{activeFilterCount > 1 ? 's' : ''} active · {filteredEvents.length} events
            </span>
          ) : (
            <span className="text-[10px] font-semibold text-muted-foreground">{filteredEvents.length} events</span>
          )}
          <div className="flex items-center gap-2">
            {hasActiveFilters && (
              <button onClick={resetAll} className="flex items-center gap-1 text-[10px] font-semibold text-primary hover:text-primary/80">
                <X className="h-3 w-3" /> Reset
              </button>
            )}
            <button
              onClick={() => setShareOpen(true)}
              disabled={filteredEvents.length === 0}
              className="flex items-center gap-1 text-[10px] font-semibold text-primary hover:text-primary/80 disabled:opacity-40"
            >
              <Share2 className="h-3 w-3" /> Share
            </button>
            {/* Mobile view toggle */}
            <div className="flex items-center rounded-lg border border-border overflow-hidden">
              <button
                onClick={() => setViewMode('table')}
                className={cn(
                  'flex items-center gap-1 px-2 py-1 text-[10px] font-semibold transition-colors',
                  viewMode === 'table' ? 'bg-primary text-white' : 'text-muted-foreground'
                )}
              >
                <Table className="h-3 w-3" />
              </button>
              <button
                onClick={() => setViewMode('grid')}
                className={cn(
                  'flex items-center gap-1 px-2 py-1 text-[10px] font-semibold transition-colors',
                  viewMode === 'grid' ? 'bg-primary text-white' : 'text-muted-foreground'
                )}
              >
                <LayoutGrid className="h-3 w-3" />
              </button>
            </div>
          </div>
        </div>

        {/* ── Events List ──────────────────────────────────────── */}
        {loading && events.length > 0 ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground/70" />
          </div>
        ) : filteredEvents.length === 0 ? (
          <Card className="border-border bg-card/90 backdrop-blur-[14px]">
            <CardContent className="flex flex-col items-center py-12">
              <Calendar className="h-12 w-12 text-muted-foreground/50 mb-3" />
              <p className="text-sm font-semibold text-muted-foreground">No events match your filters</p>
              <p className="text-xs text-muted-foreground/70 mt-1">Try adjusting the filters above</p>
              {hasActiveFilters && (
                <button onClick={resetAll} className="mt-3 text-xs font-semibold text-primary hover:text-primary/80">
                  Reset all filters
                </button>
              )}
            </CardContent>
          </Card>
        ) : (
          grouped.map(([date, dateEvents]) => (
            <div key={date}>
              {/* Date Header */}
              <div className="flex items-center gap-2 mb-3">
                <Calendar className="h-4 w-4 text-primary" />
                <h2 className="text-sm font-bold text-foreground">{formatDateLabel(date, userTz)}</h2>
                <span className="text-[10px] text-muted-foreground/70 font-medium">({dateEvents.length} events)</span>
              </div>

              {/* ── Mobile: Card View ─────────────────────────── */}
              <div className="md:hidden space-y-2">
                {dateEvents.map((ev) => {
                  const cfg = IMPORTANCE_CONFIG[ev.importance]
                  return (
                    <Card
                      key={ev.id}
                      className="border-border bg-card/90 backdrop-blur-[14px] overflow-hidden"
                    >
                      <CardContent className="p-3">
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-mono font-bold tabular-nums text-foreground">{ev.localTime ?? ev.time}</span>
                            <Badge className={cn('border-0 px-1.5 py-0 text-[10px] font-bold', cfg.bg, cfg.text)}>
                              <span className={cn('w-1.5 h-1.5 rounded-full mr-1 inline-block', cfg.dot)} />
                              {cfg.label}
                            </Badge>
                          </div>
                          <div className="flex items-center gap-1.5">
                            <CurrencyFlag currency={ev.currency} size={16} />
                            <Badge className="font-mono text-[10px] bg-muted text-muted-foreground border-0 px-2 py-0 font-bold">
                              {ev.currency}
                            </Badge>
                          </div>
                        </div>
                        <p className="text-sm font-bold text-foreground/90 mb-2 leading-tight">{ev.event}</p>
                        <div className="grid grid-cols-3 gap-2">
                          <div className="flex flex-col">
                            <span className="text-[9px] font-bold text-muted-foreground/70 uppercase tracking-wider">Previous</span>
                            <span className="text-xs font-mono font-semibold tabular-nums text-foreground/80">{ev.previous || '—'}</span>
                          </div>
                          <div className="flex flex-col">
                            <span className="text-[9px] font-bold text-muted-foreground/70 uppercase tracking-wider">Forecast</span>
                            <span className="text-xs font-mono font-semibold tabular-nums text-foreground/80">{ev.forecast || '—'}</span>
                          </div>
                          <div className="flex flex-col">
                            <span className="text-[9px] font-bold text-muted-foreground/70 uppercase tracking-wider">Actual</span>
                            <span className="text-xs font-mono font-semibold tabular-nums text-primary">{ev.actual || '—'}</span>
                          </div>
                        </div>
                      </CardContent>
                    </Card>
                  )
                })}
              </div>

              {/* ── Desktop: Table View ───────────────────────── */}
              {viewMode === 'table' && (
                <Card className="hidden md:block border-border bg-card mb-6">
                  <div className="overflow-x-auto">
                    <table className="w-full">
                      <thead>
                        <tr className="border-b border-border/50">
                          <th className="text-left px-4 py-3 text-[10px] font-bold text-muted-foreground/70 uppercase tracking-wider w-[72px]">Time</th>
                          <th className="text-left px-4 py-3 text-[10px] font-bold text-muted-foreground/70 uppercase tracking-wider w-[100px]">Currency</th>
                          <th className="text-left px-4 py-3 text-[10px] font-bold text-muted-foreground/70 uppercase tracking-wider">Event</th>
                          <th className="text-left px-4 py-3 text-[10px] font-bold text-muted-foreground/70 uppercase tracking-wider w-[72px]">Imp</th>
                          <th className="text-right px-4 py-3 text-[10px] font-bold text-muted-foreground/70 uppercase tracking-wider w-[96px]">Previous</th>
                          <th className="text-right px-4 py-3 text-[10px] font-bold text-muted-foreground/70 uppercase tracking-wider w-[96px]">Forecast</th>
                          <th className="text-right px-4 py-3 text-[10px] font-bold text-muted-foreground/70 uppercase tracking-wider w-[96px]">Actual</th>
                        </tr>
                      </thead>
                      <tbody>
                        {dateEvents.map((ev, idx) => {
                          const cfg = IMPORTANCE_CONFIG[ev.importance]
                          return (
                            <tr
                              key={ev.id}
                              className={cn(
                                'border-b border-border hover:bg-muted/40 transition-colors',
                                idx === dateEvents.length - 1 && 'border-b-0'
                              )}
                            >
                              <td className="px-4 py-3">
                                <span className="text-xs font-mono font-bold tabular-nums text-foreground">{ev.localTime ?? ev.time}</span>
                              </td>
                              <td className="px-4 py-3">
                                <div className="flex items-center gap-1.5">
                                  <CurrencyFlag currency={ev.currency} size={16} />
                                  <Badge className="font-mono text-[10px] bg-muted text-muted-foreground border-0 px-2 py-0.5 font-bold">
                                    {ev.currency}
                                  </Badge>
                                </div>
                              </td>
                              <td className="px-4 py-3">
                                <span className="text-xs font-semibold text-foreground/90">{ev.event}</span>
                              </td>
                              <td className="px-4 py-3">
                                <div className="flex items-center gap-1.5">
                                  <span className={cn('w-2 h-2 rounded-full', cfg.dot)} />
                                  <span className={cn('text-[10px] font-bold', cfg.text)}>{cfg.label}</span>
                                </div>
                              </td>
                              <td className="px-4 py-3 text-right">
                                <span className="text-xs font-mono font-semibold tabular-nums text-muted-foreground">{ev.previous || '—'}</span>
                              </td>
                              <td className="px-4 py-3 text-right">
                                <span className="text-xs font-mono font-semibold tabular-nums text-muted-foreground">{ev.forecast || '—'}</span>
                              </td>
                              <td className="px-4 py-3 text-right">
                                <span className={cn(
                                  'text-xs font-mono font-bold tabular-nums',
                                  ev.actual === '—' ? 'text-muted-foreground/70' : 'text-primary'
                                )}>
                                  {ev.actual || '—'}
                                </span>
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                </Card>
              )}

              {/* ── Desktop: Grid View ────────────────────────── */}
              {viewMode === 'grid' && (
                <div className="hidden md:grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3 mb-6">
                  {dateEvents.map((ev) => (
                    <GridEventCard key={ev.id} ev={ev} />
                  ))}
                </div>
              )}
            </div>
          ))
        )}

        {/* Footer */}
        <div className="flex items-center justify-center gap-4 pt-2 flex-wrap">
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-red-500" />
            <span className="text-[10px] font-semibold text-muted-foreground/70">High</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-amber-500" />
            <span className="text-[10px] font-semibold text-muted-foreground/70">Medium</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-gray-400" />
            <span className="text-[10px] font-semibold text-muted-foreground/70">Low</span>
          </div>
          <span className="text-[10px] text-muted-foreground/50">|</span>
          <span className="text-[10px] font-medium text-muted-foreground/70">Auto-refreshes every 60s</span>
          <span className="text-[10px] text-muted-foreground/50">|</span>
          <div className="flex items-center gap-1">
            <Clock className="h-3 w-3 text-muted-foreground/50" />
            <span className="text-[10px] font-medium text-muted-foreground/70">Times shown in {tzAbbr} (your local time)</span>
          </div>
        </div>
      </main>

      <ShareNewsDialog
        open={shareOpen}
        onOpenChange={setShareOpen}
        events={shareEvents}
        tzNote={tzAbbr}
        periodLabel={sharePeriodLabel}
      />
    </div>
  )
}
