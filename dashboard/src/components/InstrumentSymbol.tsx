'use client'

import Image from 'next/image'
import InstrumentIcon from '@/components/InstrumentIcon'

// ── Currency → ISO-2 country code (for flag SVGs under /flags/l) ──
export const CURRENCY_TO_COUNTRY: Record<string, string> = {
  EUR: 'EU', USD: 'US', GBP: 'GB', JPY: 'JP',
  CHF: 'CH', AUD: 'AU', CAD: 'CA', NZD: 'NZ',
  SEK: 'SE', NOK: 'NO', DKK: 'DK', SGD: 'SG',
  HKD: 'HK', CNH: 'CN', CNY: 'CN', MXN: 'MX',
  ZAR: 'ZA', TRY: 'TR', HUF: 'HU', PLN: 'PL',
  CZK: 'CZ', RUB: 'RU', INR: 'IN', BRL: 'BR',
  THB: 'TH',
}

export type InstrumentInfo = {
  type: 'commodity' | 'index' | 'crypto' | 'forex' | 'stock'
  iconType?: 'gold' | 'silver' | 'platinum' | 'palladium' | 'oil' | 'gas' | 'copper' | 'index' | 'crypto'
  iconUrl?: string
  base?: string
  quote?: string
  iconColor?: string
  color?: string
  /** Emoji fallback for the plain-stock case (used by the Account page rows). */
  icon?: string
}

/**
 * Classifies a trading symbol into an instrument type + icon hints.
 * Consolidated from the Account page so every surface (dashboard, account,
 * calendar) renders symbols the same professional way.
 */
export function getInstrumentInfo(symbol: string): InstrumentInfo {
  const sym = (symbol || '').toUpperCase()
  if (sym.includes('XAU') || sym.includes('GOLD'))
    return { type: 'commodity', iconType: 'gold', color: 'from-slate-800 to-slate-900', iconColor: 'text-gold/80' }
  if (sym.includes('XAG') || sym.includes('SILVER'))
    return { type: 'commodity', iconType: 'silver', color: 'from-slate-300 to-slate-500' }
  if (sym.includes('OIL') || sym.includes('WTI') || sym.includes('BRENT'))
    return { type: 'commodity', iconType: 'oil', color: 'from-stone-700 to-stone-900' }
  if (sym.includes('US30') || sym.includes('NAS') || sym.includes('SPX') || sym.includes('DAX') || sym.includes('GER') || sym.includes('UK100'))
    return { type: 'index', iconType: 'index', color: 'from-blue-600 to-indigo-800' }

  if (sym.includes('BTC'))
    return { type: 'crypto', iconUrl: 'https://www.cryptocompare.com/media/37746251/btc.png', color: 'from-orange-400 to-orange-600' }
  if (sym.includes('ETH'))
    return { type: 'crypto', iconUrl: 'https://www.cryptocompare.com/media/37746238/eth.png', color: 'from-purple-500 to-purple-700' }

  // Strip broker suffixes (.c, .m, +, -, trailing digits) so EURUSD.c → EURUSD
  const clean = sym.replace(/[^A-Z]/g, '')
  const base = clean.substring(0, 3)
  const quote = clean.substring(3, 6)
  if (CURRENCY_TO_COUNTRY[base] && CURRENCY_TO_COUNTRY[quote])
    return {
      type: 'forex',
      base: CURRENCY_TO_COUNTRY[base],
      quote: CURRENCY_TO_COUNTRY[quote],
      color: 'from-blue-400 to-blue-600',
    }

  return { type: 'stock', icon: '📈', color: 'from-slate-400 to-slate-600' }
}

const SIZE_MAP = {
  sm: { box: 'w-8 h-8', icon: 'w-4 h-4', flag: 'w-5 h-5', flagSpace: '-space-x-2' },
  md: { box: 'w-10 h-10', icon: 'w-6 h-6', flag: 'w-7 h-7', flagSpace: '-space-x-3' },
  lg: { box: 'w-12 h-12', icon: 'w-10 h-10', flag: 'w-8 h-8', flagSpace: '-space-x-3' },
} as const

/**
 * Professional instrument icon for any trading symbol:
 * metal/oil/index glyphs, crypto logos, or dual overlapping country flags
 * for forex pairs — matching the Account page's positions display.
 */
export function InstrumentSymbol({
  symbol,
  size = 'md',
}: {
  symbol: string
  size?: 'sm' | 'md' | 'lg'
}) {
  const info = getInstrumentInfo(symbol)
  const s = SIZE_MAP[size]

  return (
    <div className="relative group shrink-0">
      <div
        className={`relative flex items-center justify-center rounded-xl overflow-hidden ${s.box} bg-muted/50 border border-border shadow-sm group-hover:border-primary/20 transition-colors`}
      >
        {info.iconUrl ? (
          <div className="relative z-10 p-1.5 w-full h-full flex items-center justify-center">
            <Image
              src={info.iconUrl}
              alt={symbol || 'Unknown'}
              width={40}
              height={40}
              className="w-full h-full object-contain"
            />
          </div>
        ) : info.iconType ? (
          <div className="relative z-10 text-muted-foreground">
            <InstrumentIcon type={info.iconType} className={`${s.icon} ${info.iconColor ?? ''}`} />
          </div>
        ) : info.type === 'forex' && info.base && info.quote ? (
          <div className={`relative z-10 flex ${s.flagSpace} scale-110`}>
            <div className={`${s.flag} rounded-full border border-white overflow-hidden bg-muted/50 shadow-sm`}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={`/flags/l/${info.base}.svg`}
                alt={info.base}
                className="w-full h-full object-cover"
                onError={(e) => ((e.target as HTMLImageElement).style.display = 'none')}
              />
            </div>
            <div className={`${s.flag} rounded-full border border-white overflow-hidden bg-muted/50 shadow-sm`}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={`/flags/l/${info.quote}.svg`}
                alt={info.quote}
                className="w-full h-full object-cover"
                onError={(e) => ((e.target as HTMLImageElement).style.display = 'none')}
              />
            </div>
          </div>
        ) : (
          <span className="relative z-10 text-[10px] font-black text-muted-foreground/70 uppercase">
            {(symbol || 'UNK').substring(0, 3)}
          </span>
        )}
      </div>
    </div>
  )
}

/**
 * Single country flag for a currency (or ISO-2 country) code, used by the
 * economic-calendar rows. Renders nothing if the code is unknown.
 */
export function CurrencyFlag({
  currency,
  size = 16,
}: {
  currency: string
  size?: number
}) {
  const code = (currency || '').toUpperCase()
  const iso2 = CURRENCY_TO_COUNTRY[code] ?? (code.length === 2 ? code : null)
  if (!iso2) return null
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={`/flags/l/${iso2}.svg`}
      alt={currency}
      width={size}
      height={size}
      className="rounded-full object-cover inline-block flex-shrink-0 border border-border/60"
      style={{ width: size, height: size }}
      onError={(e) => ((e.target as HTMLImageElement).style.display = 'none')}
    />
  )
}
