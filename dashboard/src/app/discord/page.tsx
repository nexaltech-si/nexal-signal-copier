'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronUp,
  Copy,
  ExternalLink,
  Gamepad2,
  Hash,
  KeyRound,
  Lock,
  RefreshCw,
  Search,
  Trash2,
} from 'lucide-react'
import MobilePageHeader from '@/components/MobilePageHeader'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { cn } from '@/lib/utils'
import type {
  DiscordAction,
  DiscordGuild,
  DiscordGuildChannel,
  DiscordResponse,
  DiscordState,
  DiscordStatus,
} from '@/lib/types/discord'

const POLL_MS = 15_000

const STATE: Record<DiscordState, { label: string; badge: string; text: (s: DiscordStatus) => string }> = {
  live: {
    label: 'LISTENING',
    badge: 'bg-success/10 text-success',
    text: (s) =>
      `${s.account?.name ?? 'Connected'} · in ${s.guildCount} server${s.guildCount === 1 ? '' : 's'} · listening to ${s.channels.length} channel${s.channels.length === 1 ? '' : 's'}`,
  },
  connecting: { label: 'CONNECTING', badge: 'bg-gold/10 text-gold', text: () => 'Connecting to Discord…' },
  disabled: { label: 'OFF', badge: 'bg-muted text-muted-foreground', text: () => 'Discord is switched off — no Discord messages are read' },
  no_token: { label: 'NO TOKEN', badge: 'bg-gold/10 text-gold', text: () => 'Switched on, but no bot token is saved yet' },
  error: { label: 'ERROR', badge: 'bg-destructive/10 text-destructive', text: () => 'Not connected' },
}

