'use client'

import { useEffect, useState } from 'react'
import { cn } from '@/lib/utils'

interface SystemStatusProps {
  collapsed?: boolean
}

export default function SystemStatus({ collapsed = false }: SystemStatusProps) {
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
          color: 'bg-emerald-500',
          bgGradient: 'from-emerald-50 to-emerald-100/50',
          textColor: 'text-success',
          label: 'System Online',
        }
      case 'degraded':
        return {
          color: 'bg-yellow-500',
          bgGradient: 'from-yellow-50 to-yellow-100/50',
          textColor: 'text-yellow-900',
          label: 'System Degraded',
        }
      case 'unhealthy':
        return {
          color: 'bg-red-500',
          bgGradient: 'from-red-50 to-red-100/50',
          textColor: 'text-red-900',
          label: 'System Offline',
        }
      default:
        return {
          color: 'bg-gray-500',
          bgGradient: 'from-gray-50 to-gray-100/50',
          textColor: 'text-gray-900',
          label: 'Status Unknown',
        }
    }
  }

  const config = getStatusConfig()

  if (collapsed) {
    return (
      <div className="flex justify-center">
        <div className={cn('w-2 h-2 rounded-full', config.color, !isLoading && 'animate-pulse')} />
      </div>
    )
  }

  return (
    <div className={cn('flex items-center justify-between p-3 rounded-lg bg-gradient-to-r', config.bgGradient)}>
      <div className="flex items-center space-x-2">
        <div className={cn('w-2 h-2 rounded-full', config.color, !isLoading && 'animate-pulse')} />
        <span className={cn('text-sm font-medium', config.textColor)}>{config.label}</span>
      </div>
    </div>
  )
}
