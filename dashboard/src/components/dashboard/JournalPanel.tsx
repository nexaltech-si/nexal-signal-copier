'use client'

import { useEffect, useState } from 'react'
import { BookOpen } from 'lucide-react'
import WidgetCard, { WidgetEmpty, WidgetSkeleton } from './WidgetCard'

interface JournalEntry {
  notes: string
  tags: string[]
}

export default function JournalPanel() {
  const [entries, setEntries] = useState<JournalEntry[] | null>(null)

  useEffect(() => {
    let cancelled = false
    fetch('/api/trade-journal')
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (cancelled) return
        // API returns a { [tradeId]: {notes, tags} } map.
        const list = data && typeof data === 'object' ? Object.values(data) : []
        setEntries(list as JournalEntry[])
      })
      .catch(() => !cancelled && setEntries([]))
    return () => {
      cancelled = true
    }
  }, [])

  // Aggregate the most-used tags across entries.
  const tagCounts: Record<string, number> = {}
  ;(entries ?? []).forEach((e) =>
    (e.tags || []).forEach((t) => (tagCounts[t] = (tagCounts[t] || 0) + 1)),
  )
  const topTags = Object.entries(tagCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6)

  return (
    <WidgetCard
      title="Journal Overview"
      icon={<BookOpen className="h-4 w-4" />}
      actionLabel="View journal"
      actionHref="/journal"
    >
      {entries == null ? (
        <WidgetSkeleton lines={3} />
      ) : entries.length === 0 ? (
        <WidgetEmpty message="No journal entries yet" />
      ) : (
        <div>
          <div className="flex items-center justify-between mb-3">
            <span className="tech-label">Entries</span>
            <span className="text-lg font-black text-foreground tabular-nums">
              {entries.length}
            </span>
          </div>
          {topTags.length > 0 && (
            <>
              <div className="tech-label mb-2">Top Tags</div>
              <div className="flex flex-wrap gap-1.5">
                {topTags.map(([tag, count]) => (
                  <span
                    key={tag}
                    className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-primary/10 border border-primary/20 text-primary"
                  >
                    {tag} · {count}
                  </span>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </WidgetCard>
  )
}
