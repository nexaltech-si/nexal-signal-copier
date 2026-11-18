'use client'

import { ReactNode } from 'react'
import { Zap, Clock } from 'lucide-react'
import LiveStatusDisplay from './LiveStatusDisplay'

interface MobilePageHeaderProps {
  title?: string
  subtitle?: string
  icon?: ReactNode
  hidden?: boolean
  smartCloseConfig?: {
    enabled: boolean
    percentage: number
    setBreakeven: boolean
  }
  refreshInterval?: number
}

export default function MobilePageHeader({
  title,
  subtitle,
  icon,
  hidden,
  smartCloseConfig,
  refreshInterval
}: MobilePageHeaderProps) {
  if (hidden) {
    return <div className="md:hidden pt-[80px] pb-2" />
  }

  return (
    <div className="md:hidden pt-[80px] pb-2 pl-1.5 pr-4 flex flex-col gap-1">
      {/* Page title section */}
      <div className="flex items-center gap-3 mb-2 ml-1.5">
        {icon && (
          <div className="p-1.5 rounded-lg bg-primary/10 border border-primary/20">
            {icon}
          </div>
        )}
        <h1 className="text-[38px] font-black text-foreground tracking-[-0.05em] leading-[0.95]">{title}</h1>
      </div>
      {subtitle && (
        <div className="ml-1.5 mb-3">
          {subtitle === 'Live Monitor' ? (
            <LiveStatusDisplay />
          ) : (
            <div className="flex items-center gap-2.5 group">
              <div className="relative flex items-center justify-center">
                <span className="w-2.5 h-2.5 bg-border rounded-full" />
              </div>
              <p className="text-[16px] text-muted-foreground font-medium">{subtitle}</p>
            </div>
          )}
        </div>
      )}

      {/* Smart Close & Refresh Interval Info */}
      <div className="ml-1.5 flex flex-wrap gap-2">
        {smartCloseConfig && (
          <div className="flex items-center gap-1.5 px-2 py-1 bg-gold/10 rounded-md border border-gold/20">
            <Zap className="h-3 w-3 text-gold" />
            <span className="text-[11px] font-semibold text-gold">
              Smart Close: {smartCloseConfig.enabled ? `${smartCloseConfig.percentage}%${smartCloseConfig.setBreakeven ? '+BE' : ''}` : 'Off'}
            </span>
          </div>
        )}
        {refreshInterval && (
          <div className="flex items-center gap-1.5 px-2 py-1 bg-primary/10 rounded-md border border-primary/20">
            <Clock className="h-3 w-3 text-primary" />
            <span className="text-[11px] font-semibold text-primary">
              Refresh: {refreshInterval}s
            </span>
          </div>
        )}
      </div>
    </div>
  )
}
