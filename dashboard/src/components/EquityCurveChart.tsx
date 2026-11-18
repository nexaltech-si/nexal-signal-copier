'use client'

import {
  ComposedChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer
} from 'recharts'
import { Activity, TrendingUp, TrendingDown } from 'lucide-react'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { formatCurrency } from '@/lib/utils'

export interface EquityPoint {
  time: string
  balance: number
  equity: number
  drawdownPercent: number
}

export interface CumulativePoint {
  date: string
  cumulative: number
}

interface EquityCurveChartProps {
  points: EquityPoint[]
  hasEnoughData: boolean
  fallbackData: CumulativePoint[]
}

function CurveTooltip({ active, payload, label, real }: { active?: boolean; payload?: any[]; label?: string; real: boolean }) {
  if (!active || !payload || payload.length === 0) return null
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2 shadow-lg text-xs">
      <p className="font-semibold text-foreground mb-1">{label}</p>
      {real ? (
        <>
          <p className="text-foreground/80">Equity: <span className="font-bold">{formatCurrency(payload[0]?.payload?.equity ?? 0)}</span></p>
          <p className="text-muted-foreground">Drawdown: <span className="font-semibold text-destructive">{(payload[0]?.payload?.drawdownPercent ?? 0).toFixed(2)}%</span></p>
        </>
      ) : (
        <p className="text-foreground/80">P&amp;L: <span className="font-bold">{formatCurrency(payload[0]?.payload?.cumulative ?? 0)}</span></p>
      )}
    </div>
  )
}

export default function EquityCurveChart({ points, hasEnoughData, fallbackData }: EquityCurveChartProps) {
  const usingReal = hasEnoughData && points.length > 1

  let runningPeak = 0
  const data = usingReal
    ? points.map(p => {
        runningPeak = Math.max(runningPeak, p.equity)
        return {
          label: new Date(p.time).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
          equity: p.equity,
          gapToPeak: runningPeak - p.equity,
          drawdownPercent: p.drawdownPercent
        }
      })
    : fallbackData.map(p => ({
        label: p.date,
        cumulative: p.cumulative
      }))

  const startValue = usingReal ? points[0].equity : (fallbackData[0]?.cumulative ?? 0)
  const endValue = usingReal ? points[points.length - 1].equity : (fallbackData[fallbackData.length - 1]?.cumulative ?? 0)
  const change = endValue - startValue
  const changePct = startValue !== 0 ? (change / Math.abs(startValue)) * 100 : 0
  const worstDrawdown = usingReal ? Math.min(...points.map(p => p.drawdownPercent), 0) : 0

  return (
    <Card className="border border-border shadow-sm bg-card overflow-hidden">
      <CardHeader className="py-4 px-5 flex flex-row items-start justify-between gap-4 border-b bg-muted/30 flex-wrap">
        <div className="flex items-center gap-4 flex-wrap">
          <div>
            <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider flex items-center gap-1.5 mb-1">
              <Activity className="h-3.5 w-3.5 text-primary" />
              {usingReal ? 'Account Equity' : 'Realized P&L (estimated)'}
            </p>
            <p className="text-3xl md:text-4xl font-black tracking-tight text-foreground">
              {formatCurrency(endValue)}
            </p>
          </div>
          <div className={`flex items-center gap-1 px-2.5 py-1.5 rounded-lg font-bold text-sm ${change >= 0 ? 'bg-success/10 text-success' : 'bg-destructive/10 text-destructive'}`}>
            {change >= 0 ? <TrendingUp className="h-4 w-4" /> : <TrendingDown className="h-4 w-4" />}
            {change >= 0 ? '+' : ''}{formatCurrency(change)}
            <span className="opacity-70 font-semibold">({changePct >= 0 ? '+' : ''}{changePct.toFixed(1)}%)</span>
          </div>
        </div>
        {usingReal ? (
          <div className="text-right">
            <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider mb-1">Worst Drawdown</p>
            <p className="text-xl font-black text-destructive">{worstDrawdown.toFixed(2)}%</p>
          </div>
        ) : (
          <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider max-w-[220px] text-right">
            Collecting equity history — showing realized P&amp;L until enough data accumulates
          </span>
        )}
      </CardHeader>
      <CardContent className="p-5 pt-4">
        {data.length === 0 ? (
          <div className="h-[360px] flex items-center justify-center text-sm text-muted-foreground">
            No data available yet
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={360}>
            <ComposedChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="hsl(var(--chart-1))" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="hsl(var(--chart-1))" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="drawdownGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="hsl(var(--destructive))" stopOpacity={0} />
                  <stop offset="95%" stopColor="hsl(var(--destructive))" stopOpacity={0.4} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="hsl(var(--border))" />
              <XAxis dataKey="label" tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }} stroke="hsl(var(--border))" minTickGap={40} />
              <YAxis
                yAxisId="value"
                tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }}
                stroke="hsl(var(--border))"
                width={56}
                tickFormatter={(v) => usingReal ? `$${(v / 1000).toFixed(1)}k` : `$${v.toFixed(0)}`}
              />
              <Tooltip content={<CurveTooltip real={usingReal} />} />
              {usingReal ? (
                <>
                  <Area yAxisId="value" type="monotone" dataKey="equity" stackId="equity" stroke="hsl(var(--chart-1))" strokeWidth={2.5} fill="url(#equityGrad)" />
                  <Area yAxisId="value" type="monotone" dataKey="gapToPeak" stackId="equity" stroke="none" fill="url(#drawdownGrad)" />
                </>
              ) : (
                <Area yAxisId="value" type="monotone" dataKey="cumulative" stroke="hsl(var(--chart-1))" strokeWidth={2.5} fill="url(#equityGrad)" />
              )}
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  )
}
