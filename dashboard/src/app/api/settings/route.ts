import { NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'

export const dynamic = 'force-dynamic'

// Python API server URL (configured via environment variable)
const PYTHON_API_URL = process.env.PYTHON_API_URL || 'http://localhost:8001'

/**
 * GET /api/settings
 * Proxy to Python API server for secure encryption/decryption
 */
export async function GET(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const url = new URL(request.url)
    const category = url.searchParams.get('category')
    const decryptSecrets = url.searchParams.get('decryptSecrets')

    // Build Python API URL
    const pythonUrl = new URL(`${PYTHON_API_URL}/api/settings`)
    if (category) pythonUrl.searchParams.set('category', category)
    if (decryptSecrets) pythonUrl.searchParams.set('decryptSecrets', decryptSecrets)

    // Proxy request to Python API
    const response = await fetch(pythonUrl.toString())
    
    if (!response.ok) {
      const error = await response.json()
      return NextResponse.json(error, { status: response.status })
    }

    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error('Error proxying to Python API:', error)
    return NextResponse.json(
      { error: 'Failed to fetch settings from Python API' },
      { status: 500 }
    )
  }
}

/**
 * POST /api/settings
 * Proxy to Python API server for secure encryption
 */
export async function POST(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const body = await request.json()
    
    // Proxy request to Python API
    const response = await fetch(`${PYTHON_API_URL}/api/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    
    if (!response.ok) {
      const error = await response.json()
      return NextResponse.json(error, { status: response.status })
    }

    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error('Error proxying to Python API:', error)
    return NextResponse.json(
      { error: 'Failed to create setting via Python API' },
      { status: 500 }
    )
  }
}
