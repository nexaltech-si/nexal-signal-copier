'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { toast } from 'sonner'
import {
  Link2,
  RefreshCw,
  Server,
  Cpu,
  Database,
  MessageSquare,
  Bell,
  Rss,
  Copy,
  Zap,
  ShieldCheck,
  XCircle,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  CircleOff,
  ArrowUpRight,
  LogIn,
  LogOut,
  Gamepad2,
  type LucideIcon,
} from 'lucide-react'
import MobilePageHeader from '@/components/MobilePageHeader'
import ProviderSwitcher from '@/components/ProviderSwitcher'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import type { ConnectionsResponse, ConnectionView, ConnStatus, Detail, ConnectionAction, TelegramAuth } from '@/lib/types/connections'

const POLL_MS = 20_000

const ICONS: Record<string, LucideIcon> = {
  bot: Cpu,
  mt5: Server,
  telegram: MessageSquare,
  discord: Gamepad2,
  copier: Copy,
  news: Rss,
  notifications: Bell,
  database: Database,
  redis: Zap,
}

const STATUS: Record<ConnStatus, { label: string; badge: string; icon: string; dot: string }> = {
  ok: { label: 'OK', badge: 'bg-success/10 text-success', icon: 'bg-success/10 text-success', dot: 'bg-emerald-500' },
  warn: { label: 'ATTENTION', badge: 'bg-gold/10 text-gold', icon: 'bg-gold/10 text-gold', dot: 'bg-amber-500' },
  down: { label: 'DOWN', badge: 'bg-destructive/10 text-destructive', icon: 'bg-destructive/10 text-destructive', dot: 'bg-rose-500' },
  off: { label: 'OFF', badge: 'bg-muted text-muted-foreground', icon: 'bg-muted text-muted-foreground', dot: 'bg-muted-foreground' },
}

const TONE: Record<NonNullable<Detail['tone']>, string> = {
  good: 'text-success',
  bad: 'text-destructive',
  warn: 'text-gold',
}

function secondsAgo(iso: string | undefined, now: number) {
  if (!iso) return null
  return Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000))
}

type AuthStep = 'send-code' | 'code' | 'password' | 'cancel' | 'sign-out'

