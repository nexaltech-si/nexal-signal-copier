'use client'

import { Activity } from 'lucide-react'
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts'
import WidgetCard, { WidgetEmpty } from './WidgetCard'
import type { DailyPerformance } from '@/lib/types'

interface PerformancePanelProps {
  daily: DailyPerformance[]
}

/** 7-day cumulative performance area chart, styled to match the mockup. */
export default function PerformancePanel({ daily }: PerformancePanelProps) {
  // Take the last 7 days and build a cumulative P/L series.
  const sorted = [...daily].sort((a, b) => a.date.localeCompare(b.date)).slice(-7)
  let running = 0
  const data = sorted.map((d) => {
    running += d.profit
    return {
      label: d.date.slice(5), // MM-DD
      pl: Number(running.toFixed(2)),
    }
  })

  const totalPL = data.length ? data[data.length - 1].pl : 0
  const positive = totalPL >= 0
  const stroke = positive ? 'hsl(var(--success))' : 'hsl(var(--destructive))'

  return (
    <WidgetCard
      title="Performance (7 Days)"
      icon={<Activity className="h-4 w-4" />}
      actionLabel="Full history"
      actionHref="/performance"
    >
      {data.length === 0 ? (
        <WidgetEmpty message="No closed trades in the last 7 days" />
      ) : (
        <>
          <div className="mb-3">
            <span
              className="text-2xl font-black tabular-nums font-mono"
              style={{ color: stroke }}
            >
              {positive ? '+' : ''}
              {totalPL.toFixed(2)}
            </span>
            <span className="tech-label ml-2">cumulative P/L</span>
          </div>
          <ResponsiveContainer width="100%" height={180}>
            <AreaChart data={data} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
              <defs>
                <linearGradient id="plFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={stroke} stopOpacity={0.35} />
                  <stop offset="100%" stopColor={stroke} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="hsl(var(--border))"
                vertical={false}
              />
              <XAxis
                dataKey="label"
                stroke="hsl(var(--muted-foreground))"
                fontSize={10}
                tickLine={false}
                axisLine={false}
              />
              <YAxis
                stroke="hsl(var(--muted-foreground))"
                fontSize={10}
                tickLine={false}
                axisLine={false}
                tickFormatter={(v) => `$${v}`}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: 'hsl(var(--card))',
                  border: '1px solid hsl(var(--border))',
                  borderRadius: '8px',
                  fontSize: '12px',
                }}
                labelStyle={{ color: 'hsl(var(--foreground))', fontWeight: 600 }}
                formatter={(v: number) => [`$${v.toFixed(2)}`, 'Cumulative P/L']}
              />
              <Area
                type="monotone"
                dataKey="pl"
                stroke={stroke}
                strokeWidth={2}
                fill="url(#plFill)"
              />
            </AreaChart>
          </ResponsiveContainer>
        </>
      )}
    </WidgetCard>
  )
}
