import { NextResponse } from 'next/server';
import { Prisma } from '@prisma/client';
import { prisma } from '@/lib/prisma';
import { requireOwner } from '@/lib/auth'
import { getActiveProvider, type TradingProvider } from '@/lib/provider'

export const dynamic = 'force-dynamic';

const mt5RestUrl = process.env.MT5_REST_API_URL || 'http://mt5:5001';
const mt5RestApiKey = process.env.MT5_REST_API_KEY || '';

interface LiveDrawdown {
  balance: number;
  equity: number;
  drawdownAmount: number;
  drawdownPercent: number;
  isInDrawdown: boolean;
}

async function fetchLiveDrawdown(tradingProvider: TradingProvider): Promise<LiveDrawdown | null> {
  try {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (mt5RestApiKey) headers['X-API-Key'] = mt5RestApiKey;

    const url = tradingProvider === 'mt5rest'
      ? `${mt5RestUrl}/account_info`
      : null;

    if (!url) {
      // For MetaAPI, try the cloud endpoint
      const token = process.env.METAAPI_TOKEN;
      const accountId = process.env.METAAPI_ACCOUNT_ID;
      if (!token || !accountId) return null;

      const regions = ['london', 'new-york', 'singapore'];
      for (const region of regions) {
        try {
          const res = await fetch(
            `https://mt-client-api-v1.${region}.agiliumtrade.ai/users/current/accounts/${accountId}/account-information`,
            { headers: { 'auth-token': token, Accept: 'application/json' }, cache: 'no-store' }
          );
          if (res.ok) {
            const data = await res.json();
            const balance = data.balance ?? 0;
            const equity = data.equity ?? 0;
            const ddAmt = Math.max(0, balance - equity);
            const ddPct = balance > 0 ? (ddAmt / balance) * 100 : 0;
            return { balance, equity, drawdownAmount: ddAmt, drawdownPercent: ddPct, isInDrawdown: ddPct > 0 };
          }
        } catch { continue; }
      }
      return null;
    }

    const res = await fetch(url, { headers, cache: 'no-store' });
    if (!res.ok) return null;
    const data = await res.json();
    const balance = data.balance ?? 0;
    const equity = data.equity ?? 0;
    const ddAmt = Math.max(0, balance - equity);
    const ddPct = balance > 0 ? (ddAmt / balance) * 100 : 0;
    return { balance, equity, drawdownAmount: ddAmt, drawdownPercent: ddPct, isInDrawdown: ddPct > 0 };
  } catch {
    return null;
  }
}

