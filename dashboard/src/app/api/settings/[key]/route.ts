import { NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import type { SettingUpdateRequest } from '@/lib/types/settings'
import { requireOwner } from '@/lib/auth'

export const dynamic = 'force-dynamic'

// Python API server URL (configured via environment variable)
const PYTHON_API_URL = process.env.PYTHON_API_URL || 'http://localhost:8001'

/**
 * PUT /api/settings/[key]
 * Update a single setting value. Secret settings go through the Python API,
 * which encrypts them; written here they would be stored as plain text.
 */
export async function PUT(
  request: Request,
  { params }: { params: Promise<{ key: string }> }
) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const { key } = await params
    const body: SettingUpdateRequest = await request.json()

    // Serialize the value — for new settings, default to STRING type
    let serializedValue: string
    let valueType = 'STRING'

    // @ts-ignore - Setting model will be available after Prisma migration
    const existing = await prisma.setting.findUnique({ where: { key } })
    if (existing) {
      valueType = existing.valueType
    }

    if (existing?.isSecret) {
      const response = await fetch(`${PYTHON_API_URL}/api/settings/${encodeURIComponent(key)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value: body.value }),
      })
      const data = await response.json().catch(() => ({ error: 'Invalid response from Python API' }))
      return NextResponse.json(data, { status: response.status })
    }

    switch (valueType) {
      case 'JSON':
        serializedValue = JSON.stringify(body.value)
        break
      default:
        serializedValue = String(body.value)
    }

    // Upsert: create if missing, update if exists — so new model fields like
    // GEMINI_MODEL are created automatically on first save.
    // @ts-ignore - Setting model will be available after Prisma migration
    const updated = await prisma.setting.upsert({
      where: { key },
      create: {
        key,
        value: serializedValue,
        valueType,
        category: existing?.category ?? 'AI',
        description: existing?.description ?? '',
        isSecret: existing?.isSecret ?? false,
      },
      update: { value: serializedValue },
    })

    return NextResponse.json({
      success: true,
      setting: updated,
    })
  } catch (error) {
    console.error('Error updating setting:', error)
    return NextResponse.json(
      { error: 'Failed to update setting' },
      { status: 500 }
    )
  }
}

/**
 * DELETE /api/settings/[key]
 * Permanently remove a single setting (used to clean up unused/custom keys)
 */
export async function DELETE(
  request: Request,
  { params }: { params: Promise<{ key: string }> }
) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const { key } = await params

    // @ts-ignore - Setting model will be available after Prisma migration
    const existing = await prisma.setting.findUnique({ where: { key } })
    if (!existing) {
      return NextResponse.json({ error: 'Setting not found' }, { status: 404 })
    }

    // @ts-ignore - Setting model will be available after Prisma migration
    await prisma.setting.delete({ where: { key } })

    return NextResponse.json({ success: true, key })
  } catch (error) {
    console.error('Error deleting setting:', error)
    return NextResponse.json(
      { error: 'Failed to delete setting' },
      { status: 500 }
    )
  }
}
