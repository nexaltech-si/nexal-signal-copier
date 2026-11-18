import { NextResponse } from 'next/server'
import Redis from 'ioredis'
import { prisma } from '@/lib/prisma'
import { requireOwner } from '@/lib/auth'
import { getMT5RestConfig, getActiveProvider } from '@/lib/provider'
import { connectionOf } from '@/lib/copier'
import type { ConnectionsResponse, ConnectionView, ConnStatus, Detail, TelegramAuth } from '@/lib/types/connections'
import type { DiscordStatus } from '@/lib/types/discord'

export const dynamic = 'force-dynamic'

const PYTHON_API_URL = process.env.PYTHON_API_URL || 'http://localhost:8001'
const TIMEOUT_MS = 5000
/** The bot writes SystemHealth every 15s; older than this means its health loop (or the bot) is stuck. */
const HEARTBEAT_STALE_SEC = 90

type Probe<T> = { ok: true; ms: number; data: T } | { ok: false; ms: number; error: string }

async function probe<T>(fn: () => Promise<T>): Promise<Probe<T>> {
  const start = Date.now()
  try {
    const data = await Promise.race([
      fn(),
      new Promise<never>((_, reject) => setTimeout(() => reject(new Error(`timed out after ${TIMEOUT_MS / 1000}s`)), TIMEOUT_MS)),
    ])
    return { ok: true, ms: Date.now() - start, data }
  } catch (error) {
    return { ok: false, ms: Date.now() - start, error: error instanceof Error ? error.message : String(error) }
  }
}

async function getJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, { cache: 'no-store', ...init })
  const body = await res.json().catch(() => null)
  if (!res.ok) throw new Error(body?.detail || body?.error || `HTTP ${res.status}`)
  return body as T
}

function ago(iso: string | Date | null | undefined, now: number): string {
  if (!iso) return 'never'
  const sec = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000))
  if (sec < 60) return `${sec}s ago`
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m ago`
  return `${Math.floor(sec / 86400)}d ${Math.floor((sec % 86400) / 3600)}h ago`
}

function duration(sec: number): string {
  if (sec < 3600) return `${Math.floor(sec / 60)}m`
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m`
  return `${Math.floor(sec / 86400)}d ${Math.floor((sec % 86400) / 3600)}h`
}

const money = (n: number | null | undefined, ccy?: string | null) =>
  n == null ? '—' : `${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}${ccy ? ` ${ccy}` : ''}`

const yesNo = (v: boolean | null | undefined, goodWhen = true): Detail['tone'] =>
  v == null ? undefined : v === goodWhen ? 'good' : 'bad'

function worst(issues: { level: 'warn' | 'down' }[], fallback: ConnStatus = 'ok'): ConnStatus {
  if (issues.some((i) => i.level === 'down')) return 'down'
  if (issues.some((i) => i.level === 'warn')) return 'warn'
  return fallback
}

// ---- bot-side shapes (src/api/connections_router.py) ----
interface BotStatus {
  telegram: {
    available: boolean
    reason?: string
    connected?: boolean
    auth?: TelegramAuth
    listeningSince?: string | null
    configuredCount?: number
    channels?: { id: string; title: string; username: string | null; lastMessageAt: string | null }[]
    unresolved?: { id: string; error: string }[]
    lastMessageAt?: string | null
    inflight?: number
  }
  /** Absent on a bot image from before the Discord listener existed. */
  discord?: DiscordStatus
  news: {
    available: boolean
    reason?: string
    enabled?: boolean
    running?: boolean
    events?: number
    activeBlocks?: number
    nextNews?: { title: string; country: string; impact: string; minutes_until: number } | null
    fetchedAt?: string | null
    stale?: boolean
    currencies?: string[]
    impacts?: string[]
  }
  health: {
    running: boolean
    startedAt: string | null
    lastCheck: string | null
    intervalSeconds: number
    components: Record<string, { status: string; message: string }>
  }
}

interface Mt5Terminal {
  connected: boolean
  trade_allowed: boolean
  tradeapi_disabled: boolean
  ping_last: number
  retransmission: number
  build: number
  company: string
}

