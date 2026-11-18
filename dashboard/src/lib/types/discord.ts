/** Shapes for the Discord page (/api/discord). Mirrors DiscordListener.status() / .guilds()
 *  in src/integrations/discord/listener.py. */

export type DiscordState = 'disabled' | 'no_token' | 'connecting' | 'live' | 'error'

export interface DiscordMonitoredChannel {
  id: string
  name: string | null
  guildId: string
  guildName: string | null
  lastMessageAt: string | null
  /** Why the bot cannot read this channel right now, if it cannot. */
  problem: string | null
}

/** bot = official bot (a server admin must add it); user = the owner's own Discord account. */
export type DiscordAccountType = 'bot' | 'user'

export interface DiscordStatus {
  enabled: boolean
  accountType: DiscordAccountType
  /** A token is saved for the active account type. */
  tokenSet: boolean
  botTokenSet: boolean
  userTokenSet: boolean
  state: DiscordState
  error: string | null
  account: { id: string; name: string } | null
  inviteUrl: string | null
  guildCount: number
  listeningSince: string | null
  lastMessageAt: string | null
  inflight: number
  channels: DiscordMonitoredChannel[]
}

export interface DiscordGuildChannel {
  id: string
  name: string
  category: string | null
  readable: boolean
  monitored: boolean
}

export interface DiscordGuild {
  id: string
  name: string
  icon: string | null
  channels: DiscordGuildChannel[]
}

export interface DiscordResponse {
  status: DiscordStatus
  guilds: DiscordGuild[]
}

export const DISCORD_ACTIONS = ['config', 'reconnect', 'set-channels', 'remove-channel'] as const
export type DiscordAction = (typeof DISCORD_ACTIONS)[number]
