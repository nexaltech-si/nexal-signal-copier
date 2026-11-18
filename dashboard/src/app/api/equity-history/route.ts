import { NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { requireOwner } from '@/lib/auth'

export const dynamic = 'force-dynamic'

/**
 * Equity History API Endpoint
 * Serves the real balance/equity time series recorded by the position monitor's
 * periodic snapshot writer, with running peak-to-trough drawdown computed per point.
 */

export async function GET(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const { searchParams } = new URL(request.url)
    const days = parseInt(searchParams.get('days') || '30')
    const dateFrom = new Date()
    dateFrom.setDate(dateFrom.getDate() - days)

    const snapshots = await prisma.equitySnapshot.findMany({
      where: { createdAt: { gte: dateFrom } },
      orderBy: { createdAt: 'asc' }
    })

    if (snapshots.length < 2) {
      return NextResponse.json({ points: [], hasEnoughData: false })
    }

    let peak = 0
    const points = snapshots.map(s => {
      peak = Math.max(peak, s.equity)
      const drawdown = peak - s.equity
      return {
        time: s.createdAt.toISOString(),
        balance: s.balance,
        equity: s.equity,
        drawdownPercent: peak > 0 ? -(drawdown / peak) * 100 : 0
      }
    })

    return NextResponse.json({ points, hasEnoughData: true })

  } catch (error: unknown) {
    console.error('Equity history API error:', error)
    return NextResponse.json(
      {
        error: 'Failed to fetch equity history',
        message: error instanceof Error ? error.message : 'Unable to fetch equity history'
      },
      { status: 500 }
    )
  }
}
