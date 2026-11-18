import { NextRequest, NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'
import { prisma } from '@/lib/prisma'

export const dynamic = 'force-dynamic'

/** Forget a mirror account and its event log (e.g. a retired terminal). Owner-only.
 *  It reappears on its next report if the EA is still running — revoke its key
 *  on the API Keys page to actually cut it off. */
export async function DELETE(_request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const denied = await requireOwner()
  if (denied) return denied

  const { id } = await params
  try {
    await prisma.eaAccount.delete({ where: { id } })
    return NextResponse.json({ ok: true })
  } catch {
    return NextResponse.json({ error: 'account not found' }, { status: 404 })
  }
}
