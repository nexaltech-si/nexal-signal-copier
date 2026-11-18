import { NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { requireOwner } from '@/lib/auth'
import { ruleDataFromInput, serializeRule, type RuleInput } from '@/lib/channelRules'

export async function GET() {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const rules = await prisma.channelBehaviorRule.findMany({
      orderBy: [{ priority: 'desc' }, { createdAt: 'asc' }],
    })
    const channelIds = [...new Set(rules.map((r) => r.channelId))]
    const channels = channelIds.length
      ? await prisma.monitoredChannel.findMany({
          where: { channelId: { in: channelIds } },
          select: { channelId: true, channelTitle: true },
        })
      : []
    const titleMap = Object.fromEntries(channels.map((c) => [c.channelId, c.channelTitle]))
    return NextResponse.json({ rules: rules.map((r) => serializeRule(r, titleMap[r.channelId])) })
  } catch (error) {
    console.error('Error fetching channel behavior rules:', error)
    return NextResponse.json({ error: 'Failed to fetch rules' }, { status: 500 })
  }
}

export async function POST(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const parsed = ruleDataFromInput((await request.json()) as RuleInput, false)
    if ('error' in parsed) return NextResponse.json({ error: parsed.error }, { status: 400 })
    const rule = await prisma.channelBehaviorRule.create({ data: parsed.data as never })
    return NextResponse.json({ success: true, rule: serializeRule(rule) })
  } catch (error) {
    console.error('Error creating channel behavior rule:', error)
    return NextResponse.json({ error: 'Failed to create rule' }, { status: 500 })
  }
}
