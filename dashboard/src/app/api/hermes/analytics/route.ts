import { NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { requireOwner } from '@/lib/auth'

// GET /api/hermes/analytics -> aggregate stats over Hermes setups
export async function GET() {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const setups: { setupType: string; status: string; bias: string }[] =
      await prisma.hermesSetup.findMany({
        select: { setupType: true, status: true, bias: true },
      })
    const total = setups.length
    const byType: Record<string, number> = {}
    const byStatus: Record<string, number> = {}
    const byBias: Record<string, number> = {}
    for (const s of setups) {
      byType[s.setupType] = (byType[s.setupType] || 0) + 1
      byStatus[s.status] = (byStatus[s.status] || 0) + 1
      byBias[s.bias] = (byBias[s.bias] || 0) + 1
    }
    const wins = (byStatus['TP1'] || 0) + (byStatus['TP2'] || 0) + (byStatus['TP3'] || 0)
    const losses = byStatus['SL'] || 0
    const invalidated = byStatus['INVALIDATED'] || 0
    const resolved = wins + losses
    const winRate = resolved ? Math.round((wins / resolved) * 100) : null
    return NextResponse.json({ total, byType, byStatus, byBias, wins, losses, invalidated, winRate })
  } catch (e: any) {
    return NextResponse.json({ error: e?.message ?? 'failed' }, { status: 500 })
  }
}
