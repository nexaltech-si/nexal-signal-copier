'use client'

import { useEffect, useState } from 'react'
import { 
  Wallet, 
  DollarSign, 
  Target,
  TrendingUp,
  RefreshCw
} from 'lucide-react'
import { formatCurrency, cn } from '@/lib/utils'

interface DeepSeekBalance {
  is_available: boolean
  balance_infos: Array<{
    currency: string
    total_balance: string
    granted_balance: string
    topped_up_balance: string
  }>
}

interface MetaAPIBillingBalance {
  amount: number
  trialAmount: number
}

interface MetaAPIAccountInfo {
  balance: number
  equity: number
  margin: number
  freeMargin: number
  currency: string
  leverage: number
  profitLoss: number
}

interface BalancesData {
  deepseek?: DeepSeekBalance
  metaapi_billing?: MetaAPIBillingBalance
  metaapi_trading?: MetaAPIAccountInfo
  errors: string[]
}

export default function APIBalancesCard() {
  const [balances, setBalances] = useState<BalancesData | null>(null)
  const [loading, setLoading] = useState(true)

  const fetchBalances = async () => {
    setLoading(true)
    try {
      const response = await fetch('/api/balances')
      const data = await response.json()
      setBalances(data)
    } catch (error) {
      console.error('Error fetching balances:', error)
      setBalances({ errors: ['Failed to fetch balances'] })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchBalances()
    const interval = setInterval(fetchBalances, 5 * 60 * 1000)
    return () => clearInterval(interval)
  }, [])

  const deepseekBalance = parseFloat(balances?.deepseek?.balance_infos[0]?.total_balance ?? '0')
  const creditsBalance = balances?.metaapi_billing ? (balances.metaapi_billing.amount + balances.metaapi_billing.trialAmount) : 0
  const tradingBalance = balances?.metaapi_trading?.balance || 0
  const tradingPL = balances?.metaapi_trading?.profitLoss || 0

  return (
    <>
      {/* Classy Mobile Grid */}
      <div className="md:hidden grid grid-cols-3 gap-2.5 mb-2 relative z-10">
        {/* DeepSeek */}
        <div className="flex items-center gap-2">
          <div className="w-9 h-9 rounded-xl bg-white/60 shadow-[0_5px_14px_rgba(28,34,74,0.04)] flex items-center justify-center text-muted-foreground">
            <Wallet className="w-5 h-5" />
          </div>
          <div className="flex flex-col">
            <div className={cn(
              "text-[11px] font-bold tabular-nums",
              deepseekBalance > 5 ? "text-[#16b36a]" : "text-[#df1414]"
            )}>
              {loading ? '...' : `$${deepseekBalance.toFixed(2)}`}
            </div>
            <div className="text-[9px] text-[#6b7288] uppercase font-bold tracking-tight">AI Credits</div>
          </div>
        </div>

        {/* MetaAPI Credits */}
        <div className="flex items-center gap-2">
          <div className="w-9 h-9 rounded-xl bg-white/60 shadow-[0_5px_14px_rgba(28,34,74,0.04)] flex items-center justify-center text-[#2f7bf1]">
            <DollarSign className="w-5 h-5" />
          </div>
          <div className="flex flex-col">
            <div className={cn(
              "text-[11px] font-bold tabular-nums",
              creditsBalance > 5 ? "text-[#2f7bf1]" : "text-[#df1414]"
            )}>
              {loading ? '...' : `$${creditsBalance.toFixed(2)}`}
            </div>
            <div className="text-[9px] text-[#6b7288] uppercase font-bold tracking-tight">API Credits</div>
          </div>
        </div>

        {/* Trading Account */}
        <div className="flex items-center gap-2">
          <div className={cn(
            "w-9 h-9 rounded-xl flex items-center justify-center transition-colors shadow-[0_5px_14px_rgba(28,34,74,0.04)]",
            tradingPL >= 0 ? "bg-[#e6f7ec] text-[#16b36a]" : "bg-[#fde2e4] text-[#df1414]"
          )}>
            {tradingPL >= 0 ? <TrendingUp className="w-5 h-5" /> : <Target className="w-5 h-5" />}
          </div>
          <div className="flex flex-col">
            <div className="text-[11px] font-bold tabular-nums text-foreground truncate max-w-[80px]">
              {loading ? '...' : formatCurrency(tradingBalance, balances?.metaapi_trading?.currency)}
            </div>
            <div className="text-[9px] text-[#6b7288] uppercase font-bold tracking-tight">Account</div>
          </div>
        </div>
      </div>

      {/* Standard Desktop Row */}
      <div className="hidden md:block tech-card rounded-xl overflow-hidden mb-6">
        <div className="grid grid-cols-1 md:grid-cols-3 divide-y md:divide-y-0 md:divide-x divide-slate-100">
          <div className="p-4 flex items-center gap-4">
            <div className="w-10 h-10 rounded-lg bg-muted/50 flex items-center justify-center text-muted-foreground">
              <Wallet className="w-5 h-5" />
            </div>
            <div>
              <div className="text-[10px] text-muted-foreground font-bold uppercase tracking-wider">AI API Credits</div>
              <div className={cn(
                "text-lg font-bold tabular-nums",
                deepseekBalance > 5 ? "text-success" : "text-destructive"
              )}>
                {loading ? '...' : `$${deepseekBalance.toFixed(2)}`}
              </div>
            </div>
          </div>

          <div className="p-4 flex items-center gap-4">
            <div className="w-10 h-10 rounded-lg bg-muted/50 flex items-center justify-center text-muted-foreground">
              <DollarSign className="w-5 h-5" />
            </div>
            <div>
              <div className="text-[10px] text-muted-foreground font-bold uppercase tracking-wider">MetaAPI Credits</div>
              <div className={cn(
                "text-lg font-bold tabular-nums",
                creditsBalance > 5 ? "text-primary" : "text-destructive"
              )}>
                {loading ? '...' : `$${creditsBalance.toFixed(2)}`}
              </div>
            </div>
          </div>

          <div className="p-4 flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className={cn(
                "w-10 h-10 rounded-lg flex items-center justify-center",
                tradingPL >= 0 ? "bg-success/10 text-success" : "bg-destructive/10 text-destructive"
              )}>
                {tradingPL >= 0 ? <TrendingUp className="w-5 h-5" /> : <Target className="w-5 h-5" />}
              </div>
              <div>
                <div className="text-[10px] text-muted-foreground font-bold uppercase tracking-wider">Trading Account</div>
                <div className="text-lg font-bold tabular-nums text-foreground">
                  {loading ? '...' : formatCurrency(tradingBalance, balances?.metaapi_trading?.currency)}
                </div>
              </div>
            </div>
            <button onClick={fetchBalances} disabled={loading} className="p-2 hover:bg-muted/50 rounded-lg text-muted-foreground/70 transition-colors">
              <RefreshCw className={cn("w-4 h-4", loading && "animate-spin")} />
            </button>
          </div>
        </div>
      </div>
    </>
  )
}
