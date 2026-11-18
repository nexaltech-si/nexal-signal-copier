'use client'

import { BarChart, Bar, Cell, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine, ResponsiveContainer } from 'recharts'
import { Target } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

export interface RMultipleBucket {
  range: string
  count: number
}

export interface RMultipleSummary {
  avgRMultiple: number
  expectancyR: number
  tradesWithRiskData: number
  tradesWithoutRiskData: number
}

interface RMultipleHistogramProps {
  data: RMultipleBucket[]
  summary: RMultipleSummary
}

const NEGATIVE_BUCKETS = new Set(['<-2R', '-2R to -1R', '-1R to 0R'])

function HistTooltip({ active, payload }: { active?: boolean; payload?: any[] }) {
  if (!active || !payload || payload.length === 0) return null
  const { range, count } = payload[0].payload
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2 shadow-md text-xs">
      <p className="font-semibold text-foreground">{range}</p>
      <p className="text-muted-foreground">{count} trade{count === 1 ? '' : 's'}</p>
    </div>
  )
}

export default function RMultipleHistogram({ data, summary }: RMultipleHistogramProps) {
  const hasData = summary.tradesWithRiskData > 0

  return (
    <Card className="border border-border shadow-sm bg-card overflow-hidden">
      <CardHeader className="py-3.5 px-5 border-b bg-muted/40">
        <CardTitle className="text-sm font-bold flex items-center gap-2 text-foreground">
          <Target className="h-4 w-4 text-primary" />
          R-Multiple Distribution
        </CardTitle>
      </CardHeader>
      <CardContent className="p-5">
        {!hasData ? (
          <div className="h-[280px] flex items-center justify-center text-sm text-muted-foreground text-center px-6">
            No trades with risk data yet — R-multiples need a stored risk amount on the originating signal.
          </div>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-4 mb-5">
              <div className="rounded-lg border border-border/60 bg-muted/20 px-4 py-3">
                <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider mb-1">Average R</p>
                <p className={`text-3xl font-black tracking-tight ${summary.avgRMultiple >= 0 ? 'text-success' : 'text-destructive'}`}>
                  {summary.avgRMultiple >= 0 ? '+' : ''}{summary.avgRMultiple.toFixed(2)}R
                </p>
              </div>
              <div className="rounded-lg border border-border/60 bg-muted/20 px-4 py-3">
                <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider mb-1">Expectancy</p>
                <p className={`text-3xl font-black tracking-tight ${summary.expectancyR >= 0 ? 'text-success' : 'text-destructive'}`}>
                  {summary.expectancyR >= 0 ? '+' : ''}{summary.expectancyR.toFixed(2)}R
                </p>
              </div>
            </div>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={data} margin={{ top: 4, right: 4, left: -16, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="hsl(var(--border))" />
                <XAxis dataKey="range" tick={{ fontSize: 9, fill: 'hsl(var(--muted-foreground))' }} angle={-30} textAnchor="end" height={50} stroke="hsl(var(--border))" />
                <YAxis tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }} stroke="hsl(var(--border))" allowDecimals={false} />
                <ReferenceLine x="0R to 1R" stroke="hsl(var(--border))" strokeDasharray="2 2" />
                <Tooltip content={<HistTooltip />} cursor={{ fill: 'hsl(var(--muted) / 0.4)' }} />
                <Bar dataKey="count" radius={[3, 3, 0, 0]} maxBarSize={44}>
                  {data.map((entry, index) => (
                    <Cell key={index} fill={NEGATIVE_BUCKETS.has(entry.range) ? 'hsl(var(--destructive))' : 'hsl(var(--success))'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
            {summary.tradesWithoutRiskData > 0 && (
              <p className="text-[10px] text-muted-foreground mt-3 text-center">
                {summary.tradesWithoutRiskData} trade{summary.tradesWithoutRiskData === 1 ? '' : 's'} excluded (no stored risk amount)
              </p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}
