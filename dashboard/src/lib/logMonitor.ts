// Log monitor: parses the bot's loguru files and groups ERROR/WARNING lines into
// "issues" (same message with numbers/ids stripped). Pure functions, no I/O, so the
// API route and the tests share them. Run tests: npm test

export interface LogEntry {
  timestamp: string
  level: string
  message: string
  file?: string
  /** Continuation lines (tracebacks, multi-line messages) that follow the entry. */
  details?: string
}

/** action: operator must fix something · watch: degraded or worth a look · noise: expected, never alerts */
export type IssueKind = 'action' | 'watch' | 'noise'

export type IssueCategory =
  | 'ai-provider' | 'signal-parsing' | 'trade-sync' | 'mt5' | 'telegram'
  | 'database' | 'network' | 'risk' | 'bot-lifecycle' | 'security' | 'other'

export interface IssueHint {
  title: string
  fix: string
  href?: string
}

export interface Classification {
  kind: IssueKind
  category: IssueCategory
  hint?: IssueHint
}

export interface LogIssue {
  id: string
  signature: string
  level: string
  count: number
  firstSeen: string
  lastSeen: string
  sample: string
  samples: string[]
  details?: string
  /** Occurrences per hour for the last 24h, oldest first. */
  hourly: number[]
  kind: IssueKind
  category: IssueCategory
  hint?: IssueHint
  /** Acknowledged and nothing new since. */
  acknowledged: boolean
  muted: boolean
  /** Occurrences after the acknowledgement time. */
  newSinceAck: number
}

export interface AckRecord {
  at: string
  muted?: boolean
}

export type MonitorStatus = 'ok' | 'warning' | 'critical'

export interface MonitorSummary {
  status: MonitorStatus
  statusReason: string
  generatedAt: string
  lastEntryAt: string | null
  totals: { errors1h: number; warnings1h: number; errors24h: number; warnings24h: number; entries24h: number }
  issues: LogIssue[]
}

const isError = (level: string) => level === 'ERROR' || level === 'CRITICAL'

const LINE = /^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d{3})?) \| ([A-Z]+)\s*\| ?(.*)$/
const MAX_DETAIL_LINES = 60

/** Loguru format: `2026-10-13 18:33:02.163 | WARNING  | message`, continuation lines attach to the previous entry. */
export function parseLogContent(content: string, filename?: string): LogEntry[] {
  const out: LogEntry[] = []
  let current: LogEntry | null = null
  let detailLines: string[] = []

  const flush = () => {
    if (!current) return
    if (detailLines.length) {
      const kept = detailLines.length > MAX_DETAIL_LINES
        ? [...detailLines.slice(0, 10), `… ${detailLines.length - MAX_DETAIL_LINES} lines omitted …`, ...detailLines.slice(-(MAX_DETAIL_LINES - 10))]
        : detailLines
      current.details = kept.join('\n')
    }
    out.push(current)
  }

  for (const raw of content.split('\n')) {
    const line = raw.replace(/\r$/, '')
    const m = line.match(LINE)
    if (m) {
      flush()
      current = { timestamp: m[1], level: m[2], message: m[3], ...(filename ? { file: filename } : {}) }
      detailLines = []
    } else if (current && line.trim()) {
      detailLines.push(line)
    }
  }
  flush()
  return out
}

/** Log timestamps are written in the containers' timezone, which is UTC. */
export function entryTime(ts: string): number {
  return Date.parse(ts.replace(' ', 'T') + 'Z')
}

/** Normalises a message so repeats of the same problem collapse into one issue. */
export function signatureOf(message: string): string {
  return message
    .replace(/\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi, '<id>')
    .replace(/request_id: [^)'",\s]+/gi, 'request_id: <id>')
    .replace(/\*{2,}\w+/g, '***')
    .replace(/\b(?:0x)?[0-9a-f]{12,}\b/gi, '<id>')
    // Truncated ids like "Trade 54700dcc..." (hex with at least one letter, else it's a number)
    .replace(/\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{6,}\b/gi, '<id>')
    .replace(/'[^']{0,80}'|"[^"]{0,80}"/g, (q) => (/\d/.test(q) ? '<str>' : q))
    .replace(/-?\d+(?:[.,]\d+)*/g, 'N')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 240)
}

