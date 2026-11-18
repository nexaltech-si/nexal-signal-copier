import { NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'

const BOT_API_URL = process.env.PYTHON_API_URL || 'http://localhost:8001'

export async function DELETE(
  _request: Request,
  { params }: { params: { id: string } }
) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const res = await fetch(`${BOT_API_URL}/api/plans/${params.id}`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
    })

    if (!res.ok) {
      const text = await res.text()
      return NextResponse.json({ error: text }, { status: res.status })
    }

    return NextResponse.json(await res.json())
  } catch (error) {
    console.error('Error deleting plan:', error)
    return NextResponse.json({ error: 'Failed to delete plan' }, { status: 500 })
  }
}
