import { NextRequest, NextResponse } from 'next/server'
import { checkAuthorization } from '@/lib/auth'
import { prisma } from '@/lib/prisma'

export const dynamic = 'force-dynamic'

/** Revoke/reactivate, rename, or change the expiry of one key. Admin-only.
 *  There is deliberately no way to read the raw key back here — see POST /
 *  in the parent route for why. */
export async function PATCH(request: NextRequest, { params }: { params: { id: string } }) {
  const { authorized, response } = await checkAuthorization()
  if (!authorized) return response

  const body = await request.json().catch(() => ({}))
  const data: { revokedAt?: Date | null; label?: string; expiresAt?: Date | null } = {}

  if (body.action === 'revoke') {
    data.revokedAt = new Date()
  } else if (body.action === 'reactivate') {
    data.revokedAt = null
  }

  if ('label' in body) {
    const label = typeof body.label === 'string' ? body.label.trim() : ''
    if (!label) {
      return NextResponse.json({ error: 'label cannot be empty' }, { status: 400 })
    }
    data.label = label
  }

  if ('expiresAt' in body) {
    if (body.expiresAt === null) {
      data.expiresAt = null
    } else {
      const parsed = new Date(body.expiresAt)
      if (isNaN(parsed.getTime())) {
        return NextResponse.json({ error: 'invalid expiresAt' }, { status: 400 })
      }
      data.expiresAt = parsed
    }
  }

  if (Object.keys(data).length === 0) {
    return NextResponse.json({ error: 'no valid fields to update' }, { status: 400 })
  }

  try {
    const updated = await prisma.apiKey.update({ where: { id: params.id }, data })
    return NextResponse.json({
      id: updated.id,
      label: updated.label,
      expiresAt: updated.expiresAt,
      revokedAt: updated.revokedAt,
    })
  } catch {
    return NextResponse.json({ error: 'key not found' }, { status: 404 })
  }
}

/** Permanently delete a key and its usage history. Admin-only. Prefer revoke
 *  (PATCH action=revoke) for anything you might want to audit later — this
 *  is for cleaning up mistakes, not the normal "stop a customer" action. */
export async function DELETE(_request: NextRequest, { params }: { params: { id: string } }) {
  const { authorized, response } = await checkAuthorization()
  if (!authorized) return response

  try {
    await prisma.apiKey.delete({ where: { id: params.id } })
    return NextResponse.json({ ok: true })
  } catch {
    return NextResponse.json({ error: 'key not found' }, { status: 404 })
  }
}
