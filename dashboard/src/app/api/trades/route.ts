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
    const outcome = searchParams.get('outcome') // win, loss, breakeven
    const provider = searchParams.get('provider') // metaapi | mt5_rest

    // Build where clause dynamically
    const whereClause: Record<string, unknown> = {}
    
    if (status) {
      whereClause.status = status
    }
    
    if (provider) {
      whereClause.provider = provider
    }

    if (symbol) {
      whereClause.symbol = {
        contains: symbol.toUpperCase()
      }
    }
    
    if (channel) {
      whereClause.signal = {
        OR: [
          { channelId: { contains: channel } },
          { channelName: { contains: channel } }
        ]
      }
    }
    
    // Filter by outcome (win/loss/breakeven)
    if (outcome) {
      if (outcome === 'win') {
        whereClause.profitLoss = { gt: 0 }
      } else if (outcome === 'loss') {
        whereClause.profitLoss = { lt: 0 }
      } else if (outcome === 'breakeven') {
        whereClause.profitLoss = 0
      }
    }

    const trades = await prisma.trade.findMany({
      where: Object.keys(whereClause).length > 0 ? whereClause : undefined,
      include: {
        signal: true,
        parentTrade: true,
        childTrades: true,
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
          take: 1, // Get only the latest AI analysis
        },
      },
      orderBy: [
        { createdAt: 'desc' },
        { id: 'desc' },
      ],
      skip: offset,
      take: limit,
    })

    return NextResponse.json(trades, {
      headers: {
        'Cache-Control': 'private, max-age=30, stale-while-revalidate=60',
      },
    })
  } catch (error) {
    console.error('Error fetching trades:', error)
    return NextResponse.json(
      { error: 'Failed to fetch trades' },
      { status: 500 }
    )
  }
}
