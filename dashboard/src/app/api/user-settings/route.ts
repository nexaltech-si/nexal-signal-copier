import { NextRequest, NextResponse } from 'next/server'
import { auth } from '@clerk/nextjs/server'
import { prisma } from '@/lib/prisma'
import { requireOwner } from '@/lib/auth'

export async function GET(request: NextRequest) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const { userId } = await auth()
    
    if (!userId) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    }

    let settings = await prisma.userSettings.findUnique({
      where: { userId }
    })

    // Create default settings if they don't exist
    if (!settings) {
      settings = await prisma.userSettings.create({
        data: {
          userId,
          smartCloseEnabled: true,
          smartClosePercentage: 50.0,
          smartCloseSetBreakeven: true,
          defaultRefreshInterval: 5,
          notificationsEnabled: true,
          tradeNotificationsEnabled: true,
          systemNotificationsEnabled: true,
          errorNotificationsEnabled: true,
          debugModeEnabled: false,
          consoleLogsEnabled: false,
          disabledConnections: '[]',
          newsShareConfig: '{}',
        }
      })
    }

    return NextResponse.json(settings)
  } catch (error) {
    console.error('Error fetching user settings:', error)
    return NextResponse.json({ error: 'Failed to fetch settings' }, { status: 500 })
  }
}

export async function PUT(request: NextRequest) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const { userId } = await auth()
    
    if (!userId) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    }

    const body = await request.json()
    
    const settings = await prisma.userSettings.upsert({
      where: { userId },
      update: {
        smartCloseEnabled: body.smartCloseEnabled,
        smartClosePercentage: body.smartClosePercentage,
        smartCloseSetBreakeven: body.smartCloseSetBreakeven,
        defaultRefreshInterval: body.defaultRefreshInterval,
        notificationsEnabled: body.notificationsEnabled,
        tradeNotificationsEnabled: body.tradeNotificationsEnabled,
        systemNotificationsEnabled: body.systemNotificationsEnabled,
        errorNotificationsEnabled: body.errorNotificationsEnabled,
        debugModeEnabled: body.debugModeEnabled,
        consoleLogsEnabled: body.consoleLogsEnabled,
        disabledConnections: body.disabledConnections,
        ...(body.newsShareConfig !== undefined && { newsShareConfig: body.newsShareConfig }),
      },
      create: {
        userId,
        smartCloseEnabled: body.smartCloseEnabled ?? true,
        smartClosePercentage: body.smartClosePercentage ?? 50.0,
        smartCloseSetBreakeven: body.smartCloseSetBreakeven ?? true,
        defaultRefreshInterval: body.defaultRefreshInterval ?? 5,
        notificationsEnabled: body.notificationsEnabled ?? true,
        tradeNotificationsEnabled: body.tradeNotificationsEnabled ?? true,
        systemNotificationsEnabled: body.systemNotificationsEnabled ?? true,
        errorNotificationsEnabled: body.errorNotificationsEnabled ?? true,
        debugModeEnabled: body.debugModeEnabled ?? false,
        consoleLogsEnabled: body.consoleLogsEnabled ?? false,
        disabledConnections: body.disabledConnections ?? '[]',
        newsShareConfig: body.newsShareConfig ?? '{}',
      }
    })

    return NextResponse.json(settings)
  } catch (error) {
    console.error('Error updating user settings:', error)
    return NextResponse.json({ error: 'Failed to update settings' }, { status: 500 })
  }
}
