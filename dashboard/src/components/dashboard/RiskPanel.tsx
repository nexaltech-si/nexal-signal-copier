'use client'

import { useEffect, useState } from 'react'
import { ShieldAlert } from 'lucide-react'
import { cn } from '@/lib/utils'
import WidgetCard, { WidgetSkeleton } from './WidgetCard'

interface DrawdownData {
  liveDrawdown?: {
    balance?: number
    equity?: number
    drawdownAmount?: number
    drawdownPercent?: number
    isInDrawdown?: boolean
  } | null
  limits?: {
    daily?: number | null
    overall?: number | null
  }
}

function Meter({
  label,
  used,
  limit,
  unit = '%',
}: {
  label: string
  used: number | null
  limit: number | null
  unit?: string
}) {
  const pct =
    used != null && limit != null && limit > 0
      ? Math.min(100, (Math.abs(used) / limit) * 100)
      : 0
  const danger = pct >= 80
  const warn = pct >= 50
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="tech-label">{label}</span>
        <span className="text-[11px] font-bold text-foreground tabular-nums">
          {limit != null ? `${limit}${unit}` : '—'}
        </span>
      </div>
      <div className="w-full h-2 bg-border rounded-full overflow-hidden">
        <div
          className={cn(
            'h-full rounded-full transition-all',
            danger ? 'bg-destructive' : warn ? 'bg-gold' : 'bg-success',
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="text-[9px] text-muted-foreground mt-1">
        {used != null ? `${Math.abs(used).toFixed(2)}${unit} used` : 'No data'}
      </div>
    </div>
  )
}

export default function RiskPanel() {
  const [data, setData] = useState<DrawdownData | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    fetch('/api/drawdown')
      .then((r) => (r.ok ? r.json() : null))
      .then((json) => {
        if (cancelled) return
        if (json?.data) setData(json.data)
        else setFailed(true)
      })
      .catch(() => !cancelled && setFailed(true))
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <WidgetCard
      title="Risk Management"
      icon={<ShieldAlert className="h-4 w-4" />}
      actionLabel="View risk"
      actionHref="/drawdown"
    >
      {data == null && !failed ? (
        <WidgetSkeleton lines={3} />
      ) : (
        <div className="space-y-3">
          <Meter
            label="Daily Loss Limit"
            used={data?.liveDrawdown?.drawdownPercent ?? null}
            limit={data?.limits?.daily ?? null}
          />
          <Meter
            label="Max Drawdown"
            used={data?.liveDrawdown?.drawdownPercent ?? null}
            limit={data?.limits?.overall ?? null}
          />
        </div>
      )}
    </WidgetCard>
  )
}
