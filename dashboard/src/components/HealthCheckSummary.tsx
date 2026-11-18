'use client'

import { Badge } from '@/components/ui/badge'
import { CheckCircle2, AlertCircle, AlertTriangle, HelpCircle } from 'lucide-react'
import type { HealthCheckData } from '@/lib/types'

interface HealthCheckSummaryProps {
  healthData: HealthCheckData
}

const STATUS_CONFIG = {
  healthy: {
    icon: CheckCircle2,
    color: 'text-green-600',
    badgeVariant: 'default' as const,
    label: 'Healthy'
  },
  degraded: {
    icon: AlertTriangle,
    color: 'text-yellow-600',
    badgeVariant: 'secondary' as const,
    label: 'Degraded'
  },
  unhealthy: {
    icon: AlertCircle,
    color: 'text-destructive',
    badgeVariant: 'destructive' as const,
    label: 'Unhealthy'
  },
  partial: {
    icon: AlertTriangle,
    color: 'text-orange-600',
    badgeVariant: 'secondary' as const,
    label: 'Partial'
  },
  unknown: {
    icon: HelpCircle,
    color: 'text-gray-600',
    badgeVariant: 'outline' as const,
    label: 'Unknown'
  }
}

export default function HealthCheckSummary({ healthData }: HealthCheckSummaryProps) {
  if (!healthData) {
    return (
      <div className="text-sm text-muted-foreground">
        No health data available
      </div>
    )
  }

  const overallConfig = STATUS_CONFIG[healthData.overall_status] || STATUS_CONFIG.unknown
  const OverallIcon = overallConfig.icon

  return (
    <div className="flex items-center gap-4 text-sm">
      <Badge variant={overallConfig.badgeVariant} className="flex items-center gap-1">
        <OverallIcon className="h-3 w-3" />
        {overallConfig.label}
      </Badge>
      
      <div className="flex items-center gap-3 text-muted-foreground">
        <span className="flex items-center gap-1">
          <span className="font-semibold text-green-600">{healthData.summary.healthy}</span> healthy
        </span>
        
        {healthData.summary.degraded > 0 && (
          <span className="flex items-center gap-1">
            <span className="font-semibold text-yellow-600">{healthData.summary.degraded}</span> degraded
          </span>
        )}
        
        {healthData.summary.unhealthy > 0 && (
          <span className="flex items-center gap-1">
            <span className="font-semibold text-destructive">{healthData.summary.unhealthy}</span> unhealthy
          </span>
        )}
        
        <span className="text-xs">
          {healthData.summary.total} total components
        </span>
      </div>
    </div>
  )
}
