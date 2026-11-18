'use client'

import { useState } from 'react'
import { Activity } from 'lucide-react'
import LiveStatusDisplay from '@/components/LiveStatusDisplay'
import { cn } from '@/lib/utils'

type Period = '1d' | '7d' | '30d'

export default function DashboardHeader() {
  const [period, setPeriod] = useState<Period>('7d')

  return (
    <header className="hidden md:flex sticky top-0 z-40 w-full tech-header">
      <div className="max-w-[1800px] w-full mx-auto flex h-14 items-center px-6 gap-3">
        <div className="p-1.5 rounded-lg bg-primary/10 border border-primary/20">
          <Activity className="h-5 w-5 text-primary" />
        </div>
        <LiveStatusDisplay variant="compact" className="mt-0.5" />
        <div className="flex items-center gap-1 ml-auto">
          {(['1d', '7d', '30d'] as const).map(p => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={cn(
                'h-7 px-3 rounded-md text-xs font-semibold transition-colors',
                period === p
                  ? 'bg-primary/15 text-primary border border-primary/30'
                  : 'text-muted-foreground hover:text-foreground'
              )}
            >
              {p}
            </button>
          ))}
        </div>
      </div>
    </header>
  )
}
