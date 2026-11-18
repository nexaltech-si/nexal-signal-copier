'use client'

import { useEffect, useState, useCallback } from 'react'
import {
  BarChart, Bar, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer
} from 'recharts'
import {
  TrendingUp, DollarSign, Target, AlertTriangle,
  Activity, Award, BarChart3, RefreshCw, Filter, Layers, Zap, Clock
} from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import PerformanceGauge from '@/components/PerformanceGauge'
import MobilePageHeader from '@/components/MobilePageHeader'
import EquityCurveChart, { EquityPoint } from '@/components/EquityCurveChart'
import RMultipleHistogram from '@/components/RMultipleHistogram'
import PerformanceHeatmap from '@/components/PerformanceHeatmap'
import StreakSequence from '@/components/StreakSequence'
import { formatCurrency } from '@/lib/utils'

interface PerformanceMetrics {
  balance: number
  equity: number
  profit: number
  gain: number
  totalTrades: number
  wonTrades: number
  profitFactor: number
  expectancy: number
  maxDrawdown: number
  sharpeRatio: number
  sortinoRatio: number
  dailyGrowth: number
  monthlyGrowth: number
  cagr: number
  lastUpdateTime: string
}

interface AnalyticsData {
  summary: {
    totalTrades: number
    winningTrades: number
    losingTrades: number
    winRate: number
    totalProfit: number
    avgWin: number
    avgLoss: number
    profitFactor: number
    maxWinStreak: number
    maxLossStreak: number
    maxDrawdown: number
    expectancy: number
  }
  charts: {
    cumulativeProfit: Array<{ date: string; profit: number; cumulative: number }>
    profitDistribution: Array<{ range: string; count: number }>
    durationAnalysis: Array<{ range: string; count: number; avgProfit: number }>
    hourlyPerformance: Array<{ hour: string; trades: number; profit: number; winRate: number }>
    weekdayPerformance: Array<{ day: string; trades: number; profit: number; winRate: number }>
    hourByDayPerformance: Array<{ day: string; hours: Array<{ hour: number; trades: number; profit: number; winRate: number }> }>
    symbolPerformance: Array<{
      symbol: string
      trades: number
      profit: number
      avgProfit: number
      winRate: number
      avgPips: number
      profitFactor: number
    }>
    weeklyComparison: Array<{ week: string; trades: number; profit: number; winRate: number }>
    drawdown: Array<{ date: string; drawdown: number }>
  }
  advanced: {
    rMultiples: Array<{ symbol: string; rMultiple: number; profit: number; isWin: boolean }>
    rMultipleDistribution: Array<{ range: string; count: number }>
    rMultipleSummary: {
      avgRMultiple: number
      expectancyR: number
      tradesWithRiskData: number
      tradesWithoutRiskData: number
    }
    tradeDurations: Array<{ duration: number; profit: number; symbol: string }>
    streaks: number[]
  }
}

interface EquityHistoryData {
  points: EquityPoint[]
  hasEnoughData: boolean
}

interface ChannelData {
  summary: Record<string, any>
  channels: Array<Record<string, any>>
}

