'use client'

import { useState, useEffect, useCallback, useRef, useTransition } from 'react'
import { createChart, IChartApi, ISeriesApi, ColorType, CandlestickSeriesPartialOptions, HistogramSeriesPartialOptions, BarData, HistogramData, Time } from 'lightweight-charts'
import { toast } from 'sonner'
import {
  Wallet,
  TrendingUp,
  TrendingDown,
  X,
  Settings,
  Loader2,
  Activity,
  Server,
  AlertCircle,
  DollarSign,
  BarChart3,
  RefreshCw,
  Clock,
  Edit3,
  Trash2,
  Maximize2,
  Minimize2,
  ChevronRight,
  PieChart,
  Target,
  Percent,
  ArrowUpRight,
  ArrowDownRight,
  Calendar as CalendarIcon,
  Shield,
  Zap,
  LineChart,
  TrendingUpDown,
  ExternalLink,
  ArrowUpCircle,
  ArrowDownCircle,
  XCircle,
  Info,
  ShieldCheck,
  CreditCard,
  History,
  Settings2,
  Scissors,
  AlertTriangle,
  ChevronDown
} from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Calendar } from '@/components/ui/calendar'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { format } from 'date-fns'
import { type DateRange } from 'react-day-picker'
import RiskGauge from '@/components/RiskGauge'
import RiskSlider from '@/components/RiskSlider'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { formatCurrency } from '@/lib/utils'
import { AreaChart, Area, ResponsiveContainer } from 'recharts'
import Image from 'next/image'
import InstrumentIcon from '@/components/InstrumentIcon'
import { InstrumentSymbol, getInstrumentInfo } from '@/components/InstrumentSymbol'
import MobilePageHeader from '@/components/MobilePageHeader'
import NexalPanel from '@/components/NexalPanel'
import { ResizablePanelGroup, ResizablePanel, ResizableHandle } from '@/components/ui/resizable'
import MobilePerformance from '@/components/account/MobilePerformance'
import MobilePositionsList from '@/components/account/MobilePositionsList'
import MobileOrdersList from '@/components/account/MobileOrdersList'
import MobileOrderEditSheet, { type ModifyOrderPayload } from '@/components/account/MobileOrderEditSheet'
import ConvertToMarketDialog from '@/components/account/ConvertToMarketDialog'

interface Position {
  ticket: number
  symbol: string
  type: number
  volume: number
  price_open: number
  price_current: number
  sl: number
  tp: number
  profit: number
  swap: number
  commission: number
  time: string
}

interface Order {
  ticket: number
  symbol: string
  type: number
  volume_initial: number
  volume?: number
  price_open: number
  sl: number
  tp: number
  time_setup: string
  // Raw MT5 TradeOrder fields — read only by the mobile order editor
  volume_current?: number
  price_current?: number
  price_stoplimit?: number
  time_expiration?: number
  type_time?: number
  state?: number
}

interface AccountInfo {
  balance: number
  equity: number
  margin: number
  margin_free: number
  profit: number
  leverage: number
  currency: string
  login?: number
  server?: string
}

interface AccountStats {
  win_rate: number
  profit_factor: number
  total_trades: number
  wins: number
  losses: number
  gross_profit: number
  gross_loss: number
  avg_win: number
  avg_loss: number
  total_profit: number
  total_commission: number
  total_swap: number
}

interface ProtectionStatus {
  daily_drawdown_pct: number
  total_drawdown_pct: number
  trading_blocked: boolean
  block_reason: string | null
  account_number: string
  equity: number
  balance: number
  margin_level: number
  protection_enabled: boolean
  protection_mode: string
  daily_starting_value?: number
  current_value?: number
  historical_peak?: number
  peak_equity?: number
  current_equity_balance_pct?: number
  current_equity_balance_diff?: number
}

interface ProtectionConfig {
  max_daily_loss_pct: number
  max_total_drawdown_pct: number
  max_daily_loss_abs: number
  max_total_drawdown_abs: number
  min_margin_level_pct: number
  protection_mode: 'equity' | 'balance'
  action: 'close_all' | 'close_profitable' | 'close_losing' | 'notify_only'
  heartbeat_interval: number
  order_check_interval: number
  ws_update_interval: number
  auto_reset_daily: boolean
  day_offset_hours?: number
  verbose_logging: boolean
  enabled: boolean
}

interface HistoryTrade {
  ticket: number
  symbol: string
  type: number
  volume: number
  price_open: number
  price_close: number
  profit: number
  time_open: string
  time_close: string
  magic: number
  comment: string
}

interface ProviderInfo {
  name: string
  label: string
  ismt5rest: boolean
}

// ── Chart panel types & constants ────────────────────────────────────────────
interface Candle {
  time: string
  open: number
  high: number
  low: number
  close: number
  tick_volume: number
}

interface ChartPriceInfo {
  bid: number
  ask: number
  spread: number
  high: number
  low: number
  change: number
  changePct: number
  digits: number
}

const CHART_TIMEFRAMES = ['M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1'] as const
type ChartTimeframeT = typeof CHART_TIMEFRAMES[number]
const CHART_TF_LABELS: Record<ChartTimeframeT, string> = {
  M1: '1m', M5: '5m', M15: '15m', M30: '30m', H1: '1h', H4: '4h', D1: 'D',
}

