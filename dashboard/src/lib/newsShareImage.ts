/**
 * Renders the shareable economic-calendar card to a PNG Blob using the native
 * Canvas 2D API — no external dependency, no canvas-taint issues.
 *
 * The layout mirrors the plain-text formatter (same header/footer/columns,
 * driven by the same NewsShareConfig) so the image and text variants stay
 * visually consistent. Rendered at 2× for crisp output on retina + when
 * re-scaled by messaging apps.
 */

import type { NewsShareConfig, ShareEvent } from '@/lib/types/newsShare'
import { currencyToFlagEmoji } from '@/lib/newsShareFormat'

const SCALE = 2
const WIDTH = 720 // CSS px; canvas is WIDTH * SCALE
const PAD = 32

const IMPACT_COLOR: Record<ShareEvent['importance'], string> = {
  High: '#ef4444',
  Medium: '#f59e0b',
  Low: '#9ca3af',
}

interface Theme {
  bg: string
  card: string
  text: string
  subtle: string
  faint: string
  border: string
  headerText: string
}

const DARK: Theme = {
  bg: '#0b0e14',
  card: '#131722',
  text: '#e6e8ec',
  subtle: '#9aa0ab',
  faint: '#6b7280',
  border: '#232838',
  headerText: '#ffffff',
}

/** Rounded-rect path helper (older canvas engines lack roundRect). */
function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  const rr = Math.min(r, w / 2, h / 2)
  ctx.beginPath()
  ctx.moveTo(x + rr, y)
  ctx.arcTo(x + w, y, x + w, y + h, rr)
  ctx.arcTo(x + w, y + h, x, y + h, rr)
  ctx.arcTo(x, y + h, x, y, rr)
  ctx.arcTo(x, y, x + w, y, rr)
  ctx.closePath()
}

interface Row {
  ev: ShareEvent
}
type Line = { kind: 'dateHeader'; label: string } | { kind: 'event'; row: Row }

function buildLines(events: ShareEvent[], cfg: NewsShareConfig): { lines: Line[]; hidden: number } {
  let list = events
  let hidden = 0
  if (cfg.maxEvents > 0 && events.length > cfg.maxEvents) {
    hidden = events.length - cfg.maxEvents
    list = events.slice(0, cfg.maxEvents)
  }
  const lines: Line[] = []
  if (cfg.groupByDate) {
    const groups = new Map<string, ShareEvent[]>()
    for (const ev of list) {
      const arr = groups.get(ev.dateKey) ?? []
      arr.push(ev)
      groups.set(ev.dateKey, arr)
    }
    for (const [, group] of Array.from(groups.entries()).sort(([a], [b]) => a.localeCompare(b))) {
      lines.push({ kind: 'dateHeader', label: group[0].dateLabel })
      for (const ev of group) lines.push({ kind: 'event', row: { ev } })
    }
  } else {
    for (const ev of list) lines.push({ kind: 'event', row: { ev } })
  }
  return { lines, hidden }
}

const ROW_H = 54
const DATE_H = 40
const HEADER_H = 96

