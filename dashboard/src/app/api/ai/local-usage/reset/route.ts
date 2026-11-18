import { NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'

export const dynamic = 'force-dynamic'

const PYTHON_API_URL = process.env.PYTHON_API_URL || 'http://localhost:8001'

export async function POST() {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const res = await fetch(`${PYTHON_API_URL}/api/ai-costs/reset`, { method: 'POST', cache: 'no-store' })
    const data = await res.json()
    return NextResponse.json(data)
  } catch (err: any) {
    return NextResponse.json({ error: err.message }, { status: 502 })
  }
}
