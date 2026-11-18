'use client'

import { useEffect, useState } from 'react'
import { Wallet, DollarSign, TrendingUp, TrendingDown, RefreshCw } from 'lucide-react'
import { formatCurrency } from '@/lib/utils'

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

export default function APIBalancesSummary() {
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
  }, [])

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <RefreshCw className="h-4 w-4 animate-spin" />
        <span>Loading balances...</span>
      </div>
    )
  }

  return (
    <div className="grid grid-cols-3 gap-2 text-sm sm:flex sm:items-center sm:gap-6">
      {/* DeepSeek Balance */}
      <div className="flex items-center gap-1.5">
        <Wallet className="h-4 w-4 shrink-0 text-muted-foreground" />
        <span className="text-muted-foreground hidden sm:inline">DeepSeek:</span>
        {balances?.deepseek ? (
          <span className={`font-semibold ${balances.deepseek.is_available ? 'text-green-600' : 'text-destructive'}`}>
            ${parseFloat(balances.deepseek.balance_infos[0]?.total_balance || '0').toFixed(2)}
          </span>
        ) : (
          <span className="text-muted-foreground">N/A</span>
        )}
      </div>

      {/* MetaAPI Credits */}
      <div className="flex items-center gap-1.5">
        <DollarSign className="h-4 w-4 shrink-0 text-muted-foreground" />
        <span className="text-muted-foreground hidden sm:inline">MetaAPI:</span>
        {balances?.metaapi_billing ? (
          <span className="font-semibold text-primary">
            ${(balances.metaapi_billing.amount + balances.metaapi_billing.trialAmount).toFixed(2)}
          </span>
        ) : (
          <span className="text-muted-foreground">N/A</span>
        )}
      </div>

      {/* Trading Account */}
      <div className="flex items-center gap-1.5">
        {balances?.metaapi_trading && balances.metaapi_trading.profitLoss >= 0 ? (
          <TrendingUp className="h-4 w-4 shrink-0 text-green-600" />
        ) : (
          <TrendingDown className="h-4 w-4 shrink-0 text-destructive" />
        )}
        <span className="text-muted-foreground hidden sm:inline">Trading:</span>
        {balances?.metaapi_trading ? (
          <span className="font-semibold">
            {formatCurrency(balances.metaapi_trading.balance, balances.metaapi_trading.currency)}
          </span>
        ) : (
          <span className="text-muted-foreground">N/A</span>
        )}
      </div>
    </div>
  )
}
