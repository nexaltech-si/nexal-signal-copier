import { NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'

const BOT_API_URL = process.env.PYTHON_API_URL || 'http://localhost:8001'

export async function POST(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const body = await request.json()
    const res = await fetch(`${BOT_API_URL}/api/plans/bulk-delete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })

    if (!res.ok) {
      const text = await res.text()
      return NextResponse.json({ error: text }, { status: res.status })
    }

    return NextResponse.json(await res.json())
  } catch (error) {
    console.error('Error bulk-deleting plans:', error)
    return NextResponse.json({ error: 'Failed to bulk-delete plans' }, { status: 500 })
  }
}
