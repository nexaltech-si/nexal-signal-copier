import { NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'

export const dynamic = 'force-dynamic'
const API = process.env.PYTHON_API_URL || 'http://localhost:8001'

export async function GET(_req: Request, { params }: { params: { filename: string } }) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const res = await fetch(`${API}/api/simulator/results/${params.filename}`, { cache: 'no-store' })
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}

export async function DELETE(_req: Request, { params }: { params: { filename: string } }) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const res = await fetch(`${API}/api/simulator/results/${params.filename}`, { method: 'DELETE' })
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}