/** Telegram login / re-login / sign-out (replaces the old Flask page on :5001). */
function TelegramAuthPanel({ auth, onChanged }: { auth: TelegramAuth; onChanged: () => void }) {
  const [phone, setPhone] = useState('')
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState<AuthStep | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [confirmSignOut, setConfirmSignOut] = useState(false)
  const [resendAt, setResendAt] = useState(0)

  useEffect(() => {
    setResendAt(Date.now() + auth.resendInSeconds * 1000)
  }, [auth.resendInSeconds, auth.state])

  const resendIn = Math.max(0, Math.ceil((resendAt - Date.now()) / 1000))

  const run = async (action: AuthStep, payload: Record<string, string> = {}) => {
    setBusy(action)
    setError(null)
    try {
      const res = await fetch('/api/telegram/auth', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, ...payload }),
      })
      const body = await res.json().catch(() => null)
      if (!res.ok) throw new Error(body?.error || `HTTP ${res.status}`)
      if (action === 'code') setCode('')
      if (body?.state === 'live') toast.success('Logged in to Telegram — listening for signals')
      if (action === 'sign-out') toast.success('Signed out of Telegram')
      setConfirmSignOut(false)
      onChanged()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Request failed')
    } finally {
      if (action === 'password') setPassword('') // never keep the 2FA password around
      setBusy(null)
    }
  }

  const btn = 'h-8 text-[11px] font-bold uppercase'
  const box = 'mx-3 md:mx-4 mb-3 rounded-lg border bg-muted/30 p-3 space-y-2'

  if (auth.state === 'starting' || auth.state === 'not_configured') return null

  if (auth.state === 'live' || auth.state === 'error') {
    return (
      <div className="mx-3 md:mx-4 mb-3">
        {confirmSignOut ? (
          <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 space-y-2">
            <p className="text-xs">
              Sign out of Telegram? The bot stops receiving signals until you log in again, and the session is ended on
              Telegram&apos;s side too.
            </p>
            <div className="flex gap-2">
              <Button size="sm" variant="destructive" className={btn} disabled={busy !== null} onClick={() => run('sign-out')}>
                <LogOut className="h-3.5 w-3.5 mr-1" />
                {busy === 'sign-out' ? 'Signing out…' : 'Yes, sign out'}
              </Button>
              <Button size="sm" variant="ghost" className={btn} disabled={busy !== null} onClick={() => setConfirmSignOut(false)}>
                Keep logged in
              </Button>
            </div>
            {error && <p className="text-xs text-destructive">{error}</p>}
          </div>
        ) : (
          <Button size="sm" variant="ghost" className={cn(btn, 'h-7 px-2 text-[10px] text-muted-foreground')} onClick={() => setConfirmSignOut(true)}>
            <LogOut className="h-3 w-3 mr-1" />
            Sign out of Telegram
          </Button>
        )}
      </div>
    )
  }

  if (auth.state === 'logged_out') {
    return (
      <form
        className={box}
        onSubmit={(e) => {
          e.preventDefault()
          run('send-code', { phone: auth.phoneLocked ? '' : phone })
        }}
      >
        <p className="text-xs font-semibold">
          {auth.phoneLocked ? `Log in as ${auth.phoneHint}` : 'Log in to the Telegram account the bot listens with'}
        </p>
        {!auth.phoneLocked && (
          <Input
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="+44 7700 900123"
            inputMode="tel"
            autoComplete="tel"
            className="h-8 text-sm"
          />
        )}
        <Button type="submit" size="sm" className={btn} disabled={busy !== null || resendIn > 0 || (!auth.phoneLocked && !phone.trim())}>
          <LogIn className="h-3.5 w-3.5 mr-1" />
          {busy === 'send-code' ? 'Sending…' : resendIn > 0 ? `Send code in ${resendIn}s` : 'Send login code'}
        </Button>
        {error && <p className="text-xs text-destructive">{error}</p>}
      </form>
    )
  }

  if (auth.state === 'code_sent') {
    return (
      <form
        className={box}
        onSubmit={(e) => {
          e.preventDefault()
          run('code', { code })
        }}
      >
        <p className="text-xs">
          Enter the code Telegram sent to <span className="font-semibold">{auth.phoneHint}</span> via {auth.codeVia ?? 'Telegram'}.
        </p>
        <Input
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="12345"
          inputMode="numeric"
          autoComplete="one-time-code"
          autoFocus
          className="h-8 text-sm tracking-widest"
        />
        <div className="flex flex-wrap gap-2">
          <Button type="submit" size="sm" className={btn} disabled={busy !== null || !code.trim()}>
            <LogIn className="h-3.5 w-3.5 mr-1" />
            {busy === 'code' ? 'Checking…' : 'Log in'}
          </Button>
          <Button type="button" size="sm" variant="ghost" className={btn} disabled={busy !== null || resendIn > 0} onClick={() => run('send-code', { phone: '' })}>
            {resendIn > 0 ? `Resend in ${resendIn}s` : 'Resend code'}
          </Button>
          <Button type="button" size="sm" variant="ghost" className={btn} disabled={busy !== null} onClick={() => run('cancel')}>
            Cancel
          </Button>
        </div>
        {error && <p className="text-xs text-destructive">{error}</p>}
      </form>
    )
  }

  // password_required
  return (
    <form
      className={box}
      autoComplete="off"
      onSubmit={(e) => {
        e.preventDefault()
        run('password', { password })
      }}
    >
      <p className="text-xs">This account has two-step verification. Enter your Telegram password.</p>
      <Input
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        autoComplete="current-password"
        autoFocus
        className="h-8 text-sm"
      />
      <div className="flex gap-2">
        <Button type="submit" size="sm" className={btn} disabled={busy !== null || !password}>
          <LogIn className="h-3.5 w-3.5 mr-1" />
          {busy === 'password' ? 'Checking…' : 'Continue'}
        </Button>
        <Button type="button" size="sm" variant="ghost" className={btn} disabled={busy !== null} onClick={() => run('cancel')}>
          Cancel
        </Button>
      </div>
      {error && <p className="text-xs text-destructive">{error}</p>}
    </form>
  )
}

