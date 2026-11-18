'use client'

import { useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'

interface DashboardAutoRefreshProps {
  children: React.ReactNode
  intervalSeconds?: number
}

export default function DashboardAutoRefresh({ 
  children, 
  intervalSeconds = 30 
}: DashboardAutoRefreshProps) {
  const router = useRouter()
  const [countdown, setCountdown] = useState(intervalSeconds)


  const handleRefresh = () => {
    setCountdown(intervalSeconds)
    
    // Trigger router refresh after state updates
    setTimeout(() => {
      router.refresh()
    }, 100)
  }

  // Countdown timer
  useEffect(() => {
    const interval = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          return 0 // Set to 0 to trigger refresh in separate effect
        }
        return prev - 1
      })
    }, 1000)

    return () => clearInterval(interval)
  }, [intervalSeconds])

  // Separate effect to trigger refresh when countdown reaches 0
  useEffect(() => {
    if (countdown === 0) {
      handleRefresh()
    }
  }, [countdown, handleRefresh])

  return <>{children}</>
}
