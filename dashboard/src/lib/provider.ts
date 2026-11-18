/**
 * Centralized Trading Provider Configuration
 * Single source of truth for provider-related logic
 */

export type TradingProvider = 'mt5rest' | 'metaapi'

export interface ProviderConfig {
  name: TradingProvider
  label: string
  displayName: string
  ismt5rest: boolean
  icon: 'server' | 'cloud'
  color: {
    bg: string
    text: string
    icon: string
  }
}

/**
 * Get the current trading provider from environment
 */
export function getTradingProvider(): TradingProvider {
  const provider = (process.env.TRADING_PROVIDER || 'metaapi').toLowerCase().trim()
  return provider === 'mt5rest' ? 'mt5rest' : 'metaapi'
}


const PYTHON_API_URL = process.env.PYTHON_API_URL || 'http://localhost:8001'
const ACTIVE_CACHE_MS = 3_000
let activeCache: { value: TradingProvider; at: number } | null = null

function normalizeProvider(raw: unknown): TradingProvider | null {
  const v = String(raw ?? '').toLowerCase().trim()
  return v === 'mt5rest' || v === 'metaapi' ? v : null
}

/**
 * The provider the bot is trading on RIGHT NOW. The bot can switch providers at runtime
 * (no restart), so the container's TRADING_PROVIDER env var is only the startup value.
 * Resolution: bot's /api/provider (live) -> settings table -> env. Cached for a few seconds.
 */
export async function getActiveProvider(): Promise<TradingProvider> {
  const now = Date.now()
  if (activeCache && now - activeCache.at < ACTIVE_CACHE_MS) return activeCache.value

  let resolved: TradingProvider | null = null
  try {
    const res = await fetch(`${PYTHON_API_URL}/api/provider`, { cache: 'no-store', signal: AbortSignal.timeout(2_000) })
    if (res.ok) resolved = normalizeProvider((await res.json())?.active)
  } catch {
    // bot unreachable: fall through to the stored setting
  }
  if (!resolved) {
    try {
      const { prisma } = await import('@/lib/prisma')
      const row = await prisma.setting.findUnique({ where: { key: 'TRADING_PROVIDER' } })
      resolved = normalizeProvider(row?.value)
    } catch {
      // DB unavailable: fall through to env
    }
  }
  const value = resolved ?? getTradingProvider()
  activeCache = { value, at: now }
  return value
}

/** Drop the cached provider (call right after a switch so the next request sees the new one). */
export function invalidateActiveProvider(): void {
  activeCache = null
}

/**
 * Get provider configuration
 */
export function getProviderConfig(provider?: TradingProvider): ProviderConfig {
  const currentProvider = provider || getTradingProvider()
  
  if (currentProvider === 'mt5rest') {
    return {
      name: 'mt5rest',
      label: 'MT5 REST',
      displayName: 'MT5 REST API',
      ismt5rest: true,
      icon: 'server',
      color: {
        bg: 'bg-blue-50',
        text: 'text-blue-700',
        icon: 'text-blue-600',
      },
    }
  }
  
  return {
    name: 'metaapi',
    label: 'MetaAPI',
    displayName: 'MetaAPI Cloud',
    ismt5rest: false,
    icon: 'cloud',
    color: {
      bg: 'bg-violet-50',
      text: 'text-violet-700',
      icon: 'text-violet-600',
    },
  }
}

/**
 * Check if current provider is MT5 REST
 */
export function isMT5RestProvider(): boolean {
  return getTradingProvider() === 'mt5rest'
}

/**
 * Get MT5 REST API configuration
 */
export function getMT5RestConfig() {
  return {
    url: process.env.MT5_REST_API_URL || 'http://mt5:5001',
    apiKey: process.env.MT5_REST_API_KEY || '',
  }
}

/**
 * Get MetaAPI configuration
 */
export function getMetaAPIConfig() {
  return {
    token: process.env.METAAPI_TOKEN || '',
    accountId: process.env.METAAPI_ACCOUNT_ID || '',
    statsUrl: 'https://metastats-api-v1.london.agiliumtrade.ai',
  }
}
