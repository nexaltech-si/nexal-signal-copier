import { NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { requireOwner } from '@/lib/auth'

export async function GET(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const { searchParams } = new URL(request.url)
    const status = searchParams.get('status')

    const count = await prisma.signal.count({
      where: status ? { status } : undefined,
    })

    return NextResponse.json({ count })
  } catch (error) {
    console.error('Error counting signals:', error)
    return NextResponse.json({ error: 'Failed to count signals' }, { status: 500 })
  }
}
