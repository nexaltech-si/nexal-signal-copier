'use client'

import { Clock } from 'lucide-react'
import { cn } from '@/lib/utils'
import WidgetCard, { WidgetEmpty } from './WidgetCard'

export interface ActivityItem {
  type: string
  symbol: string
  at: string
  detail?: string | null
}

export default function RecentActivity({ items }: { items: ActivityItem[] }) {
  return (
    <WidgetCard
      title="Recent Activity"
      icon={<Clock className="h-4 w-4" />}
      actionLabel="View all"
      actionHref="/history"
    >
      {items.length === 0 ? (
        <WidgetEmpty message="No recent activity" />
      ) : (
        <div className="space-y-2.5">
          {items.slice(0, 6).map((a, i) => (
            <div key={i} className="flex items-center gap-2.5">
              <span
                className={cn(
                  'text-[9px] font-black px-1.5 py-0.5 rounded border shrink-0 uppercase',
                  'bg-gold/10 border-gold/25 text-gold',
                )}
              >
                {a.type}
              </span>
              <span className="text-xs font-semibold text-foreground">{a.symbol}</span>
              {a.detail && (
                <span className="text-[11px] text-muted-foreground truncate">{a.detail}</span>
              )}
              <span className="text-[10px] text-muted-foreground/60 font-mono ml-auto shrink-0">
                {a.at}
              </span>
            </div>
          ))}
        </div>
      )}
    </WidgetCard>
  )
}
