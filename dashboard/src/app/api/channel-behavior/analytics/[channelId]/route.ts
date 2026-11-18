import { NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { requireOwner } from '@/lib/auth'

export async function GET(
  _request: Request,
  { params }: { params: { channelId: string } }
) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const analytics = await prisma.channelBehaviorAnalytics.findMany({
      where: { channelId: params.channelId },
      orderBy: { occurrenceCount: 'desc' },
      take: 500,
    })

    return NextResponse.json({
      analytics: analytics.map((a) => ({
        id: a.id,
        channelId: a.channelId,
        messageType: a.messageType,
        messagePattern: a.messagePattern,
        symbol: a.symbol,
        action: a.action,
        hasPips: a.hasPips,
        hasPrice: a.hasPrice,
        occurrenceCount: a.occurrenceCount,
        confidenceScore: a.confidenceScore,
        createdAt: a.createdAt.toISOString(),
      })),
    })
  } catch (error) {
    console.error('Error fetching channel behavior analytics:', error)
    return NextResponse.json({ error: 'Failed to fetch analytics' }, { status: 500 })
  }
}
