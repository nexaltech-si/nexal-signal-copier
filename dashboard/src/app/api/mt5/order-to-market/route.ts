import { NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'

export const dynamic = 'force-dynamic'

const PYTHON_API_URL = process.env.PYTHON_API_URL || 'http://localhost:8001'

// Pending order → market order at the same money risk. Runs in the bot, not the
// bridge: it relinks the trade record and holds the order-sync lock.

function ticketOf(value: unknown): string | null {
  const s = String(value ?? '').trim()
  return /^\d+$/.test(s) ? s : null
}

async function forward(ticket: string, method: 'GET' | 'POST') {
  const response = await fetch(`${PYTHON_API_URL}/api/orders/${ticket}/to-market`, { method })
  const data = await response.json().catch(() => ({ error: `Backend error ${response.status}` }))
  return NextResponse.json(data, { status: response.ok ? 200 : response.status })
}

/** Preview: live price, recalculated lots and risk change. Places nothing. */
export async function GET(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied
  const ticket = ticketOf(new URL(request.url).searchParams.get('ticket'))
  if (!ticket) return NextResponse.json({ error: 'ticket required' }, { status: 400 })
  try {
    return await forward(ticket, 'GET')
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : 'Preview failed' }, { status: 500 })
  }
}

/** Convert: cancels the pending order and opens it at market (lots recalculated on live price). */
export async function POST(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied
  const body = await request.json().catch(() => ({}))
  const ticket = ticketOf(body?.ticket)
  if (!ticket) return NextResponse.json({ success: false, error: 'ticket required' }, { status: 400 })
  try {
    return await forward(ticket, 'POST')
  } catch (error) {
    return NextResponse.json(
      { success: false, error: error instanceof Error ? error.message : 'Conversion failed' },
      { status: 500 },
    )
  }
}
