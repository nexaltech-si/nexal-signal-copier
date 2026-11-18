'use client'

import { useState, useEffect, useCallback } from 'react'
import { 
  Shield, 
  TrendingDown, 
  AlertTriangle, 
  CheckCircle, 
  Activity,
  Clock,
  Server,
  Cloud, 
  ArrowRight,
  ShieldCheck,
  RefreshCw
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import MobilePageHeader from '@/components/MobilePageHeader'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import DrawdownGauge from '@/components/DrawdownGauge'
import { formatDate, formatCurrency } from '@/lib/utils'

function formatTime(date: string | null): string {
  if (!date) return '—'
  return new Intl.DateTimeFormat('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(date))
}

interface DrawdownBreach {
  id: string
  breachType: string
  drawdownPercent: number
  limitPercent: number
  accountId: string
  trackerId: string
  tradingPaused: boolean
  pausedAt: string
  resumedAt: string | null
  losersClosedCount: number
  closedPositionIds: string[]
  brokerTime: string | null
  brokerDate: string | null
  isActive: boolean
  resolvedAt: string | null
  resolvedReason: string | null
  createdAt: string
}

interface DrawdownStats {
  total: number
  active: number
  resolved: number
  totalPositionsClosed: number
  byType: Array<{
    type: string
    count: number
    avgDrawdown: string
    totalPositionsClosed: number
  }>
}

interface LiveDrawdown {
  balance: number
  equity: number
  drawdownAmount: number
  drawdownPercent: number
  isInDrawdown: boolean
}

interface ProviderInfo {
  name: string
  label: string
  ismt5rest: boolean
  cloudTrackersAvailable: boolean
}

interface DrawdownLimits {
  daily: number
  overall: number
}

export function DrawdownContent({ asTab = false }: { asTab?: boolean }) {
  const [breaches, setBreaches] = useState<DrawdownBreach[]>([])
  const [stats, setStats] = useState<DrawdownStats | null>(null)
  const [liveDrawdown, setLiveDrawdown] = useState<LiveDrawdown | null>(null)
  const [provider, setProvider] = useState<ProviderInfo | null>(null)
  const [limits, setLimits] = useState<DrawdownLimits | null>(null)
  const [availableLevels, setAvailableLevels] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [statusFilter, setStatusFilter] = useState('all')
  const [refreshInterval, setRefreshInterval] = useState(10)
  const [resetting, setResetting] = useState(false)

  const handleResetBreach = async () => {
    if (!confirm('Are you sure you want to manually reset the drawdown breach? Trading will resume.')) return
    setResetting(true)
    try {
      const res = await fetch('/api/drawdown/reset', { method: 'POST' })
      const data = await res.json()
      if (data.success) {
        await fetchDrawdownData()
      } else {
        alert(data.message || data.error || 'Failed to reset breach')
      }
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Failed to reset breach')
    } finally {
      setResetting(false)
    }
  }

  const fetchDrawdownData = useCallback(async () => {
    try {
      const params = new URLSearchParams({
        status: statusFilter,
        limit: '50',
      })

      const response = await fetch(`/api/drawdown?${params}`)
      const result = await response.json()

      if (result.success) {
        setBreaches(result.data.breaches)
        setStats(result.data.stats)
        setAvailableLevels(result.data.filters?.levels || [])
        if (result.data.liveDrawdown) setLiveDrawdown(result.data.liveDrawdown)
        if (result.data.provider) setProvider(result.data.provider)
        if (result.data.limits) setLimits(result.data.limits)
      } else {
        console.error(result.error)
      }
    } catch (err: unknown) {
      console.error(err instanceof Error ? err.message : 'Failed to fetch drawdown data')
    } finally {
      setLoading(false)
    }
  }, [statusFilter])

  useEffect(() => {
    fetchDrawdownData()
  }, [fetchDrawdownData])

  useEffect(() => {
    const interval = setInterval(() => {
      fetchDrawdownData()
    }, refreshInterval * 1000)

    return () => clearInterval(interval)
  }, [refreshInterval, fetchDrawdownData])

  const getRiskScore = () => {
    if (!liveDrawdown || !limits) return 0
    const dailyRatio = liveDrawdown.drawdownPercent / limits.daily
    const overallRatio = liveDrawdown.drawdownPercent / limits.overall
    const maxRatio = Math.max(dailyRatio, overallRatio)
    return Math.min(100, Math.round(maxRatio * 100))
  }

  const riskScore = getRiskScore()
  const riskColor = riskScore >= 90 ? 'text-destructive' : riskScore >= 70 ? 'text-orange-500' : riskScore >= 40 ? 'text-yellow-600' : 'text-success'
  const riskLabel = riskScore >= 90 ? 'CRITICAL' : riskScore >= 70 ? 'HIGH' : riskScore >= 40 ? 'ELEVATED' : 'SAFE'

  if (loading && breaches.length === 0) {
    return (
      <div className={asTab ? "flex h-40 items-center justify-center" : "flex h-[calc(100vh-4rem)] items-center justify-center"}>
        <div className="animate-pulse flex flex-col items-center gap-4">
          <Shield className="h-12 w-12 text-muted-foreground/20" />
          <p className="text-sm font-medium text-muted-foreground">Initializing protection monitor...</p>
        </div>
      </div>
    )
  }

  return (
    <div className={asTab ? "flex flex-col pb-10" : "flex flex-col min-h-full pb-10"}>
      {!asTab && (
        <MobilePageHeader
          title="Drawdown"
          subtitle="Risk Management"
          hidden
          icon={<Shield className="h-5 w-5" />}
        />
      )}
      {!asTab && (
        <header className="hidden md:flex sticky top-0 z-40 w-full tech-header">
          <div className="max-w-[1800px] w-full mx-auto flex h-14 items-center px-6 gap-3">
            <div className="p-1.5 rounded-lg bg-primary/10 border border-primary/20">
              <Shield className="h-5 w-5 text-primary" />
            </div>
            <div className="flex flex-col">
              <h1 className="text-sm font-bold text-foreground leading-none">Drawdown</h1>
              <p className="text-[10px] text-[#6b7288] font-bold uppercase tracking-wider mt-1">Risk Management</p>
            </div>
            <div className="ml-auto flex items-center gap-2">
              {provider && (
                <div className="hidden md:flex items-center gap-1.5 opacity-70">
                  {provider.ismt5rest ? <Server className="h-3 w-3 text-primary" /> : <Cloud className="h-3 w-3 text-muted-foreground" />}
                  <span className="text-[10px] font-bold text-muted-foreground uppercase">{provider.label}</span>
                </div>
              )}
              <div className="h-4 w-px bg-muted mx-1 hidden md:block" />
              <div className="flex items-center gap-2 bg-muted/50 py-0.5 px-1 rounded-md">
                <button
                  onClick={fetchDrawdownData}
                  className="p-1 rounded-sm hover:bg-background transition-all group"
                >
                  <Activity className="h-3 w-3 text-muted-foreground group-hover:text-primary" />
                </button>
                <select
                  value={refreshInterval}
                  onChange={(e) => setRefreshInterval(Number(e.target.value))}
                  className="bg-transparent text-[10px] font-bold outline-none cursor-pointer"
                >
                  <option value={5}>5s</option>
                  <option value={10}>10s</option>
                  <option value={30}>30s</option>
                </select>
              </div>
            </div>
          </div>
        </header>
      )}

      <main className="flex-1 px-3 md:px-4 py-4 md:py-6 space-y-4 md:space-y-6 max-w-7xl mx-auto w-full">
        {/* Status Alert Banner */}
        {stats?.active ? (
          <div className="relative overflow-hidden rounded-2xl bg-red-600 p-6 text-white shadow-lg shadow-red-200 dark:shadow-red-900/20">
            <div className="relative z-10 flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className="flex h-12 w-12 items-center justify-center rounded-full bg-white/20 backdrop-blur-sm">
                  <AlertTriangle className="h-7 w-7 animate-pulse" />
                </div>
                <div>
                  <h2 className="text-xl font-bold">Active Breach Detected</h2>
                  <p className="text-sm text-red-100 font-medium">Trading is currently paused on {stats.active} tracker(s).</p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <Badge className="bg-card text-destructive hover:bg-card/90 px-4 py-1 text-xs font-bold">PAUSED</Badge>
                <button
                  onClick={handleResetBreach}
                  disabled={resetting}
                  className="flex items-center gap-2 px-4 py-2 rounded-lg bg-white/20 hover:bg-white/30 text-white font-bold text-xs uppercase tracking-wide transition-all disabled:opacity-50 border border-white/20"
                >
                  <RefreshCw className={`h-4 w-4 ${resetting ? 'animate-spin' : ''}`} />
                  {resetting ? 'Resetting...' : 'Reset Breach'}
                </button>
              </div>
            </div>
            <div className="absolute -right-8 -top-8 h-32 w-32 rounded-full bg-white/5 blur-3xl" />
          </div>
        ) : (
          <div className="rounded-2xl bg-emerald-500/10 border border-emerald-500/20 p-6 shadow-sm">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className="flex h-12 w-12 items-center justify-center rounded-full bg-emerald-500/20">
                  <ShieldCheck className="h-7 w-7 text-success" />
                </div>
                <div>
                  <h2 className="text-lg font-bold text-foreground dark:text-white">System Shield Active</h2>
                  <p className="text-sm text-success font-bold">Account is protected and trading is normal.</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <div className="flex h-2 w-2 rounded-full bg-emerald-500 animate-ping" />
                <span className="text-[10px] font-bold text-success uppercase tracking-widest">Live monitoring</span>
              </div>
            </div>
          </div>
        )}

        {/* Core Live Data Area */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 md:gap-6">
          {/* Gauges Card */}
          <Card className="lg:col-span-8 border-none shadow-xl bg-background/60 backdrop-blur-sm">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
                <Activity className="h-4 w-4 text-primary" />
                Live Drawdown Gauges
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-col md:flex-row items-center justify-around py-4 gap-6 md:gap-8">
                {liveDrawdown && limits ? (
                  <>
                    <DrawdownGauge 
                      value={liveDrawdown.drawdownPercent} 
                      limit={limits.daily} 
                      label="Daily Limit" 
                      size={160}
                    />
                    <div className="h-32 w-px bg-muted hidden md:block" />
                    <DrawdownGauge 
                      value={liveDrawdown.drawdownPercent} 
                      limit={limits.overall} 
                      label="Overall Limit" 
                      size={160}
                    />
                  </>
                ) : (
                  <div className="h-48 flex items-center justify-center text-muted-foreground italic text-sm">
                    Live data currently unavailable
                  </div>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Account & Risk Column */}
          <div className="lg:col-span-4 space-y-4 md:space-y-6">
            {/* Risk Score */}
            <Card className={`border-none shadow-xl overflow-hidden`}>
              <div className={`h-1.5 w-full ${riskScore >= 70 ? 'bg-red-500' : riskScore >= 40 ? 'bg-orange-500' : 'bg-emerald-500'}`} />
              <CardContent className="pt-6">
                <div className="flex justify-between items-start mb-4">
                  <div>
                    <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Breach Risk Score</p>
                    <p className="text-3xl font-black mt-1 tracking-tight">{riskScore}<span className="text-lg text-muted-foreground/40 italic">/100</span></p>
                  </div>
                  <Badge className={`${riskColor} bg-transparent border-0 font-black text-xs`}>{riskLabel}</Badge>
                </div>
                <div className="h-2 w-full bg-muted rounded-full overflow-hidden">
                  <div 
                    className={`h-full transition-all duration-1000 ${riskScore >= 70 ? 'bg-red-500' : riskScore >= 40 ? 'bg-orange-500' : 'bg-emerald-500'}`}
                    style={{ width: `${riskScore}%` }}
                  />
                </div>
              </CardContent>
            </Card>

            {/* Account Snapshot */}
            <Card className="border-none shadow-xl">
              <CardContent className="pt-6 space-y-5">
                <div className="flex justify-between items-center group">
                  <span className="text-xs font-bold text-muted-foreground uppercase">Balance</span>
                  <span className="text-lg font-mono font-bold tracking-tight">
                    {formatCurrency(liveDrawdown?.balance || 0)}
                  </span>
                </div>
                <div className="flex justify-between items-center group">
                  <span className="text-xs font-bold text-muted-foreground uppercase">Equity</span>
                  <span className={`text-lg font-mono font-bold tracking-tight ${liveDrawdown?.isInDrawdown ? 'text-destructive' : 'text-success'}`}>
                    {formatCurrency(liveDrawdown?.equity || 0)}
                  </span>
                </div>
                <div className="pt-3 border-t border-muted">
                  <div className="flex justify-between items-center">
                    <span className="text-[10px] font-black text-muted-foreground uppercase tracking-widest">Floating Drawdown</span>
                    <span className={`text-xl font-mono font-black ${liveDrawdown?.isInDrawdown ? 'text-destructive' : 'text-success'}`}>
                      -{formatCurrency(liveDrawdown?.drawdownAmount || 0)}
                    </span>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>

        {/* Statistics Tiles */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 md:gap-4">
          {[
            { label: 'Total Breaches', value: stats?.total || 0, icon: TrendingDown, color: 'text-primary' },
            { label: 'Active Issues', value: stats?.active || 0, icon: AlertTriangle, color: 'text-destructive' },
            { label: 'Risk Recovered', value: stats?.resolved || 0, icon: CheckCircle, color: 'text-success' },
            { label: 'Loss Mitigated', value: stats?.totalPositionsClosed || 0, icon: Activity, color: 'text-orange-500' },
          ].map((item, i) => (
            <Card key={i} className="border-none shadow-md hover:shadow-lg transition-all group overflow-hidden">
              <CardContent className="p-3 md:p-5">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">{item.label}</span>
                  <item.icon className={`h-4 w-4 ${item.color} group-hover:scale-110 transition-transform`} />
                </div>
                <p className="text-2xl font-black tracking-tight">{item.value}</p>
              </CardContent>
            </Card>
          ))}
        </div>

        {/* Breach Timeline Section */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-bold flex items-center gap-2">
              <Clock className="h-5 w-5 text-muted-foreground" />
              Breach Analytics & History
            </h3>
            <div className="flex gap-2">
              <select 
                value={statusFilter} 
                onChange={(e) => setStatusFilter(e.target.value)}
                className="text-[10px] font-bold border rounded-lg px-2 py-1 bg-background uppercase focus:ring-0"
              >
                <option value="all">All Events</option>
                <option value="active">Active Only</option>
                <option value="resolved">Resolved Only</option>
              </select>
            </div>
          </div>

          {breaches.length === 0 ? (
            <Card className="border border-border shadow-sm bg-muted/30 py-16">
              <CardContent className="flex flex-col items-center text-center">
                <CheckCircle className="h-16 w-16 text-success/20 mb-4" />
                <p className="font-bold text-muted-foreground/70">Perfect Record</p>
                <p className="text-xs text-muted-foreground mt-1">No breaches have been recorded on this account.</p>
              </CardContent>
            </Card>
          ) : (
            <Card className="border border-border shadow-sm bg-card overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="bg-muted border-b text-foreground/80 font-bold">
                    <tr>
                      <th className="px-4 py-3 text-left">Date</th>
                      <th className="px-4 py-3 text-left">Type</th>
                      <th className="px-4 py-3 text-right">Peak DD</th>
                      <th className="px-4 py-3 text-right">Limit</th>
                      <th className="px-4 py-3 text-right">Closed</th>
                      <th className="px-4 py-3 text-left">Downtime</th>
                      <th className="px-4 py-3 text-left">Tracker</th>
                      <th className="px-4 py-3 text-right">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {breaches.map((breach) => (
                      <tr key={breach.id} className={`hover:bg-muted/50 transition-colors ${breach.isActive ? 'bg-red-500/5' : ''}`}>
                        <td className="px-4 py-3 text-muted-foreground font-semibold whitespace-nowrap">
                          {formatDate(breach.createdAt)}
                        </td>
                        <td className="px-4 py-3">
                          <Badge className={`${breach.breachType === 'DAILY' ? 'bg-orange-100 text-orange-700' : 'bg-purple-100 text-purple-700'} border-0 px-2 py-0.5 text-[10px] font-black uppercase`}>
                            {breach.breachType}
                          </Badge>
                        </td>
                        <td className="px-4 py-3 text-right font-bold text-destructive">
                          {breach.drawdownPercent.toFixed(2)}%
                        </td>
                        <td className="px-4 py-3 text-right text-muted-foreground font-semibold">
                          {breach.limitPercent}%
                        </td>
                        <td className="px-4 py-3 text-right font-semibold text-foreground">
                          {breach.losersClosedCount}
                          {breach.closedPositionIds.length > 0 && (
                            <span className="ml-1 text-muted-foreground font-mono text-[10px]" title={breach.closedPositionIds.map((pid) => `#${pid}`).join(', ')}>
                              ({breach.closedPositionIds.length} ids)
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap">
                          <div className="flex items-center gap-1.5 text-foreground/80 font-semibold">
                            <span>{formatTime(breach.pausedAt)}</span>
                            <ArrowRight className="h-3 w-3 text-muted-foreground shrink-0" />
                            <span>{breach.resumedAt ? formatTime(breach.resumedAt) : 'Ongoing'}</span>
                          </div>
                        </td>
                        <td className="px-4 py-3 font-mono text-[10px] text-muted-foreground truncate max-w-[140px]">
                          {breach.trackerId || 'System Managed'}
                        </td>
                        <td className="px-4 py-3 text-right">
                          {breach.isActive ? (
                            <Badge className="bg-red-100 text-destructive border-0 inline-flex items-center gap-1 text-[10px] font-bold px-2">
                              <AlertTriangle className="h-3 w-3" /> ACTIVE
                            </Badge>
                          ) : (
                            <Badge className="bg-success/10 text-success border-0 inline-flex items-center gap-1 text-[10px] font-bold px-2">
                              <CheckCircle className="h-3 w-3" /> RESOLVED
                            </Badge>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </div>
      </main>
    </div>
  )
}

export default function DrawdownPage() {
  return <DrawdownContent />
}
