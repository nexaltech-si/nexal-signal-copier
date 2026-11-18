import { Activity } from 'lucide-react'
import AutoVerifyWrapper from '@/components/AutoVerifyWrapper'
import DashboardAutoRefresh from '@/components/DashboardAutoRefresh'
import MobilePageHeader from '@/components/MobilePageHeader'
import DashboardHeader from '@/components/DashboardHeader'
import MarketTicker from '@/components/MarketTicker'
import { getStats, getSignals, getTrades, getTradeActions } from '@/lib/data'

// Dashboard widgets
import KpiRow from '@/components/dashboard/KpiRow'
import ActiveTradeCard from '@/components/dashboard/ActiveTradeCard'
import AISummaryCard, { type AISummary } from '@/components/dashboard/AISummaryCard'
import MarketOverview from '@/components/dashboard/MarketOverview'
import EconomicCalendar from '@/components/dashboard/EconomicCalendar'
import TradingOverview from '@/components/dashboard/TradingOverview'
import PerformancePanel from '@/components/dashboard/PerformancePanel'
import RiskPanel from '@/components/dashboard/RiskPanel'
import JournalPanel from '@/components/dashboard/JournalPanel'
import WatchlistPanel from '@/components/dashboard/WatchlistPanel'
import RecentActivity, { type ActivityItem } from '@/components/dashboard/RecentActivity'

export const dynamic = 'force-dynamic'
export const revalidate = 0

export default async function Home() {
  const [stats, signals, trades, tradeActions] = await Promise.all([
    getStats(),
    getSignals(),
    getTrades(),
    getTradeActions(),
  ])

  if (!stats) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <p className="text-destructive">Failed to load dashboard data</p>
      </div>
    )
  }

  const unverifiedCount = signals.filter((s) => !s.aiVerified).length

  // ── Derive the latest market analysis (for the AI summary + confidence KPI) ──
  const allAnalyses = trades.flatMap((t) => t.marketAnalyses ?? [])
  const latestAnalysis = allAnalyses.length
    ? allAnalyses.reduce((newest, a) =>
        new Date(a.createdAt) > new Date(newest.createdAt) ? a : newest,
      )
    : null

  const aiSummary: AISummary | null = latestAnalysis
    ? {
        symbol: latestAnalysis.symbol,
        trend: latestAnalysis.trend,
        momentum: latestAnalysis.momentum,
        volatility: latestAnalysis.volatility,
        confidence: latestAnalysis.confidence,
        positionType: latestAnalysis.positionType,
        recommendBreakeven: latestAnalysis.recommendBreakeven,
        recommendTpAdjustment: latestAnalysis.recommendTpAdjustment,
        recommendReducePosition: latestAnalysis.recommendReducePosition,
        recommendTightStop: latestAnalysis.recommendTightStop,
        keepPositionOpen: latestAnalysis.keepPositionOpen,
        createdAt: latestAnalysis.createdAt?.toISOString?.() ?? null,
      }
    : null

  // ── Open-trade exposure by symbol (for the Trading Overview donut) ──
  const openTrades = trades.filter(
    (t) => t.status === 'EXECUTED' || t.status === 'EXECUTING' || t.status === 'PENDING',
  )
  const openBySymbolMap = openTrades.reduce<Record<string, number>>((acc, t) => {
    acc[t.symbol] = (acc[t.symbol] || 0) + 1
    return acc
  }, {})
  const openBySymbol = Object.entries(openBySymbolMap)
    .map(([symbol, count]) => ({ symbol, count }))
    .sort((a, b) => b.count - a.count)

  // ── Recent activity feed ──
  const recentActivity: ActivityItem[] = tradeActions.slice(0, 6).map((a) => ({
    type: a.actionType ?? 'ACTION',
    symbol: a.trade?.symbol ?? '—',
    detail: a.triggeredBy ? a.triggeredBy.replace(/_/g, ' ') : null,
    at: new Date(a.createdAt).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
    }),
  }))

  return (
    <DashboardAutoRefresh intervalSeconds={60}>
      <AutoVerifyWrapper unverifiedCount={unverifiedCount}>
        <div className="flex min-h-full flex-col">
          <MobilePageHeader
            title="Dashboard"
            subtitle="Live Monitor"
            hidden
            icon={<Activity className="h-5 w-5 text-primary" />}
          />

          {/* Desktop header with time-period filter */}
          <DashboardHeader />

          <div className="flex-1 px-4 md:px-8 py-4 md:py-6">
            <div className="flex flex-col gap-4 md:gap-5 max-w-[1800px] mx-auto">

              {/* Live trades alert strip */}
              {stats.activeTrades > 0 && (
                <div className="flex items-center gap-3 px-4 py-2.5 rounded-lg bg-success/10 border border-success/20 text-success text-xs font-semibold">
                  <span className="relative flex h-2 w-2">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-success opacity-75" />
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-success" />
                  </span>
                  {stats.activeTrades} active trade{stats.activeTrades > 1 ? 's' : ''} in progress
                </div>
              )}

              {/* ── Top KPI strip ── */}
              <KpiRow
                totalProfitLoss={stats.totalProfitLoss}
                winRate={stats.winRate}
                activeTrades={stats.activeTrades}
                totalTrades={stats.totalTrades}
                aiConfidence={latestAnalysis?.confidence ?? null}
              />

              {/* ── Market Overview / Economic Calendar / Trading Overview ── */}
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 md:gap-5">
                <MarketOverview />
                <EconomicCalendar />
                <TradingOverview
                  activeTrades={stats.activeTrades}
                  totalTrades={stats.totalTrades}
                  closedTrades={stats.closedTrades}
                  totalSignals={stats.totalSignals}
                  winRate={stats.winRate}
                  openBySymbol={openBySymbol}
                />
              </div>

              {/* ── Active Trade + AI Summary ── */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 md:gap-5">
                <ActiveTradeCard trades={trades} />
                <AISummaryCard analysis={aiSummary} />
              </div>

              {/* ── Performance (wide) + Recent Activity ── */}
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 md:gap-5">
                <div className="lg:col-span-2">
                  <PerformancePanel daily={stats.dailyPerformance} />
                </div>
                <RecentActivity items={recentActivity} />
              </div>

              {/* ── Risk / Journal / Watchlist ── */}
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 md:gap-5">
                <RiskPanel />
                <JournalPanel />
                <WatchlistPanel />
              </div>

              {/* ── Bottom market ticker ── */}
              <MarketTicker />
            </div>
          </div>
        </div>
      </AutoVerifyWrapper>
    </DashboardAutoRefresh>
  )
}
