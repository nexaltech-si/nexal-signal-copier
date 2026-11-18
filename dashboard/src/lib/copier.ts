// Trade Copier view model: joins the master's live snapshot (backend
// /api/ea/mirror/state) with what each copier EA last reported (EaAccount.links)
// into per-ticket sync states for the /copier page. Pure — no I/O — so it can
// be tested on its own.

export interface MasterPosition {
  ticket: string
  symbol: string
  rawSymbol: string
  side: 'BUY' | 'SELL'
  volume: number
  openPrice: number
  currentPrice: number | null
  sl: number | null
  tp: number | null
  profit: number | null
  magic: number | null
  ageMinutes: number | null
  tradeId: string | null
  signalId: string | null
  channel: string | null
}

export interface MasterOrder {
  ticket: string
  symbol: string
  rawSymbol: string
  type: string
  volume: number
  price: number
  sl: number | null
  tp: number | null
  magic: number | null
  ageMinutes: number | null
  tradeId: string | null
  signalId: string | null
  channel: string | null
}

export interface MasterSnapshot {
  version: number
  generatedAt: string
  master: {
    login: string
    server: string | null
    company: string | null
    currency: string | null
    leverage: number | null
    balance: number | null
    equity: number | null
    margin: number | null
    freeMargin: number | null
    profit: number | null
  }
  positions: MasterPosition[]
  orders: MasterOrder[]
}

/** One master->mirror ticket link, as the EA reports it (see /api/ea/report). */
export interface EaLink {
  master: string | null
  mirror: string | null
  // WAIT: not copied yet for a transient reason (spread, max positions, ...)
  state: 'OPEN' | 'PENDING' | 'SKIPPED' | 'DONE' | 'DRY' | 'WAIT'
  symbol: string | null
  side: string | null
  volume: number | null
  price: number | null
  sl: number | null
  tp: number | null
  profit: number | null
  inSync: boolean
  note: string | null
}

export type Connection = 'online' | 'stale' | 'offline'

export type SyncStatus =
  | 'SYNCED' // mirror holds it and the EA reports SL/TP/volume matching
  | 'DRIFT' // mirror holds it but something differs (note says what)
  | 'AWAITING_FILL' // master filled; mirror's pending order hasn't yet
  | 'MISSING' // not on the mirror (note says why when the EA reported a reason)
  | 'SKIPPED' // EA decided not to copy it (note says why)
  | 'CLOSED' // mirror's copy closed on its own (its SL/TP, or by hand)
  | 'DRY' // dry run: would have copied
  | 'UNKNOWN' // account isn't reporting, so its state is unknown

export interface SyncCell {
  status: SyncStatus
  note: string | null
  mirror: { ticket: string | null; volume: number | null; price: number | null; sl: number | null; tp: number | null; profit: number | null } | null
}

export interface AccountInput {
  id: string
  keyLabel: string
  keyActive: boolean
  login: string
  server: string
  broker: string | null
  name: string | null
  currency: string | null
  leverage: number | null
  eaVersion: string | null
  mode: string | null
  halted: boolean
  sizing: string | null
  pollSeconds: number | null
  reportSeconds: number | null
  balance: number | null
  equity: number | null
  margin: number | null
  freeMargin: number | null
  lastSeenAt: Date
  lastIp: string | null
  feedOk: boolean
  pollFailures: number
  lastError: string | null
  links: string | null
  events24h: number
}

const DEFAULT_REPORT_SECONDS = 15
const STALE_AFTER_SECONDS = 300
// Tickets with no master counterpart that the EA still holds are mid-close
// (it waits for N consecutive snapshots before acting) or failing to close.
const ACTIVE_STATES = new Set(['OPEN', 'PENDING'])

export function connectionOf(lastSeenAt: Date, reportSeconds: number | null, now: number): Connection {
  const ageSec = (now - lastSeenAt.getTime()) / 1000
  const expected = reportSeconds && reportSeconds > 0 ? reportSeconds : DEFAULT_REPORT_SECONDS
  if (ageSec <= Math.max(3 * expected, 30)) return 'online'
  if (ageSec <= STALE_AFTER_SECONDS) return 'stale'
  return 'offline'
}

