'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { createChart, IChartApi, ISeriesApi, ColorType, CandlestickSeriesPartialOptions, HistogramSeriesPartialOptions, BarData, HistogramData, Time } from 'lightweight-charts'
import {
  Activity,
  TrendingUp,
  TrendingDown,
  RefreshCw,
  Loader2,
  ArrowLeft,
  Zap,
  Maximize2,
  Edit3,
  X,
  TrendingUpDown,
  ExternalLink,
} from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn, formatCurrency } from '@/lib/utils'
import MobilePageHeader from '@/components/MobilePageHeader'

interface Candle {
  time: string
  open: number
  high: number
  low: number
  close: number
  tick_volume: number
}

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

interface PriceInfo {
  bid: number
  ask: number
  spread: number
  high: number
  low: number
  change: number
  changePct: number
  digits: number
}

const TIMEFRAMES = ['M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1', 'W1'] as const
type TimeframeT = typeof TIMEFRAMES[number]

const TF_LABELS: Record<TimeframeT, string> = {
  M1: '1m', M5: '5m', M15: '15m', M30: '30m',
  H1: '1h', H4: '4h', D1: 'D', W1: 'W',
}

export default function LiveTradePage() {
  const params = useParams()
  const router = useRouter()
  const ticket = params?.id as string

  const [position, setPosition] = useState<Position | null>(null)
  const [priceInfo, setPriceInfo] = useState<PriceInfo | null>(null)
  const [selectedTimeframe, setSelectedTimeframe] = useState<TimeframeT>('M5')
  const [loading, setLoading] = useState(true)
  const [chartLoading, setChartLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const chartContainerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null)
  const entryLineRef = useRef<ISeriesApi<'Line'> | null>(null)

  // ── Chart Setup ──
  useEffect(() => {
    if (!chartContainerRef.current) return

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#0D1624' },
        textColor: '#6B7A99',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: '#18243A' },
        horzLines: { color: '#18243A' },
      },
      crosshair: {
        mode: 0,
        vertLine: { color: '#29ADFF', width: 1, style: 2, labelBackgroundColor: '#29ADFF' },
        horzLine: { color: '#29ADFF', width: 1, style: 2, labelBackgroundColor: '#29ADFF' },
      },
      rightPriceScale: {
        borderColor: '#18243A',
        scaleMargins: { top: 0.05, bottom: 0.25 },
      },
      timeScale: {
        borderColor: '#18243A',
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 4,
      },
      handleScroll: { vertTouchDrag: true },
      handleScale: { axisPressedMouseMove: { time: true, price: true } },
    })

    const candleSeries = chart.addCandlestickSeries({
      upColor: '#24C87A',
      downColor: '#F23050',
      borderUpColor: '#24C87A',
      borderDownColor: '#F23050',
      wickUpColor: '#24C87A',
      wickDownColor: '#F23050',
      priceFormat: { type: 'price', precision: 5, minMove: 0.00001 },
    } as CandlestickSeriesPartialOptions)

    const volumeSeries = chart.addHistogramSeries({
      color: '#3b82f680',
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    } as HistogramSeriesPartialOptions)

    chart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.80, bottom: 0 },
      visible: true,
    })

    // Entry price line
    const entryLine = chart.addLineSeries({
      color: '#29ADFF',
      priceLineVisible: false,
      lastValueVisible: false,
      lineWidth: 1,
      lineStyle: 2,
    })

    chartRef.current = chart
    candleSeriesRef.current = candleSeries
    volumeSeriesRef.current = volumeSeries
    entryLineRef.current = entryLine

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect
        chart.applyOptions({ width, height })
      }
    })
    observer.observe(chartContainerRef.current)

    return () => {
      observer.disconnect()
      chart.remove()
      chartRef.current = null
      candleSeriesRef.current = null
      volumeSeriesRef.current = null
      entryLineRef.current = null
    }
  }, [])

  // ── Fetch Position ──
  const fetchPosition = useCallback(async () => {
    try {
      const res = await fetch('/api/mt5/positions')
      if (!res.ok) return
      const data = await res.json()
      const positions: Position[] = Array.isArray(data) ? data : data.positions || []
      const found = positions.find((p: Position) => p.ticket.toString() === ticket)
      setPosition(found || null)
      return found
    } catch {
      return null
    }
  }, [ticket])

  // ── Fetch Candles ──
  const fetchCandles = useCallback(async (symbol: string, tf: string) => {
    setChartLoading(true)
    try {
      const res = await fetch(`/api/candles?symbol=${symbol}&timeframe=${tf}&bars=200`)
      if (!res.ok) throw new Error('Failed')
      return await res.json() as Candle[]
    } catch {
      return null
    } finally {
      setChartLoading(false)
    }
  }, [])

  // ── Fetch Price Info ──
  const fetchPriceInfo = useCallback(async (symbol: string) => {
    try {
      const [tickRes, infoRes] = await Promise.all([
        fetch(`/api/symbol-info?symbol=${symbol}`),
        fetch(`/api/candles?symbol=${symbol}&timeframe=M1&bars=2`),
      ])
      const info = tickRes.ok ? await tickRes.json() : null
      const candles = infoRes.ok ? await infoRes.json() : []
      const tick = info?.tick || {}
      const symbolInfo = info?.symbol || {}
      const digits = symbolInfo.digits ?? 5
      const bid = tick.bid ?? 0
      const ask = tick.ask ?? 0
      const spread = symbolInfo.spread ?? 0
      let high = 0, low = 0, change = 0, changePct = 0
      if (candles?.length > 0) {
        const last = candles[candles.length - 1]
        high = last.high; low = last.low
        if (candles.length > 1) {
          const prevClose = candles[candles.length - 2].close
          change = last.close - prevClose
          changePct = prevClose !== 0 ? (change / prevClose) * 100 : 0
        }
      }
      setPriceInfo({ bid, ask, spread, high, low, change, changePct, digits })
    } catch { /* silent */ }
  }, [])

  // ── Load Chart Data ──
  const loadChartData = useCallback(async (symbol: string, tf: string) => {
    const candles = await fetchCandles(symbol, tf)
    if (!candles || candles.length === 0) {
      setError('No data available')
      return
    }
    setError(null)

    const candleData: BarData[] = []
    const volumeData: HistogramData[] = []
    for (const c of candles) {
      const time = (Math.floor(new Date(c.time).getTime() / 1000)) as Time
      candleData.push({ time, open: c.open, high: c.high, low: c.low, close: c.close })
      volumeData.push({ time, value: c.tick_volume, color: c.close >= c.open ? '#22c55e40' : '#ef444440' })
    }

    if (candleSeriesRef.current && volumeSeriesRef.current) {
      candleSeriesRef.current.setData(candleData)
      volumeSeriesRef.current.setData(volumeData)
      chartRef.current?.timeScale().fitContent()
    }
  }, [fetchCandles])

  // ── Init ──
  useEffect(() => {
    const init = async () => {
      setLoading(true)
      const pos = await fetchPosition()
      if (pos) {
        await Promise.all([
          loadChartData(pos.symbol, selectedTimeframe),
          fetchPriceInfo(pos.symbol),
        ])
        // Draw entry line
        if (entryLineRef.current) {
          const now = Math.floor(Date.now() / 1000)
          entryLineRef.current.setData([
            { time: (now - 86400 * 7) as Time, value: pos.price_open },
            { time: now as Time, value: pos.price_open },
          ])
        }
      } else {
        setError('Position not found')
      }
      setLoading(false)
    }
    init()
  }, [ticket, selectedTimeframe, fetchPosition, loadChartData, fetchPriceInfo])

  // ── Periodic refresh ──
  useEffect(() => {
    if (!position) return
    const interval = setInterval(() => {
      fetchPriceInfo(position.symbol)
      fetchPosition()
    }, 3000)
    return () => clearInterval(interval)
  }, [position, fetchPriceInfo, fetchPosition])

  // ── Position helpers ──
  const getOrderTypeName = (type: number) => type === 0 ? 'BUY' : 'SELL'
  const isBuy = position?.type === 0
  const isUp = (priceInfo?.change ?? 0) >= 0
  const changeColor = priceInfo?.change === 0 ? 'text-muted-foreground' : isUp ? 'text-green-600' : 'text-destructive'

  function getPips(pos: Position): string {
    const diff = pos.type === 0 ? pos.price_current - pos.price_open : pos.price_open - pos.price_current
    let multiplier = 10000
    if (pos.symbol.includes('JPY')) multiplier = 100
    else if (pos.symbol.includes('XAU') || pos.symbol.includes('GOLD')) multiplier = 10
    else if (pos.symbol.includes('XAG') || pos.symbol.includes('SILVER') || pos.symbol.includes('XPD') || pos.symbol.includes('XPT')) multiplier = 100
    return (diff * multiplier).toFixed(1)
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    )
  }

  if (error || !position) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <p className="text-destructive font-medium mb-4">{error || 'Position not found'}</p>
          <Button onClick={() => router.back()} variant="outline"><ArrowLeft className="h-4 w-4 mr-2" /> Back</Button>
        </div>
      </div>
    )
  }

  return (
    <>
      <MobilePageHeader title={`#${position.ticket}`} subtitle={position.symbol} hidden icon={<Activity className="h-5 w-5 text-primary" />} />

      <header className="hidden md:flex sticky top-0 z-40 w-full tech-header">
        <div className="max-w-[1800px] w-full mx-auto flex h-14 items-center px-6 gap-3">
          <Button variant="ghost" size="sm" onClick={() => router.back()} className="h-8 w-8 p-0 mr-1">
            <ArrowLeft className="h-4 w-4 text-muted-foreground" />
          </Button>
          <div className="p-1.5 rounded-lg bg-primary/10">
            <Activity className="h-5 w-5 text-primary" />
          </div>
          <div className="flex flex-col">
            <h1 className="text-sm font-bold text-foreground leading-none">#{position.ticket} · {position.symbol}</h1>
            <p className="text-[11px] text-muted-foreground/70 font-medium mt-0.5">{position.volume.toFixed(2)} {getOrderTypeName(position.type)}</p>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <div className='w-2 h-2 rounded-full bg-blue-400 animate-pulse' />
            <span className='text-[11px] text-muted-foreground/70 font-medium'>Polling</span>
          </div>
        </div>
      </header>

      <div className="flex-1 px-4 md:px-8 py-4 md:py-6">
        <div className="flex flex-col gap-3 md:gap-6 max-w-[1800px] mx-auto">

          {/* ── Position Info Bar ── */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Card className="border-border bg-card/90 backdrop-blur-[14px]">
              <CardContent className="p-3 md:p-4">
                <span className="text-[10px] font-semibold text-muted-foreground/70 uppercase tracking-wider">P&L</span>
                <p className={`text-lg font-bold ${position.profit >= 0 ? 'text-success' : 'text-destructive'}`}>
                  {position.profit >= 0 ? '+' : ''}{formatCurrency(position.profit)}
                </p>
                <p className={`text-xs font-semibold ${parseFloat(getPips(position)) >= 0 ? 'text-success' : 'text-destructive'}`}>
                  {parseFloat(getPips(position)) >= 0 ? '+' : ''}{getPips(position)} Pips
                </p>
              </CardContent>
            </Card>

            <Card className="border-border bg-card/90 backdrop-blur-[14px]">
              <CardContent className="p-3 md:p-4">
                <span className="text-[10px] font-semibold text-muted-foreground/70 uppercase tracking-wider">Entry</span>
                <p className="text-lg font-bold text-foreground font-mono">{position.price_open.toFixed(5)}</p>
                <p className="text-xs text-muted-foreground font-medium">
                  {getOrderTypeName(position.type)} · {position.volume.toFixed(2)}
                </p>
              </CardContent>
            </Card>

            <Card className="border-border bg-card/90 backdrop-blur-[14px]">
              <CardContent className="p-3 md:p-4">
                <span className="text-[10px] font-semibold text-muted-foreground/70 uppercase tracking-wider">Current</span>
                <p className="text-lg font-bold text-foreground font-mono">{position.price_current.toFixed(5)}</p>
                <div className="flex items-center gap-1">
                  <span className="text-xs text-muted-foreground/70">Bid:</span>
                  <span className="text-xs font-mono font-semibold text-muted-foreground">{priceInfo?.bid.toFixed(position.symbol.includes('JPY') ? 3 : 5) ?? '--'}</span>
                  <span className="text-xs text-muted-foreground/70 ml-1">Ask:</span>
                  <span className="text-xs font-mono font-semibold text-muted-foreground">{priceInfo?.ask.toFixed(position.symbol.includes('JPY') ? 3 : 5) ?? '--'}</span>
                </div>
              </CardContent>
            </Card>

            <Card className="border-border bg-card/90 backdrop-blur-[14px]">
              <CardContent className="p-3 md:p-4">
                <span className="text-[10px] font-semibold text-muted-foreground/70 uppercase tracking-wider">SL / TP</span>
                <p className="text-lg font-bold font-mono">
                  <span className={position.sl > 0 ? 'text-destructive' : 'text-muted-foreground/50'}>{position.sl > 0 ? position.sl.toFixed(5) : '---'}</span>
                  <span className="text-muted-foreground/50 mx-1">/</span>
                  <span className={position.tp > 0 ? 'text-success' : 'text-muted-foreground/50'}>{position.tp > 0 ? position.tp.toFixed(5) : '---'}</span>
                </p>
                <div className="flex items-center gap-1">
                  <span className="text-xs text-muted-foreground/70">Spread:</span>
                  <span className="text-xs font-mono font-semibold text-muted-foreground">{priceInfo?.spread ?? '--'}</span>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* ── Timeframe Buttons ── */}
          <div className="flex flex-wrap gap-1.5">
            {TIMEFRAMES.map((tf) => (
              <button
                key={tf}
                onClick={() => setSelectedTimeframe(tf)}
                className={cn(
                  'px-3 py-1.5 rounded-lg text-xs font-semibold transition-all',
                  selectedTimeframe === tf
                    ? 'bg-primary text-white shadow-sm'
                    : 'bg-muted text-muted-foreground hover:bg-border'
                )}
              >
                {TF_LABELS[tf]}
              </button>
            ))}
          </div>

          {/* ── Chart ── */}
          <Card className="border-border bg-card">
            <CardHeader className="p-3 md:p-4 pb-0 flex flex-row items-center justify-between">
              <CardTitle className="text-sm font-bold text-foreground">
                {position.symbol}
                <span className="text-[11px] font-medium text-muted-foreground/70 ml-2">{TF_LABELS[selectedTimeframe]}</span>
              </CardTitle>
              <div className="flex items-center gap-1.5">
                {chartLoading && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground/70" />}
                <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => {
                  loadChartData(position.symbol, selectedTimeframe)
                  fetchPriceInfo(position.symbol)
                }}>
                  <RefreshCw className="h-3.5 w-3.5 text-muted-foreground/70" />
                </Button>
              </div>
            </CardHeader>
            <CardContent className="p-0 relative">
              <div ref={chartContainerRef} className="w-full" style={{ height: '520px' }} />
              {error && (
                <div className="absolute inset-0 flex items-center justify-center bg-white/80 z-10">
                  <p className="text-sm text-muted-foreground font-medium">{error}</p>
                </div>
              )}
            </CardContent>
          </Card>

          {/* ── Trade Details ── */}
          <Card className="border-border bg-card/90 backdrop-blur-[14px]">
            <CardHeader className="p-3 md:p-4 pb-0">
              <CardTitle className="text-xs font-bold text-muted-foreground uppercase tracking-wider">Trade Details</CardTitle>
            </CardHeader>
            <CardContent className="p-3 md:p-4">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div><span className="text-[10px] font-semibold text-muted-foreground/70 uppercase">Ticket</span><p className="text-sm font-mono font-bold text-foreground">#{position.ticket}</p></div>
                <div><span className="text-[10px] font-semibold text-muted-foreground/70 uppercase">Type</span><p className="text-sm font-bold" style={{ color: isBuy ? '#22c55e' : '#ef4444' }}>{getOrderTypeName(position.type)}</p></div>
                <div><span className="text-[10px] font-semibold text-muted-foreground/70 uppercase">Volume</span><p className="text-sm font-mono font-bold text-foreground">{position.volume.toFixed(2)}</p></div>
                <div><span className="text-[10px] font-semibold text-muted-foreground/70 uppercase">Swap</span><p className="text-sm font-mono font-bold text-foreground">{formatCurrency(position.swap)}</p></div>
                <div><span className="text-[10px] font-semibold text-muted-foreground/70 uppercase">Commission</span><p className="text-sm font-mono font-bold text-foreground">{formatCurrency(position.commission)}</p></div>
                <div><span className="text-[10px] font-semibold text-muted-foreground/70 uppercase">Open Time</span><p className="text-sm font-mono font-bold text-foreground">{position.time ? new Date(position.time).toLocaleString() : '--'}</p></div>
                <div className="md:col-span-2">
                  <span className="text-[10px] font-semibold text-muted-foreground/70 uppercase">SL → BE</span>
                  <p className="text-sm font-mono font-bold text-foreground">{position.sl > 0 ? position.sl.toFixed(5) : 'none'} → {position.price_open.toFixed(5)} ({((position.price_open - position.sl) / (position.sl || 1) * 100).toFixed(2)}% move)</p>
                </div>
              </div>
            </CardContent>
          </Card>

        </div>
      </div>
    </>
  )
}