interface Mt5Account {
  login: number
  server: string
  currency: string
  leverage: number
  balance: number
  equity: number
  margin: number
  margin_free: number
  margin_level: number
  trade_allowed: boolean
  trade_expert: boolean
}

export async function GET() {
  const denied = await requireOwner()
  if (denied) return denied

  const now = Date.now()
  const provider = await getActiveProvider()
  const mt5 = getMT5RestConfig()
  const mt5Headers: Record<string, string> = mt5.apiKey ? { 'X-API-Key': mt5.apiKey } : {}

  const [bot, mt5Health, mt5Terminal, mt5Account, mt5Bridge, db, redis, eaAccounts, heartbeat, userSettings] = await Promise.all([
    probe(() => getJson<BotStatus>(`${PYTHON_API_URL}/api/connections/status`)),
    provider === 'mt5rest' ? probe(() => getJson<{ mt5_connected: boolean }>(`${mt5.url}/health`)) : null,
    provider === 'mt5rest' ? probe(() => getJson<Mt5Terminal>(`${mt5.url}/terminal_info`, { headers: mt5Headers })) : null,
    provider === 'mt5rest' ? probe(() => getJson<Mt5Account>(`${mt5.url}/account_info`, { headers: mt5Headers })) : null,
    provider === 'mt5rest' ? probe(() => getJson<{ uptime_seconds: number }>(`${mt5.url}/metrics/health`, { headers: mt5Headers })) : null,
    probe(async () => {
      await prisma.$queryRawUnsafe('SELECT 1')
      const [pages] = await prisma.$queryRawUnsafe<{ page_count: bigint }[]>('PRAGMA page_count')
      const [size] = await prisma.$queryRawUnsafe<{ page_size: bigint }[]>('PRAGMA page_size')
      return { bytes: Number(pages.page_count) * Number(size.page_size) }
    }),
    probe(async () => {
      const client = new Redis(process.env.REDIS_URL || 'redis://redis:6379', {
        lazyConnect: true,
        connectTimeout: TIMEOUT_MS,
        maxRetriesPerRequest: 0,
        retryStrategy: () => null,
      })
      try {
        await client.connect()
        const t = Date.now()
        await client.ping()
        const pingMs = Date.now() - t
        const info = await client.info()
        const field = (k: string) => info.match(new RegExp(`^${k}:(.*)$`, 'm'))?.[1]?.trim()
        return {
          pingMs,
          uptimeSec: Number(field('uptime_in_seconds') ?? 0),
          memory: field('used_memory_human') ?? '—',
          clients: Number(field('connected_clients') ?? 0),
          version: field('redis_version') ?? '—',
        }
      } finally {
        client.disconnect()
      }
    }),
    prisma.eaAccount.findMany({ orderBy: { lastSeenAt: 'desc' } }).catch(() => null),
    prisma.systemHealth.findFirst({ orderBy: { updatedAt: 'desc' } }).catch(() => null),
    prisma.userSettings.findFirst().catch(() => null),
  ])

  let disabled: string[] = []
  try {
    const parsed = JSON.parse(userSettings?.disabledConnections || '[]')
    if (Array.isArray(parsed)) disabled = parsed
  } catch { /* keep empty */ }

  const botComponents: Record<string, { status: string; message: string }> =
    bot.ok ? bot.data.health.components : heartbeat ? JSON.parse(heartbeat.components) : {}

  const connections: ConnectionView[] = []

  // ---------------------------------------------------------------- Bot engine
  {
    const issues: { level: 'warn' | 'down'; text: string }[] = []
    const hbAge = heartbeat ? (now - new Date(heartbeat.lastCheck).getTime()) / 1000 : null
    if (!bot.ok) issues.push({ level: 'down', text: `Bot API unreachable (${bot.error}) — the bot process is down or restarting` })
    if (hbAge == null) issues.push({ level: 'down', text: 'The bot has never written a health report' })
    else if (hbAge > HEARTBEAT_STALE_SEC) issues.push({ level: 'down', text: `Last health report was ${ago(heartbeat!.lastCheck, now)} — the health loop is stuck or the bot is down` })
    if (bot.ok && !bot.data.health.running) issues.push({ level: 'warn', text: 'Health-check loop is not running inside the bot' })

    const startedAt = bot.ok ? bot.data.health.startedAt : null
    connections.push({
      key: 'bot',
      name: 'Bot Engine',
      role: 'Signal processing & execution',
      status: worst(issues),
      summary: bot.ok
        ? `Running${startedAt ? ` for ${duration((now - new Date(startedAt).getTime()) / 1000)}` : ''} · last health report ${ago(heartbeat?.lastCheck, now)}`
        : 'Not responding',
      latencyMs: bot.ms,
      issues: issues.map((i) => i.text),
      details: [
        { label: 'API', value: bot.ok ? `reachable (${bot.ms}ms)` : 'unreachable', tone: bot.ok ? 'good' : 'bad' },
        { label: 'Started', value: startedAt ? new Date(startedAt).toLocaleString('en-GB', { timeZone: 'UTC' }) + ' UTC' : '—' },
        { label: 'Health report', value: ago(heartbeat?.lastCheck, now), tone: hbAge != null && hbAge <= HEARTBEAT_STALE_SEC ? 'good' : 'bad' },
        { label: 'Check interval', value: bot.ok ? `${bot.data.health.intervalSeconds}s` : '—' },
      ],
      actions: bot.ok ? [{ id: 'bot.healthcheck', label: 'Run checks now' }] : [],
      links: [{ label: 'Logs', href: '/logs' }],
    })
  }

  // ---------------------------------------------------------------- Broker / MT5
  if (provider === 'mt5rest' && mt5Health && mt5Terminal && mt5Account && mt5Bridge) {
    const issues: { level: 'warn' | 'down'; text: string }[] = []
    const term = mt5Terminal.ok ? mt5Terminal.data : null
    const acct = mt5Account.ok ? mt5Account.data : null
    if (!mt5Health.ok) issues.push({ level: 'down', text: `MT5 REST bridge unreachable (${mt5Health.error})` })
    else if (!mt5Health.data.mt5_connected) issues.push({ level: 'down', text: 'Bridge is up but the MT5 terminal is not connected to the broker' })
    if (mt5Health.ok && !term) issues.push({ level: 'warn', text: `Terminal info unavailable (${!mt5Terminal.ok ? mt5Terminal.error : ''})` })
    if (term && !term.trade_allowed) issues.push({ level: 'down', text: '"Algo Trading" is switched OFF in the terminal — every order the bot sends will be rejected' })
    if (term?.tradeapi_disabled) issues.push({ level: 'down', text: 'Python trade API is disabled in the terminal settings' })
    if (acct && !acct.trade_allowed) issues.push({ level: 'down', text: 'Trading is not allowed on this account (investor/read-only login?)' })
    if (acct && !acct.trade_expert) issues.push({ level: 'down', text: 'The broker does not allow automated (EA) trading on this account' })
    if (term && term.ping_last > 300_000) issues.push({ level: 'warn', text: `High broker ping: ${Math.round(term.ping_last / 1000)}ms` })
    if (term && term.retransmission > 5) issues.push({ level: 'warn', text: `Network retransmission ${term.retransmission.toFixed(1)}% — unstable link to the broker` })
    if (mt5Health.ok && !acct) issues.push({ level: 'warn', text: `Account info unavailable (${!mt5Account.ok ? mt5Account.error : ''})` })

    const pingMs = term ? Math.round(term.ping_last / 1000) : null
    connections.push({
      key: 'mt5',
      name: 'MT5 REST API',
      role: 'Broker execution',
      status: worst(issues),
      summary: acct
        ? `${acct.login} @ ${acct.server}${pingMs != null ? ` · broker ping ${pingMs}ms` : ''}`
        : mt5Health.ok ? 'Bridge up, account unavailable' : 'Bridge unreachable',
      latencyMs: mt5Health.ms,
      issues: issues.map((i) => i.text),
      details: [
        { label: 'Terminal ↔ broker', value: term ? (term.connected ? 'connected' : 'disconnected') : '—', tone: yesNo(term?.connected) },
        { label: 'Algo Trading button', value: term ? (term.trade_allowed ? 'ON' : 'OFF') : '—', tone: yesNo(term?.trade_allowed) },
        { label: 'Account trading', value: acct ? (acct.trade_allowed ? 'allowed' : 'blocked') : '—', tone: yesNo(acct?.trade_allowed) },
        { label: 'EA trading (broker)', value: acct ? (acct.trade_expert ? 'allowed' : 'blocked') : '—', tone: yesNo(acct?.trade_expert) },
        { label: 'Broker ping', value: pingMs != null ? `${pingMs}ms` : '—' },
        { label: 'Retransmission', value: term ? `${term.retransmission.toFixed(2)}%` : '—' },
        { label: 'Balance', value: money(acct?.balance, acct?.currency) },
        { label: 'Equity', value: money(acct?.equity, acct?.currency) },
        { label: 'Margin level', value: acct && acct.margin > 0 ? `${acct.margin_level.toFixed(0)}%` : 'no margin used' },
        { label: 'Leverage', value: acct ? `1:${acct.leverage}` : '—' },
        { label: 'Terminal build', value: term ? String(term.build) : '—' },
        { label: 'Bridge uptime', value: mt5Bridge.ok ? duration(mt5Bridge.data.uptime_seconds) : '—' },
      ],
      actions: [],
      links: [{ label: 'Open terminal', href: '/mt5-terminal' }, { label: 'Account', href: '/account' }],
    })
  } else {
    const comp = botComponents['MetaAPI']
    const status: ConnStatus = !comp ? 'warn' : comp.status === 'healthy' ? 'ok' : comp.status === 'degraded' ? 'warn' : 'down'
    connections.push({
      key: 'mt5',
      name: 'MetaAPI',
      role: 'Broker execution (cloud)',
      status,
      summary: comp?.message ?? 'No report from the bot',
      latencyMs: null,
      issues: status === 'ok' ? [] : [comp?.message ?? 'The bot has not reported MetaAPI status'],
      details: [{ label: 'Bot report', value: comp?.status ?? '—' }],
      actions: [],
      links: [{ label: 'Account', href: '/account' }],
    })
  }

  // ---------------------------------------------------------------- Telegram listener
  {
    const tg = bot.ok ? bot.data.telegram : null
    const auth = tg?.available ? tg.auth : undefined
    const live = auth?.state === 'live'
    const issues: { level: 'warn' | 'down'; text: string }[] = []
    if (!bot.ok) issues.push({ level: 'down', text: 'Unknown — the bot is not responding' })
    else if (!tg?.available || !auth) issues.push({ level: 'down', text: tg?.reason ?? 'Listener not running' })
    else if (auth.state === 'logged_out') issues.push({ level: 'down', text: auth.error ?? 'Not logged in — no signals are being received. Log in below.' })
    else if (auth.state === 'code_sent' || auth.state === 'password_required') issues.push({ level: 'down', text: 'Login in progress — no signals are being received until it completes' })
    else if (auth.state === 'error') issues.push({ level: 'down', text: auth.error ?? 'Listener failed to start' })
    else if (auth.state === 'not_configured') { /* optional source that is not set up: reported as OFF below */ }
    else if (auth.state === 'starting') issues.push({ level: 'warn', text: auth.error ?? 'Connecting to Telegram…' })
    else {
      if (!tg.connected) issues.push({ level: 'down', text: 'Telegram client is disconnected — no signals are being received' })
      if (tg.configuredCount === 0) issues.push({ level: 'down', text: 'No channels configured to monitor' })
      for (const u of tg.unresolved ?? []) {
        issues.push({ level: 'warn', text: `Channel ${u.id} is configured but could not be joined/resolved, so it is NOT being listened to (${u.error})` })
      }
    }
    const channels = live ? tg?.channels ?? [] : []
    const account = auth?.account
    connections.push({
      key: 'telegram',
      name: 'Telegram',
      role: 'Signal source',
      status: auth?.state === 'not_configured' ? 'off' : worst(issues),
      summary: live
        ? `${account ? `${account.name}${account.username ? ` (@${account.username})` : ''} · ` : ''}listening to ${channels.length}/${tg?.configuredCount ?? 0} channels · last message ${ago(tg?.lastMessageAt, now)}`
        : auth?.state === 'not_configured' ? 'Not set up — the bot runs without Telegram. Add the API ID and API hash under AI & Bot → Telegram.'
        : auth?.state === 'logged_out' ? 'Not logged in'
        : auth?.state === 'code_sent' ? `Waiting for the login code (sent via ${auth.codeVia ?? 'Telegram'})`
        : auth?.state === 'password_required' ? 'Waiting for the 2FA password'
        : auth?.state === 'starting' ? 'Connecting…'
        : 'Not running',
      latencyMs: null,
      issues: issues.map((i) => i.text),
      details: live && tg
        ? [
            { label: 'Client', value: tg.connected ? 'connected' : 'disconnected', tone: yesNo(tg.connected) },
            { label: 'Account', value: account ? `${account.name}${account.username ? ` (@${account.username})` : ''}` : '—' },
            { label: 'Bot started', value: ago(tg.listeningSince, now) },
            { label: 'Messages in progress', value: String(tg.inflight ?? 0) },
          ]
        : [],
      table: channels.length || (live && tg?.unresolved?.length)
        ? {
            title: 'Channels (activity since bot start)',
            columns: ['Channel', 'Last message'],
            rows: [
              ...channels
                .slice()
                .sort((a, b) => (b.lastMessageAt ?? '').localeCompare(a.lastMessageAt ?? ''))
                .map((c) => ({ cells: [c.title + (c.username ? ` (@${c.username})` : ''), ago(c.lastMessageAt, now)] })),
              ...(tg?.unresolved ?? []).map((u) => ({ cells: [u.id, 'not listening'], tone: 'bad' as const })),
            ],
          }
        : undefined,
      actions: live ? [{ id: 'telegram.resync', label: 'Re-sync channels' }] : [],
      links: [{ label: 'Manage channels', href: '/config' }, { label: 'Browse', href: '/telegram-browser' }],
      telegramAuth: auth,
    })
  }

  // ---------------------------------------------------------------- Discord listener
  // Optional signal source: no card until it is switched on or a token is saved.
  {
    const dc = bot.ok ? bot.data.discord : undefined
    if (dc && (dc.enabled || dc.botTokenSet || dc.userTokenSet)) {
      const issues: { level: 'warn' | 'down'; text: string }[] = []
      if (dc.enabled) {
        if (dc.state === 'no_token') issues.push({ level: 'down', text: 'Switched on, but no token is saved' })
        else if (dc.state === 'error') issues.push({ level: 'down', text: dc.error ?? 'Not connected to Discord' })
        else if (dc.state === 'connecting') issues.push({ level: 'warn', text: 'Connecting to Discord…' })
        else if (dc.state === 'live') {
          if (dc.guildCount === 0) issues.push({ level: 'warn', text: 'Not in any server yet' })
          else if (dc.channels.length === 0) issues.push({ level: 'warn', text: 'No channels selected — nothing is being listened to' })
          for (const c of dc.channels) {
            if (c.problem) issues.push({ level: 'warn', text: `${c.guildName ?? c.guildId} #${c.name ?? c.id}: ${c.problem}` })
          }
        }
      }
      const live = dc.state === 'live'
      connections.push({
        key: 'discord',
        name: 'Discord',
        role: 'Signal source',
        status: dc.enabled ? worst(issues) : 'off',
        summary: !dc.enabled
          ? 'Switched off'
          : live
            ? `${dc.account?.name ?? 'Bot'} · listening to ${dc.channels.length} channel${dc.channels.length === 1 ? '' : 's'} in ${dc.guildCount} server${dc.guildCount === 1 ? '' : 's'} · last message ${ago(dc.lastMessageAt, now)}`
            : dc.state === 'connecting' ? 'Connecting…' : 'Not connected',
        latencyMs: null,
        issues: issues.map((i) => i.text),
        details: live
          ? [
              { label: dc.accountType === 'user' ? 'Own account' : 'Bot account', value: dc.account?.name ?? '—' },
              { label: 'Servers', value: String(dc.guildCount) },
              { label: 'Connected', value: ago(dc.listeningSince, now) },
              { label: 'Messages in progress', value: String(dc.inflight) },
            ]
          : [],
        table: dc.channels.length
          ? {
              title: 'Channels (activity since bot start)',
              columns: ['Channel', 'Last message'],
              rows: dc.channels
                .slice()
                .sort((a, b) => (b.lastMessageAt ?? '').localeCompare(a.lastMessageAt ?? ''))
                .map((c) => ({
                  cells: [`${c.guildName ?? c.guildId} #${c.name ?? c.id}`, c.problem ? 'not readable' : ago(c.lastMessageAt, now)],
                  tone: c.problem ? ('bad' as const) : undefined,
                })),
            }
          : undefined,
        actions: [],
        links: [{ label: 'Manage', href: '/discord' }],
      })
    }
  }

  // ---------------------------------------------------------------- Trade copier EAs
  if (eaAccounts && eaAccounts.length > 0) {
    const issues: { level: 'warn' | 'down'; text: string }[] = []
    const rows = eaAccounts.map((a) => {
      const conn = connectionOf(a.lastSeenAt, a.reportSeconds, now)
      const label = `${a.name || a.login} · ${a.login}@${a.server}`
      if (conn === 'offline') issues.push({ level: 'warn', text: `${label} has not reported for ${ago(a.lastSeenAt, now).replace(' ago', '')}` })
      else if (conn === 'stale') issues.push({ level: 'warn', text: `${label} is late reporting (${ago(a.lastSeenAt, now)})` })
      if (conn !== 'offline' && !a.feedOk) issues.push({ level: 'warn', text: `${label} cannot read the master feed (${a.pollFailures} failed polls${a.lastError ? `: ${a.lastError}` : ''})` })
      if (a.halted) issues.push({ level: 'warn', text: `${label} is halted by its daily-loss limit — no new trades` })
      return {
        conn,
        cells: [
          label,
          conn,
          ago(a.lastSeenAt, now),
          `${a.mode ?? '—'}${a.halted ? ' · HALTED' : ''}`,
          a.feedOk ? 'ok' : `failing (${a.pollFailures})`,
        ],
        tone: (conn === 'online' && a.feedOk && !a.halted ? 'good' : conn === 'offline' ? 'bad' : 'warn') as Detail['tone'],
      }
    })
    const online = rows.filter((r) => r.conn === 'online').length
    connections.push({
      key: 'copier',
      name: 'Trade Copier',
      role: 'Mirror accounts (EA)',
      status: online === 0 ? 'down' : worst(issues),
      summary: `${online}/${eaAccounts.length} mirror account${eaAccounts.length === 1 ? '' : 's'} online`,
      latencyMs: null,
      issues: issues.map((i) => i.text),
      details: [],
      table: {
        title: 'Mirror terminals',
        columns: ['Account', 'State', 'Last report', 'Mode', 'Feed'],
        rows: rows.map(({ cells, tone }) => ({ cells, tone })),
      },
      actions: [],
      links: [{ label: 'Open copier', href: '/copier' }, { label: 'API keys', href: '/settings/api-keys' }],
    })
  }

  // ---------------------------------------------------------------- News filter feed
  {
    const news = bot.ok ? bot.data.news : null
    const issues: { level: 'warn' | 'down'; text: string }[] = []
    if (!bot.ok) issues.push({ level: 'warn', text: 'Unknown — the bot is not responding' })
    else if (!news?.available) issues.push({ level: 'warn', text: news?.reason ?? 'News service not running' })
    else if (news.enabled) {
      if (!news.running) issues.push({ level: 'warn', text: 'News filter is enabled but its monitor is not running' })
      if (!news.events) issues.push({ level: 'warn', text: 'No news events cached — trades are NOT being filtered around news' })
      else if (news.stale) issues.push({ level: 'warn', text: 'News cache has no events for the current week' })
    }
    const next = news?.nextNews
    connections.push({
      key: 'news',
      name: 'News Monitor',
      role: 'Economic calendar filter',
      status: news?.available && !news.enabled ? 'off' : worst(issues),
      summary: !news?.available
        ? 'Not running'
        : !news.enabled
          ? 'News filter disabled in settings'
          : `${news.events ?? 0} events this week${next ? ` · next: ${next.country} ${next.title} in ${duration(next.minutes_until * 60)}` : ''}`,
      latencyMs: null,
      issues: issues.map((i) => i.text),
      details: news?.available
        ? [
            { label: 'Filter', value: news.enabled ? 'enabled' : 'disabled' },
            { label: 'Last fetched', value: ago(news.fetchedAt, now) },
            { label: 'Events cached', value: String(news.events ?? 0) },
            { label: 'Active blocks', value: String(news.activeBlocks ?? 0), tone: news.activeBlocks ? 'warn' : undefined },
            { label: 'Currencies', value: news.currencies?.join(', ') || '—' },
            { label: 'Impacts', value: news.impacts?.join(', ') || '—' },
            ...(next ? [{ label: 'Next event', value: `${next.impact} · ${next.country} ${next.title} in ${duration(next.minutes_until * 60)}` }] : []),
          ]
        : [],
      actions: news?.available ? [{ id: 'news.refresh', label: 'Fetch now' }] : [],
      links: [{ label: 'Calendar', href: '/calendar' }],
    })
  }

  // ---------------------------------------------------------------- Notifications (bot report only)
  {
    const comp = botComponents['Notifications']
    const status: ConnStatus = !comp ? 'warn' : comp.status === 'healthy' ? 'ok' : comp.status === 'degraded' ? 'warn' : 'down'
    connections.push({
      key: 'notifications',
      name: 'Notifications',
      role: 'Telegram bot alerts',
      status,
      summary: comp?.message ?? 'No report from the bot',
      latencyMs: null,
      issues: status === 'ok' ? [] : [comp?.message ?? 'The bot has not reported notification status'],
      details: [],
      actions: [],
      links: [{ label: 'Settings', href: '/config' }],
    })
  }

  // ---------------------------------------------------------------- Database
  connections.push({
    key: 'database',
    name: 'Database',
    role: 'SQLite storage',
    status: db.ok ? (db.ms > 1000 ? 'warn' : 'ok') : 'down',
    summary: db.ok ? `${(db.data.bytes / 1024 / 1024).toFixed(1)} MB · query ${db.ms}ms` : db.error,
    latencyMs: db.ms,
    issues: db.ok ? (db.ms > 1000 ? [`Slow query: ${db.ms}ms (database locked or disk busy)`] : []) : [`Database error: ${db.error}`],
    details: db.ok
      ? [
          { label: 'Size', value: `${(db.data.bytes / 1024 / 1024).toFixed(1)} MB` },
          { label: 'Query latency', value: `${db.ms}ms` },
          { label: 'Bot sees DB', value: botComponents['Database']?.status ?? '—', tone: botComponents['Database'] ? yesNo(botComponents['Database'].status === 'healthy') : undefined },
        ]
      : [],
    actions: [],
    links: [],
  })

  // ---------------------------------------------------------------- Redis
  connections.push({
    key: 'redis',
    name: 'Redis',
    role: 'Live tick & notification stream',
    status: redis.ok ? 'ok' : 'down',
    summary: redis.ok ? `ping ${redis.data.pingMs}ms · ${redis.data.memory} · ${redis.data.clients} clients` : redis.error,
    latencyMs: redis.ok ? redis.data.pingMs : null,
    issues: redis.ok ? [] : [`Redis unreachable (${redis.error}) — live prices and notification streams stop`],
    details: redis.ok
      ? [
          { label: 'Ping', value: `${redis.data.pingMs}ms` },
          { label: 'Memory', value: redis.data.memory },
          { label: 'Clients', value: String(redis.data.clients) },
          { label: 'Uptime', value: duration(redis.data.uptimeSec) },
          { label: 'Version', value: redis.data.version },
        ]
      : [],
    actions: [],
    links: [],
  })

  for (const c of connections) c.disabled = disabled.includes(c.name)

  const active = connections.filter((c) => !c.disabled)
  const body: ConnectionsResponse = {
    generatedAt: new Date(now).toISOString(),
    overall: active.some((c) => c.status === 'down') ? 'down' : active.some((c) => c.status === 'warn') ? 'warn' : 'ok',
    connections,
  }
  return NextResponse.json(body, { headers: { 'Cache-Control': 'no-store' } })
}
