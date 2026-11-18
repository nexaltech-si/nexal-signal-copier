'use client'

import { useEffect, useState } from 'react'
import { CalendarDays } from 'lucide-react'
import { cn } from '@/lib/utils'
import WidgetCard, { WidgetEmpty, WidgetSkeleton } from './WidgetCard'
import { CurrencyFlag } from '@/components/InstrumentSymbol'

/** Defensive event shape — the cache file may vary, so every field is optional. */
interface CalendarEvent {
  title?: string
  event?: string
  newsTitle?: string
  country?: string
  newsCountry?: string
  currency?: string
  impact?: string
  importance?: string
  newsImpact?: string
  date?: string
  localDate?: string
  time?: string
  localTime?: string
  datetime?: string
}

function toLocalDateKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/**
 * Local YYYY-MM-DD for an event. The raw cache stores `date` as an ISO UTC
 * timestamp, so we convert it to the viewer's local day (matching how the
 * full /calendar page groups events) rather than slicing the UTC string.
 */
function eventDateKey(e: CalendarEvent): string | null {
  // Pre-localized field wins if the API already provided it.
  if (e.localDate && /^\d{4}-\d{2}-\d{2}$/.test(e.localDate)) return e.localDate
  const raw = e.date ?? e.datetime ?? ''
  if (!raw) return null
  const parsed = new Date(raw)
  if (!Number.isNaN(parsed.getTime())) return toLocalDateKey(parsed)
  // Fallback: plain date string with no time component.
  const iso = String(raw).slice(0, 10)
  return /^\d{4}-\d{2}-\d{2}$/.test(iso) ? iso : null
}

function impactTone(raw?: string): { label: string; cls: string } {
  const v = (raw || '').toLowerCase()
  if (v.includes('high') || v === '3')
    return { label: 'High', cls: 'bg-destructive/10 border-destructive/25 text-destructive' }
  if (v.includes('med') || v === '2')
    return { label: 'Medium', cls: 'bg-gold/10 border-gold/25 text-gold' }
  return { label: 'Low', cls: 'bg-muted text-muted-foreground' }
}

export default function EconomicCalendar() {
  const [events, setEvents] = useState<CalendarEvent[] | null>(null)

  useEffect(() => {
    let cancelled = false

    // Local "today" key (YYYY-MM-DD) so we only show events for the current day.
    const todayKey = toLocalDateKey(new Date())

    fetch('/api/news-calendar')
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (cancelled) return
        const list: CalendarEvent[] = Array.isArray(data?.events) ? data.events : []
        const todays = list.filter((e) => eventDateKey(e) === todayKey)
        setEvents(todays)
      })
      .catch(() => !cancelled && setEvents([]))
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <WidgetCard
      title="Economic Calendar · Today"
      icon={<CalendarDays className="h-4 w-4" />}
      actionLabel="View calendar"
      actionHref="/calendar"
    >
      {events == null ? (
        <WidgetSkeleton lines={4} />
      ) : events.length === 0 ? (
        <WidgetEmpty message="No events scheduled today" />
      ) : (
        <div className="space-y-2">
          {events.slice(0, 6).map((e, i) => {
            const tone = impactTone(e.importance ?? e.impact ?? e.newsImpact)
            const label = e.event ?? e.title ?? e.newsTitle ?? 'Event'
            const cur = e.currency ?? e.country ?? e.newsCountry ?? ''
            const time = e.localTime ?? e.time ?? ''
            return (
              <div key={i} className="flex items-center gap-2">
                {time && (
                  <span className="text-[10px] font-mono text-muted-foreground/70 shrink-0 tabular-nums">
                    {time}
                  </span>
                )}
                {cur && (
                  <span className="flex items-center gap-1.5 shrink-0">
                    <CurrencyFlag currency={cur} size={14} />
                    <span className="text-[10px] font-bold text-foreground/80 w-8">{cur}</span>
                  </span>
                )}
                <span className="text-xs text-foreground truncate flex-1">{label}</span>
                <span
                  className={cn(
                    'text-[9px] font-bold px-1.5 py-0.5 rounded border shrink-0',
                    tone.cls,
                  )}
                >
                  {tone.label}
                </span>
              </div>
            )
          })}
        </div>
      )}
    </WidgetCard>
  )
}
