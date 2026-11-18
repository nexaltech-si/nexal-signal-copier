import { randomBytes, createHash } from 'crypto'
import { BlockList, isIP } from 'net'
import { Prisma } from '@prisma/client'
import { prisma } from '@/lib/prisma'

// Prefix identifies these as NEXAL keys at a glance (in support chats, logs,
// broker WebRequest whitelists) without revealing anything about the key itself.
const KEY_PREFIX = 'ask_live_'
// Length of the raw key shown to the admin in the list view — enough to tell
// keys apart, never enough to reconstruct the secret.
const DISPLAY_PREFIX_LEN = KEY_PREFIX.length + 8

/** A fresh, high-entropy raw key. Shown to the admin exactly once, at creation. */
export function generateApiKey(): string {
  return KEY_PREFIX + randomBytes(24).toString('hex')
}

/** SHA-256 is fine here (not bcrypt/argon2): this hashes a 192-bit random key,
 *  not a human-chosen password, so there is no low-entropy input to protect
 *  against offline brute force — the lookup is by exact hash equality via an
 *  indexed column, the same approach GitHub/Stripe use for API keys. */
export function hashApiKey(rawKey: string): string {
  return createHash('sha256').update(rawKey).digest('hex')
}

export function keyDisplayPrefix(rawKey: string): string {
  return rawKey.slice(0, DISPLAY_PREFIX_LEN)
}

export type KeyValidation =
  | { ok: true; apiKey: { id: string; label: string } }
  | { ok: false; reason: 'invalid' }
  | { ok: false; reason: 'revoked' | 'expired'; apiKey: { id: string; label: string } }

/** Look up a raw key by its hash and check it's still usable. Never throws. */
export async function validateApiKey(rawKey: string | null): Promise<KeyValidation> {
  if (!rawKey) return { ok: false, reason: 'invalid' }

  const record = await prisma.apiKey.findUnique({ where: { keyHash: hashApiKey(rawKey) } })
  if (!record) return { ok: false, reason: 'invalid' }

  const apiKey = { id: record.id, label: record.label }
  if (record.revokedAt) return { ok: false, reason: 'revoked', apiKey }
  if (record.expiresAt && record.expiresAt.getTime() <= Date.now()) {
    return { ok: false, reason: 'expired', apiKey }
  }
  return { ok: true, apiKey }
}

/** Record one request in the key's connection log and bump its rolling
 *  counters. The log keeps one row per (key, client IP, status): a repeat
 *  request from the same IP only refreshes that row's lastSeenAt/hits, and a
 *  new IP adds a row. Only called for a RECOGNIZED key (valid, expired, or
 *  revoked) — a completely unknown key has no ApiKey row to attach a log entry
 *  to; that case is left to the server console (see route.ts). */
export async function recordUsage(params: {
  apiKeyId: string
  ip: string | null
  userAgent: string | null
  endpoint: string
  status: 'ok' | 'expired' | 'revoked'
}): Promise<void> {
  const now = new Date()
  const match = { apiKeyId: params.apiKeyId, ip: params.ip, status: params.status }
  const touch = {
    lastSeenAt: now,
    hits: { increment: 1 },
    userAgent: params.userAgent ?? undefined,
    endpoint: params.endpoint,
  }

  const { count } = await prisma.apiKeyUsage.updateMany({ where: match, data: touch })
  if (count === 0) {
    try {
      await prisma.apiKeyUsage.create({
        data: {
          ...match,
          ip: params.ip ?? undefined,
          userAgent: params.userAgent ?? undefined,
          endpoint: params.endpoint,
          createdAt: now,
          lastSeenAt: now,
        },
      })
    } catch (e) {
      // Two first requests from a new IP raced (the copier polls two endpoints
      // at once); the other one created the row, so count this hit on it.
      if (!(e instanceof Prisma.PrismaClientKnownRequestError && e.code === 'P2002')) throw e
      await prisma.apiKeyUsage.updateMany({ where: match, data: touch })
    }
  }

  if (params.status === 'ok') {
    await prisma.apiKey.update({
      where: { id: params.apiKeyId },
      data: {
        lastUsedAt: now,
        lastUsedIp: params.ip ?? undefined,
        requestCount: { increment: 1 },
      },
    })
  }
}

// Cloudflare's published edge ranges (https://www.cloudflare.com/ips/).
const CLOUDFLARE_EDGES = new BlockList()
for (const cidr of [
  '173.245.48.0/20', '103.21.244.0/22', '103.22.200.0/22', '103.31.4.0/22',
  '141.101.64.0/18', '108.162.192.0/18', '190.93.240.0/20', '188.114.96.0/20',
  '197.234.240.0/22', '198.41.128.0/17', '162.158.0.0/15', '104.16.0.0/13',
  '104.24.0.0/14', '172.64.0.0/13', '131.0.72.0/22',
  '2400:cb00::/32', '2606:4700::/32', '2803:f800::/32', '2405:b500::/32',
  '2405:8100::/32', '2a06:98c0::/29', '2c0f:f248::/32',
]) {
  const [net, bits] = cidr.split('/')
  CLOUDFLARE_EDGES.addSubnet(net, Number(bits), net.includes(':') ? 'ipv6' : 'ipv4')
}

function isCloudflareEdge(ip: string): boolean {
  const family = isIP(ip)
  return family !== 0 && CLOUDFLARE_EDGES.check(ip, family === 6 ? 'ipv6' : 'ipv4')
}

/** The caller's real IP. Public traffic arrives Cloudflare → Traefik, and
 *  Traefik (no trusted forwarders configured) sets X-Forwarded-For to the
 *  Cloudflare edge it was connected from — a different edge from one request
 *  to the next. The client itself is in CF-Connecting-IP, which is trusted
 *  only when the peer really is a Cloudflare edge, so a request that hits the
 *  origin directly can't spoof it. */
export function clientIp(request: Request): string | null {
  const fwd = request.headers.get('x-forwarded-for')
  const peer = fwd ? fwd.split(',')[0].trim() : request.headers.get('x-real-ip')
  const cf = request.headers.get('cf-connecting-ip')?.trim()
  if (cf && isIP(cf) && peer && isCloudflareEdge(peer)) return cf
  return peer
}
