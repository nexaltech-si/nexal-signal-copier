import { NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'
import { safeImageType, imageResponseHeaders } from '@/lib/safeImage'

export const dynamic = 'force-dynamic'

const PYTHON_API_URL = process.env.PYTHON_API_URL || 'http://localhost:8001'

export async function GET(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const { searchParams } = new URL(request.url)
    const channelId = searchParams.get('channel_id')
    const messageId = searchParams.get('message_id')

    if (!channelId || !messageId) {
      return new Response(null, { status: 400 })
    }

    const response = await fetch(
      `${PYTHON_API_URL}/api/telegram-browser/media/${channelId}/${messageId}`,
      { cache: 'no-store' }
    )

    if (!response.ok) {
      return new Response(null, { status: 404 })
    }

    const contentType = safeImageType(response.headers.get('content-type'))
    if (!contentType) {
      return new Response(null, { status: 415 })
    }
    const buffer = await response.arrayBuffer()

    return new Response(buffer, { headers: imageResponseHeaders(contentType, 3600) })
  } catch {
    return new Response(null, { status: 500 })
  }
}
