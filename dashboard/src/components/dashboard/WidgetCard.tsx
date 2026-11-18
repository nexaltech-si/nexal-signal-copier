'use client'

import type { ReactNode } from 'react'
import Link from 'next/link'
import { ArrowUpRight } from 'lucide-react'
import { cn } from '@/lib/utils'

interface WidgetCardProps {
  title?: string
  /** Optional action link shown top-right (e.g. "View all") */
  actionLabel?: string
  actionHref?: string
  icon?: ReactNode
  accent?: 'blue' | 'emerald' | 'rose' | 'gold'
  className?: string
  bodyClassName?: string
  children: ReactNode
}

/**
 * Shared card shell for every dashboard widget.
 * Uses the existing `.tech-card` theme system so the redesign matches the
 * current visual language rather than introducing a new palette.
 */
export default function WidgetCard({
  title,
  actionLabel,
  actionHref,
  icon,
  accent,
  className,
  bodyClassName,
  children,
}: WidgetCardProps) {
  return (
    <div
      className={cn(
        'tech-card rounded-xl p-4 md:p-5 flex flex-col',
        accent === 'blue' && 'tech-card-blue',
        accent === 'emerald' && 'tech-card-emerald',
        accent === 'rose' && 'tech-card-rose',
        accent === 'gold' && 'tech-card-gold',
        className,
      )}
    >
      {(title || actionLabel) && (
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2 min-w-0">
            {icon && <span className="text-primary shrink-0">{icon}</span>}
            {title && (
              <h3 className="text-sm font-bold text-foreground truncate">{title}</h3>
            )}
          </div>
          {actionLabel && actionHref && (
            <Link
              href={actionHref}
              className="flex items-center gap-0.5 text-[11px] font-semibold text-primary hover:text-primary/80 transition-colors shrink-0"
            >
              {actionLabel}
              <ArrowUpRight className="h-3 w-3" />
            </Link>
          )}
        </div>
      )}
      <div className={cn('flex-1', bodyClassName)}>{children}</div>
    </div>
  )
}

/** Small skeleton placeholder used while a widget's data is loading. */
export function WidgetSkeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div className="space-y-2 animate-pulse">
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className="h-3 rounded bg-muted/60"
          style={{ width: `${70 + ((i * 13) % 30)}%` }}
        />
      ))}
    </div>
  )
}

/** Consistent "no data" state so empty widgets never look broken. */
export function WidgetEmpty({ message = 'No data available' }: { message?: string }) {
  return (
    <div className="flex items-center justify-center py-6 text-xs text-muted-foreground/70 text-center">
      {message}
    </div>
  )
}
