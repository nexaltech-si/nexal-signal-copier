import { NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { requireOwner } from '@/lib/auth'

export async function PATCH(
  request: Request,
  { params }: { params: { id: string } }
) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const { autoExecute } = await request.json()

    const plan = await prisma.tradePlan.update({
      where: { id: params.id },
      data: { autoExecute: Boolean(autoExecute) },
    })

    return NextResponse.json({ id: plan.id, autoExecute: plan.autoExecute })
  } catch (error) {
    console.error('Error updating plan auto-execute:', error)
    return NextResponse.json({ error: 'Failed to update plan' }, { status: 500 })
  }
}
