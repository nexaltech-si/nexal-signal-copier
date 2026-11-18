'use client'

import { useState, useEffect, useCallback } from 'react'
import { LineChart as LineChartIcon, RefreshCw, TrendingUp, Activity, BarChart3 } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import MobilePageHeader from '@/components/MobilePageHeader'
import { formatCurrency } from '@/lib/utils'

interface IndicatorsResponse {
  ok: boolean
  symbol?: string
  timeframe?: string
  error?: string
  indicators?: {
    rsi: number | null
    macd: { macd: number } | null
    bollinger: { upper: number; lower: number; middle: number } | null
    volatility: number | null
    available: boolean
  }
}

interface PerformanceResponse {
  ok: boolean
  trade_count?: number
  days?: number
  stats?: {
    sharpe_ratio: number | null
    max_drawdown: number | null
    volatility: number | null
    available: boolean
  }
}

function StatTile({ label, value, suffix = '' }: { label: string; value: string | number | null; suffix?: string }) {
  return (
    <div className="rounded-lg border border-border bg-card/40 p-4">
      <div className="text-xs text-muted-foreground mb-1">{label}</div>
      <div className="text-xl font-semibold text-foreground">
        {value === null || value === undefined ? '—' : `${value}${suffix}`}
      </div>
    </div>
  )
}

export default function GsQuantInsightsPage() {
  const [symbol, setSymbol] = useState('XAUUSD')
  const [timeframe, setTimeframe] = useState('1h')
  const [indicators, setIndicators] = useState<IndicatorsResponse | null>(null)
  const [performance, setPerformance] = useState<PerformanceResponse | null>(null)
  const [loading, setLoading] = useState(false)

  const fetchIndicators = useCallback(async () => {
    try {
      const res = await fetch(`/api/gsquant/indicators?symbol=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(timeframe)}`)
      const data = await res.json()
      setIndicators(data)
    } catch (err) {
      setIndicators({ ok: false, error: String(err) })
    }
  }, [symbol, timeframe])

  const fetchPerformance = useCallback(async () => {
    try {
      const res = await fetch('/api/gsquant/performance?days=90')
      const data = await res.json()
      setPerformance(data)
    } catch (err) {
      setPerformance({ ok: false })
    }
  }, [])

  const refresh = useCallback(async () => {
    setLoading(true)
    await Promise.all([fetchIndicators(), fetchPerformance()])
    setLoading(false)
  }, [fetchIndicators, fetchPerformance])

  useEffect(() => {
    refresh()
  }, [refresh])

  const ind = indicators?.indicators
  const stats = performance?.stats

  return (
    <div className="p-4 md:p-8 space-y-6">
      <MobilePageHeader
        title="gs-quant Insights"
        subtitle="Read-only technical & performance analytics"
        icon={<LineChartIcon className="h-5 w-5 text-primary" />}
      />

      <div className="hidden md:flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-foreground flex items-center gap-2">
            <LineChartIcon className="h-6 w-6 text-primary" />
            gs-quant Insights
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Technical indicators and performance statistics computed via Goldman Sachs' open-source
            gs-quant library (offline analytics only — advisory, does not affect live trading).
          </p>
        </div>
        <Badge variant={ind?.available === false ? 'destructive' : 'secondary'}>
          {ind?.available === false ? 'gs-quant unavailable' : 'gs-quant active'}
        </Badge>
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-2 flex-wrap">
          <CardTitle className="text-base flex items-center gap-2">
            <Activity className="h-4 w-4 text-primary" />
            Technical Indicators
          </CardTitle>
          <div className="flex items-center gap-2">
            <Input
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
              className="h-8 w-28 text-sm"
              placeholder="Symbol"
            />
            <Input
              value={timeframe}
              onChange={(e) => setTimeframe(e.target.value)}
              className="h-8 w-20 text-sm"
              placeholder="1h"
            />
            <Button size="sm" variant="outline" onClick={refresh} disabled={loading}>
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {indicators?.ok === false && (
            <p className="text-sm text-destructive">{indicators.error || 'Failed to load indicators'}</p>
          )}
          {indicators?.ok && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <StatTile label="RSI (14)" value={ind?.rsi != null ? ind.rsi.toFixed(2) : null} />
              <StatTile label="MACD" value={ind?.macd?.macd != null ? ind.macd.macd.toFixed(4) : null} />
              <StatTile
                label="Bollinger Bands"
                value={
                  ind?.bollinger
                    ? `${ind.bollinger.lower.toFixed(2)} – ${ind.bollinger.upper.toFixed(2)}`
                    : null
                }
              />
              <StatTile label="Volatility (ann.)" value={ind?.volatility != null ? ind.volatility.toFixed(2) : null} suffix="%" />
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <BarChart3 className="h-4 w-4 text-primary" />
            Real Trade Performance (last {performance?.days ?? 90} days)
          </CardTitle>
        </CardHeader>
        <CardContent>
          {performance?.ok === false && (
            <p className="text-sm text-destructive">Failed to load performance stats</p>
          )}
          {performance?.ok && (
            <div className="space-y-3">
              <p className="text-xs text-muted-foreground">
                Based on {performance.trade_count ?? 0} closed trade(s) from real trading history.
              </p>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                <StatTile label="Sharpe Ratio" value={stats?.sharpe_ratio != null ? stats.sharpe_ratio.toFixed(2) : null} />
                <StatTile label="Max Drawdown" value={stats?.max_drawdown != null ? formatCurrency(stats.max_drawdown) : null} />
                <StatTile label="Volatility (ann.)" value={stats?.volatility != null ? stats.volatility.toFixed(2) : null} suffix="%" />
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <p className="text-xs text-muted-foreground flex items-center gap-1.5">
        <TrendingUp className="h-3.5 w-3.5" />
        This page is purely informational. It does not influence signal parsing, confidence scoring,
        position sizing, or order execution anywhere in the bot.
      </p>
    </div>
  )
}
