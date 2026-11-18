/**
 * Lite mode — a per-device preference that trims the sidebar down to a
 * chosen subset of nav items. Stored in localStorage alongside `theme`
 * (see DarkModeToggle) so it needs no backend and survives reloads.
 *
 * Nav items are identified by href, which is stable across renames.
 */

export const LITE_ENABLED_KEY = 'liteMode'
export const LITE_ITEMS_KEY = 'liteVisibleNav'

/** Hrefs shown when lite mode is on and the user hasn't customised the set. */
export const DEFAULT_LITE_HREFS = [
  '/',
  '/hermes',
  '/account',
  '/history',
  '/plans',
  '/journal',
  '/calendar',
  '/telegram-browser',
  '/mt5-terminal',
]

/** Fired on the window whenever lite mode or its item set changes. */
export const LITE_CHANGE_EVENT = 'lite-mode-change'

export function readLiteEnabled(): boolean {
  if (typeof window === 'undefined') return false
  return localStorage.getItem(LITE_ENABLED_KEY) === 'true'
}

export function readLiteHrefs(): string[] {
  if (typeof window === 'undefined') return DEFAULT_LITE_HREFS
  const raw = localStorage.getItem(LITE_ITEMS_KEY)
  if (!raw) return DEFAULT_LITE_HREFS
  try {
    const parsed = JSON.parse(raw)
    // A corrupted or empty list would hide every nav item and strand the
    // user with no way back, so fall back to the defaults.
    if (Array.isArray(parsed) && parsed.length > 0) return parsed as string[]
  } catch {
    /* fall through to defaults */
  }
  return DEFAULT_LITE_HREFS
}

function broadcast() {
  window.dispatchEvent(new Event(LITE_CHANGE_EVENT))
}

export function writeLiteEnabled(enabled: boolean) {
  localStorage.setItem(LITE_ENABLED_KEY, String(enabled))
  broadcast()
}

export function writeLiteHrefs(hrefs: string[]) {
  localStorage.setItem(LITE_ITEMS_KEY, JSON.stringify(hrefs))
  broadcast()
}
