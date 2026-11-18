// Helpers for the mobile Account views. Pip rules mirror the inline logic used
// by getPips() and the desktop Modify dialogs in app/account/page.tsx.

export function getPipMultiplier(symbol: string): number {
  if (symbol.includes('JPY')) return 100
  if (symbol.includes('XAU') || symbol.includes('GOLD')) return 10
  if (symbol.includes('XAG') || symbol.includes('SILVER') || symbol.includes('XPD') || symbol.includes('XPT')) return 100
  if (symbol.includes('BTC') || symbol.includes('ETH')) return 10
  return 10000
}

/** Display precision: one decimal finer than a pip (e.g. 5 for EURUSD, 3 for USDJPY). */
export function getPriceDigits(symbol: string): number {
  return Math.round(Math.log10(getPipMultiplier(symbol))) + 1
}

const ORDER_TYPE_LABELS: Record<number, string> = {
  0: 'BUY', 1: 'SELL', 2: 'BUY LIMIT', 3: 'SELL LIMIT', 4: 'BUY STOP', 5: 'SELL STOP', 6: 'BUY STOP LIMIT', 7: 'SELL STOP LIMIT',
}

export function getOrderTypeLabel(type: number): string {
  return ORDER_TYPE_LABELS[type] || `TYPE_${type}`
}

export function isBuyType(type: number): boolean {
  return type % 2 === 0
}
