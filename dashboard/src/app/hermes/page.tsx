'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { Brain, RefreshCw, Send, TrendingUp, TrendingDown, MessageSquare, ListChecks, BarChart3, History, Plus, ArrowLeft, Loader2, Wrench } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import Markdown from '@/components/Markdown'

interface HermesSetup {
  id: string; createdAt: string; symbol: string; setupType: string; bias: string
  entryMin: number | null; entryMax: number | null; sl: number | null; tps: string | null
  invalidation: string | null; reasoning: string | null; triggerTf: string | null
  expectedHold: string | null; riskPct: number | null; status: string
}
interface Analytics {
  total: number; byType: Record<string, number>; byStatus: Record<string, number>
  byBias: Record<string, number>; wins: number; losses: number; invalidated: number; winRate: number | null
}
interface Conversation {
  id: string; hermesSessionId: string; title: string | null; source: string | null
  model: string | null; startedAt: string | null; messageCount: number
}
type ChatMsg = { role: 'user' | 'assistant'; content: string; tool?: string }
type View = 'chat' | 'setups' | 'analytics' | 'history'

const typeColor: Record<string, string> = {
  SCALP: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
  INTRADAY: 'bg-sky-500/15 text-sky-400 border-sky-500/30',
  SWING: 'bg-violet-500/15 text-violet-400 border-violet-500/30',
}
const statusColor: Record<string, string> = {
  IDEA: 'bg-muted text-muted-foreground border-border', PENDING: 'bg-muted text-muted-foreground',
  PLACED: 'bg-sky-500/15 text-sky-400 border-sky-500/30', OPEN: 'bg-primary/15 text-primary border-primary/30',
  ACTIVE: 'bg-primary/15 text-primary border-primary/30',
  TP1: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30', TP2: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
  TP3: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30', SL: 'bg-red-500/15 text-red-400 border-red-500/30',
  INVALIDATED: 'bg-orange-500/15 text-orange-400 border-orange-500/30', EXPIRED: 'bg-muted text-muted-foreground',
  CANCELLED: 'bg-muted text-muted-foreground',
}
const SUGGESTIONS = ['XAUUSD top-down setup?', "What's the DXY read?", 'Any scalps right now?', 'Manage my open setups']

