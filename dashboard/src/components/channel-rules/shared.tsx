'use client'

import { useMemo, useState } from 'react'
import { formatDistanceToNowStrict } from 'date-fns'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { ACTIONS, paramsSummary, type ActionType } from '@/lib/channelRules'
import {
  Ban, Bot, CircleSlash, Crosshair, Lock, Loader2, Scissors, ShieldCheck, Target, XOctagon,
} from 'lucide-react'

export interface ChannelOption {
  id: string
  title: string
}

export const normalizeChannelId = (id: string): string => {
  const t = id.trim()
  if (t.startsWith('-100')) return t
  if (t.startsWith('-')) return `-100${t.substring(1)}`
  return `-100${t}`
}

export const agoIso = (iso: string | null) => (iso ? `${formatDistanceToNowStrict(new Date(iso))} ago` : 'never')

export const ACTION_ICON: Record<ActionType, typeof Bot> = {
  IGNORE: CircleSlash,
  CLOSE: XOctagon,
  PARTIAL_CLOSE: Scissors,
  BREAKEVEN: ShieldCheck,
  LOCK_PROFIT: Lock,
  MODIFY_SL: Crosshair,
  MODIFY_TP: Target,
  CANCEL: Ban,
  AI_MANAGED: Bot,
}

export const TONE: Record<string, string> = {
  muted: 'bg-muted text-muted-foreground border-border',
  danger: 'bg-destructive/10 text-destructive border-destructive/25',
  success: 'bg-success/10 text-success border-success/25',
  primary: 'bg-primary/10 text-primary border-primary/25',
  warning: 'bg-gold/10 text-gold border-gold/25',
}

export function ActionPill({
  actionType,
  params,
  className,
}: {
  actionType: ActionType
  params?: Record<string, unknown>
  className?: string
}) {
  const meta = ACTIONS[actionType]
  if (!meta) {
    return <span className={cn('text-[10px] font-bold px-2 py-0.5 rounded-md border', TONE.muted, className)}>{actionType}</span>
  }
  const Icon = ACTION_ICON[actionType]
  const extra = params ? paramsSummary(actionType, params) : null
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wide px-2 py-0.5 rounded-md border whitespace-nowrap',
        TONE[meta.tone],
        className,
      )}
    >
      <Icon className="h-3 w-3" />
      {meta.label}
      {extra && <span className="normal-case font-semibold opacity-80">· {extra}</span>}
    </span>
  )
}

export function ChannelPicker({
  value,
  onChange,
  channels,
  loading,
  placeholder = 'Select channel…',
  allowAll,
  invalid,
  className,
}: {
  value: string
  onChange: (v: string) => void
  channels: ChannelOption[]
  loading?: boolean
  placeholder?: string
  allowAll?: boolean
  invalid?: boolean
  className?: string
}) {
  const [search, setSearch] = useState('')
  const filtered = useMemo(
    () => (search ? channels.filter((c) => c.title.toLowerCase().includes(search.toLowerCase())) : channels),
    [channels, search],
  )
  const selected = channels.find((c) => c.id === value)
  const ALL = '__all__'

  return (
    <Select
      value={value || (allowAll ? ALL : '')}
      onValueChange={(v) => {
        onChange(v === ALL ? '' : v)
        setSearch('')
      }}
    >
      <SelectTrigger className={cn('h-9 text-xs', invalid && 'border-destructive/50', className)}>
        <SelectValue placeholder={placeholder}>{selected ? selected.title : allowAll && !value ? 'All channels' : undefined}</SelectValue>
      </SelectTrigger>
      <SelectContent>
        <div className="p-2 border-b sticky top-0 bg-popover z-10">
          <Input
            placeholder="Search channels…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => e.stopPropagation()}
            className="h-7 text-xs"
          />
        </div>
        <div className="max-h-64 overflow-y-auto">
          {allowAll && !search && (
            <SelectItem value={ALL} className="text-xs font-semibold">All channels</SelectItem>
          )}
          {loading ? (
            <div className="p-4 flex justify-center"><Loader2 className="h-4 w-4 animate-spin" /></div>
          ) : filtered.length === 0 ? (
            <div className="p-4 text-center text-xs text-muted-foreground">
              {channels.length === 0 ? 'No channels loaded yet' : 'No channels found'}
            </div>
          ) : (
            filtered.map((c) => (
              <SelectItem key={c.id} value={c.id} className="text-xs">{c.title}</SelectItem>
            ))
          )}
        </div>
      </SelectContent>
    </Select>
  )
}

export function EmptyState({ icon: Icon, title, children }: { icon: typeof Bot; title: string; children?: React.ReactNode }) {
  return (
    <div className="text-center py-14 px-4">
      <div className="w-14 h-14 bg-muted rounded-2xl flex items-center justify-center mx-auto mb-3 border border-border">
        <Icon className="h-7 w-7 text-muted-foreground/60" />
      </div>
      <h3 className="text-sm font-semibold text-foreground/80 mb-1">{title}</h3>
      {children && <div className="text-xs text-muted-foreground max-w-sm mx-auto">{children}</div>}
    </div>
  )
}