function ago(iso: string | null, now: number): string {
  if (!iso) return 'no message yet'
  const sec = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000))
  if (sec < 60) return `${sec}s ago`
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`
  return `${Math.floor(sec / 86400)}d ago`
}

const sameSet = (a: Set<string>, b: Set<string>) => a.size === b.size && [...a].every((id) => b.has(id))

const btn = 'h-8 text-[11px] font-bold uppercase'
const card = 'rounded-xl border bg-card shadow-sm'

// ─── Bot connection ─────────────────────────────────────────────────────────

function ConnectionCard({
  status,
  busy,
  run,
}: {
  status: DiscordStatus
  busy: DiscordAction | null
  run: (action: DiscordAction, payload?: Record<string, unknown>, done?: string) => Promise<boolean>
}) {
  const [token, setToken] = useState('')
  const [editingToken, setEditingToken] = useState(false)
  const [confirmRemove, setConfirmRemove] = useState(false)
  const [confirmUser, setConfirmUser] = useState(false)
  const [guideOpen, setGuideOpen] = useState(!status.tokenSet)
  const state = STATE[status.state]
  const showTokenInput = !status.tokenSet || editingToken
  const userMode = status.accountType === 'user'
  const tokenField = userMode ? 'userToken' : 'token'

  const saveToken = async () => {
    const ok = await run('config', { [tokenField]: token.trim(), enabled: true }, 'Token saved — connecting to Discord')
    setToken('') // never keep the token in the page
    if (ok) setEditingToken(false)
  }

  const switchTo = async (accountType: 'bot' | 'user') => {
    setConfirmUser(false)
    setEditingToken(false)
    setToken('')
    await run('config', { accountType }, accountType === 'user' ? 'Reading Discord with your own account' : 'Reading Discord with the bot')
  }

  return (
    <section className={card}>
      <div className="p-4 md:p-5 flex items-start gap-3">
        <div className={cn('w-10 h-10 rounded-lg flex items-center justify-center shrink-0', state.badge)}>
          <Gamepad2 className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <h2 className="text-sm font-bold">{userMode ? 'Discord · own account' : 'Discord bot'}</h2>
            <span className={cn('text-[10px] font-bold px-2 py-0.5 rounded-md', state.badge)}>{state.label}</span>
          </div>
          <p className="text-xs text-muted-foreground mt-1 break-words">{state.text(status)}</p>
        </div>
        <label className="flex items-center gap-2 shrink-0 cursor-pointer">
          <span className="text-[10px] font-bold uppercase text-muted-foreground hidden sm:inline">Listen</span>
          <Switch
            checked={status.enabled}
            disabled={busy !== null}
            onCheckedChange={(enabled) =>
              run('config', { enabled }, enabled ? 'Discord switched on' : 'Discord switched off')
            }
            aria-label="Listen to Discord"
          />
        </label>
      </div>

      <div className="mx-4 md:mx-5 mb-3">
        <p className="text-[10px] font-bold uppercase text-muted-foreground mb-1.5">Read Discord with</p>
        <div className="inline-flex rounded-lg border p-0.5 bg-muted/30">
          {(['bot', 'user'] as const).map((type) => (
            <button
              key={type}
              type="button"
              disabled={busy !== null}
              onClick={() => {
                if (type === status.accountType) return
                if (type === 'user') setConfirmUser(true)
                else void switchTo('bot')
              }}
              className={cn(
                'h-7 px-3 rounded-md text-[11px] font-bold uppercase transition-colors',
                status.accountType === type ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'
              )}
            >
              {type === 'bot' ? 'Bot' : 'Own account'}
            </button>
          ))}
        </div>
        <p className="text-[11px] text-muted-foreground mt-1.5">
          {userMode
            ? 'Reads every server your Discord account is a member of. Nothing is ever posted from your account.'
            : 'Official way. Works on servers where an admin added the bot.'}
        </p>
      </div>

      {(confirmUser || userMode) && (
        <div className="mx-4 md:mx-5 mb-3 rounded-lg border border-gold/30 bg-gold/10 p-3 space-y-2">
          <p className="text-xs flex gap-2">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5 text-gold" />
            <span>
              <b>Against Discord&apos;s terms of service.</b> Automating a personal account is not allowed. If Discord
              detects it, the account can be banned — including its access to paid servers. The account token gives
              full access to the account: treat it like the password.
            </span>
          </p>
          {confirmUser && (
            <div className="flex gap-2">
              <Button size="sm" className={btn} disabled={busy !== null} onClick={() => switchTo('user')}>
                I understand, use my account
              </Button>
              <Button size="sm" variant="ghost" className={btn} onClick={() => setConfirmUser(false)}>
                Cancel
              </Button>
            </div>
          )}
        </div>
      )}

      {status.error && (
        <div className="mx-4 md:mx-5 mb-3 text-xs rounded-md px-2.5 py-2 flex gap-2 bg-destructive/10 text-destructive">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
          <span className="break-words">{status.error}</span>
        </div>
      )}

      <div className="mx-4 md:mx-5 mb-4 rounded-lg border bg-muted/30 p-3 space-y-2">
        <div className="flex items-center gap-2">
          <KeyRound className="h-3.5 w-3.5 text-muted-foreground" />
          <p className="text-xs font-semibold">{userMode ? 'Account token' : 'Bot token'}</p>
          {status.tokenSet && !editingToken && (
            <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-success/10 text-success">SAVED · ENCRYPTED</span>
          )}
        </div>

        {showTokenInput ? (
          <form
            className="flex flex-col sm:flex-row gap-2"
            autoComplete="off"
            onSubmit={(e) => {
              e.preventDefault()
              void saveToken()
            }}
          >
            <Input
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder={userMode ? 'Paste the token of your Discord account' : 'Paste the bot token from the Discord Developer Portal'}
              autoComplete="off"
              spellCheck={false}
              className="h-8 text-sm font-mono"
            />
            <div className="flex gap-2">
              <Button type="submit" size="sm" className={btn} disabled={busy !== null || token.trim().length < 50}>
                {busy === 'config' ? 'Saving…' : 'Save & connect'}
              </Button>
              {editingToken && (
                <Button type="button" size="sm" variant="ghost" className={btn} onClick={() => { setEditingToken(false); setToken('') }}>
                  Cancel
                </Button>
              )}
            </div>
          </form>
        ) : confirmRemove ? (
          <div className="space-y-2">
            <p className="text-xs">Remove the token? Discord is disconnected until a new token is saved.</p>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="destructive"
                className={btn}
                disabled={busy !== null}
                onClick={async () => {
                  await run('config', { [tokenField]: '' }, 'Token removed')
                  setConfirmRemove(false)
                }}
              >
                Yes, remove
              </Button>
              <Button size="sm" variant="ghost" className={btn} onClick={() => setConfirmRemove(false)}>
                Keep it
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" className={btn} onClick={() => setEditingToken(true)}>
              Replace token
            </Button>
            <Button size="sm" variant="ghost" className={btn} disabled={busy !== null} onClick={() => run('reconnect', {}, 'Reconnecting…')}>
              <RefreshCw className={cn('h-3 w-3 mr-1', busy === 'reconnect' && 'animate-spin')} />
              Reconnect
            </Button>
            <Button size="sm" variant="ghost" className={cn(btn, 'text-muted-foreground')} onClick={() => setConfirmRemove(true)}>
              Remove
            </Button>
          </div>
        )}
        <p className="text-[11px] text-muted-foreground">
          The token is stored encrypted in the database and is never shown again. Nothing is read from the server&apos;s
          environment file.
        </p>
      </div>

      {status.inviteUrl && (
        <div className="mx-4 md:mx-5 mb-4 flex flex-wrap items-center gap-2">
          <a
            href={status.inviteUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center h-8 px-3 rounded-md bg-primary text-primary-foreground text-[11px] font-bold uppercase hover:bg-primary/90"
          >
            Add the bot to a server
            <ExternalLink className="h-3 w-3 ml-1.5" />
          </a>
          <Button
            size="sm"
            variant="ghost"
            className={btn}
            onClick={() => {
              void navigator.clipboard.writeText(status.inviteUrl!)
              toast.success('Invite link copied — send it to the server owner')
            }}
          >
            <Copy className="h-3 w-3 mr-1" />
            Copy invite link
          </Button>
          <span className="text-[11px] text-muted-foreground">Read-only: View Channels + Read Message History.</span>
        </div>
      )}

      <div className="border-t">
        <button
          type="button"
          onClick={() => setGuideOpen(!guideOpen)}
          className="w-full flex items-center justify-between px-4 md:px-5 py-2.5 text-[11px] font-bold uppercase text-muted-foreground hover:text-foreground"
        >
          How to set this up
          {guideOpen ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        </button>
        {guideOpen && userMode && (
          <ol className="px-4 md:px-5 pb-4 space-y-2 text-xs text-muted-foreground list-decimal list-inside">
            <li>
              Open <b>discord.com/app</b> in a desktop browser (Chrome, Edge, Firefox) and log in with the account that
              is a member of the servers.
            </li>
            <li>
              Press <b>F12</b> → tab <b>Network</b>, then click any channel in Discord. Select one of the new requests
              (for example <b>messages</b>) → <b>Headers</b> → <b>Request Headers</b> → copy the value of{' '}
              <b>authorization</b>.
            </li>
            <li>Paste it above. It is stored encrypted and never shown again.</li>
            <li>
              Your servers appear below. Tick the channels to listen to — every server has its own selection.
            </li>
            <li>
              The token stops working when you change your password or log out of all devices. Then copy the new one
              and save it again.
            </li>
          </ol>
        )}
        {guideOpen && !userMode && (
          <ol className="px-4 md:px-5 pb-4 space-y-2 text-xs text-muted-foreground list-decimal list-inside">
            <li>
              Open{' '}
              <a href="https://discord.com/developers/applications" target="_blank" rel="noopener noreferrer" className="underline text-foreground">
                discord.com/developers/applications
              </a>{' '}
              → <b>New Application</b> → <b>Bot</b> → <b>Reset Token</b>, and paste the token above.
            </li>
            <li>
              On the same <b>Bot</b> page switch on <b>Message Content Intent</b> (Privileged Gateway Intents). Without it
              Discord delivers empty messages.
            </li>
            <li>
              Press <b>Add the bot to a server</b>. Discord only lets someone with the <b>Manage Server</b> permission add a
              bot — for a server you do not run, send the invite link to its owner or an admin.
            </li>
            <li>The server appears below. Tick the channels to listen to — every server has its own selection.</li>
          </ol>
        )}
      </div>
    </section>
  )
}

// ─── One server and its channels ────────────────────────────────────────────

function GuildCard({
  guild,
  lastMessage,
  now,
  saving,
  onSave,
}: {
  guild: DiscordGuild
  lastMessage: Record<string, string | null>
  now: number
  saving: boolean
  onSave: (guild: DiscordGuild, ids: string[]) => Promise<boolean>
}) {
  const saved = useMemo(() => new Set(guild.channels.filter((c) => c.monitored).map((c) => c.id)), [guild.channels])
  const [draft, setDraft] = useState<Set<string> | null>(null) // null = no unsaved changes
  const [open, setOpen] = useState(saved.size > 0)
  const [query, setQuery] = useState('')
  // Once channels are chosen the card lists only those; the full list of a big
  // server (dozens of channels) is one click away for adding more.
  const [showAll, setShowAll] = useState(saved.size === 0)
  const selected = draft ?? saved
  const listAll = showAll || (saved.size === 0 && selected.size === 0)
  const dirty = draft !== null && !sameSet(draft, saved)

  const toggle = (id: string) => {
    const next = new Set(selected)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setDraft(next)
  }

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase()
    const out: { category: string | null; channels: DiscordGuildChannel[] }[] = []
    for (const channel of guild.channels) {
      // a channel just unticked stays visible until saved, so the change can still be seen and undone
      if (!listAll && !selected.has(channel.id) && !saved.has(channel.id)) continue
      if (listAll && q && !channel.name.toLowerCase().includes(q) && !(channel.category ?? '').toLowerCase().includes(q)) continue
      const last = out[out.length - 1]
      if (last && last.category === channel.category) last.channels.push(channel)
      else out.push({ category: channel.category, channels: [channel] })
    }
    return out
  }, [guild.channels, query, listAll, selected, saved])

  const initials = guild.name.split(/\s+/).map((w) => w[0]).join('').slice(0, 2).toUpperCase()

  return (
    <div className={card}>
      <button type="button" onClick={() => setOpen(!open)} className="w-full p-3 md:p-4 flex items-center gap-3 text-left">
        <div className="w-10 h-10 rounded-xl bg-primary/10 text-primary flex items-center justify-center text-xs font-bold shrink-0 overflow-hidden">
          {guild.icon ? (
            // eslint-disable-next-line @next/next/no-img-element -- Discord CDN icon, not worth an image-optimizer allowlist
            <img src={guild.icon} alt="" className="w-full h-full object-cover" referrerPolicy="no-referrer" />
          ) : (
            initials
          )}
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-bold truncate">{guild.name}</p>
          <p className="text-[11px] text-muted-foreground">
            {selected.size === 0 ? 'Not listening to any channel' : `Listening to ${selected.size} of ${guild.channels.length} channels`}
            {dirty && <span className="text-gold font-bold"> · unsaved</span>}
          </p>
        </div>
        {open ? <ChevronUp className="h-4 w-4 text-muted-foreground" /> : <ChevronDown className="h-4 w-4 text-muted-foreground" />}
      </button>

      {open && (
        <div className="border-t">
          {(saved.size > 0 || selected.size > 0) && (
            <div className="flex items-center justify-between gap-2 px-4 pt-3">
              <p className="text-[11px] text-muted-foreground">
                {listAll ? `All ${guild.channels.length} channels of this server` : 'Only the channels you listen to'}
              </p>
              <button
                type="button"
                onClick={() => { setShowAll(!listAll); setQuery('') }}
                className="text-[11px] font-bold uppercase text-primary hover:underline shrink-0"
              >
                {listAll ? 'Show selected only' : `Add channels (${guild.channels.length})`}
              </button>
            </div>
          )}
          {listAll && guild.channels.length > 8 && (
            <div className="relative m-3">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
              <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search channels" className="h-8 pl-8 text-sm" />
            </div>
          )}
          <div className="max-h-[420px] overflow-y-auto pb-2">
            {groups.length === 0 && <p className="px-4 py-3 text-xs text-muted-foreground">No channel matches.</p>}
            {groups.map((group, i) => (
              <div key={`${group.category}-${i}`}>
                {group.category && (
                  <p className="px-4 pt-3 pb-1 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">{group.category}</p>
                )}
                {group.channels.map((channel) => {
                  const checked = selected.has(channel.id)
                  const blocked = !channel.readable && !checked
                  return (
                    <label
                      key={channel.id}
                      className={cn(
                        'flex items-center gap-2.5 px-4 py-2 text-sm cursor-pointer hover:bg-muted/40',
                        checked && 'bg-primary/5',
                        blocked && 'opacity-50 cursor-not-allowed'
                      )}
                    >
                      <input
                        type="checkbox"
                        className="h-4 w-4 accent-[hsl(var(--primary))] shrink-0"
                        checked={checked}
                        disabled={blocked}
                        onChange={() => toggle(channel.id)}
                      />
                      {channel.readable ? (
                        <Hash className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                      ) : (
                        <Lock className="h-3.5 w-3.5 text-gold shrink-0" />
                      )}
                      <span className={cn('truncate', checked && 'font-semibold')}>{channel.name}</span>
                      <span className="ml-auto text-[10px] text-muted-foreground whitespace-nowrap">
                        {!channel.readable
                          ? 'no access'
                          : channel.monitored
                            ? ago(lastMessage[channel.id] ?? null, now)
                            : ''}
                      </span>
                    </label>
                  )
                })}
              </div>
            ))}
          </div>
          <div className="border-t px-3 md:px-4 py-2 flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              className={btn}
              disabled={!dirty || saving}
              onClick={async () => {
                if (await onSave(guild, [...selected])) { setDraft(null); setShowAll(false) }
              }}
            >
              <Check className="h-3.5 w-3.5 mr-1" />
              {saving ? 'Saving…' : 'Save selection'}
            </Button>
            {dirty && (
              <Button size="sm" variant="ghost" className={btn} disabled={saving} onClick={() => setDraft(null)}>
                Undo
              </Button>
            )}
            {selected.size > 0 && (
              <Button size="sm" variant="ghost" className={cn(btn, 'ml-auto text-muted-foreground')} disabled={saving} onClick={() => setDraft(new Set())}>
                Clear all
              </Button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Page ───────────────────────────────────────────────────────────────────

export default function DiscordPage() {
  const [data, setData] = useState<DiscordResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<DiscordAction | null>(null)
  const [savingGuild, setSavingGuild] = useState<string | null>(null)
  const [now, setNow] = useState(Date.now())

  const load = useCallback(async () => {
    try {
      const res = await fetch('/api/discord', { cache: 'no-store' })
      const body = await res.json().catch(() => null)
      if (!res.ok || !body) throw new Error(body?.error || `HTTP ${res.status}`)
      setData(body)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load Discord status')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
    const poll = setInterval(load, POLL_MS)
    const tick = setInterval(() => setNow(Date.now()), 5000)
    return () => {
      clearInterval(poll)
      clearInterval(tick)
    }
  }, [load])

  const post = useCallback(async (action: DiscordAction, payload: Record<string, unknown> = {}) => {
    const res = await fetch('/api/discord', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, ...payload }),
    })
    const body = await res.json().catch(() => null)
    if (!res.ok) throw new Error(body?.error || `HTTP ${res.status}`)
    return body
  }, [])

  const run = useCallback(
    async (action: DiscordAction, payload: Record<string, unknown> = {}, done?: string) => {
      setBusy(action)
      try {
        await post(action, payload)
        if (done) toast.success(done)
        await load()
        // The gateway handshake takes a moment: look again so "connecting" turns into the result
        setTimeout(load, 3000)
        return true
      } catch (e) {
        toast.error(e instanceof Error ? e.message : 'Request failed')
        return false
      } finally {
        setBusy(null)
      }
    },
    [post, load]
  )

  const saveGuild = async (guild: DiscordGuild, channelIds: string[]) => {
    setSavingGuild(guild.id)
    try {
      await post('set-channels', { guildId: guild.id, channelIds })
      toast.success(
        channelIds.length
          ? `${guild.name}: listening to ${channelIds.length} channel${channelIds.length === 1 ? '' : 's'}`
          : `${guild.name}: not listening to any channel`
      )
      await load()
      return true
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not save the selection')
      return false
    } finally {
      setSavingGuild(null)
    }
  }

  const status = data?.status
  const guilds = data?.guilds ?? []
  const guildIds = new Set(guilds.map((g) => g.id))
  const lastMessage = Object.fromEntries((status?.channels ?? []).map((c) => [c.id, c.lastMessageAt]))
  const problems = (status?.channels ?? []).filter((c) => c.problem)
  // Selected channels of servers the bot is not in right now (it was removed, or it is offline)
  const orphans = status?.state === 'live' ? (status.channels ?? []).filter((c) => !guildIds.has(c.guildId)) : []
  const offlineSelection = status && status.state !== 'live' ? status.channels : []

  return (
    <div className="flex min-h-full flex-col pb-10">
      <MobilePageHeader title="Discord" subtitle="Signal source" icon={<Gamepad2 className="h-5 w-5 text-primary" />} />
      <header className="hidden md:flex sticky top-0 z-40 w-full tech-header">
        <div className="max-w-[1800px] w-full mx-auto flex h-14 items-center px-6 gap-3">
          <div className="p-1.5 rounded-lg bg-primary/10 border border-primary/20">
            <Gamepad2 className="h-5 w-5 text-primary" />
          </div>
          <div className="flex flex-col">
            <h1 className="text-sm font-bold text-foreground leading-none">Discord</h1>
            <p className="text-[10px] text-[#6b7288] font-bold uppercase tracking-wider mt-1">Servers &amp; channels the bot listens to</p>
          </div>
          <Button variant="ghost" size="sm" onClick={load} className="ml-auto h-7 text-[10px] font-bold uppercase">
            <RefreshCw className={cn('h-3 w-3 mr-1.5', loading && 'animate-spin')} />
            Refresh
          </Button>
        </div>
      </header>

      <main className="flex-1 px-3 md:px-4 py-4 md:py-6 max-w-4xl mx-auto w-full space-y-4 md:space-y-6">
        {error && !data && (
          <div className="rounded-xl border border-destructive/20 bg-destructive/10 p-4 text-sm text-destructive">
            Could not reach the bot ({error}).
          </div>
        )}
        {!data && loading && <div className={cn(card, 'p-5 text-sm text-muted-foreground')}>Loading…</div>}

        {status && <ConnectionCard status={status} busy={busy} run={run} />}

        {status && problems.length > 0 && (
          <div className="rounded-xl border border-gold/20 bg-gold/10 p-4 space-y-1.5">
            <p className="text-xs font-bold text-gold">Selected channels that cannot be read</p>
            {problems.map((c) => (
              <p key={c.id} className="text-xs">
                <span className="font-semibold">{c.guildName} #{c.name}</span> — {c.problem}
              </p>
            ))}
          </div>
        )}

        {status?.state === 'live' && (
          <section className="space-y-3">
            <div>
              <h2 className="text-sm font-bold">Servers</h2>
              <p className="text-xs text-muted-foreground">
                Only the ticked channels are read. Everything else on a server is ignored.
              </p>
            </div>
            {guilds.length === 0 ? (
              <div className={cn(card, 'p-5 text-sm text-muted-foreground')}>
                {status.accountType === 'user'
                  ? 'Connected, but this account is not a member of any server.'
                  : <>The bot is connected but not in any server yet. Use <b>Add the bot to a server</b> above.</>}
              </div>
            ) : (
              guilds.map((guild) => (
                <GuildCard
                  key={guild.id}
                  guild={guild}
                  lastMessage={lastMessage}
                  now={now}
                  saving={savingGuild === guild.id}
                  onSave={saveGuild}
                />
              ))
            )}
          </section>
        )}

        {(orphans.length > 0 || offlineSelection.length > 0) && (
          <section className={card}>
            <div className="p-4 border-b">
              <h2 className="text-sm font-bold">{orphans.length > 0 ? 'Servers that are not reachable' : 'Saved selection'}</h2>
              <p className="text-xs text-muted-foreground">
                {orphans.length > 0
                  ? 'These channels are still selected, but their server is not reachable with the current account.'
                  : 'These channels are listened to as soon as the bot is connected.'}
              </p>
            </div>
            {(orphans.length > 0 ? orphans : offlineSelection).map((c) => (
              <div key={c.id} className="flex items-center gap-2 px-4 py-2 border-b last:border-b-0 text-sm">
                <Hash className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                <span className="truncate">
                  <span className="text-muted-foreground">{c.guildName ?? c.guildId} · </span>
                  {c.name ?? c.id}
                </span>
                <Button
                  size="sm"
                  variant="ghost"
                  className="ml-auto h-7 px-2 text-muted-foreground hover:text-destructive"
                  disabled={busy !== null}
                  onClick={() => run('remove-channel', { channelId: c.id }, 'Channel removed')}
                  aria-label={`Stop listening to ${c.name ?? c.id}`}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            ))}
          </section>
        )}
      </main>
    </div>
  )
}
