import { NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { getJournalEntry, updateJournalEntry } from '@/lib/trade-journal-store'
import { requireOwner } from '@/lib/auth'

export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const { id } = await params
    const body = await request.json()
    const { notes, tags } = body

    // Validate tags if provided
    const validTags = ['WIN', 'LOSS', 'BREAKEVEN', 'SCALP', 'NEWS', 'FOMC', 'TECHNICAL', 'EMOTIONAL']
    if (tags !== undefined) {
      if (!Array.isArray(tags)) {
        return NextResponse.json(
          { error: 'tags must be an array of strings' },
          { status: 400 }
        )
      }
      for (const tag of tags) {
        if (!validTags.includes(tag)) {
          return NextResponse.json(
            { error: `Invalid tag: ${tag}. Valid tags: ${validTags.join(', ')}` },
            { status: 400 }
          )
        }
      }
    }

    // Update the journal store
    const updated = await updateJournalEntry(id, { notes, tags })

    return NextResponse.json({
      id,
      notes: updated.notes,
      tags: updated.tags,
      savedAt: new Date().toISOString(),
    })
  } catch (error) {
    console.error('Error updating trade journal:', error)
    return NextResponse.json(
      { error: 'Failed to update trade journal' },
      { status: 500 }
    )
  }
}

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const { id } = await params

    const trade = await prisma.trade.findUnique({
      where: { id },
      include: {
        signal: {
          include: {
            trades: {
              include: {
                tradeActions: {
                  orderBy: { createdAt: 'asc' },
                },
              },
            },
          },
        },
        parentTrade: true,
        childTrades: {
          include: {
            tradeActions: {
              orderBy: { createdAt: 'asc' },
            },
          },
        },
        tradeActions: {
          orderBy: [
            { createdAt: 'desc' },
            { id: 'desc' },
          ],
        },
        marketAnalyses: {
          orderBy: {
            createdAt: 'desc',
          },
        },
      },
    })

    if (!trade) {
      return NextResponse.json(
        { error: 'Trade not found' },
        { status: 404 }
      )
    }

    // Fetch signal replies if trade has a signal
    let replies: unknown[] = []
    if (trade.signal) {
      replies = await prisma.signalReply.findMany({
        where: {
          OR: [
            { signalId: trade.signal.id },
            {
              replyToMessageId: trade.signal.messageId,
              chatId: trade.signal.channelId,
            },
          ],
        },
        orderBy: { createdAt: 'asc' },
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
    }

    return NextResponse.json({
      ...trade,
      signalReplies: replies,
    })
  } catch (error) {
    console.error('Error fetching trade:', error)
    return NextResponse.json(
      { error: 'Failed to fetch trade' },
      { status: 500 }
    )
  }
}
