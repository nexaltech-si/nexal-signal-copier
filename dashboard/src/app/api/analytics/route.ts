import { NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { requireOwner } from '@/lib/auth'

export const dynamic = 'force-dynamic'

/**
 * Enhanced Analytics API Endpoint
 * Provides comprehensive analytics based on real database data
 */

export async function GET(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const { searchParams } = new URL(request.url)
    const days = parseInt(searchParams.get('days') || '30')
    const dateFrom = new Date()
    dateFrom.setDate(dateFrom.getDate() - days)

    // Fetch all closed trades with related data
    const closedTrades = await prisma.trade.findMany({
      where: {
        status: 'CLOSED',
        closedAt: { gte: dateFrom },
        profitLoss: { not: null }
      },
      include: {
        signal: true,
        tradeActions: true
      },
      orderBy: {
        closedAt: 'asc'
      }
    })

    // Calculate cumulative profit over time
    let cumulativeProfit = 0
    const cumulativeProfitData = closedTrades.map(trade => {
      cumulativeProfit += trade.profitLoss || 0
      return {
        date: trade.closedAt?.toISOString().split('T')[0],
        time: trade.closedAt?.toISOString(),
        profit: trade.profitLoss || 0,
        cumulative: cumulativeProfit,
        symbol: trade.symbol
      }
    })

    // Profit distribution (histogram data)
    const profitBuckets: { [key: string]: number } = {
      '-500+': 0,
      '-400 to -500': 0,
      '-300 to -400': 0,
      '-200 to -300': 0,
      '-100 to -200': 0,
      '-50 to -100': 0,
      '0 to -50': 0,
      '0 to 50': 0,
      '50 to 100': 0,
      '100 to 200': 0,
      '200 to 300': 0,
      '300 to 400': 0,
      '400 to 500': 0,
      '500+': 0
    }

    closedTrades.forEach(trade => {
      const pl = trade.profitLoss || 0
      if (pl < -500) profitBuckets['-500+']++
      else if (pl < -400) profitBuckets['-400 to -500']++
      else if (pl < -300) profitBuckets['-300 to -400']++
      else if (pl < -200) profitBuckets['-200 to -300']++
      else if (pl < -100) profitBuckets['-100 to -200']++
      else if (pl < -50) profitBuckets['-50 to -100']++
      else if (pl < 0) profitBuckets['0 to -50']++
      else if (pl < 50) profitBuckets['0 to 50']++
      else if (pl < 100) profitBuckets['50 to 100']++
      else if (pl < 200) profitBuckets['100 to 200']++
      else if (pl < 300) profitBuckets['200 to 300']++
      else if (pl < 400) profitBuckets['300 to 400']++
      else if (pl < 500) profitBuckets['400 to 500']++
      else profitBuckets['500+']++
    })

    const profitDistribution = Object.entries(profitBuckets).map(([range, count]) => ({
      range,
      count
    }))

    // Trade duration analysis
    const tradeDurations = closedTrades
      .filter(t => t.executedAt && t.closedAt)
      .map(t => {
        const duration = (new Date(t.closedAt!).getTime() - new Date(t.executedAt!).getTime()) / (1000 * 60 * 60) // hours
        return {
          duration,
          profit: t.profitLoss || 0,
          symbol: t.symbol
        }
      })

    // Group durations into buckets
    const durationBuckets: { [key: string]: { count: number; profit: number } } = {
      '0-1h': { count: 0, profit: 0 },
      '1-4h': { count: 0, profit: 0 },
      '4-12h': { count: 0, profit: 0 },
      '12-24h': { count: 0, profit: 0 },
      '1-3d': { count: 0, profit: 0 },
      '3-7d': { count: 0, profit: 0 },
      '7d+': { count: 0, profit: 0 }
    }

    tradeDurations.forEach(({ duration, profit }) => {
      if (duration < 1) {
        durationBuckets['0-1h'].count++
        durationBuckets['0-1h'].profit += profit
      } else if (duration < 4) {
        durationBuckets['1-4h'].count++
        durationBuckets['1-4h'].profit += profit
      } else if (duration < 12) {
        durationBuckets['4-12h'].count++
        durationBuckets['4-12h'].profit += profit
      } else if (duration < 24) {
        durationBuckets['12-24h'].count++
        durationBuckets['12-24h'].profit += profit
      } else if (duration < 72) {
        durationBuckets['1-3d'].count++
        durationBuckets['1-3d'].profit += profit
      } else if (duration < 168) {
        durationBuckets['3-7d'].count++
        durationBuckets['3-7d'].profit += profit
      } else {
        durationBuckets['7d+'].count++
        durationBuckets['7d+'].profit += profit
      }
    })

    const durationAnalysis = Object.entries(durationBuckets).map(([range, data]) => ({
      range,
      count: data.count,
      avgProfit: data.count > 0 ? data.profit / data.count : 0,
      totalProfit: data.profit
    }))

    // Hourly performance (time of day analysis)
    const hourlyPerformance: { [hour: number]: { trades: number; profit: number; wins: number } } = {}
    for (let i = 0; i < 24; i++) {
      hourlyPerformance[i] = { trades: 0, profit: 0, wins: 0 }
    }

    closedTrades.forEach(trade => {
      if (trade.executedAt) {
        const hour = new Date(trade.executedAt).getHours()
        hourlyPerformance[hour].trades++
        hourlyPerformance[hour].profit += trade.profitLoss || 0
        if ((trade.profitLoss || 0) > 0) hourlyPerformance[hour].wins++
      }
    })

    const hourlyData = Object.entries(hourlyPerformance).map(([hour, data]) => ({
      hour: `${hour.toString().padStart(2, '0')}:00`,
      trades: data.trades,
      profit: data.profit,
      winRate: data.trades > 0 ? (data.wins / data.trades) * 100 : 0
    }))

    // Day of week analysis
    const dayOfWeekPerformance: { [day: number]: { trades: number; profit: number; wins: number } } = {}
    for (let i = 0; i < 7; i++) {
      dayOfWeekPerformance[i] = { trades: 0, profit: 0, wins: 0 }
    }

    closedTrades.forEach(trade => {
      if (trade.executedAt) {
        const day = new Date(trade.executedAt).getDay()
        dayOfWeekPerformance[day].trades++
        dayOfWeekPerformance[day].profit += trade.profitLoss || 0
        if ((trade.profitLoss || 0) > 0) dayOfWeekPerformance[day].wins++
      }
    })

    const dayNames = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
    const weekdayData = Object.entries(dayOfWeekPerformance).map(([day, data]) => ({
      day: dayNames[parseInt(day)],
      trades: data.trades,
      profit: data.profit,
      winRate: data.trades > 0 ? (data.wins / data.trades) * 100 : 0
    }))

    // Hour-of-day x day-of-week performance grid (for heatmap)
    const hourByDayGrid: { trades: number; profit: number; wins: number }[][] =
      Array.from({ length: 7 }, () => Array.from({ length: 24 }, () => ({ trades: 0, profit: 0, wins: 0 })))

    closedTrades.forEach(trade => {
      if (trade.executedAt) {
        const d = new Date(trade.executedAt)
        const cell = hourByDayGrid[d.getDay()][d.getHours()]
        cell.trades++
        cell.profit += trade.profitLoss || 0
        if ((trade.profitLoss || 0) > 0) cell.wins++
      }
    })

    const hourByDayPerformance = dayNames.map((dayName, day) => ({
      day: dayName,
      hours: hourByDayGrid[day].map((cell, hour) => ({
        hour,
        trades: cell.trades,
        profit: cell.profit,
        winRate: cell.trades > 0 ? (cell.wins / cell.trades) * 100 : 0
      }))
    }))

    // Symbol performance analysis
    const symbolStats: { [symbol: string]: { trades: number; profit: number; wins: number; losses: number; totalPips: number } } = {}
    
    closedTrades.forEach(trade => {
      if (!symbolStats[trade.symbol]) {
        symbolStats[trade.symbol] = { trades: 0, profit: 0, wins: 0, losses: 0, totalPips: 0 }
      }
      symbolStats[trade.symbol].trades++
      symbolStats[trade.symbol].profit += trade.profitLoss || 0
      symbolStats[trade.symbol].totalPips += trade.profitLossPips || 0
      if ((trade.profitLoss || 0) > 0) {
        symbolStats[trade.symbol].wins++
      } else {
        symbolStats[trade.symbol].losses++
      }
    })

    const symbolPerformance = Object.entries(symbolStats)
      .map(([symbol, data]) => ({
        symbol,
        trades: data.trades,
        profit: data.profit,
        avgProfit: data.profit / data.trades,
        winRate: (data.wins / data.trades) * 100,
        avgPips: data.totalPips / data.trades,
        profitFactor: data.losses > 0 ? data.wins / data.losses : data.wins
      }))
      .sort((a, b) => b.profit - a.profit)

    // Win/Loss streak analysis
    let currentStreak = 0
    let maxWinStreak = 0
    let maxLossStreak = 0
    const streaks: number[] = []

    closedTrades.forEach(trade => {
      const isWin = (trade.profitLoss || 0) > 0
      if (isWin) {
        if (currentStreak < 0) {
          streaks.push(currentStreak)
          currentStreak = 0
        }
        currentStreak++
        maxWinStreak = Math.max(maxWinStreak, currentStreak)
      } else {
        if (currentStreak > 0) {
          streaks.push(currentStreak)
          currentStreak = 0
        }
        currentStreak--
        maxLossStreak = Math.max(maxLossStreak, Math.abs(currentStreak))
      }
    })
    if (currentStreak !== 0) streaks.push(currentStreak)

    // Realized R-multiple distribution: profit ÷ $ actually risked on the originating signal
    const rMultiples = closedTrades
      .filter(t => t.signal?.riskAmount && t.signal.riskAmount > 0)
      .map(t => {
        const rMultiple = (t.profitLoss || 0) / t.signal!.riskAmount!
        return {
          symbol: t.symbol,
          rMultiple,
          profit: t.profitLoss || 0,
          isWin: (t.profitLoss || 0) > 0
        }
      })
    const tradesWithoutRiskData = closedTrades.length - rMultiples.length

    const rMultipleBuckets: { [key: string]: number } = {
      '<-2R': 0,
      '-2R to -1R': 0,
      '-1R to 0R': 0,
      '0R to 1R': 0,
      '1R to 2R': 0,
      '2R to 3R': 0,
      '>3R': 0
    }
    rMultiples.forEach(({ rMultiple }) => {
      if (rMultiple < -2) rMultipleBuckets['<-2R']++
      else if (rMultiple < -1) rMultipleBuckets['-2R to -1R']++
      else if (rMultiple < 0) rMultipleBuckets['-1R to 0R']++
      else if (rMultiple < 1) rMultipleBuckets['0R to 1R']++
      else if (rMultiple < 2) rMultipleBuckets['1R to 2R']++
      else if (rMultiple < 3) rMultipleBuckets['2R to 3R']++
      else rMultipleBuckets['>3R']++
    })
    const rMultipleDistribution = Object.entries(rMultipleBuckets).map(([range, count]) => ({ range, count }))

    const avgRMultiple = rMultiples.length > 0
      ? rMultiples.reduce((sum, r) => sum + r.rMultiple, 0) / rMultiples.length
      : 0
    const rMultipleWins = rMultiples.filter(r => r.isWin)
    const rMultipleLosses = rMultiples.filter(r => !r.isWin)
    const winRateForR = rMultiples.length > 0 ? rMultipleWins.length / rMultiples.length : 0
    const avgWinR = rMultipleWins.length > 0 ? rMultipleWins.reduce((s, r) => s + r.rMultiple, 0) / rMultipleWins.length : 0
    const avgLossR = rMultipleLosses.length > 0 ? rMultipleLosses.reduce((s, r) => s + r.rMultiple, 0) / rMultipleLosses.length : 0
    const expectancyR = (winRateForR * avgWinR) + ((1 - winRateForR) * avgLossR)

    // Weekly comparison
    const weeklyStats: { [week: string]: { trades: number; profit: number; wins: number } } = {}
    
    closedTrades.forEach(trade => {
      if (trade.closedAt) {
        const weekStart = new Date(trade.closedAt)
        weekStart.setDate(weekStart.getDate() - weekStart.getDay())
        const weekKey = weekStart.toISOString().split('T')[0]
        
        if (!weeklyStats[weekKey]) {
          weeklyStats[weekKey] = { trades: 0, profit: 0, wins: 0 }
        }
        weeklyStats[weekKey].trades++
        weeklyStats[weekKey].profit += trade.profitLoss || 0
        if ((trade.profitLoss || 0) > 0) weeklyStats[weekKey].wins++
      }
    })

    const weeklyComparison = Object.entries(weeklyStats)
      .map(([week, data]) => ({
        week,
        trades: data.trades,
        profit: data.profit,
        winRate: data.trades > 0 ? (data.wins / data.trades) * 100 : 0
      }))
      .sort((a, b) => a.week.localeCompare(b.week))

    // Drawdown calculation
    let peak = 0
    let maxDrawdown = 0
    const drawdownData = cumulativeProfitData.map(point => {
      peak = Math.max(peak, point.cumulative)
      const drawdown = peak - point.cumulative
      maxDrawdown = Math.max(maxDrawdown, drawdown)
      return {
        date: point.date,
        drawdown: -drawdown,
        drawdownPercent: peak > 0 ? -(drawdown / peak) * 100 : 0
      }
    })

    // Overall statistics
    const totalTrades = closedTrades.length
    const winningTrades = closedTrades.filter(t => (t.profitLoss || 0) > 0).length
    const losingTrades = closedTrades.filter(t => (t.profitLoss || 0) < 0).length
    const totalProfit = closedTrades.reduce((sum, t) => sum + (t.profitLoss || 0), 0)
    const totalWins = closedTrades.filter(t => (t.profitLoss || 0) > 0).reduce((sum, t) => sum + (t.profitLoss || 0), 0)
    const totalLosses = Math.abs(closedTrades.filter(t => (t.profitLoss || 0) < 0).reduce((sum, t) => sum + (t.profitLoss || 0), 0))
    const avgWin = winningTrades > 0 ? totalWins / winningTrades : 0
    const avgLoss = losingTrades > 0 ? totalLosses / losingTrades : 0
    const profitFactor = totalLosses > 0 ? totalWins / totalLosses : totalWins > 0 ? 999 : 0

    return NextResponse.json({
      summary: {
        totalTrades,
        winningTrades,
        losingTrades,
        winRate: totalTrades > 0 ? (winningTrades / totalTrades) * 100 : 0,
        totalProfit,
        avgWin,
        avgLoss,
        profitFactor,
        maxWinStreak,
        maxLossStreak,
        maxDrawdown,
        expectancy: totalTrades > 0 ? totalProfit / totalTrades : 0
      },
      charts: {
        cumulativeProfit: cumulativeProfitData,
        profitDistribution,
        durationAnalysis,
        hourlyPerformance: hourlyData,
        weekdayPerformance: weekdayData,
        hourByDayPerformance,
        symbolPerformance,
        weeklyComparison,
        drawdown: drawdownData
      },
      advanced: {
        rMultiples,
        rMultipleDistribution,
        rMultipleSummary: {
          avgRMultiple,
          expectancyR,
          tradesWithRiskData: rMultiples.length,
          tradesWithoutRiskData
        },
        tradeDurations,
        streaks
      }
    })

  } catch (error: unknown) {
    console.error('Analytics API error:', error)
    return NextResponse.json(
      { 
        error: 'Failed to fetch analytics',
        message: error instanceof Error ? error.message : 'Unable to calculate analytics'
      },
      { status: 500 }
    )
  }
}
