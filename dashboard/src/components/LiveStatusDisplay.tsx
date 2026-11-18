'use client'

import { useEffect, useState } from 'react'
import { cn } from '@/lib/utils'

interface LiveStatusDisplayProps {
  className?: string
  variant?: 'default' | 'compact'
}

export default function LiveStatusDisplay({ className, variant = 'default' }: LiveStatusDisplayProps) {
  const [status, setStatus] = useState<'healthy' | 'degraded' | 'unhealthy' | 'unknown'>('unknown')
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    const fetchHealth = async () => {
      try {
        const response = await fetch('/api/health')
        if (response.ok) {
          const data = await response.json()
          setStatus(data.status || 'unknown')
        } else {
          setStatus('unhealthy')
        }
      } catch (error) {
        console.error('Failed to fetch health status:', error)
        setStatus('unhealthy')
      } finally {
        setIsLoading(false)
      }
    }

    fetchHealth()
    const interval = setInterval(fetchHealth, 30000)
    return () => clearInterval(interval)
  }, [])

  const getStatusConfig = () => {
    switch (status) {
      case 'healthy':
        return {
          dotClass: 'bg-success',
          pingClass: 'bg-success',
          textClass: 'text-success',
          label: 'ONLINE',
        }
      case 'degraded':
        return {
          dotClass: 'bg-gold',
          pingClass: 'bg-gold',
          textClass: 'text-gold',
          label: 'DEGRADED',
        }
      case 'unhealthy':
        return {
          dotClass: 'bg-destructive',
          pingClass: 'bg-destructive',
          textClass: 'text-destructive',
          label: 'OFFLINE',
        }
      default:
        return {
          dotClass: 'bg-muted-foreground/50',
          pingClass: 'bg-muted-foreground/50',
          textClass: 'text-muted-foreground',
          label: 'UNKNOWN',
        }
    }
  }

  const config = getStatusConfig()

  if (variant === 'compact') {
    return (
      <div className={cn("flex items-center gap-1.5", className)}>
        <span className={cn(
          "w-1.5 h-1.5 rounded-full flex-shrink-0",
          config.dotClass,
        )} />
        <span className={cn("font-mono text-[9px] font-semibold tracking-[0.12em]", config.textClass)}>
          {config.label}
        </span>
      </div>
    )
  }

  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <div className="relative flex items-center justify-center">
        <div className={cn("w-2 h-2 rounded-full", config.dotClass)} />
      </div>
      <p className={cn("text-[15px] font-semibold tracking-tight", config.textClass)}>
        System {status === 'healthy' ? 'Online' : status === 'degraded' ? 'Degraded' : status === 'unhealthy' ? 'Offline' : 'Unknown'}
      </p>
    </div>
  )
}
