'use client'

import { useEffect, useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Switch } from '@/components/ui/switch'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { cn } from '@/lib/utils'
import { useToast } from '@/hooks/use-toast'
import {
  ACTIONS, ACTION_TYPES, PATTERN_TYPES, byPriority, matchesRule, patternError,
  type ActionType, type ChannelRule, type PatternType,
} from '@/lib/channelRules'
import { ACTION_ICON, ActionPill, ChannelPicker, TONE, type ChannelOption } from './shared'
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, FlaskConical, Loader2, Sparkles, X } from 'lucide-react'
import TelegramText from '@/components/TelegramText'

export interface RuleDraft {
  channelId: string
  ruleName: string
  replyPattern: string
  patternType: PatternType
  isCaseSensitive: boolean
  actionType: ActionType | ''
  actionParams: Record<string, string>
  conditions: string
  priority: number
  description: string
  isEnabled: boolean
}

export const emptyDraft = (channelId = ''): RuleDraft => ({
  channelId,
  ruleName: '',
  replyPattern: '',
  patternType: 'REGEX',
  isCaseSensitive: false,
  actionType: '',
  actionParams: {},
  conditions: '',
  priority: 10,
  description: '',
  isEnabled: true,
})

export const draftFromRule = (r: ChannelRule): RuleDraft => ({
  channelId: r.channelId,
  ruleName: r.ruleName,
  replyPattern: r.replyPattern,
  patternType: r.patternType,
  isCaseSensitive: r.isCaseSensitive,
  actionType: r.actionType,
  actionParams: Object.fromEntries(Object.entries(r.actionParams).map(([k, v]) => [k, String(v)])),
  conditions: Object.keys(r.conditions).length ? JSON.stringify(r.conditions, null, 2) : '',
  priority: r.priority,
  description: r.description ?? '',
  isEnabled: r.isEnabled,
})

interface Learned {
  id: string
  messagePattern: string
  occurrenceCount: number
}

const learnedCache = new Map<string, Learned[]>()