export default function HermesPage() {
  const [view, setView] = useState<View>('chat')
  const [setups, setSetups] = useState<HermesSetup[]>([])
  const [analytics, setAnalytics] = useState<Analytics | null>(null)
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [refreshing, setRefreshing] = useState(false)

  const [chat, setChat] = useState<ChatMsg[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [loadingConvo, setLoadingConvo] = useState(false)
  const [execTarget, setExecTarget] = useState<HermesSetup | null>(null)
  const [execLot, setExecLot] = useState('0.01')
  const [execTp, setExecTp] = useState(0)
  const [execBusy, setExecBusy] = useState(false)
  const [execError, setExecError] = useState<string | null>(null)
  const [toolStatus, setToolStatus] = useState<string | null>(null)
  const chatEndRef = useRef<HTMLDivElement>(null)
  const taRef = useRef<HTMLTextAreaElement>(null)

  const fetchData = useCallback(async () => {
    try {
      const [sRes, aRes, cRes] = await Promise.all([
        fetch('/api/hermes/setups?limit=200'), fetch('/api/hermes/analytics'), fetch('/api/hermes/chat'),
      ])
      if (sRes.ok) setSetups((await sRes.json()).setups || [])
      if (aRes.ok) setAnalytics(await aRes.json())
      if (cRes.ok) setConversations((await cRes.json()).conversations || [])
    } catch (e) { console.error(e) } finally { setRefreshing(false) }
  }, [])

  useEffect(() => { fetchData(); const id = setInterval(fetchData, 30_000); return () => clearInterval(id) }, [fetchData])
  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [chat, sending, toolStatus])
  useEffect(() => {
    const immersive = view === 'chat' && chat.length > 0 && !loadingConvo
    document.body.classList.toggle('hermes-immersive', immersive)
    return () => document.body.classList.remove('hermes-immersive')
  }, [view, chat.length, loadingConvo])

  function grow() { const ta = taRef.current; if (!ta) return; ta.style.height = 'auto'; ta.style.height = Math.min(ta.scrollHeight, 160) + 'px' }

  async function loadSession(id: string) {
    setLoadingConvo(true); setView('chat')
    try {
      const res = await fetch(`/api/hermes/chat?conversationId=${id}`)
      const j = await res.json()
      const msgs: ChatMsg[] = (j.messages || [])
        .filter((m: any) => m.role === 'user' || m.role === 'assistant')
        .map((m: any) => ({ role: m.role, content: m.content || '' }))
      setChat(msgs)
    } catch (e) { console.error(e) } finally { setLoadingConvo(false) }
  }
  function newChat() { setChat([]); setView('chat') }

  async function doExecute() {
    if (!execTarget) return
    setExecBusy(true); setExecError(null)
    try {
      const res = await fetch('/api/hermes/execute', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ id: execTarget.id, lot: execLot, tpIndex: execTp }),
      })
      const j = await res.json()
      if (!res.ok) setExecError(j.error || 'execution failed')
      else { setExecTarget(null); fetchData() }
    } catch (e: any) { setExecError(e?.message || 'request failed') } finally { setExecBusy(false) }
  }

  async function send(text?: string) {
    const msg = (text ?? input).trim()
    if (!msg || sending) return
    setInput(''); if (taRef.current) taRef.current.style.height = 'auto'
    const history = chat.slice(-30)

    setChat((c) => [...c, { role: 'user', content: msg }])
    const placeholderIdx = chat.length + 1
    setChat((c) => [...c, { role: 'assistant', content: '' }])
    setSending(true)
    setToolStatus(null)

    try {
      const res = await fetch('/api/hermes/send', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ message: msg, history }),
      })

      if (!res.ok || !res.body) {
        const j = await res.json().catch(() => ({ error: `status ${res.status}` }))
        setChat((c) => {
          const updated = [...c]
          updated[placeholderIdx] = { role: 'assistant', content: `⚠️ ${j.error || 'error'}` }
          return updated
        })
        setSending(false)
        return
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let content = ''
      let done = false

      while (!done) {
        const { value, done: streamDone } = await reader.read()
        if (streamDone) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed) continue
          if (trimmed.startsWith('data: ')) {
            const data = trimmed.slice(6)
            if (data === '[DONE]') { done = true; break }
            try {
              const json = JSON.parse(data)
              if (json.error) {
                content += `\n\n⚠️ ${json.error}`
                if (json.detail) content += `\n\`\`\`\n${json.detail.slice(0, 500)}\n\`\`\``
                done = true; break
              }
              if (json.object === 'tool_use' || json.type === 'tool_use') {
                const toolName = json.name || json.tool || json.function?.name || ''
                setToolStatus(toolName || 'working…')
                content += `\n\n🔧 *Running ${toolName}…*`
              }
              const delta = json.choices?.[0]?.delta?.content
              if (delta) { content += delta; setToolStatus(null) }
              if (json.content && !json.choices) content += json.content
            } catch { if (data.length < 500) content += data }
            setChat((c) => {
              const updated = [...c]
              updated[placeholderIdx] = { role: 'assistant', content }
              return updated
            })
          }
        }
      }
    } catch (e: any) {
      setChat((c) => {
        const updated = [...c]
        updated[placeholderIdx] = { role: 'assistant', content: (updated[placeholderIdx]?.content || '') + `\n\n⚠️ ${e?.message || 'request failed'}` }
        return updated
      })
    } finally { setSending(false); setToolStatus(null) }
  }

  const fmt = (n: number | null) => (n == null ? '—' : n.toLocaleString(undefined, { maximumFractionDigits: 2 }))
  const tpsOf = (s: HermesSetup) => { if (!s.tps) return '—'; try { return (JSON.parse(s.tps) as number[]).join(' / ') } catch { return s.tps } }
  const when = (iso: string | null) => { if (!iso) return ''; const d = new Date(iso); return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + ' ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) }

  const renderInput = (centered?: boolean) => (
    <div className={cn('flex items-end gap-2 bg-card border border-border rounded-2xl px-3 py-2 shadow-lg shadow-black/20', centered && 'shadow-xl')}>
      <textarea ref={taRef} value={input} rows={1}
        onChange={(e) => { setInput(e.target.value); grow() }}
        onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }}
        placeholder="Message Hermes…"
        className="flex-1 bg-transparent resize-none outline-none text-sm text-foreground placeholder:text-muted-foreground py-1.5 max-h-40" />
      <Button size="icon" className="rounded-xl h-9 w-9 shrink-0" onClick={() => send()} disabled={sending || !input.trim()}><Send className="h-4 w-4" /></Button>
    </div>
  )
  const renderPill = (v: View, Icon: any, label: string) => (
    <button onClick={() => setView(v)}
      className={cn('flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold transition-colors',
        view === v ? 'bg-primary/15 text-primary' : 'text-muted-foreground hover:text-foreground')}>
      <Icon className="h-3.5 w-3.5" /> <span className="hidden sm:inline">{label}</span>
    </button>
  )

  const immersive = view === 'chat' && chat.length > 0 && !loadingConvo
  return (
    <div className="min-h-[100dvh] flex flex-col">
      {/* Mobile chat header */}
      {immersive && (
        <div className="md:hidden fixed top-0 inset-x-0 z-40 flex items-center gap-2 px-3 py-2 pt-[calc(env(safe-area-inset-top)+8px)] bg-background/95 backdrop-blur border-b border-border">
          <Button variant="ghost" size="icon" className="h-9 w-9 shrink-0" onClick={newChat} title="New chat"><ArrowLeft className="h-5 w-5" /></Button>
          <div className="w-7 h-7 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center shrink-0"><Brain className="h-4 w-4 text-primary" /></div>
          <span className="font-semibold text-foreground truncate flex-1">Hermes</span>
          <Button variant="ghost" size="icon" className="h-9 w-9 shrink-0" onClick={newChat} title="New chat"><Plus className="h-4 w-4" /></Button>
        </div>
      )}
      {/* Header + view switcher */}
      <div className={cn('pt-[76px] md:pt-5 px-4 md:px-6 pb-2 items-center gap-3 md:sticky md:top-0 z-30 bg-background/80 backdrop-blur-md', immersive ? 'hidden md:flex' : 'flex')}>
        <div className="w-8 h-8 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center shrink-0 hidden md:flex">
          <Brain className="h-4 w-4 text-primary" />
        </div>
        <span className="font-bold text-foreground hidden md:inline">Hermes</span>
        <div className="ml-auto flex items-center gap-1 bg-card/60 border border-border rounded-full p-1">
          {renderPill('chat', MessageSquare, 'Chat')}
          {renderPill('setups', ListChecks, `Setups${setups.length ? ` ${setups.length}` : ''}`)}
          {renderPill('analytics', BarChart3, 'Analytics')}
          {renderPill('history', History, 'History')}
        </div>
        {view === 'chat' ? (
          <Button variant="outline" size="sm" className="h-8 shrink-0 gap-1.5 text-xs" onClick={newChat}><Plus className="h-3.5 w-3.5" /><span className="hidden sm:inline">New Chat</span></Button>
        ) : (
          <Button variant="ghost" size="icon" className="h-8 w-8 shrink-0" onClick={() => { setRefreshing(true); fetchData() }} title="Refresh"><RefreshCw className={cn('h-4 w-4', refreshing && 'animate-spin')} /></Button>
        )}
      </div>

      {/* CHAT */}
      {view === 'chat' && (
        loadingConvo ? (
          <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground">Loading session…</div>
        ) : chat.length === 0 ? (
          <div className="flex-1 flex flex-col items-center justify-center px-4 pb-24 md:pb-8 text-center">
            <div className="w-14 h-14 rounded-2xl bg-primary/10 border border-primary/20 flex items-center justify-center mb-4"><Brain className="h-7 w-7 text-primary" /></div>
            <h2 className="text-2xl font-bold text-foreground">How can I help?</h2>
            <p className="text-sm text-muted-foreground mt-1.5">Ask Hermes about setups, market reads, or analysis.</p>
            <div className="w-full max-w-2xl mt-6">{renderInput(true)}</div>
            <div className="flex flex-wrap gap-2 justify-center mt-4 max-w-2xl">
              {SUGGESTIONS.map((s) => (
                <button key={s} onClick={() => send(s)}
                  className="text-xs px-3 py-1.5 rounded-full border border-border bg-card/50 text-muted-foreground hover:text-foreground hover:border-primary/40 transition-colors">{s}</button>
              ))}
            </div>
          </div>
        ) : (
          <>
            <div className="flex-1 w-full max-w-3xl mx-auto px-4 pt-28 md:pt-4 pb-4 space-y-4">
              {chat.map((m, i) => (
                <div key={i} className={cn('flex', m.role === 'user' ? 'justify-end' : 'justify-start')}>
                  <div className={cn('max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed',
                    m.role === 'user' ? 'bg-primary/15 text-foreground rounded-br-md whitespace-pre-wrap' : 'bg-card border border-border text-foreground rounded-bl-md')}>
                    {m.role === 'assistant' && m.tool ? (
                      <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-1">
                        <Wrench className="h-3 w-3" /> {m.tool}
                      </div>
                    ) : null}
                    {m.role === 'user' ? m.content : <Markdown content={m.content} />}
                  </div>
                </div>
              ))}
              {toolStatus && (
                <div className="flex justify-start">
                  <div className="bg-card border border-border rounded-2xl px-3.5 py-2 text-xs text-muted-foreground flex items-center gap-2">
                    <Loader2 className="h-3 w-3 animate-spin" />{toolStatus}
                  </div>
                </div>
              )}
              {sending && !toolStatus && (
                <div className="flex justify-start">
                  <div className="bg-card border border-border rounded-2xl px-3.5 py-2.5 text-sm text-muted-foreground animate-pulse">Hermes is thinking…</div>
                </div>
              )}
              <div ref={chatEndRef} />
            </div>
            <div className="fixed inset-x-0 bottom-0 z-20 px-4 pb-[calc(env(safe-area-inset-bottom)+12px)] pt-2 bg-background/95 backdrop-blur border-t border-border md:relative md:border-t-0 md:bg-transparent md:backdrop-blur-none md:pb-0 md:max-w-3xl md:mx-auto">
              {renderInput()}
            </div>
          </>
        )
      )}

      {/* HISTORY */}
      {view === 'history' && (
        <div className="flex-1 w-full max-w-3xl mx-auto px-4 py-4 space-y-3 pb-32 md:pb-10">
          <Button variant="outline" className="w-full gap-2 text-sm" onClick={newChat}>
            <Plus className="h-4 w-4" /> Start New Chat
          </Button>
          {conversations.length === 0 ? (
            <Card><CardContent className="py-10 text-center text-sm text-muted-foreground">No sessions yet.</CardContent></Card>
          ) : conversations.map((c) => (
            <button key={c.id} onClick={() => loadSession(c.id)}
              className="w-full text-left p-3 rounded-lg border border-border bg-card/50 hover:bg-card hover:border-primary/40 transition-colors">
              <div className="flex items-center gap-2">
                <MessageSquare className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                <span className="text-sm text-foreground font-medium truncate flex-1">{c.title || '(untitled session)'}</span>
                <Badge variant="outline" className="text-[9px] uppercase tracking-wide text-muted-foreground shrink-0">{c.source || '—'}</Badge>
              </div>
              <div className="text-[11px] text-muted-foreground mt-1 ml-6">{c.messageCount} messages · {when(c.startedAt)}</div>
            </button>
          ))}
        </div>
      )}

      {/* SETUPS */}
      {view === 'setups' && (
        <div className="flex-1 w-full max-w-4xl mx-auto px-4 py-4 space-y-2 pb-32 md:pb-10">
          {setups.length === 0 ? (
            <Card><CardContent className="py-10 text-center text-sm text-muted-foreground">No Hermes setups logged yet.</CardContent></Card>
          ) : setups.map((s) => (
            <Card key={s.id}><CardContent className="p-3">
              <div className="flex flex-wrap items-center gap-2 mb-2">
                <span className="font-bold text-sm text-foreground">{s.symbol}</span>
                <Badge variant="outline" className={cn('text-[10px]', typeColor[s.setupType] || '')}>{s.setupType}</Badge>
                <span className={cn('inline-flex items-center gap-1 text-xs font-semibold', s.bias === 'SELL' ? 'text-red-400' : 'text-emerald-400')}>
                  {s.bias === 'SELL' ? <TrendingDown className="h-3 w-3" /> : <TrendingUp className="h-3 w-3" />}{s.bias}</span>
                <Badge variant="outline" className={cn('text-[10px] ml-auto', statusColor[s.status] || '')}>{s.status}</Badge>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-x-4 gap-y-1 text-xs">
                <div><span className="text-muted-foreground">Entry </span><span className="text-foreground font-medium">{fmt(s.entryMin)}{s.entryMax && s.entryMax !== s.entryMin ? `–${fmt(s.entryMax)}` : ''}</span></div>
                <div><span className="text-muted-foreground">SL </span><span className="text-foreground font-medium">{fmt(s.sl)}</span></div>
                <div className="col-span-2"><span className="text-muted-foreground">TP </span><span className="text-foreground font-medium">{tpsOf(s)}</span></div>
                {s.triggerTf && <div><span className="text-muted-foreground">TF </span><span className="text-foreground font-medium">{s.triggerTf}</span></div>}
                {s.expectedHold && <div><span className="text-muted-foreground">Hold </span><span className="text-foreground font-medium">{s.expectedHold}</span></div>}
                {s.riskPct != null && <div><span className="text-muted-foreground">Risk </span><span className="text-foreground font-medium">{s.riskPct}%</span></div>}
              </div>
              {s.reasoning && <Markdown content={s.reasoning} className="text-xs text-muted-foreground mt-2 leading-relaxed break-words" />}
              {s.invalidation && <p className="text-[11px] text-orange-400/80 mt-1">✗ {s.invalidation}</p>}
              {s.status === 'IDEA' && (
                <div className="mt-2.5 flex justify-end">
                  <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => { setExecTarget(s); setExecLot('0.01'); setExecTp(0); setExecError(null) }}>Execute</Button>
                </div>
              )}
            </CardContent></Card>
          ))}
        </div>
      )}

      {/* ANALYTICS */}
      {view === 'analytics' && (
        <div className="flex-1 w-full max-w-4xl mx-auto px-4 py-4 space-y-4 pb-32 md:pb-10">
          {!analytics ? <p className="text-sm text-muted-foreground">Loading…</p> : (
            <>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <Card><CardHeader className="pb-1"><CardTitle className="text-xs text-muted-foreground font-medium">Total setups</CardTitle></CardHeader><CardContent><span className="text-2xl font-bold text-foreground">{analytics.total}</span></CardContent></Card>
                <Card><CardHeader className="pb-1"><CardTitle className="text-xs text-muted-foreground font-medium">Win rate</CardTitle></CardHeader><CardContent><span className="text-2xl font-bold text-foreground">{analytics.winRate == null ? '—' : `${analytics.winRate}%`}</span></CardContent></Card>
                <Card><CardHeader className="pb-1"><CardTitle className="text-xs text-muted-foreground font-medium">Wins / Losses</CardTitle></CardHeader><CardContent><span className="text-2xl font-bold"><span className="text-emerald-400">{analytics.wins}</span> <span className="text-muted-foreground">/</span> <span className="text-red-400">{analytics.losses}</span></span></CardContent></Card>
                <Card><CardHeader className="pb-1"><CardTitle className="text-xs text-muted-foreground font-medium">Invalidated</CardTitle></CardHeader><CardContent><span className="text-2xl font-bold text-orange-400">{analytics.invalidated}</span></CardContent></Card>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                {([['By type', analytics.byType], ['By status', analytics.byStatus], ['By bias', analytics.byBias]] as [string, Record<string, number>][]).map(([title, obj]) => (
                  <Card key={title}><CardHeader className="pb-2"><CardTitle className="text-sm">{title}</CardTitle></CardHeader><CardContent className="space-y-1">
                    {Object.entries(obj).length === 0 ? <span className="text-xs text-muted-foreground">—</span> :
                      Object.entries(obj).map(([k, v]) => <div key={k} className="flex justify-between text-xs"><span className="text-muted-foreground">{k}</span><span className="text-foreground font-medium">{v}</span></div>)}
                  </CardContent></Card>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {/* Execute confirm modal */}
      {execTarget && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4" onClick={() => !execBusy && setExecTarget(null)}>
          <div className="bg-card border border-border rounded-2xl p-4 w-full max-w-md shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="font-bold text-foreground">Execute setup</h3>
            <p className="text-xs text-muted-foreground mt-0.5 mb-3">{execTarget.symbol} · {execTarget.setupType} · <span className={execTarget.bias === 'SELL' ? 'text-red-400' : 'text-emerald-400'}>{execTarget.bias}</span></p>
            <div className="space-y-2 text-xs">
              <div className="flex justify-between"><span className="text-muted-foreground">Entry</span><span className="text-foreground">{fmt(execTarget.entryMin)}{execTarget.entryMax && execTarget.entryMax !== execTarget.entryMin ? `–${fmt(execTarget.entryMax)}` : ''}</span></div>
              <div className="flex justify-between"><span className="text-muted-foreground">Stop loss</span><span className="text-foreground">{fmt(execTarget.sl)}</span></div>
              <div>
                <span className="text-muted-foreground">Take profit</span>
                <div className="flex flex-wrap gap-1.5 mt-1">
                  {(execTarget.tps ? (JSON.parse(execTarget.tps) as number[]) : []).map((tp, i) => (
                    <button key={i} onClick={() => setExecTp(i)} className={cn('px-2 py-1 rounded-lg border text-xs', execTp === i ? 'border-primary bg-primary/15 text-primary' : 'border-border text-muted-foreground')}>TP{i + 1} · {fmt(tp)}</button>
                  ))}
                </div>
              </div>
              <div className="flex items-center justify-between pt-1">
                <span className="text-muted-foreground">Lot size</span>
                <input value={execLot} onChange={(e) => setExecLot(e.target.value)} inputMode="decimal" className="w-24 bg-background border border-border rounded-lg px-2 py-1 text-right text-foreground outline-none focus:border-primary" />
              </div>
            </div>
            <p className="text-[11px] text-orange-400/90 mt-3 leading-relaxed">⚠ Places a LIVE order on your MT5 account — market if price is in the zone, else a pending limit at entry. Stop loss is attached.</p>
            {execError && <p className="text-xs text-red-400 mt-2 break-words">{execError}</p>}
            <div className="flex gap-2 mt-4">
              <Button variant="outline" className="flex-1" onClick={() => setExecTarget(null)} disabled={execBusy}>Cancel</Button>
              <Button className="flex-1" onClick={doExecute} disabled={execBusy || !(parseFloat(execLot) > 0)}>{execBusy ? 'Placing…' : 'Confirm & place'}</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
