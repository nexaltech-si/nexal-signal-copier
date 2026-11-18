import { prisma } from './prisma'
import type { SignalWithTrades, TradeWithRelations, StatsData, DailyPerformance, TradeActionWithTrade, HealthCheckData } from './types'

export async function getStats(): Promise<StatsData | null> {
  try {
    // Get overall statistics
    const [totalSignals, totalTrades, activeTrades, closedTrades, totalActions] = await Promise.all([
      prisma.signal.count(),
      prisma.trade.count(),
      prisma.trade.count({ where: { status: 'EXECUTED' } }),
      prisma.trade.count({ where: { status: 'CLOSED' } }),
      prisma.tradeAction.count(),
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
    const dailyPerformanceMap = dailyTrades.reduce<Record<string, DailyPerformance>>((acc, trade) => {
      if (!trade.closedAt || trade.profitLoss === null) return acc
      const date = trade.closedAt.toISOString().split('T')[0]
      if (!acc[date]) {
        acc[date] = { date, profit: 0, trades: 0 }
      }
      acc[date].profit += trade.profitLoss
      acc[date].trades += 1
      return acc
    }, {})
    
    const dailyPerformance: DailyPerformance[] = Object.values(dailyPerformanceMap)

    return {
      totalSignals,
      totalTrades,
      activeTrades,
      closedTrades,
      totalActions,
      totalProfitLoss: profitLossData._sum.profitLoss || 0,
      averageProfitLoss: profitLossData._avg.profitLoss || 0,
      winningTrades,
      losingTrades,
      winRate,
      recentSessions,
      tradesBySymbol,
      dailyPerformance,
    }
  } catch (error: unknown) {
    console.error('Error fetching stats:', error instanceof Error ? error.message : error)
    return null
  }
}

export async function getSignals(limit = 20): Promise<SignalWithTrades[]> {
  try {
    const signals = await prisma.signal.findMany({
      include: {
        trades: {
          include: {
            childTrades: true,
            parentTrade: true,
            tradeActions: {
              orderBy: {
                createdAt: 'asc',
              },
            },
            marketAnalyses: {
              orderBy: {
                createdAt: 'desc',
              },
            },
          },
        },
      },
      orderBy: [
        { createdAt: 'desc' },
        { id: 'desc' },
      ],
      take: limit,
    })

    // Fetch replies for each signal
    const signalsWithReplies = await Promise.all(
      signals.map(async (signal) => {
        // Fetch replies by BOTH signalId AND by message matching
        // This ensures we get all replies even if signalId wasn't set
        const replies = await prisma.signalReply.findMany({
          where: {
            OR: [
              // Replies directly linked to signal
              { signalId: signal.id },
              // Replies to the original message (by message ID and chat)
              {
                replyToMessageId: signal.messageId,
                chatId: signal.channelId,
              },
            ],
          },
          orderBy: {
            createdAt: 'asc',
          },
          select: {
            id: true,
            createdAt: true,
            replyMessageId: true,
            replyToMessageId: true,
            replyText: true,
            userId: true,
            username: true,
            actionTaken: true,
            actionType: true,
            actionSuccess: true,
            actionResult: true,
            positionsClosed: true,
            ordersCancelled: true,
            processed: true,
            processingError: true,
            aiParsed: true,
          },
        })
        
        return {
          ...signal,
          replies,
        }
      })
    )

    return signalsWithReplies
  } catch (error: unknown) {
    console.error('Error fetching signals:', error instanceof Error ? error.message : error)
    return []
  }
}

export async function getMessageMappings() {
  try {
    const mappings = await prisma.messageMapping.findMany({
      orderBy: {
        createdAt: 'desc',
      },
      take: 50,
    })

    return mappings
  } catch (error) {
    console.error('Error fetching message mappings:', error)
    return []
  }
}

export async function getTrades(limit = 20): Promise<TradeWithRelations[]> {
  try {
    const trades = await prisma.trade.findMany({
      include: {
        signal: true,
        parentTrade: true,
        childTrades: true,
        tradeActions: {
          orderBy: [
            { createdAt: 'desc' },
            { id: 'desc' },
          ],
        },
        marketAnalyses: {
          orderBy: {
            createdAt: 'desc',
          },
        },
      },
      orderBy: [
        { createdAt: 'desc' },
        { id: 'desc' },
      ],
      take: limit,
    })

    return trades
  } catch (error: unknown) {
    console.error('Error fetching trades:', error instanceof Error ? error.message : error)
    return []
  }
}

export async function getTradeActions(limit = 50): Promise<TradeActionWithTrade[]> {
  try {
    const actions = await prisma.tradeAction.findMany({
      include: {
        trade: {
          include: {
            signal: true,
          },
        },
      },
      orderBy: [
        { createdAt: 'desc' },
        { id: 'desc' },
      ],
      take: limit,
    })

    return actions
  } catch (error: unknown) {
    console.error('Error fetching trade actions:', error instanceof Error ? error.message : error)
    return []
  }
}

export async function getHealthCheck(): Promise<HealthCheckData> {
  try {
    // Get the latest health check record
    const healthRecord = await prisma.systemHealth.findFirst({
      orderBy: {
        lastCheck: 'desc',
      },
    })

    if (!healthRecord) {
      return null
    }

    // Parse the components JSON
    const components = JSON.parse(healthRecord.components)

    return {
      overall_status: healthRecord.overallStatus as 'healthy' | 'degraded' | 'unhealthy' | 'partial' | 'unknown',
      last_check: healthRecord.lastCheck.toISOString(),
      components,
      summary: {
        total: healthRecord.totalComponents,
        healthy: healthRecord.healthyComponents,
        degraded: healthRecord.degradedComponents,
        unhealthy: healthRecord.unhealthyComponents,
        unknown: healthRecord.unknownComponents,
      },
    }
  } catch (error: unknown) {
    console.error('Error fetching health check:', error instanceof Error ? error.message : error)
    return null
  }
}
