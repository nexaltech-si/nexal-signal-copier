import { NextRequest, NextResponse } from 'next/server'
import { auth } from '@clerk/nextjs/server'
import { checkAuthorization } from '@/lib/auth'
import { prisma } from '@/lib/prisma'
import { generateApiKey, hashApiKey, keyDisplayPrefix } from '@/lib/apiKeys'

export const dynamic = 'force-dynamic'

/** List every issued key with a computed status, most recent first. Admin-only. */
export async function GET() {
  const { authorized, response } = await checkAuthorization()
  if (!authorized) return response

  const keys = await prisma.apiKey.findMany({ orderBy: { createdAt: 'desc' } })
  const now = Date.now()

  return NextResponse.json({
    keys: keys.map((k) => ({
      id: k.id,
      label: k.label,
      keyPrefix: k.keyPrefix,
      createdAt: k.createdAt,
      expiresAt: k.expiresAt,
      revokedAt: k.revokedAt,
      lastUsedAt: k.lastUsedAt,
      lastUsedIp: k.lastUsedIp,
      requestCount: k.requestCount,
      status: k.revokedAt ? 'revoked' : k.expiresAt && k.expiresAt.getTime() <= now ? 'expired' : 'active',
    })),
  })
}

/** Issue a new key. Admin-only. The raw key is returned exactly once — it is
 *  never stored (only its hash is) and can never be retrieved again after this
 *  response, matching how Stripe/GitHub/etc. hand out API keys. */
export async function POST(request: NextRequest) {
  const { authorized, response } = await checkAuthorization()
  if (!authorized) return response

  const body = await request.json().catch(() => ({}))
  const label = typeof body.label === 'string' ? body.label.trim() : ''
  if (!label) {
    return NextResponse.json({ error: 'label is required (e.g. the customer name)' }, { status: 400 })
  }

  let expiresAt: Date | null = null
  if (body.expiresAt) {
    const parsed = new Date(body.expiresAt)
    if (isNaN(parsed.getTime())) {
      return NextResponse.json({ error: 'invalid expiresAt' }, { status: 400 })
    }
    expiresAt = parsed
  }

  const { userId } = await auth()
  const rawKey = generateApiKey()

  const record = await prisma.apiKey.create({
    data: {
      label,
      keyPrefix: keyDisplayPrefix(rawKey),
      keyHash: hashApiKey(rawKey),
      expiresAt,
      createdBy: userId ?? undefined,
    },
  })

  return NextResponse.json({
    id: record.id,
    label: record.label,
    expiresAt: record.expiresAt,
    // Only appears in this one response — copy it now.
    key: rawKey,
  })
}