export default function RuleEditor({
  open,
  onOpenChange,
  initial,
  editingId,
  channels,
  channelsLoading,
  rules,
  sampleText,
  onSaved,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  initial: RuleDraft
  editingId: string | null
  channels: ChannelOption[]
  channelsLoading: boolean
  rules: ChannelRule[]
  sampleText?: string
  onSaved: () => void
}) {
  const { toast } = useToast()
  const [draft, setDraft] = useState<RuleDraft>(initial)
  const [sample, setSample] = useState(sampleText ?? '')
  const [saving, setSaving] = useState(false)
  const [aiText, setAiText] = useState('')
  const [aiOpen, setAiOpen] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [advanced, setAdvanced] = useState(false)
  const [learned, setLearned] = useState<Learned[] | null>(null)

  useEffect(() => {
    if (!open) return
    setDraft(initial)
    setSample(sampleText ?? '')
    setAiOpen(false)
    setAiText('')
    setAdvanced(!!initial.conditions)
  }, [open, initial, sampleText])

  // The channel's learned messages: a live check of what the pattern will catch
  useEffect(() => {
    const id = draft.channelId
    if (!open || !id) {
      setLearned(null)
      return
    }
    if (learnedCache.has(id)) {
      setLearned(learnedCache.get(id)!)
      return
    }
    setLearned(null)
    let cancelled = false
    fetch(`/api/channel-behavior/analytics/${encodeURIComponent(id)}`)
      .then((r) => (r.ok ? r.json() : { analytics: [] }))
      .then((d) => {
        const rows: Learned[] = (d.analytics || []).map((a: Learned) => ({
          id: a.id, messagePattern: a.messagePattern, occurrenceCount: a.occurrenceCount,
        }))
        learnedCache.set(id, rows)
        if (!cancelled) setLearned(rows)
      })
      .catch(() => !cancelled && setLearned([]))
    return () => {
      cancelled = true
    }
  }, [open, draft.channelId])

  const set = <K extends keyof RuleDraft>(k: K, v: RuleDraft[K]) => setDraft((d) => ({ ...d, [k]: v }))

  const pErr = draft.replyPattern ? patternError(draft.replyPattern, draft.patternType) : null
  const condErr = useMemo(() => {
    if (!draft.conditions.trim()) return null
    try {
      const v = JSON.parse(draft.conditions)
      return v && typeof v === 'object' && !Array.isArray(v) ? null : 'Must be a JSON object'
    } catch {
      return 'Invalid JSON'
    }
  }, [draft.conditions])

  const matchable = { replyPattern: draft.replyPattern, patternType: draft.patternType, isCaseSensitive: draft.isCaseSensitive }
  const canTest = !!draft.replyPattern && !pErr

  const learnedHits = useMemo(() => {
    if (!learned || !canTest) return null
    const hits = learned.filter((l) => matchesRule(l.messagePattern, matchable))
    return { hits, occurrences: hits.reduce((n, h) => n + h.occurrenceCount, 0) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [learned, canTest, draft.replyPattern, draft.patternType, draft.isCaseSensitive])

  const sampleMatches = sample.trim() && canTest ? matchesRule(sample, matchable) : null

  // Would another enabled rule on this channel fire before this one?
  const shadowedBy = useMemo(() => {
    if (!sample.trim() || !sampleMatches) return null
    const me = { priority: draft.priority, createdAt: editingId ? rules.find((r) => r.id === editingId)?.createdAt ?? '9' : '9' }
    return (
      rules
        .filter((r) => r.id !== editingId && r.isEnabled && r.channelId === draft.channelId && byPriority(r, me) < 0)
        .sort(byPriority)
        .find((r) => matchesRule(sample, r)) ?? null
    )
  }, [sample, sampleMatches, rules, editingId, draft.channelId, draft.priority])

  const generate = async () => {
    if (!aiText.trim()) return
    setGenerating(true)
    try {
      const res = await fetch('/api/channel-behavior/generate-rule', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ description: aiText }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || data.error || 'Generation failed')
      const r = data.rule
      setDraft((d) => ({
        ...d,
        ruleName: r.ruleName,
        replyPattern: r.replyPattern,
        patternType: r.patternType,
        isCaseSensitive: !!r.isCaseSensitive,
        actionType: r.actionType,
        actionParams: Object.fromEntries(Object.entries(r.actionParams || {}).map(([k, v]) => [k, String(v)])),
        conditions: r.conditions && Object.keys(r.conditions).length ? JSON.stringify(r.conditions, null, 2) : '',
        priority: r.priority ?? d.priority,
        description: r.description || '',
      }))
      if (r.conditions && Object.keys(r.conditions).length) setAdvanced(true)
      setAiOpen(false)
      toast({ title: 'Draft ready', description: 'Review the rule, test it, then save.' })
    } catch (e) {
      toast({ title: 'AI draft failed', description: e instanceof Error ? e.message : String(e), variant: 'destructive' })
    } finally {
      setGenerating(false)
    }
  }

  const save = async () => {
    if (!draft.channelId) return toast({ title: 'Choose a channel', variant: 'destructive' })
    if (!draft.ruleName.trim()) return toast({ title: 'Give the rule a name', variant: 'destructive' })
    if (!draft.actionType) return toast({ title: 'Choose an action', variant: 'destructive' })
    if (draft.actionType === 'AI_MANAGED' && !draft.description.trim()) {
      return toast({ title: 'Add a note', description: '“AI decides” acts on your note — tell it what this channel means.', variant: 'destructive' })
    }
    const err = patternError(draft.replyPattern, draft.patternType)
    if (err) return toast({ title: 'Pattern problem', description: err, variant: 'destructive' })
    if (condErr) return toast({ title: 'Conditions problem', description: condErr, variant: 'destructive' })

    setSaving(true)
    try {
      const body = {
        channelId: draft.channelId,
        channelTitle: channels.find((c) => c.id === draft.channelId)?.title ?? null,
        ruleName: draft.ruleName,
        replyPattern: draft.replyPattern,
        patternType: draft.patternType,
        isCaseSensitive: draft.isCaseSensitive,
        actionType: draft.actionType,
        actionParams: draft.actionParams,
        conditions: draft.conditions.trim() ? JSON.parse(draft.conditions) : null,
        priority: draft.priority,
        description: draft.description,
        isEnabled: draft.isEnabled,
      }
      const res = await fetch(editingId ? `/api/channel-behavior/rules/${editingId}` : '/api/channel-behavior/rules', {
        method: editingId ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error || 'Save failed')
      toast({ title: editingId ? 'Rule updated' : 'Rule created', description: 'Live on the next message — no restart needed.' })
      onSaved()
      onOpenChange(false)
    } catch (e) {
      toast({ title: 'Save failed', description: e instanceof Error ? e.message : String(e), variant: 'destructive' })
    } finally {
      setSaving(false)
    }
  }

  const action = draft.actionType ? ACTIONS[draft.actionType] : null
  const patternHint = PATTERN_TYPES.find((p) => p.value === draft.patternType)?.hint

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-5xl max-h-[92vh] overflow-y-auto p-0 gap-0">
        <DialogHeader className="px-5 pt-5 pb-3 border-b border-border">
          <DialogTitle className="text-base font-bold">{editingId ? 'Edit rule' : 'New rule'}</DialogTitle>
          <DialogDescription className="text-xs">
            When a reply in this channel matches the pattern, the bot treats the action as your instruction.
          </DialogDescription>
        </DialogHeader>

        <div className="grid md:grid-cols-[minmax(0,1fr)_340px]">
          {/* ── form ───────────────────────────────────────────── */}
          <div className="p-5 space-y-5 min-w-0">
            {aiOpen ? (
              <div className="space-y-2 p-3 bg-primary/5 rounded-xl border border-primary/20">
                <div className="flex items-center justify-between">
                  <Label className="text-xs font-bold">Describe the rule in plain words</Label>
                  <button onClick={() => setAiOpen(false)} className="text-muted-foreground hover:text-foreground">
                    <X className="h-4 w-4" />
                  </button>
                </div>
                <Textarea
                  value={aiText}
                  onChange={(e) => setAiText(e.target.value)}
                  placeholder="e.g. When they say 'secure profits' or 'take some off', close 50%"
                  className="min-h-[64px] resize-none text-sm"
                />
                <Button size="sm" onClick={generate} disabled={generating || !aiText.trim()} className="w-full h-8 text-xs">
                  {generating ? <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5 mr-1.5" />}
                  Draft rule with AI
                </Button>
              </div>
            ) : (
              <button
                onClick={() => setAiOpen(true)}
                className="w-full flex items-center justify-center gap-2 h-9 rounded-lg border-2 border-dashed border-primary/30 text-primary text-xs font-bold hover:border-primary/60 hover:bg-primary/5 transition-colors"
              >
                <Sparkles className="h-3.5 w-3.5" /> Draft with AI from a description
              </button>
            )}

            <div className="grid sm:grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label className="text-xs font-bold">Channel</Label>
                <ChannelPicker
                  value={draft.channelId}
                  onChange={(v) => set('channelId', v)}
                  channels={channels}
                  loading={channelsLoading}
                  invalid={!draft.channelId}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="rule-name" className="text-xs font-bold">Name</Label>
                <Input
                  id="rule-name"
                  value={draft.ruleName}
                  onChange={(e) => set('ruleName', e.target.value)}
                  placeholder="e.g. Breakeven on 'BE now'"
                  className="h-9 text-sm"
                />
              </div>
            </div>

            {/* WHEN */}
            <section className="space-y-2">
              <div className="flex items-baseline justify-between">
                <h4 className="text-[10px] font-black uppercase tracking-[0.15em] text-muted-foreground">When a reply matches</h4>
                <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground cursor-pointer">
                  <Switch checked={draft.isCaseSensitive} onCheckedChange={(v) => set('isCaseSensitive', v)} className="scale-75" />
                  Case sensitive
                </label>
              </div>
              <div className="flex gap-1 flex-wrap">
                {PATTERN_TYPES.map((p) => (
                  <button
                    key={p.value}
                    onClick={() => set('patternType', p.value)}
                    className={cn(
                      'px-2.5 h-7 rounded-md text-[11px] font-bold border transition-colors',
                      draft.patternType === p.value
                        ? 'bg-primary text-primary-foreground border-primary'
                        : 'border-border text-muted-foreground hover:text-foreground hover:bg-muted/60',
                    )}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
              <Input
                value={draft.replyPattern}
                onChange={(e) => set('replyPattern', e.target.value)}
                placeholder={draft.patternType === 'REGEX' ? '\\b(be now|breakeven|risk free)\\b' : 'set be'}
                className={cn('font-mono text-sm h-9', pErr && 'border-destructive/60')}
              />
              <p className={cn('text-[11px]', pErr ? 'text-destructive' : 'text-muted-foreground')}>{pErr ?? patternHint}</p>
            </section>

            {/* THEN */}
            <section className="space-y-2">
              <h4 className="text-[10px] font-black uppercase tracking-[0.15em] text-muted-foreground">Then</h4>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                {ACTION_TYPES.map((t) => {
                  const meta = ACTIONS[t]
                  const Icon = ACTION_ICON[t]
                  const active = draft.actionType === t
                  return (
                    <button
                      key={t}
                      onClick={() => set('actionType', t)}
                      className={cn(
                        'text-left p-2.5 rounded-lg border transition-all',
                        active ? 'border-primary ring-2 ring-primary/25 bg-primary/5' : 'border-border hover:border-primary/40 hover:bg-muted/40',
                      )}
                    >
                      <div className="flex items-center gap-1.5">
                        <span className={cn('p-1 rounded-md border', TONE[meta.tone])}>
                          <Icon className="h-3 w-3" />
                        </span>
                        <span className="text-xs font-bold">{meta.label}</span>
                      </div>
                    </button>
                  )
                })}
              </div>
              {action && (
                <div className="rounded-lg bg-muted/40 border border-border p-3 space-y-3">
                  <p className="text-[11px] text-muted-foreground">{action.summary}</p>
                  {action.params.length > 0 && (
                    <div className="flex gap-3 flex-wrap">
                      {action.params.map((f) => (
                        <div key={f.key} className="space-y-1">
                          <Label className="text-[11px] font-bold">{f.label}</Label>
                          <Input
                            type="number"
                            step="any"
                            value={draft.actionParams[f.key] ?? ''}
                            onChange={(e) => set('actionParams', { ...draft.actionParams, [f.key]: e.target.value })}
                            placeholder={f.placeholder}
                            className="h-8 w-36 text-sm font-mono"
                          />
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </section>

            <div className="space-y-1.5">
              <Label htmlFor="rule-note" className="text-xs font-bold">
                Note for the AI {draft.actionType === 'AI_MANAGED' ? <span className="text-destructive">*</span> : <span className="text-muted-foreground font-normal">(optional)</span>}
              </Label>
              <Textarea
                id="rule-note"
                value={draft.description}
                onChange={(e) => set('description', e.target.value)}
                placeholder={draft.actionType === 'AI_MANAGED'
                  ? "e.g. In this channel 'done' means close everything that is still open"
                  : 'Context the AI should know when applying this rule'}
                rows={2}
                className="resize-none text-sm"
              />
            </div>

            <div className="flex items-center gap-4 flex-wrap">
              <div className="flex items-center gap-2">
                <Label htmlFor="rule-priority" className="text-xs font-bold">Priority</Label>
                <Input
                  id="rule-priority"
                  type="number"
                  min={0}
                  max={100}
                  value={draft.priority}
                  onChange={(e) => set('priority', Number(e.target.value) || 0)}
                  className="h-8 w-20 text-sm"
                />
                <span className="text-[11px] text-muted-foreground">0–100, higher wins</span>
              </div>
              <label className="flex items-center gap-2 text-xs font-bold cursor-pointer ml-auto">
                <Switch checked={draft.isEnabled} onCheckedChange={(v) => set('isEnabled', v)} />
                {draft.isEnabled ? 'Active' : 'Paused'}
              </label>
            </div>

            <div>
              <button
                onClick={() => setAdvanced(!advanced)}
                className="flex items-center gap-1 text-[11px] font-bold text-muted-foreground hover:text-foreground"
              >
                {advanced ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                Conditions (advanced)
              </button>
              {advanced && (
                <div className="mt-2 space-y-1">
                  <Textarea
                    value={draft.conditions}
                    onChange={(e) => set('conditions', e.target.value)}
                    placeholder='{"min_profit_pips": 20}'
                    rows={3}
                    className={cn('font-mono text-xs resize-none', condErr && 'border-destructive/60')}
                  />
                  <p className={cn('text-[11px]', condErr ? 'text-destructive' : 'text-muted-foreground')}>
                    {condErr ?? 'The AI checks these against live positions before acting. Leave empty for always.'}
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* ── live preview ───────────────────────────────────── */}
          <aside className="border-t md:border-t-0 md:border-l border-border bg-muted/20 p-5 space-y-4 min-w-0">
            <div className="flex items-center gap-2">
              <FlaskConical className="h-4 w-4 text-primary" />
              <h4 className="text-xs font-bold">Live test</h4>
            </div>

            <div className="space-y-1.5">
              <Label className="text-[11px] font-bold text-muted-foreground">Try a message</Label>
              <Textarea
                value={sample}
                onChange={(e) => setSample(e.target.value)}
                placeholder="Paste a reply from the channel…"
                rows={3}
                className="resize-none text-sm bg-background"
              />
              {sampleMatches !== null && (
                <div
                  className={cn(
                    'flex items-start gap-2 rounded-md px-2.5 py-2 text-[11px] font-semibold border',
                    sampleMatches
                      ? shadowedBy
                        ? 'bg-gold/10 border-gold/30 text-gold'
                        : 'bg-success/10 border-success/30 text-success'
                      : 'bg-muted border-border text-muted-foreground',
                  )}
                >
                  {sampleMatches ? (
                    shadowedBy ? <AlertTriangle className="h-3.5 w-3.5 mt-px shrink-0" /> : <CheckCircle2 className="h-3.5 w-3.5 mt-px shrink-0" />
                  ) : (
                    <X className="h-3.5 w-3.5 mt-px shrink-0" />
                  )}
                  <span>
                    {!sampleMatches
                      ? 'No match: this rule would not fire.'
                      : shadowedBy
                        ? `Matches, but “${shadowedBy.ruleName}” (priority ${shadowedBy.priority}) fires first.`
                        : 'Matches: this rule fires.'}
                  </span>
                </div>
              )}
            </div>

            <div className="space-y-2">
              <div className="flex items-baseline justify-between gap-2">
                <Label className="text-[11px] font-bold text-muted-foreground">Channel’s real messages</Label>
                {learnedHits && learned && (
                  <span className="text-[10px] font-bold tabular-nums">
                    {learnedHits.hits.length}/{learned.length} patterns · {learnedHits.occurrences}×
                  </span>
                )}
              </div>
              {!draft.channelId ? (
                <p className="text-[11px] text-muted-foreground">Pick a channel to test against what it actually posts.</p>
              ) : learned === null ? (
                <div className="py-4 flex justify-center"><Loader2 className="h-4 w-4 animate-spin text-muted-foreground" /></div>
              ) : learned.length === 0 ? (
                <p className="text-[11px] text-muted-foreground">No messages learned for this channel yet.</p>
              ) : !canTest ? (
                <p className="text-[11px] text-muted-foreground">Enter a valid pattern to see what it catches.</p>
              ) : learnedHits && learnedHits.hits.length === 0 ? (
                <p className="text-[11px] text-muted-foreground">Catches none of the {learned.length} learned messages.</p>
              ) : (
                <ul className="space-y-1 max-h-72 overflow-y-auto pr-1">
                  {learnedHits?.hits.slice(0, 25).map((h) => (
                    <li key={h.id}>
                      <button
                        onClick={() => setSample(h.messagePattern)}
                        className="w-full text-left flex items-start gap-2 rounded-md px-2 py-1.5 bg-background border border-border hover:border-primary/40"
                      >
                        <TelegramText text={h.messagePattern} inline className="text-[11px] flex-1 min-w-0 line-clamp-2" />
                        <span className="text-[10px] font-bold text-muted-foreground tabular-nums shrink-0">{h.occurrenceCount}×</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </aside>
        </div>

        <div className="flex items-center gap-2 px-5 py-3 border-t border-border bg-card">
          {draft.actionType && <ActionPill actionType={draft.actionType} params={draft.actionParams} />}
          <div className="ml-auto flex gap-2">
            <Button variant="outline" size="sm" onClick={() => onOpenChange(false)} className="h-8 text-xs">Cancel</Button>
            <Button size="sm" onClick={save} disabled={saving} className="h-8 text-xs font-bold">
              {saving && <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />}
              {editingId ? 'Save changes' : 'Create rule'}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
