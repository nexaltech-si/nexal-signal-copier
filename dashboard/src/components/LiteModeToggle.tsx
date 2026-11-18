'use client'

import { Zap, ZapOff } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useLiteMode } from '@/hooks/useLiteMode'

export default function LiteModeToggle({
  className,
  size = 'default',
}: {
  className?: string
  size?: 'default' | 'sm' | 'xs'
}) {
  const { enabled, toggle } = useLiteMode()

  return (
    <button
      onClick={toggle}
      aria-label={enabled ? 'Show full navigation' : 'Show lite navigation'}
      aria-pressed={enabled}
      title={enabled ? 'Lite mode on — click for full menu' : 'Lite mode off — click to simplify menu'}
      className={cn(
        'relative flex items-center justify-center rounded-full transition-all duration-200 ease-in-out',
        'hover:bg-accent border',
        enabled ? 'border-gold/40 bg-gold/10' : 'border-border',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
        size === 'xs' ? 'h-7 w-7' : size === 'sm' ? 'h-8 w-8' : 'h-9 w-9',
        className,
      )}
    >
      <Zap className={cn(
        'h-3.5 w-3.5 text-gold absolute transition-all duration-300',
        enabled ? 'scale-100 opacity-100' : 'scale-0 opacity-0'
      )} />
      <ZapOff className={cn(
        'h-3.5 w-3.5 text-muted-foreground absolute transition-all duration-300',
        enabled ? 'scale-0 opacity-0' : 'scale-100 opacity-100'
      )} />
    </button>
  )
}
