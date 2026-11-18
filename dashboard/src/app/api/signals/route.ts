import { NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { requireOwner } from '@/lib/auth'

export async function GET(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const { searchParams } = new URL(request.url)
    const limit = parseInt(searchParams.get('limit') || '50')
    const offset = parseInt(searchParams.get('offset') || '0')
    const status = searchParams.get('status')
    const symbol = searchParams.get('symbol')
    const channel = searchParams.get('channel')
    const verification = searchParams.get('verification')
    const dateFrom = searchParams.get('dateFrom')
    const dateTo = searchParams.get('dateTo')

    // Build where clause dynamically
    const whereClause: Record<string, unknown> = {}
    
    if (status) {
      whereClause.status = status
    }
    
    if (symbol) {
      whereClause.symbol = {
        contains: symbol.toUpperCase()
      }
    }
    
    if (channel) {
      whereClause.OR = [
        { channelId: { contains: channel } },
        { channelName: { contains: channel } }
      ]
    }
    
    if (verification) {
      if (verification === 'unverified') {
        whereClause.aiVerified = false
      } else if (verification === 'verified') {
        whereClause.aiVerified = true
      } else {
        // Specific verification type (TRADE_SIGNAL, INFO_MESSAGE, etc.)
        whereClause.aiVerificationType = verification
      }
    }
    
    // Date range filter
    if (dateFrom || dateTo) {
      const createdAt: { gte?: Date; lte?: Date } = {}
      if (dateFrom) {
        createdAt.gte = new Date(dateFrom)
      }
      if (dateTo) {
        // Add one day to include the entire end date
        const endDate = new Date(dateTo)
        endDate.setHours(23, 59, 59, 999)
        createdAt.lte = endDate
      }
      whereClause.createdAt = createdAt
    }

    const where = Object.keys(whereClause).length > 0 ? whereClause : undefined

    const [signals, total] = await Promise.all([
      prisma.signal.findMany({
        where,
        include: {
          trades: {
            include: {
              childTrades: true,
              parentTrade: true,
              tradeActions: {
                orderBy: {
                  createdAt: 'asc',
                },
              },
              marketAnalyses: {
                orderBy: {
                  createdAt: 'desc',
                },
              },
            },
          },
        },
        orderBy: [
          { createdAt: 'desc' },
          { id: 'desc' },
        ],
        skip: offset,
        take: limit,
      }),
      prisma.signal.count({ where }),
    ])

    // Fetch replies for each signal
    const signalsWithReplies = await Promise.all(
      signals.map(async (signal) => {
        // Fetch replies by BOTH signalId AND by message matching
        // This ensures we get all replies even if signalId wasn't set
        const replies = await prisma.signalReply.findMany({
          where: {
            OR: [
              // Replies directly linked to signal
              { signalId: signal.id },
              // Replies to the original message (by message ID and chat)
              {
                replyToMessageId: signal.messageId,
                chatId: signal.channelId,
              },
            ],
          },
          orderBy: {
            createdAt: 'asc',
          },
          select: {
            id: true,
            createdAt: true,
            replyMessageId: true,
            replyToMessageId: true,
            replyText: true,
            userId: true,
            username: true,
            actionTaken: true,
            actionType: true,
            actionSuccess: true,
            actionResult: true,
            positionsClosed: true,
            ordersCancelled: true,
            processed: true,
            processingError: true,
            aiParsed: true,
          },
        })
        
        // Exclude raw imageData from list response (large base64 string).
        // Use hasImage flag instead; image is served via /api/signals/[id]/image.
        const { imageData, ...signalWithoutImage } = signal as typeof signal & { imageData?: string | null }
        return {
          ...signalWithoutImage,
          hasImage: !!imageData,
          replies,
        }
      })
    )

    return NextResponse.json({ signals: signalsWithReplies, total })
  } catch (error) {
    console.error('Error fetching signals:', error)
    return NextResponse.json(
      { error: 'Failed to fetch signals' },
      { status: 500 }
    )
  }
}
