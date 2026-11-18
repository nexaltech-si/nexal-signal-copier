'use client'

import { useMemo, useState } from 'react'
import { formatCurrency } from '@/lib/utils'

interface ClosedTrade {
  profit: number
  time_close: string | number
}

const RANGES = [
  { key: '7D', days: 7 },
  { key: '30D', days: 30 },
  { key: '90D', days: 90 },
  { key: 'All', days: 0 },
] as const
type RangeKey = typeof RANGES[number]['key']

const DAY = 86_400_000
const closeTime = (t: ClosedTrade) => new Date(typeof t.time_close === 'number' ? t.time_close * 1000 : t.time_close).getTime()
const startOfDay = (ts: number) => { const d = new Date(ts); d.setHours(0, 0, 0, 0); return d.getTime() }
const fmtDay = (ts: number) => new Date(ts).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
const signed = (v: number) => `${v >= 0 ? '+' : ''}${formatCurrency(v)}`

interface Bucket { label: string; value: number }

/**
 * Compact realized-P/L strip: headline number + P/L bars per day (7D/30D) or
 * per week/month (90D/All). Tapping a bar swaps the headline for that bucket.
 */
export default function MobilePerformance({ history }: { history: ClosedTrade[] }) {
  const [range, setRange] = useState<RangeKey>('30D')
  const [active, setActive] = useState<number | null>(null)

  const { buckets, net, count } = useMemo(() => {
    const days = RANGES.find(r => r.key === range)!.days
    const today = startOfDay(Date.now())
    const trades = history
      .map(t => ({ ts: closeTime(t), profit: t.profit }))
      .filter(t => Number.isFinite(t.ts))
    const first = trades.length ? Math.min(...trades.map(t => t.ts)) : today
    const from = days ? today - (days - 1) * DAY : startOfDay(first)
    const inRange = trades.filter(t => t.ts >= from)

    // Bucket width keeps bars legible at phone width: daily up to 30 bars, else weekly, else monthly
    const span = Math.round((today - from) / DAY) + 1
    const size = span <= 31 ? 1 : span <= 182 ? 7 : 30
    const n = Math.ceil(span / size)
    const out: Bucket[] = Array.from({ length: n }, (_, i) => {
      const start = from + i * size * DAY
      const end = Math.min(start + (size - 1) * DAY, today)
      return { label: size === 1 ? fmtDay(start) : `${fmtDay(start)} – ${fmtDay(end)}`, value: 0 }
    })
    for (const t of inRange) {
      const i = Math.min(n - 1, Math.floor((startOfDay(t.ts) - from) / DAY / size))
      if (i >= 0) out[i].value += t.profit
    }
    return { buckets: out, net: inRange.reduce((s, t) => s + t.profit, 0), count: inRange.length }
  }, [history, range])

  const maxUp = Math.max(0, ...buckets.map(b => b.value))
  const maxDown = Math.max(0, ...buckets.map(b => -b.value))
  const scale = maxUp + maxDown || 1
  const zero = maxUp + maxDown ? (maxUp / scale) * 100 : 50 // baseline position, % from top

  const shown = active !== null ? buckets[active] : null
  const headline = shown ? shown.value : net

  return (
    <section aria-label="Performance" className="px-1">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-foreground">Performance</h2>
        <div className="-mr-2 flex" role="tablist" aria-label="Performance period">
          {RANGES.map(r => (
            <button
              key={r.key}
              type="button"
              role="tab"
              aria-selected={range === r.key}
              onClick={() => { setRange(r.key); setActive(null) }}
              className={`h-8 px-2 text-xs font-semibold transition-colors ${range === r.key ? 'text-foreground' : 'text-muted-foreground/70'}`}
            >
              {r.key}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-1 flex items-center gap-4">
        <div className="w-[8.5rem] shrink-0">
          <p className={`font-mono text-xl font-bold tabular-nums tracking-tight ${headline >= 0 ? 'text-success' : 'text-destructive'}`}>
            {signed(headline)}
          </p>
          <p className="truncate text-[11px] text-muted-foreground">
            {shown ? shown.label : `Realized · ${count} trade${count !== 1 ? 's' : ''}`}
          </p>
        </div>

        <div
          className="relative flex h-11 min-w-0 flex-1 items-stretch gap-[2px]"
          onPointerLeave={() => setActive(null)}
          role="img"
          aria-label={`Realized P/L ${signed(net)} over ${range}`}
        >
          <div className="pointer-events-none absolute inset-x-0 border-t border-border" style={{ top: `${zero}%` }} />
          {count > 0 && buckets.map((b, i) => {
            const h = (Math.abs(b.value) / scale) * 100
            const up = b.value >= 0
            return (
              <button
                key={i}
                type="button"
                aria-label={`${b.label}: ${signed(b.value)}`}
                onPointerEnter={() => setActive(i)}
                onClick={() => setActive(active === i ? null : i)}
                className="relative min-w-0 flex-1"
              >
                {b.value !== 0 && (
                  <span
                    className={`absolute inset-x-0 ${up ? 'rounded-t-[2px] bg-success' : 'rounded-b-[2px] bg-destructive'} ${active !== null && active !== i ? 'opacity-40' : ''}`}
                    style={up
                      ? { bottom: `${100 - zero}%`, height: `max(${h}%, 2px)` }
                      : { top: `${zero}%`, height: `max(${h}%, 2px)` }}
                  />
                )}
              </button>
            )
          })}
        </div>
      </div>
    </section>
  )
}