export function parseLinks(json: string | null): EaLink[] {
  if (!json) return []
  try {
    const v = JSON.parse(json)
    return Array.isArray(v) ? v : []
  } catch {
    return []
  }
}

export function syncCell(kind: 'POSITION' | 'ORDER', link: EaLink | undefined, connection: Connection): SyncCell {
  if (connection === 'offline') return { status: 'UNKNOWN', note: 'account not reporting', mirror: null }
  if (!link) return { status: 'MISSING', note: null, mirror: null }

  const mirror = {
    ticket: link.mirror,
    volume: link.volume,
    price: link.price,
    sl: link.sl,
    tp: link.tp,
    profit: link.profit,
  }
  switch (link.state) {
    case 'WAIT':
      return { status: 'MISSING', note: link.note, mirror: null }
    case 'SKIPPED':
      return { status: 'SKIPPED', note: link.note, mirror: null }
    case 'DONE':
      return { status: 'CLOSED', note: link.note, mirror: null }
    case 'DRY':
      return { status: 'DRY', note: link.note, mirror: null }
    case 'PENDING':
      if (kind === 'POSITION') return { status: 'AWAITING_FILL', note: link.note, mirror }
      break
  }
  return { status: link.inSync ? 'SYNCED' : 'DRIFT', note: link.note, mirror }
}

const ISSUE_STATUSES = new Set<SyncStatus>(['DRIFT', 'MISSING', 'AWAITING_FILL'])

export function buildCopierView(master: MasterSnapshot | null, accounts: AccountInput[], now: number) {
  const items = master
    ? [
        ...master.positions.map((p) => ({
          kind: 'POSITION' as const,
          ticket: p.ticket,
          symbol: p.rawSymbol,
          side: p.side,
          volume: p.volume,
          price: p.openPrice,
          sl: p.sl,
          tp: p.tp,
          profit: p.profit,
          ageMinutes: p.ageMinutes,
          channel: p.channel,
          manual: !p.tradeId,
        })),
        ...master.orders.map((o) => ({
          kind: 'ORDER' as const,
          ticket: o.ticket,
          symbol: o.rawSymbol,
          side: o.type,
          volume: o.volume,
          price: o.price,
          sl: o.sl,
          tp: o.tp,
          profit: null,
          ageMinutes: o.ageMinutes,
          channel: o.channel,
          manual: !o.tradeId,
        })),
      ]
    : []
  const masterTickets = new Set(items.map((i) => i.ticket))

  const views = accounts.map((a) => {
    const connection = connectionOf(a.lastSeenAt, a.reportSeconds, now)
    const links = parseLinks(a.links)
    const byMaster = new Map(links.filter((l) => l.master).map((l) => [l.master as string, l]))

    const cells: Record<string, SyncCell> = {}
    const counts: Partial<Record<SyncStatus, number>> = {}
    if (master) {
      for (const item of items) {
        const cell = syncCell(item.kind, byMaster.get(item.ticket), connection)
        cells[item.ticket] = cell
        counts[cell.status] = (counts[cell.status] ?? 0) + 1
      }
    }
    // Still held on the mirror though the master no longer has it.
    const closing = master
      ? links.filter((l) => ACTIVE_STATES.has(l.state) && l.master && !masterTickets.has(l.master))
      : []

    const issues = Object.entries(counts)
      .filter(([s]) => ISSUE_STATUSES.has(s as SyncStatus))
      .reduce((n, [, c]) => n + (c ?? 0), 0) + closing.length

    return {
      ...a,
      links: undefined,
      connection,
      lastSeenAgoSec: Math.max(0, Math.round((now - a.lastSeenAt.getTime()) / 1000)),
      cells,
      counts,
      synced: counts.SYNCED ?? 0,
      issues,
      closing,
      mirrorPositions: links.filter((l) => l.state === 'OPEN').length,
      mirrorOrders: links.filter((l) => l.state === 'PENDING').length,
      mirrorProfit: links.reduce((sum, l) => sum + (l.state === 'OPEN' && l.profit ? l.profit : 0), 0),
    }
  })

  return { items, accounts: views }
}

export type CopierView = ReturnType<typeof buildCopierView>
export type CopierAccountView = CopierView['accounts'][number]
export type CopierItem = CopierView['items'][number]
