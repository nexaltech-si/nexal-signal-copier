import { NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { requireOwner } from '@/lib/auth'

interface RuleOutcome {
  id: string
  name: string
  actionType: string
  aiAction: string | null
  followed: boolean
}

// Replies the bot handled, with the channel rule each one matched (stored in actionDetails.channel_rule).
export async function GET(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const params = new URL(request.url).searchParams
    const channelId = params.get('channelId') || undefined
    const rulesOnly = params.get('rulesOnly') === '1'
    const replies = await prisma.signalReply.findMany({
      where: { chatId: channelId, ...(rulesOnly ? { actionDetails: { contains: '"channel_rule"' } } : {}) },
      orderBy: { createdAt: 'desc' },
      take: 100,
    })

    return NextResponse.json({
      activity: replies.map((r) => {
        let rule: RuleOutcome | null = null
        try {
          rule = r.actionDetails ? (JSON.parse(r.actionDetails).channel_rule ?? null) : null
        } catch {
          rule = null
        }
        return {
          id: r.id,
          createdAt: r.createdAt.toISOString(),
          channelId: r.chatId,
          replyText: r.replyText,
          symbol: r.symbol,
          username: r.username,
          actionType: r.actionType,
          actionTaken: r.actionTaken,
          actionSuccess: r.actionSuccess,
          actionResult: r.actionResult,
          processingError: r.processingError,
          aiParsed: r.aiParsed,
          rule,
        }
      }),
    })
  } catch (error) {
    console.error('Error fetching channel rule activity:', error)
    return NextResponse.json({ error: 'Failed to fetch activity' }, { status: 500 })
  }
}
