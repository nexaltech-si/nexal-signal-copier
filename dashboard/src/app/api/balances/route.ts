import { NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'
import { getActiveProvider } from '@/lib/provider'

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

export async function GET() {
  const denied = await requireOwner()
  if (denied) return denied

  const results: {
    deepseek?: DeepSeekBalance
    metaapi_billing?: MetaAPIBillingBalance
    metaapi_trading?: MetaAPIAccountInfo
    errors: string[]
  } = {
    errors: [],
  }

  // Get environment variables
  const deepseekKey = process.env.DEEPSEEK_API_KEY
  const metaapiToken = process.env.METAAPI_TOKEN
  const metaapiAccountId = process.env.METAAPI_ACCOUNT_ID

  // Fetch DeepSeek balance
  if (deepseekKey) {
    try {
      const response = await fetch('https://api.deepseek.com/v1/user/balance', {
        headers: {
          Authorization: `Bearer ${deepseekKey}`,
          'Content-Type': 'application/json',
        },
        next: { revalidate: 300 }, // Cache for 5 minutes
      })

      if (response.ok) {
        results.deepseek = await response.json()
      } else {
        results.errors.push(`DeepSeek API error: ${response.status}`)
      }
    } catch (error) {
      results.errors.push(`DeepSeek fetch error: ${error instanceof Error ? error.message : 'Unknown error'}`)
    }
  } else {
    results.errors.push('DEEPSEEK_API_KEY not configured')
  }

  // Fetch MetaAPI billing balance
  if (metaapiToken) {
    try {
      const response = await fetch(
        'https://billing-api-v1.agiliumtrade.agiliumtrade.ai/users/current/balance',
        {
          headers: {
            'auth-token': metaapiToken,
            'Content-Type': 'application/json',
            Accept: 'application/json',
          },
          next: { revalidate: 300 }, // Cache for 5 minutes
        }
      )

      if (response.ok) {
        results.metaapi_billing = await response.json()
      } else if (response.status === 403) {
        // Token doesn't have billing access - this is normal
        results.errors.push('MetaAPI token does not have billing API access (normal for trading tokens)')
      } else {
        results.errors.push(`MetaAPI billing error: ${response.status}`)
      }
    } catch (error) {
      results.errors.push(`MetaAPI billing fetch error: ${error instanceof Error ? error.message : 'Unknown error'}`)
    }
  } else {
    results.errors.push('METAAPI_TOKEN not configured')
  }

  // Fetch trading account info - provider-aware
  const tradingProvider = await getActiveProvider()
  const mt5RestUrl = process.env.MT5_REST_API_URL || 'http://mt5:5001'
  const mt5RestApiKey = process.env.MT5_REST_API_KEY || ''

  if (tradingProvider === 'mt5rest') {
    // Use self-hosted MT5 REST API for account info
    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (mt5RestApiKey) {
        headers['X-API-Key'] = mt5RestApiKey
      }

      const response = await fetch(`${mt5RestUrl}/account_info`, {
        headers,
        cache: 'no-store',
      })

      if (response.ok) {
        const accountInfo = await response.json()
        results.metaapi_trading = {
          balance: accountInfo.balance || 0,
          equity: accountInfo.equity || 0,
          margin: accountInfo.margin || 0,
          freeMargin: accountInfo.margin_free || 0,
          currency: accountInfo.currency || 'USD',
          leverage: accountInfo.leverage || 0,
          profitLoss: (accountInfo.equity || 0) - (accountInfo.balance || 0),
        }
      } else {
        results.errors.push(`MT5 REST API error: ${response.status}`)
      }
    } catch (error) {
      results.errors.push(`MT5 REST API fetch error: ${error instanceof Error ? error.message : 'Unknown error'}`)
    }
  } else if (metaapiToken && metaapiAccountId) {
    // Use MetaAPI Cloud REST API for account info
    const regions = ['london', 'new-york', 'singapore']
    let accountInfo = null
    
    for (const region of regions) {
      try {
        const url = `https://mt-client-api-v1.${region}.agiliumtrade.ai/users/current/accounts/${metaapiAccountId}/account-information`
        
        const response = await fetch(url, {
          headers: {
            'auth-token': metaapiToken,
            'Content-Type': 'application/json',
            Accept: 'application/json',
          },
          next: { revalidate: 60 }, // Cache for 1 minute
        })

        if (response.ok) {
          accountInfo = await response.json()
          break // Found it!
        }
      } catch {
        // Try next region
        continue
      }
    }

    if (accountInfo) {
      results.metaapi_trading = {
        balance: accountInfo.balance || 0,
        equity: accountInfo.equity || 0,
        margin: accountInfo.margin || 0,
        freeMargin: accountInfo.freeMargin || 0,
        currency: accountInfo.currency || 'USD',
        leverage: accountInfo.leverage || 0,
        profitLoss: (accountInfo.equity || 0) - (accountInfo.balance || 0),
      }
    } else {
      results.errors.push('MetaAPI trading account not synchronized or not found')
    }
  } else if (!metaapiAccountId && metaapiToken) {
    results.errors.push('METAAPI_ACCOUNT_ID not configured')
  }

  return NextResponse.json(results)
}
