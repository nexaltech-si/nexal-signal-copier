import { NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'

export const dynamic = 'force-dynamic'
const API = process.env.PYTHON_API_URL || 'http://localhost:8001'

export async function GET() {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const res = await fetch(`${API}/api/simulator/channels`, { cache: 'no-store' })
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch (err) {
    return NextResponse.json({ ok: false, channels: [], error: String(err) }, { status: 500 })
  }
}
