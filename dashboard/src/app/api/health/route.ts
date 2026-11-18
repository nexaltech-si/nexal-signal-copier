import { NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { auth } from '@clerk/nextjs/server'
import { requireOwner } from '@/lib/auth'

export const dynamic = 'force-dynamic'
export const revalidate = 0

export async function GET(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    // Verify authentication
    const { userId } = await auth()
    if (!userId) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    }
    // Get user settings to check disabled connections
    const userSettings = await prisma.userSettings.findFirst()
    let disabledConnections: string[] = []
    
    if (userSettings?.disabledConnections) {
      try {
        disabledConnections = JSON.parse(userSettings.disabledConnections)
      } catch {
        disabledConnections = []
      }
    }
    
    // Get latest health status from database (written by Python bot)
    const healthRecord = await prisma.systemHealth.findFirst({
      orderBy: {
        updatedAt: 'desc'
      }
    })
    
    if (!healthRecord) {
      // No health data yet - bot might not be running
      return NextResponse.json({
        success: true,
        timestamp: new Date().toISOString(),
        status: 'unknown',
        message: 'No health data available. Bot may not be running.',
        components: {},
        summary: {
          total: 0,
          healthy: 0,
          degraded: 0,
          unhealthy: 0,
          unknown: 0
        }
      })
    }
    
    // Parse components JSON
    const components = JSON.parse(healthRecord.components) as Record<string, any>
    
    // Check if data is stale (older than 5 minutes)
    const dataAge = Date.now() - new Date(healthRecord.lastCheck).getTime()
    const isStale = dataAge > 5 * 60 * 1000
    
    // Filter out disabled connections from components
    const enabledComponents = Object.entries(components)
      .filter(([name, comp]) => !disabledConnections.includes(comp.name || name))
    
    // Recalculate overall status based only on ENABLED components
    const enabledStatuses = enabledComponents.map(([, comp]) => comp.status)
    let recalculatedStatus = healthRecord.overallStatus
    
    if (!isStale && enabledComponents.length > 0) {
      if (enabledStatuses.includes('unhealthy')) {
        recalculatedStatus = 'unhealthy'
      } else if (enabledStatuses.includes('degraded')) {
        recalculatedStatus = 'degraded'
      } else if (enabledStatuses.includes('unknown')) {
        recalculatedStatus = 'partial'
      } else {
        recalculatedStatus = 'healthy'
      }
    } else if (enabledComponents.length === 0) {
      recalculatedStatus = 'unknown'
    }
    
    // Filter components to only include enabled ones
    let processedComponents = Object.fromEntries(enabledComponents)
    
    // Recalculate summary based on enabled components only
    let summary = {
      total: enabledComponents.length,
      healthy: enabledComponents.filter(([, c]) => c.status === 'healthy').length,
      degraded: enabledComponents.filter(([, c]) => c.status === 'degraded').length,
      unhealthy: enabledComponents.filter(([, c]) => c.status === 'unhealthy').length,
      unknown: enabledComponents.filter(([, c]) => c.status === 'unknown').length
    }
    
    if (isStale) {
      // Override all enabled components to show unknown status
      processedComponents = Object.fromEntries(
        enabledComponents.map(([key, value]) => [
          key,
          {
            ...value,
            status: 'unknown',
            message: `System offline - Last seen ${Math.floor(dataAge / 60000)} minutes ago`
          }
        ])
      )
      
      // Update summary for stale data
      summary = {
        total: enabledComponents.length,
        healthy: 0,
        degraded: 0,
        unhealthy: 0,
        unknown: enabledComponents.length
      }
    }
    
    const response = NextResponse.json({
      success: true,
      timestamp: new Date().toISOString(),
      status: isStale ? 'unknown' : recalculatedStatus,
      lastCheck: healthRecord.lastCheck,
      dataAge: Math.floor(dataAge / 1000), // seconds
      isStale,
      components: processedComponents,
      summary
    })
    
    // Prevent caching
    response.headers.set('Cache-Control', 'no-store, no-cache, must-revalidate, proxy-revalidate')
    response.headers.set('Pragma', 'no-cache')
    response.headers.set('Expires', '0')
    
    return response
  } catch (error: unknown) {
    console.error('Error fetching health status:', error)
    return NextResponse.json(
      {
        success: false,
        status: 'error',
        error: error instanceof Error ? error.message : 'Failed to fetch health status'
      },
      { status: 500 }
    )
  }
}
