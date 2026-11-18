import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { auth } from '@clerk/nextjs/server'
import { requireOwner } from '@/lib/auth'

// Notification inbox. Rows are written by the bot's event pusher
// (src/services/event_pusher.py); new ones also arrive live via ./stream.

function serialize(n: {
  id: string; createdAt: Date; category: string | null; type: string; severity: string
  title: string; body: string; url: string | null; data: string | null; readAt: Date | null
}) {
  let data = null
  if (n.data) {
    try { data = JSON.parse(n.data) } catch { data = null }
  }
  return { ...n, createdAt: n.createdAt.toISOString(), readAt: n.readAt?.toISOString() ?? null, data }
}

export async function GET(request: NextRequest) {
  const denied = await requireOwner()
  if (denied) return denied

  const { userId } = await auth()
  if (!userId) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }
  try {
    const { searchParams } = new URL(request.url)
    const limit = Math.min(Number(searchParams.get('limit')) || 50, 200)
    const before = searchParams.get('before')

    const [items, unreadCount] = await Promise.all([
      prisma.appNotification.findMany({
        where: before ? { createdAt: { lt: new Date(before) } } : undefined,
        orderBy: { createdAt: 'desc' },
        take: limit,
      }),
      prisma.appNotification.count({ where: { readAt: null } }),
    ])

    return NextResponse.json({ items: items.map(serialize), unreadCount })
  } catch (error) {
    console.error('Failed to fetch notifications:', error)
    return NextResponse.json({ error: 'Internal Server Error' }, { status: 500 })
  }
}

// Mark read: { ids: [...] } for specific notifications, {} for all.
export async function PATCH(request: NextRequest) {
  const denied = await requireOwner()
  if (denied) return denied

  const { userId } = await auth()
  if (!userId) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }
  try {
    const { ids } = await request.json().catch(() => ({}))
    await prisma.appNotification.updateMany({
      where: { readAt: null, ...(Array.isArray(ids) ? { id: { in: ids } } : {}) },
      data: { readAt: new Date() },
    })
    const unreadCount = await prisma.appNotification.count({ where: { readAt: null } })
    return NextResponse.json({ unreadCount })
  } catch (error) {
    console.error('Failed to mark notifications read:', error)
    return NextResponse.json({ error: 'Internal Server Error' }, { status: 500 })
  }
}

// Clear: { ids: [...] } for specific notifications, {} for all.
export async function DELETE(request: NextRequest) {
  const denied = await requireOwner()
  if (denied) return denied

  const { userId } = await auth()
  if (!userId) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }
  try {
    const { ids } = await request.json().catch(() => ({}))
    await prisma.appNotification.deleteMany({
      where: Array.isArray(ids) ? { id: { in: ids } } : {},
    })
    const unreadCount = await prisma.appNotification.count({ where: { readAt: null } })
    return NextResponse.json({ unreadCount })
  } catch (error) {
    console.error('Failed to clear notifications:', error)
    return NextResponse.json({ error: 'Internal Server Error' }, { status: 500 })
  }
}