export default function PerformancePage() {
  const [activeTab, setActiveTab] = useState<'overview' | 'analytics' | 'channels'>('overview')
  const [metrics, setMetrics] = useState<PerformanceMetrics | null>(null)
  const [analytics, setAnalytics] = useState<AnalyticsData | null>(null)
  const [equityHistory, setEquityHistory] = useState<EquityHistoryData | null>(null)
  const [channelData, setChannelData] = useState<ChannelData | null>(null)
  const [loading, setLoading] = useState(true)
  const [days, setDays] = useState(30)

  const fetchData = useCallback(async () => {
    try {
      setLoading(true)
      const [performanceRes, analyticsRes, equityRes, channelsRes] = await Promise.all([
        fetch('/api/performance'),
        fetch(`/api/analytics?days=${days}`),
        fetch(`/api/equity-history?days=${days}`),
        fetch(`/api/channels?days=${days}`)
      ])

      const p = await performanceRes.json()
      const a = await analyticsRes.json()
      const e = await equityRes.json()
      const c = await channelsRes.json()

      if (p.service !== 'offline' && !p.error) setMetrics(p)
      if (!a.error) setAnalytics(a)
      if (!e.error) setEquityHistory(e)
      if (!c.error) setChannelData(c)
    } catch (err: unknown) {
      console.error(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }, [days])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  return (
    <div className="flex flex-col min-h-full pb-10">
      <MobilePageHeader 
        title="Performance" 
        subtitle="Analytics"
        hidden
        icon={<BarChart3 className="h-5 w-5" />}
      />
      <header className="hidden md:flex sticky top-0 z-40 w-full tech-header">
        <div className="max-w-[1800px] w-full mx-auto flex h-14 items-center px-6 gap-3">
          <div className="p-1.5 rounded-lg bg-primary/10 border border-primary/20">
            <BarChart3 className="h-5 w-5 text-primary" />
          </div>
          <div className="flex flex-col">
            <h1 className="text-sm font-bold text-foreground leading-none">Performance</h1>
            <p className="text-[10px] text-[#6b7288] font-bold uppercase tracking-wider mt-1">Analytics</p>
          </div>
          <div className="ml-auto flex items-center gap-2">
             <div className="flex items-center gap-1 border border-border rounded px-2 py-1 bg-card">
                <Filter className="h-3 w-3 text-muted-foreground/70" />
                <select 
                  value={days} 
                  onChange={(e) => setDays(Number(e.target.value))}
                  className="bg-transparent text-xs font-semibold text-foreground/80 border-none outline-none focus:ring-0"
                >
                   <option value={7}>7D</option>
                   <option value={30}>30D</option>
                   <option value={90}>90D</option>
                </select>
             </div>
             <button onClick={fetchData} disabled={loading} className="p-1.5 hover:bg-muted rounded transition-colors">
                <RefreshCw className={`h-3.5 w-3.5 text-muted-foreground ${loading ? 'animate-spin' : ''}`} />
             </button>
          </div>
        </div>
      </header>

      <div className="hidden md:flex max-w-[1800px] w-full mx-auto px-6 border-b border-border bg-card">
        <div className="flex h-10 gap-1">
          {[
            { id: 'overview', icon: Activity, label: 'Overview' },
            { id: 'analytics', icon: TrendingUp, label: 'Analytics' },
            { id: 'channels', icon: Layers, label: 'Channels' },
          ].map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as 'overview' | 'analytics' | 'channels')}
              className={`flex items-center gap-1.5 px-3 py-2 text-xs font-semibold transition-colors relative border-b-2 ${
                activeTab === tab.id ? 'text-primary border-primary' : 'text-muted-foreground border-transparent hover:text-foreground'
              }`}
            >
              <tab.icon className="w-3.5 h-3.5" />
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      <main className="flex-1 px-3 md:px-4 py-4 md:py-4">
        <div className="flex flex-col gap-3 md:gap-4 max-w-[1800px] mx-auto">
        {activeTab === 'overview' && metrics && (
          <div className="grid grid-cols-1 gap-4 md:gap-5">
            <EquityCurveChart
              points={equityHistory?.points || []}
              hasEnoughData={equityHistory?.hasEnoughData || false}
              fallbackData={analytics?.charts.cumulativeProfit.map(p => ({ date: p.date, cumulative: p.cumulative })) || []}
            />

            {/* Secondary metrics strip — compact, not a second wall of tiles */}
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2 md:gap-3">
              <StatItem title="Balance" value={formatCurrency(metrics.balance)} sub={null} icon={DollarSign} />
              <StatItem title="Win Rate" value={`${metrics.wonTrades.toFixed(1)}%`} sub={`${metrics.totalTrades} trades`} icon={Target} />
              <StatItem title="Profit Factor" value={metrics.profitFactor.toFixed(2)} sub={null} icon={Award} />
              <StatItem title="Sharpe" value={metrics.sharpeRatio.toFixed(2)} sub={null} icon={TrendingUp} />
              <StatItem title="Sortino" value={metrics.sortinoRatio.toFixed(2)} sub={null} icon={Activity} />
              <StatItem title="CAGR" value={`${metrics.cagr.toFixed(1)}%`} sub={null} icon={AlertTriangle} />
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 md:gap-4">
               <Card className="shadow-sm border border-border bg-card lg:col-span-2">
                  <CardHeader className="py-3 px-4 flex flex-row items-center gap-2 border-b bg-muted/40">
                     <AlertTriangle className="h-4 w-4 text-primary" />
                     <CardTitle className="text-sm font-bold text-foreground">Risk &amp; Growth</CardTitle>
                  </CardHeader>
                  <CardContent className="p-4 grid grid-cols-2 gap-x-6 gap-y-3">
                     <MetricLine label="Expectancy" value={formatCurrency(metrics.expectancy)} />
                     <MetricLine label="Max Drawdown" value={`${metrics.maxDrawdown.toFixed(2)}%`} color="text-destructive" />
                     <MetricLine label="Daily Growth" value={`${metrics.dailyGrowth.toFixed(2)}%`} />
                     <MetricLine label="Monthly Growth" value={`${metrics.monthlyGrowth.toFixed(2)}%`} color="text-primary" />
                  </CardContent>
               </Card>

               <Card className="shadow-sm border border-border bg-card overflow-hidden">
                  <CardHeader className="py-3 px-4 flex flex-row items-center gap-2 border-b bg-muted/40">
                     <Target className="h-4 w-4 text-primary" />
                     <CardTitle className="text-sm font-bold text-foreground">Accuracy</CardTitle>
                  </CardHeader>
                  <CardContent className="p-4 flex items-center justify-center">
                     <PerformanceGauge
                       value={metrics.wonTrades}
                       label="Success"
                       subLabel={`${metrics.totalTrades} Executed`}
                       size={140}
                     />
                  </CardContent>
               </Card>
            </div>
          </div>
        )}

        {activeTab === 'analytics' && analytics && (
          <div className="space-y-4 md:space-y-5">
            {/* Featured row: R-multiple is the headline analytics story, heatmap is the widest panel */}
            <div className="grid grid-cols-1 xl:grid-cols-5 gap-4 md:gap-5">
               <div className="xl:col-span-2">
                  <RMultipleHistogram data={analytics.advanced.rMultipleDistribution} summary={analytics.advanced.rMultipleSummary} />
               </div>
               <div className="xl:col-span-3">
                  <PerformanceHeatmap data={analytics.charts.hourByDayPerformance} />
               </div>
            </div>

            {/* Streaks gets room to breathe; P/L distribution + weekly + duration share a denser row */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 md:gap-5">
               <StreakSequence streaks={analytics.advanced.streaks} />

               <ChartCard title="P/L Distribution" icon={Zap}>
                  <ResponsiveContainer width="100%" height={260}>
                    <BarChart data={analytics.charts.profitDistribution}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="hsl(var(--border))" />
                      <XAxis dataKey="range" tick={{ fontSize: 8, fill: 'hsl(var(--muted-foreground))' }} angle={-45} textAnchor="end" height={55} stroke="hsl(var(--border))" />
                      <YAxis tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }} stroke="hsl(var(--border))" allowDecimals={false} />
                      <Tooltip contentStyle={{ borderRadius: '8px', border: '1px solid hsl(var(--border))', fontSize: '12px', background: 'hsl(var(--card))' }} cursor={{ fill: 'hsl(var(--muted) / 0.4)' }} />
                      <Bar dataKey="count" radius={[2, 2, 0, 0]} maxBarSize={28}>
                        {analytics.charts.profitDistribution.map((entry, index) => (
                          <Cell key={index} fill={entry.range.includes('-') ? 'hsl(var(--destructive))' : 'hsl(var(--success))'} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
               </ChartCard>

               <div className="grid grid-cols-1 gap-4 md:gap-5">
                  <ChartCard title="Weekly P&L" icon={Clock} compact>
                     <ResponsiveContainer width="100%" height={110}>
                       <BarChart data={analytics.charts.weeklyComparison}>
                         <XAxis dataKey="week" hide />
                         <YAxis hide />
                         <Tooltip contentStyle={{ borderRadius: '8px', border: '1px solid hsl(var(--border))', fontSize: '12px', background: 'hsl(var(--card))' }} cursor={{ fill: 'hsl(var(--muted) / 0.4)' }} />
                         <Bar dataKey="profit" radius={[2, 2, 0, 0]} maxBarSize={20}>
                           {analytics.charts.weeklyComparison.map((entry, index) => (
                             <Cell key={index} fill={entry.profit >= 0 ? 'hsl(var(--success))' : 'hsl(var(--destructive))'} />
                           ))}
                         </Bar>
                       </BarChart>
                     </ResponsiveContainer>
                  </ChartCard>
                  <ChartCard title="Trade Duration" icon={Clock} compact>
                     <ResponsiveContainer width="100%" height={110}>
                       <BarChart data={analytics.charts.durationAnalysis}>
                         <XAxis dataKey="range" tick={{ fontSize: 8, fill: 'hsl(var(--muted-foreground))' }} stroke="hsl(var(--border))" />
                         <YAxis hide />
                         <Tooltip contentStyle={{ borderRadius: '8px', border: '1px solid hsl(var(--border))', fontSize: '12px', background: 'hsl(var(--card))' }} cursor={{ fill: 'hsl(var(--muted) / 0.4)' }} />
                         <Bar dataKey="count" radius={[2, 2, 0, 0]} fill="hsl(var(--chart-1))" maxBarSize={20} />
                       </BarChart>
                     </ResponsiveContainer>
                  </ChartCard>
               </div>
            </div>

            <Card className="border border-border shadow-sm bg-card">
                <CardHeader className="py-3 px-4 border-b bg-muted/40">
                    <CardTitle className="text-sm font-bold flex items-center gap-2 text-foreground">
                        <Activity className="h-4 w-4 text-primary" /> Performance by Symbol
                    </CardTitle>
                </CardHeader>
                <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                        <thead className="bg-muted border-b text-foreground/80 font-bold">
                            <tr>
                                <th className="px-4 py-3 text-left">Symbol</th>
                                <th className="px-4 py-3 text-right">Trades</th>
                                <th className="px-4 py-3 text-right">Net Profit</th>
                                <th className="px-4 py-3 text-right">Avg Profit</th>
                                <th className="px-4 py-3 text-right">Win Rate</th>
                                <th className="px-4 py-3 text-right">Profit Factor</th>
                                <th className="px-4 py-3 text-right">Avg Pips</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-200">
                            {analytics.charts.symbolPerformance.map((s, i) => (
                                <tr key={i} className="hover:bg-muted/50 transition-colors">
                                    <td className="px-4 py-3 font-bold text-foreground">{s.symbol}</td>
                                    <td className="px-4 py-3 text-right font-semibold text-foreground/80">{s.trades}</td>
                                    <td className={`px-4 py-3 text-right font-bold ${s.profit >= 0 ? 'text-success' : 'text-destructive'}`}>
                                        {formatCurrency(s.profit)}
                                    </td>
                                    <td className={`px-4 py-3 text-right font-semibold ${s.avgProfit >= 0 ? 'text-success' : 'text-destructive'}`}>
                                        {formatCurrency(s.avgProfit)}
                                    </td>
                                    <td className="px-4 py-3 text-right font-semibold text-foreground">{s.winRate.toFixed(1)}%</td>
                                    <td className="px-4 py-3 text-right">
                                        <Badge variant="outline" className="text-[10px] font-bold px-1.5 py-0.5 border-border">{s.profitFactor.toFixed(2)}</Badge>
                                    </td>
                                    <td className={`px-4 py-3 text-right font-semibold ${s.avgPips >= 0 ? 'text-success' : 'text-destructive'}`}>
                                        {s.avgPips.toFixed(1)}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </Card>
          </div>
        )}

        {activeTab === 'channels' && channelData && (
          <div className="space-y-6">
             <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3 md:gap-4">
                <StatItem title="Best Profit" value={channelData.summary.bestProfitChannel?.channelName || 'N/A'} sub={formatCurrency(channelData.summary.bestProfitChannel?.totalProfitLoss || 0)} />
                <StatItem title="Highest Win Rate" value={channelData.summary.bestWinRateChannel?.channelName || 'N/A'} sub={`${channelData.summary.bestWinRateChannel?.winRate?.toFixed(1) || '0.0'}%`} />
                <StatItem title="Most Active" value={channelData.summary.mostActiveChannel?.channelName || 'N/A'} sub={`${channelData.summary.mostActiveChannel?.totalSignals || 0} signals`} />
                <StatItem title="Total Volume" value={String(channelData.summary.totalSignals)} sub={`${channelData.summary.totalChannels} Channels`} />
             </div>

             <Card className="border border-border shadow-sm bg-card overflow-hidden">
                <CardHeader className="py-3 px-4 border-b bg-muted/40">
                    <CardTitle className="text-sm font-bold text-foreground">Channel Performance</CardTitle>
                </CardHeader>
                <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                        <thead className="bg-muted border-b text-foreground/80 font-bold">
                            <tr>
                                <th className="px-4 py-3 text-left">Channel Name</th>
                                <th className="px-4 py-3 text-right">Exec%</th>
                                <th className="px-4 py-3 text-right">W/L</th>
                                <th className="px-4 py-3 text-right">Win Rate</th>
                                <th className="px-4 py-3 text-right">Total P/L</th>
                                <th className="px-4 py-3 text-right">Avg P/L</th>
                                <th className="px-4 py-3 text-right">Profit Factor</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-200">
                            {channelData.channels.map((c, i) => (
                                <tr key={i} className="hover:bg-muted/50 transition-colors">
                                    <td className="px-4 py-4">
                                        <p className="font-bold text-foreground">{c.channelName || 'Unknown'}</p>
                                        <p className="text-[10px] text-muted-foreground truncate max-w-[120px] font-medium">{c.channelId}</p>
                                    </td>
                                    <td className="px-4 py-4 text-right font-semibold">
                                        <div className="flex flex-col items-end gap-1">
                                            <span className="text-foreground">{c.executionRate.toFixed(0)}%</span>
                                            <div className="w-12 h-1.5 bg-border rounded-full overflow-hidden">
                                                <div className="h-full bg-primary" style={{ width: `${c.executionRate}%` }} />
                                            </div>
                                        </div>
                                    </td>
                                    <td className="px-4 py-4 text-right text-muted-foreground font-semibold">
                                        {c.winningTrades}W / {c.losingTrades}L
                                    </td>
                                    <td className={`px-4 py-4 text-right font-bold ${c.winRate >= 60 ? 'text-success' : c.winRate < 40 ? 'text-destructive' : 'text-foreground'}`}>
                                        {c.winRate.toFixed(1)}%
                                    </td>
                                    <td className={`px-4 py-4 text-right font-bold ${c.totalProfitLoss >= 0 ? 'text-success' : 'text-destructive'}`}>
                                        {formatCurrency(c.totalProfitLoss)}
                                    </td>
                                    <td className={`px-4 py-4 text-right font-semibold ${c.averageProfitLoss >= 0 ? 'text-success' : 'text-destructive'}`}>
                                        {formatCurrency(c.averageProfitLoss)}
                                    </td>
                                    <td className="px-4 py-4 text-right">
                                        <Badge variant={c.profitFactor >= 1.5 ? 'default' : 'outline'} className="text-[10px] font-bold px-1.5 py-0.5">
                                            {c.profitFactor.toFixed(2)}
                                        </Badge>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
             </Card>
          </div>
        )}
        </div>
      </main>
    </div>
  )
}

function StatItem({ 
    title, 
    value, 
    sub, 
    icon: Icon, 
    trend, 
    color 
}: { 
    title: string; 
    value: string; 
    sub?: string | null; 
    icon?: any; 
    trend?: 'up' | 'down'; 
    color?: string 
}) {
    return (
        <Card className="border border-border shadow-sm p-3 md:p-4 bg-card hover:shadow-md transition-all">
            <div className="flex flex-col gap-1">
                <div className="flex items-center justify-between mb-1">
                    <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">{title}</span>
                    {Icon && <Icon className="h-3.5 w-3.5 text-muted-foreground/70" />}
                </div>
                <div className="flex items-baseline gap-1.5">
                    <span className={`text-xl md:text-2xl font-bold tracking-tight ${color || 'text-foreground'}`}>{value}</span>
                    {trend && (
                        <span className={`text-xs font-bold ${trend === 'up' ? 'text-success' : 'text-destructive'}`}>
                            {trend === 'up' ? '▲' : '▼'}
                        </span>
                    )}
                </div>
                {sub && <span className="text-xs font-semibold text-muted-foreground mt-0.5">{sub}</span>}
            </div>
        </Card>
    )
}

function MetricLine({ label, value, color }: { label: string; value: string; color?: string }) {
    return (
        <div className="flex justify-between items-center text-xs">
            <span className="text-muted-foreground font-semibold">{label}</span>
            <span className={`font-bold ${color || 'text-foreground'}`}>{value}</span>
        </div>
    )
}

function ChartCard({ title, icon: Icon, children, compact }: { title: string; icon: any; children: React.ReactNode; compact?: boolean }) {
    return (
        <Card className="border border-border shadow-sm bg-card overflow-hidden">
            <CardHeader className={`flex flex-row items-center gap-2 border-b bg-muted/40 ${compact ? 'py-2 px-3' : 'py-3 px-4'}`}>
                <Icon className={compact ? 'h-3.5 w-3.5 text-primary' : 'h-4 w-4 text-primary'} />
                <CardTitle className={compact ? 'text-xs font-bold text-foreground' : 'text-sm font-bold text-foreground'}>{title}</CardTitle>
            </CardHeader>
            <CardContent className={compact ? 'p-2' : 'p-4'}>
                {children}
            </CardContent>
        </Card>
    )
}
