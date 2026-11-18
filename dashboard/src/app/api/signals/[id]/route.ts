import { NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { checkAuthorization, requireOwner } from '@/lib/auth'

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const { id } = await params

    const signal = await prisma.signal.findUnique({
      where: { id },
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
              take: 1,
            },
          },
        },
      },
    })

    if (!signal) {
      return NextResponse.json(
        { error: 'Signal not found' },
        { status: 404 }
      )
    }

    // Fetch replies
    const replies = await prisma.signalReply.findMany({
      where: {
        OR: [
          { signalId: signal.id },
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

    // Strip imageData from response (large base64) and add hasImage flag instead
    const { imageData, ...signalWithoutImage } = signal
    return NextResponse.json({
      ...signalWithoutImage,
      hasImage: !!imageData,
      replies,
    })
  } catch (error) {
    console.error('Error fetching signal:', error)
    return NextResponse.json(
      { error: 'Failed to fetch signal' },
      { status: 500 }
    )
  }
}

export async function DELETE(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { authorized, response } = await checkAuthorization()
  if (!authorized) return response

  try {
    const { id } = await params

    // Check if signal exists
    const signal = await prisma.signal.findUnique({
      where: { id },
      include: {
        trades: true,
      },
    })

    if (!signal) {
      return NextResponse.json(
        { error: 'Signal not found' },
        { status: 404 }
      )
    }

    // Delete all related data in correct order to handle foreign key constraints
    
    // 1. Delete trade actions for all trades
    const tradeIds = signal.trades.map(t => t.id)
    if (tradeIds.length > 0) {
      await prisma.tradeAction.deleteMany({
        where: {
          tradeId: {
            in: tradeIds,
          },
        },
      })
    }

    // 2. Delete market analyses for all trades
    if (tradeIds.length > 0) {
      await prisma.marketAnalysis.deleteMany({
        where: {
          tradeId: {
            in: tradeIds,
          },
        },
      })
    }

    // 3. Delete child trades
    await prisma.trade.deleteMany({
      where: {
        parentTradeId: {
          in: tradeIds,
        },
      },
    })

    // 4. Delete trades
    await prisma.trade.deleteMany({
      where: {
        signalId: id,
      },
    })

    // 5. Delete signal replies
    await prisma.signalReply.deleteMany({
      where: {
        OR: [
          { signalId: id },
          {
            replyToMessageId: signal.messageId,
            chatId: signal.channelId,
          },
        ],
      },
    })

    // 6. Delete message mappings
    await prisma.messageMapping.deleteMany({
      where: {
        signalId: id,
      },
    })

    // 7. Delete the signal
    await prisma.signal.delete({
      where: { id },
    })

    return NextResponse.json({
      success: true,
      message: 'Signal and all related data deleted successfully',
    })
  } catch (error) {
    console.error('Error deleting signal:', error)
    return NextResponse.json(
      { error: 'Failed to delete signal' },
      { status: 500 }
    )
  }
}