export async function renderNewsImage(
  events: ShareEvent[],
  cfg: NewsShareConfig,
  tzNote: string,
): Promise<Blob> {
  const theme = DARK
  const { lines, hidden } = buildLines(events, cfg)

  // ── Measure height ───────────────────────────────────────────
  let bodyH = 0
  for (const l of lines) bodyH += l.kind === 'dateHeader' ? DATE_H : ROW_H
  const footerBits: string[] = []
  if (cfg.showTimezoneNote && tzNote) footerBits.push(`Times in ${tzNote}`)
  if (cfg.footer.trim()) footerBits.push(cfg.footer.trim())
  const footerH = footerBits.length ? 44 : 0
  const emptyH = lines.length === 0 ? 60 : 0
  const hiddenH = hidden > 0 ? 32 : 0

  const totalH = HEADER_H + PAD + bodyH + emptyH + hiddenH + footerH + PAD

  const canvas = document.createElement('canvas')
  canvas.width = WIDTH * SCALE
  canvas.height = Math.ceil(totalH) * SCALE
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('Canvas 2D context unavailable')
  ctx.scale(SCALE, SCALE)
  ctx.textBaseline = 'middle'

  // Background
  ctx.fillStyle = theme.bg
  ctx.fillRect(0, 0, WIDTH, totalH)

  // ── Header band ──────────────────────────────────────────────
  ctx.fillStyle = cfg.accentColor
  roundRect(ctx, PAD, PAD, WIDTH - PAD * 2, HEADER_H - 16, 14)
  ctx.fill()

  ctx.fillStyle = theme.headerText
  ctx.font = '700 24px system-ui, -apple-system, "Segoe UI", sans-serif'
  ctx.textAlign = 'left'
  const brand = cfg.brandName.trim() || 'Economic Calendar'
  ctx.fillText(brand, PAD + 24, PAD + 32)
  if (cfg.headerSubtitle.trim()) {
    ctx.font = '600 14px system-ui, -apple-system, sans-serif'
    ctx.globalAlpha = 0.85
    ctx.fillText(cfg.headerSubtitle.trim(), PAD + 24, PAD + 58)
    ctx.globalAlpha = 1
  }
  ctx.textAlign = 'right'
  ctx.font = '600 13px system-ui, sans-serif'
  ctx.globalAlpha = 0.85
  ctx.fillText('📅', WIDTH - PAD - 24, PAD + 32)
  ctx.globalAlpha = 1

  // ── Body ─────────────────────────────────────────────────────
  let y = HEADER_H + PAD
  const leftX = PAD + 8
  const rightX = WIDTH - PAD - 8
  ctx.textAlign = 'left'

  if (lines.length === 0) {
    ctx.fillStyle = theme.subtle
    ctx.font = '600 15px system-ui, sans-serif'
    ctx.fillText('No events match the current filters.', leftX, y + 24)
    y += emptyH
  }

  for (const l of lines) {
    if (l.kind === 'dateHeader') {
      ctx.fillStyle = theme.subtle
      ctx.font = '700 13px system-ui, sans-serif'
      ctx.fillText(l.label.toUpperCase(), leftX, y + DATE_H / 2)
      // faint underline
      ctx.strokeStyle = theme.border
      ctx.lineWidth = 1
      const tw = ctx.measureText(l.label.toUpperCase()).width
      ctx.beginPath()
      ctx.moveTo(leftX + tw + 12, y + DATE_H / 2)
      ctx.lineTo(rightX, y + DATE_H / 2)
      ctx.stroke()
      y += DATE_H
      continue
    }

    const { ev } = l.row
    const cy = y + ROW_H / 2

    // row card
    ctx.fillStyle = theme.card
    roundRect(ctx, PAD, y + 4, WIDTH - PAD * 2, ROW_H - 8, 10)
    ctx.fill()

    let x = leftX + 8

    // impact dot
    ctx.fillStyle = IMPACT_COLOR[ev.importance]
    ctx.beginPath()
    ctx.arc(x + 4, cy, 5, 0, Math.PI * 2)
    ctx.fill()
    x += 22

    // time
    if (cfg.showTime && ev.time) {
      ctx.fillStyle = theme.text
      ctx.font = '700 14px "SF Mono", ui-monospace, Menlo, monospace'
      ctx.fillText(ev.time, x, cy)
      x += 58
    }

    // flag + currency
    ctx.font = '700 13px system-ui, sans-serif'
    if (cfg.showFlag) {
      const flag = currencyToFlagEmoji(ev.currency)
      if (flag) {
        ctx.fillText(flag, x, cy)
        x += 24
      }
    }
    ctx.fillStyle = theme.subtle
    ctx.fillText(ev.currency, x, cy)
    x += 44

    // data columns (right-aligned)
    const dataBits: string[] = []
    if (cfg.showActual && ev.actual && ev.actual !== '—') dataBits.push(`A ${ev.actual}`)
    if (cfg.showForecastPrevious) {
      if (ev.forecast && ev.forecast !== '—') dataBits.push(`F ${ev.forecast}`)
      if (ev.previous && ev.previous !== '—') dataBits.push(`P ${ev.previous}`)
    }
    let dataRightEdge = rightX
    if (dataBits.length) {
      ctx.textAlign = 'right'
      ctx.font = '600 12px "SF Mono", ui-monospace, monospace'
      let dx = rightX
      for (const bit of dataBits) {
        const isActual = bit.startsWith('A ')
        ctx.fillStyle = isActual ? cfg.accentColor : theme.faint
        ctx.fillText(bit, dx, cy)
        dx -= ctx.measureText(bit).width + 16
      }
      dataRightEdge = dx
      ctx.textAlign = 'left'
    }

    // event title (truncated to fit before the data columns)
    ctx.fillStyle = theme.text
    ctx.font = '600 14px system-ui, sans-serif'
    const titleMax = dataRightEdge - x - 16
    ctx.fillText(truncate(ctx, ev.event, titleMax), x, cy)

    y += ROW_H
  }

  if (hidden > 0) {
    ctx.fillStyle = theme.faint
    ctx.font = '600 13px system-ui, sans-serif'
    ctx.textAlign = 'left'
    ctx.fillText(`+ ${hidden} more event${hidden === 1 ? '' : 's'}`, leftX, y + 16)
    y += hiddenH
  }

  // ── Footer ───────────────────────────────────────────────────
  if (footerBits.length) {
    ctx.fillStyle = theme.faint
    ctx.font = '600 12px system-ui, sans-serif'
    ctx.textAlign = 'left'
    ctx.fillText(footerBits.join('   ·   '), leftX, y + footerH / 2)
  }

  return await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error('toBlob failed'))), 'image/png')
  })
}

function truncate(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string {
  if (maxWidth <= 0) return ''
  if (ctx.measureText(text).width <= maxWidth) return text
  let lo = 0
  let hi = text.length
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (ctx.measureText(text.slice(0, mid) + '…').width <= maxWidth) lo = mid
    else hi = mid - 1
  }
  return text.slice(0, lo) + '…'
}
