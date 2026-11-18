import { NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { requireOwner } from '@/lib/auth'

export async function POST(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const { status } = await request.json()

    if (!status || typeof status !== 'string') {
      return NextResponse.json({ error: 'status is required' }, { status: 400 })
    }

    const signals = await prisma.signal.findMany({
      where: { status },
      select: { id: true },
    })
    const signalIds = signals.map(s => s.id)

    if (signalIds.length === 0) {
      return NextResponse.json({ deleted: 0 })
    }

    // Get trade IDs linked to these signals
    const trades = await prisma.trade.findMany({
      where: { signalId: { in: signalIds } },
      select: { id: true },
    })
    const tradeIds = trades.map(t => t.id)

    const [, , , deleted] = await prisma.$transaction([
      // 1. Delete trade actions for linked trades
      prisma.tradeAction.deleteMany({ where: { tradeId: { in: tradeIds } } }),
      // 2. Nullify parentTradeId on child trades referencing these trades
      prisma.trade.updateMany({ where: { parentTradeId: { in: tradeIds } }, data: { parentTradeId: null } }),
      // 3. Delete trades (TradePlan cascades automatically via onDelete: Cascade on Signal)
      prisma.trade.deleteMany({ where: { signalId: { in: signalIds } } }),
      // 4. Delete signals (TradePlan deleted automatically by DB cascade)
      prisma.signal.deleteMany({ where: { id: { in: signalIds } } }),
    ])

    return NextResponse.json({ deleted: deleted.count })
  } catch (error) {
    console.error('Error bulk-deleting signals by status:', error)
    return NextResponse.json({ error: 'Failed to delete signals' }, { status: 500 })
  }
}
