'use client'

import { useState, useEffect } from 'react'
import { Badge } from '@/components/ui/badge'
import { CheckCircle2, AlertCircle, AlertTriangle, HelpCircle, Clock } from 'lucide-react'
import type { HealthCheckData } from '@/lib/types'

interface HealthCheckCardProps {
  healthData: HealthCheckData
}

const STATUS_CONFIG = {
  healthy: {
    icon: CheckCircle2,
    color: 'text-green-600',
    bgColor: 'bg-green-100',
    badgeVariant: 'default' as const,
    label: 'Healthy'
  },
  degraded: {
    icon: AlertTriangle,
    color: 'text-yellow-600',
    bgColor: 'bg-yellow-100',
    badgeVariant: 'secondary' as const,
    label: 'Degraded'
  },
  unhealthy: {
    icon: AlertCircle,
    color: 'text-destructive',
    bgColor: 'bg-red-100',
    badgeVariant: 'destructive' as const,
    label: 'Unhealthy'
  },
  partial: {
    icon: AlertTriangle,
    color: 'text-orange-600',
    bgColor: 'bg-orange-100',
    badgeVariant: 'secondary' as const,
    label: 'Partial'
  },
  unknown: {
    icon: HelpCircle,
    color: 'text-gray-600',
    bgColor: 'bg-gray-100',
    badgeVariant: 'outline' as const,
    label: 'Unknown'
  }
}

export default function HealthCheckCard({ healthData }: HealthCheckCardProps) {
  const [timeAgo, setTimeAgo] = useState<string>('')
  const [isMounted, setIsMounted] = useState(false)

  const formatTime = (isoString: string | null) => {
    if (!isoString) return 'Never'
    const date = new Date(isoString)
    const now = new Date()
    const diff = now.getTime() - date.getTime()
    const seconds = Math.floor(diff / 1000)
    
    if (seconds < 60) return `${seconds}s ago`
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
    return `${Math.floor(seconds / 86400)}d ago`
  }

  // Update time display on client only to avoid hydration mismatch
  useEffect(() => {
    setIsMounted(true)
    if (healthData?.last_check) {
      setTimeAgo(formatTime(healthData.last_check))
      
      // Update every 10 seconds instead of every second to reduce re-renders
      const interval = setInterval(() => {
        setTimeAgo(formatTime(healthData.last_check))
      }, 10000)
      
      return () => clearInterval(interval)
    }
  }, [healthData?.last_check])

  if (!healthData) {
    return (
      <div className="rounded-lg border bg-card px-3 py-2 text-xs text-muted-foreground">
        No health data available
      </div>
    )
  }

  const overallConfig = STATUS_CONFIG[healthData.overall_status] || STATUS_CONFIG.unknown
  const OverallIcon = overallConfig.icon

  return (
    <div className="rounded-lg border bg-card shadow-sm">
      <div className="flex items-center justify-between px-3 py-2.5 border-b bg-muted/40">
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold text-foreground">System Health</span>
          <Badge variant={overallConfig.badgeVariant} className="flex items-center gap-1 h-4 text-[10px] px-1.5 font-semibold">
            <OverallIcon className="h-2.5 w-2.5" />
            {overallConfig.label}
          </Badge>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span className="font-semibold">{healthData.summary.total} total</span>
            <span className="text-success font-semibold">{healthData.summary.healthy} healthy</span>
            {healthData.summary.degraded > 0 && (
              <span className="text-gold font-semibold">{healthData.summary.degraded} degraded</span>
            )}
            {healthData.summary.unhealthy > 0 && (
              <span className="text-destructive font-semibold">{healthData.summary.unhealthy} unhealthy</span>
            )}
          </div>
          <div className="flex items-center gap-1 text-[10px] text-muted-foreground font-medium" suppressHydrationWarning>
            <Clock className="h-3 w-3" />
            {isMounted ? timeAgo : '...'}
          </div>
        </div>
      </div>

      <div className="p-2 grid gap-1.5 grid-cols-2 md:grid-cols-3 lg:grid-cols-4">
        {Object.entries(healthData.components).map(([name, component]) => {
          const config = STATUS_CONFIG[component.status] || STATUS_CONFIG.unknown
          const Icon = config.icon

          return (
            <div
              key={name}
              className={`px-2 py-1.5 rounded-md border ${config.bgColor}`}
            >
              <div className="flex items-center justify-between mb-0.5">
                <div className="flex items-center gap-1">
                  <Icon className={`h-3 w-3 ${config.color}`} />
                  <span className="text-xs font-semibold text-foreground">{component.name}</span>
                </div>
                <Badge variant={config.badgeVariant} className="h-3.5 text-[9px] px-1 leading-none font-semibold">
                  {config.label}
                </Badge>
              </div>
              <p className="text-[10px] text-muted-foreground leading-tight truncate font-medium">{component.message}</p>
              <div className="flex items-center justify-between mt-0.5 text-[10px] text-muted-foreground font-medium">
                {component.response_time_ms ? (
                  <span>⚡ {component.response_time_ms}ms</span>
                ) : <span />}
                {component.details && (
                  <span>
                    {Object.entries(component.details).slice(0, 1).map(([key, value]) => (
                      <span key={key}>{key}: {typeof value === 'number' ? value.toFixed(2) : String(value)}</span>
                    ))}
                  </span>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
