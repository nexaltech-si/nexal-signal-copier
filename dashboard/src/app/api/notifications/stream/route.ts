import { NextRequest } from 'next/server'
import Redis from 'ioredis'
import { auth } from '@clerk/nextjs/server'
import { requireOwner } from '@/lib/auth'

export const dynamic = 'force-dynamic'

// Live notification stream (SSE). The bot's event pusher publishes each new
// notification on this Redis channel the moment it is created.
const CHANNEL = 'notifications:events'

export async function GET(request: NextRequest) {
  const denied = await requireOwner()
  if (denied) return denied

  const { userId } = await auth()
  if (!userId) {
    return new Response('Unauthorized', { status: 401 })
  }

  const encoder = new TextEncoder()
  const subscriber = new Redis(process.env.REDIS_URL || 'redis://redis:6379', {
    lazyConnect: true,
    retryStrategy: (times) => Math.min(times * 200, 5000),
  })
  let keepalive: NodeJS.Timeout | null = null
  let closed = false

  const stream = new ReadableStream({
    async start(controller) {
      const send = (chunk: string) => {
        if (!closed) controller.enqueue(encoder.encode(chunk))
      }
      const cleanup = () => {
        if (closed) return
        closed = true
        if (keepalive) clearInterval(keepalive)
        subscriber.disconnect()
        try { controller.close() } catch { /* already closed */ }
      }
      request.signal.addEventListener('abort', cleanup)

      // Tell EventSource to reconnect after 3s if the stream drops
      send('retry: 3000\n\n')

      try {
        await subscriber.connect()
        await subscriber.subscribe(CHANNEL)
      } catch (error) {
        console.error('[Notifications Stream] Redis unavailable:', error)
        send(`event: error\ndata: ${JSON.stringify({ message: 'Redis unavailable' })}\n\n`)
        cleanup()
        return
      }

      subscriber.on('message', (_channel, message) => {
        send(`event: notification\ndata: ${message}\n\n`)
      })
      subscriber.on('error', (error) => {
        console.error('[Notifications Stream] Redis error:', error)
      })

      send(`event: ready\ndata: {}\n\n`)
      keepalive = setInterval(() => send(': keepalive\n\n'), 25000)
    },
    cancel() {
      closed = true
      if (keepalive) clearInterval(keepalive)
      subscriber.disconnect()
    },
  })

  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      'Connection': 'keep-alive',
      'X-Accel-Buffering': 'no',
    },
  })
}
