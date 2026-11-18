import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { requireOwner } from '@/lib/auth'

// GET /api/hermes/setups?status=&symbol=&limit=
// List Hermes setups (isolated from channel Signal/TradePlan pipeline).
export async function GET(req: NextRequest) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const { searchParams } = new URL(req.url)
    const status = searchParams.get('status') || undefined
    const symbol = searchParams.get('symbol') || undefined
    const limit = Math.min(parseInt(searchParams.get('limit') || '100', 10), 500)

    const setups = await prisma.hermesSetup.findMany({
      where: { ...(status ? { status } : {}), ...(symbol ? { symbol } : {}) },
      orderBy: { createdAt: 'desc' },
      take: limit,
      include: { events: { orderBy: { createdAt: 'asc' } } },
    })
    return NextResponse.json({ setups })
  } catch (e: any) {
    return NextResponse.json({ error: e?.message ?? 'failed' }, { status: 500 })
  }
}

// POST /api/hermes/setups
// Body: { symbol, setupType, bias, entryMin?, entryMax?, sl?, tps?[], invalidation?,
//         reasoning?, triggerTf?, expectedHold?, riskPct?, linkedMessageId?, sourceConversationId? }
// Creates a setup + a CREATED event. Hermes calls this via HTTP when it generates a setup.
export async function POST(req: NextRequest) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const b = await req.json()
    if (!b?.symbol || !b?.setupType || !b?.bias) {
      return NextResponse.json(
        { error: 'symbol, setupType, bias are required' },
        { status: 400 }
      )
    }
    const setupType = String(b.setupType).toUpperCase()
    const bias = String(b.bias).toUpperCase()
    const validTypes = ['SCALP', 'INTRADAY', 'SWING']
    if (!validTypes.includes(setupType)) {
      return NextResponse.json(
        { error: `setupType must be one of ${validTypes.join(', ')}` },
        { status: 400 }
      )
    }

    const setup = await prisma.hermesSetup.create({
      data: {
        symbol: String(b.symbol),
        setupType,
        bias,
        entryMin: b.entryMin ?? null,
        entryMax: b.entryMax ?? null,
        sl: b.sl ?? null,
        tps: b.tps ? JSON.stringify(b.tps) : null,
        invalidation: b.invalidation ?? null,
        reasoning: b.reasoning ?? null,
        triggerTf: b.triggerTf ?? null,
        expectedHold: b.expectedHold ?? null,
        riskPct: b.riskPct ?? null,
        linkedMessageId: b.linkedMessageId ?? null,
        sourceConversationId: b.sourceConversationId ?? null,
        status: 'PENDING',
        events: {
          create: [{ eventType: 'CREATED', note: 'Setup logged by Hermes' }],
        },
      },
      include: { events: true },
    })
    return NextResponse.json({ setup }, { status: 201 })
  } catch (e: any) {
    return NextResponse.json({ error: e?.message ?? 'failed' }, { status: 500 })
  }
}
