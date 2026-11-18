import { NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { requireOwner } from '@/lib/auth'

export async function GET(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const { searchParams } = new URL(request.url)
    const tradeId = searchParams.get('tradeId')
    const limit = parseInt(searchParams.get('limit') || '100')
    const offset = parseInt(searchParams.get('offset') || '0')
    const symbol = searchParams.get('symbol')
    const actionType = searchParams.get('actionType')
    const triggeredBy = searchParams.get('triggeredBy')

    // Build where clause dynamically
    const whereClause: Record<string, unknown> = {}
    
    if (tradeId) {
      whereClause.tradeId = tradeId
    }
    
    if (actionType) {
      whereClause.actionType = actionType
    }
    
    if (triggeredBy) {
      whereClause.triggeredBy = triggeredBy
    }
    
    if (symbol) {
      whereClause.trade = {
        symbol: {
          contains: symbol.toUpperCase()
        }
      }
    }

    const actions = await prisma.tradeAction.findMany({
      where: Object.keys(whereClause).length > 0 ? whereClause : undefined,
      include: {
        trade: {
          include: {
            signal: true,
          },
        },
      },
      orderBy: [
        { createdAt: 'desc' },
        { id: 'desc' },
      ],
      skip: offset,
      take: limit,
    })

    return NextResponse.json(actions)
  } catch (error) {
    console.error('Error fetching trade actions:', error)
    return NextResponse.json(
      { error: 'Failed to fetch trade actions' },
      { status: 500 }
    )
  }
}
