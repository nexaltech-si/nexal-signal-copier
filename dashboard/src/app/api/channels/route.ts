import { NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { Prisma } from '@prisma/client'
import { requireOwner } from '@/lib/auth'

export const dynamic = 'force-dynamic'

/**
 * Channel Performance Analysis API
 * Provides detailed performance metrics for each Telegram channel
 */

interface ChannelPerformance {
  channelId: string
  channelName: string | null
  
  // Signal stats
  totalSignals: number
  signalsExecuted: number
  signalsRejected: number
  signalsFailed: number
  executionRate: number
  
  // Trade stats
  totalTrades: number
  closedTrades: number
  openTrades: number
  winningTrades: number
  losingTrades: number
  breakevenTrades: number
  
  // Performance metrics
  totalProfitLoss: number
  totalProfitLossPips: number
  averageProfitLoss: number
  averageProfitLossPips: number
  winRate: number
  averageWin: number
  averageLoss: number
  profitFactor: number
  largestWin: number
  largestLoss: number
  
  // Risk metrics
  averageRiskRewardRatio: number
  averageLotSize: number
  
  // Time metrics
  firstSignalDate: string | null
  lastSignalDate: string | null
  daysActive: number
  averageSignalsPerDay: number
  
  // Recent performance (30 days)
  recentTotalTrades: number
  recentProfitLoss: number
  recentWinRate: number
}

export async function GET(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const { searchParams } = new URL(request.url)
    const channelId = searchParams.get('channelId')
    const days = searchParams.get('days') ? parseInt(searchParams.get('days')!) : undefined
    const minTrades = searchParams.get('minTrades') ? parseInt(searchParams.get('minTrades')!) : 0
    
    // Build date filter
    let dateFrom: Date | undefined
    if (days) {
      dateFrom = new Date()
      dateFrom.setDate(dateFrom.getDate() - days)
    }
    
    // If specific channel requested
    if (channelId) {
      const performance = await getChannelPerformance(channelId, dateFrom)
      return NextResponse.json(performance)
    }
    
    // Get all channels
    const signals = await prisma.signal.findMany({
      where: dateFrom ? {
        createdAt: { gte: dateFrom }
      } : undefined,
      include: {
        trades: true
      }
    })
    
    // Group by channel
    const channelMap = new Map<string, typeof signals>()
    signals.forEach(signal => {
      if (!channelMap.has(signal.channelId)) {
        channelMap.set(signal.channelId, [])
      }
      channelMap.get(signal.channelId)!.push(signal)
    })
    
    // Calculate performance for each channel
    const performances: ChannelPerformance[] = []
    
    for (const [chanId, channelSignals] of channelMap.entries()) {
      const perf = calculateChannelMetrics(chanId, channelSignals)
      
      // Filter by minimum trades
      if (perf.totalTrades >= minTrades) {
        performances.push(perf)
      }
    }
    
    // Sort by profit
    performances.sort((a, b) => b.totalProfitLoss - a.totalProfitLoss)
    
    // Calculate summary
    const summary = {
      totalChannels: performances.length,
      totalProfit: performances.reduce((sum, p) => sum + p.totalProfitLoss, 0),
      totalTrades: performances.reduce((sum, p) => sum + p.totalTrades, 0),
      totalSignals: performances.reduce((sum, p) => sum + p.totalSignals, 0),
      bestProfitChannel: performances[0] || null,
      bestWinRateChannel: [...performances].sort((a, b) => b.winRate - a.winRate)[0] || null,
      mostActiveChannel: [...performances].sort((a, b) => b.totalSignals - a.totalSignals)[0] || null
    }
    
    return NextResponse.json({
      summary,
      channels: performances
    })
    
  } catch (error: unknown) {
    console.error('Channel performance API error:', error)
    return NextResponse.json(
      { 
        error: 'Failed to fetch channel performance',
        message: error instanceof Error ? error.message : 'Unable to calculate channel metrics'
      },
      { status: 500 }
    )
  }
}

async function getChannelPerformance(channelId: string, dateFrom?: Date): Promise<ChannelPerformance | null> {
  const signals = await prisma.signal.findMany({
    where: {
      channelId,
      ...(dateFrom && { createdAt: { gte: dateFrom } })
    },
    include: {
      trades: true
    }
  })
  
  if (signals.length === 0) {
    return null
  }
  
  return calculateChannelMetrics(channelId, signals)
}

type SignalWithTrades = Prisma.SignalGetPayload<{
  include: { trades: true }
}>;

