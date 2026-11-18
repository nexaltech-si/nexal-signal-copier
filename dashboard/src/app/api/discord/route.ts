import { NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'
import { DISCORD_ACTIONS, type DiscordAction, type DiscordGuild, type DiscordStatus } from '@/lib/types/discord'

export const dynamic = 'force-dynamic'

const PYTHON_API_URL = process.env.PYTHON_API_URL || 'http://localhost:8001'
const SNOWFLAKE = /^\d{5,25}$/

async function bot<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${PYTHON_API_URL}${path}`, {
    cache: 'no-store',
    signal: AbortSignal.timeout(30_000),
    ...init,
    headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
  })
  const body = await res.json().catch(() => null)
  if (!res.ok) {
    throw Object.assign(new Error(body?.detail || `Bot returned HTTP ${res.status}`), { status: res.status })
  }
  return body as T
}

function failure(error: unknown) {
  const status = (error as { status?: number })?.status
  return NextResponse.json(
    { error: error instanceof Error ? error.message : 'Bot unreachable' },
    { status: status && status >= 400 && status < 500 ? status : 502 }
  )
}

/** Discord listener state plus the servers the bot is in (src/api/discord_router.py). Owner-only. */
export async function GET() {
  const denied = await requireOwner()
  if (denied) return denied
  try {
    const [status, guilds] = await Promise.all([
      bot<DiscordStatus>('/api/discord/status'),
      bot<{ guilds: DiscordGuild[] }>('/api/discord/guilds'),
    ])
    return NextResponse.json({ status, guilds: guilds.guilds }, { headers: { 'Cache-Control': 'no-store' } })
  } catch (error) {
    return failure(error)
  }
}

/**
 * Everything the Discord page changes. Owner-only. A token (bot or own account) is forwarded to
 * the bot over the internal network, which stores it encrypted — it is never
 * logged or stored here, and never sent back to the browser.
 */
export async function POST(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  const body = await request.json().catch(() => null)
  const action = body?.action as DiscordAction
  if (!DISCORD_ACTIONS.includes(action)) {
    return NextResponse.json({ error: 'Unknown action' }, { status: 400 })
  }

  try {
    if (action === 'config') {
      const config: { enabled?: boolean; token?: string; userToken?: string; accountType?: string } = {}
      if (typeof body.enabled === 'boolean') config.enabled = body.enabled
      if (typeof body.token === 'string') config.token = body.token
      if (typeof body.userToken === 'string') config.userToken = body.userToken
      if (body.accountType === 'bot' || body.accountType === 'user') config.accountType = body.accountType
      if (!Object.keys(config).length) return NextResponse.json({ error: 'Nothing to change' }, { status: 400 })
      return NextResponse.json(await bot('/api/discord/config', { method: 'PUT', body: JSON.stringify(config) }))
    }
    if (action === 'reconnect') {
      return NextResponse.json(await bot('/api/discord/reconnect', { method: 'POST' }))
    }
    if (action === 'set-channels') {
      const ids: unknown = body.channelIds
      if (!SNOWFLAKE.test(body.guildId) || !Array.isArray(ids) || !ids.every((id) => typeof id === 'string' && SNOWFLAKE.test(id))) {
        return NextResponse.json({ error: 'Invalid server or channel id' }, { status: 400 })
      }
      return NextResponse.json(
        await bot(`/api/discord/guilds/${body.guildId}/channels`, { method: 'PUT', body: JSON.stringify({ channelIds: ids }) })
      )
    }
    // remove-channel
    if (!SNOWFLAKE.test(body.channelId)) return NextResponse.json({ error: 'Invalid channel id' }, { status: 400 })
    return NextResponse.json(await bot(`/api/discord/channels/${body.channelId}`, { method: 'DELETE' }))
  } catch (error) {
    return failure(error)
  }
}
