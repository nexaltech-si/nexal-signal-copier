import { NextRequest, NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'

export const dynamic = 'force-dynamic'
const API = process.env.PYTHON_API_URL || 'http://localhost:8001'

export async function GET(request: NextRequest) {
  const denied = await requireOwner()
  if (denied) return denied

  const { searchParams } = new URL(request.url)
  const symbol = searchParams.get('symbol') || 'XAUUSD'
  const timeframe = searchParams.get('timeframe') || '1h'
  const limit = searchParams.get('limit') || '200'

  try {
    const res = await fetch(
      `${API}/api/gsquant/indicators/${encodeURIComponent(symbol)}?timeframe=${encodeURIComponent(timeframe)}&limit=${encodeURIComponent(limit)}`,
      { cache: 'no-store' }
    )
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch (err) {
    return NextResponse.json({ ok: false, error: String(err) }, { status: 500 })
  }
}
