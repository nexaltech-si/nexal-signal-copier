import { NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'

export const dynamic = 'force-dynamic'

const PYTHON_API_URL = process.env.PYTHON_API_URL || 'http://localhost:8001'

export async function POST() {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const response = await fetch(`${PYTHON_API_URL}/api/drawdown/reset`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    })

    if (!response.ok) {
      const error = await response.json()
      return NextResponse.json(error, { status: response.status })
    }

    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error('Error resetting drawdown breach:', error)
    return NextResponse.json(
      { error: 'Failed to reset drawdown breach' },
      { status: 500 }
    )
  }
}
