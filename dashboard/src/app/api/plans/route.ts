import { NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'

const BOT_API_URL = process.env.PYTHON_API_URL || 'http://localhost:8001'

export async function GET(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const { searchParams } = new URL(request.url)
    const status = searchParams.get('status') || ''
    const limit = searchParams.get('limit') || '50'

    const params = new URLSearchParams()
    if (status) params.set('status', status)
    params.set('limit', limit)

    const res = await fetch(`${BOT_API_URL}/api/plans?${params}`, {
      headers: { 'Content-Type': 'application/json' },
      cache: 'no-store',
    })

    if (!res.ok) {
      const text = await res.text()
      return NextResponse.json({ error: text }, { status: res.status })
    }

    const data = await res.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error('Error fetching plans:', error)
    return NextResponse.json({ error: 'Failed to fetch plans' }, { status: 500 })
  }
}
