import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { authenticateEa } from '@/lib/eaAuth'

export const dynamic = 'force-dynamic'

const ENDPOINT = '/api/ea/report'
const MAX_BODY_BYTES = 256 * 1024
const MAX_LINKS = 500
const MAX_EVENTS = 100
const EVENT_RETENTION_DAYS = 30

/**
 * Status report from a copier EA (NexalSignalMirrorEA v2+), POSTed every
 * InpReportSeconds and right after it acts. Upserts that terminal's EaAccount
 * row (one per key + login + server) and appends its new events — this is what
 * the Trade Copier page (/copier) shows. Everything here is untrusted input
 * from a customer machine: sizes are capped, every field is coerced, and only
 * whitelisted link fields are stored.
 *
 * Exempt from Clerk in middleware.ts; the key check is the auth.
 */
export async function POST(request: NextRequest) {
  const auth = await authenticateEa(request, ENDPOINT)
  if (!auth.ok) return auth.response

  const raw = await request.text()
  if (raw.length > MAX_BODY_BYTES) {
    return NextResponse.json({ error: 'report too large' }, { status: 413 })
  }
  let body: Record<string, unknown>
  try {
    body = JSON.parse(raw)
  } catch {
    return NextResponse.json({ error: 'invalid JSON' }, { status: 400 })
  }
  if (!body || typeof body !== 'object') {
    return NextResponse.json({ error: 'invalid report' }, { status: 400 })
  }

  const login = str(body.login, 32)
  const server = str(body.server, 128)
  if (!login || !server) {
    return NextResponse.json({ error: 'login and server are required' }, { status: 400 })
  }

  const links = Array.isArray(body.links) ? body.links.slice(0, MAX_LINKS).map(cleanLink) : []
  const events = Array.isArray(body.events) ? body.events.slice(-MAX_EVENTS).map(cleanEvent) : []

  const fields = {
    broker: str(body.broker, 128),
    name: str(body.name, 128),
    currency: str(body.currency, 8),
    leverage: int(body.leverage),
    eaVersion: str(body.eaVersion, 16),
    mode: body.mode === 'LIVE' ? 'LIVE' : 'DRY',
    halted: body.halted === true,
    sizing: str(body.sizing, 64),
    pollSeconds: int(body.pollSeconds),
    reportSeconds: int(body.reportSeconds),
    balance: num(body.balance),
    equity: num(body.equity),
    margin: num(body.margin),
    freeMargin: num(body.freeMargin),
    lastSeenAt: new Date(),
    lastIp: auth.ip,
    feedOk: body.feedOk !== false,
    pollFailures: int(body.pollFailures) ?? 0,
    lastError: str(body.lastError, 500),
    positionsCount: links.filter((l) => l.state === 'OPEN').length,
    ordersCount: links.filter((l) => l.state === 'PENDING').length,
    links: JSON.stringify(links),
  }

  const account = await prisma.eaAccount.upsert({
    where: { apiKeyId_login_server: { apiKeyId: auth.apiKey.id, login, server } },
    create: { apiKeyId: auth.apiKey.id, login, server, ...fields },
    update: fields,
  })

  if (events.length > 0) {
    await prisma.eaEvent.createMany({ data: events.map((e) => ({ ...e, accountId: account.id })) })
  }
  await prisma.eaEvent.deleteMany({
    where: { accountId: account.id, createdAt: { lt: new Date(Date.now() - EVENT_RETENTION_DAYS * 86_400_000) } },
  })

  return NextResponse.json({ ok: true })
}

function str(v: unknown, max: number): string | null {
  if (typeof v === 'number' && Number.isFinite(v)) v = String(v)
  if (typeof v !== 'string') return null
  const s = v.trim().slice(0, max)
  return s || null
}

function num(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

function int(v: unknown): number | null {
  const n = num(v)
  return n === null ? null : Math.trunc(n)
}

const LINK_STATES = new Set(['OPEN', 'PENDING', 'SKIPPED', 'DONE', 'DRY', 'WAIT'])

function cleanLink(v: unknown) {
  const l = (v && typeof v === 'object' ? v : {}) as Record<string, unknown>
  const state = typeof l.state === 'string' && LINK_STATES.has(l.state) ? l.state : 'SKIPPED'
  return {
    master: str(l.master, 32),
    mirror: str(l.mirror, 32),
    state,
    symbol: str(l.symbol, 32),
    side: str(l.side, 16),
    volume: num(l.volume),
    price: num(l.price),
    sl: num(l.sl),
    tp: num(l.tp),
    profit: num(l.profit),
    inSync: l.inSync === true,
    note: str(l.note, 200),
  }
}

function cleanEvent(v: unknown) {
  const e = (v && typeof v === 'object' ? v : {}) as Record<string, unknown>
  return {
    type: str(e.type, 16) ?? 'INFO',
    symbol: str(e.symbol, 32),
    masterTicket: str(e.master, 32),
    mirrorTicket: str(e.mirror, 32),
    message: str(e.msg, 500) ?? '',
  }
}
