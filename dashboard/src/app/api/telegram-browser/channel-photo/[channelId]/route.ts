import { NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'
import { imageResponseHeaders } from '@/lib/safeImage'

export const dynamic = 'force-dynamic'

const PYTHON_API_URL = process.env.PYTHON_API_URL || 'http://localhost:8001'

export async function GET(
  _request: Request,
  { params }: { params: { channelId: string } }
) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const response = await fetch(
      `${PYTHON_API_URL}/api/telegram-browser/channel-photo/${params.channelId}`,
      { cache: 'no-store' }
    )
    if (!response.ok) {
      return new NextResponse(null, { status: 404 })
    }
    const buffer = await response.arrayBuffer()
    return new NextResponse(buffer, { headers: imageResponseHeaders('image/jpeg', 86400) })
  } catch {
    return new NextResponse(null, { status: 500 })
  }
}
