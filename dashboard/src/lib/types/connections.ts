/** Shapes for the Connections page (/api/connections). */

/** ok = working, warn = working with a problem, down = not working, off = intentionally disabled. */
export type ConnStatus = 'ok' | 'warn' | 'down' | 'off'

export interface Detail {
  label: string
  value: string
  tone?: 'good' | 'bad' | 'warn'
}

export interface ConnectionView {
  key: string
  /** Also the name used by UserSettings.disabledConnections. */
  name: string
  role: string
  status: ConnStatus
  summary: string
  latencyMs: number | null
  /** Concrete, actionable problems — empty when healthy. */
  issues: string[]
  details: Detail[]
  table?: {
    title: string
    columns: string[]
    rows: { cells: string[]; tone?: Detail['tone'] }[]
  }
  /** Buttons that POST to /api/connections/action. */
  actions: { id: ConnectionAction; label: string }[]
  links: { label: string; href: string }[]
  disabled?: boolean
  /** Telegram card only: drives the login / sign-out panel. */
  telegramAuth?: TelegramAuth
}

export type TelegramAuthState = 'not_configured' | 'starting' | 'logged_out' | 'code_sent' | 'password_required' | 'live' | 'error'

/** Mirrors TelethonListener.auth_status() in src/integrations/telegram/listener.py. */
export interface TelegramAuth {
  state: TelegramAuthState
  error: string | null
  account: { id: number; name: string; username: string | null } | null
  phoneLocked: boolean
  phoneHint: string | null
  codeVia: string | null
  resendInSeconds: number
}

export interface ConnectionsResponse {
  generatedAt: string
  overall: Exclude<ConnStatus, 'off'>
  connections: ConnectionView[]
}

export const CONNECTION_ACTIONS = ['bot.healthcheck', 'telegram.resync', 'news.refresh'] as const
export type ConnectionAction = (typeof CONNECTION_ACTIONS)[number]