export async function GET(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const { searchParams } = new URL(request.url);
    
    // Query parameters
    const status = searchParams.get('status'); // 'active', 'resolved', or 'all'
    const breachType = searchParams.get('type'); // 'DAILY', 'OVERALL', or 'all'
    const limit = parseInt(searchParams.get('limit') || '50');
    const dateFrom = searchParams.get('dateFrom');
    const dateTo = searchParams.get('dateTo');

    // Build where clause
    const where: Prisma.DrawdownBreachWhereInput = {};
    
    if (status === 'active') {
      where.isActive = true;
    } else if (status === 'resolved') {
      where.isActive = false;
    }
    
    if (breachType && breachType !== 'all') {
      where.breachType = breachType as 'DAILY' | 'OVERALL';
    }
    
    if (dateFrom || dateTo) {
      where.createdAt = {};
      if (dateFrom) {
        where.createdAt.gte = new Date(dateFrom);
      }
      if (dateTo) {
        where.createdAt.lte = new Date(dateTo);
      }
    }

    // Fetch breaches
    const breaches = await prisma.drawdownBreach.findMany({
      where,
      orderBy: { createdAt: 'desc' },
      take: limit,
    });

    // Get statistics
    const stats = await prisma.drawdownBreach.groupBy({
      by: ['breachType'],
      _count: {
        id: true,
      },
      _avg: {
        drawdownPercent: true,
      },
      _sum: {
        losersClosedCount: true,
      },
    });

    // Get active breach count
    const activeCount = await prisma.drawdownBreach.count({
      where: { isActive: true },
    });

    // Calculate total positions closed
    const totalPositionsClosed = breaches.reduce(
      (sum, breach) => sum + (breach.losersClosedCount || 0),
      0
    );

    // Format response
    const formattedBreaches = breaches.map(breach => ({
      id: breach.id,
      breachType: breach.breachType,
      drawdownPercent: breach.drawdownPercent,
      limitPercent: breach.limitPercent,
      accountId: breach.accountId,
      trackerId: breach.trackerId,
      tradingPaused: breach.tradingPaused,
      pausedAt: breach.pausedAt.toISOString(),
      resumedAt: breach.resumedAt?.toISOString() || null,
      losersClosedCount: breach.losersClosedCount,
      closedPositionIds: breach.closedPositionIds 
        ? JSON.parse(breach.closedPositionIds) 
        : [],
      brokerTime: breach.brokerTime,
      brokerDate: breach.brokerDate,
      isActive: breach.isActive,
      resolvedAt: breach.resolvedAt?.toISOString() || null,
      resolvedReason: breach.resolvedReason,
      createdAt: breach.createdAt.toISOString(),
    }));

    // Fetch live drawdown from account info
    const tradingProvider = await getActiveProvider();
    const liveDrawdown = await fetchLiveDrawdown(tradingProvider);

    // Read limits and the protection toggle from the DB settings table — the
    // dashboard and bot must agree on the same source of truth. process.env is
    // only a fallback for a fresh DB that hasn't been seeded yet.
    const limitSettings = await prisma.setting.findMany({
      where: {
        key: {
          in: [
            'DAILY_DRAWDOWN_LIMIT_PERCENT',
            'OVERALL_DRAWDOWN_LIMIT_PERCENT',
            'ENABLE_EQUITY_PROTECTION',
          ],
        },
      },
    });
    const settingsMap = new Map(limitSettings.map(s => [s.key, s.value]));

    const dailyLimit = parseFloat(
      settingsMap.get('DAILY_DRAWDOWN_LIMIT_PERCENT') ??
        process.env.DAILY_DRAWDOWN_LIMIT_PERCENT ??
        '3'
    );
    const overallLimit = parseFloat(
      settingsMap.get('OVERALL_DRAWDOWN_LIMIT_PERCENT') ??
        process.env.OVERALL_DRAWDOWN_LIMIT_PERCENT ??
        '10'
    );
    const equityProtectionEnabled =
      (settingsMap.get('ENABLE_EQUITY_PROTECTION') ?? 'true').toLowerCase() ===
      'true';

    return NextResponse.json({
      success: true,
      data: {
        breaches: formattedBreaches,
        stats: {
          total: breaches.length,
          active: activeCount,
          resolved: breaches.length - activeCount,
          totalPositionsClosed,
          byType: stats.map(s => ({
            type: s.breachType,
            count: s._count.id,
            avgDrawdown: s._avg.drawdownPercent?.toFixed(2) || 0,
            totalPositionsClosed: s._sum.losersClosedCount || 0,
          })),
        },
        provider: {
          name: tradingProvider,
          label: tradingProvider === 'mt5rest' ? 'MT5 REST API' : 'MetaAPI Cloud SDK',
          ismt5rest: tradingProvider === 'mt5rest',
          cloudTrackersAvailable: tradingProvider !== 'mt5rest',
        },
        liveDrawdown,
        limits: {
          daily: dailyLimit,
          overall: overallLimit,
        },
        equityProtectionEnabled,
      },
    });
  } catch (error: unknown) {
    console.error('Error fetching drawdown breaches:', error);
    return NextResponse.json(
      { 
        success: false, 
        error: error instanceof Error ? error.message : 'Failed to fetch drawdown data' 
      },
      { status: 500 }
    );
  }
}
