'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  DEFAULT_LITE_HREFS,
  LITE_CHANGE_EVENT,
  LITE_ENABLED_KEY,
  LITE_ITEMS_KEY,
  readLiteEnabled,
  readLiteHrefs,
  writeLiteEnabled,
  writeLiteHrefs,
} from '@/lib/liteMode'

/**
 * Reads lite-mode preferences and stays in sync with other components
 * (and other browser tabs) that change them.
 *
 * `hydrated` is false on the first client render so callers can render the
 * full nav until localStorage has been read — otherwise the server HTML and
 * the first client paint disagree and React logs a hydration mismatch.
 */
export function useLiteMode() {
  const [enabled, setEnabled] = useState(false)
  const [hrefs, setHrefs] = useState<string[]>(DEFAULT_LITE_HREFS)
  const [hydrated, setHydrated] = useState(false)

  useEffect(() => {
    const sync = () => {
      setEnabled(readLiteEnabled())
      setHrefs(readLiteHrefs())
    }
    sync()
    setHydrated(true)

    const onStorage = (e: StorageEvent) => {
      if (e.key === LITE_ENABLED_KEY || e.key === LITE_ITEMS_KEY) sync()
    }
    window.addEventListener(LITE_CHANGE_EVENT, sync)
    window.addEventListener('storage', onStorage)
    return () => {
      window.removeEventListener(LITE_CHANGE_EVENT, sync)
      window.removeEventListener('storage', onStorage)
    }
  }, [])

  const toggle = useCallback(() => writeLiteEnabled(!enabled), [enabled])

  const toggleItem = useCallback((href: string) => {
    const next = hrefs.includes(href)
      ? hrefs.filter(h => h !== href)
      : [...hrefs, href]
    // Never let the set empty out — see readLiteHrefs.
    if (next.length === 0) return
    writeLiteHrefs(next)
  }, [hrefs])

  return { enabled, hrefs, hydrated, toggle, toggleItem, setEnabled: writeLiteEnabled }
}
