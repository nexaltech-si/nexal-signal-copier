/**
 * News-share (economic calendar) branding + format config.
 *
 * Persisted server-side as a JSON string in `UserSettings.newsShareConfig`
 * and edited from the Settings page. It controls how the "Share today's news"
 * output looks — both the plain-text (Telegram/WhatsApp) and the rendered PNG
 * card variants share this same config so the two stay visually consistent.
 */

export interface NewsShareConfig {
  /** Channel / brand name shown in the header (e.g. "NEXAL"). Empty hides it. */
  brandName: string
  /** Optional subtitle under the brand (e.g. "Daily Economic Calendar"). */
  headerSubtitle: string
  /** Footer line — a handle, link, or disclaimer. Empty hides it. */
  footer: string
  /** Accent colour used for the image card header + impact-high marker. Hex. */
  accentColor: string

  // ── What each event row includes ─────────────────────────────
  showTime: boolean
  showFlag: boolean
  showForecastPrevious: boolean
  showActual: boolean
  /** Group events under date headings (relevant when sharing multiple days). */
  groupByDate: boolean

  /** Append the timezone label (e.g. "Times in GMT+3") to the output. */
  showTimezoneNote: boolean
  /** Cap on how many events go into a single share (0 = no cap). */
  maxEvents: number
}

export const DEFAULT_NEWS_SHARE_CONFIG: NewsShareConfig = {
  brandName: '',
  headerSubtitle: 'Economic Calendar',
  footer: '',
  accentColor: '#2563eb',
  showTime: true,
  showFlag: true,
  showForecastPrevious: true,
  showActual: true,
  groupByDate: true,
  showTimezoneNote: true,
  maxEvents: 0,
}

/** Merge a possibly-partial persisted config over the defaults. */
export function normalizeNewsShareConfig(raw: unknown): NewsShareConfig {
  if (!raw || typeof raw !== 'object') return { ...DEFAULT_NEWS_SHARE_CONFIG }
  const r = raw as Partial<NewsShareConfig>
  return {
    brandName: typeof r.brandName === 'string' ? r.brandName : DEFAULT_NEWS_SHARE_CONFIG.brandName,
    headerSubtitle: typeof r.headerSubtitle === 'string' ? r.headerSubtitle : DEFAULT_NEWS_SHARE_CONFIG.headerSubtitle,
    footer: typeof r.footer === 'string' ? r.footer : DEFAULT_NEWS_SHARE_CONFIG.footer,
    accentColor: typeof r.accentColor === 'string' ? r.accentColor : DEFAULT_NEWS_SHARE_CONFIG.accentColor,
    showTime: r.showTime ?? DEFAULT_NEWS_SHARE_CONFIG.showTime,
    showFlag: r.showFlag ?? DEFAULT_NEWS_SHARE_CONFIG.showFlag,
    showForecastPrevious: r.showForecastPrevious ?? DEFAULT_NEWS_SHARE_CONFIG.showForecastPrevious,
    showActual: r.showActual ?? DEFAULT_NEWS_SHARE_CONFIG.showActual,
    groupByDate: r.groupByDate ?? DEFAULT_NEWS_SHARE_CONFIG.groupByDate,
    showTimezoneNote: r.showTimezoneNote ?? DEFAULT_NEWS_SHARE_CONFIG.showTimezoneNote,
    maxEvents: typeof r.maxEvents === 'number' && r.maxEvents >= 0 ? r.maxEvents : DEFAULT_NEWS_SHARE_CONFIG.maxEvents,
  }
}

/** Parse the raw JSON string persisted in UserSettings.newsShareConfig. */
export function parseNewsShareConfig(rawJson: string | null | undefined): NewsShareConfig {
  if (!rawJson) return { ...DEFAULT_NEWS_SHARE_CONFIG }
  try {
    return normalizeNewsShareConfig(JSON.parse(rawJson))
  } catch {
    return { ...DEFAULT_NEWS_SHARE_CONFIG }
  }
}

// ── Shared event shape used by both the text + image renderers ──
export interface ShareEvent {
  time: string
  currency: string
  event: string
  importance: 'High' | 'Medium' | 'Low'
  previous: string
  forecast: string
  actual: string
  /** Date heading key (YYYY-MM-DD) + human label, for grouped output. */
  dateKey: string
  dateLabel: string
}
