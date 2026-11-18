import { NextRequest, NextResponse } from 'next/server'
import { checkAuthorization } from '@/lib/auth'
import { prisma } from '@/lib/prisma'

export const dynamic = 'force-dynamic'

/** Connection log for one key — one row per client IP (and status) with
 *  first/last seen and hit count, most recently active first. Admin-only.
 *  Capped at 200 rows; the table only grows when a key shows up from a new IP. */
export async function GET(request: NextRequest, { params }: { params: { id: string } }) {
  const { authorized, response } = await checkAuthorization()
  if (!authorized) return response

  const limitParam = Number(request.nextUrl.searchParams.get('limit'))
  const limit = Number.isFinite(limitParam) && limitParam > 0 ? Math.min(limitParam, 200) : 50

  const usage = await prisma.apiKeyUsage.findMany({
    where: { apiKeyId: params.id },
    orderBy: { lastSeenAt: 'desc' },
    take: limit,
  })

  return NextResponse.json({
    usage: usage.map((u) => ({
      id: u.id,
      createdAt: u.createdAt,
      lastSeenAt: u.lastSeenAt,
      hits: u.hits,
      ip: u.ip,
      userAgent: u.userAgent,
      endpoint: u.endpoint,
      status: u.status,
    })),
  })
}
