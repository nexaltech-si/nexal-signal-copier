import { NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { requireOwner } from '@/lib/auth'

export async function GET() {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    // Get unique symbols from trades
    const symbols = await prisma.trade.findMany({
      select: { symbol: true },
      distinct: ['symbol'],
      orderBy: { symbol: 'asc' },
    })

    // Get unique channels from signals
    const channels = await prisma.signal.findMany({
      select: { 
        channelId: true,
        channelName: true,
      },
      distinct: ['channelId'],
      orderBy: { channelId: 'asc' },
    })

    // Get unique action types from trade actions
    const actionTypes = await prisma.tradeAction.findMany({
      select: { actionType: true },
      distinct: ['actionType'],
      orderBy: { actionType: 'asc' },
    })

    // Get unique triggered by sources from trade actions
    const triggeredBySources = await prisma.tradeAction.findMany({
      select: { triggeredBy: true },
      distinct: ['triggeredBy'],
      orderBy: { triggeredBy: 'asc' },
    })

    // Get unique trade statuses
    const tradeStatuses = await prisma.trade.findMany({
      select: { status: true },
      distinct: ['status'],
      orderBy: { status: 'asc' },
    })

    // Get unique signal statuses
    const signalStatuses = await prisma.signal.findMany({
      select: { status: true },
      distinct: ['status'],
      orderBy: { status: 'asc' },
    })

    return NextResponse.json({
      symbols: symbols.map(s => s.symbol).filter(Boolean),
      channels: channels.map(c => ({
        id: c.channelId,
        name: c.channelName || c.channelId,
      })),
      actionTypes: actionTypes.map(a => a.actionType).filter(Boolean),
      triggeredBy: triggeredBySources.map(t => t.triggeredBy).filter(Boolean),
      tradeStatuses: tradeStatuses.map(s => s.status).filter(Boolean),
      signalStatuses: signalStatuses.map(s => s.status).filter(Boolean),
    })
  } catch (error) {
    console.error('Error fetching filter options:', error)
    return NextResponse.json(
      { error: 'Failed to fetch filter options' },
      { status: 500 }
    )
  }
}
