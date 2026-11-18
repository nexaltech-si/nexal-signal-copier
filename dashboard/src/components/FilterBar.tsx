'use client'

import { ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { X, Filter } from 'lucide-react'
import { cn } from '@/lib/utils'

interface FilterBarProps {
  children: ReactNode
  onReset?: () => void
  onApply?: () => void
  hasActiveFilters?: boolean
  showApplyButton?: boolean
  loading?: boolean
  className?: string
  compact?: boolean
}

export function FilterBar({
  children,
  onReset,
  onApply,
  hasActiveFilters = false,
  showApplyButton = false,
  loading = false,
  className,
  compact = false,
}: FilterBarProps) {
  return (
    <Card className={cn('p-3 bg-card border-border shadow-sm', className)}>
      <div className="flex flex-col md:flex-row items-stretch md:items-center gap-2">
        <div className={cn(
          'flex-1 grid gap-2',
          compact
            ? 'grid-cols-2 sm:grid-cols-2 lg:grid-cols-3'
            : 'grid-cols-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5'
        )}>
          {children}
        </div>

        <div className="flex items-center gap-1.5 justify-end md:justify-start">
          {showApplyButton && onApply && (
            <Button
              onClick={onApply}
              size="sm"
              disabled={loading}
              className="h-8 px-3 text-xs font-semibold whitespace-nowrap"
            >
              <Filter className="w-3.5 h-3.5 mr-1.5" />
              Apply
            </Button>
          )}
          {hasActiveFilters && onReset && (
            <Button
              variant="outline"
              size="sm"
              onClick={onReset}
              className="h-8 px-3 text-xs font-semibold whitespace-nowrap border-border"
            >
              <X className="h-3.5 w-3.5 mr-1.5" />
              Reset
            </Button>
          )}
        </div>
      </div>
    </Card>
  )
}

interface FilterItemProps {
  label: string
  children: ReactNode
  className?: string
}

export function FilterItem({ label, children, className }: FilterItemProps) {
  return (
    <div className={cn('space-y-1', className)}>
      <label className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">
        {label}
      </label>
      {children}
    </div>
  )
}
