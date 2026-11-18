import { NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { checkAuthorization } from '@/lib/auth'

export async function POST() {
  const { authorized, response } = await checkAuthorization()
  if (!authorized) return response

  try {
    const stats = {
      signalsFixed: 0,
      repliesDeleted: 0,
      repliesLinked: 0,
    }

    // Step 1: Fix signal channel IDs using multiple strategies
    console.log('Step 1: Fixing signal channel IDs...')
    
    const allSignals = await prisma.signal.findMany({
      select: {
        id: true,
        channelId: true,
        messageId: true,
      }
    })

    for (const signal of allSignals) {
      let correctId: string | null = null

      // Strategy 1: Use message mapping
      const mapping = await prisma.messageMapping.findFirst({
        where: { signalId: signal.id }
      })

      if (mapping && mapping.chatId !== signal.channelId) {
        correctId = mapping.chatId
      }

      // Strategy 2: Check if @username or plain numeric - fix via nearby signals or pattern
      if (!correctId && (signal.channelId.startsWith('@') || 
          (signal.channelId.match(/^\d+$/) && !signal.channelId.startsWith('-')))) {
        
        // Try to find nearby signals with correct format
        const nearbySignals = await prisma.signal.findMany({
          where: {
            messageId: {
              gte: signal.messageId - 100,
              lte: signal.messageId + 100
            },
            channelId: {
              startsWith: '-'
            }
          },
          select: { channelId: true },
          take: 10
        })

        if (nearbySignals.length > 0) {
          // Use most common channel ID
          const channelIds = nearbySignals.map(s => s.channelId)
          correctId = channelIds.sort((a, b) =>
            channelIds.filter(id => id === a).length - channelIds.filter(id => id === b).length
          ).pop() || null
        }
        
        // Plain numeric: add -100 prefix
        if (!correctId && signal.channelId.match(/^\d+$/)) {
          correctId = `-100${signal.channelId}`
        }
      }

      // Apply fix if found
      if (correctId) {
        await prisma.signal.update({
          where: { id: signal.id },
          data: { channelId: correctId }
        })
        stats.signalsFixed++
      }
    }

    console.log(`Fixed ${stats.signalsFixed} signal channel IDs`)

    // Step 2: Link replies to signals where possible
    console.log('Step 2: Linking replies to signals...')
    
    const unlinkedReplies = await prisma.signalReply.findMany({
      where: { signalId: null }
    })

    console.log(`Found ${unlinkedReplies.length} unlinked replies`)

    for (const reply of unlinkedReplies) {
      // Try to find matching signal
      const matchingSignal = await prisma.signal.findFirst({
        where: {
          channelId: reply.chatId,
          messageId: reply.replyToMessageId
        }
      })

      if (matchingSignal) {
        // Link reply to signal
        await prisma.signalReply.update({
          where: { id: reply.id },
          data: {
            signalId: matchingSignal.id,
            symbol: matchingSignal.symbol
          }
        })
        stats.repliesLinked++
      }
    }

    console.log(`Linked ${stats.repliesLinked} replies to signals`)

    // Step 3: Delete remaining unlinked replies (orphaned replies with no matching signals)
    console.log('Step 3: Deleting orphaned unlinked replies...')
    
    const result = await prisma.signalReply.deleteMany({
      where: { signalId: null }
    })
    
    stats.repliesDeleted = result.count
    console.log(`Deleted ${stats.repliesDeleted} orphaned replies`)

    return NextResponse.json({
      success: true,
      ...stats,
      message: `Fixed ${stats.signalsFixed} signals, linked ${stats.repliesLinked} replies, deleted ${stats.repliesDeleted} orphaned replies`
    })
  } catch (error) {
    console.error('Error fixing database:', error)
    return NextResponse.json(
      { 
        error: 'Failed to fix database',
        details: error instanceof Error ? error.message : 'Unknown error'
      },
      { status: 500 }
    )
  }
}