// ── AccountChartPanel ─────────────────────────────────────────────────────────
function AccountChartPanel({
  symbol,
  positions,
  history,
  onClose,
  refreshInterval = 5,
  isFullscreen = false,
  onFullscreenChange,
}: {
  symbol: string
  positions: Position[]
  history: HistoryTrade[]
  onClose: () => void
  refreshInterval?: number
  isFullscreen?: boolean
  onFullscreenChange?: (v: boolean) => void
}) {
  const [timeframe, setTimeframe] = useState<ChartTimeframeT>('H1')
  const [priceInfo, setPriceInfo] = useState<ChartPriceInfo | null>(null)
  const [chartLoading, setChartLoading] = useState(true)

  const chartContainerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null)
  const priceLineHandlesRef = useRef<ReturnType<ISeriesApi<'Candlestick'>['createPriceLine']>[]>([])
  const positionsRef = useRef(positions)
  const disposedRef = useRef(false)

  // Keep positionsRef current without causing loadData to re-create
  useEffect(() => { positionsRef.current = positions }, [positions])

  // Initialize chart once mounted
  useEffect(() => {
    if (!chartContainerRef.current) return
    const isDark = document.documentElement.classList.contains('dark')
    const chartBg  = isDark ? '#0D1624' : '#ffffff'
    const gridCol  = isDark ? '#18243A' : '#f1f5f9'
    const textCol  = isDark ? '#6B7A99' : '#64748b'
    const chart = createChart(chartContainerRef.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: chartBg },
        textColor: textCol,
        fontSize: 11,
      },
      grid: {
        vertLines: { color: gridCol },
        horzLines: { color: gridCol },
      },
      crosshair: {
        mode: 0,
        vertLine: { color: '#29ADFF', width: 1, style: 2, labelBackgroundColor: '#29ADFF' },
        horzLine: { color: '#29ADFF', width: 1, style: 2, labelBackgroundColor: '#29ADFF' },
      },
      rightPriceScale: { borderColor: gridCol, scaleMargins: { top: 0.05, bottom: 0.25 } },
      timeScale: { borderColor: gridCol, timeVisible: true, secondsVisible: false, rightOffset: 4 },
    })
    const candleSeries = chart.addCandlestickSeries({
      upColor: '#24C87A', downColor: '#F23050',
      borderUpColor: '#24C87A', borderDownColor: '#F23050',
      wickUpColor: '#24C87A', wickDownColor: '#F23050',
    } as CandlestickSeriesPartialOptions)
    const volumeSeries = chart.addHistogramSeries({
      color: '#29ADFF60',
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    } as HistogramSeriesPartialOptions)
    chart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } })

    chartRef.current = chart
    candleSeriesRef.current = candleSeries
    volumeSeriesRef.current = volumeSeries

    const getThemeColors = () => {
      const dark = document.documentElement.classList.contains('dark')
      return {
        bg:   dark ? '#0D1624' : '#ffffff',
        grid: dark ? '#18243A' : '#f1f5f9',
        text: dark ? '#6B7A99' : '#64748b',
      }
    }

    const themeObserver = new MutationObserver(() => {
      const { bg, grid, text } = getThemeColors()
      chart.applyOptions({
        layout: { background: { type: ColorType.Solid, color: bg }, textColor: text },
        grid: { vertLines: { color: grid }, horzLines: { color: grid } },
        rightPriceScale: { borderColor: grid },
        timeScale: { borderColor: grid },
      })
    })
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })

    return () => {
      disposedRef.current = true
      themeObserver.disconnect()
      chart.remove()
    }
  }, [])

  // Helper: remove all tracked price lines and redraw from current positions
  const redrawPriceLines = useCallback(() => {
    if (!candleSeriesRef.current) return
    for (const handle of priceLineHandlesRef.current) {
      try { candleSeriesRef.current.removePriceLine(handle) } catch { /* already removed */ }
    }
    priceLineHandlesRef.current = []
    for (const pos of positionsRef.current) {
      priceLineHandlesRef.current.push(
        candleSeriesRef.current.createPriceLine({ price: pos.price_open, color: pos.type === 0 ? '#22c55e' : '#ef4444', lineWidth: 1, lineStyle: 2, title: `#${pos.ticket} ${pos.type === 0 ? '▲BUY' : '▼SELL'} ${pos.volume}` })
      )
      if (pos.sl > 0) priceLineHandlesRef.current.push(candleSeriesRef.current.createPriceLine({ price: pos.sl, color: '#ef444480', lineWidth: 1, lineStyle: 1, title: 'SL' }))
      if (pos.tp > 0) priceLineHandlesRef.current.push(candleSeriesRef.current.createPriceLine({ price: pos.tp, color: '#22c55e80', lineWidth: 1, lineStyle: 1, title: 'TP' }))
    }
  }, [])

  // Load candles only — does NOT depend on positions so data refreshes don't re-fetch candles
  const loadData = useCallback(async (sym: string, tf: string) => {
    setChartLoading(true)
    try {
      const res = await fetch(`/api/candles?symbol=${sym}&timeframe=${tf}&bars=500`)
      if (!res.ok || !candleSeriesRef.current || !volumeSeriesRef.current) return
      const candles: Candle[] = await res.json()
      const candleData: BarData[] = []
      const volumeData: HistogramData[] = []
      for (const c of candles) {
        const time = Math.floor(new Date(c.time).getTime() / 1000) as Time
        candleData.push({ time, open: c.open, high: c.high, low: c.low, close: c.close })
        volumeData.push({ time, value: c.tick_volume, color: c.close >= c.open ? '#22c55e40' : '#ef444440' })
      }
      candleSeriesRef.current.setData(candleData)
      volumeSeriesRef.current.setData(volumeData)
      redrawPriceLines()
      chartRef.current?.timeScale().fitContent()
    } catch { /* silent */ } finally { setChartLoading(false) }
  }, [redrawPriceLines])

  // Only re-fetch candles when symbol or timeframe changes
  useEffect(() => { loadData(symbol, timeframe) }, [symbol, timeframe, loadData])

  // Redraw price lines in-place when positions update (no candle re-fetch)
  useEffect(() => { redrawPriceLines() }, [positions, redrawPriceLines])

  // Live candle update — bypasses Redis cache, catches up on any missed bars
  const updateLatestCandles = useCallback(async () => {
    if (disposedRef.current || !candleSeriesRef.current || !volumeSeriesRef.current) return
    try {
      // live=true skips Redis; bars=5 covers any missed periods since last tick
      const res = await fetch(`/api/candles?symbol=${symbol}&timeframe=${timeframe}&bars=5&live=true`)
      if (!res.ok || disposedRef.current) return
      const candles: Candle[] = await res.json()
      if (!candles.length || disposedRef.current) return
      for (const c of candles) {
        const time = Math.floor(new Date(c.time).getTime() / 1000) as Time
        try {
          candleSeriesRef.current.update({ time, open: c.open, high: c.high, low: c.low, close: c.close })
          volumeSeriesRef.current.update({ time, value: c.tick_volume, color: c.close >= c.open ? '#22c55e40' : '#ef444440' })
        } catch { /* bar is older than series tail — skip */ }
      }
    } catch { /* silent */ }
  }, [symbol, timeframe])

  useEffect(() => {
    if (!refreshInterval || refreshInterval <= 0) return
    const id = setInterval(updateLatestCandles, refreshInterval * 1000)
    return () => clearInterval(id)
  }, [refreshInterval, updateLatestCandles])

  // Digits and point once per symbol (/api/symbol-info is the flat contract spec,
  // it has no tick — reading bid/ask from it showed 0.00000).
  const symbolMetaRef = useRef({ digits: 5, point: 0.00001 })
  useEffect(() => {
    symbolMetaRef.current = { digits: 5, point: 0.00001 }
    fetch(`/api/symbol-info?symbol=${symbol}`)
      .then(r => (r.ok ? r.json() : null))
      .then(info => {
        if (info) symbolMetaRef.current = { digits: info.digits ?? 5, point: info.point || info.tickSize || 0.00001 }
      })
      .catch(() => { /* keep defaults */ })
  }, [symbol])

  // Refresh price info every 1 second
  const fetchPriceInfo = useCallback(async () => {
    try {
      const [tickRes, candleRes] = await Promise.all([
        fetch(`/api/mt5/symbol-tick?symbol=${symbol}`),
        fetch(`/api/candles?symbol=${symbol}&timeframe=M1&bars=2`),
      ])
      const tick = tickRes.ok ? await tickRes.json() : {}
      const candles = candleRes.ok ? await candleRes.json() : []
      const { digits, point } = symbolMetaRef.current
      const spread = tick.bid > 0 && tick.ask > 0 ? Math.round((tick.ask - tick.bid) / point) : 0  // points, as MT5 shows it
      let high = 0, low = 0, change = 0, changePct = 0
      if (candles?.length > 0) {
        const last = candles[candles.length - 1]
        high = last.high; low = last.low
        if (candles.length > 1) {
          const prev = candles[candles.length - 2].close
          change = last.close - prev
          changePct = prev !== 0 ? (change / prev) * 100 : 0
        }
      }
      setPriceInfo({ bid: tick.bid ?? 0, ask: tick.ask ?? 0, spread, high, low, change, changePct, digits })
    } catch { /* silent */ }
  }, [symbol])

  useEffect(() => {
    fetchPriceInfo()
    const id = setInterval(fetchPriceInfo, 1000)
    return () => clearInterval(id)
  }, [fetchPriceInfo])

  const isUp = (priceInfo?.change ?? 0) >= 0
  const openProfit = positions.reduce((s, p) => s + p.profit, 0)
  const historyProfit = history.reduce((s, t) => s + t.profit, 0)

  return (
    <div className="flex flex-col h-full min-w-0">
      {/* ── Header ── */}
      <div className="flex flex-col gap-0 border-b border-border/50 flex-shrink-0">
        <div className="flex items-center justify-between px-3 sm:px-5 py-2.5">
          <div className="flex items-center gap-2 min-w-0">
            <div>
              <h2 className="text-sm sm:text-base font-bold text-foreground">{symbol}</h2>
              {priceInfo && (
                <div className="hidden sm:flex items-center gap-2 mt-0.5 flex-wrap">
                  <span className="text-[11px] font-mono text-muted-foreground">Bid: <span className="text-foreground/90 font-semibold">{priceInfo.bid.toFixed(priceInfo.digits)}</span></span>
                  <span className="text-muted-foreground/50">·</span>
                  <span className="text-[11px] font-mono text-muted-foreground">Ask: <span className="text-foreground/90 font-semibold">{priceInfo.ask.toFixed(priceInfo.digits)}</span></span>
                  <span className="text-muted-foreground/50">·</span>
                  <span className={`text-[11px] font-bold ${isUp ? 'text-success' : 'text-destructive'}`}>
                    {priceInfo.changePct >= 0 ? '+' : ''}{priceInfo.changePct.toFixed(2)}%
                  </span>
                </div>
              )}
            </div>
            {positions.length > 0 && (
              <Badge className={`text-[10px] sm:text-xs px-1.5 sm:px-2 py-0.5 ${openProfit >= 0 ? 'bg-success/10 text-success border border-success/20' : 'bg-red-100 text-destructive border-red-200'}`}>
                {positions.length} · {openProfit >= 0 ? '+' : ''}{openProfit.toFixed(2)}
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-1.5 flex-shrink-0">
            <Button
              variant="ghost" size="icon" className="h-7 w-7"
              onClick={() => onFullscreenChange?.(!isFullscreen)}
              title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}
            >
              {isFullscreen
                ? <Minimize2 className="h-4 w-4 text-muted-foreground" />
                : <Maximize2 className="h-4 w-4 text-muted-foreground" />
              }
            </Button>
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onClose}>
              <X className="h-4 w-4 text-muted-foreground" />
            </Button>
          </div>
        </div>
        {/* Timeframe buttons — scrollable on mobile */}
        <div className="flex items-center gap-1 px-3 sm:px-5 pb-2 overflow-x-auto no-scrollbar">
          {CHART_TIMEFRAMES.map(tf => (
            <button
              key={tf}
              onClick={() => setTimeframe(tf)}
              className={`px-2.5 py-1 rounded text-[11px] font-semibold transition-all whitespace-nowrap flex-shrink-0 ${
                timeframe === tf ? 'bg-primary text-white' : 'bg-muted text-muted-foreground hover:bg-border'
              }`}
            >
              {CHART_TF_LABELS[tf]}
            </button>
          ))}
        </div>
      </div>

      {/* ── Price Info Bar ── */}
      {priceInfo && (
        <div className="grid grid-cols-3 sm:grid-cols-6 gap-0 border-b border-border/50 flex-shrink-0">
          {([
            { label: 'Bid', value: priceInfo.bid.toFixed(priceInfo.digits), cls: 'text-foreground/90' },
            { label: 'Ask', value: priceInfo.ask.toFixed(priceInfo.digits), cls: 'text-foreground/90' },
            { label: 'Spread', value: String(priceInfo.spread), cls: 'text-foreground/90' },
            { label: 'High', value: priceInfo.high.toFixed(priceInfo.digits), cls: 'text-success' },
            { label: 'Low', value: priceInfo.low.toFixed(priceInfo.digits), cls: 'text-destructive' },
            { label: 'Change', value: `${priceInfo.changePct >= 0 ? '+' : ''}${priceInfo.changePct.toFixed(2)}%`, cls: isUp ? 'text-success' : 'text-destructive' },
          ] as { label: string; value: string; cls: string }[]).map(item => (
            <div key={item.label} className="flex flex-col items-center py-2 px-1 bg-muted/50 border-r border-border/50 last:border-r-0">
              <span className="text-[9px] font-bold text-muted-foreground/70 uppercase tracking-wider">{item.label}</span>
              <span className={`text-[11px] font-bold tabular-nums ${item.cls}`}>{item.value}</span>
            </div>
          ))}
        </div>
      )}

      {/* ── Resizable chart / data split ── */}
      <ResizablePanelGroup orientation="vertical" className="flex-1 min-h-0">
        {/* Chart panel */}
        <ResizablePanel defaultSize={62} minSize={20}>
          <div className="relative w-full h-full overflow-hidden">
            <div ref={chartContainerRef} className="w-full h-full" />
            {chartLoading && (
              <div className="absolute inset-0 flex items-center justify-center bg-background/60 pointer-events-none">
                <Loader2 className="h-6 w-6 animate-spin text-primary" />
              </div>
            )}
          </div>
        </ResizablePanel>

        <ResizableHandle withHandle className="bg-muted hover:bg-primary/20 transition-colors" />

        {/* Data panel — positions + history */}
        <ResizablePanel defaultSize={38} minSize={10}>
          <div className="overflow-y-auto h-full no-scrollbar bg-muted/30">
            {/* Open positions for symbol */}
            {positions.length > 0 && (
              <div className="px-4 pt-3 pb-2">
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest">Open</span>
                  <span className="text-[10px] font-bold text-primary bg-primary/10 rounded-full px-1.5 py-0.5">{positions.length}</span>
                  <span className={`ml-auto text-[11px] font-bold tabular-nums ${openProfit >= 0 ? 'text-success' : 'text-destructive'}`}>
                    {openProfit >= 0 ? '+' : ''}{openProfit.toFixed(2)}
                  </span>
                </div>
                <div className="space-y-1">
                  {positions.map(pos => (
                    <div key={pos.ticket} className="flex items-center justify-between bg-card rounded-lg px-3 py-2 border border-border shadow-sm">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${pos.type === 0 ? 'bg-success/10 text-success' : 'bg-destructive/10 text-destructive'}`}>
                          {pos.type === 0 ? 'BUY' : 'SELL'}
                        </span>
                        <span className="text-[10px] font-mono text-muted-foreground hidden sm:inline">#{pos.ticket}</span>
                        <span className="text-[11px] font-semibold text-foreground tabular-nums">{pos.volume}L</span>
                      </div>
                      <div className="flex items-center gap-2 text-[10px] font-mono flex-shrink-0">
                        <span className="text-muted-foreground">{pos.price_open.toFixed(5)}</span>
                        <span className="text-border">›</span>
                        <span className="text-foreground font-semibold">{pos.price_current.toFixed(5)}</span>
                        <span className={`font-bold min-w-[48px] text-right tabular-nums ${pos.profit >= 0 ? 'text-success' : 'text-destructive'}`}>
                          {pos.profit >= 0 ? '+' : ''}{pos.profit.toFixed(2)}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Historical trades for symbol */}
            {history.length > 0 && (
              <div className="px-4 pt-2 pb-4">
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest">History</span>
                  <span className="text-[10px] font-bold text-muted-foreground bg-muted rounded-full px-1.5 py-0.5">{history.length}</span>
                  <span className={`ml-auto text-[11px] font-bold tabular-nums ${historyProfit >= 0 ? 'text-success' : 'text-destructive'}`}>
                    {historyProfit >= 0 ? '+' : ''}{historyProfit.toFixed(2)}
                  </span>
                </div>
                <div className="overflow-x-auto no-scrollbar rounded-lg border border-border bg-card">
                  <table className="w-full text-[11px]">
                    <thead>
                      <tr className="border-b border-border bg-muted/50">
                        {['#', 'Side', 'Vol', 'Entry', 'Exit', 'P&L'].map(h => (
                          <th key={h} className={`py-1.5 px-3 font-semibold text-[9px] text-muted-foreground uppercase tracking-widest whitespace-nowrap ${h === 'P&L' ? 'text-right' : 'text-left'}`}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {history.slice(0, 50).map((trade, i) => (
                        <tr key={trade.ticket} className={`border-b border-border/50 last:border-0 ${i % 2 === 0 ? '' : 'bg-muted/20'} hover:bg-primary/5 transition-colors`}>
                          <td className="py-1.5 px-3 font-mono text-muted-foreground">{trade.ticket}</td>
                          <td className="py-1.5 px-3">
                            <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${trade.type === 0 ? 'bg-success/10 text-success' : 'bg-destructive/10 text-destructive'}`}>
                              {trade.type === 0 ? 'BUY' : 'SELL'}
                            </span>
                          </td>
                          <td className="py-1.5 px-3 tabular-nums text-foreground/70">{trade.volume}</td>
                          <td className="py-1.5 px-3 font-mono tabular-nums text-foreground/70">{trade.price_open.toFixed(5)}</td>
                          <td className="py-1.5 px-3 font-mono tabular-nums text-foreground/70">{trade.price_close.toFixed(5)}</td>
                          <td className={`py-1.5 px-3 text-right font-bold tabular-nums ${trade.profit >= 0 ? 'text-success' : 'text-destructive'}`}>
                            {trade.profit >= 0 ? '+' : ''}{trade.profit.toFixed(2)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {positions.length === 0 && history.length === 0 && (
              <div className="flex flex-col items-center justify-center h-full py-10 text-center">
                <Activity className="h-7 w-7 text-muted-foreground/40 mb-2" />
                <p className="text-xs text-muted-foreground font-medium">No trades for {symbol}</p>
              </div>
            )}
          </div>
        </ResizablePanel>
      </ResizablePanelGroup>
    </div>
  )
}

export default function AccountPage() {
  const [positions, setPositions] = useState<Position[]>([])
  const [orders, setOrders] = useState<Order[]>([])
  const [account, setAccount] = useState<AccountInfo | null>(null)
  const [stats, setStats] = useState<AccountStats | null>(null)
  const [protection, setProtection] = useState<ProtectionStatus | null>(null)
  const [history, setHistory] = useState<HistoryTrade[]>([])
  const [provider, setProvider] = useState<ProviderInfo | null>(null)
  const [protectionConfig, setProtectionConfig] = useState<ProtectionConfig | null>(null)
  const [originalProtectionConfig, setOriginalProtectionConfig] = useState<ProtectionConfig | null>(null)

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null)
  const [isPending, startTransition] = useTransition()
  const [mounted, setMounted] = useState(false)
  const [actionLoading, setActionLoading] = useState(false)

  // Inline SL/TP editing
  const [editingCell, setEditingCell] = useState<{ ticket: number; field: 'sl' | 'tp' } | null>(null)
  const [editValue, setEditValue] = useState('')
  const editInputRef = useRef<HTMLInputElement>(null)

  const intervalRef = useRef<NodeJS.Timeout | null>(null)
  const isFetchingRef = useRef(false)

  // User Preferences
  const [userSettings, setUserSettings] = useState({
    smartCloseEnabled: true,
    smartClosePercentage: 50.0,
    smartCloseSetBreakeven: true,
  })

  const [refreshInterval, setRefreshInterval] = useState(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('mt5-refresh-interval')
      return saved ? parseFloat(saved) : 5
    }
    return 10
  })

  // Chart panel
  const [chartSymbol, setChartSymbol] = useState<string | null>(null)
  const [chartFullscreen, setChartFullscreen] = useState(false)

  // Modal states
  const [settingsModal, setSettingsModal] = useState(false)
  const [mobileRefreshModal, setMobileRefreshModal] = useState(false)
  const [modifyModal, setModifyModal] = useState<{ open: boolean; position: Position | null }>({ open: false, position: null })
  const [partialCloseModal, setPartialCloseModal] = useState<{ open: boolean; position: Position | null }>({ open: false, position: null })
  const [modifyOrderModal, setModifyOrderModal] = useState<{ open: boolean; order: Order | null }>({ open: false, order: null })
  const [confirmDialog, setConfirmDialog] = useState<{ open: boolean; title: string; message: string; onConfirm: () => void; danger?: boolean }>({
    open: false, title: '', message: '', onConfirm: () => { }, danger: false
  })
  const [closeSymbolModal, setCloseSymbolModal] = useState<{ open: boolean; symbol: string }>({ open: false, symbol: '' })
  // Mobile-only: single bottom-sheet editor for pending orders
  const [mobileEditOrder, setMobileEditOrder] = useState<Order | null>(null)
  // Pending order being turned into a market order (same-risk lots), desktop and mobile
  const [marketTicket, setMarketTicket] = useState<number | null>(null)

  // Derived: close Nexal panel when any modal/dialog is open
  const anyModalOpen =
    settingsModal || mobileRefreshModal ||
    modifyModal.open || partialCloseModal.open ||
    modifyOrderModal.open || confirmDialog.open ||
    closeSymbolModal.open || !!chartSymbol || !!mobileEditOrder || marketTicket != null

  // Form states
  const [modifySL, setModifySL] = useState('')
  const [modifyTP, setModifyTP] = useState('')
  const [partialVolume, setPartialVolume] = useState('')
  const [orderPrice, setOrderPrice] = useState('')
  const [orderSL, setOrderSL] = useState('')
  const [orderTP, setOrderTP] = useState('')
  const [symbolInfo, setSymbolInfo] = useState<{ volumeStep: number; volumeMin: number; volumeMax: number } | null>(null)
  const [symbolInfoLoading, setSymbolInfoLoading] = useState(false)

  // Tab state — risk/history are lazy-loaded on first click
  const [activeTab, setActiveTab] = useState('trades')
  const riskLoadedRef = useRef(false)

  // Mobile splits "trades" into separate Positions / Orders tabs; keep the active
  // tab valid for whichever layout is showing so desktop always lands on "trades".
  useEffect(() => {
    const mq = window.matchMedia('(min-width: 768px)')
    const sync = () => setActiveTab(t => mq.matches
      ? (t === 'positions' || t === 'orders' ? 'trades' : t)
      : (t === 'trades' ? 'positions' : t))
    sync()
    mq.addEventListener('change', sync)
    return () => mq.removeEventListener('change', sync)
  }, [])

  const handleTabChange = useCallback((tab: string) => {
    setActiveTab(tab)
    if (tab === 'risk' && !riskLoadedRef.current) {
      riskLoadedRef.current = true
      Promise.allSettled([
        fetch('/api/mt5/protection/status', { cache: 'no-store' }),
        fetch('/api/mt5/protection/config'),
      ]).then(([statusRes, configRes]) => {
        if (statusRes.status === 'fulfilled' && statusRes.value.ok) statusRes.value.json().then(setProtection)
        if (configRes.status === 'fulfilled' && configRes.value.ok) {
          configRes.value.json().then((config: ProtectionConfig) => {
            setProtectionConfig(config)
            setOriginalProtectionConfig(config)
          })
        }
      }).catch(() => {})
    }
  }, [])

  // History filters
  const [historyDateRange, setHistoryDateRange] = useState<DateRange | undefined>(undefined)
  const [historyTimeFilter, setHistoryTimeFilter] = useState<string>('all')
  const [historyDayFilter, setHistoryDayFilter] = useState<string>('all')

  // Filter history trades based on selected filters
  const getFilteredHistory = () => {
    let filtered = [...history]

    // Filter by date range
    if (historyDateRange?.from) {
      const fromDate = new Date(historyDateRange.from)
      fromDate.setHours(0, 0, 0, 0)
      filtered = filtered.filter(trade => {
        const tradeDate = new Date(typeof trade.time_close === 'number' ? trade.time_close * 1000 : trade.time_close)
        return tradeDate >= fromDate
      })
    }
    if (historyDateRange?.to) {
      const toDate = new Date(historyDateRange.to)
      toDate.setHours(23, 59, 59, 999)
      filtered = filtered.filter(trade => {
        const tradeDate = new Date(typeof trade.time_close === 'number' ? trade.time_close * 1000 : trade.time_close)
        return tradeDate <= toDate
      })
    }

    // Filter by time of day
    if (historyTimeFilter !== 'all') {
      filtered = filtered.filter(trade => {
        const tradeDate = new Date(typeof trade.time_close === 'number' ? trade.time_close * 1000 : trade.time_close)
        const hour = tradeDate.getHours()
        if (historyTimeFilter === 'morning') return hour >= 6 && hour < 12
        if (historyTimeFilter === 'afternoon') return hour >= 12 && hour < 18
        if (historyTimeFilter === 'evening') return hour >= 18 && hour < 22
        if (historyTimeFilter === 'night') return hour >= 22 || hour < 6
        return true
      })
    }

    // Filter by day of week
    if (historyDayFilter !== 'all') {
      filtered = filtered.filter(trade => {
        const tradeDate = new Date(typeof trade.time_close === 'number' ? trade.time_close * 1000 : trade.time_close)
        const day = tradeDate.getDay()
        return day.toString() === historyDayFilter
      })
    }

    return filtered
  }

  // Calculate statistics for filtered trades
  const getHistoryStats = (filteredTrades: HistoryTrade[]) => {
    const wins = filteredTrades.filter(t => t.profit > 0)
    const losses = filteredTrades.filter(t => t.profit < 0)
    const totalProfit = filteredTrades.reduce((sum, t) => sum + t.profit, 0)
    const winRate = filteredTrades.length > 0 ? (wins.length / filteredTrades.length) * 100 : 0

    return {
      total: filteredTrades.length,
      wins: wins.length,
      losses: losses.length,
      totalProfit,
      winRate
    }
  }

  // Icon Helper
  // Thin wrapper over the shared <InstrumentSymbol> so existing call sites keep working.
  const AccountInstrumentIcon = ({ symbol, size = "md" }: { symbol: string, size?: "sm" | "md" | "lg" }) => (
    <InstrumentSymbol symbol={symbol} size={size} />
  )

  const handleRefreshIntervalChange = (interval: number) => {
    setRefreshInterval(interval)
    if (typeof window !== 'undefined') {
      localStorage.setItem('mt5-refresh-interval', interval.toString())
    }
  }

  const handleManualRefresh = async () => {
    await fetchData(true)
  }

  useEffect(() => {
    setMounted(true)
    loadUserSettings()
  }, [])

  const loadUserSettings = async () => {
    try {
      const res = await fetch('/api/user-settings')
      if (res.ok) {
        const data = await res.json()
        setUserSettings({
          smartCloseEnabled: data.smartCloseEnabled,
          smartClosePercentage: data.smartClosePercentage,
          smartCloseSetBreakeven: data.smartCloseSetBreakeven,
        })
      }
    } catch (error) {
      console.error('Failed to load user settings:', error)
    }
  }

  const saveUserSettings = async (settings: typeof userSettings) => {
    try {
      const res = await fetch('/api/user-settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings),
      })
      if (res.ok) {
        setUserSettings(settings)
        toast.success('Settings Saved')
      }
    } catch (error) {
      toast.error('Failed to save settings')
    }
  }

  const fetchData = useCallback(async (isBackgroundRefresh = false) => {
    if (isFetchingRef.current) return
    try {
      isFetchingRef.current = true
      if (isBackgroundRefresh) setIsRefreshing(true)

      // Initial load: account + positions + orders + stats + provider + history
      // Protection is loaded lazily when user clicks the Risk tab
      const [providerRes, accountRes, positionsRes, ordersRes, statsRes, historyRes] = await Promise.allSettled([
        fetch('/api/provider', { cache: 'no-store' }),
        fetch('/api/mt5/account', { cache: 'no-store' }),
        fetch('/api/mt5/positions', { cache: 'no-store' }),
        fetch('/api/mt5/orders', { cache: 'no-store' }),
        fetch('/api/mt5/stats', { cache: 'no-store' }),
        fetch('/api/mt5/history', { cache: 'no-store' }),
      ])

      startTransition(() => {
        if (providerRes.status === 'fulfilled' && providerRes.value.ok) providerRes.value.json().then(setProvider)
        if (accountRes.status === 'fulfilled' && accountRes.value.ok) accountRes.value.json().then(setAccount)
        if (positionsRes.status === 'fulfilled' && positionsRes.value.ok) {
          positionsRes.value.json().then(data => setPositions(Array.isArray(data) ? data : data.positions || []))
        }
        if (ordersRes.status === 'fulfilled' && ordersRes.value.ok) {
          ordersRes.value.json().then(data => setOrders(Array.isArray(data) ? data : data.orders || []))
        }
        if (statsRes.status === 'fulfilled' && statsRes.value.ok) statsRes.value.json().then(setStats)
        if (historyRes.status === 'fulfilled' && historyRes.value.ok) {
          historyRes.value.json().then(data => {
            const trades = Array.isArray(data) ? data : data.trades || []
            const sortedTrades = trades.sort((a: HistoryTrade, b: HistoryTrade) => {
              const timeA = new Date(typeof a.time_close === 'number' ? a.time_close * 1000 : a.time_close).getTime()
              const timeB = new Date(typeof b.time_close === 'number' ? b.time_close * 1000 : b.time_close).getTime()
              return timeB - timeA
            })
            setHistory(sortedTrades)
          })
        }
        setError(null)
        setLastRefresh(new Date())
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch data')
    } finally {
      setLoading(false)
      setIsRefreshing(false)
      isFetchingRef.current = false
    }
  }, [])

  // Lightweight interval fetch — only the data needed to manage live trades
  const fetchLiveData = useCallback(async () => {
    if (isFetchingRef.current) return
    try {
      isFetchingRef.current = true
      setIsRefreshing(true)
      const [accountRes, positionsRes, ordersRes] = await Promise.allSettled([
        fetch('/api/mt5/account', { cache: 'no-store' }),
        fetch('/api/mt5/positions', { cache: 'no-store' }),
        fetch('/api/mt5/orders', { cache: 'no-store' }),
      ])
      startTransition(() => {
        if (accountRes.status === 'fulfilled' && accountRes.value.ok) accountRes.value.json().then(setAccount)
        if (positionsRes.status === 'fulfilled' && positionsRes.value.ok)
          positionsRes.value.json().then(data => setPositions(Array.isArray(data) ? data : data.positions || []))
        if (ordersRes.status === 'fulfilled' && ordersRes.value.ok)
          ordersRes.value.json().then(data => setOrders(Array.isArray(data) ? data : data.orders || []))
        setLastRefresh(new Date())
      })
    } catch { /* silent */ } finally {
      setIsRefreshing(false)
      isFetchingRef.current = false
    }
  }, [])

  useEffect(() => {
    fetchData(false)
  }, [fetchData])

  // Fetch symbol constraints whenever partial close modal opens
  useEffect(() => {
    if (!partialCloseModal.open || !partialCloseModal.position) {
      setSymbolInfo(null)
      return
    }
    const symbol = partialCloseModal.position.symbol
    setSymbolInfoLoading(true)
    fetch(`/api/symbol-info?symbol=${symbol}`)
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data) setSymbolInfo({ volumeStep: data.volumeStep || 0.01, volumeMin: data.volumeMin || 0.01, volumeMax: data.volumeMax || 100 })
      })
      .catch(() => {})
      .finally(() => setSymbolInfoLoading(false))
  }, [partialCloseModal.open, partialCloseModal.position])

  const fetchProtectionConfig = async () => {
    try {
      const res = await fetch('/api/mt5/protection/config')
      if (res.ok) {
        const config = await res.json()
        setProtectionConfig(config)
        setOriginalProtectionConfig(config)
      }
    } catch (err) {
      console.error('Failed to fetch protection config:', err)
    }
  }

  const handleUpdateProtectionConfig = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!protectionConfig) return
    setActionLoading(true)
    try {
      // Only send fields that the backend API accepts
      const updateData = {
        max_daily_loss_pct: protectionConfig.max_daily_loss_pct,
        max_total_drawdown_pct: protectionConfig.max_total_drawdown_pct,
        max_daily_loss_abs: protectionConfig.max_daily_loss_abs,
        max_total_drawdown_abs: protectionConfig.max_total_drawdown_abs,
        min_margin_level_pct: protectionConfig.min_margin_level_pct,
        protection_mode: protectionConfig.protection_mode,
        action: protectionConfig.action,
        heartbeat_interval: protectionConfig.heartbeat_interval,
        order_check_interval: protectionConfig.order_check_interval,
        ws_update_interval: protectionConfig.ws_update_interval,
        auto_reset_daily: protectionConfig.auto_reset_daily,
        day_offset_hours: protectionConfig.day_offset_hours ?? 0,
        verbose_logging: protectionConfig.verbose_logging,
        enabled: protectionConfig.enabled,
      }
      
      const res = await fetch('/api/mt5/protection/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updateData),
      })
      if (!res.ok) throw new Error('Update failed')
      toast.success('Risk Config Updated')
      await fetchProtectionConfig()
      await fetchData()
    } catch (err) {
      toast.error('Update failed')
    } finally {
      setActionLoading(false)
    }
  }

  const toggleProtection = async () => {
    if (!protectionConfig) return
    setActionLoading(true)
    try {
      const endpoint = protectionConfig.enabled ? '/api/mt5/protection/disable' : '/api/mt5/protection/enable'
      const res = await fetch(endpoint, { method: 'POST' })
      if (!res.ok) throw new Error('Action failed')
      toast.success(`Protection ${protectionConfig.enabled ? 'Disabled' : 'Enabled'}`)
      await fetchProtectionConfig()
      await fetchData()
    } catch (err) {
      toast.error('Action failed')
    } finally {
      setActionLoading(false)
    }
  }

  const resetProtectionBlock = async () => {
    setActionLoading(true)
    try {
      const res = await fetch('/api/mt5/protection/reset-block', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ account_number: protection?.account_number }),
      })
      if (!res.ok) throw new Error('Reset failed')
      toast.success('Risk Block Reset')
      await fetchData()
    } catch (err) {
      toast.error('Reset failed')
    } finally {
      setActionLoading(false)
    }
  }

  const closePosition = async (position: Position) => {
    setConfirmDialog({
      open: true,
      title: 'Close Position',
      message: `Close ${position.symbol} #${position.ticket}?`,
      onConfirm: async () => {
        setActionLoading(true)
        try {
          const res = await fetch('/api/mt5/close-position', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ position }),
          })
          if (!res.ok) throw new Error('Failed')
          await fetchData()
          toast.success('Position Closed')
        } catch (err) {
          toast.error('Close failed')
        } finally {
          setActionLoading(false)
        }
      }
    })
  }

  const setBreakeven = async (position: Position) => {
    setActionLoading(true)
    try {
      const res = await fetch('/api/mt5/modify-sltp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          position: position.ticket,
          sl: position.price_open,
          tp: position.tp || undefined,
        }),
      })
      if (!res.ok) throw new Error('Failed')
      await fetchData()
      toast.success('Breakeven Set', { description: `SL moved to ${position.price_open.toFixed(5)}` })
    } catch (err) {
      toast.error('Breakeven failed')
    } finally {
      setActionLoading(false)
    }
  }

  const smartClose = async (position: Position) => {
    if (!userSettings.smartCloseEnabled) {
      toast.error('Smart Close Disabled')
      return
    }
    setActionLoading(true)
    try {
      const symbolInfoRes = await fetch(`/api/symbol-info?symbol=${position.symbol}`)
      if (!symbolInfoRes.ok) throw new Error('Symbol info failed')
      const symbolInfo = await symbolInfoRes.json()

      const rawVolume = position.volume * userSettings.smartClosePercentage / 100
      const volumeStep = symbolInfo.volumeStep || 0.01
      const volumeMin = symbolInfo.volumeMin || 0.01
      let closeVolume = Math.round(rawVolume / volumeStep) * volumeStep
      if (closeVolume >= position.volume) closeVolume = Math.floor((position.volume - volumeStep) / volumeStep) * volumeStep
      if (closeVolume < volumeMin) throw new Error(`Volume too small (${volumeMin} lots min)`)

      const res = await fetch('/api/mt5/close-partial', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ position, volume: closeVolume }),
      })
      if (!res.ok) throw new Error('Partial close failed')

      if (userSettings.smartCloseSetBreakeven && Math.abs(position.sl - position.price_open) >= 0.00001) {
        await new Promise(r => setTimeout(r, 500))
        const modifyRes = await fetch('/api/mt5/modify-sltp', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ position: position.ticket, sl: position.price_open, tp: position.tp || undefined }),
        })
        
        if (!modifyRes.ok) {
          console.warn('Set BE step of smart close failed or was redundant')
        }
      }

      await fetchData()
      toast.success('Smart Close Success', { 
        description: `Closed ${userSettings.smartClosePercentage}% of position${userSettings.smartCloseSetBreakeven ? ' and set BE' : ''}` 
      })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Smart close failed')
    } finally {
      setActionLoading(false)
    }
  }

  const handleModifySLTP = async () => {
    if (!modifyModal.position) return

    const nextSL = modifySL ? parseFloat(modifySL) : 0
    const nextTP = modifyTP ? parseFloat(modifyTP) : 0

    // Prevent "No changes" error if user didn't change anything
    if (Math.abs(nextSL - (modifyModal.position?.sl || 0)) < 0.00001 && 
        Math.abs(nextTP - (modifyModal.position?.tp || 0)) < 0.00001) {
      setModifyModal({ open: false, position: null })
      return
    }

    setActionLoading(true)
    try {
      const res = await fetch('/api/mt5/modify-sltp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          position: modifyModal.position.ticket,
          sl: nextSL,
          tp: nextTP,
        }),
      })
      if (!res.ok) throw new Error('Failed')
      setModifyModal({ open: false, position: null })
      await fetchData()
      toast.success('Levels Updated')
    } catch (err) {
      toast.error('Update failed')
    } finally {
      setActionLoading(false)
    }
  }

  const handleInlineSLTPEdit = async () => {
    if (!editingCell || !editValue) return
    const ticket = editingCell.ticket
    const field = editingCell.field
    const pos = positions.find(p => p.ticket === ticket)
    if (!pos) return

    setActionLoading(true)
    try {
      const sl = field === 'sl' ? parseFloat(editValue) : pos.sl
      const tp = field === 'tp' ? parseFloat(editValue) : pos.tp
      // Don't send if no change
      if (Math.abs(sl - pos.sl) < 0.00001 && Math.abs(tp - pos.tp) < 0.00001) {
        setEditingCell(null)
        return
      }
      const res = await fetch('/api/mt5/modify-sltp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ position: ticket, sl, tp }),
      })
      if (!res.ok) throw new Error('Failed')
      setEditingCell(null)
      await fetchData()
      toast.success(`${field === 'sl' ? 'Stop Loss' : 'Take Profit'} Updated`)
    } catch (err) {
      toast.error('Update failed')
    } finally {
      setActionLoading(false)
    }
  }

  const closeAllPositions = async () => {
    setConfirmDialog({
      open: true,
      title: 'Close All Positions',
      message: `Are you sure you want to close ALL ${positions.length} active positions?`,
      onConfirm: async () => {
        setActionLoading(true)
        try {
          const res = await fetch('/api/mt5/close-all', { method: 'POST' })
          if (!res.ok) throw new Error('Failed to close positions')
          await fetchData()
          toast.success('All Positions Closed')
        } catch (err) {
          toast.error('Action failed')
        } finally {
          setActionLoading(false)
        }
      }
    })
  }

  const closeAllOrders = async () => {
    setConfirmDialog({
      open: true,
      title: 'Cancel All Orders',
      message: `Are you sure you want to cancel ALL ${orders.length} pending orders?`,
      onConfirm: async () => {
        setActionLoading(true)
        try {
          const promises = orders.map(order => 
            fetch('/api/mt5/cancel-order', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ ticket: order.ticket })
            })
          )
          await Promise.all(promises)
          await fetchData()
          toast.success('All Orders Cancelled')
        } catch (err) {
          toast.error('Action failed')
        } finally {
          setActionLoading(false)
        }
      }
    })
  }

  const setAllBreakeven = async () => {
    const profitablePositions = positions.filter(p => p.profit > 0 && Math.abs(p.sl - p.price_open) >= 0.00001)
    if (profitablePositions.length === 0) {
      toast.info('No Profitable Positions', { description: 'Only positions in profit can be set to breakeven' })
      return
    }

    setConfirmDialog({
      open: true,
      title: 'Set All Breakeven',
      message: `Move Stop Loss to entry price for all ${profitablePositions.length} profitable positions?`,
      onConfirm: async () => {
        setActionLoading(true)
        try {
          const promises = profitablePositions.map(pos => 
            fetch('/api/mt5/modify-sltp', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                position: pos.ticket,
                sl: pos.price_open,
                tp: pos.tp || undefined,
              }),
            })
          )
          await Promise.all(promises)
          await fetchData()
          toast.success('Batch Breakeven Success', { description: `Updated ${profitablePositions.length} positions` })
        } catch (err) {
          toast.error('Error', { description: 'Some positions failed to update' })
        } finally {
          setActionLoading(false)
        }
      }
    })
  }

  const handlePartialClose = async () => {
    if (!partialCloseModal.position || !partialVolume) return
    setActionLoading(true)
    try {
      // Fetch symbol info to get correct lot step, min, and max
      const symbolInfoRes = await fetch(`/api/symbol-info?symbol=${partialCloseModal.position.symbol}`)
      if (!symbolInfoRes.ok) {
        throw new Error('Failed to fetch symbol info')
      }
      const symbolInfo = await symbolInfoRes.json()
      
      const rawVolume = parseFloat(partialVolume)
      const volumeStep = symbolInfo.volumeStep || 0.01
      const volumeMin = symbolInfo.volumeMin || 0.01
      const volumeMax = symbolInfo.volumeMax || 100
      
      // Round to the nearest valid step
      const roundedVolume = Math.round(rawVolume / volumeStep) * volumeStep
      
      // Validate against min volume
      if (roundedVolume < volumeMin) {
        throw new Error(`Volume (${rawVolume.toFixed(2)} lots) is below minimum (${volumeMin} lots)`)
      }
      
      // Validate against max volume
      if (roundedVolume > volumeMax) {
        throw new Error(`Volume (${rawVolume.toFixed(2)} lots) exceeds maximum (${volumeMax} lots)`)
      }
      
      // Show notification if volume was rounded
      if (roundedVolume !== rawVolume) {
        toast.info('Volume Adjusted', { 
          description: `Rounded from ${rawVolume.toFixed(2)} to ${roundedVolume.toFixed(2)} lots (step: ${volumeStep})`
        })
      }

      const res = await fetch('/api/mt5/close-partial', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ position: partialCloseModal.position, volume: roundedVolume }),
      })
      if (!res.ok) throw new Error('Failed')
      setPartialCloseModal({ open: false, position: null })
      setPartialVolume('')
      await fetchData()
      toast.success('Partial Close', { description: 'Partial close successful' })
    } catch (err) {
      toast.error('Error', { description: err instanceof Error ? err.message : 'Failed to partial close' })
    } finally {
      setActionLoading(false)
    }
  }

  const handleCloseProfitable = async () => {
    const count = positions.filter(p => p.profit > 0).length
    setConfirmDialog({
      open: true,
      title: 'Liquidate Profits',
      message: `Close all ${count} profitable position${count !== 1 ? 's' : ''}? This action cannot be undone.`,
      danger: false,
      onConfirm: async () => {
        setActionLoading(true)
        try {
          await fetch('/api/mt5/close-profitable', { method: 'POST' })
          await fetchData()
          toast.success('Profits Liquidated', { description: 'All profitable positions have been closed' })
        } finally { setActionLoading(false) }
      }
    })
  }

  const handleCloseLosing = async () => {
    const losers = positions.filter(p => p.profit < 0)
    if (losers.length === 0) {
      toast.info('No Losing Positions', { description: 'All open positions are currently in profit' })
      return
    }
    const totalLoss = losers.reduce((s, p) => s + p.profit, 0)
    setConfirmDialog({
      open: true,
      title: 'Cut Losses',
      danger: true,
      message: `Close ${losers.length} losing position${losers.length !== 1 ? 's' : ''}? Estimated realized loss: ${formatCurrency(totalLoss)}`,
      onConfirm: async () => {
        setActionLoading(true)
        try {
          await fetch('/api/mt5/close-losing', { method: 'POST' })
          await fetchData()
          toast.success('Losses Cut', { description: `Closed ${losers.length} losing positions` })
        } catch { toast.error('Failed to close losing positions') }
        finally { setActionLoading(false) }
      }
    })
  }

  const handleCloseBySymbol = async (symbol: string) => {
    const symPositions = positions.filter(p => p.symbol === symbol)
    const totalPL = symPositions.reduce((s, p) => s + p.profit, 0)
    setConfirmDialog({
      open: true,
      title: `Close All ${symbol}`,
      danger: totalPL < 0,
      message: `Close all ${symPositions.length} ${symbol} position${symPositions.length !== 1 ? 's' : ''}? Net P/L: ${formatCurrency(totalPL)}`,
      onConfirm: async () => {
        setActionLoading(true)
        try {
          await fetch('/api/mt5/close-all', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symbol })
          })
          await fetchData()
          toast.success(`${symbol} Closed`, { description: `All ${symbol} positions closed` })
        } catch { toast.error('Failed') }
        finally { setActionLoading(false) }
      }
    })
  }

  const cancelOrder = async (order: Order) => {
    setActionLoading(true)
    try {
      await fetch('/api/mt5/cancel-order', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticket: order.ticket }),
      })
      await fetchData()
      toast.success('Order Cancelled', { description: `Order #${order.ticket} has been cancelled` })
    } finally { setActionLoading(false) }
  }

  const handleModifyOrder = async () => {
    if (!modifyOrderModal.order || !orderPrice) return
    const order = modifyOrderModal.order
    setActionLoading(true)
    try {
      const res = await fetch('/api/mt5/modify-order', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ticket: order.ticket,
          price: parseFloat(orderPrice),
          sl: orderSL ? parseFloat(orderSL) : undefined,
          tp: orderTP ? parseFloat(orderTP) : undefined,
          // MT5 treats a modify without expiration as GTC, so re-send the existing one
          expiration: order.time_expiration && order.time_expiration > 0
            ? new Date(order.time_expiration * 1000).toISOString()
            : undefined,
        }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => null)
        throw new Error(err?.error || err?.message || 'Broker rejected the change')
      }
      setModifyOrderModal({ open: false, order: null })
      await fetchData()
      toast.success('Order Modified', { description: `Order #${order.ticket} has been updated` })
    } catch (err) {
      toast.error('Modify failed', { description: err instanceof Error ? err.message : undefined })
    } finally { setActionLoading(false) }
  }

  // Mobile edit sheet save — same endpoint and body as handleModifyOrder, but reports
  // broker rejections so the sheet stays open for correction.
  const handleMobileOrderSave = async (payload: ModifyOrderPayload): Promise<boolean> => {
    setActionLoading(true)
    try {
      const res = await fetch('/api/mt5/modify-order', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => null)
        throw new Error(err?.error || err?.message || 'Broker rejected the change')
      }
      await fetchData()
      toast.success('Order Updated', { description: `Order #${payload.ticket} has been updated` })
      return true
    } catch (err) {
      toast.error('Update failed', { description: err instanceof Error ? err.message : undefined })
      return false
    } finally {
      setActionLoading(false)
    }
  }

  const confirmCancelOrder = (order: Order) => {
    setMobileEditOrder(null)
    setConfirmDialog({
      open: true,
      title: 'Delete Order',
      message: `Delete ${getOrderTypeName(order.type)} ${order.symbol} #${order.ticket}?`,
      danger: true,
      onConfirm: () => cancelOrder(order),
    })
  }

  const closeAll = async () => {
    setConfirmDialog({
      open: true,
      title: 'LIQUIDATE ACCOUNT',
      message: 'Close ALL positions and cancel ALL orders immediately?',
      onConfirm: async () => {
        setActionLoading(true)
        try {
          await fetch('/api/mt5/close-all', { method: 'POST' })
          await Promise.all(orders.map(o => fetch('/api/mt5/cancel-order', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ticket: o.ticket }) })))
          await fetchData()
          toast.success('Account Liquidated', { description: 'All positions and orders have been closed' })
        } finally { setActionLoading(false) }
      }
    })
  }

  useEffect(() => {
    if (intervalRef.current) clearInterval(intervalRef.current)
    if (refreshInterval === 0) {
      intervalRef.current = null
      return
    }
    intervalRef.current = setInterval(() => {
      fetchLiveData()
    }, refreshInterval * 1000)
    return () => { if (intervalRef.current) clearInterval(intervalRef.current) }
  }, [refreshInterval, fetchLiveData])

  // Handle custom events from mobile header buttons
  useEffect(() => {
    const handleSmartCloseSettings = () => setSettingsModal(true)
    const handleRefreshSettings = () => setMobileRefreshModal(true)

    document.addEventListener('open-smart-close-settings', handleSmartCloseSettings)
    document.addEventListener('open-refresh-settings', handleRefreshSettings)

    return () => {
      document.removeEventListener('open-smart-close-settings', handleSmartCloseSettings)
      document.removeEventListener('open-refresh-settings', handleRefreshSettings)
    }
  }, [])

  const getPips = (position: Position) => {
    const diff = position.type === 0 ? position.price_current - position.price_open : position.price_open - position.price_current
    // Determine pip multiplier based on symbol
    let multiplier = 10000 // Default for standard forex (1 pip = 0.0001)
    if (position.symbol.includes('JPY')) {
      multiplier = 100 // JPY pairs (1 pip = 0.01)
    } else if (position.symbol.includes('XAU') || position.symbol.includes('GOLD')) {
      multiplier = 10 // Gold (1 pip = 0.1)
    } else if (position.symbol.includes('XAG') || position.symbol.includes('SILVER') || position.symbol.includes('XPD') || position.symbol.includes('XPT')) {
      multiplier = 100 // Silver / Platinum / Palladium (1 pip = 0.01, digits=3)
    } else if (position.symbol.includes('BTC') || position.symbol.includes('ETH')) {
      multiplier = 10 // Crypto (1 pip = 0.1)
    }
    return (diff * multiplier).toFixed(1)
  }

  const getPossibleLoss = (pos: Position): number | null => {
    if (pos.sl <= 0) return null
    const priceDiff = pos.type === 0 ? pos.price_current - pos.price_open : pos.price_open - pos.price_current
    if (Math.abs(priceDiff) < 0.000001 || pos.volume === 0) return null
    const ratePerUnit = pos.profit / (priceDiff * pos.volume)
    const slDiff = pos.type === 0 ? pos.price_open - pos.sl : pos.sl - pos.price_open
    return -(slDiff * pos.volume * ratePerUnit)
  }

  const getPossibleProfit = (pos: Position): number | null => {
    if (pos.tp <= 0) return null
    const priceDiff = pos.type === 0 ? pos.price_current - pos.price_open : pos.price_open - pos.price_current
    if (Math.abs(priceDiff) < 0.000001 || pos.volume === 0) return null
    const ratePerUnit = pos.profit / (priceDiff * pos.volume)
    const tpDiff = pos.type === 0 ? pos.tp - pos.price_open : pos.price_open - pos.tp
    return tpDiff * pos.volume * ratePerUnit
  }

  const getOrderTypeName = (type: number) => {
    const types: Record<number, string> = { 0: 'BUY', 1: 'SELL', 2: 'BUY LIMIT', 3: 'SELL LIMIT', 4: 'BUY STOP', 5: 'SELL STOP' }
    return types[type] || `TYPE_${type}`
  }

  // getInstrumentInfo is now imported from '@/components/InstrumentSymbol' (shared).

  const renderSparkline = (data: any[], color: string) => (
    <div className="h-10 w-20">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data}>
          <Area type="monotone" dataKey="value" stroke={color} fill={color} fillOpacity={0.1} strokeWidth={2} isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )

  const mockSparkline = [{ value: 10 }, { value: 15 }, { value: 12 }, { value: 18 }, { value: 20 }]

  if (loading && !account) return (
    <div className="fixed inset-0 z-[100] flex flex-col items-center justify-center tech-canvas tech-grid-bg">
      <div className="glow-primary" />
      <div className="glow-secondary" />
      <div className="relative z-10">
        <div className="relative tech-card p-8 rounded-2xl flex flex-col items-center gap-6 overflow-hidden">
          <div className="relative">
            <Activity className="h-12 w-12 text-primary" />
            <div className="absolute inset-0 border-2 border-primary/20 border-t-primary rounded-full animate-spin" />
          </div>
          <div className="text-center space-y-2">
            <h2 className="font-mono text-xs font-bold text-foreground uppercase tracking-[0.2em] animate-pulse">Initializing Terminal</h2>
            <p className="font-mono text-[10px] font-semibold text-primary/70 uppercase tracking-[0.18em]">Neural Link Syncing...</p>
          </div>
        </div>
      </div>
    </div>
  )

  return (
    <div className="flex min-h-full flex-col">
      <MobilePageHeader 
        title="Neural Account" 
        subtitle={provider?.label || 'LIVE ENGINE'}
        hidden
        icon={<Activity className="h-5 w-5 text-primary" />}
      />

      <header className="hidden md:flex sticky top-0 z-40 w-full tech-header">
        <div className="max-w-[1800px] w-full mx-auto flex h-14 items-center px-6 gap-3">
          <div className="p-1.5 rounded-lg bg-primary/10 border border-primary/20">
            <Activity className="h-5 w-5 text-primary" />
          </div>
          <div className="flex flex-col gap-0.5">
            <div className="flex items-center gap-2">
              <h1 className="text-sm font-bold text-foreground leading-none">Account</h1>
              <span className="font-mono text-[9px] tracking-[0.15em] text-muted-foreground/50 uppercase">/ trading</span>
            </div>
            <p className="font-mono text-[9px] text-muted-foreground/60 tracking-widest uppercase">MT5 Terminal</p>
          </div>

          <div className="ml-auto flex items-center gap-3">
            {provider && (
              <div className="hidden lg:flex items-center gap-2 px-2.5 py-1 rounded-md bg-accent border border-border">
                <Server className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="text-xs font-medium text-foreground">{provider.label}</span>
              </div>
            )}

            <div className="flex items-center gap-2 bg-accent px-2 py-1 rounded-md border border-border">
              <Button
                onClick={handleManualRefresh}
                variant="ghost"
                size="sm"
                className="h-6 w-6 p-0 hover:bg-muted"
                disabled={isRefreshing}
              >
                <RefreshCw className={`h-3.5 w-3.5 text-muted-foreground ${isRefreshing ? 'animate-spin' : ''}`} />
              </Button>
              <div className="h-3.5 w-px bg-border" />
              {lastRefresh && (
                <>
                  <span className="font-mono text-[10px] text-muted-foreground">
                    {lastRefresh.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                  </span>
                  <div className="h-3.5 w-px bg-border" />
                </>
              )}
              <div className="flex items-center gap-1.5">
                <Clock className="h-3.5 w-3.5 text-muted-foreground" />
                <select
                  value={refreshInterval}
                  onChange={(e) => {
                    const val = Number(e.target.value)
                    handleRefreshIntervalChange(val)
                  }}
                  className="w-16 bg-transparent font-mono text-xs font-medium text-foreground outline-none cursor-pointer border border-border rounded px-1 py-0.5"
                >
                  <option value={0}>Off</option>
                  <option value={1}>1s</option>
                  <option value={5}>5s</option>
                  <option value={10}>10s</option>
                  <option value={30}>30s</option>
                  <option value={60}>60s</option>
                </select>
              </div>
              <div className="h-3.5 w-px bg-border" />
              <Button
                onClick={() => setSettingsModal(true)}
                variant="ghost"
                size="sm"
                className="h-6 w-6 p-0 hover:bg-muted"
                title="Settings"
              >
                <Settings className="h-3.5 w-3.5 text-muted-foreground" />
              </Button>
            </div>
          </div>
        </div>
      </header>

      <div className="flex-1 px-3 md:px-4 py-3 md:py-4">
        <div className="flex flex-col gap-3 md:gap-6 max-w-[1800px] mx-auto">
        {/* ── MOBILE STATS LAYOUT ── */}
        <div className="md:hidden flex flex-col gap-3">
          {/* Hero Equity Card */}
          <div className="relative rounded-2xl overflow-hidden bg-gradient-to-br from-blue-600 via-blue-500 to-indigo-600 p-5 shadow-lg">
            {/* Background sparkline */}
            <div className="absolute inset-0 opacity-20">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={mockSparkline} margin={{ top: 0, right: 0, left: 0, bottom: 0 }}>
                  <Area type="monotone" dataKey="value" stroke="white" fill="white" fillOpacity={0.3} strokeWidth={2} isAnimationActive={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
            <div className="relative z-10">
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-bold text-blue-100 uppercase tracking-widest">Equity</span>
                <div className="flex items-center gap-1.5">
                  <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                  <span className="text-xs text-blue-100 font-semibold">Live</span>
                </div>
              </div>
              <p className="text-4xl font-black text-white tracking-tight mb-1">
                {account ? formatCurrency(account.equity) : '—'}
              </p>
              <div className="flex items-center gap-2 mb-4">
                <span className={`text-sm font-bold ${account && account.profit >= 0 ? 'text-success/70' : 'text-destructive/70'}`}>
                  {account && account.profit >= 0 ? '+' : ''}{account ? formatCurrency(account.profit) : '—'}
                </span>
                <span className={`text-xs font-semibold ${account && account.profit >= 0 ? 'text-success/70' : 'text-destructive/70'}`}>
                  ({account && account.balance > 0 ? `${((account.profit / account.balance) * 100).toFixed(2)}%` : '0%'}) today
                </span>
              </div>
              <div className="flex items-center justify-between border-t border-white/10 pt-3">
                <span className="text-xs text-blue-200">vs Balance</span>
                <span className="text-sm font-bold text-white">{account ? formatCurrency(account.balance) : '—'}</span>
              </div>
            </div>
          </div>

          {/* Single P/L view replaces the Overview / Performance card grids */}
          <MobilePerformance history={history} />
        </div>

        {/* ── DESKTOP STATS GRID ── */}
        <div className="hidden md:grid grid-cols-4 lg:grid-cols-8 gap-3">
          {/* Balance */}
          <Card className="tech-card tech-card-blue border-border relative overflow-hidden">
            <div className="absolute inset-0 bg-gradient-to-br from-blue-500/[0.04] to-transparent pointer-events-none" />
            <CardContent className="p-4 relative">
              <div className="flex items-center gap-1.5 mb-1.5">
                <div className="w-5 h-5 rounded-md bg-blue-500/10 flex items-center justify-center shrink-0">
                  <Wallet className="h-3 w-3 text-primary" />
                </div>
                <p className="tech-label">Balance</p>
              </div>
              <p className="text-lg font-bold text-foreground mb-0.5 font-mono">{account ? formatCurrency(account.balance) : '—'}</p>
              <p className={`text-[10px] font-semibold flex items-center gap-0.5 ${account && account.profit >= 0 ? 'text-success' : 'text-destructive'}`}>
                {account && account.profit >= 0 ? <ArrowUpRight className="h-2.5 w-2.5" /> : <ArrowDownRight className="h-2.5 w-2.5" />}
                {account && account.balance > 0 ? `${((account.profit / account.balance) * 100).toFixed(2)}%` : '0.00%'} today
              </p>
            </CardContent>
          </Card>

          {/* Equity */}
          <Card className="tech-card tech-card-blue border-border relative overflow-hidden">
            <div className="absolute inset-0 bg-gradient-to-br from-indigo-500/[0.04] to-transparent pointer-events-none" />
            <CardContent className="p-4 relative">
              <div className="flex items-center justify-between mb-1.5">
                <div className="flex items-center gap-1.5">
                  <div className="w-5 h-5 rounded-md bg-indigo-500/10 flex items-center justify-center shrink-0">
                    <BarChart3 className="h-3 w-3 text-indigo-500" />
                  </div>
                  <p className="tech-label">Equity</p>
                </div>
                <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse shrink-0" />
              </div>
              <p className="text-lg font-bold text-foreground mb-0.5 font-mono">{account ? formatCurrency(account.equity) : '—'}</p>
              <p className={`text-[10px] font-semibold flex items-center gap-0.5 ${account && account.equity >= (account?.balance ?? 0) ? 'text-success' : 'text-destructive'}`}>
                {account && account.equity >= (account?.balance ?? 0) ? <ArrowUpRight className="h-2.5 w-2.5" /> : <ArrowDownRight className="h-2.5 w-2.5" />}
                {account && account.balance > 0 ? `${Math.abs(((account.equity - account.balance) / account.balance) * 100).toFixed(2)}%` : '0.00%'} today
              </p>
            </CardContent>
          </Card>

          {/* P/L */}
          <Card className={`tech-card border-border relative overflow-hidden ${account && account.profit >= 0 ? 'tech-card-emerald' : 'tech-card-rose'}`}>
            <div className={`absolute inset-0 pointer-events-none bg-gradient-to-br ${account && account.profit >= 0 ? 'from-emerald-500/[0.05]' : 'from-red-500/[0.05]'} to-transparent`} />
            <CardContent className="p-4 relative">
              <div className="flex items-center justify-between mb-1.5">
                <div className="flex items-center gap-1.5">
                  <div className={`w-5 h-5 rounded-md flex items-center justify-center shrink-0 ${account && account.profit >= 0 ? 'bg-emerald-500/10' : 'bg-red-500/10'}`}>
                    {account && account.profit >= 0
                      ? <TrendingUp className="h-3 w-3 text-success" />
                      : <TrendingDown className="h-3 w-3 text-destructive" />}
                  </div>
                  <p className="tech-label">P / L</p>
                </div>
                <div className={`w-1.5 h-1.5 rounded-full animate-pulse shrink-0 ${account && account.profit >= 0 ? 'bg-emerald-500' : 'bg-red-500'}`} />
              </div>
              <p className={`text-lg font-bold mb-0.5 font-mono ${account && account.profit >= 0 ? 'text-success' : 'text-destructive'}`}>
                {account ? `${account.profit >= 0 ? '+' : ''}${formatCurrency(account.profit)}` : '—'}
              </p>
              <p className={`text-[10px] font-semibold ${account && account.profit >= 0 ? 'text-success' : 'text-destructive'}`}>
                {account && account.balance > 0 ? `${((account.profit / account.balance) * 100).toFixed(2)}%` : '0.00%'} today
              </p>
            </CardContent>
          </Card>

          {/* Free Margin */}
          <Card className="tech-card tech-card-emerald border-border relative overflow-hidden">
            <div className="absolute inset-0 bg-gradient-to-br from-emerald-500/[0.04] to-transparent pointer-events-none" />
            <CardContent className="p-4 relative">
              <div className="flex items-center gap-1.5 mb-1.5">
                <div className="w-5 h-5 rounded-md bg-emerald-500/10 flex items-center justify-center shrink-0">
                  <Shield className="h-3 w-3 text-success" />
                </div>
                <p className="tech-label">Free Margin</p>
              </div>
              <p className="text-lg font-bold text-foreground mb-0.5 font-mono">{account ? formatCurrency(account.margin_free) : '—'}</p>
              <p className="text-[10px] font-semibold text-success">
                {account && account.equity > 0 ? `${((account.margin_free / account.equity) * 100).toFixed(1)}%` : '0.0%'} of equity
              </p>
            </CardContent>
          </Card>

          {/* Win Rate */}
          <Card className="tech-card tech-card-gold border-border relative overflow-hidden">
            <div className="absolute inset-0 bg-gradient-to-br from-amber-500/[0.04] to-transparent pointer-events-none" />
            <CardContent className="p-4 relative">
              <div className="flex items-center gap-1.5 mb-1.5">
                <div className="w-5 h-5 rounded-md bg-amber-500/10 flex items-center justify-center shrink-0">
                  <Target className="h-3 w-3 text-gold" />
                </div>
                <p className="tech-label">Win Rate</p>
              </div>
              <p className="text-lg font-bold text-foreground mb-0.5 font-mono">{stats?.win_rate?.toFixed(1) || '—'}%</p>
              <div className="flex items-center gap-1.5">
                <div className="flex-1 h-1 rounded-full bg-slate-200 overflow-hidden">
                  <div className="h-full rounded-full bg-amber-500 transition-all" style={{ width: `${stats?.win_rate || 0}%` }} />
                </div>
                <span className="text-[9px] text-muted-foreground font-mono shrink-0">{stats?.wins || 0}W/{stats?.losses || 0}L</span>
              </div>
            </CardContent>
          </Card>

          {/* Profit Factor */}
          <Card className="tech-card tech-card-gold border-border relative overflow-hidden">
            <div className="absolute inset-0 bg-gradient-to-br from-violet-500/[0.04] to-transparent pointer-events-none" />
            <CardContent className="p-4 relative">
              <div className="flex items-center justify-between mb-1.5">
                <div className="flex items-center gap-1.5">
                  <div className="w-5 h-5 rounded-md bg-violet-500/10 flex items-center justify-center shrink-0">
                    <Zap className="h-3 w-3 text-muted-foreground" />
                  </div>
                  <p className="tech-label">Profit Factor</p>
                </div>
                {stats?.profit_factor && (
                  <span className={`text-[9px] font-bold px-1 py-0.5 rounded shrink-0 ${stats.profit_factor >= 1.5 ? 'bg-emerald-500/10 text-success' : stats.profit_factor >= 1 ? 'bg-amber-500/10 text-gold' : 'bg-red-500/10 text-destructive'}`}>
                    {stats.profit_factor >= 1.5 ? 'Strong' : stats.profit_factor >= 1 ? 'Fair' : 'Weak'}
                  </span>
                )}
              </div>
              <p className="text-lg font-bold text-foreground mb-0.5 font-mono">{stats?.profit_factor?.toFixed(2) || '—'}</p>
              <p className="text-[10px] text-muted-foreground font-mono">avg win {formatCurrency(stats?.avg_win || 0)}</p>
            </CardContent>
          </Card>

          {/* Margin Level */}
          {(() => {
            const ml = account && account.margin > 0 ? (account.equity / account.margin) * 100 : 0
            const isSafe = ml > 200
            const isWarn = ml > 120 && ml <= 200
            return (
              <Card className={`tech-card border-border relative overflow-hidden ${isSafe ? 'tech-card-emerald' : isWarn ? 'tech-card-gold' : 'tech-card-rose'}`}>
                <div className={`absolute inset-0 pointer-events-none bg-gradient-to-br ${isSafe ? 'from-emerald-500/[0.04]' : isWarn ? 'from-amber-500/[0.04]' : 'from-red-500/[0.04]'} to-transparent`} />
                <CardContent className="p-4 relative">
                  <div className="flex items-center justify-between mb-1.5">
                    <div className="flex items-center gap-1.5">
                      <div className={`w-5 h-5 rounded-md flex items-center justify-center shrink-0 ${isSafe ? 'bg-emerald-500/10' : isWarn ? 'bg-amber-500/10' : 'bg-red-500/10'}`}>
                        <Activity className={`h-3 w-3 ${isSafe ? 'text-success' : isWarn ? 'text-gold' : 'text-destructive'}`} />
                      </div>
                      <p className="tech-label">Margin Lvl</p>
                    </div>
                    <span className={`text-[9px] font-bold px-1 py-0.5 rounded shrink-0 ${isSafe ? 'bg-emerald-500/10 text-success' : isWarn ? 'bg-amber-500/10 text-gold' : 'bg-red-500/10 text-destructive'}`}>
                      {isSafe ? 'Safe' : isWarn ? 'Warn' : 'Risk'}
                    </span>
                  </div>
                  <p className="text-lg font-bold text-foreground mb-0.5 font-mono">{ml > 0 ? `${ml.toFixed(0)}%` : '—'}</p>
                  <p className="text-[10px] text-muted-foreground font-mono">used {formatCurrency(account?.margin || 0)}</p>
                </CardContent>
              </Card>
            )
          })()}

          {/* Volume */}
          <Card className="tech-card tech-card-blue border-border relative overflow-hidden">
            <div className="absolute inset-0 bg-gradient-to-br from-cyan-500/[0.04] to-transparent pointer-events-none" />
            <CardContent className="p-4 relative">
              <div className="flex items-center gap-1.5 mb-1.5">
                <div className="w-5 h-5 rounded-md bg-cyan-500/10 flex items-center justify-center shrink-0">
                  <BarChart3 className="h-3 w-3 text-cyan-500" />
                </div>
                <p className="tech-label">Volume</p>
              </div>
              <p className="text-lg font-bold text-foreground mb-0.5 font-mono">
                {positions.reduce((sum, p) => sum + p.volume, 0).toFixed(2)} <span className="text-[10px] font-normal text-muted-foreground">lots</span>
              </p>
              <p className="text-[10px] text-muted-foreground font-mono">{positions.length} position{positions.length !== 1 ? 's' : ''}</p>
            </CardContent>
          </Card>
        </div>

        {/* ── Danger Zone Sticky Bar ── */}
        {(positions.length > 0 || orders.length > 0) && (
          <div className="hidden md:block sticky top-14 z-30 -mx-3 md:-mx-4 px-3 md:px-4 py-2 bg-destructive/5 backdrop-blur-[12px] border-b border-destructive/20 shadow-sm">
            <div className="max-w-[1800px] mx-auto flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-1.5 text-xs font-bold text-destructive uppercase tracking-wider">
                <AlertTriangle className="h-3.5 w-3.5 text-destructive" />
                Danger Zone
              </div>
              <Button
                onClick={closeAll}
                disabled={actionLoading}
                size="sm"
                className="h-8 px-4 text-[11px] font-bold bg-red-600 hover:bg-red-700 text-white border-0 shadow-sm"
              >
                {actionLoading
                  ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />
                  : <AlertTriangle className="h-3.5 w-3.5 mr-1.5" />
                }
                Liquidate All — {positions.length > 0 ? `${positions.length} position${positions.length !== 1 ? 's' : ''}` : ''}{positions.length > 0 && orders.length > 0 ? ' + ' : ''}{orders.length > 0 ? `${orders.length} order${orders.length !== 1 ? 's' : ''}` : ''}
              </Button>
            </div>
          </div>
        )}

        {/* Main Content Tabs */}
        <div className="overflow-hidden md:overflow-visible">
          <Tabs value={activeTab} onValueChange={handleTabChange} className="w-full">
            {/* Mobile tabs */}
            <TabsList className="md:hidden grid w-full grid-cols-4 h-11 p-0 mb-3 bg-transparent rounded-none border-b border-border">
              {[
                { value: 'positions', label: 'Positions', count: positions.length },
                { value: 'orders', label: 'Orders', count: orders.length },
                { value: 'history', label: 'History' },
                { value: 'risk', label: 'Risk' },
              ].map(t => (
                <TabsTrigger
                  key={t.value}
                  value={t.value}
                  className="h-full gap-1 px-1 rounded-none border-b-2 border-transparent -mb-px text-[13px] font-semibold text-muted-foreground data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:text-foreground data-[state=active]:border-primary"
                >
                  {t.label}
                  {t.count !== undefined && t.count > 0 && <span className="font-mono text-[11px] text-muted-foreground tabular-nums">{t.count}</span>}
                </TabsTrigger>
              ))}
            </TabsList>
            <TabsList className="hidden md:grid w-full grid-cols-3 h-[52px] md:h-10 md:w-[450px] bg-card/90 md:bg-muted backdrop-blur-[14px] md:backdrop-blur-none border border-border md:border-0 shadow-[0_8px_24px_rgba(0,0,0,0.3)] md:shadow-none rounded-[18px] md:rounded-lg p-1 mb-4 md:mb-6">
              <TabsTrigger value="trades" className="text-[11px] md:text-xs font-bold data-[state=active]:bg-primary/10 data-[state=active]:text-primary data-[state=active]:shadow-none rounded-[14px] md:rounded-md h-full transition-all">
                <span className="hidden sm:inline">Trades ({positions.length + orders.length})</span>
                <span className="sm:hidden">Trades ({positions.length + orders.length})</span>
              </TabsTrigger>
              <TabsTrigger value="risk" className="text-[11px] md:text-xs font-bold data-[state=active]:bg-primary/10 data-[state=active]:text-primary data-[state=active]:shadow-none rounded-[14px] md:rounded-md h-full transition-all">
                Risk
              </TabsTrigger>
              <TabsTrigger value="history" className="text-[11px] md:text-xs font-bold data-[state=active]:bg-primary/10 data-[state=active]:text-primary data-[state=active]:shadow-none rounded-[14px] md:rounded-md h-full transition-all">
                History
              </TabsTrigger>
            </TabsList>

            <TabsContent value="positions" className="md:hidden m-0">
              <MobilePositionsList
                positions={positions}
                actionLoading={actionLoading}
                smartClose={{ enabled: userSettings.smartCloseEnabled, setBreakeven: userSettings.smartCloseSetBreakeven, percentage: userSettings.smartClosePercentage }}
                getPips={p => getPips(p as Position)}
                getPossibleLoss={p => getPossibleLoss(p as Position)}
                getPossibleProfit={p => getPossibleProfit(p as Position)}
                onSmartClose={p => smartClose(p as Position)}
                onBreakeven={p => setBreakeven(p as Position)}
                onEdit={p => {
                  setModifyModal({ open: true, position: p as Position })
                  setModifySL(p.sl.toString())
                  setModifyTP(p.tp.toString())
                }}
                onPartial={p => {
                  setPartialCloseModal({ open: true, position: p as Position })
                  setPartialVolume((p.volume / 2).toFixed(2))
                }}
                onChart={p => setChartSymbol(p.symbol)}
                onClose={p => closePosition(p as Position)}
                bulkActions={[
                  { label: 'All BE', icon: <TrendingUpDown className="h-4 w-4" />, onClick: setAllBreakeven, disabled: positions.filter(p => p.profit > 0).length === 0 },
                  { label: 'Profits', icon: <ArrowUpCircle className="h-4 w-4" />, onClick: handleCloseProfitable, disabled: positions.filter(p => p.profit > 0).length === 0 },
                  { label: 'Losses', icon: <ArrowDownCircle className="h-4 w-4" />, onClick: handleCloseLosing, disabled: positions.filter(p => p.profit < 0).length === 0 },
                  { label: 'Close all', icon: <XCircle className="h-4 w-4" />, onClick: closeAllPositions, danger: true },
                  { label: 'Liquidate', icon: <AlertTriangle className="h-4 w-4" />, onClick: closeAll, danger: true },
                ]}
              />
            </TabsContent>

            <TabsContent value="orders" className="md:hidden m-0">
              <MobileOrdersList
                orders={orders}
                actionLoading={actionLoading}
                onSelect={o => setMobileEditOrder(o as Order)}
                onCancelAll={closeAllOrders}
              />
            </TabsContent>

            <TabsContent value="trades" className="m-0 space-y-4">
              {/* Active Positions */}
              <Card className="bg-card border border-border rounded-xl shadow-sm">
                <CardHeader className="pb-3 pt-4 px-5 border-b border-border/50">
                  <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 sm:gap-0">
                    <div>
                      <CardTitle className="text-sm font-semibold text-foreground">Active Positions</CardTitle>
                      <p className="text-xs text-muted-foreground/70 mt-0.5">{positions.length} active position{positions.length !== 1 ? 's' : ''}</p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2 w-full sm:w-auto">
                      {positions.length > 0 && (
                        <Button 
                          onClick={setAllBreakeven}
                          disabled={actionLoading || positions.filter(p => p.profit > 0).length === 0}
                          variant="outline"
                          size="sm"
                          className="h-8 text-xs px-3 border-blue-200 text-primary hover:bg-primary/10"
                        >
                          Set All BE
                        </Button>
                      )}
                      {positions.length > 0 && (
                        <Button 
                          onClick={handleCloseProfitable}
                          disabled={actionLoading || positions.filter(p => p.profit > 0).length === 0}
                          variant="outline"
                          size="sm"
                          className="h-8 text-xs px-3 border-emerald-200 text-success hover:bg-success/10"
                        >
                          Close Profits
                        </Button>
                      )}
                      {positions.length > 0 && (
                        <Button 
                          onClick={handleCloseLosing}
                          disabled={actionLoading || positions.filter(p => p.profit < 0).length === 0}
                          variant="outline"
                          size="sm"
                          className="h-8 text-xs px-3 border-orange-200 text-orange-600 hover:bg-orange-50"
                        >
                          Cut Losses
                        </Button>
                      )}
                      {positions.length > 0 && (
                        <Button 
                          onClick={closeAllPositions}
                          disabled={actionLoading || positions.length === 0}
                          variant="outline"
                          size="sm"
                          className="h-8 text-xs px-3 text-destructive border-red-200 hover:bg-red-50"
                        >
                          Close All
                        </Button>
                      )}
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="p-0">
                  {positions.length === 0 ? (
                    <div className="py-12 text-center">
                      <Activity className="h-10 w-10 mx-auto text-muted-foreground/50 mb-2" />
                      <p className="text-xs font-medium text-muted-foreground">No open positions</p>
                    </div>
                  ) : (
                    <>
                      {/* Totals Summary Strip */}
                      {(() => {
                        const totalPossLoss = positions.reduce((sum, pos) => {
                          const v = getPossibleLoss(pos)
                          return sum + (v !== null ? v : 0)
                        }, 0)
                        const totalPossProfit = positions.reduce((sum, pos) => {
                          const v = getPossibleProfit(pos)
                          return sum + (v !== null ? v : 0)
                        }, 0)
                        const totalCurrentPL = positions.reduce((sum, pos) => sum + pos.profit, 0)
                        const rrRatio = totalPossLoss !== 0 ? Math.abs(totalPossProfit / totalPossLoss).toFixed(2) : null
                        return (
                          <div className="flex flex-wrap items-center gap-3 px-5 py-3 bg-muted/30 border-b border-border/50 text-xs">
                            <div className="flex items-center gap-1.5">
                              <span className="text-muted-foreground font-medium uppercase tracking-wide">Current P/L:</span>
                              <span className={`font-bold ${totalCurrentPL >= 0 ? 'text-success' : 'text-destructive'}`}>
                                {totalCurrentPL >= 0 ? '+' : ''}{formatCurrency(totalCurrentPL)}
                              </span>
                            </div>
                            <div className="w-px h-3 bg-border/70" />
                            <div className="flex items-center gap-1.5">
                              <span className="text-muted-foreground font-medium uppercase tracking-wide">If All SL Hit:</span>
                              <span className="font-bold text-destructive">{formatCurrency(totalPossLoss)}</span>
                            </div>
                            <div className="w-px h-3 bg-border/70" />
                            <div className="flex items-center gap-1.5">
                              <span className="text-muted-foreground font-medium uppercase tracking-wide">If All TP Hit:</span>
                              <span className="font-bold text-success">+{formatCurrency(totalPossProfit)}</span>
                            </div>
                            {rrRatio && (
                              <>
                                <div className="w-px h-3 bg-border/70" />
                                <div className="flex items-center gap-1.5">
                                  <span className="text-muted-foreground font-medium uppercase tracking-wide">R:R Ratio:</span>
                                  <span className="font-bold text-foreground">1 : {rrRatio}</span>
                                </div>
                              </>
                            )}
                          </div>
                        )
                      })()}
                      <div className="overflow-x-auto hidden md:block">
                        <table className="w-full">
                        <thead className="bg-muted/50 border-b border-border/50">
                          <tr>
                            <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">Symbol</th>
                            <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">Type</th>
                            <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">Volume</th>
                            <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">Open Price</th>
                            <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">Current Price</th>
                            <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">P/L (Pips)</th>
                            <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">P/L (USD)</th>
                            <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">Poss. Loss</th>
                            <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">Poss. Profit</th>
                            <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">SL / TP</th>
                            <th className="px-5 py-3 text-center text-xs font-medium text-muted-foreground uppercase tracking-wide">Actions</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100">
                          {positions.map((pos) => (
                            <tr key={pos.ticket} className="hover:bg-muted/40 transition-colors">
                              <td className="px-5 py-4">
                                <div className="flex items-center gap-2">
                                  <div className="relative w-10 h-10">
                                    {(() => {
                                      if (!mounted) return null
                                      const info = getInstrumentInfo(pos.symbol)
                                      
                                      if (info.type === 'forex' && info.base && info.quote) {
                                        return (
                                          <>
                                            <div className="absolute left-0 top-0 w-5 h-10 overflow-hidden rounded-l-full border-l border-t border-b border-border">
                                              <img
                                                src={`/flags/l/${info.base}.svg`}
                                                alt={info.base}
                                                className="w-full h-full object-cover"
                                              />
                                            </div>
                                            <div className="absolute right-0 top-0 w-5 h-10 overflow-hidden rounded-r-full border-r border-t border-b border-border">
                                              <img
                                                src={`/flags/l/${info.quote}.svg`}
                                                alt={info.quote}
                                                className="w-full h-full object-cover"
                                              />
                                            </div>
                                          </>
                                        )
                                      } else {
                                        return (
                                          <div className={`w-10 h-10 rounded-full ${info.iconUrl ? 'bg-card' : `bg-gradient-to-br ${info.color || 'from-blue-400 to-blue-600'}`} flex items-center justify-center border border-border shadow-sm overflow-hidden`}>
                                            {info.iconUrl ? (
                                              <Image 
                                                src={info.iconUrl}
                                                alt={pos.symbol}
                                                width={32}
                                                height={32}
                                                className="w-7 h-7 object-contain"
                                              />
                                            ) : info.iconType ? (
                                              <InstrumentIcon type={info.iconType} className={`w-6 h-6 ${info.iconColor || 'text-white'}`} />
                                            ) : (
                                              <span className="text-lg font-bold text-white">{info.icon || pos.symbol.substring(0, 2)}</span>
                                            )}
                                          </div>
                                        )
                                      }
                                    })()}
                                  </div>
                                  <div>
                                    <p className="text-sm font-semibold text-foreground">{pos.symbol}</p>
                                    <p className="text-xs text-muted-foreground/70">#{pos.ticket}</p>
                                  </div>
                                </div>
                              </td>
                              <td className="px-5 py-4">
                                <Badge className={`px-2 py-1 text-xs font-semibold ${pos.type === 0 ? 'bg-success/10 text-success border border-success/20' : 'bg-red-100 text-destructive'}`}>
                                  {getOrderTypeName(pos.type)}
                                </Badge>
                              </td>
                              <td className="px-5 py-4 text-sm font-medium text-foreground">{pos.volume}</td>
                              <td className="px-5 py-4 text-sm font-mono text-foreground/80">{pos.price_open.toFixed(5)}</td>
                              <td className="px-5 py-4 text-sm font-mono text-foreground/80">{pos.price_current.toFixed(5)}</td>
                              <td className="px-5 py-4">
                                <span className={`text-sm font-semibold ${parseFloat(getPips(pos)) >= 0 ? 'text-success' : 'text-destructive'}`}>
                                  {parseFloat(getPips(pos)) >= 0 ? '+' : ''}{getPips(pos)}
                                </span>
                              </td>
                              <td className="px-5 py-4">
                                <span className={`text-sm font-semibold ${pos.profit >= 0 ? 'text-success' : 'text-destructive'}`}>
                                  {pos.profit >= 0 ? '+' : ''}{formatCurrency(pos.profit)}
                                </span>
                              </td>
                              <td className="px-5 py-4">
                                {(() => {
                                  const loss = getPossibleLoss(pos)
                                  return loss !== null ? (
                                    <span className="text-sm font-semibold text-destructive">
                                      {formatCurrency(loss)}
                                    </span>
                                  ) : (
                                    <span className="text-xs text-muted-foreground/50">---</span>
                                  )
                                })()}
                              </td>
                              <td className="px-5 py-4">
                                {(() => {
                                  const profit = getPossibleProfit(pos)
                                  return profit !== null ? (
                                    <span className="text-sm font-semibold text-success">
                                      +{formatCurrency(profit)}
                                    </span>
                                  ) : (
                                    <span className="text-xs text-muted-foreground/50">---</span>
                                  )
                                })()}
                              </td>
                              <td className="px-5 py-4">
                                <div className="flex flex-col gap-0.5 text-xs font-mono">
                                  {editingCell?.ticket === pos.ticket && editingCell?.field === 'sl' ? (
                                    <div className="flex items-center gap-1">
                                      <span className="text-destructive font-semibold">SL:</span>
                                      <input
                                        ref={editInputRef}
                                        type="number"
                                        step="0.00001"
                                        value={editValue}
                                        onChange={e => setEditValue(e.target.value)}
                                        onBlur={handleInlineSLTPEdit}
                                        onKeyDown={e => {
                                          if (e.key === 'Enter') handleInlineSLTPEdit()
                                          if (e.key === 'Escape') setEditingCell(null)
                                        }}
                                        className="w-20 h-6 text-xs font-mono bg-card border border-rose-300 rounded px-1 focus:outline-none focus:ring-1 focus:ring-rose-500"
                                        autoFocus
                                      />
                                    </div>
                                  ) : (
                                    <span
                                      className={`cursor-pointer hover:bg-destructive/10 rounded px-0.5 -mx-0.5 ${pos.sl > 0 ? 'text-destructive font-semibold' : 'text-muted-foreground/50'}`}
                                      title="Double-click to edit SL"
                                      onDoubleClick={() => {
                                        setEditingCell({ ticket: pos.ticket, field: 'sl' })
                                        setEditValue(pos.sl > 0 ? pos.sl.toFixed(5) : '')
                                        setTimeout(() => editInputRef.current?.focus(), 50)
                                      }}
                                    >
                                      SL: {pos.sl > 0 ? pos.sl.toFixed(5) : '---'}
                                    </span>
                                  )}
                                  {editingCell?.ticket === pos.ticket && editingCell?.field === 'tp' ? (
                                    <div className="flex items-center gap-1">
                                      <span className="text-success font-semibold">TP:</span>
                                      <input
                                        ref={editInputRef}
                                        type="number"
                                        step="0.00001"
                                        value={editValue}
                                        onChange={e => setEditValue(e.target.value)}
                                        onBlur={handleInlineSLTPEdit}
                                        onKeyDown={e => {
                                          if (e.key === 'Enter') handleInlineSLTPEdit()
                                          if (e.key === 'Escape') setEditingCell(null)
                                        }}
                                        className="w-20 h-6 text-xs font-mono bg-card border border-emerald-300 rounded px-1 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                                        autoFocus
                                      />
                                    </div>
                                  ) : (
                                    <span
                                      className={`cursor-pointer hover:bg-success/10 rounded px-0.5 -mx-0.5 ${pos.tp > 0 ? 'text-success font-semibold' : 'text-muted-foreground/50'}`}
                                      title="Double-click to edit TP"
                                      onDoubleClick={() => {
                                        setEditingCell({ ticket: pos.ticket, field: 'tp' })
                                        setEditValue(pos.tp > 0 ? pos.tp.toFixed(5) : '')
                                        setTimeout(() => editInputRef.current?.focus(), 50)
                                      }}
                                    >
                                      TP: {pos.tp > 0 ? pos.tp.toFixed(5) : '---'}
                                    </span>
                                  )}
                                </div>
                              </td>
                              <td className="px-5 py-4">
                                <div className="flex items-center justify-center gap-1">
                                  <Button 
                                    onClick={() => smartClose(pos)}
                                    variant="ghost"
                                    size="sm"
                                    disabled={actionLoading || !userSettings.smartCloseEnabled || pos.profit <= 0 || (userSettings.smartCloseSetBreakeven && Math.abs(pos.sl - pos.price_open) < 0.00001)}
                                    className="h-8 w-8 p-0 hover:bg-gold/10"
                                    title={pos.profit <= 0 ? 'Smart Close only available when in profit' : (userSettings.smartCloseSetBreakeven && Math.abs(pos.sl - pos.price_open) < 0.00001) ? 'Breakeven already set' : `Smart Close (${userSettings.smartClosePercentage}%${userSettings.smartCloseSetBreakeven ? ' + BE' : ''})`}
                                  >
                                    <Zap className={`h-3.5 w-3.5 ${pos.profit > 0 && !(userSettings.smartCloseSetBreakeven && Math.abs(pos.sl - pos.price_open) < 0.00001) ? 'text-gold' : 'text-muted-foreground/70'}`} />
                                  </Button>
                                  <Button 
                                    onClick={() => setBreakeven(pos)}
                                    variant="ghost"
                                    size="sm"
                                    disabled={actionLoading || Math.abs(pos.sl - pos.price_open) < 0.00001 || pos.profit <= 0}
                                    className="h-8 w-8 p-0 hover:bg-primary/10"
                                    title={pos.profit <= 0 ? 'Breakeven only available when in profit' : 'Set Breakeven (Move SL to Entry)'}
                                  >
                                    <TrendingUpDown className={`h-3.5 w-3.5 ${pos.profit > 0 && Math.abs(pos.sl - pos.price_open) >= 0.00001 ? 'text-primary' : 'text-muted-foreground/70'}`} />
                                  </Button>
                                  <Button 
                                    onClick={() => {
                                      setModifyModal({ open: true, position: pos })
                                      setModifySL(pos.sl.toString())
                                      setModifyTP(pos.tp.toString())
                                    }}
                                    variant="ghost"
                                    size="sm"
                                    disabled={actionLoading}
                                    className="h-8 w-8 p-0 hover:bg-muted"
                                    title="Modify SL/TP"
                                  >
                                    <Edit3 className="h-3.5 w-3.5 text-muted-foreground" />
                                  </Button>
                                  <Button 
                                    onClick={() => {
                                      setPartialCloseModal({ open: true, position: pos })
                                      setPartialVolume((pos.volume / 2).toFixed(2))
                                    }}
                                    variant="ghost"
                                    size="sm"
                                    disabled={actionLoading}
                                    className="h-8 w-8 p-0 hover:bg-orange-50"
                                    title="Partial Close"
                                  >
                                    <Maximize2 className="h-3.5 w-3.5 text-orange-600" />
                                  </Button>
                                  {positions.filter(p => p.symbol === pos.symbol).length > 1 && (
                                    <Button 
                                      onClick={() => handleCloseBySymbol(pos.symbol)}
                                      variant="ghost"
                                      size="sm"
                                      disabled={actionLoading}
                                      className="h-8 w-8 p-0 hover:bg-purple-50"
                                      title={`Close all ${pos.symbol}`}
                                    >
                                      <Scissors className="h-3.5 w-3.5 text-purple-600" />
                                    </Button>
                                  )}
                                  <Button
                                    onClick={() => setChartSymbol(pos.symbol)}
                                    variant="ghost"
                                    size="sm"
                                    className="h-8 w-8 p-0 hover:bg-cyan-50"
                                    title={`Chart — ${pos.symbol}`}
                                  >
                                    <TrendingUp className="h-3.5 w-3.5 text-cyan-600" />
                                  </Button>
                                  <Button 
                                    onClick={() => closePosition(pos)}
                                    variant="ghost"
                                    size="sm"
                                    disabled={actionLoading}
                                    className="h-8 w-8 p-0 hover:bg-red-50"
                                    title="Close Position"
                                  >
                                    <X className="h-3.5 w-3.5 text-destructive" />
                                  </Button>
                                </div>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    </>
                  )}
                </CardContent>
              </Card>

              {/* Pending Orders */}
              <Card className="bg-card border border-border rounded-xl shadow-sm">
                <CardHeader className="pb-3 pt-4 px-5 border-b border-border/50">
                  <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 sm:gap-0">
                    <CardTitle className="text-sm font-semibold text-foreground">Pending Orders ({orders.length})</CardTitle>
                    <div className="flex flex-wrap items-center gap-2 w-full sm:w-auto">
                      {orders.length > 0 && (
                      <Button 
                        onClick={closeAllOrders} 
                        disabled={actionLoading || orders.length === 0}
                        variant="outline"
                        size="sm"
                        className="h-8 text-xs px-3 text-destructive border-red-200 hover:bg-red-50"
                      >
                        Cancel All Orders
                      </Button>
                    )}
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="p-0">
                  {orders.length === 0 ? (
                    <div className="py-12 text-center">
                      <Clock className="h-10 w-10 mx-auto text-muted-foreground/50 mb-2" />
                      <p className="text-xs font-medium text-muted-foreground">No pending orders</p>
                    </div>
                  ) : (
                    <>
                    <div className="overflow-x-auto hidden md:block">
                      <table className="w-full">
                        <thead className="bg-muted/50 border-b border-border/50">
                          <tr>
                            <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">Symbol</th>
                            <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">Type</th>
                            <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">Volume</th>
                            <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">Target Price</th>
                            <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide">SL / TP</th>
                            <th className="px-5 py-3 text-center text-xs font-medium text-muted-foreground uppercase tracking-wide">Actions</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100">
                          {orders.map((order) => (
                            <tr key={order.ticket} className="hover:bg-muted/40 transition-colors">
                              <td className="px-5 py-4">
                                <div className="flex items-center gap-2">
                                  <div className="relative w-10 h-10">
                                    {(() => {
                                      if (!mounted) return null
                                      const info = getInstrumentInfo(order.symbol)
                                      
                                      if (info.type === 'forex' && info.base && info.quote) {
                                        return (
                                          <>
                                            <div className="absolute left-0 top-0 w-5 h-10 overflow-hidden rounded-l-full border-l border-t border-b border-border">
                                              <img
                                                src={`/flags/l/${info.base}.svg`}
                                                alt={info.base}
                                                className="w-full h-full object-cover"
                                              />
                                            </div>
                                            <div className="absolute right-0 top-0 w-5 h-10 overflow-hidden rounded-r-full border-r border-t border-b border-border">
                                              <img
                                                src={`/flags/l/${info.quote}.svg`}
                                                alt={info.quote}
                                                className="w-full h-full object-cover"
                                              />
                                            </div>
                                          </>
                                        )
                                      } else {
                                        return (
                                          <div className={`w-10 h-10 rounded-full ${info.iconUrl ? 'bg-card' : `bg-gradient-to-br ${info.color || 'from-blue-400 to-blue-600'}`} flex items-center justify-center border border-border shadow-sm overflow-hidden`}>
                                            {info.iconUrl ? (
                                              <Image 
                                                src={info.iconUrl}
                                                alt={order.symbol}
                                                width={32}
                                                height={32}
                                                className="w-7 h-7 object-contain"
                                              />
                                            ) : info.iconType ? (
                                              <InstrumentIcon type={info.iconType} className="w-6 h-6 text-white" />
                                            ) : (
                                              <span className="text-lg font-bold text-white">{info.icon || order.symbol.substring(0, 2)}</span>
                                            )}
                                          </div>
                                        )
                                      }
                                    })()}
                                  </div>
                                  <div>
                                    <p className="text-sm font-semibold text-foreground">{order.symbol}</p>
                                    <p className="text-xs text-muted-foreground/70">#{order.ticket}</p>
                                  </div>
                                </div>
                              </td>
                              <td className="px-5 py-4">
                                <Badge variant="outline" className="text-[10px] font-semibold bg-muted/50 text-muted-foreground border-border/50 uppercase">
                                  {getOrderTypeName(order.type)}
                                </Badge>
                              </td>
                              <td className="px-5 py-4 text-sm font-medium text-foreground">{(order.volume || order.volume_initial).toFixed(2)}</td>
                              <td className="px-5 py-4 text-sm font-mono text-foreground/80">{order.price_open.toFixed(5)}</td>
                              <td className="px-5 py-4 text-sm font-mono text-muted-foreground">
                                <div className="flex items-center gap-2">
                                  <span className="text-muted-foreground/70">S:</span>
                                  <span className={order.sl > 0 ? 'text-destructive font-semibold' : 'text-muted-foreground/50'}>{order.sl > 0 ? order.sl.toFixed(5) : '---'}</span>
                                </div>
                                <div className="flex items-center gap-2">
                                  <span className="text-muted-foreground/70">T:</span>
                                  <span className={order.tp > 0 ? 'text-success font-semibold' : 'text-muted-foreground/50'}>{order.tp > 0 ? order.tp.toFixed(5) : '---'}</span>
                                </div>
                              </td>
                              <td className="px-5 py-4">
                                <div className="flex items-center justify-center gap-1">
                                  <Button 
                                    onClick={() => {
                                      setModifyOrderModal({ open: true, order })
                                      setOrderPrice(order.price_open.toString())
                                      setOrderSL(order.sl.toString())
                                      setOrderTP(order.tp.toString())
                                    }}
                                    variant="ghost"
                                    size="sm"
                                    disabled={actionLoading}
                                    className="h-8 w-8 p-0 hover:bg-muted"
                                    title="Modify Order"
                                  >
                                    <Edit3 className="h-3.5 w-3.5 text-muted-foreground" />
                                  </Button>
                                  <Button
                                    onClick={() => setMarketTicket(order.ticket)}
                                    variant="ghost"
                                    size="sm"
                                    disabled={actionLoading}
                                    className="h-8 w-8 p-0 hover:bg-muted"
                                    title="Execute at market (same risk)"
                                  >
                                    <Zap className="h-3.5 w-3.5 text-primary" />
                                  </Button>
                                  <Button 
                                    onClick={() => cancelOrder(order)}
                                    variant="ghost"
                                    size="sm"
                                    disabled={actionLoading}
                                    className="h-8 w-8 p-0 hover:bg-red-50"
                                    title="Cancel Order"
                                  >
                                    <X className="h-3.5 w-3.5 text-destructive" />
                                  </Button>
                                </div>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    </>
                  )}
                </CardContent>
              </Card>

            </TabsContent>

         <TabsContent value="risk" className="p-0 outline-none">
          {/* Mobile Master Control */}
          <div className="xl:hidden mb-4">
            <Card className="border-2 border-emerald-100 bg-success/10/30 shadow-sm">
              <div className="p-4 flex items-center justify-between gap-4">
                <div className="flex items-center gap-3">
                  <div className={`p-2 rounded-full ${protectionConfig?.enabled ? 'bg-success/10 text-success border border-success/20' : 'bg-muted text-muted-foreground/70'}`}>
                    <Zap className="h-5 w-5" />
                  </div>
                  <div>
                    <p className="text-xs font-bold text-foreground">Master Guard</p>
                    <p className="text-[10px] text-muted-foreground font-medium">Auto-liquidate enabled</p>
                  </div>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={resetProtectionBlock}
                    disabled={actionLoading || !protection?.trading_blocked}
                    className="px-3 py-2 rounded-xl text-xs font-black bg-card border border-rose-200 text-destructive hover:bg-destructive/10 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    RESET
                  </button>
                  <button
                    onClick={toggleProtection}
                    disabled={actionLoading}
                    className={`px-4 py-2 rounded-xl text-xs font-black transition-all ${
                      protectionConfig?.enabled 
                      ? 'bg-emerald-600 text-white hover:bg-emerald-700' 
                      : 'bg-card border border-border text-muted-foreground hover:bg-muted/50'
                    }`}
                  >
                    {actionLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : protectionConfig?.enabled ? 'PAUSE' : 'START'}
                  </button>
                </div>
              </div>
            </Card>
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-[1.2fr_1fr_1fr] gap-4">
            
            {/* Left Column: Risk Controls */}
            <div className="space-y-4">
              <Card className="border border-border bg-card shadow-sm overflow-hidden">
                <div className="flex items-center justify-between px-5 py-3.5 border-b border-border/50 bg-card">
                  <div className="flex items-center gap-2">
                    <Shield className="h-4 w-4 text-primary" />
                    <h3 className="text-sm font-bold text-foreground">Risk Parameters</h3>
                  </div>
                  {JSON.stringify(protectionConfig) !== JSON.stringify(originalProtectionConfig) && (
                    <Badge variant="outline" className="text-[10px] font-bold text-primary border-blue-100 bg-primary/10 animate-pulse">Unsaved Changes</Badge>
                  )}
                </div>

                {protectionConfig && (
                  <div className="pb-4">
                    <RiskSlider
                      label="Daily Loss Limit"
                      value={protectionConfig.max_daily_loss_pct}
                      min={0}
                      max={50}
                      unit="%"
                      info="Maximum daily loss percentage relative to starting balance"
                      onChange={(val) => setProtectionConfig({ ...protectionConfig, max_daily_loss_pct: val })}
                      currentUsage={protectionConfig.max_daily_loss_pct > 0 
                        ? `Used ${((protection?.daily_drawdown_pct || 0) / (protectionConfig.max_daily_loss_pct || 1) * 100).toFixed(2)}%`
                        : "Disabled"}
                    />
                    <RiskSlider
                      label="Drawdown Limit"
                      value={protectionConfig.max_total_drawdown_pct}
                      min={0}
                      max={50}
                      unit="%"
                      info="Maximum total drawdown percentage relative to peak equity/balance"
                      onChange={(val) => setProtectionConfig({ ...protectionConfig, max_total_drawdown_pct: val })}
                      currentUsage={protectionConfig.max_total_drawdown_pct > 0
                        ? `Used ${((protection?.total_drawdown_pct || 0) / (protectionConfig.max_total_drawdown_pct || 1) * 100).toFixed(2)}%`
                        : "Disabled"}
                    />
                    <RiskSlider
                      label="Minimum Margin Level"
                      value={protectionConfig.min_margin_level_pct}
                      min={0}
                      max={100}
                      unit="%"
                      info="Minimum margin level allowed before automatic closure (prop firms usually set their own limit)"
                      onChange={(val) => setProtectionConfig({ ...protectionConfig, min_margin_level_pct: val })}
                      currentUsage={`Current ${protection?.margin_level?.toFixed(0) || 0}%`}
                    />
                    
                    {/* Protection Mode & Action */}
                    <div className="px-5 pb-4 space-y-4">
                      <div className="grid grid-cols-2 gap-4">
                        <div className="space-y-2">
                          <div className="flex items-center gap-2">
                            <label className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Protection Mode</label>
                            <Info className="w-3 h-3 text-muted-foreground/50" />
                          </div>
                          <select 
                            value={protectionConfig.protection_mode} 
                            onChange={e => setProtectionConfig({ ...protectionConfig, protection_mode: e.target.value as 'equity' | 'balance' })}
                            className="w-full rounded-xl h-10 text-xs font-bold border border-border px-3 bg-card focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all"
                          >
                            <option value="equity">Equity Base</option>
                            <option value="balance">Balance Base</option>
                          </select>
                        </div>
                        <div className="space-y-2">
                          <div className="flex items-center gap-2">
                            <label className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Breach Action</label>
                            <Info className="w-3 h-3 text-muted-foreground/50" />
                          </div>
                          <select 
                            value={protectionConfig.action} 
                            onChange={e => setProtectionConfig({ ...protectionConfig, action: e.target.value as any })}
                            className="w-full rounded-xl h-10 text-xs font-bold border border-border px-3 bg-card focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all"
                          >
                            <option value="close_all">Close All</option>
                            <option value="close_profitable">Close Profitable</option>
                            <option value="close_losing">Close Losers</option>
                            <option value="notify_only">Notify Only</option>
                          </select>
                        </div>
                      </div>
                    </div>

                    <form onSubmit={handleUpdateProtectionConfig} className="px-5 mt-2">
                      <Button 
                        type="submit" 
                        disabled={actionLoading || JSON.stringify(protectionConfig) === JSON.stringify(originalProtectionConfig)}
                        className={`w-full font-bold rounded-xl py-5 shadow-sm transition-all ${
                          JSON.stringify(protectionConfig) === JSON.stringify(originalProtectionConfig)
                          ? 'bg-muted/50 text-muted-foreground/70 border border-border'
                          : 'bg-blue-600 text-white hover:bg-blue-700 shadow-blue-200'
                        }`}
                      >
                        {actionLoading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <Settings2 className="h-4 w-4 mr-2" />}
                        Apply Parameters
                      </Button>
                    </form>
                  </div>
                )}
              </Card>
            </div>

            {/* Middle Column: Risk Dashboard */}
            <div className="space-y-4">
              <Card className="border border-border bg-card shadow-sm overflow-hidden">
                <div className="p-5 border-b border-border/50 flex items-center justify-between bg-muted/40">
                  <h3 className="text-sm font-bold text-foreground">Live Health</h3>
                  <Badge className={protectionConfig?.enabled ? 'bg-emerald-500 text-white' : 'bg-muted text-white'}>
                    {protectionConfig?.enabled ? 'GUARD ACTIVE' : 'GUARD PAUSED'}
                  </Badge>
                </div>
                <div className="p-5">
                  <div className="flex justify-center mb-6">
                    <RiskGauge
                      value={protection?.trading_blocked ? 100 : Math.round(Math.max((protection?.daily_drawdown_pct || 0) / (protectionConfig?.max_daily_loss_pct || 1), (protection?.total_drawdown_pct || 0) / (protectionConfig?.max_total_drawdown_pct || 1)) * 100)}
                      max={100}
                      status={protection?.trading_blocked ? 'Critical' : (protection?.total_drawdown_pct || 0) / (protectionConfig?.max_total_drawdown_pct || 1) > 0.8 ? 'High Risk' : 'Low Risk'}
                    />
                  </div>

                  <div className="space-y-4">
                    <div className="bg-muted/50 rounded-2xl p-4 border border-border/50">
                      <div className="grid grid-cols-2 gap-4">
                        <div className="space-y-1.5">
                          <p className="text-[10px] font-bold text-muted-foreground/70 uppercase tracking-widest">Daily Loss</p>
                          <p className="text-sm font-black text-foreground">
                            {protection?.daily_drawdown_pct?.toFixed(2) || 0}% 
                            <span className="text-muted-foreground/70 font-normal text-[10px] ml-1">/ {protectionConfig?.max_daily_loss_pct || 0}%</span>
                          </p>
                          <div className="flex items-center gap-1.5">
                            <div className="flex-1 h-1 bg-muted rounded-full overflow-hidden">
                              <div 
                                className="h-full bg-blue-500 transition-all" 
                                style={{ width: `${Math.min(100, (protection?.daily_drawdown_pct || 0) / (protectionConfig?.max_daily_loss_pct || 1) * 100)}%` }}
                              />
                            </div>
                            <span className="text-[10px] font-bold text-primary">
                              {protectionConfig?.max_daily_loss_pct ? `${((protection?.daily_drawdown_pct || 0) / (protectionConfig?.max_daily_loss_pct || 1) * 100).toFixed(1)}%` : '0%'}
                            </span>
                          </div>
                        </div>
                        <div className="space-y-1.5">
                          <p className="text-[10px] font-bold text-muted-foreground/70 uppercase tracking-widest">Drawdown</p>
                          <p className="text-sm font-black text-foreground">
                            {protection?.total_drawdown_pct?.toFixed(2) || 0}% 
                            <span className="text-muted-foreground/70 font-normal text-[10px] ml-1">/ {protectionConfig?.max_total_drawdown_pct || 0}%</span>
                          </p>
                          <div className="flex items-center gap-1.5">
                            <div className="flex-1 h-1 bg-muted rounded-full overflow-hidden">
                              <div 
                                className="h-full bg-blue-500 transition-all" 
                                style={{ width: `${Math.min(100, (protection?.total_drawdown_pct || 0) / (protectionConfig?.max_total_drawdown_pct || 1) * 100)}%` }}
                              />
                            </div>
                            <span className="text-[10px] font-bold text-primary">
                              {protectionConfig?.max_total_drawdown_pct ? `${((protection?.total_drawdown_pct || 0) / (protectionConfig?.max_total_drawdown_pct || 1) * 100).toFixed(1)}%` : '0%'}
                            </span>
                          </div>
                        </div>
                      </div>
                      <div className="grid grid-cols-2 gap-4 mt-4 pt-4 border-t border-border/50">
                        <div className="space-y-1">
                          <p className="text-[10px] font-bold text-muted-foreground/70 uppercase tracking-widest">Current Equity</p>
                          <p className="text-sm font-black text-foreground">{formatCurrency(protection?.equity || 0)}</p>
                        </div>
                        <div className="space-y-1">
                          <p className="text-[10px] font-bold text-muted-foreground/70 uppercase tracking-widest">Starting Balance</p>
                          <p className="text-sm font-black text-foreground">{formatCurrency(protection?.daily_starting_value || 0)}</p>
                        </div>
                      </div>

                      <div className="grid grid-cols-3 gap-2 mt-4 pt-4 border-t border-border/50 bg-muted/40 -mx-4 px-4 pb-2">
                        <div className="space-y-1">
                          <p className="text-[9px] font-bold text-muted-foreground/70 uppercase tracking-tight">Acc Number</p>
                          <p className="text-[11px] font-bold text-foreground/80">{protection?.account_number || '---'}</p>
                        </div>
                        <div className="space-y-1">
                          <p className="text-[9px] font-bold text-muted-foreground/70 uppercase tracking-tight">Margin Level</p>
                          <p className="text-[11px] font-bold text-foreground/80">{protection?.margin_level?.toFixed(1) || '0'}%</p>
                        </div>
                        <div className="space-y-1">
                          <p className="text-[9px] font-bold text-muted-foreground/70 uppercase tracking-tight">Base Mode</p>
                          <p className="text-[11px] font-bold text-foreground/80 capitalize">{protection?.protection_mode || '---'}</p>
                        </div>
                      </div>

                      <div className="grid grid-cols-2 gap-4 mt-2">
                        <div className="space-y-1">
                          <p className="text-[9px] font-bold text-muted-foreground/70 uppercase tracking-tight">Historical Peak</p>
                          <p className="text-[11px] font-bold text-foreground/80">
                            {formatCurrency(protection?.historical_peak || 0)}
                          </p>
                        </div>
                        <div className="space-y-1">
                          <p className="text-[9px] font-bold text-muted-foreground/70 uppercase tracking-tight">Equity Peak</p>
                          <p className="text-[11px] font-bold text-foreground/80">
                            {formatCurrency(protection?.peak_equity || 0)}
                          </p>
                        </div>
                      </div>

                      <div className="mt-2 pt-2 border-t border-border/50/50">
                        <div className="space-y-1">
                          <p className="text-[9px] font-bold text-muted-foreground/70 uppercase tracking-tight">Floating P/L</p>
                          <p className={`text-[11px] font-bold ${((protection?.equity || 0) - (protection?.balance || 0)) >= 0 ? 'text-success' : 'text-destructive'}`}>
                            {((protection?.equity || 0) - (protection?.balance || 0)) >= 0 ? '+' : ''}{formatCurrency((protection?.equity || 0) - (protection?.balance || 0))}
                          </p>
                        </div>
                      </div>
                    </div>

                    <div className={`p-4 rounded-2xl border transition-all ${protection?.trading_blocked ? 'bg-destructive/10 border-rose-100' : 'bg-success/10 border-emerald-100'}`}>
                      <div className="flex items-start gap-3">
                        <div className={`mt-0.5 p-1.5 rounded-lg ${protection?.trading_blocked ? 'bg-rose-200 text-destructive' : 'bg-emerald-200 text-success'}`}>
                          {protection?.trading_blocked ? <AlertTriangle className="h-4 w-4" /> : <ShieldCheck className="h-4 w-4" />}
                        </div>
                        <div>
                          <div className={`text-sm font-bold ${protection?.trading_blocked ? 'text-destructive' : 'text-success'}`}>
                            {protection?.trading_blocked ? 'Trading Blocked' : 'System Healthy'}
                          </div>
                          <div className={`text-xs ${protection?.trading_blocked ? 'text-destructive' : 'text-success'} opacity-80 mt-0.5 leading-relaxed`}>
                            {protection?.trading_blocked ? protection?.block_reason || 'Risk limit breached' : 'All systems operating within safe parameters'}
                          </div>
                        </div>
                      </div>
                      {protection?.trading_blocked && (
                        <Button 
                          onClick={resetProtectionBlock} 
                          disabled={actionLoading}
                          variant="outline" 
                          className="w-full mt-4 bg-card border-rose-200 text-destructive hover:bg-rose-500 hover:text-white font-bold h-9 rounded-xl transition-all"
                        >
                          Reset Block
                        </Button>
                      )}
                    </div>
                  </div>
                </div>
              </Card>
            </div>

            {/* Right Column: Actions & Technical */}
            <div className="space-y-4">
              {/* Master Control - Desktop Only */}
              <div className="hidden xl:block">
                <Card className="border-2 border-emerald-100 bg-success/10/30 shadow-sm">
                  <div className="p-4 flex items-center justify-between gap-4">
                    <div className="flex items-center gap-3">
                      <div className={`p-2 rounded-full ${protectionConfig?.enabled ? 'bg-success/10 text-success border border-success/20' : 'bg-muted text-muted-foreground/70'}`}>
                        <Zap className="h-5 w-5" />
                      </div>
                      <div>
                        <p className="text-xs font-bold text-foreground">Master Guard</p>
                        <p className="text-[10px] text-muted-foreground font-medium">Auto-liquidate enabled</p>
                      </div>
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={resetProtectionBlock}
                        disabled={actionLoading || !protection?.trading_blocked}
                        className="px-3 py-2 rounded-xl text-xs font-black bg-card border border-rose-200 text-destructive hover:bg-destructive/10 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        RESET
                      </button>
                      <button
                        onClick={toggleProtection}
                        disabled={actionLoading}
                        className={`px-4 py-2 rounded-xl text-xs font-black transition-all ${
                          protectionConfig?.enabled 
                          ? 'bg-emerald-600 text-white hover:bg-emerald-700' 
                          : 'bg-card border border-border text-muted-foreground hover:bg-muted/50'
                        }`}
                      >
                        {actionLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : protectionConfig?.enabled ? 'PAUSE' : 'START'}
                      </button>
                    </div>
                  </div>
                </Card>
              </div>

              {/* Technical Limits */}
              <Card className="border border-border bg-card shadow-sm overflow-hidden">
                <div className="p-5 border-b border-border/50 bg-muted/50/30">
                  <h3 className="text-sm font-bold text-foreground">Advanced Config</h3>
                </div>
                <div className="p-5 space-y-6">
                  {protectionConfig && (
                    <>
                      <div className="space-y-4">
                        <h4 className="text-[10px] font-black text-muted-foreground/70 uppercase tracking-[0.2em]">Absolute Limits</h4>
                        <div className="grid grid-cols-2 gap-3">
                          <div className="space-y-1.5">
                            <label className="text-[10px] font-bold text-muted-foreground">Daily (Abs)</label>
                            <Input type="number" step="1" value={protectionConfig.max_daily_loss_abs} onChange={e => setProtectionConfig({ ...protectionConfig, max_daily_loss_abs: parseFloat(e.target.value) || 0 })} className="h-9 text-xs font-bold rounded-xl border-border focus:ring-blue-500" />
                          </div>
                          <div className="space-y-1.5">
                            <label className="text-[10px] font-bold text-muted-foreground">Drawdown (Abs)</label>
                            <Input type="number" step="1" value={protectionConfig.max_total_drawdown_abs} onChange={e => setProtectionConfig({ ...protectionConfig, max_total_drawdown_abs: parseFloat(e.target.value) || 0 })} className="h-9 text-xs font-bold rounded-xl border-border focus:ring-blue-500" />
                          </div>
                        </div>
                      </div>

                      <div className="space-y-4 pt-2">
                        <h4 className="text-[10px] font-black text-muted-foreground/70 uppercase tracking-[0.2em]">Intervals (Sec)</h4>
                        <div className="grid grid-cols-3 gap-2">
                          <div className="space-y-1">
                            <label className="text-[10px] font-bold text-muted-foreground">Heart</label>
                            <Input type="number" step="0.1" value={protectionConfig.heartbeat_interval} onChange={e => setProtectionConfig({ ...protectionConfig, heartbeat_interval: parseFloat(e.target.value) || 0.1 })} className="h-9 text-xs font-bold rounded-xl" />
                          </div>
                          <div className="space-y-1">
                            <label className="text-[10px] font-bold text-muted-foreground">Check</label>
                            <Input type="number" step="1" value={protectionConfig.order_check_interval} onChange={e => setProtectionConfig({ ...protectionConfig, order_check_interval: parseInt(e.target.value) || 1 })} className="h-9 text-xs font-bold rounded-xl" />
                          </div>
                          <div className="space-y-1">
                            <label className="text-[10px] font-bold text-muted-foreground">WS</label>
                            <Input type="number" step="1" value={protectionConfig.ws_update_interval} onChange={e => setProtectionConfig({ ...protectionConfig, ws_update_interval: parseInt(e.target.value) || 1 })} className="h-9 text-xs font-bold rounded-xl" />
                          </div>
                        </div>
                      </div>

                      <div className="space-y-3 pt-2">
                         <div className="flex items-center justify-between p-3 bg-muted/50 rounded-xl border border-border/50">
                          <label className="text-[11px] font-bold text-foreground/80">Auto Reset Daily</label>
                          <input type="checkbox" checked={protectionConfig.auto_reset_daily} onChange={e => setProtectionConfig({ ...protectionConfig, auto_reset_daily: e.target.checked })} className="h-4 w-4 rounded border-border text-primary focus:ring-blue-500" />
                        </div>
                        <div className="space-y-1 p-3 bg-muted/50 rounded-xl border border-border/50">
                          <div className="flex items-center justify-between">
                            <label className="text-[11px] font-bold text-foreground/80">Daily Reset Offset (hours)</label>
                            <Input type="number" step="0.5" min={-14} max={14} value={protectionConfig.day_offset_hours ?? 0} onChange={e => setProtectionConfig({ ...protectionConfig, day_offset_hours: parseFloat(e.target.value) || 0 })} className="h-8 w-20 text-xs font-bold rounded-xl" />
                          </div>
                          <p className="text-[10px] text-muted-foreground">Shifts when the daily drawdown resets, to match your broker/prop-firm day (e.g. 3 if their midnight is 03:00 on the bot&apos;s clock). Applied immediately.</p>
                        </div>
                        <div className="flex items-center justify-between p-3 bg-muted/50 rounded-xl border border-border/50">
                          <label className="text-[11px] font-bold text-foreground/80">Verbose Logging</label>
                          <input type="checkbox" checked={protectionConfig.verbose_logging} onChange={e => setProtectionConfig({ ...protectionConfig, verbose_logging: e.target.checked })} className="h-4 w-4 rounded border-border text-primary focus:ring-blue-500" />
                        </div>
                      </div>
                    </>
                  )}
                </div>
              </Card>
            </div>
          </div>
        </TabsContent>

        <TabsContent value="history" className="p-0 outline-none space-y-4">
          <Card className="tech-card border-border">
            <CardHeader className="pb-3 pt-4 px-5 border-b border-border/50">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm font-semibold text-foreground">Trade History</CardTitle>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setHistoryDateRange(undefined)
                    setHistoryTimeFilter('all')
                    setHistoryDayFilter('all')
                  }}
                  className="text-xs text-muted-foreground hover:text-foreground"
                >
                  Reset Filters
                </Button>
              </div>
              {/* Filter Controls */}
              <div className="flex flex-wrap gap-3 mt-3">
                <Popover>
                  <PopoverTrigger asChild>
                    <Button variant="outline" size="sm" className="h-8 text-xs">
                      <CalendarIcon className="h-3.5 w-3.5 mr-2" />
                      {historyDateRange?.from ? format(historyDateRange.from, 'MMM d') : 'Date Range'}
                      {historyDateRange?.to && ` - ${format(historyDateRange.to, 'MMM d')}`}
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent className="w-auto p-0" align="start">
                    <Calendar
                      mode="range"
                      selected={historyDateRange}
                      onSelect={setHistoryDateRange}
                      initialFocus
                    />
                  </PopoverContent>
                </Popover>
                <Select value={historyTimeFilter} onValueChange={setHistoryTimeFilter}>
                  <SelectTrigger className="h-8 w-[140px] text-xs">
                    <SelectValue placeholder="Time" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All Times</SelectItem>
                    <SelectItem value="morning">Morning (6-12)</SelectItem>
                    <SelectItem value="afternoon">Afternoon (12-18)</SelectItem>
                    <SelectItem value="evening">Evening (18-22)</SelectItem>
                    <SelectItem value="night">Night (22-6)</SelectItem>
                  </SelectContent>
                </Select>
                <Select value={historyDayFilter} onValueChange={setHistoryDayFilter}>
                  <SelectTrigger className="h-8 w-[140px] text-xs">
                    <SelectValue placeholder="Day" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All Days</SelectItem>
                    <SelectItem value="0">Sunday</SelectItem>
                    <SelectItem value="1">Monday</SelectItem>
                    <SelectItem value="2">Tuesday</SelectItem>
                    <SelectItem value="3">Wednesday</SelectItem>
                    <SelectItem value="4">Thursday</SelectItem>
                    <SelectItem value="5">Friday</SelectItem>
                    <SelectItem value="6">Saturday</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </CardHeader>
            <CardContent className="p-0">
              <>
              {(() => {
                const filteredHistory = getFilteredHistory()
                const stats = getHistoryStats(filteredHistory)
                return (
                  <>
                  <div className="overflow-x-auto hidden md:block">
                    <table className="w-full text-left">
                      <thead className="bg-muted/40">
                        <tr>
                          <th className="px-5 py-3 text-xs font-semibold text-muted-foreground uppercase tracking-wider">Trade</th>
                          <th className="px-5 py-3 text-xs font-semibold text-muted-foreground uppercase tracking-wider text-center">Type</th>
                          <th className="px-5 py-3 text-xs font-semibold text-muted-foreground uppercase tracking-wider">Volume</th>
                          <th className="px-5 py-3 text-xs font-semibold text-muted-foreground uppercase tracking-wider">Exit Time</th>
                          <th className="px-5 py-3 text-xs font-semibold text-muted-foreground uppercase tracking-wider">Profit</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-50">
                        {filteredHistory.length === 0 ? (
                          <tr><td colSpan={5} className="px-5 py-12 text-center text-muted-foreground/70"><History className="h-8 w-8 mx-auto mb-3 opacity-50" /><p className="text-sm font-semibold">No Trade History</p></td></tr>
                        ) : (
                          filteredHistory.slice(0, 20).map(trade => (
                            <tr key={trade.ticket} className="hover:bg-muted/50 transition-colors">
                              <td className="px-5 py-4">
                                <div className="flex items-center gap-3">
                                  <AccountInstrumentIcon symbol={trade.symbol} size="sm" />
                                  <span className="font-semibold text-sm text-foreground">{trade.symbol}</span>
                                </div>
                              </td>
                              <td className="px-5 py-4 text-center">
                                <Badge variant={trade.type === 0 ? 'default' : 'destructive'} className="text-xs font-semibold">
                                  {trade.type === 0 ? 'BUY' : 'SELL'}
                                </Badge>
                              </td>
                              <td className="px-5 py-4 font-semibold text-sm text-foreground/80">{trade.volume.toFixed(2)}</td>
                              <td className="px-5 py-4 text-sm text-muted-foreground font-mono">{new Date(typeof trade.time_close === 'number' ? trade.time_close * 1000 : trade.time_close).toLocaleString()}</td>
                              <td className="px-5 py-4 font-semibold text-sm">
                                <span className={trade.profit >= 0 ? 'text-success' : 'text-destructive'}>
                                  {trade.profit >= 0 ? '+' : ''}{formatCurrency(trade.profit)}
                                </span>
                              </td>
                            </tr>
                          ))
                        )}
                      </tbody>
                      {filteredHistory.length > 0 && (
                        <tfoot className="bg-muted/50 border-t-2 border-border">
                          <tr>
                            <td colSpan={4} className="px-5 py-3 text-xs font-semibold text-foreground/80">
                              Statistics ({stats.total} trades)
                            </td>
                            <td className="px-5 py-3">
                              <div className="flex gap-3 text-xs">
                                <span className="font-semibold text-success">Wins: {stats.wins}</span>
                                <span className="font-semibold text-destructive">Losses: {stats.losses}</span>
                                <span className="font-semibold text-foreground/80">Win Rate: {stats.winRate.toFixed(1)}%</span>
                                <span className={`font-semibold ${stats.totalProfit >= 0 ? 'text-success' : 'text-destructive'}`}>
                                  Total: {formatCurrency(stats.totalProfit)}
                                </span>
                              </div>
                            </td>
                          </tr>
                        </tfoot>
                      )}
                    </table>
                  </div>
                  {/* Mobile View */}
                  <div className="md:hidden flex flex-col gap-2 p-3 bg-muted/40">
                    {filteredHistory.length === 0 ? (
                      <div className="py-8 text-center text-muted-foreground/70">
                        <History className="h-8 w-8 mx-auto mb-3 opacity-50" />
                        <p className="text-sm font-semibold">No Trade History</p>
                      </div>
                    ) : (
                      <>
                      {filteredHistory.slice(0, 20).map(trade => (
                        <div key={trade.ticket} className="tech-card rounded-xl overflow-hidden">
                          <div className="p-3">
                            <div className="flex items-center justify-between">
                              <div className="flex items-center gap-2">
                                <div className={`flex items-center justify-center w-7 h-7 rounded-md ${
                                  trade.type === 0 ? 'bg-success/10' : 'bg-destructive/10'
                                }`}>
                                  {trade.type === 0 ? <TrendingUp className="h-4 w-4 text-success" /> : <TrendingDown className="h-4 w-4 text-destructive" />}
                                </div>
                                <div className="min-w-0 flex-1">
                                  <div className="flex items-center gap-1.5 flex-wrap">
                                    <span className="font-bold text-sm text-foreground tracking-tight">{trade.symbol}</span>
                                    <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-4 font-semibold border-border text-foreground/80">
                                      {trade.type === 0 ? 'BUY' : 'SELL'} · {trade.volume.toFixed(2)}
                                    </Badge>
                                  </div>
                                  <span className="text-[10px] text-muted-foreground font-mono">{new Date(typeof trade.time_close === 'number' ? trade.time_close * 1000 : trade.time_close).toLocaleString()}</span>
                                </div>
                              </div>
                              <div className="flex flex-col items-end">
                                <span className={`text-sm font-bold ${trade.profit >= 0 ? 'text-success' : 'text-destructive'}`}>
                                  {trade.profit >= 0 ? '+' : ''}{formatCurrency(trade.profit)}
                                </span>
                              </div>
                            </div>
                          </div>
                        </div>
                      ))}
                      {/* Mobile Statistics */}
                      <div className="mt-3 p-3 bg-muted rounded-xl border border-border">
                        <div className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider mb-2">Statistics ({stats.total} trades)</div>
                        <div className="flex flex-wrap gap-3 text-xs">
                          <span className="font-semibold text-success">Wins: {stats.wins}</span>
                          <span className="font-semibold text-destructive">Losses: {stats.losses}</span>
                          <span className="font-semibold text-foreground/80">Win Rate: {stats.winRate.toFixed(1)}%</span>
                          <span className={`font-semibold ${stats.totalProfit >= 0 ? 'text-success' : 'text-destructive'}`}>
                            Total: {formatCurrency(stats.totalProfit)}
                          </span>
                        </div>
                      </div>
                      </>
                    )}
                  </div>
                  </>
                )
              })()}
              </>
            </CardContent>
          </Card>
        </TabsContent>
          </Tabs>
        </div>
        </div>
      </div>

      {/* Symbol Chart Dialog */}
      <Dialog open={!!chartSymbol} onOpenChange={open => { if (!open) { setChartSymbol(null); setChartFullscreen(false) } }}>
        <DialogContent
          hideCloseButton
          onPointerDownOutside={(e) => e.preventDefault()}
          onInteractOutside={(e) => e.preventDefault()}
          // grid-cols-1 = minmax(0,1fr): the default auto column grew to the panel's
          // content width on phones, so the right side was clipped off-screen.
          className="p-0 overflow-hidden grid-cols-1"
          style={chartFullscreen
            ? { left: 0, top: 0, transform: 'none', width: '100vw', maxWidth: '100vw', height: '100dvh', borderRadius: 0, border: 'none' }
            : { width: 'calc(100vw - 1rem)', maxWidth: '56rem', height: '88dvh' }
          }
        >
          <DialogTitle className="sr-only">{chartSymbol} Chart</DialogTitle>
          {chartSymbol && (
            <AccountChartPanel
              symbol={chartSymbol}
              positions={positions.filter(p => p.symbol === chartSymbol)}
              history={history.filter(h => h.symbol === chartSymbol)}
              onClose={() => { setChartSymbol(null); setChartFullscreen(false) }}
              refreshInterval={refreshInterval}
              isFullscreen={chartFullscreen}
              onFullscreenChange={setChartFullscreen}
            />
          )}
        </DialogContent>
      </Dialog>

      {/* Settings Dialog */}
      <Dialog open={settingsModal} onOpenChange={setSettingsModal}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="text-xl font-bold text-foreground flex items-center gap-2">
              <Settings className="h-5 w-5" />
              Trading Settings
            </DialogTitle>
            <DialogDescription>
              Configure your smart close preferences
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-6 py-4">
            {/* Smart Close Enabled */}
            <div className="flex items-center justify-between">
              <div>
                <Label className="text-sm font-semibold text-foreground">Enable Smart Close</Label>
                <p className="text-xs text-muted-foreground mt-1">Quick partial close with breakeven</p>
              </div>
              <input
                type="checkbox"
                checked={userSettings.smartCloseEnabled}
                onChange={(e) => setUserSettings({ ...userSettings, smartCloseEnabled: e.target.checked })}
                className="h-5 w-5 rounded border-border text-primary focus:ring-blue-500"
              />
            </div>

            {/* Close Percentage */}
            <div className="space-y-2">
              <Label className="text-sm font-semibold text-foreground">Close Percentage</Label>
              <div className="flex items-center gap-3">
                <input
                  type="range"
                  min="10"
                  max="90"
                  step="5"
                  value={userSettings.smartClosePercentage}
                  onChange={(e) => setUserSettings({ ...userSettings, smartClosePercentage: parseFloat(e.target.value) })}
                  className="flex-1 h-2 bg-border rounded-lg appearance-none cursor-pointer"
                  disabled={!userSettings.smartCloseEnabled}
                />
                <span className="text-lg font-bold text-foreground w-16 text-right">
                  {userSettings.smartClosePercentage}%
                </span>
              </div>
              <p className="text-xs text-muted-foreground">Percentage of position to close</p>
            </div>

            {/* Set Breakeven After Close */}
            <div className="flex items-center justify-between">
              <div>
                <Label className="text-sm font-semibold text-foreground">Set Breakeven After Close</Label>
                <p className="text-xs text-muted-foreground mt-1">Automatically move SL to entry after partial close</p>
              </div>
              <input
                type="checkbox"
                checked={userSettings.smartCloseSetBreakeven}
                onChange={(e) => setUserSettings({ ...userSettings, smartCloseSetBreakeven: e.target.checked })}
                disabled={!userSettings.smartCloseEnabled}
                className="h-5 w-5 rounded border-border text-primary focus:ring-blue-500"
              />
            </div>

            {/* Preview */}
            <div className="bg-gold/10 border border-amber-200 rounded-lg p-4">
              <div className="flex items-start gap-2">
                <Zap className="h-5 w-5 text-gold mt-0.5" />
                <div>
                  <p className="text-sm font-semibold text-gold">Smart Close Preview</p>
                  <p className="text-xs text-gold mt-1">
                    {userSettings.smartCloseEnabled ? (
                      <>
                        Will close <strong>{userSettings.smartClosePercentage}%</strong> of position
                        {userSettings.smartCloseSetBreakeven && <> and set remaining position to breakeven</>}
                      </>
                    ) : (
                      'Smart Close is disabled'
                    )}
                  </p>
                </div>
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setSettingsModal(false)}>Cancel</Button>
            <Button onClick={() => { saveUserSettings(userSettings); setSettingsModal(false); }}>Save Settings</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Mobile Refresh Interval Dialog */}
      <Dialog open={mobileRefreshModal} onOpenChange={setMobileRefreshModal}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle className="text-xl font-bold text-foreground flex items-center gap-2">
              <Clock className="h-5 w-5 text-primary" />
              Refresh Interval
            </DialogTitle>
          </DialogHeader>
            <div className="space-y-4 py-4">
            <div className="space-y-2">
              <label className="text-sm font-medium text-foreground/80">Auto-refresh interval</label>
              <div className="flex gap-2">
                {[
                  { value: 0, label: 'Off' },
                  { value: 1, label: '1s' },
                  { value: 5, label: '5s' },
                  { value: 10, label: '10s' },
                  { value: 30, label: '30s' },
                  { value: 60, label: '60s' },
                ].map((opt) => (
                  <button
                    key={opt.value}
                    onClick={() => handleRefreshIntervalChange(opt.value)}
                    className={`flex-1 py-2 px-3 rounded-md text-xs font-semibold transition-colors ${
                      refreshInterval === opt.value
                        ? 'bg-blue-600 text-white'
                        : 'bg-muted text-foreground/80 hover:bg-border'
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">Choose how often to refresh account data</p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setMobileRefreshModal(false)}>Close</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={modifyModal.open} onOpenChange={o => setModifyModal({ open: o, position: null })}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="text-xl font-bold flex items-center gap-2">
              <Edit3 className="h-5 w-5 text-primary" /> Modify SL / TP
            </DialogTitle>
          </DialogHeader>
          {modifyModal.position && (() => {
            const pos = modifyModal.position!
            // Determine pip multiplier based on symbol
            let pipMult = 10000 // Default for standard forex (1 pip = 0.0001)
            if (pos.symbol.includes('JPY')) {
              pipMult = 100 // JPY pairs (1 pip = 0.01)
            } else if (pos.symbol.includes('XAU') || pos.symbol.includes('GOLD')) {
              pipMult = 10 // Gold (1 pip = 0.1)
            } else if (pos.symbol.includes('XAG') || pos.symbol.includes('SILVER') || pos.symbol.includes('XPD') || pos.symbol.includes('XPT')) {
              pipMult = 100 // Silver / Platinum / Palladium (1 pip = 0.01, digits=3)
            } else if (pos.symbol.includes('BTC') || pos.symbol.includes('ETH')) {
              pipMult = 10 // Crypto (1 pip = 0.1)
            }
            const slPips = modifySL && parseFloat(modifySL) > 0
              ? Math.abs((pos.price_current - parseFloat(modifySL)) * pipMult).toFixed(1)
              : null
            const tpPips = modifyTP && parseFloat(modifyTP) > 0
              ? Math.abs((parseFloat(modifyTP) - pos.price_current) * pipMult).toFixed(1)
              : null
            const rr = slPips && tpPips && parseFloat(slPips) > 0
              ? (parseFloat(tpPips) / parseFloat(slPips)).toFixed(2)
              : null
            return (
              <div className="space-y-5 py-2">
                {/* Position Context */}
                <div className="grid grid-cols-3 gap-2 bg-muted/50 rounded-xl p-3 border border-border/50">
                  <div className="text-center">
                    <p className="text-[10px] font-bold text-muted-foreground/70 uppercase tracking-widest">Symbol</p>
                    <p className="text-sm font-bold text-foreground">{pos.symbol}</p>
                  </div>
                  <div className="text-center border-x border-border">
                    <p className="text-[10px] font-bold text-muted-foreground/70 uppercase tracking-widest">Entry</p>
                    <p className="text-sm font-mono font-bold text-foreground/80">{pos.price_open.toFixed(5)}</p>
                  </div>
                  <div className="text-center">
                    <p className="text-[10px] font-bold text-muted-foreground/70 uppercase tracking-widest">Current</p>
                    <p className={`text-sm font-mono font-bold ${pos.profit >= 0 ? 'text-success' : 'text-destructive'}`}>{pos.price_current.toFixed(5)}</p>
                  </div>
                </div>
                {/* SL Input */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <Label className="text-sm font-semibold text-foreground/80 flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full bg-rose-500 inline-block" /> Stop Loss
                    </Label>
                    {slPips && <span className="text-xs font-bold text-destructive bg-destructive/10 px-2 py-0.5 rounded-full">{slPips} pips risk</span>}
                  </div>
                  <div className="relative">
                    <Input type="number" step="0.00001" value={modifySL} onChange={e => setModifySL(e.target.value)}
                      className="h-12 text-base font-mono rounded-lg border-rose-200 focus:border-rose-400 pr-20" />
                    <button onClick={() => setModifySL(pos.price_open.toFixed(5))}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-[10px] font-bold text-muted-foreground hover:text-primary bg-muted hover:bg-border px-2 py-1 rounded transition-colors">
                      BE
                    </button>
                  </div>
                </div>
                {/* TP Input */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <Label className="text-sm font-semibold text-foreground/80 flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" /> Take Profit
                    </Label>
                    {tpPips && <span className="text-xs font-bold text-success bg-success/10 px-2 py-0.5 rounded-full">{tpPips} pips target</span>}
                  </div>
                  <Input type="number" step="0.00001" value={modifyTP} onChange={e => setModifyTP(e.target.value)}
                    className="h-12 text-base font-mono rounded-lg border-emerald-200 focus:border-emerald-400" />
                </div>
                {/* R:R Preview */}
                {rr && (
                  <div className={`flex items-center justify-between px-4 py-3 rounded-xl border ${parseFloat(rr) >= 1.5 ? 'bg-success/10 border-emerald-200' : 'bg-gold/10 border-amber-200'}`}>
                    <span className="text-xs font-bold text-muted-foreground">Risk : Reward Ratio</span>
                    <span className={`text-lg font-black ${parseFloat(rr) >= 2 ? 'text-success' : parseFloat(rr) >= 1 ? 'text-gold' : 'text-destructive'}`}>
                      1 : {rr}
                    </span>
                  </div>
                )}
              </div>
            )
          })()}
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setModifyModal({ open: false, position: null })}>Cancel</Button>
            <Button onClick={handleModifySLTP} disabled={actionLoading} className="bg-primary hover:bg-primary/90">
              {actionLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Update Levels
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={modifyOrderModal.open} onOpenChange={(open) => setModifyOrderModal({ open, order: null })}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-xl font-bold text-foreground flex items-center gap-2">
              <Edit3 className="h-5 w-5 text-primary" /> Modify Pending Order
            </DialogTitle>
          </DialogHeader>
          {modifyOrderModal.order && (() => {
            const order = modifyOrderModal.order!
            const isBuy = order.type % 2 === 0
            // Determine pip multiplier based on symbol
            let pipMult = 10000 // Default for standard forex (1 pip = 0.0001)
            if (order.symbol.includes('JPY')) {
              pipMult = 100 // JPY pairs (1 pip = 0.01)
            } else if (order.symbol.includes('XAU') || order.symbol.includes('GOLD')) {
              pipMult = 10 // Gold (1 pip = 0.1)
            } else if (order.symbol.includes('XAG') || order.symbol.includes('SILVER') || order.symbol.includes('XPD') || order.symbol.includes('XPT')) {
              pipMult = 100 // Silver / Platinum / Palladium (1 pip = 0.01, digits=3)
            } else if (order.symbol.includes('BTC') || order.symbol.includes('ETH')) {
              pipMult = 10 // Crypto (1 pip = 0.1)
            }
            const slPips = orderSL && parseFloat(orderSL) > 0 && orderPrice
              ? Math.abs((parseFloat(orderPrice) - parseFloat(orderSL)) * pipMult).toFixed(1)
              : null
            const tpPips = orderTP && parseFloat(orderTP) > 0 && orderPrice
              ? Math.abs((parseFloat(orderTP) - parseFloat(orderPrice)) * pipMult).toFixed(1)
              : null
            return (
              <div className="space-y-4 py-2">
                <div className="flex items-center gap-3 bg-muted/50 rounded-xl px-4 py-3 border border-border/50">
                  <Badge className={isBuy ? 'bg-emerald-500' : 'bg-rose-500'}>{getOrderTypeName(order.type)}</Badge>
                  <div>
                    <p className="font-bold text-foreground">{order.symbol}</p>
                    <p className="text-xs text-muted-foreground/70">#{order.ticket} · {(order.volume || order.volume_initial).toFixed(2)} lots</p>
                  </div>
                  <div className="ml-auto text-right">
                    <p className="text-[10px] text-muted-foreground font-mono uppercase tracking-widest">Current Target</p>
                    <p className="font-mono font-bold text-foreground/80">{order.price_open.toFixed(5)}</p>
                  </div>
                </div>
                <div className="space-y-1.5">
                  <Label className="text-sm font-semibold text-foreground/80">New Entry Price</Label>
                  <Input id="price" type="number" step="0.00001" value={orderPrice}
                    onChange={(e) => setOrderPrice(e.target.value)} placeholder="0.00000"
                    className="h-12 text-base font-mono rounded-lg border-border focus:border-primary" />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between">
                      <Label className="text-sm font-semibold text-foreground/80 flex items-center gap-1.5">
                        <span className="w-2 h-2 rounded-full bg-rose-500 inline-block" /> Stop Loss
                      </Label>
                      {slPips && <span className="text-[10px] font-bold text-destructive">{slPips}p</span>}
                    </div>
                    <Input id="order-sl" type="number" step="0.00001" value={orderSL}
                      onChange={(e) => setOrderSL(e.target.value)} placeholder="0.00000"
                      className="h-11 text-sm font-mono rounded-lg border-rose-200 focus:border-rose-400" />
                  </div>
                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between">
                      <Label className="text-sm font-semibold text-foreground/80 flex items-center gap-1.5">
                        <span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" /> Take Profit
                      </Label>
                      {tpPips && <span className="text-[10px] font-bold text-success">{tpPips}p</span>}
                    </div>
                    <Input id="order-tp" type="number" step="0.00001" value={orderTP}
                      onChange={(e) => setOrderTP(e.target.value)} placeholder="0.00000"
                      className="h-11 text-sm font-mono rounded-lg border-emerald-200 focus:border-emerald-400" />
                  </div>
                </div>
              </div>
            )
          })()}
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setModifyOrderModal({ open: false, order: null })}>Cancel</Button>
            <Button onClick={handleModifyOrder} disabled={actionLoading} className="bg-primary hover:bg-primary/90">
              {actionLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Modify Order
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={partialCloseModal.open} onOpenChange={(open) => setPartialCloseModal({ open, position: null })}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-xl font-bold text-foreground flex items-center gap-2">
              <Maximize2 className="h-5 w-5 text-orange-500" /> Partial Close
            </DialogTitle>
          </DialogHeader>
          {partialCloseModal.position && (() => {
            const pos = partialCloseModal.position!
            const step = symbolInfo?.volumeStep ?? 0.01
            const min = symbolInfo?.volumeMin ?? 0.01
            const max = symbolInfo ? Math.min(symbolInfo.volumeMax, pos.volume) : pos.volume
            const rawVol = parseFloat(partialVolume) || 0
            const rounded = rawVol > 0 ? Math.round(rawVol / step) * step : 0
            const roundedFixed = parseFloat(rounded.toFixed(8))
            const wasRounded = rawVol > 0 && Math.abs(roundedFixed - rawVol) > 0.000001
            const isTooSmall = rawVol > 0 && roundedFixed < min
            const isTooLarge = rawVol > 0 && roundedFixed > max
            const wouldCloseAll = rawVol > 0 && roundedFixed >= pos.volume
            const isInvalid = isTooSmall || isTooLarge || wouldCloseAll || rawVol <= 0
            const pct = pos.volume > 0 && rawVol > 0 ? ((rawVol / pos.volume) * 100).toFixed(0) : '0'
            const remaining = (pos.volume - roundedFixed).toFixed(2)

            return (
              <div className="space-y-4 py-2">
                {/* Position Header */}
                <div className="flex items-center justify-between bg-muted/50 rounded-xl px-4 py-3 border border-border/50">
                  <div>
                    <p className="text-xs text-muted-foreground/70 font-medium uppercase tracking-widest">Position</p>
                    <p className="font-bold text-foreground">{pos.symbol} <span className="text-muted-foreground/70 font-normal text-xs">#{pos.ticket}</span></p>
                  </div>
                  <div className="text-right">
                    <p className="text-xs text-muted-foreground/70 font-medium uppercase tracking-widest">Total Lots</p>
                    <p className="text-xl font-black text-foreground">{pos.volume}</p>
                  </div>
                </div>

                {/* Constraints strip */}
                {symbolInfoLoading ? (
                  <div className="flex items-center gap-2 text-xs text-muted-foreground/70 bg-muted/50 rounded-lg px-3 py-2">
                    <Loader2 className="h-3 w-3 animate-spin" /> Loading symbol constraints…
                  </div>
                ) : symbolInfo ? (
                  <div className="flex items-center gap-3 bg-primary/10 border border-blue-100 rounded-lg px-3 py-2 text-xs font-mono">
                    <span className="text-blue-400 font-bold uppercase tracking-wide text-[10px]">Constraints</span>
                    <span className="text-primary">Min: <strong>{min}</strong></span>
                    <span className="text-primary">Max: <strong>{max}</strong></span>
                    <span className="text-primary">Step: <strong>{step}</strong></span>
                  </div>
                ) : null}

                {/* Percentage Presets */}
                <div>
                  <p className="text-xs font-bold text-muted-foreground/70 uppercase tracking-widest mb-2">Quick Select</p>
                  <div className="grid grid-cols-4 gap-2">
                    {[25, 33, 50, 75].map(p => {
                      const presetRaw = pos.volume * p / 100
                      const presetRounded = Math.round(presetRaw / step) * step
                      const presetFinal = parseFloat(Math.max(min, Math.min(max - step, presetRounded)).toFixed(8))
                      return (
                        <button key={p}
                          onClick={() => setPartialVolume(presetFinal.toFixed(2))}
                          className={`py-2 rounded-lg text-sm font-bold border transition-all ${
                            pct === String(p)
                              ? 'bg-orange-500 text-white border-orange-500 shadow-md'
                              : 'bg-card text-foreground/80 border-border hover:border-orange-300 hover:text-orange-600'
                          }`}
                        >{p}%</button>
                      )
                    })}
                  </div>
                </div>

                {/* Volume Input */}
                <div className="space-y-1.5">
                  <Label className="text-sm font-semibold text-foreground/80">Lots to Close</Label>
                  <Input
                    type="number"
                    step={step}
                    min={min}
                    max={max}
                    value={partialVolume}
                    onChange={(e) => setPartialVolume(e.target.value)}
                    className={`h-12 text-lg font-mono font-bold rounded-lg transition-colors ${
                      isInvalid && rawVol > 0
                        ? 'border-rose-400 bg-destructive/10 focus:border-rose-500'
                        : 'border-orange-200 focus:border-orange-400'
                    }`}
                  />
                  {/* Inline validation messages */}
                  {isTooSmall && <p className="text-xs text-destructive font-semibold">⚠ Below minimum lot size — must be at least <strong>{min}</strong> lots</p>}
                  {isTooLarge && <p className="text-xs text-destructive font-semibold">⚠ Exceeds maximum — must be less than <strong>{max}</strong> lots</p>}
                  {wouldCloseAll && <p className="text-xs text-destructive font-semibold">⚠ Would close entire position — use "Close Position" instead</p>}
                  {wasRounded && !isInvalid && (
                    <div className="flex items-center gap-2 bg-gold/10 border border-amber-200 rounded-lg px-3 py-2">
                      <Info className="h-3.5 w-3.5 text-gold shrink-0" />
                      <p className="text-xs text-gold">
                        Will be rounded from <strong>{rawVol.toFixed(2)}</strong> → <strong>{roundedFixed.toFixed(2)}</strong> lots (step: {step})
                      </p>
                    </div>
                  )}
                </div>

                {/* Impact Preview — only shown when valid */}
                {!isInvalid && roundedFixed > 0 && (
                  <div className="grid grid-cols-2 gap-2">
                    <div className="bg-orange-50 border border-orange-100 rounded-lg p-3 text-center">
                      <p className="text-[10px] font-bold text-orange-400 uppercase tracking-widest">Closing</p>
                      <p className="text-lg font-black text-orange-600">{roundedFixed.toFixed(2)} <span className="text-xs font-normal">lots</span></p>
                      <p className="text-xs text-orange-400">{pct}% of position</p>
                    </div>
                    <div className="bg-muted/50 border border-border/50 rounded-lg p-3 text-center">
                      <p className="text-[10px] font-bold text-muted-foreground/70 uppercase tracking-widest">Remaining</p>
                      <p className="text-lg font-black text-foreground/80">{remaining} <span className="text-xs font-normal">lots</span></p>
                      <p className="text-xs text-muted-foreground/70">{(100 - parseInt(pct)).toFixed(0)}% kept</p>
                    </div>
                  </div>
                )}
              </div>
            )
          })()}
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setPartialCloseModal({ open: false, position: null })}>Cancel</Button>
            <Button
              onClick={handlePartialClose}
              disabled={actionLoading || (() => {
                if (!partialCloseModal.position || !symbolInfo) return false
                const pos = partialCloseModal.position
                const step = symbolInfo.volumeStep
                const min = symbolInfo.volumeMin
                const max = Math.min(symbolInfo.volumeMax, pos.volume)
                const raw = parseFloat(partialVolume) || 0
                const rounded = parseFloat((Math.round(raw / step) * step).toFixed(8))
                return raw <= 0 || rounded < min || rounded > max || rounded >= pos.volume
              })()}
              className="bg-orange-600 hover:bg-orange-700 text-white disabled:opacity-50"
            >
              {actionLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Execute Partial Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={confirmDialog.open} onOpenChange={o => !o && setConfirmDialog({ ...confirmDialog, open: false })}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className={`text-xl font-bold flex items-center gap-2 ${confirmDialog.danger ? 'text-destructive' : 'text-foreground'}`}>
              {confirmDialog.danger
                ? <AlertTriangle className="h-5 w-5 text-destructive" />
                : <Info className="h-5 w-5 text-primary" />}
              {confirmDialog.title}
            </DialogTitle>
          </DialogHeader>
          <div className={`rounded-xl border p-4 my-2 ${confirmDialog.danger ? 'bg-destructive/10 border-rose-200' : 'bg-muted/50 border-border'}`}>
            <p className={`text-sm leading-relaxed ${confirmDialog.danger ? 'text-destructive' : 'text-foreground/80'}`}>
              {confirmDialog.message}
            </p>
          </div>
          {confirmDialog.danger && (
            <p className="text-xs text-destructive font-medium text-center">⚠️ This action cannot be undone</p>
          )}
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setConfirmDialog({ ...confirmDialog, open: false })}>
              Abort
            </Button>
            <Button
              onClick={() => { setConfirmDialog({ ...confirmDialog, open: false }); confirmDialog.onConfirm(); }}
              className={confirmDialog.danger ? 'bg-rose-600 hover:bg-rose-700 text-white' : 'bg-primary hover:bg-primary/90 text-white'}
            >
              Confirm
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Mobile Edit Order sheet (opened only from the mobile Orders tab) */}
      <MobileOrderEditSheet
        order={mobileEditOrder}
        saving={actionLoading}
        onClose={() => setMobileEditOrder(null)}
        onSave={handleMobileOrderSave}
        onDelete={o => confirmCancelOrder(o as Order)}
        onMarket={o => { setMobileEditOrder(null); setMarketTicket(o.ticket) }}
      />

      <ConvertToMarketDialog
        ticket={marketTicket}
        onClose={() => setMarketTicket(null)}
        onDone={() => { fetchData() }}
      />

      {/* Nexal Trading Panel */}
      <NexalPanel
        account={account}
        positions={positions}
        actionLoading={actionLoading}
        externalModalOpen={anyModalOpen}
        onClosePosition={(ticket) => {
          const pos = positions.find(p => p.ticket === ticket)
          if (pos) closePosition(pos)
        }}
        onHalfPosition={(ticket) => {
          const pos = positions.find(p => p.ticket === ticket)
          if (pos) {
            setPartialCloseModal({ open: true, position: pos })
            setPartialVolume((pos.volume / 2).toFixed(2))
          }
        }}
        onCloseProfitable={handleCloseProfitable}
        onCloseLosing={handleCloseLosing}
        onCloseAll={closeAll}
      />
    </div>
  )
}
