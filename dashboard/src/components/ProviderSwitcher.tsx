'use client'

import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Cloud, Server, RefreshCw, ArrowRightLeft } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

type Provider = 'metaapi' | 'mt5rest'

interface BotProviderStatus {
  active: Provider | null
  configured: Provider
  connected: boolean
  healthy: boolean
  live_reads: boolean
  last_switch: { from: string; to: string; reason: string; at: number } | null
}

interface ProviderResponse {
  provider: Provider
  bot: BotProviderStatus | null
}

const LABEL: Record<Provider, string> = { metaapi: 'MetaAPI Cloud', mt5rest: 'MT5 REST (self-hosted)' }
const ICON: Record<Provider, typeof Cloud> = { metaapi: Cloud, mt5rest: Server }

/** Shows the provider the bot is trading on and switches it live (no restart). */
export default function ProviderSwitcher({ onSwitched }: { onSwitched?: () => void }) {
  const [data, setData] = useState<ProviderResponse | null>(null)
  const [busy, setBusy] = useState<Provider | null>(null)
  const [confirm, setConfirm] = useState<Provider | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const res = await fetch('/api/provider', { cache: 'no-store' })
      if (res.ok) setData(await res.json())
    } catch {
      // keep the last known state
    }
  }, [])

  useEffect(() => {
    load()
    const id = setInterval(load, 15_000)
    return () => clearInterval(id)
  }, [load])

  const active = data?.bot?.active ?? data?.provider ?? null
  const other: Provider | null = active ? (active === 'metaapi' ? 'mt5rest' : 'metaapi') : null

  async function doSwitch(target: Provider) {
    setBusy(target)
    setError(null)
    try {
      const res = await fetch('/api/provider/switch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider: target }),
      })
      const body = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(body?.error || `Switch failed (HTTP ${res.status})`)
        toast.error(body?.error || 'Provider switch failed - previous provider kept')
        return
      }
      toast.success(`Now trading on ${LABEL[target]}`)
      setConfirm(null)
      await load()
      onSwitched?.()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Switch failed')
    } finally {
      setBusy(null)
    }
  }

  const ActiveIcon = active ? ICON[active] : Cloud
  const bot = data?.bot
  const lastSwitch = bot?.last_switch

  return (
    <div className="rounded-2xl border bg-card p-4 space-y-3">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className={cn('rounded-xl p-2', bot?.healthy ? 'bg-success/10 text-success' : 'bg-gold/10 text-gold')}>
            <ActiveIcon className="h-5 w-5" />
          </div>
          <div>
            <div className="text-xs uppercase tracking-wide text-muted-foreground">Trading provider</div>
            <div className="font-semibold">{active ? LABEL[active] : 'Loading…'}</div>
            <div className="text-xs text-muted-foreground">
              {bot
                ? `${bot.connected ? 'connected' : 'disconnected'} · ${bot.healthy ? 'healthy' : 'unhealthy'}${bot.live_reads ? ' · live streamed reads' : ''}`
                : 'bot status unavailable'}
            </div>
          </div>
        </div>
        <Button variant="ghost" size="sm" onClick={load} aria-label="Refresh provider status">
          <RefreshCw className="h-4 w-4" />
        </Button>
      </div>

      {other && confirm !== other && (
        <Button variant="outline" size="sm" disabled={!!busy} onClick={() => { setConfirm(other); setError(null) }}>
          <ArrowRightLeft className="mr-2 h-4 w-4" />
          Switch to {LABEL[other]}
        </Button>
      )}

      {other && confirm === other && (
        <div className="rounded-xl border border-gold/40 bg-gold/5 p-3 space-y-2 text-sm">
          <p>
            Switch trading to <strong>{LABEL[other]}</strong> now? It is a <strong>different account</strong>: the new provider
            connects first (if it fails, nothing changes), and the switch is refused while the bot still has open trades or
            pending orders. There is no automatic fallback — only one provider trades at a time.
          </p>
          {error && <p className="text-destructive text-xs">{error}</p>}
          <div className="flex gap-2">
            <Button size="sm" disabled={!!busy} onClick={() => doSwitch(other)}>
              {busy ? 'Switching…' : 'Confirm switch'}
            </Button>
            <Button size="sm" variant="ghost" disabled={!!busy} onClick={() => { setConfirm(null); setError(null) }}>
              Cancel
            </Button>
          </div>
        </div>
      )}

      {lastSwitch && (
        <div className="text-xs text-muted-foreground">
          Last switch: {lastSwitch.from} → {lastSwitch.to} ({lastSwitch.reason}) · {new Date(lastSwitch.at * 1000).toLocaleString()}
        </div>
      )}
    </div>
  )
}