function hashId(s: string): string {
  let h = 5381
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0
  return (h >>> 0).toString(36)
}

interface Rule {
  test: RegExp
  kind: IssueKind
  category: IssueCategory
  title: string
  fix: string
  href?: string
}

// Rule-based classification, no AI involved. Built from the bot's real log lines.
// First match wins, so specific rules go above generic ones.
const RULES: Rule[] = [
  // ── AI providers ──────────────────────────────────────────────────────────
  {
    test: /AUTH ERROR|invalid or expired api key|authentication[_ ]fail|authentication_error|incorrect api key/i,
    kind: 'action', category: 'ai-provider',
    title: 'AI provider rejected its API key',
    fix: 'The key for this provider is invalid or expired. Replace it in Settings → API Keys, or take the provider out of the fallback chain.',
    href: '/settings/api-keys',
  },
  {
    test: /insufficient[_ ]quota|insufficient balance|quota exceeded|billing|payment required/i,
    kind: 'action', category: 'ai-provider',
    title: 'AI provider out of credit',
    fix: 'Top up the provider account, or move another provider first in the fallback chain.',
    href: '/settings',
  },
  {
    test: /falling back to next provider/i,
    kind: 'watch', category: 'ai-provider',
    title: 'Primary AI provider failing — fallback in use',
    fix: 'Signals still get parsed by the next provider, but every call wastes a failed request first. Fix the error logged just before this line.',
    href: '/settings',
  },
  {
    test: /Recovered via fallback provider/i,
    kind: 'noise', category: 'ai-provider',
    title: 'Fallback provider answered',
    fix: 'Informational: the fallback chain worked.',
  },
  {
    test: /rate.?limit|\b429\b|too many requests/i,
    kind: 'watch', category: 'ai-provider',
    title: 'Rate limited',
    fix: 'Requests are being throttled. Lower call volume or add a fallback provider.',
  },
  {
    test: /AI response parse error|returned empty\/invalid completion|returned empty result/i,
    kind: 'watch', category: 'signal-parsing',
    title: 'AI returned an unusable answer',
    fix: 'One-offs are normal. If it repeats, the model may be too small or truncating — try another model.',
    href: '/settings',
  },

  // ── Signal parsing: messages correctly ignored ───────────────────────────
  {
    test: /Failed to extract signal: (?:Message classified as not_trading|Not a trading signal|No trading symbol found)|Could not extract signal from update message/i,
    kind: 'noise', category: 'signal-parsing',
    title: 'Non-signal message ignored',
    fix: 'Expected: chat/commentary in the channel was correctly skipped.',
  },
  {
    test: /Incomplete .* signal: no stop loss/i,
    kind: 'watch', category: 'signal-parsing',
    title: 'Signal skipped — no stop loss',
    fix: 'The channel posted a signal without SL. Expected for some providers; check the channel rules if you wanted it traded.',
    href: '/channel-behavior',
  },
  {
    test: /Failed to extract signal/i,
    kind: 'watch', category: 'signal-parsing',
    title: 'Signal could not be parsed',
    fix: 'Open the raw message in History and check whether it was a real signal.',
    href: '/history',
  },
  {
    test: /Edited message already processed/i,
    kind: 'noise', category: 'telegram',
    title: 'Duplicate edit ignored',
    fix: 'Expected: Telegram re-sent an edit the bot already handled.',
  },

  // ── Trade management ──────────────────────────────────────────────────────
  {
    test: /Reply to closed trade|No active trades or signal found anywhere|Command guard vetoed/i,
    kind: 'noise', category: 'trade-sync',
    title: 'Reply had no open trade to act on',
    fix: 'Expected: the channel replied to a trade that is already closed, or posted a status update.',
  },
  {
    test: /NOT FOUND in MT5/i,
    kind: 'watch', category: 'trade-sync',
    title: 'Position missing in MT5 — reconciling',
    fix: 'Usually closed by SL/TP or manually; the lifecycle check updates the record. Investigate only if trades stay stuck open in History.',
    href: '/history',
  },
  {
    test: /Risk warnings? for|adjusted for spread|Low risk-reward/i,
    kind: 'noise', category: 'risk',
    title: 'Risk adjustment applied',
    fix: 'Expected: entry/SL were nudged for spread or R:R flagged. The trade still followed your risk rules.',
  },

  // ── Bot lifecycle lines logged at WARNING so they reach the file ─────────
  {
    test: /Registering bot command handlers|Checking for stale AWAITING_APPROVAL|No stale AWAITING_APPROVAL|Bot commands registered|Bot is already stopping/i,
    kind: 'noise', category: 'bot-lifecycle',
    title: 'Bot start/stop message',
    fix: 'Expected on every restart. Many of these in a short time mean the bot is restart-looping.',
  },

  // ── Security ──────────────────────────────────────────────────────────────
  {
    test: /Internal API: rejected/i,
    kind: 'watch', category: 'security',
    title: 'Bot API call without valid token',
    fix: 'Something on the Docker network called the bot API without the internal token. A one-off right after a deploy or a manual test is harmless. Repeated hits, or a source IP that is not the dashboard container, need investigating; check INTERNAL_API_TOKEN / SETTINGS_ENCRYPTION_KEY match in both containers.',
  },

  // ── Infrastructure ────────────────────────────────────────────────────────
  {
    test: /floodwait|flood wait|a wait of \d+ seconds/i,
    kind: 'watch', category: 'telegram',
    title: 'Telegram flood-wait',
    fix: 'Telegram is throttling this session. It clears on its own; avoid restarts that re-sync many dialogs.',
  },
  {
    test: /AuthKey|session (?:revoked|expired)|not authorized|SessionPasswordNeeded/i,
    kind: 'action', category: 'telegram',
    title: 'Telegram session problem',
    fix: 'Re-login the Telegram session from the Telegram page.',
    href: '/telegram-browser',
  },
  {
    test: /database is locked|sqlite.*locked/i,
    kind: 'watch', category: 'database',
    title: 'SQLite database locked',
    fix: 'Two writers collided on the shared database. Occasional hits are harmless; frequent ones mean a long-running transaction.',
  },
  {
    // The bridge answered (it is up): 4xx/500 with an MT5 reason. 503 means the
    // terminal itself is not ready and stays a bridge problem below.
    test: /"retcode":\s*\d+|MT5 REST API (?:4\d\d|500) on /i,
    kind: 'action', category: 'mt5',
    title: 'MT5 refused the request',
    fix: 'The bridge is up and answered; MT5 or the broker rejected this order or change. The reason is in the message (mt5_error): check the prices sent, market hours and free margin.',
  },
  {
    test: /\b(?:mt5|metatrader|bridge)\b.*\b(?:fail|error|disconnect|refused|timed? ?out|unreachable|not connected|cannot connect)|\b(?:fail|error|disconnect|cannot connect)\w*\b.*\b(?:mt5|metatrader|bridge)\b/i,
    kind: 'action', category: 'mt5',
    title: 'MT5 bridge problem',
    fix: 'Check the MT5 container is running and logged in (MT5 page / VNC).',
    href: '/mt5-terminal',
  },
  {
    test: /connection (?:refused|reset|error|aborted)|timed? ?out|unreachable|name or service not known/i,
    kind: 'watch', category: 'network',
    title: 'Network / connectivity error',
    fix: 'A dependency was unreachable. If it repeats, check the target container or upstream service.',
  },
]

