import { NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { requireOwner } from '@/lib/auth'

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const { id } = await params

    // Fetch trade to get position ID
    const trade = await prisma.trade.findUnique({
      where: { id },
      select: {
        positionId: true,
        symbol: true,
      },
    })

    if (!trade) {
      return NextResponse.json(
        { error: 'Trade not found' },
        { status: 404 }
      )
    }

    if (!trade.positionId) {
      return NextResponse.json(
        { error: 'Trade has no position ID' },
        { status: 400 }
      )
    }

    // Call MT5 REST API to get trade lifecycle
    const mt5Url = process.env.MT5_REST_API_URL || 'http://mt5:5001'
    const response = await fetch(
      `${mt5Url}/trade_lifecycle?ticket=${trade.positionId}&days_back=30`
    )

    if (!response.ok) {
      return NextResponse.json(
        { error: 'Failed to fetch lifecycle from MT5 API' },
        { status: response.status }
      )
    }

    const lifecycleData = await response.json()

    return NextResponse.json(lifecycleData)
  } catch (error) {
    console.error('Error fetching trade lifecycle:', error)
    return NextResponse.json(
      { error: 'Failed to fetch trade lifecycle' },
      { status: 500 }
    )
  }
}
