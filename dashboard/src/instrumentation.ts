// Runs once when the Next.js server starts (also under the custom server.js).
// The import must sit inside this exact NEXT_RUNTIME check so webpack drops it
// from the Edge bundle (it needs Node's crypto).
export async function register() {
  if (process.env.NEXT_RUNTIME === 'nodejs') {
    const { installInternalApiAuth } = await import('./lib/internalApi')
    installInternalApiAuth()
  }
}
