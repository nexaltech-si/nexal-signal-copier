import { NextResponse } from 'next/server'
import { PrismaClient } from '@prisma/client'
import { requireOwner } from '@/lib/auth'

const prisma = new PrismaClient()

// GET /api/ai-config - Read directly from database
export async function GET() {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    // Read directly from database (dashboard shares volume with bot)
    const config = await prisma.aIConfiguration.findFirst()
    
    if (!config) {
      // Create default config if not exists
      const newConfig = await prisma.aIConfiguration.create({
        data: {}
      })
      return NextResponse.json(newConfig)
    }
    
    return NextResponse.json(config)
  } catch (error) {
    console.error('Error fetching AI config:', error)
    return NextResponse.json({ error: 'Failed to fetch AI config', details: error instanceof Error ? error.message : 'Unknown error' }, { status: 500 })
  }
}

// PUT /api/ai-config - Update directly in database
export async function PUT(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const body = await request.json()
    
    // Get existing config
    const existing = await prisma.aIConfiguration.findFirst()
    
    if (!existing) {
      return NextResponse.json({ error: 'AI config not found' }, { status: 404 })
    }
    
    // Update config
    const updated = await prisma.aIConfiguration.update({
      where: { id: existing.id },
      data: body
    })
    
    return NextResponse.json(updated)
  } catch (error) {
    console.error('Error updating AI config:', error)
    return NextResponse.json({ error: 'Failed to update AI config', details: error instanceof Error ? error.message : 'Unknown error' }, { status: 500 })
  }
}
