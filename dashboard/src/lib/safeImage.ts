// Serving rules for images that originate from Telegram (untrusted channel
// content) — audit finding M-08. Only raster formats: SVG is an "image/*" type
// too, but it runs script when opened directly on the dashboard origin.
const RASTER_TYPES = new Set(['image/jpeg', 'image/png', 'image/gif', 'image/webp'])

export function safeImageType(contentType: string | null | undefined): string | null {
  const base = (contentType || '').split(';')[0].trim().toLowerCase()
  return RASTER_TYPES.has(base) ? base : null
}

export function imageResponseHeaders(contentType: string, maxAgeSeconds: number): Record<string, string> {
  return {
    'Content-Type': contentType,
    // Owner-only data: never let a shared cache keep it.
    'Cache-Control': `private, max-age=${maxAgeSeconds}`,
    'X-Content-Type-Options': 'nosniff',
    'Content-Security-Policy': "default-src 'none'; sandbox",
  }
}