function calculateChannelMetrics(channelId: string, signals: SignalWithTrades[]): ChannelPerformance {
  // Signal statistics
  const totalSignals = signals.length
  const signalsExecuted = signals.filter(s => s.status === 'EXECUTED').length
  const signalsRejected = signals.filter(s => s.status === 'REJECTED').length
  const signalsFailed = signals.filter(s => s.status === 'FAILED').length
  const executionRate = totalSignals > 0 ? (signalsExecuted / totalSignals) * 100 : 0
  
  const channelName = signals[0]?.channelName || null
  
  // Collect all trades
  const allTrades = signals.flatMap(s => s.trades || [])
  const totalTrades = allTrades.length
  
  const closedTrades = allTrades.filter(t => t.status === 'CLOSED')
  const openTrades = allTrades.filter(t => ['PENDING', 'EXECUTING', 'EXECUTED'].includes(t.status))
  
  // Calculate P&L metrics
  const totalProfitLoss = closedTrades.reduce((sum, t) => sum + (t.profitLoss || 0), 0)
  const totalProfitLossPips = closedTrades.reduce((sum, t) => sum + (t.profitLossPips || 0), 0)
  
  const winningTrades = closedTrades.filter(t => (t.profitLoss || 0) > 0)
  const losingTrades = closedTrades.filter(t => (t.profitLoss || 0) < 0)
  const breakevenTrades = closedTrades.filter(t => t.profitLoss === 0)
  
  const winRate = closedTrades.length > 0 ? (winningTrades.length / closedTrades.length) * 100 : 0
  
  const averageProfitLoss = closedTrades.length > 0 ? totalProfitLoss / closedTrades.length : 0
  const averageProfitLossPips = closedTrades.length > 0 ? totalProfitLossPips / closedTrades.length : 0
  
  const totalWins = winningTrades.reduce((sum, t) => sum + (t.profitLoss || 0), 0)
  const totalLosses = Math.abs(losingTrades.reduce((sum, t) => sum + (t.profitLoss || 0), 0))
  
  const averageWin = winningTrades.length > 0 ? totalWins / winningTrades.length : 0
  const averageLoss = losingTrades.length > 0 ? totalLosses / losingTrades.length : 0
  
  const profitFactor = totalLosses > 0 ? totalWins / totalLosses : (totalWins > 0 ? 999 : 0)
  
  const largestWin = winningTrades.length > 0 
    ? Math.max(...winningTrades.map(t => t.profitLoss || 0)) 
    : 0
  const largestLoss = losingTrades.length > 0 
    ? Math.min(...losingTrades.map(t => t.profitLoss || 0)) 
    : 0
  
  // Risk metrics
  const rrRatios = signals.filter(s => s.riskRewardRatio).map(s => s.riskRewardRatio!)
  const averageRiskRewardRatio = rrRatios.length > 0 
    ? rrRatios.reduce((sum, r) => sum + r, 0) / rrRatios.length 
    : 0
  
  const lotSizes = allTrades.filter(t => t.lotSize).map(t => t.lotSize!)
  const averageLotSize = lotSizes.length > 0 
    ? lotSizes.reduce((sum, l) => sum + l, 0) / lotSizes.length 
    : 0
  
  // Time-based metrics
  const signalDates = signals.map(s => new Date(s.createdAt))
  const firstSignalDate = signalDates.length > 0 
    ? new Date(Math.min(...signalDates.map(d => d.getTime()))).toISOString() 
    : null
  const lastSignalDate = signalDates.length > 0 
    ? new Date(Math.max(...signalDates.map(d => d.getTime()))).toISOString() 
    : null
  
  let daysActive = 0
  let averageSignalsPerDay = 0
  if (firstSignalDate && lastSignalDate) {
    const first = new Date(firstSignalDate)
    const last = new Date(lastSignalDate)
    daysActive = Math.floor((last.getTime() - first.getTime()) / (1000 * 60 * 60 * 24)) + 1
    averageSignalsPerDay = daysActive > 0 ? totalSignals / daysActive : 0
  }
  
  // Recent performance (last 30 days)
  const thirtyDaysAgo = new Date()
  thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30)
  
  const recentTrades = closedTrades.filter(t => t.closedAt && new Date(t.closedAt) >= thirtyDaysAgo)
  const recentTotalTrades = recentTrades.length
  const recentProfitLoss = recentTrades.reduce((sum, t) => sum + (t.profitLoss || 0), 0)
  const recentWinning = recentTrades.filter(t => (t.profitLoss || 0) > 0)
  const recentWinRate = recentTrades.length > 0 ? (recentWinning.length / recentTrades.length) * 100 : 0
  
  return {
    channelId,
    channelName,
    totalSignals,
    signalsExecuted,
    signalsRejected,
    signalsFailed,
    executionRate,
    totalTrades,
    closedTrades: closedTrades.length,
    openTrades: openTrades.length,
    winningTrades: winningTrades.length,
    losingTrades: losingTrades.length,
    breakevenTrades: breakevenTrades.length,
    totalProfitLoss,
    totalProfitLossPips,
    averageProfitLoss,
    averageProfitLossPips,
    winRate,
    averageWin,
    averageLoss,
    profitFactor,
    largestWin,
    largestLoss,
    averageRiskRewardRatio,
    averageLotSize,
    firstSignalDate,
    lastSignalDate,
    daysActive,
    averageSignalsPerDay,
    recentTotalTrades,
    recentProfitLoss,
    recentWinRate
  }
}
