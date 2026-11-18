import { NextRequest, NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'
import { prisma } from '@/lib/prisma'

export const dynamic = 'force-dynamic'

/** Recent copier actions reported by one mirror account's EA. Owner-only. */
export async function GET(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const denied = await requireOwner()
  if (denied) return denied

  const { id } = await params
  const limitParam = Number(request.nextUrl.searchParams.get('limit'))
  const limit = Number.isFinite(limitParam) && limitParam > 0 ? Math.min(limitParam, 500) : 100

  const events = await prisma.eaEvent.findMany({
    where: { accountId: id },
    orderBy: { createdAt: 'desc' },
    take: limit,
  })
  return NextResponse.json({ events })
}
