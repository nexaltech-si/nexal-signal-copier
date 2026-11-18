import { NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { requireOwner } from '@/lib/auth'
import { ruleDataFromInput, serializeRule, type RuleInput } from '@/lib/channelRules'

export async function PUT(request: Request, { params }: { params: Promise<{ ruleId: string }> }) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const { ruleId } = await params
    const current = await prisma.channelBehaviorRule.findUnique({ where: { id: ruleId } })
    if (!current) return NextResponse.json({ error: 'Rule not found' }, { status: 404 })
    const parsed = ruleDataFromInput((await request.json()) as RuleInput, true, current)
    if ('error' in parsed) return NextResponse.json({ error: parsed.error }, { status: 400 })
    const rule = await prisma.channelBehaviorRule.update({ where: { id: ruleId }, data: parsed.data })
    return NextResponse.json({ success: true, rule: serializeRule(rule) })
  } catch (error) {
    console.error('Error updating channel behavior rule:', error)
    return NextResponse.json({ error: 'Failed to update rule' }, { status: 500 })
  }
}

export async function DELETE(_request: Request, { params }: { params: Promise<{ ruleId: string }> }) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const { ruleId } = await params
    await prisma.channelBehaviorRule.delete({ where: { id: ruleId } })
    return NextResponse.json({ success: true })
  } catch (error) {
    console.error('Error deleting channel behavior rule:', error)
    return NextResponse.json({ error: 'Failed to delete rule' }, { status: 500 })
  }
}
