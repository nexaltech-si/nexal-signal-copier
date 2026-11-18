import { NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'
import { prisma } from '@/lib/prisma'
import { buildCopierView, type MasterSnapshot } from '@/lib/copier'

export const dynamic = 'force-dynamic'

const PYTHON_API_URL = process.env.PYTHON_API_URL || 'http://localhost:8001'

/** Trade Copier page data: the master's live snapshot, every copier EA that
 *  has reported in, and per-ticket sync state between them. Owner-only. */
export async function GET() {
  const denied = await requireOwner()
  if (denied) return denied

  let master: MasterSnapshot | null = null
  let masterError: string | null = null
  const internalKey = process.env.EA_API_KEY
  if (!internalKey) {
    masterError = 'EA_API_KEY is not configured on the backend'
  } else {
    try {
      const res = await fetch(`${PYTHON_API_URL}/api/ea/mirror/state`, {
        headers: { 'X-EA-Key': internalKey },
        cache: 'no-store',
      })
      const body = await res.json().catch(() => null)
      if (res.ok && body) master = body
      else masterError = body?.detail || `backend HTTP ${res.status}`
    } catch (error) {
      masterError = error instanceof Error ? error.message : 'failed to reach backend'
    }
  }

  const since = new Date(Date.now() - 86_400_000)
  const [accounts, eventCounts] = await Promise.all([
    prisma.eaAccount.findMany({
      include: { apiKey: { select: { label: true, revokedAt: true, expiresAt: true } } },
      orderBy: [{ lastSeenAt: 'desc' }],
    }),
    prisma.eaEvent.groupBy({ by: ['accountId'], where: { createdAt: { gte: since } }, _count: { _all: true } }),
  ])
  const events24h = new Map(eventCounts.map((e) => [e.accountId, e._count._all]))

  const now = Date.now()
  const view = buildCopierView(
    master,
    accounts.map(({ apiKey, ...a }) => ({
      ...a,
      keyLabel: apiKey.label,
      keyActive: !apiKey.revokedAt && !(apiKey.expiresAt && apiKey.expiresAt.getTime() <= now),
      events24h: events24h.get(a.id) ?? 0,
    })),
    now
  )

  return NextResponse.json({
    generatedAt: new Date(now).toISOString(),
    master: master ? { ...master.master, generatedAt: master.generatedAt } : null,
    masterError,
    ...view,
  })
}
