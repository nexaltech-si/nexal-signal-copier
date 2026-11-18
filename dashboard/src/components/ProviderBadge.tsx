'use client'

import { useEffect, useState } from 'react'
import { Server, Cloud } from 'lucide-react'
import { cn } from '@/lib/utils'

interface ProviderInfo {
  label: string
  ismt5rest: boolean
}

interface ProviderBadgeProps {
  collapsed?: boolean
  className?: string
}

export default function ProviderBadge({ collapsed = false, className }: ProviderBadgeProps) {
  const [provider, setProvider] = useState<ProviderInfo | null>(null)

  useEffect(() => {
    const fetchProvider = async () => {
      try {
        const res = await fetch('/api/provider')
        const data = await res.json()
        setProvider({ label: data.label, ismt5rest: data.ismt5rest })
      } catch (error) {
        console.error('Error fetching provider:', error)
      }
    }
    fetchProvider()
  }, [])

  if (!provider) return null

  if (collapsed) {
    return (
      <div className={cn('flex justify-center group relative', className)}>
        {provider.ismt5rest ? (
          <Server className="h-3.5 w-3.5 text-primary" />
        ) : (
          <Cloud className="h-3.5 w-3.5 text-muted-foreground" />
        )}
        <div className="absolute left-full ml-2 px-2 py-1 bg-card border border-border text-foreground text-xs font-mono rounded shadow-lg shadow-black/40 opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity whitespace-nowrap z-50">
          {provider.label}
        </div>
      </div>
    )
  }

  return (
    <div className={cn(
      'flex items-center gap-1.5 rounded px-2 py-1 text-[10px] font-semibold tracking-wide uppercase',
      provider.ismt5rest
        ? 'bg-primary/10 border border-primary/20 text-primary'
        : 'bg-accent border border-border text-muted-foreground',
      className
    )}>
      {provider.ismt5rest ? (
        <Server className="h-3 w-3 flex-shrink-0" />
      ) : (
        <Cloud className="h-3 w-3 flex-shrink-0" />
      )}
      <span className="truncate">{provider.ismt5rest ? 'MT5 REST' : 'MetaAPI'}</span>
    </div>
  )
}
