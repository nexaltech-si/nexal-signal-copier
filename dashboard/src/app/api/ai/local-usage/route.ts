import { NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'

export const dynamic = 'force-dynamic'

const PYTHON_API_URL = process.env.PYTHON_API_URL || 'http://localhost:8001'

export async function GET(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  const { searchParams } = new URL(request.url)
  const start = searchParams.get('start')
  const end = searchParams.get('end')

  const params = new URLSearchParams()
  if (start) params.set('start', start)
  if (end) params.set('end', end)

  const url = `${PYTHON_API_URL}/api/ai-costs${params.toString() ? '?' + params.toString() : ''}`

  try {
    const res = await fetch(url, { cache: 'no-store' })
    if (!res.ok) {
      const text = await res.text()
      return NextResponse.json({ error: text }, { status: res.status })
    }
    const data = await res.json()
    return NextResponse.json(data)
  } catch (err: any) {
    return NextResponse.json({ error: err.message ?? 'Failed to fetch local usage' }, { status: 502 })
  }
}

export async function POST(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  const { pathname } = new URL(request.url)
  if (!pathname.endsWith('/reset')) {
    return NextResponse.json({ error: 'Not found' }, { status: 404 })
  }
  try {
    const res = await fetch(`${PYTHON_API_URL}/api/ai-costs/reset`, { method: 'POST', cache: 'no-store' })
    const data = await res.json()
    return NextResponse.json(data)
  } catch (err: any) {
    return NextResponse.json({ error: err.message }, { status: 502 })
  }
}
