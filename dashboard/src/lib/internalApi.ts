import { createHmac } from 'crypto'

// Shared secret for the bot's internal API (audit finding H-05). Must match
// src/api/internal_auth.py: INTERNAL_API_TOKEN, else an HMAC of the
// SETTINGS_ENCRYPTION_KEY both containers already load from the same .env.
export const INTERNAL_TOKEN_HEADER = 'X-Internal-Token'
const DERIVATION_LABEL = 'nexal-internal-api-v1'

export function resolveInternalToken(env: Record<string, string | undefined> = process.env): string | null {
  const explicit = env.INTERNAL_API_TOKEN?.trim()
  if (explicit) return explicit
  const base = env.SETTINGS_ENCRYPTION_KEY?.trim()
  if (base) return createHmac('sha256', base).update(DERIVATION_LABEL).digest('hex')
  return null
}

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === 'string') return input
  if (input instanceof URL) return input.href
  return input.url
}

/**
 * Wraps a fetch so that requests to `apiBase`'s origin carry the internal token.
 * Requests to any other origin are passed through untouched, so the token never
 * leaves the Docker network.
 */
export function withInternalToken(baseFetch: typeof fetch, apiBase: string, token: string): typeof fetch {
  const apiOrigin = new URL(apiBase).origin
  const wrapped = ((input: RequestInfo | URL, init?: RequestInit) => {
    let origin: string | null = null
    try { origin = new URL(requestUrl(input)).origin } catch { /* relative URL: not ours */ }
    if (origin !== apiOrigin) return baseFetch(input, init)

    const headers = new Headers(init?.headers ?? (input instanceof Request ? input.headers : undefined))
    headers.set(INTERNAL_TOKEN_HEADER, token)
    return baseFetch(input, { ...init, headers })
  }) as typeof fetch
  // Keep markers other code uses to detect Next's own fetch patch.
  return Object.assign(wrapped, baseFetch)
}

export function installInternalApiAuth(): void {
  const token = resolveInternalToken()
  if (!token) {
    console.error('❌ SECURITY: no INTERNAL_API_TOKEN or SETTINGS_ENCRYPTION_KEY — calls to the bot API will be rejected (401).')
    return
  }
  const apiBase = process.env.PYTHON_API_URL || 'http://localhost:8001'
  globalThis.fetch = withInternalToken(globalThis.fetch, apiBase, token)
}
