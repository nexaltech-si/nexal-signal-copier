'use client'

import { useEffect, useRef } from 'react'
import { useRouter } from 'next/navigation'

interface AutoVerifyWrapperProps {
  children: React.ReactNode
  unverifiedCount: number
}

/**
 * Wrapper component that automatically triggers AI verification
 * for unverified signals when the dashboard loads
 */
export default function AutoVerifyWrapper({ children, unverifiedCount }: AutoVerifyWrapperProps) {
  const router = useRouter()
  const hasAutoVerified = useRef(false)

  useEffect(() => {
    // Only run once per page load
    if (hasAutoVerified.current || unverifiedCount === 0) {
      return
    }

    // Check if auto-verification is enabled
    const autoVerify = async () => {
      try {
        // First check if it's enabled
        const statusRes = await fetch('/api/signals/auto-verify')
        const status = await statusRes.json()
        
        if (!status.enabled) {
          console.log('Auto-verification is disabled')
          return
        }

        if (status.unverifiedCount === 0) {
          console.log('No signals to verify')
          return
        }

        console.log(`🤖 Auto-verifying ${status.unverifiedCount} signals...`)
        
        // Trigger auto-verification
        const verifyRes = await fetch('/api/signals/auto-verify', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ limit: 10 }) // Verify up to 10 at a time
        })

        const result = await verifyRes.json()
        
        if (result.success && result.verified > 0) {
          console.log(`✅ Auto-verified ${result.verified} signals`)
          // Refresh the page to show updated data
          router.refresh()
        }
      } catch (error) {
        console.error('Auto-verification error:', error)
      }
    }

    hasAutoVerified.current = true
    autoVerify()
  }, [unverifiedCount, router])

  return <>{children}</>
}
