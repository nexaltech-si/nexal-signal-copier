import { NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { requireOwner } from '@/lib/auth'

export async function GET() {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    // Get overall statistics
    const [totalSignals, totalTrades, totalActions, activeTrades, closedTrades] = await Promise.all([
      prisma.signal.count(),
      prisma.trade.count(),
      prisma.tradeAction.count(),
      prisma.trade.count({ where: { status: 'EXECUTED' } }),
      prisma.trade.count({ where: { status: 'CLOSED' } }),
    ])

    // Get profit/loss summary
    const profitLossData = await prisma.trade.aggregate({
      where: {
        status: 'CLOSED',
        profitLoss: { not: null },
      },
      _sum: {
        profitLoss: true,
      },
      _avg: {
        profitLoss: true,
      },
      _count: true,
    })

    // Get win rate
    const winningTrades = await prisma.trade.count({
      where: {
        status: 'CLOSED',
        profitLoss: { gt: 0 },
      },
    })

    const losingTrades = await prisma.trade.count({
      where: {
        status: 'CLOSED',
        profitLoss: { lt: 0 },
      },
    })

    const winRate = closedTrades > 0 ? (winningTrades / closedTrades) * 100 : 0

    // Get recent sessions
    const recentSessions = await prisma.tradingSession.findMany({
      orderBy: {
        startedAt: 'desc',
      },
      take: 5,
    })

    // Get trades by symbol
    const tradesBySymbol = await prisma.trade.groupBy({
      by: ['symbol'],
      _count: {
        symbol: true,
      },
      _sum: {
        profitLoss: true,
      },
      orderBy: {
        _count: {
          symbol: 'desc',
        },
      },
      take: 10,
    })

    // Get daily performance
    const thirtyDaysAgo = new Date()
    thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30)

    const dailyTrades = await prisma.trade.findMany({
      where: {
        closedAt: {
          gte: thirtyDaysAgo,
        },
        status: 'CLOSED',
      },
      select: {
        closedAt: true,
        profitLoss: true,
      },
    })

    // Group by day
    const dailyPerformance = dailyTrades.reduce((acc: Record<string, { date: string; profit: number; trades: number }>, trade) => {
      if (!trade.closedAt || trade.profitLoss === null) return acc
      const date = trade.closedAt.toISOString().split('T')[0]
      if (!acc[date]) {
        acc[date] = { date, profit: 0, trades: 0 }
      }
      acc[date].profit += trade.profitLoss
      acc[date].trades += 1
      return acc
    }, {})

    return NextResponse.json({
      totalSignals,
      totalTrades,
      totalActions,
      activeTrades,
      closedTrades,
      totalProfitLoss: profitLossData._sum.profitLoss || 0,
      averageProfitLoss: profitLossData._avg.profitLoss || 0,
      winningTrades,
      losingTrades,
      winRate,
      recentSessions,
      tradesBySymbol,
      dailyPerformance: Object.values(dailyPerformance),
    })
  } catch (error) {
    console.error('Error fetching stats:', error)
    return NextResponse.json(
      { error: 'Failed to fetch statistics' },
      { status: 500 }
    )
  }
}