function ConnectionCard({
  c,
  running,
  onAction,
  onChanged,
}: {
  c: ConnectionView
  running: ConnectionAction | null
  onAction: (id: ConnectionAction, label: string) => void
  onChanged: () => void
}) {
  const [open, setOpen] = useState(false)
  const Icon = ICONS[c.key] ?? Link2
  const s = STATUS[c.disabled ? 'off' : c.status]
  const hasMore = c.details.length > 0 || !!c.table

  return (
    <div className={cn('rounded-xl border bg-card shadow-sm flex flex-col', c.disabled && 'opacity-60')}>
      <div className="p-3 md:p-4 flex items-start gap-3">
        <div className={cn('w-9 h-9 rounded-lg flex items-center justify-center shrink-0', s.icon)}>
          <Icon className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-bold truncate">{c.name}</p>
            <span className={cn('text-[10px] font-bold px-2 py-0.5 rounded-md shrink-0', s.badge)}>
              {c.disabled ? 'HIDDEN' : s.label}
            </span>
          </div>
          <p className="text-[10px] font-bold uppercase text-muted-foreground">{c.role}</p>
          <p className="text-xs text-muted-foreground mt-1.5 break-words">{c.summary}</p>
        </div>
      </div>

      {!c.disabled && c.issues.length > 0 && (
        <ul className="mx-3 md:mx-4 mb-3 space-y-1.5">
          {c.issues.map((issue) => (
            <li
              key={issue}
              className={cn(
                'text-xs rounded-md px-2.5 py-1.5 flex gap-2',
                c.status === 'down' ? 'bg-destructive/10 text-destructive' : 'bg-gold/10 text-gold'
              )}
            >
              <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
              <span className="break-words">{issue}</span>
            </li>
          ))}
        </ul>
      )}

      {c.telegramAuth && <TelegramAuthPanel auth={c.telegramAuth} onChanged={onChanged} />}

      {open && hasMore && (
        <div className="mx-3 md:mx-4 mb-3 space-y-3">
          {c.details.length > 0 && (
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 rounded-lg bg-muted/40 p-3">
              {c.details.map((d) => (
                <div key={d.label} className="min-w-0">
                  <dt className="text-[10px] font-bold uppercase text-muted-foreground">{d.label}</dt>
                  <dd className={cn('text-xs font-semibold break-words', d.tone && TONE[d.tone])}>{d.value}</dd>
                </div>
              ))}
            </dl>
          )}
          {c.table && (
            <div>
              <p className="text-[10px] font-bold uppercase text-muted-foreground mb-1">{c.table.title}</p>
              <div className="overflow-x-auto rounded-lg border">
                <table className="w-full text-xs">
                  <thead className="bg-muted/40">
                    <tr>
                      {c.table.columns.map((col) => (
                        <th key={col} className="text-left font-bold px-2.5 py-1.5 whitespace-nowrap">{col}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {c.table.rows.map((row, i) => (
                      <tr key={i} className="border-t">
                        {row.cells.map((cell, j) => (
                          <td
                            key={j}
                            className={cn('px-2.5 py-1.5', j === 0 ? 'font-semibold' : 'whitespace-nowrap', j > 0 && row.tone && TONE[row.tone])}
                          >
                            {cell}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      <div className="mt-auto flex flex-wrap items-center gap-1.5 border-t px-3 md:px-4 py-2">
        {hasMore && (
          <Button variant="ghost" size="sm" onClick={() => setOpen(!open)} className="h-7 px-2 text-[10px] font-bold uppercase">
            {open ? <ChevronUp className="h-3 w-3 mr-1" /> : <ChevronDown className="h-3 w-3 mr-1" />}
            Details
          </Button>
        )}
        {c.actions.map((a) => (
          <Button
            key={a.id}
            variant="ghost"
            size="sm"
            disabled={running !== null}
            onClick={() => onAction(a.id, a.label)}
            className="h-7 px-2 text-[10px] font-bold uppercase text-primary"
          >
            <RefreshCw className={cn('h-3 w-3 mr-1', running === a.id && 'animate-spin')} />
            {a.label}
          </Button>
        ))}
        <div className="ml-auto flex items-center gap-1">
          {c.links.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className="inline-flex items-center h-7 px-2 rounded-md text-[10px] font-bold uppercase text-muted-foreground hover:text-foreground hover:bg-muted"
            >
              {l.label}
              <ArrowUpRight className="h-3 w-3 ml-0.5" />
            </Link>
          ))}
          {c.latencyMs != null && (
            <span className="text-[10px] font-bold text-muted-foreground tabular-nums pl-1">{c.latencyMs}ms</span>
          )}
        </div>
      </div>
    </div>
  )
}

function ConnectionContent({ asTab = false }: { asTab?: boolean }) {
  const [data, setData] = useState<ConnectionsResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState<ConnectionAction | null>(null)
  const [now, setNow] = useState(Date.now())

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/connections', { cache: 'no-store' })
      const body = await res.json().catch(() => null)
      if (!res.ok || !body) throw new Error(body?.error || `HTTP ${res.status}`)
      setData(body)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load connections')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    const poll = setInterval(load, POLL_MS)
    const tick = setInterval(() => setNow(Date.now()), 1000)
    return () => {
      clearInterval(poll)
      clearInterval(tick)
    }
  }, [load])

  const runAction = async (id: ConnectionAction, label: string) => {
    setRunning(id)
    try {
      const res = await fetch('/api/connections/action', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: id }),
      })
      const body = await res.json().catch(() => null)
      if (!res.ok) throw new Error(body?.error || `HTTP ${res.status}`)
      if (id === 'telegram.resync') {
        toast.success(`Listening to ${body.listening} channel(s)${body.unresolved ? ` · ${body.unresolved} could not be resolved` : ''}`)
      } else if (id === 'news.refresh') {
        toast.success(`News fetched: ${body.events} events this week`)
      } else {
        toast.success(`Health checks ran: ${body.overall}`)
      }
      await load()
    } catch (e) {
      toast.error(`${label} failed: ${e instanceof Error ? e.message : 'unknown error'}`)
    } finally {
      setRunning(null)
    }
  }

  const active = data?.connections.filter((c) => !c.disabled) ?? []
  const attention = active.filter((c) => c.issues.length > 0 && (c.status === 'down' || c.status === 'warn'))
  const okCount = active.filter((c) => c.status === 'ok' || c.status === 'off').length
  const overall: ConnStatus = error && !data ? 'down' : data?.overall ?? 'ok'
  const checkedAgo = secondsAgo(data?.generatedAt, now)

  const heroTone =
    overall === 'down'
      ? 'bg-destructive/10 border-destructive/20'
      : overall === 'warn'
        ? 'bg-gold/10 border-gold/20'
        : 'bg-success/10 border-success/20'
  const HeroIcon = overall === 'down' ? XCircle : overall === 'warn' ? AlertTriangle : ShieldCheck

  const refreshButton = (
    <Button variant="ghost" size="sm" onClick={load} disabled={loading} className="h-7 text-[10px] font-bold uppercase">
      <RefreshCw className={cn('h-3 w-3 mr-1.5', loading && 'animate-spin')} />
      Check now
    </Button>
  )

  return (
    <div className={asTab ? 'flex flex-col pb-10' : 'flex min-h-full flex-col pb-10'}>
      {!asTab && (
        <MobilePageHeader title="Connections" subtitle="Live service checks" hidden icon={<Link2 className="h-5 w-5" />} />
      )}
      {!asTab && (
        <header className="hidden md:flex sticky top-0 z-40 w-full tech-header">
          <div className="max-w-[1800px] w-full mx-auto flex h-14 items-center px-6 gap-3">
            <div className="p-1.5 rounded-lg bg-primary/10 border border-primary/20">
              <Link2 className="h-5 w-5 text-primary" />
            </div>
            <div className="flex flex-col">
              <h1 className="text-sm font-bold text-foreground leading-none">Connections</h1>
              <p className="text-[10px] text-[#6b7288] font-bold uppercase tracking-wider mt-1">Live service checks</p>
            </div>
            <div className="ml-auto flex items-center gap-3">
              {checkedAgo != null && (
                <span className="text-[10px] font-bold uppercase text-muted-foreground">Checked {checkedAgo}s ago</span>
              )}
              {refreshButton}
            </div>
          </div>
        </header>
      )}

      <main className="flex-1 px-3 md:px-4 py-4 md:py-6 max-w-7xl mx-auto w-full space-y-4 md:space-y-6">
        <ProviderSwitcher onSwitched={() => { void load() }} />
        {/* Overall + what needs attention */}
        <div className={cn('rounded-xl p-4 md:p-5 border shadow-sm', heroTone)}>
          <div className="flex items-center gap-4">
            <div
              className={cn(
                'w-11 h-11 rounded-lg flex items-center justify-center shrink-0',
                STATUS[overall].icon
              )}
            >
              <HeroIcon className="h-6 w-6" />
            </div>
            <div className="min-w-0 flex-1">
              <h2 className="text-base md:text-lg font-bold tracking-tight">
                {!data && loading
                  ? 'Checking connections…'
                  : error && !data
                    ? 'Could not run checks'
                    : overall === 'ok'
                      ? 'Everything is connected'
                      : overall === 'warn'
                        ? `${attention.length} connection${attention.length === 1 ? '' : 's'} need${attention.length === 1 ? 's' : ''} attention`
                        : 'Something is down'}
              </h2>
              <p className="text-xs font-medium text-muted-foreground">
                {error && !data
                  ? error
                  : data
                    ? `${okCount} of ${active.length} healthy · checks run live every ${POLL_MS / 1000}s`
                    : ''}
              </p>
            </div>
            <div className="md:hidden">{refreshButton}</div>
          </div>

          {attention.length > 0 && (
            <ul className="mt-4 space-y-1.5">
              {attention.flatMap((c) =>
                c.issues.map((issue) => (
                  <li key={c.key + issue} className="flex gap-2 text-xs">
                    <span className={cn('w-1.5 h-1.5 rounded-full mt-1.5 shrink-0', STATUS[c.status].dot)} />
                    <span>
                      <span className="font-bold">{c.name}:</span> {issue}
                    </span>
                  </li>
                ))
              )}
            </ul>
          )}
          {error && data && (
            <p className="mt-3 text-xs text-destructive">Last refresh failed ({error}) — showing the previous result.</p>
          )}
        </div>

        <div className="grid gap-3 md:gap-4 grid-cols-1 md:grid-cols-2 xl:grid-cols-3">
          {data?.connections
            .slice()
            .sort((a, b) => Number(!!a.disabled) - Number(!!b.disabled))
            .map((c) => (
              <ConnectionCard key={c.key} c={c} running={running} onAction={runAction} onChanged={load} />
            ))}
        </div>

        {data && data.connections.some((c) => c.disabled) && (
          <p className="text-[11px] text-muted-foreground flex items-center gap-1.5">
            <CircleOff className="h-3.5 w-3.5" />
            Hidden connections are still checked but don&apos;t count toward the overall status. Change this in{' '}
            <Link href="/settings" className="underline">Settings</Link>.
          </p>
        )}
      </main>
    </div>
  )
}

export default function ConnectionPage() {
  return <ConnectionContent />
}
