import { NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { requireOwner } from '@/lib/auth'

// Returns a lightweight list of signals for a channel to power the timeline chart.
// Only fields needed for chart markers are returned (no imageData, no raw replies).
export async function GET(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const { searchParams } = new URL(request.url)
    const channelId = searchParams.get('channelId')
    const channelName = searchParams.get('channelName')
    const symbol = searchParams.get('symbol') // optional symbol filter
    const limit = Math.min(parseInt(searchParams.get('limit') || '200'), 2000)

    if (!channelId && !channelName) {
      return NextResponse.json({ error: 'channelId or channelName required' }, { status: 400 })
    }

    const whereClause: Record<string, unknown> = {}
    if (channelId) whereClause.channelId = channelId
    else if (channelName) whereClause.channelName = { contains: channelName }
    if (symbol) whereClause.symbol = symbol.toUpperCase()

    // Only include signals that have trade-relevant data
    const signals = await prisma.signal.findMany({
      where: whereClause,
      select: {
        id: true,
        createdAt: true,
        symbol: true,
        orderType: true,
        entryPrice: true,
        entryRangeMin: true,
        entryRangeMax: true,
        stopLoss: true,
        takeProfit: true,
        status: true,
        channelName: true,
        channelId: true,
        confidence: true,
        aiVerificationType: true,
        rejectionReason: true,
        trades: {
          select: {
            id: true,
            status: true,
            profitLoss: true,
            entryPrice: true,
            closePrice: true,
            createdAt: true,
            closedAt: true,
          },
        },
      },
      orderBy: { createdAt: 'asc' },
      take: limit,
    })

    // Compute per-signal outcome for chart colouring
    const enriched = signals.map((sig) => {
      const totalPnL = sig.trades.reduce((s, t) => s + (t.profitLoss || 0), 0)
      const hasTrades = sig.trades.length > 0
      const allClosed = hasTrades && sig.trades.every((t) => t.status === 'CLOSED')
      const entryPrice =
        sig.entryPrice ??
        (sig.entryRangeMin != null && sig.entryRangeMax != null
          ? (sig.entryRangeMin + sig.entryRangeMax) / 2
          : null)

      let tpLevels: number[] = []
      try {
        if (sig.takeProfit) tpLevels = JSON.parse(sig.takeProfit)
      } catch {
        /* ignore */
      }

      return {
        id: sig.id,
        createdAt: sig.createdAt,
        symbol: sig.symbol,
        orderType: sig.orderType,
        entryPrice,
        stopLoss: sig.stopLoss,
        tpLevels,
        status: sig.status,
        channelName: sig.channelName,
        channelId: sig.channelId,
        confidence: sig.confidence,
        aiVerificationType: sig.aiVerificationType,
        rejectionReason: sig.rejectionReason,
        totalPnL,
        hasTrades,
        allClosed,
        tradeCount: sig.trades.length,
      }
    })

    return NextResponse.json(enriched)
  } catch (error) {
    console.error('Error fetching channel timeline:', error)
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 })
  }
}
