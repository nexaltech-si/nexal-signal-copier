import { NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'

export const dynamic = 'force-dynamic'
const API = process.env.PYTHON_API_URL || 'http://localhost:8001'

export async function POST() {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const res = await fetch(`${API}/api/simulator/flow/stop`, { method: 'POST' })
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}
