import { NextRequest } from 'next/server'
import Redis from 'ioredis'
import { requireOwner } from '@/lib/auth'

export const dynamic = 'force-dynamic'

// Redis client for subscriptions
let redis: Redis | null = null

function getRedisClient(): Redis {
  if (!redis) {
    const redisUrl = process.env.REDIS_URL || 'redis://redis:6379'
    redis = new Redis(redisUrl, {
      lazyConnect: true,
      retryStrategy: (times) => Math.min(times * 50, 2000),
    })
  }
  return redis
}

export async function GET(request: NextRequest) {
  const denied = await requireOwner()
  if (denied) return denied

  const { searchParams } = new URL(request.url)
  const symbol = searchParams.get('symbol') || 'XAUUSD'
  
  const encoder = new TextEncoder()
  const redis = getRedisClient()
  
  // Create a readable stream for SSE
  const stream = new ReadableStream({
    async start(controller) {
      let subscriber: Redis | null = null
      let keepaliveInterval: NodeJS.Timeout | null = null
      
      try {
        // Connect to Redis
        await redis.connect()
        
        // Subscribe to symbol channel
        subscriber = redis.duplicate()
        await subscriber.connect()
        await subscriber.subscribe(`ticks:${symbol}`)
        
        console.log(`[Redis Stream] Subscribed to ticks:${symbol}`)
        
        // Send initial connection message
        controller.enqueue(encoder.encode(`data: ${JSON.stringify({ type: 'connected', symbol })}\n\n`))
        
        // Listen for messages
        subscriber.on('message', (channel, message) => {
          if (channel === `ticks:${symbol}`) {
            try {
              const data = JSON.parse(message)
              controller.enqueue(encoder.encode(`data: ${JSON.stringify({ type: 'tick', data })}\n\n`))
            } catch (error) {
              console.error('[Redis Stream] Failed to parse message:', error)
            }
          }
        })
        
        subscriber.on('error', (error) => {
          console.error('[Redis Stream] Redis error:', error)
          controller.enqueue(encoder.encode(`data: ${JSON.stringify({ type: 'error', message: error.message })}\n\n`))
        })
        
        // Send keepalive every 30 seconds
        keepaliveInterval = setInterval(() => {
          controller.enqueue(encoder.encode(`: keepalive\n\n`))
        }, 30000)
        
        // Handle client disconnect
        request.signal.addEventListener('abort', () => {
          cleanup()
        })
        
      } catch (error) {
        console.error('[Redis Stream] Error:', error)
        controller.enqueue(encoder.encode(`data: ${JSON.stringify({ type: 'error', message: 'Failed to connect to Redis' })}\n\n`))
        controller.close()
      }
      
      function cleanup() {
        if (subscriber) {
          subscriber.unsubscribe(`ticks:${symbol}`)
          subscriber.disconnect()
          subscriber = null
        }
        if (keepaliveInterval) {
          clearInterval(keepaliveInterval)
          keepaliveInterval = null
        }
        controller.close()
      }
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
