'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import MobilePageHeader from '@/components/MobilePageHeader'
import { useToast } from '@/hooks/use-toast'
import { cn } from '@/lib/utils'
import { ACTIONS, byPriority, firstMatch, matchesRule, type ActionType, type ChannelRule } from '@/lib/channelRules'
import RuleEditor, { draftFromRule, emptyDraft, type RuleDraft } from '@/components/channel-rules/RuleEditor'
import { ActivityPanel, LearnedPanel, SuggestionsPanel, type CreateFrom, type Suggestion } from '@/components/channel-rules/Panels'
import {
  ActionPill, ChannelPicker, EmptyState, agoIso, normalizeChannelId, type ChannelOption,
} from '@/components/channel-rules/shared'
import {
  Activity, ArrowRight, BookOpen, Bot, Brain, CircleSlash, Copy, FlaskConical, Lightbulb, ListChecks,
  MessageSquareReply, Pencil, Plus, RefreshCw, Search, Trash2, Zap,
} from 'lucide-react'

type StatusFilter = 'all' | 'active' | 'paused'

interface EditorState {
  open: boolean
  initial: RuleDraft
  editingId: string | null
  sample?: string
}

export default function ChannelRulesPage() {
  const { toast } = useToast()
  const [rules, setRules] = useState<ChannelRule[]>([])
  const [loading, setLoading] = useState(true)
  const [channels, setChannels] = useState<ChannelOption[]>([])
  const [channelsLoading, setChannelsLoading] = useState(true)
  const [suggestions, setSuggestions] = useState<Suggestion[]>([])
  const [suggestionsLoading, setSuggestionsLoading] = useState(true)
  const [tab, setTab] = useState('rules')
  const [search, setSearch] = useState('')
  const [channelFilter, setChannelFilter] = useState('')
  const [status, setStatus] = useState<StatusFilter>('all')
  const [testChannel, setTestChannel] = useState('')
  const [testText, setTestText] = useState('')
  const [editor, setEditor] = useState<EditorState>({ open: false, initial: emptyDraft(), editingId: null })

  const loadRules = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/channel-behavior/rules')
      if (!res.ok) throw new Error('Failed to load rules')
      setRules((await res.json()).rules || [])
    } catch (e) {
      toast({ title: 'Error', description: e instanceof Error ? e.message : String(e), variant: 'destructive' })
    } finally {
      setLoading(false)
    }
  }, [toast])

  const loadSuggestions = useCallback(async () => {
    setSuggestionsLoading(true)
    try {
      const res = await fetch('/api/channel-behavior/rule-suggestions')
      setSuggestions(res.ok ? (await res.json()).suggestions || [] : [])
    } finally {
      setSuggestionsLoading(false)
    }
  }, [])

  useEffect(() => {
    loadRules()
    loadSuggestions()
    fetch('/api/telegram/channels/all')
      .then((r) => r.json())
      .then((d) => {
        if (!d.success) return
        const all = [...(d.data.channels || []), ...(d.data.supergroups || []), ...(d.data.groups || [])]
        const seen = new Set<string>()
        setChannels(
          all
            .map((c: { id: string | number; title: string }) => ({ id: normalizeChannelId(String(c.id)), title: c.title }))
            .filter((c: ChannelOption) => !seen.has(c.id) && seen.add(c.id)),
        )
      })
      .catch(() => {})
      .finally(() => setChannelsLoading(false))
  }, [loadRules, loadSuggestions])

  const channelTitle = useCallback(
    (id: string) => channels.find((c) => c.id === id)?.title ?? rules.find((r) => r.channelId === id && r.channelTitle && r.channelTitle !== id)?.channelTitle ?? id,
    [channels, rules],
  )

  // Channels that have rules come first in pickers
  const pickerChannels = useMemo(() => {
    const ruleIds = new Set(rules.map((r) => r.channelId))
    const known = new Set(channels.map((c) => c.id))
    const extra = [...ruleIds].filter((id) => !known.has(id)).map((id) => ({ id, title: channelTitle(id) }))
    return [...extra, ...channels].sort((a, b) => Number(ruleIds.has(b.id)) - Number(ruleIds.has(a.id)))
  }, [channels, rules, channelTitle])

  const stats = useMemo(() => {
    const active = rules.filter((r) => r.isEnabled)
    const matches = rules.reduce((n, r) => n + r.matchCount, 0)
    const done = rules.reduce((n, r) => n + r.successCount, 0)
    const last = rules.map((r) => r.lastMatchedAt).filter(Boolean).sort().pop() ?? null
    return {
      active: active.length,
      total: rules.length,
      channels: new Set(active.map((r) => r.channelId)).size,
      matches,
      done,
      last,
    }
  }, [rules])

  const groups = useMemo(() => {
    const q = search.toLowerCase()
    const visible = rules.filter(
      (r) =>
        (!channelFilter || r.channelId === channelFilter) &&
        (status === 'all' || (status === 'active' ? r.isEnabled : !r.isEnabled)) &&
        (!q || [r.ruleName, r.replyPattern, r.description ?? '', ACTIONS[r.actionType]?.label ?? ''].some((s) => s.toLowerCase().includes(q))),
    )
    const byChannel = new Map<string, ChannelRule[]>()
    for (const r of [...visible].sort(byPriority)) {
      byChannel.set(r.channelId, [...(byChannel.get(r.channelId) ?? []), r])
    }
    return [...byChannel.entries()].sort((a, b) => channelTitle(a[0]).localeCompare(channelTitle(b[0])))
  }, [rules, search, channelFilter, status, channelTitle])

  const openNew = (init?: Partial<RuleDraft>, sample?: string) =>
    setEditor({ open: true, initial: { ...emptyDraft(channelFilter || testChannel), ...init }, editingId: null, sample })

  const createFrom: CreateFrom = ({ channelId, ruleName, replyPattern, actionType, sample }) =>
    openNew({ channelId, ruleName: ruleName ?? '', replyPattern: replyPattern ?? '', actionType: actionType ?? '' }, sample)

  const updateRule = async (rule: ChannelRule, patch: Partial<ChannelRule>) => {
    setRules((rs) => rs.map((r) => (r.id === rule.id ? { ...r, ...patch } : r)))
    const res = await fetch(`/api/channel-behavior/rules/${rule.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    })
    if (!res.ok) {
      setRules((rs) => rs.map((r) => (r.id === rule.id ? rule : r)))
      toast({ title: 'Update failed', description: (await res.json()).error, variant: 'destructive' })
    }
  }

  const deleteRule = async (rule: ChannelRule) => {
    if (!confirm(`Delete rule “${rule.ruleName}”?`)) return
    const res = await fetch(`/api/channel-behavior/rules/${rule.id}`, { method: 'DELETE' })
    if (!res.ok) return toast({ title: 'Delete failed', variant: 'destructive' })
    setRules((rs) => rs.filter((r) => r.id !== rule.id))
    toast({ title: 'Rule deleted' })
  }

  // Tester: what the bot would do with this message in this channel
  const testHit = testChannel && testText.trim() ? firstMatch(testText, testChannel, rules) : null
  const testAlso = testHit
    ? rules.filter((r) => r.id !== testHit.id && r.channelId === testChannel && matchesRule(testText, r))
    : []

  const header = (
    <div className="ml-auto flex items-center gap-2">
      <Button variant="outline" size="sm" onClick={() => { loadRules(); loadSuggestions() }} disabled={loading} className="h-8 text-xs gap-1.5">
        <RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />Refresh
      </Button>
      <Button size="sm" onClick={() => openNew()} className="h-8 text-xs gap-1.5 font-bold">
        <Plus className="h-3.5 w-3.5" />New rule
      </Button>
    </div>
  )

  return (
    <div className="flex min-h-full flex-col">
      <MobilePageHeader title="Channel Rules" subtitle="Your instructions per channel" icon={<Brain className="h-5 w-5 text-primary" />} />

      <header className="hidden md:flex sticky top-0 z-40 w-full tech-header">
        <div className="max-w-[1800px] w-full mx-auto flex h-14 items-center px-6 gap-3">
          <div className="p-1.5 rounded-lg bg-primary/10 border border-primary/20">
            <Brain className="h-5 w-5 text-primary" />
          </div>
          <div className="flex flex-col gap-0.5">
            <div className="flex items-center gap-2">
              <h1 className="text-sm font-bold text-foreground leading-none">Channel Rules</h1>
              <span className="font-mono text-[9px] tracking-[0.15em] text-muted-foreground/50 uppercase">/ behavior</span>
            </div>
            <p className="text-[10px] text-muted-foreground/70 font-semibold uppercase tracking-wider leading-none">
              Your instructions for each channel’s replies
            </p>
          </div>
          {header}
        </div>
      </header>

      <div className="flex-1 px-4 md:px-8 py-4 md:py-6">
        <div className="max-w-[1800px] mx-auto space-y-4 md:space-y-5">
          <div className="flex md:hidden">{header}</div>

          {/* ── KPIs ─────────────────────────────────────────────────── */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <Kpi icon={ListChecks} label="Active rules" value={`${stats.active}`} sub={`${stats.total} total · ${stats.channels} channel${stats.channels === 1 ? '' : 's'}`} />
            <Kpi icon={Zap} label="Matches" value={`${stats.matches}`} sub={`last ${agoIso(stats.last)}`} />
            <Kpi
              icon={Activity}
              label="Carried out"
              value={`${stats.done}`}
              sub={stats.matches ? `${Math.round((stats.done / stats.matches) * 100)}% of matches` : 'no matches yet'}
            />
            <Kpi icon={Lightbulb} label="Suggestions" value={suggestionsLoading ? '…' : `${suggestions.length}`} sub="repeated messages without a rule" onClick={() => setTab('suggestions')} />
          </div>

          {/* ── how it runs ──────────────────────────────────────────── */}
          <div className="tech-card px-4 py-3">
            <div className="flex items-center gap-2 md:gap-3 flex-wrap text-[11px]">
              <Step icon={MessageSquareReply} title="Reply arrives" sub="in a monitored channel" />
              <ArrowRight className="h-3.5 w-3.5 text-muted-foreground/50 hidden sm:block" />
              <Step icon={ListChecks} title="Rules checked" sub="highest priority first, edits apply instantly" />
              <ArrowRight className="h-3.5 w-3.5 text-muted-foreground/50 hidden sm:block" />
              <Step icon={CircleSlash} title="Ignore → dropped" sub="no AI call, no trade action" />
              <span className="text-muted-foreground/60 font-bold hidden sm:block">·</span>
              <Step icon={Bot} title="Other actions → AI" sub="as your instruction, checked against live positions" />
              <ArrowRight className="h-3.5 w-3.5 text-muted-foreground/50 hidden sm:block" />
              <Step icon={Zap} title="Executed" sub="runs directly if no AI is reachable" />
            </div>
          </div>

          <div className="grid lg:grid-cols-[minmax(0,1fr)_360px] gap-4 md:gap-5 items-start">
            {/* ── main ─────────────────────────────────────────────── */}
            <Tabs value={tab} onValueChange={setTab} className="min-w-0">
              <TabsList className="h-9 mb-3">
                <TabsTrigger value="rules" className="text-xs gap-1.5"><ListChecks className="h-3.5 w-3.5" />Rules<Count n={rules.length} /></TabsTrigger>
                <TabsTrigger value="activity" className="text-xs gap-1.5"><Activity className="h-3.5 w-3.5" />Activity</TabsTrigger>
                <TabsTrigger value="suggestions" className="text-xs gap-1.5"><Lightbulb className="h-3.5 w-3.5" />Suggestions<Count n={suggestions.length} accent /></TabsTrigger>
                <TabsTrigger value="learned" className="text-xs gap-1.5"><BookOpen className="h-3.5 w-3.5" />Learned</TabsTrigger>
              </TabsList>

              <TabsContent value="rules" className="mt-0">
                <div className="tech-card overflow-hidden">
                  <div className="flex items-center gap-2 flex-wrap px-4 py-3 border-b border-border">
                    <div className="relative flex-1 min-w-[160px] max-w-xs">
                      <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
                      <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search rules…" className="pl-8 h-9 text-xs" />
                    </div>
                    <div className="w-56"><ChannelPicker value={channelFilter} onChange={setChannelFilter} channels={pickerChannels} loading={channelsLoading} allowAll /></div>
                    <div className="flex rounded-md border border-border p-0.5">
                      {(['all', 'active', 'paused'] as StatusFilter[]).map((s) => (
                        <button
                          key={s}
                          onClick={() => setStatus(s)}
                          className={cn('px-2.5 h-7 rounded text-[11px] font-bold capitalize', status === s ? 'bg-muted text-foreground' : 'text-muted-foreground hover:text-foreground')}
                        >
                          {s}
                        </button>
                      ))}
                    </div>
                  </div>

                  {loading && rules.length === 0 ? (
                    <div className="py-16 flex justify-center"><RefreshCw className="h-6 w-6 animate-spin text-muted-foreground" /></div>
                  ) : rules.length === 0 ? (
                    <EmptyState icon={ListChecks} title="No rules yet">
                      <p className="mb-4">Tell the bot how to read a channel’s replies, e.g. “in this channel <i>BE now</i> means move to breakeven”.</p>
                      <Button size="sm" onClick={() => openNew()} className="h-8 text-xs"><Plus className="h-3.5 w-3.5 mr-1" />Create your first rule</Button>
                    </EmptyState>
                  ) : groups.length === 0 ? (
                    <EmptyState icon={Search} title="No rules match these filters" />
                  ) : (
                    groups.map(([channelId, list]) => (
                      <section key={channelId} className="border-b border-border last:border-b-0">
                        <div className="flex items-center gap-2 px-4 py-2 bg-muted/30">
                          <span className="text-xs font-bold truncate">{channelTitle(channelId)}</span>
                          <span className="font-mono text-[10px] text-muted-foreground hidden sm:inline">{channelId}</span>
                          <span className="text-[10px] font-bold text-muted-foreground">{list.length} rule{list.length === 1 ? '' : 's'}</span>
                          <Button variant="ghost" size="sm" className="ml-auto h-6 text-[11px]" onClick={() => openNew({ channelId })}>
                            <Plus className="h-3 w-3 mr-1" />Add
                          </Button>
                        </div>
                        <ul className="divide-y divide-border">
                          {list.map((r) => (
                            <RuleRow
                              key={r.id}
                              rule={r}
                              onToggle={(v) => updateRule(r, { isEnabled: v })}
                              onEdit={() => setEditor({ open: true, initial: draftFromRule(r), editingId: r.id })}
                              onDuplicate={() => setEditor({ open: true, initial: { ...draftFromRule(r), ruleName: `${r.ruleName} (copy)` }, editingId: null })}
                              onTest={() => setTestChannel(r.channelId)}
                              onDelete={() => deleteRule(r)}
                            />
                          ))}
                        </ul>
                      </section>
                    ))
                  )}
                </div>
              </TabsContent>

              <TabsContent value="activity" className="mt-0">
                <div className="tech-card overflow-hidden">
                  {tab === 'activity' && <ActivityPanel channels={pickerChannels} channelTitle={channelTitle} />}
                </div>
              </TabsContent>

              <TabsContent value="suggestions" className="mt-0">
                <div className="tech-card overflow-hidden">
                  <SuggestionsPanel suggestions={suggestions} loading={suggestionsLoading} channelTitle={channelTitle} onCreate={createFrom} />
                </div>
              </TabsContent>

              <TabsContent value="learned" className="mt-0">
                <div className="tech-card overflow-hidden">
                  {tab === 'learned' && (
                    <LearnedPanel channels={pickerChannels} rules={rules} defaultChannel={channelFilter || rules[0]?.channelId || ''} onCreate={createFrom} />
                  )}
                </div>
              </TabsContent>
            </Tabs>

            {/* ── tester ───────────────────────────────────────────── */}
            <aside className="tech-card p-4 space-y-3 lg:sticky lg:top-20">
              <div className="flex items-center gap-2">
                <FlaskConical className="h-4 w-4 text-primary" />
                <h3 className="text-sm font-bold">Rule tester</h3>
              </div>
              <p className="text-[11px] text-muted-foreground">Paste a reply to see exactly what the bot will do with it.</p>
              <ChannelPicker value={testChannel} onChange={setTestChannel} channels={pickerChannels} loading={channelsLoading} placeholder="Channel…" />
              <Textarea
                value={testText}
                onChange={(e) => setTestText(e.target.value)}
                placeholder="e.g. +120 pips running — set BE now"
                rows={3}
                className="resize-none text-sm"
              />
              {!testChannel || !testText.trim() ? (
                <p className="text-[11px] text-muted-foreground/80">Pick a channel and type a message.</p>
              ) : testHit ? (
                <div className="rounded-lg border border-primary/30 bg-primary/5 p-3 space-y-2">
                  <div className="text-[10px] font-black uppercase tracking-[0.15em] text-primary">Rule fires</div>
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-bold">{testHit.ruleName}</span>
                    <ActionPill actionType={testHit.actionType} params={testHit.actionParams} />
                  </div>
                  <p className="text-[11px] text-muted-foreground">
                    {testHit.actionType === 'IGNORE'
                      ? 'The message is dropped: no AI call and no trade action.'
                      : testHit.actionType === 'AI_MANAGED'
                        ? 'The AI gets your note as the instruction and decides with live positions.'
                        : `The AI is told to ${ACTIONS[testHit.actionType].label.toLowerCase()}. It checks live positions first (e.g. only pending orders → cancels them).`}
                  </p>
                  {testAlso.length > 0 && (
                    <p className="text-[11px] text-muted-foreground border-t border-border pt-2">
                      Also matches (not used): {testAlso.map((r) => `“${r.ruleName}”${r.isEnabled ? '' : ' (paused)'}`).join(', ')}
                    </p>
                  )}
                  <Button variant="ghost" size="sm" className="h-7 text-[11px] -ml-2" onClick={() => setEditor({ open: true, initial: draftFromRule(testHit), editingId: testHit.id, sample: testText })}>
                    <Pencil className="h-3 w-3 mr-1" />Edit this rule
                  </Button>
                </div>
              ) : (
                <div className="rounded-lg border border-border bg-muted/30 p-3 space-y-2">
                  <div className="text-[10px] font-black uppercase tracking-[0.15em] text-muted-foreground">No rule matches</div>
                  <p className="text-[11px] text-muted-foreground">The AI reads the message on its own, with live positions and the thread history.</p>
                  <Button variant="outline" size="sm" className="h-7 text-[11px]" onClick={() => openNew({ channelId: testChannel }, testText)}>
                    <Plus className="h-3 w-3 mr-1" />Make a rule for this
                  </Button>
                </div>
              )}
            </aside>
          </div>
        </div>
      </div>

      <RuleEditor
        open={editor.open}
        onOpenChange={(open) => setEditor((e) => ({ ...e, open }))}
        initial={editor.initial}
        editingId={editor.editingId}
        sampleText={editor.sample}
        channels={pickerChannels}
        channelsLoading={channelsLoading}
        rules={rules}
        onSaved={() => { loadRules(); loadSuggestions() }}
      />
    </div>
  )
}

function Kpi({ icon: Icon, label, value, sub, onClick }: { icon: typeof Zap; label: string; value: string; sub: string; onClick?: () => void }) {
  return (
    <button onClick={onClick} disabled={!onClick} className={cn('tech-card p-3.5 text-left', onClick && 'neon-border-hover cursor-pointer')}>
      <div className="flex items-center gap-1.5 text-[10px] font-black uppercase tracking-[0.15em] text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />{label}
      </div>
      <div className="text-2xl font-bold tabular-nums mt-1 leading-none">{value}</div>
      <div className="text-[11px] text-muted-foreground mt-1 truncate">{sub}</div>
    </button>
  )
}

function Step({ icon: Icon, title, sub }: { icon: typeof Zap; title: string; sub: string }) {
  return (
    <div className="flex items-center gap-2 min-w-0">
      <span className="p-1.5 rounded-md bg-primary/10 border border-primary/20 shrink-0"><Icon className="h-3.5 w-3.5 text-primary" /></span>
      <div className="leading-tight min-w-0">
        <div className="font-bold">{title}</div>
        <div className="text-muted-foreground text-[10px]">{sub}</div>
      </div>
    </div>
  )
}

function Count({ n, accent }: { n: number; accent?: boolean }) {
  if (!n) return null
  return (
    <span className={cn('ml-0.5 rounded-full text-[10px] px-1.5 font-bold tabular-nums', accent ? 'bg-primary text-primary-foreground' : 'bg-muted-foreground/15')}>
      {n}
    </span>
  )
}

function RuleRow({
  rule,
  onToggle,
  onEdit,
  onDuplicate,
  onTest,
  onDelete,
}: {
  rule: ChannelRule
  onToggle: (v: boolean) => void
  onEdit: () => void
  onDuplicate: () => void
  onTest: () => void
  onDelete: () => void
}) {
  const rate = rule.matchCount ? Math.round((rule.successCount / rule.matchCount) * 100) : null
  return (
    <li className={cn('px-4 py-3 flex gap-3 items-start group', !rule.isEnabled && 'opacity-55')}>
      <span
        title="Priority: higher is checked first"
        className="mt-0.5 shrink-0 w-9 text-center rounded-md border border-border bg-muted/40 text-[10px] font-black tabular-nums py-0.5"
      >
        P{rule.priority}
      </span>
      <div className="flex-1 min-w-0 space-y-1.5">
        <div className="flex items-center gap-2 flex-wrap">
          <button onClick={onEdit} className="text-sm font-bold hover:text-primary text-left">{rule.ruleName}</button>
          <ActionPill actionType={rule.actionType as ActionType} params={rule.actionParams} />
          {Object.keys(rule.conditions).length > 0 && (
            <span className="text-[10px] font-bold text-muted-foreground border border-dashed border-border rounded px-1.5">conditional</span>
          )}
        </div>
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-[9px] font-black uppercase tracking-wider text-muted-foreground shrink-0">{rule.patternType.replace('_', ' ')}</span>
          <code className="text-[11px] font-mono bg-muted px-1.5 py-0.5 rounded truncate">{rule.replyPattern}</code>
        </div>
        {rule.description && <p className="text-[11px] text-muted-foreground line-clamp-2">{rule.description}</p>}
        <div className="flex items-center gap-3 text-[10px] text-muted-foreground tabular-nums flex-wrap">
          <span><b className="text-foreground">{rule.matchCount}</b> matches</span>
          <span><b className="text-foreground">{rule.successCount}</b> carried out{rate !== null && ` (${rate}%)`}</span>
          <span>last match {agoIso(rule.lastMatchedAt)}</span>
        </div>
      </div>
      <div className="flex items-center gap-0.5 shrink-0">
        <IconBtn title="Test in tester" onClick={onTest} icon={FlaskConical} desktopOnly />
        <IconBtn title="Duplicate" onClick={onDuplicate} icon={Copy} desktopOnly />
        <IconBtn title="Edit" onClick={onEdit} icon={Pencil} />
        <IconBtn title="Delete" onClick={onDelete} icon={Trash2} danger />
        <Switch checked={rule.isEnabled} onCheckedChange={onToggle} className="ml-1.5" aria-label={rule.isEnabled ? 'Pause rule' : 'Activate rule'} />
      </div>
    </li>
  )
}

function IconBtn({ title, onClick, icon: Icon, danger, desktopOnly }: { title: string; onClick: () => void; icon: typeof Zap; danger?: boolean; desktopOnly?: boolean }) {
  return (
    <Button variant="ghost" size="sm" title={title} onClick={onClick} className={cn('h-7 w-7 p-0 md:opacity-60 md:group-hover:opacity-100', desktopOnly && 'hidden sm:inline-flex')}>
      <Icon className={cn('h-3.5 w-3.5', danger && 'text-destructive')} />
    </Button>
  )
}
