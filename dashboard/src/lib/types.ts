import { Prisma } from '@prisma/client'

// Define the full types with all relations
export type SignalWithTrades = Prisma.SignalGetPayload<{
  include: {
    trades: {
      include: {
        childTrades: true
        parentTrade: true
        tradeActions: true
        marketAnalyses: true
      }
    }
  }
}> & {
  replies?: SignalReplyType[]
}

export type SignalReplyType = Prisma.SignalReplyGetPayload<{
  select: {
    id: true
    createdAt: true
    replyMessageId: true
    replyToMessageId: true
    replyText: true
    userId: true
    username: true
    actionTaken: true
    actionType: true
    actionSuccess: true
    actionResult: true
    positionsClosed: true
    ordersCancelled: true
    processed: true
    processingError: true
    aiParsed: true
  }
}>

export type TradeWithRelations = Prisma.TradeGetPayload<{
  include: {
    signal: true
    parentTrade: true
    childTrades: true
    tradeActions: true
    marketAnalyses: true
  }
}>

export type TradeActionWithTrade = Prisma.TradeActionGetPayload<{
  include: {
    trade: {
      include: {
        signal: true
      }
    }
  }
}>

// For rendering child trades with simplified nested structure
export type TradeDisplay = TradeWithRelations & {
  childTrades: TradeWithRelations[]
}

export type TradePlanWithSignal = Prisma.TradePlanGetPayload<{
  include: { signal: true }
}> & {
  signal: Prisma.TradePlanGetPayload<{ include: { signal: true } }>['signal'] & {
    hasImage?: boolean
  }
}

export type DailyPerformance = {
  date: string
  profit: number
  trades: number
}

export type StatsData = {
  totalSignals: number
  totalTrades: number
  activeTrades: number
  closedTrades: number
  totalActions: number
  totalProfitLoss: number
  averageProfitLoss: number
  winningTrades: number
  losingTrades: number
  winRate: number
  recentSessions: Array<Record<string, unknown>>
  tradesBySymbol: Array<Record<string, unknown>>
  dailyPerformance: DailyPerformance[]
}

export type ComponentHealth = {
  name: string
  status: 'healthy' | 'degraded' | 'unhealthy' | 'unknown'
  message: string
  last_check: string
  response_time_ms?: number
  details?: Record<string, unknown>
}

export type HealthCheckData = {
  overall_status: 'healthy' | 'degraded' | 'unhealthy' | 'partial' | 'unknown'
  last_check: string | null
  components: Record<string, ComponentHealth>
  summary: {
    total: number
    healthy: number
    degraded: number
    unhealthy: number
    unknown: number
  }
} | null
