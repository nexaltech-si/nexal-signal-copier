import { NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'
import { getActiveProvider } from '@/lib/provider'

export const dynamic = 'force-dynamic'

export async function GET() {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const tradingProvider = await getActiveProvider()
    if (tradingProvider !== 'mt5rest') {
      return NextResponse.json({ error: 'MT5 REST provider not configured' }, { status: 400 })
    }

    const mt5RestUrl = process.env.MT5_REST_API_URL
    const mt5RestApiKey = process.env.MT5_REST_API_KEY

    if (!mt5RestUrl) {
      return NextResponse.json({ error: 'MT5_REST_API_URL not configured' }, { status: 500 })
    }

    const headers: HeadersInit = {}
    if (mt5RestApiKey) {
      headers['X-API-Key'] = mt5RestApiKey
    }

    const response = await fetch(`${mt5RestUrl}/protection/config`, {
      method: 'GET',
      headers,
    })

    if (!response.ok) {
      const error = await response.json()
      return NextResponse.json(error, { status: response.status })
    }

    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error('Error fetching protection config:', error)
    return NextResponse.json({ error: 'Failed to fetch protection config' }, { status: 500 })
  }
}

export async function PUT(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  return await handleUpdate(request)
}

export async function POST(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  return await handleUpdate(request)
}

async function handleUpdate(request: Request) {
  try {
    const tradingProvider = await getActiveProvider()
    if (tradingProvider !== 'mt5rest') {
      return NextResponse.json({ error: 'MT5 REST provider not configured' }, { status: 400 })
    }

    const mt5RestUrl = process.env.MT5_REST_API_URL
    const mt5RestApiKey = process.env.MT5_REST_API_KEY

    if (!mt5RestUrl) {
      return NextResponse.json({ error: 'MT5_REST_API_URL not configured' }, { status: 500 })
    }

    const body = await request.json()

    const headers: HeadersInit = {
      'Content-Type': 'application/json',
    }
    if (mt5RestApiKey) {
      headers['X-API-Key'] = mt5RestApiKey
    }

    // Use PUT as primary, some systems might require it
    const response = await fetch(`${mt5RestUrl}/protection/config`, {
      method: 'PUT',
      headers,
      body: JSON.stringify(body),
    })

    if (!response.ok) {
      const error = await response.json()
      return NextResponse.json(error, { status: response.status })
    }

    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error('Error updating protection config:', error)
    return NextResponse.json({ error: 'Failed to update protection config' }, { status: 500 })
  }
}