/** Classifies one log line without AI. Unknown errors need action, unknown warnings are worth a look. */
export function classify(message: string, level: string): Classification {
  const rule = RULES.find((r) => r.test.test(message))
  if (!rule) return { kind: isError(level) ? 'action' : 'watch', category: 'other' }
  const { kind, category, title, fix, href } = rule
  return { kind, category, hint: href ? { title, fix, href } : { title, fix } }
}

const ISSUE_LEVELS = new Set(['ERROR', 'CRITICAL', 'WARNING'])
const HOUR = 3_600_000

export function buildMonitor(
  entries: LogEntry[],
  opts: { now?: number; acks?: Record<string, AckRecord> } = {},
): MonitorSummary {
  const now = opts.now ?? Date.now()
  const acks = opts.acks ?? {}
  const dayAgo = now - 24 * HOUR
  const hourAgo = now - HOUR

  const totals = { errors1h: 0, warnings1h: 0, errors24h: 0, warnings24h: 0, entries24h: 0 }
  const groups = new Map<string, LogIssue>()
  let lastEntry: number | null = null

  for (const e of entries) {
    const t = entryTime(e.timestamp)
    if (Number.isNaN(t)) continue
    if (lastEntry === null || t > lastEntry) lastEntry = t
    if (t < dayAgo) continue
    totals.entries24h++
    if (!ISSUE_LEVELS.has(e.level)) continue

    const signature = signatureOf(e.message)
    const ack = acks[signature]
    const afterAck = !ack || t > Date.parse(ack.at)

    let g = groups.get(signature)
    if (!g) {
      const c = classify(e.message, e.level)
      g = {
        id: hashId(signature),
        signature,
        level: e.level,
        count: 0,
        firstSeen: e.timestamp,
        lastSeen: e.timestamp,
        sample: e.message,
        samples: [],
        hourly: new Array(24).fill(0),
        kind: c.kind,
        category: c.category,
        ...(c.hint ? { hint: c.hint } : {}),
        acknowledged: false,
        muted: !!ack?.muted,
        newSinceAck: 0,
      }
      groups.set(signature, g)
    }
    if (isError(e.level) && !isError(g.level)) {
      g.level = e.level
      if (g.category === 'other') g.kind = 'action'
    }

    // Headline numbers only count what still needs attention.
    if (afterAck && !ack?.muted && g.kind !== 'noise') {
      if (isError(e.level)) {
        totals.errors24h++
        if (t >= hourAgo) totals.errors1h++
      } else {
        totals.warnings24h++
        if (t >= hourAgo) totals.warnings1h++
      }
    }

    g.count++
    if (e.timestamp < g.firstSeen) g.firstSeen = e.timestamp
    if (e.timestamp >= g.lastSeen) {
      g.lastSeen = e.timestamp
      g.sample = e.message
      if (e.details) g.details = e.details
    } else if (e.details && !g.details) {
      g.details = e.details
    }
    if (g.samples.length < 3 && !g.samples.includes(e.message)) g.samples.push(e.message)
    const bucket = 23 - Math.floor((now - t) / HOUR)
    if (bucket >= 0 && bucket < 24) g.hourly[bucket]++
    if (ack && afterAck) g.newSinceAck++
  }

  const issues = [...groups.values()]
  for (const g of issues) {
    const ack = acks[g.signature]
    g.acknowledged = !!ack && g.newSinceAck === 0
  }

  const KIND_RANK: Record<IssueKind, number> = { action: 0, watch: 1, noise: 2 }
  const rank = (g: LogIssue) => (g.muted || g.acknowledged ? 3 : KIND_RANK[g.kind])
  issues.sort((a, b) => rank(a) - rank(b) || b.lastSeen.localeCompare(a.lastSeen) || b.count - a.count)

  const open = issues.filter(isOpen)
  const action = open.filter((g) => g.kind === 'action')
  const action1h = action.filter((g) => entryTime(g.lastSeen) >= hourAgo)

  let status: MonitorStatus = 'ok'
  let statusReason = 'Nothing needs attention in the last 24h'
  if (action1h.length > 0) {
    status = 'critical'
    statusReason = `${action1h.length} problem${action1h.length === 1 ? '' : 's'} needing action, active in the last hour`
  } else if (action.length > 0) {
    status = 'warning'
    statusReason = `${action.length} problem${action.length === 1 ? '' : 's'} needing action in the last 24h`
  } else if (open.length > 0) {
    status = 'warning'
    statusReason = `${open.length} issue${open.length === 1 ? '' : 's'} worth a look in the last 24h`
  }

  return {
    status,
    statusReason,
    generatedAt: new Date(now).toISOString(),
    lastEntryAt: lastEntry === null ? null : new Date(lastEntry).toISOString(),
    totals,
    issues,
  }
}

/** Not noise, not muted, not marked fixed. */
export function isOpen(g: LogIssue): boolean {
  return g.kind !== 'noise' && !g.muted && !g.acknowledged
}
