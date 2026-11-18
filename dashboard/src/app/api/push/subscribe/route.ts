import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { auth } from '@clerk/nextjs/server'
import { requireOwner } from '@/lib/auth'

// Registers this browser/device for Web Push. The bot's event pusher sends to
// every row in push_subscriptions and prunes the ones that expire.

export async function POST(request: NextRequest) {
  const denied = await requireOwner()
  if (denied) return denied

  const { userId } = await auth()
  if (!userId) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }
  try {
    const { subscription, oldEndpoint } = await request.json()
    const endpoint: string | undefined = subscription?.endpoint
    const p256dh: string | undefined = subscription?.keys?.p256dh
    const authKey: string | undefined = subscription?.keys?.auth
    if (!endpoint || !p256dh || !authKey || !endpoint.startsWith('https://')) {
      return NextResponse.json({ error: 'Invalid subscription' }, { status: 400 })
    }

    if (oldEndpoint && oldEndpoint !== endpoint) {
      await prisma.pushSubscription.deleteMany({ where: { endpoint: oldEndpoint } })
    }

    const userAgent = request.headers.get('user-agent')?.slice(0, 300) ?? null
    await prisma.pushSubscription.upsert({
      where: { endpoint },
      create: { endpoint, p256dh, auth: authKey, userId, userAgent },
      update: { p256dh, auth: authKey, userId, userAgent, failureCount: 0 },
    })
    return NextResponse.json({ ok: true })
  } catch (error) {
    console.error('Failed to save push subscription:', error)
    return NextResponse.json({ error: 'Internal Server Error' }, { status: 500 })
  }
}

export async function DELETE(request: NextRequest) {
  const denied = await requireOwner()
  if (denied) return denied

  const { userId } = await auth()
  if (!userId) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }
  try {
    const { endpoint } = await request.json()
    if (endpoint) {
      await prisma.pushSubscription.deleteMany({ where: { endpoint } })
    }
    return NextResponse.json({ ok: true })
  } catch (error) {
    console.error('Failed to remove push subscription:', error)
    return NextResponse.json({ error: 'Internal Server Error' }, { status: 500 })
  }
}
