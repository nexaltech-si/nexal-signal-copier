import { NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'

export const dynamic = 'force-dynamic'
const API = process.env.PYTHON_API_URL || 'http://localhost:8001'

export async function GET(req: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const since = new URL(req.url).searchParams.get('since') || '0'
    const res = await fetch(`${API}/api/simulator/flow/state?since=${encodeURIComponent(since)}`, { cache: 'no-store' })
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 502 })
  }
}
