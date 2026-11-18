'use client'

import { useState } from 'react'
import { Flame } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { formatCurrency } from '@/lib/utils'

export interface HeatmapCell {
  hour: number
  trades: number
  profit: number
  winRate: number
}

export interface HeatmapRow {
  day: string
  hours: HeatmapCell[]
}

interface PerformanceHeatmapProps {
  data: HeatmapRow[]
}

const DAY_ABBR: Record<string, string> = {
  Sunday: 'Sun', Monday: 'Mon', Tuesday: 'Tue', Wednesday: 'Wed',
  Thursday: 'Thu', Friday: 'Fri', Saturday: 'Sat'
}

function cellStyle(cell: HeatmapCell, maxAbsProfit: number): React.CSSProperties {
  if (cell.trades === 0 || maxAbsProfit === 0) {
    return { backgroundColor: 'hsl(var(--muted) / 0.4)' }
  }
  // Gamma-boost so mid-magnitude cells are still clearly visible, not washed out.
  const intensity = Math.pow(Math.min(1, Math.abs(cell.profit) / maxAbsProfit), 0.55)
  const alpha = 0.22 + intensity * 0.72
  const varName = cell.profit >= 0 ? '--success' : '--destructive'
  return { backgroundColor: `hsl(var(${varName}) / ${alpha})` }
}

export default function PerformanceHeatmap({ data }: PerformanceHeatmapProps) {
  const [hovered, setHovered] = useState<{ day: string; cell: HeatmapCell } | null>(null)

  const maxAbsProfit = data.reduce((max, row) =>
    row.hours.reduce((m, c) => Math.max(m, Math.abs(c.profit)), max), 0)
  const totalTrades = data.reduce((sum, row) => sum + row.hours.reduce((s, c) => s + c.trades, 0), 0)

  const bestCell = data.reduce<{ day: string; cell: HeatmapCell } | null>((best, row) => {
    return row.hours.reduce((b, cell) => {
      if (cell.trades === 0) return b
      if (!b || cell.profit > b.cell.profit) return { day: row.day, cell }
      return b
    }, best)
  }, null)

  return (
    <Card className="border border-border shadow-sm bg-card overflow-hidden">
      <CardHeader className="py-3.5 px-5 flex flex-row items-center justify-between gap-3 border-b bg-muted/40">
        <CardTitle className="text-sm font-bold flex items-center gap-2 text-foreground">
          <Flame className="h-4 w-4 text-primary" />
          When You Trade Best
        </CardTitle>
        {bestCell && (
          <span className="text-[11px] font-semibold text-muted-foreground">
            Peak session: <span className="text-success font-bold">{DAY_ABBR[bestCell.day]} {bestCell.cell.hour.toString().padStart(2, '0')}:00</span>
            {' '}({formatCurrency(bestCell.cell.profit)})
          </span>
        )}
      </CardHeader>
      <CardContent className="p-5">
        {totalTrades === 0 ? (
          <div className="h-[260px] flex items-center justify-center text-sm text-muted-foreground">
            No trade timing data available yet
          </div>
        ) : (
          <div className="overflow-x-auto">
            <div className="min-w-[720px]">
              <div className="grid mb-1.5" style={{ gridTemplateColumns: '36px repeat(24, 1fr)' }}>
                <div />
                {Array.from({ length: 24 }, (_, h) => (
                  <div key={h} className="text-center text-[9px] font-semibold text-muted-foreground/60">
                    {h % 2 === 0 ? h : ''}
                  </div>
                ))}
              </div>
              <div className="flex flex-col gap-1">
                {data.map((row) => (
                  <div key={row.day} className="grid items-center" style={{ gridTemplateColumns: '36px repeat(24, 1fr)' }}>
                    <span className="text-[11px] font-bold text-muted-foreground pr-2 text-right">
                      {DAY_ABBR[row.day]}
                    </span>
                    {row.hours.map((cell) => (
                      <div key={cell.hour} className="px-[1.5px]">
                        <div
                          className="aspect-square rounded transition-transform hover:scale-[1.35] hover:z-10 relative"
                          style={cellStyle(cell, maxAbsProfit)}
                          onMouseEnter={() => setHovered({ day: row.day, cell })}
                          onMouseLeave={() => setHovered(null)}
                        />
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </div>

            <div className="flex items-center justify-between mt-4 pt-3 border-t border-border/60">
              <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                <span>Loss</span>
                <div className="flex gap-0.5">
                  {[0.85, 0.55, 0.3].map((a) => (
                    <div key={`l${a}`} className="h-3 w-3 rounded-sm" style={{ backgroundColor: `hsl(var(--destructive) / ${a})` }} />
                  ))}
                  <div className="h-3 w-3 rounded-sm" style={{ backgroundColor: 'hsl(var(--muted) / 0.4)' }} />
                  {[0.3, 0.55, 0.85].map((a) => (
                    <div key={`p${a}`} className="h-3 w-3 rounded-sm" style={{ backgroundColor: `hsl(var(--success) / ${a})` }} />
                  ))}
                </div>
                <span>Profit</span>
              </div>
              <div className="text-[11px] font-semibold h-4">
                {hovered ? (
                  <span>
                    <span className="font-bold text-foreground">{DAY_ABBR[hovered.day]} {hovered.cell.hour.toString().padStart(2, '0')}:00</span>
                    {' — '}
                    <span className={hovered.cell.profit >= 0 ? 'text-success font-bold' : 'text-destructive font-bold'}>
                      {formatCurrency(hovered.cell.profit)}
                    </span>
                    <span className="text-muted-foreground"> · {hovered.cell.trades} trade{hovered.cell.trades === 1 ? '' : 's'} · {hovered.cell.winRate.toFixed(0)}% win</span>
                  </span>
                ) : (
                  <span className="text-muted-foreground">{totalTrades} trades plotted — hover a cell for detail</span>
                )}
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
