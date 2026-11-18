/**
 * Plain-text formatter for the "Share today's news" feature.
 *
 * Produces clean, well-aligned text that renders nicely in Telegram, WhatsApp,
 * and other messengers (no markdown that would show as literal asterisks in
 * apps that don't parse it). Impact is shown with a coloured circle emoji so it
 * reads at a glance without needing formatting support.
 */

import { CURRENCY_TO_COUNTRY } from '@/components/InstrumentSymbol'
import type { NewsShareConfig, ShareEvent } from '@/lib/types/newsShare'

/** ISO-2 country code → regional-indicator flag emoji. */
export function countryToFlagEmoji(iso2: string): string {
  const code = (iso2 || '').toUpperCase()
  if (code.length !== 2 || !/^[A-Z]{2}$/.test(code)) return ''
  const A = 0x1f1e6
  return String.fromCodePoint(A + (code.charCodeAt(0) - 65), A + (code.charCodeAt(1) - 65))
}

/** Currency (USD/EUR/…) → flag emoji, via the shared country map. */
export function currencyToFlagEmoji(currency: string): string {
  const iso2 = CURRENCY_TO_COUNTRY[(currency || '').toUpperCase()]
  return iso2 ? countryToFlagEmoji(iso2) : ''
}

const IMPACT_DOT: Record<ShareEvent['importance'], string> = {
  High: '🔴',
  Medium: '🟠',
  Low: '⚪',
}

function applyCap(events: ShareEvent[], cap: number): { events: ShareEvent[]; hidden: number } {
  if (!cap || cap <= 0 || events.length <= cap) return { events, hidden: 0 }
  return { events: events.slice(0, cap), hidden: events.length - cap }
}

/**
 * Builds the shareable plain-text block.
 *
 * @param events     already filtered + sorted events
 * @param cfg        branding/format config
 * @param tzNote     e.g. "GMT+3" — appended when cfg.showTimezoneNote
 * @param singleDay  when true (a single-day filter) the top date line is the header
 */
export function formatNewsText(
  events: ShareEvent[],
  cfg: NewsShareConfig,
  tzNote: string,
): string {
  const { events: capped, hidden } = applyCap(events, cfg.maxEvents)
  const lines: string[] = []

  // ── Header ───────────────────────────────────────────────────
  if (cfg.brandName.trim()) lines.push(`📊 ${cfg.brandName.trim()}`)
  if (cfg.headerSubtitle.trim()) lines.push(cfg.headerSubtitle.trim())
  if (lines.length) lines.push('')

  if (capped.length === 0) {
    lines.push('No events match the current filters.')
  } else if (cfg.groupByDate) {
    const groups = new Map<string, ShareEvent[]>()
    for (const ev of capped) {
      const arr = groups.get(ev.dateKey) ?? []
      arr.push(ev)
      groups.set(ev.dateKey, arr)
    }
    let first = true
    for (const [, group] of Array.from(groups.entries()).sort(([a], [b]) => a.localeCompare(b))) {
      if (!first) lines.push('')
      first = false
      lines.push(`🗓 ${group[0].dateLabel}`)
      for (const ev of group) lines.push(formatEventLine(ev, cfg))
    }
  } else {
    for (const ev of capped) lines.push(formatEventLine(ev, cfg))
  }

  if (hidden > 0) {
    lines.push('')
    lines.push(`…and ${hidden} more event${hidden === 1 ? '' : 's'}`)
  }

  // ── Footer ───────────────────────────────────────────────────
  const footerBits: string[] = []
  if (cfg.showTimezoneNote && tzNote) footerBits.push(`🕒 Times in ${tzNote}`)
  if (cfg.footer.trim()) footerBits.push(cfg.footer.trim())
  if (footerBits.length) {
    lines.push('')
    lines.push('—')
    footerBits.forEach((b) => lines.push(b))
  }

  return lines.join('\n').trim()
}

function formatEventLine(ev: ShareEvent, cfg: NewsShareConfig): string {
  const parts: string[] = [IMPACT_DOT[ev.importance]]
  if (cfg.showTime && ev.time) parts.push(ev.time)
  if (cfg.showFlag) {
    const flag = currencyToFlagEmoji(ev.currency)
    parts.push(flag ? `${flag} ${ev.currency}` : ev.currency)
  } else {
    parts.push(ev.currency)
  }
  parts.push(`— ${ev.event}`)

  const line = parts.filter(Boolean).join(' ')

  // Second (indented) line for numeric data, only when present.
  const dataBits: string[] = []
  if (cfg.showForecastPrevious) {
    if (ev.forecast && ev.forecast !== '—') dataBits.push(`F: ${ev.forecast}`)
    if (ev.previous && ev.previous !== '—') dataBits.push(`P: ${ev.previous}`)
  }
  if (cfg.showActual && ev.actual && ev.actual !== '—') dataBits.push(`A: ${ev.actual}`)

  return dataBits.length ? `${line}\n    ${dataBits.join('  ·  ')}` : line
}
