import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { requireOwner } from '@/lib/auth'

// GET /api/hermes/chat            -> { conversations: [...] }
// GET /api/hermes/chat?conversationId=X -> { messages: [...] }
export async function GET(req: NextRequest) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const { searchParams } = new URL(req.url)
    const conversationId = searchParams.get('conversationId')
    if (conversationId) {
      const messages = await prisma.hermesMessage.findMany({
        where: { conversationId },
        orderBy: { timestamp: 'asc' },
        take: 500,
      })
      return NextResponse.json({ messages })
    }
    const conversations = await prisma.hermesConversation.findMany({
      orderBy: { startedAt: 'desc' },
      take: 100,
    })
    return NextResponse.json({ conversations })
  } catch (e: any) {
    return NextResponse.json({ error: e?.message ?? 'failed' }, { status: 500 })
  }
}
