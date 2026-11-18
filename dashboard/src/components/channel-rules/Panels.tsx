'use client'

import { useEffect, useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { cn } from '@/lib/utils'
import { ACTIONS, firstMatch, type ActionType, type ChannelRule } from '@/lib/channelRules'
import { ActionPill, ChannelPicker, EmptyState, agoIso, type ChannelOption } from './shared'
import {
  Activity, AlertTriangle, BookOpen, CheckCircle2, CircleSlash, Lightbulb, Loader2, MessageSquare, Plus, Search, XCircle,
} from 'lucide-react'
import TelegramText from '@/components/TelegramText'
import { telegramPlainText } from '@/lib/telegramMarkdown'

export interface ActivityItem {
  id: string
  createdAt: string
  channelId: string
  replyText: string
  symbol: string | null
  username: string | null
  actionType: string | null
  actionTaken: boolean
  actionSuccess: boolean
  actionResult: string | null
  processingError: string | null
  aiParsed: boolean
  rule: { id: string; name: string; actionType: string; aiAction: string | null; followed: boolean } | null
}

export interface Suggestion {
  id: string
  channelId: string
  example: string
  suggestedPattern: string
  actionType: ActionType
  learnedAction: string | null
  occurrenceCount: number
}

export type CreateFrom = (init: { channelId: string; ruleName?: string; replyPattern?: string; actionType?: ActionType; sample?: string; patternType?: 'REGEX' | 'EXACT' }) => void

function outcome(a: ActivityItem): { label: string; tone: 'ok' | 'warn' | 'bad' | 'muted'; detail?: string | null } {
  if (a.processingError) return { label: 'Error', tone: 'bad', detail: a.processingError }
  if (a.actionType === 'RULE_IGNORED') return { label: 'Ignored by rule', tone: 'muted' }
  if (a.rule && !a.rule.followed) {
    return { label: a.rule.aiAction ? `AI chose ${a.rule.aiAction}` : 'AI chose no action', tone: 'warn', detail: a.actionResult }
  }
  if (a.actionType === 'STATUS_MESSAGE') return { label: 'No action (status message)', tone: 'muted' }
  if (a.actionTaken && a.actionSuccess) return { label: a.rule?.aiAction ? `Done · ${a.rule.aiAction}` : `Done${a.actionType ? ` · ${a.actionType}` : ''}`, tone: 'ok', detail: a.actionResult }
  if (!a.processingError && !a.actionTaken && a.actionResult) return { label: 'Not executed', tone: 'bad', detail: a.actionResult }
  return { label: a.actionType ?? 'Received', tone: 'muted', detail: a.actionResult }
}

const OUTCOME_STYLE = {
  ok: 'text-success',
  warn: 'text-gold',
  bad: 'text-destructive',
  muted: 'text-muted-foreground',
}
const OUTCOME_ICON = { ok: CheckCircle2, warn: AlertTriangle, bad: XCircle, muted: CircleSlash }

export function ActivityPanel({
  channels,
  channelTitle,
}: {
  channels: ChannelOption[]
  channelTitle: (id: string) => string
}) {
  const [items, setItems] = useState<ActivityItem[] | null>(null)
  const [channelId, setChannelId] = useState('')
  const [rulesOnly, setRulesOnly] = useState(true)

  useEffect(() => {
    let cancelled = false
    setItems(null)
    const q = new URLSearchParams()
    if (channelId) q.set('channelId', channelId)
    if (rulesOnly) q.set('rulesOnly', '1')
    fetch(`/api/channel-behavior/activity?${q}`)
      .then((r) => (r.ok ? r.json() : { activity: [] }))
      .then((d) => !cancelled && setItems(d.activity || []))
      .catch(() => !cancelled && setItems([]))
    return () => {
      cancelled = true
    }
  }, [channelId, rulesOnly])

  return (
    <div>
      <div className="flex items-center gap-2 flex-wrap px-4 py-3 border-b border-border">
        <div className="w-60"><ChannelPicker value={channelId} onChange={setChannelId} channels={channels} allowAll /></div>
        <label className="flex items-center gap-2 text-xs font-semibold cursor-pointer">
          <Switch checked={rulesOnly} onCheckedChange={setRulesOnly} />
          Rule hits only
        </label>
        <span className="ml-auto text-[10px] text-muted-foreground">Last 100 replies</span>
      </div>
      {items === null ? (
        <div className="py-14 flex justify-center"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
      ) : items.length === 0 ? (
        <EmptyState icon={Activity} title={rulesOnly ? 'No rule hits yet' : 'No replies yet'}>
          {rulesOnly
            ? 'Every reply that matches one of your rules shows up here with what the bot did about it.'
            : 'Replies to signals appear here as the bot handles them.'}
        </EmptyState>
      ) : (
        <ul className="divide-y divide-border">
          {items.map((a) => {
            const o = outcome(a)
            const Icon = OUTCOME_ICON[o.tone]
            return (
              <li key={a.id} className="px-4 py-3 flex gap-3">
                <Icon className={cn('h-4 w-4 mt-0.5 shrink-0', OUTCOME_STYLE[o.tone])} />
                <div className="flex-1 min-w-0 space-y-1">
                  <TelegramText text={a.replyText} className="text-sm" />
                  <div className="flex items-center gap-x-3 gap-y-1 flex-wrap text-[11px] text-muted-foreground">
                    <span className={cn('font-bold', OUTCOME_STYLE[o.tone])}>{o.label}</span>
                    {a.rule && (
                      <span className="inline-flex items-center gap-1">
                        rule <span className="font-semibold text-foreground">“{a.rule.name}”</span>
                        {a.rule.actionType in ACTIONS && <ActionPill actionType={a.rule.actionType as ActionType} className="scale-90 origin-left" />}
                      </span>
                    )}
                    <span>{channelTitle(a.channelId)}</span>
                    {a.symbol && <span className="font-mono">{a.symbol}</span>}
                    <span>{agoIso(a.createdAt)}</span>
                  </div>
                  {o.detail && <p className="text-[11px] text-muted-foreground/80 break-words line-clamp-2">{o.detail}</p>}
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

export function SuggestionsPanel({
  suggestions,
  loading,
  channelTitle,
  onCreate,
}: {
  suggestions: Suggestion[]
  loading: boolean
  channelTitle: (id: string) => string
  onCreate: CreateFrom
}) {
  if (loading && suggestions.length === 0) {
    return <div className="py-14 flex justify-center"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
  }
  if (suggestions.length === 0) {
    return (
      <EmptyState icon={Lightbulb} title="No suggestions right now">
        Suggestions come from close/move messages a channel has posted 3+ times that no rule covers yet.
      </EmptyState>
    )
  }
  return (
    <ul className="divide-y divide-border">
      {suggestions.map((s) => (
        <li key={s.id} className="px-4 py-3 flex items-start gap-3">
          <div className="flex-1 min-w-0 space-y-1.5">
            <TelegramText text={s.example} className="text-sm" />
            <div className="flex items-center gap-2 flex-wrap text-[11px] text-muted-foreground">
              <span className="font-bold text-foreground tabular-nums">seen {s.occurrenceCount}×</span>
              <span>{channelTitle(s.channelId)}</span>
              <span>→</span>
              <ActionPill actionType={s.actionType} />
            </div>
          </div>
          <Button
            size="sm"
            variant="outline"
            className="h-8 text-xs shrink-0"
            onClick={() =>
              onCreate({
                channelId: s.channelId,
                ruleName: `${ACTIONS[s.actionType].label}: ${telegramPlainText(s.example).trim().slice(0, 28)}${telegramPlainText(s.example).trim().length > 28 ? '…' : ''}`,
                replyPattern: s.suggestedPattern,
                actionType: s.actionType,
                sample: s.example,
              })
            }
          >
            <Plus className="h-3.5 w-3.5 mr-1" />Make rule
          </Button>
        </li>
      ))}
    </ul>
  )
}

interface Learned {
  id: string
  messagePattern: string
  messageType: string
  action: string | null
  occurrenceCount: number
  createdAt: string
}

export function LearnedPanel({
  channels,
  rules,
  defaultChannel,
  onCreate,
}: {
  channels: ChannelOption[]
  rules: ChannelRule[]
  defaultChannel: string
  onCreate: CreateFrom
}) {
  const [channelId, setChannelId] = useState(defaultChannel)
  const [rows, setRows] = useState<Learned[] | null>(null)
  const [q, setQ] = useState('')

  useEffect(() => {
    if (!channelId && defaultChannel) setChannelId(defaultChannel)
  }, [defaultChannel, channelId])

  useEffect(() => {
    if (!channelId) return
    let cancelled = false
    setRows(null)
    fetch(`/api/channel-behavior/analytics/${encodeURIComponent(channelId)}`)
      .then((r) => (r.ok ? r.json() : { analytics: [] }))
      .then((d) => !cancelled && setRows(d.analytics || []))
      .catch(() => !cancelled && setRows([]))
    return () => {
      cancelled = true
    }
  }, [channelId])

  const visible = useMemo(
    () => (rows ?? []).filter((r) => !q || r.messagePattern.toLowerCase().includes(q.toLowerCase())),
    [rows, q],
  )

  return (
    <div>
      <div className="flex items-center gap-2 flex-wrap px-4 py-3 border-b border-border">
        <div className="w-60"><ChannelPicker value={channelId} onChange={setChannelId} channels={channels} /></div>
        <div className="relative flex-1 min-w-[160px] max-w-xs">
          <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter messages…" className="pl-8 h-9 text-xs" />
        </div>
        {rows && <span className="ml-auto text-[10px] text-muted-foreground tabular-nums">{visible.length} patterns</span>}
      </div>
      {!channelId ? (
        <EmptyState icon={BookOpen} title="Pick a channel">See every message pattern the bot has learned from it, and which rule catches each.</EmptyState>
      ) : rows === null ? (
        <div className="py-14 flex justify-center"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
      ) : visible.length === 0 ? (
        <EmptyState icon={MessageSquare} title="Nothing learned yet" />
      ) : (
        <ul className="divide-y divide-border">
          {visible.map((r) => {
            const hit = firstMatch(r.messagePattern, channelId, rules)
            return (
              <li key={r.id} className="px-4 py-2.5 flex items-center gap-3">
                <span className="text-[11px] font-bold tabular-nums text-muted-foreground w-10 text-right shrink-0">{r.occurrenceCount}×</span>
                <div className="flex-1 min-w-0">
                  <TelegramText text={r.messagePattern} inline className="text-xs line-clamp-2" />
                  <div className="flex items-center gap-2 text-[10px] text-muted-foreground mt-0.5">
                    <span className="uppercase font-bold tracking-wide">{r.messageType}</span>
                    {r.action && <span className="uppercase font-bold tracking-wide text-primary">{r.action}</span>}
                  </div>
                </div>
                {hit ? (
                  <span className="hidden sm:inline-flex items-center gap-1.5 text-[11px] shrink-0 max-w-[45%]">
                    <span className="truncate font-semibold">{hit.ruleName}</span>
                    <ActionPill actionType={hit.actionType} params={hit.actionParams} />
                  </span>
                ) : (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-7 text-[11px] shrink-0"
                    onClick={() => onCreate({ channelId, sample: r.messagePattern, patternType: 'REGEX' })}
                  >
                    <Plus className="h-3 w-3 mr-1" />Rule
                  </Button>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
