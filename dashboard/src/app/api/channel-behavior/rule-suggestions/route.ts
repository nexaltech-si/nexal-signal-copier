import { NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { requireOwner } from '@/lib/auth'
import { matchesRule, patternToRegex, suggestedAction, type PatternType } from '@/lib/channelRules'

const MIN_OCCURRENCES = 3

// Messages the bot keeps seeing that carry a trade action (close / move) and no rule covers yet.
export async function GET(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const channelId = new URL(request.url).searchParams.get('channelId') || undefined
    const [learned, rules] = await Promise.all([
      prisma.channelBehaviorAnalytics.findMany({
        where: { channelId, occurrenceCount: { gte: MIN_OCCURRENCES }, action: { not: null } },
        orderBy: { occurrenceCount: 'desc' },
        take: 200,
      }),
      prisma.channelBehaviorRule.findMany({
        where: { channelId },
        select: { channelId: true, replyPattern: true, patternType: true, isCaseSensitive: true },
      }),
    ])

    const suggestions = learned
      .filter((a) => !rules.some((r) => r.channelId === a.channelId &&
        matchesRule(a.messagePattern, { ...r, patternType: r.patternType as PatternType })))
      .slice(0, 50)
      .map((a) => ({
        id: a.id,
        channelId: a.channelId,
        example: a.messagePattern,
        suggestedPattern: patternToRegex(a.messagePattern),
        actionType: suggestedAction(a.action),
        learnedAction: a.action,
        occurrenceCount: a.occurrenceCount,
      }))

    return NextResponse.json({ suggestions })
  } catch (error) {
    console.error('Error fetching rule suggestions:', error)
    return NextResponse.json({ error: 'Failed to fetch suggestions' }, { status: 500 })
  }
}
