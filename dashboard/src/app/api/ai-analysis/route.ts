import { NextResponse } from 'next/server';
import { prisma } from '@/lib/prisma';
import { requireOwner } from '@/lib/auth'

export async function GET(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const { searchParams } = new URL(request.url);
    const symbol = searchParams.get('symbol');
    const tradeId = searchParams.get('tradeId');
    const limit = parseInt(searchParams.get('limit') || '20');
    const days = searchParams.get('days');

    const where: Record<string, unknown> = {};
    
    if (symbol) {
      where.symbol = symbol;
    }
    
    if (tradeId) {
      where.tradeId = tradeId;
    }

    // Date filtering - default to today's events if no days parameter is provided
    if (days !== null && days !== 'all') {
      const now = new Date();
      let startDate: Date;
      
      if (days === '0' || days === 'today') {
        // Today's events only - from start of today to now
        startDate = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0, 0);
      } else {
        // Last N days
        const daysNum = parseInt(days);
        startDate = new Date(now.getTime() - (daysNum * 24 * 60 * 60 * 1000));
      }
      
      where.createdAt = {
        gte: startDate
      };
    } else if (days === null) {
      // Default to today's events
      const now = new Date();
      const startDate = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0, 0);
      where.createdAt = {
        gte: startDate
      };
    }
    // If days === 'all', don't add date filter

    const analyses = await prisma.marketAnalysis.findMany({
      where,
      include: {
        trade: {
          select: {
            id: true,
            symbol: true,
            action: true,
            entryPrice: true,
            stopLoss: true,
            takeProfit: true,
            profitLoss: true,
            status: true
          }
        }
      },
      orderBy: {
        createdAt: 'desc'
      },
      take: limit
    });

    return NextResponse.json(analyses);
  } catch (error) {
    console.error('Error fetching AI analysis:', error);
    return NextResponse.json(
      { error: 'Failed to fetch AI analysis' },
      { status: 500 }
    );
  }
}
