'use client'

import { useState, useEffect, useCallback, useMemo, Fragment } from 'react'
import { toast } from 'sonner'
import {
  KeyRound,
  Plus,
  Copy,
  Check,
  Ban,
  RotateCcw,
  Trash2,
  Activity,
  ChevronDown,
  ChevronUp,
  ShieldCheck,
  ShieldOff,
  Clock,
  Radio,
  AlertTriangle,
  Search,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  X,
  Globe,
  Calendar,
  Hash,
  Fingerprint,
} from 'lucide-react'
import MobilePageHeader from '@/components/MobilePageHeader'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from '@/components/ui/dialog'
import { formatDate } from '@/lib/utils'

interface ApiKeyRow {
  id: string
  label: string
  keyPrefix: string
  createdAt: string
  expiresAt: string | null
  revokedAt: string | null
  lastUsedAt: string | null
  lastUsedIp: string | null
  requestCount: number
  status: 'active' | 'expired' | 'revoked'
}

interface UsageRow {
  id: string
  createdAt: string
  lastSeenAt: string
  hits: number
  ip: string | null
  userAgent: string | null
  endpoint: string
  status: string
}

type SortKey = 'label' | 'createdAt' | 'lastUsedAt' | 'requestCount'
type StatusFilter = 'all' | 'active' | 'expired' | 'revoked'

const STATUS_META: Record<ApiKeyRow['status'], { label: string; className: string; dot: string }> = {
  active: { label: 'Active', className: 'text-success bg-success/10 border-success/25', dot: 'bg-success' },
  expired: { label: 'Expired', className: 'text-muted-foreground bg-muted border-border', dot: 'bg-muted-foreground' },
  revoked: { label: 'Revoked', className: 'text-destructive bg-destructive/10 border-destructive/25', dot: 'bg-destructive' },
}

function StatusPill({ status }: { status: ApiKeyRow['status'] }) {
  const meta = STATUS_META[status]
  return (
    <span className={`inline-flex items-center gap-1.5 text-[11px] font-bold rounded-full border px-2 py-0.5 ${meta.className}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${meta.dot}`} />
      {meta.label}
    </span>
  )
}

export default function ApiKeysPage() {
  const [keys, setKeys] = useState<ApiKeyRow[]>([])
  const [loading, setLoading] = useState(true)

  const [createOpen, setCreateOpen] = useState(false)
  const [newLabel, setNewLabel] = useState('')
  const [newExpiresAt, setNewExpiresAt] = useState('')
  const [creating, setCreating] = useState(false)
  const [issuedKey, setIssuedKey] = useState<{ label: string; key: string } | null>(null)
  const [justCopied, setJustCopied] = useState(false)

  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [usageByKey, setUsageByKey] = useState<Record<string, UsageRow[]>>({})
  const [usageLoading, setUsageLoading] = useState<string | null>(null)

  // Detail drawer
  const [detailKey, setDetailKey] = useState<ApiKeyRow | null>(null)

  // Search / filter / sort
  const [query, setQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [sortKey, setSortKey] = useState<SortKey>('createdAt')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  // Bulk selection
  const [selected, setSelected] = useState<Set<string>>(new Set())

  const loadKeys = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/admin/api-keys', { cache: 'no-store' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setKeys(data.keys ?? [])
    } catch (err) {
      toast.error('Failed to load keys', { description: err instanceof Error ? err.message : undefined })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadKeys()
  }, [loadKeys])

  const loadUsage = useCallback(async (id: string) => {
    setUsageLoading(id)
    try {
      const res = await fetch(`/api/admin/api-keys/${id}/usage?limit=200`, { cache: 'no-store' })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`)
      setUsageByKey((prev) => ({ ...prev, [id]: data.usage ?? [] }))
    } catch (err) {
      toast.error('Failed to load connection log', { description: err instanceof Error ? err.message : undefined })
    } finally {
      setUsageLoading(null)
    }
  }, [])

  const stats = useMemo(() => {
    const active = keys.filter((k) => k.status === 'active').length
    const revoked = keys.filter((k) => k.status === 'revoked').length
    const expired = keys.filter((k) => k.status === 'expired').length
    const totalRequests = keys.reduce((sum, k) => sum + k.requestCount, 0)
    return { active, revoked, expired, totalRequests, total: keys.length }
  }, [keys])

  const filteredKeys = useMemo(() => {
    let rows = keys
    if (statusFilter !== 'all') rows = rows.filter((k) => k.status === statusFilter)
    const q = query.trim().toLowerCase()
    if (q) {
      rows = rows.filter((k) => k.label.toLowerCase().includes(q) || k.keyPrefix.toLowerCase().includes(q))
    }
    const dir = sortDir === 'asc' ? 1 : -1
    return [...rows].sort((a, b) => {
      switch (sortKey) {
        case 'label':
          return a.label.localeCompare(b.label) * dir
        case 'lastUsedAt': {
          const av = a.lastUsedAt ? new Date(a.lastUsedAt).getTime() : 0
          const bv = b.lastUsedAt ? new Date(b.lastUsedAt).getTime() : 0
          return (av - bv) * dir
        }
        case 'requestCount':
          return (a.requestCount - b.requestCount) * dir
        case 'createdAt':
        default:
          return (new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime()) * dir
      }
    })
  }, [keys, statusFilter, query, sortKey, sortDir])

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir(key === 'label' ? 'asc' : 'desc')
    }
  }

  function toggleSelected(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function toggleSelectAll() {
    setSelected((prev) => {
      if (prev.size === filteredKeys.length && filteredKeys.length > 0) return new Set()
      return new Set(filteredKeys.map((k) => k.id))
    })
  }

  async function createKey() {
    if (!newLabel.trim()) {
      toast.error('Label is required — e.g. the customer name')
      return
    }
    setCreating(true)
    try {
      const res = await fetch('/api/admin/api-keys', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          label: newLabel.trim(),
          expiresAt: newExpiresAt ? new Date(newExpiresAt).toISOString() : null,
        }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`)
      setIssuedKey({ label: data.label, key: data.key })
      setNewLabel('')
      setNewExpiresAt('')
      await loadKeys()
    } catch (err) {
      toast.error('Failed to create key', { description: err instanceof Error ? err.message : undefined })
    } finally {
      setCreating(false)
    }
  }

  async function revokeKey(id: string) {
    if (!confirm('Revoke this key? Any EA still using it will start getting 403s immediately.')) return
    try {
      const res = await fetch(`/api/admin/api-keys/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'revoke' }),
      })
      if (!res.ok) throw new Error((await res.json()).error || `HTTP ${res.status}`)
      toast.success('Key revoked')
      await loadKeys()
    } catch (err) {
      toast.error('Failed to revoke key', { description: err instanceof Error ? err.message : undefined })
    }
  }

  async function reactivateKey(id: string) {
    try {
      const res = await fetch(`/api/admin/api-keys/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'reactivate' }),
      })
      if (!res.ok) throw new Error((await res.json()).error || `HTTP ${res.status}`)
      toast.success('Key reactivated')
      await loadKeys()
    } catch (err) {
      toast.error('Failed to reactivate key', { description: err instanceof Error ? err.message : undefined })
    }
  }

  async function deleteKey(id: string) {
    if (!confirm('Permanently delete this key and its usage history? This cannot be undone — prefer Revoke unless this was a mistake.')) return
    try {
      const res = await fetch(`/api/admin/api-keys/${id}`, { method: 'DELETE' })
      if (!res.ok) throw new Error((await res.json()).error || `HTTP ${res.status}`)
      toast.success('Key deleted')
      setSelected((prev) => {
        const next = new Set(prev)
        next.delete(id)
        return next
      })
      await loadKeys()
    } catch (err) {
      toast.error('Failed to delete key', { description: err instanceof Error ? err.message : undefined })
    }
  }

  async function bulkRevoke() {
    const ids = Array.from(selected).filter((id) => keys.find((k) => k.id === id)?.status === 'active')
    if (ids.length === 0) return
    if (!confirm(`Revoke ${ids.length} selected key${ids.length > 1 ? 's' : ''}? Any EA still using them will start getting 403s immediately.`)) return
    try {
      await Promise.all(
        ids.map((id) =>
          fetch(`/api/admin/api-keys/${id}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'revoke' }),
          })
        )
      )
      toast.success(`${ids.length} key${ids.length > 1 ? 's' : ''} revoked`)
      setSelected(new Set())
      await loadKeys()
    } catch (err) {
      toast.error('Bulk revoke failed', { description: err instanceof Error ? err.message : undefined })
    }
  }

  async function toggleUsage(id: string) {
    if (expandedId === id) {
      setExpandedId(null)
      return
    }
    setExpandedId(id)
    if (!usageByKey[id]) await loadUsage(id)
  }

  function openDetail(k: ApiKeyRow) {
    setDetailKey(k)
    if (!usageByKey[k.id]) loadUsage(k.id)
  }

  function copyToClipboard(text: string, message = 'Copied to clipboard') {
    navigator.clipboard.writeText(text)
    toast.success(message)
  }

  function copyIssuedKey(key: string) {
    navigator.clipboard.writeText(key)
    setJustCopied(true)
    toast.success('Copied to clipboard')
    setTimeout(() => setJustCopied(false), 1800)
  }

  const allSelected = filteredKeys.length > 0 && selected.size === filteredKeys.length
  const someSelected = selected.size > 0 && !allSelected

  return (
    <div className="flex min-h-full flex-col">
      <MobilePageHeader
        title="API Keys"
        subtitle="EA Mirror Feed Access"
        hidden
        icon={<KeyRound className="w-5 h-5" />}
      />

      <header className="hidden md:flex sticky top-0 z-40 w-full tech-header">
        <div className="max-w-[1400px] w-full mx-auto flex h-14 items-center justify-between px-6 gap-3">
          <div className="flex items-center gap-3">
            <div className="p-1.5 rounded-lg bg-primary/10 border border-primary/20">
              <KeyRound className="h-5 w-5 text-primary" />
            </div>
            <div className="flex flex-col">
              <h1 className="text-sm font-bold text-foreground leading-none">API Keys</h1>
              <p className="text-[10px] text-[#6b7288] font-bold uppercase tracking-wider mt-1">
                EA Mirror Feed Access
              </p>
            </div>
          </div>
          <Button onClick={() => { setIssuedKey(null); setCreateOpen(true) }} size="sm" className="font-semibold">
            <Plus className="w-4 h-4 mr-1" /> New Key
          </Button>
        </div>
      </header>

      <div className="flex-1 px-3 md:px-6 py-3 md:py-5">
        <div className="max-w-[1400px] mx-auto space-y-4">
          {/* Mobile-only create button */}
          <Button
            onClick={() => { setIssuedKey(null); setCreateOpen(true) }}
            className="md:hidden w-full font-bold h-11"
          >
            <Plus className="w-4 h-4 mr-1" /> New Key
          </Button>

          {/* Stat strip — one surface, divided columns, click to filter */}
          <div className="tech-card grid grid-cols-2 sm:grid-cols-4 divide-y sm:divide-y-0 sm:divide-x divide-border overflow-hidden">
            <StatTile label="Active" value={stats.active} icon={ShieldCheck} tone="success" active={statusFilter === 'active'} onClick={() => setStatusFilter(statusFilter === 'active' ? 'all' : 'active')} />
            <StatTile label="Expired" value={stats.expired} icon={Clock} tone="muted" active={statusFilter === 'expired'} onClick={() => setStatusFilter(statusFilter === 'expired' ? 'all' : 'expired')} />
            <StatTile label="Revoked" value={stats.revoked} icon={ShieldOff} tone="destructive" active={statusFilter === 'revoked'} onClick={() => setStatusFilter(statusFilter === 'revoked' ? 'all' : 'revoked')} />
            <StatTile label="Total Requests" value={stats.totalRequests} icon={Radio} tone="primary" />
          </div>

          {/* Keys card */}
          <div className="tech-card overflow-hidden">
            <div className="flex flex-col gap-3 px-4 sm:px-5 py-3.5 border-b border-border">
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <h2 className="text-sm font-bold flex items-center gap-2">
                    <KeyRound className="h-3.5 w-3.5" />
                    Issued Keys
                  </h2>
                  <p className="text-xs text-muted-foreground font-medium mt-0.5 hidden sm:block">
                    Per-customer keys authenticating EA connections to the mirror feed
                  </p>
                </div>
                {keys.length > 0 && (
                  <span className="tech-label bg-muted px-2 py-1 rounded-md shrink-0">
                    {filteredKeys.length === stats.total ? `${stats.total} total` : `${filteredKeys.length} of ${stats.total}`}
                  </span>
                )}
              </div>

              {keys.length > 0 && (
                <div className="flex flex-col sm:flex-row gap-2 sm:items-center">
                  <div className="relative flex-1 min-w-0">
                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                    <input
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      placeholder="Search by label or key prefix…"
                      className="w-full h-8 pl-8 pr-8 rounded-md border border-border bg-background dark:bg-card text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    />
                    {query && (
                      <button
                        onClick={() => setQuery('')}
                        className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    )}
                  </div>
                  <div className="flex items-center gap-1 overflow-x-auto no-scrollbar">
                    {(['all', 'active', 'expired', 'revoked'] as StatusFilter[]).map((f) => (
                      <button
                        key={f}
                        onClick={() => setStatusFilter(f)}
                        className={`px-2.5 py-1 rounded-md text-[11px] font-semibold whitespace-nowrap transition-colors ${
                          statusFilter === f ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground hover:bg-accent'
                        }`}
                      >
                        {f === 'all' ? 'All' : f.charAt(0).toUpperCase() + f.slice(1)}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {selected.size > 0 && (
                <div className="flex items-center gap-2 rounded-md border border-primary/30 bg-primary/5 px-3 py-2">
                  <span className="text-xs font-semibold text-primary">{selected.size} selected</span>
                  <div className="ml-auto flex items-center gap-2">
                    <Button variant="outline" size="sm" className="h-7 text-xs" onClick={bulkRevoke}>
                      <Ban className="w-3 h-3 mr-1" /> Revoke selected
                    </Button>
                    <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => setSelected(new Set())}>
                      Clear
                    </Button>
                  </div>
                </div>
              )}
            </div>

            {loading ? (
              <div className="py-16 flex flex-col items-center justify-center gap-2 text-muted-foreground">
                <div className="h-5 w-5 rounded-full border-2 border-primary/30 border-t-primary animate-spin" />
                <p className="text-sm font-medium">Loading keys…</p>
              </div>
            ) : keys.length === 0 ? (
              <div className="py-16 px-6 flex flex-col items-center justify-center gap-3 text-center">
                <div className="p-3 rounded-full bg-primary/10 border border-primary/20">
                  <KeyRound className="h-6 w-6 text-primary" />
                </div>
                <div className="space-y-1">
                  <p className="text-sm font-bold text-foreground">No keys yet</p>
                  <p className="text-xs text-muted-foreground max-w-sm">
                    Create one to give a customer&apos;s EA access to the mirror feed.
                  </p>
                </div>
                <Button onClick={() => { setIssuedKey(null); setCreateOpen(true) }} size="sm" className="mt-1 font-semibold">
                  <Plus className="w-4 h-4 mr-1" /> New Key
                </Button>
              </div>
            ) : filteredKeys.length === 0 ? (
              <div className="py-16 px-6 flex flex-col items-center justify-center gap-3 text-center">
                <div className="p-3 rounded-full bg-muted">
                  <Search className="h-6 w-6 text-muted-foreground" />
                </div>
                <div className="space-y-1">
                  <p className="text-sm font-bold text-foreground">No matching keys</p>
                  <p className="text-xs text-muted-foreground max-w-sm">
                    Try a different search term or clear the status filter.
                  </p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => { setQuery(''); setStatusFilter('all') }}
                >
                  Clear filters
                </Button>
              </div>
            ) : (
              <>
                {/* Table — desktop/wide only, avoids cramped overflow at tablet widths */}
                <div className="hidden lg:block overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border/70 bg-muted/30">
                        <th className="w-10 pl-5 pr-1 py-2.5">
                          <input
                            type="checkbox"
                            checked={allSelected}
                            ref={(el) => { if (el) el.indeterminate = someSelected }}
                            onChange={toggleSelectAll}
                            className="h-3.5 w-3.5 rounded border-border accent-primary cursor-pointer"
                          />
                        </th>
                        <SortableHead label="Label" col="label" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} className="text-left pr-3" />
                        <th className="py-2.5 px-3 text-left font-semibold text-[10px] uppercase tracking-widest text-muted-foreground whitespace-nowrap">Key</th>
                        <th className="py-2.5 px-3 text-left font-semibold text-[10px] uppercase tracking-widest text-muted-foreground whitespace-nowrap">Status</th>
                        <th className="py-2.5 px-3 text-left font-semibold text-[10px] uppercase tracking-widest text-muted-foreground whitespace-nowrap">Expires</th>
                        <SortableHead label="Last used" col="lastUsedAt" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} className="text-left px-3" />
                        <SortableHead label="Requests" col="requestCount" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} className="text-right px-3" />
                        <th className="py-2.5 pl-3 pr-5 text-right font-semibold text-[10px] uppercase tracking-widest text-muted-foreground whitespace-nowrap">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredKeys.map((k) => (
                        <Fragment key={k.id}>
                          <tr className={`group border-b border-border/50 last:border-0 hover:bg-primary/5 transition-colors ${selected.has(k.id) ? 'bg-primary/5' : ''}`}>
                            <td className="pl-5 pr-1 py-3">
                              <input
                                type="checkbox"
                                checked={selected.has(k.id)}
                                onChange={() => toggleSelected(k.id)}
                                className="h-3.5 w-3.5 rounded border-border accent-primary cursor-pointer"
                              />
                            </td>
                            <td className="py-3 pr-3">
                              <button onClick={() => openDetail(k)} className="font-semibold hover:text-primary transition-colors text-left">
                                {k.label}
                              </button>
                            </td>
                            <td className="py-3 px-3">
                              <button
                                onClick={() => copyToClipboard(k.keyPrefix, 'Key prefix copied')}
                                className="group/key inline-flex items-center gap-1 font-mono text-xs bg-muted hover:bg-accent px-1.5 py-0.5 rounded border border-border/60 transition-colors"
                                title="Copy key prefix"
                              >
                                {k.keyPrefix}…
                                <Copy className="w-2.5 h-2.5 opacity-0 group-hover/key:opacity-60 transition-opacity" />
                              </button>
                            </td>
                            <td className="py-3 px-3"><StatusPill status={k.status} /></td>
                            <td className="py-3 px-3 text-xs text-muted-foreground">
                              {k.expiresAt ? formatDate(k.expiresAt) : <span className="italic">Never</span>}
                            </td>
                            <td className="py-3 px-3 text-xs">
                              {k.lastUsedAt ? (
                                <div className="flex flex-col gap-0.5">
                                  <span className="text-foreground/80">{formatDate(k.lastUsedAt)}</span>
                                  <span className="font-mono text-[10px] text-muted-foreground/70">{k.lastUsedIp ?? 'unknown ip'}</span>
                                </div>
                              ) : (
                                <span className="italic text-muted-foreground">Never</span>
                              )}
                            </td>
                            <td className="py-3 px-3 text-right font-mono font-semibold tabular-nums">
                              {k.requestCount.toLocaleString()}
                            </td>
                            <td className="py-3 pl-3 pr-5">
                              <div className="flex items-center justify-end gap-1 opacity-70 group-hover:opacity-100 transition-opacity">
                                <button
                                  onClick={() => toggleUsage(k.id)}
                                  title="Connection log"
                                  className={`h-8 w-8 inline-flex items-center justify-center rounded-md hover:bg-muted transition-colors ${expandedId === k.id ? 'bg-muted text-primary' : ''}`}
                                >
                                  {expandedId === k.id ? <ChevronUp className="w-3.5 h-3.5" /> : <Activity className="w-3.5 h-3.5" />}
                                </button>
                                {k.status === 'revoked' ? (
                                  <button
                                    onClick={() => reactivateKey(k.id)}
                                    title="Reactivate"
                                    className="h-8 w-8 inline-flex items-center justify-center rounded-md hover:bg-success/10 hover:text-success transition-colors"
                                  >
                                    <RotateCcw className="w-3.5 h-3.5" />
                                  </button>
                                ) : (
                                  <button
                                    onClick={() => revokeKey(k.id)}
                                    title="Revoke"
                                    className="h-8 w-8 inline-flex items-center justify-center rounded-md hover:bg-destructive/10 hover:text-destructive transition-colors"
                                  >
                                    <Ban className="w-3.5 h-3.5" />
                                  </button>
                                )}
                                <button
                                  onClick={() => deleteKey(k.id)}
                                  title="Delete permanently"
                                  className="h-8 w-8 inline-flex items-center justify-center rounded-md hover:bg-destructive/10 hover:text-destructive transition-colors"
                                >
                                  <Trash2 className="w-3.5 h-3.5" />
                                </button>
                              </div>
                            </td>
                          </tr>
                          {expandedId === k.id && (
                            <tr className="border-b border-border/50 last:border-0 bg-muted/20">
                              <td colSpan={8} className="px-5 py-3">
                                <UsagePanel loading={usageLoading === k.id} rows={usageByKey[k.id]?.slice(0, 25)} />
                                {(usageByKey[k.id]?.length ?? 0) > 0 && (
                                  <button
                                    onClick={() => openDetail(k)}
                                    className="mt-2 text-xs font-semibold text-primary hover:underline"
                                  >
                                    View full connection log & details →
                                  </button>
                                )}
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Cards — used below the lg breakpoint so nothing overflows/clips at tablet widths */}
                <div className="lg:hidden divide-y divide-border">
                  {filteredKeys.map((k) => (
                    <div key={k.id} className="p-4 space-y-3">
                      <div className="flex items-start justify-between gap-2">
                        <button onClick={() => openDetail(k)} className="min-w-0 text-left">
                          <p className="text-sm font-bold text-foreground truncate hover:text-primary transition-colors">{k.label}</p>
                          <p className="font-mono text-[11px] text-muted-foreground mt-0.5">{k.keyPrefix}…</p>
                        </button>
                        <StatusPill status={k.status} />
                      </div>
                      <div className="grid grid-cols-2 gap-y-2 text-xs">
                        <div>
                          <p className="text-muted-foreground">Expires</p>
                          <p className="font-medium">{k.expiresAt ? formatDate(k.expiresAt) : 'Never'}</p>
                        </div>
                        <div>
                          <p className="text-muted-foreground">Requests</p>
                          <p className="font-medium font-mono">{k.requestCount.toLocaleString()}</p>
                        </div>
                        <div className="col-span-2">
                          <p className="text-muted-foreground">Last used</p>
                          <p className="font-medium">
                            {k.lastUsedAt ? `${formatDate(k.lastUsedAt)} · ${k.lastUsedIp ?? 'unknown ip'}` : 'Never'}
                          </p>
                        </div>
                      </div>
                      <div className="flex items-center gap-2 pt-1">
                        <button
                          onClick={() => toggleUsage(k.id)}
                          className="flex-1 h-9 rounded-md border border-border text-xs font-semibold inline-flex items-center justify-center gap-1.5"
                        >
                          <Activity className="w-3.5 h-3.5" />
                          Log
                          {expandedId === k.id ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                        </button>
                        {k.status === 'revoked' ? (
                          <button onClick={() => reactivateKey(k.id)} className="h-9 w-9 rounded-md border border-border inline-flex items-center justify-center text-success">
                            <RotateCcw className="w-3.5 h-3.5" />
                          </button>
                        ) : (
                          <button onClick={() => revokeKey(k.id)} className="h-9 w-9 rounded-md border border-border inline-flex items-center justify-center">
                            <Ban className="w-3.5 h-3.5" />
                          </button>
                        )}
                        <button onClick={() => deleteKey(k.id)} className="h-9 w-9 rounded-md border border-border inline-flex items-center justify-center text-destructive">
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                      {expandedId === k.id && (
                        <>
                          <UsagePanel loading={usageLoading === k.id} rows={usageByKey[k.id]?.slice(0, 25)} />
                          {(usageByKey[k.id]?.length ?? 0) > 0 && (
                            <button
                              onClick={() => openDetail(k)}
                              className="text-xs font-semibold text-primary hover:underline"
                            >
                              View full connection log & details →
                            </button>
                          )}
                        </>
                      )}
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Create-key dialog */}
      <Dialog open={createOpen} onOpenChange={(open) => { setCreateOpen(open); if (!open) setIssuedKey(null) }}>
        <DialogContent>
          {issuedKey ? (
            <>
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2">
                  <div className="p-1.5 rounded-lg bg-success/10 border border-success/25">
                    <ShieldCheck className="w-4 h-4 text-success" />
                  </div>
                  Key created for &quot;{issuedKey.label}&quot;
                </DialogTitle>
                <DialogDescription>
                  Copy this now — it is shown only once and cannot be retrieved again. If you lose it,
                  revoke this key and issue a new one.
                </DialogDescription>
              </DialogHeader>
              <div className="flex items-center gap-2 rounded-md border border-border bg-muted p-3">
                <code className="flex-1 text-xs break-all font-mono">{issuedKey.key}</code>
                <Button size="sm" variant={justCopied ? 'default' : 'outline'} onClick={() => copyIssuedKey(issuedKey.key)}>
                  {justCopied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
                </Button>
              </div>
              <div className="flex items-start gap-2 rounded-md border border-gold/30 bg-gold/10 p-3">
                <AlertTriangle className="w-3.5 h-3.5 text-gold mt-0.5 shrink-0" />
                <p className="text-xs text-gold font-medium">
                  Give this to the customer as their EA&apos;s <code className="font-mono">InpApiKey</code> input value.
                </p>
              </div>
              <DialogFooter>
                <Button onClick={() => { setCreateOpen(false); setIssuedKey(null) }} className="font-semibold">Done</Button>
              </DialogFooter>
            </>
          ) : (
            <>
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2">
                  <div className="p-1.5 rounded-lg bg-primary/10 border border-primary/20">
                    <KeyRound className="w-4 h-4 text-primary" />
                  </div>
                  New API key
                </DialogTitle>
                <DialogDescription>Issue a key for one customer/EA instance.</DialogDescription>
              </DialogHeader>
              <div className="space-y-3">
                <div className="space-y-1.5">
                  <Label htmlFor="key-label" className="text-sm font-semibold">Label (customer name / note)</Label>
                  <Input
                    id="key-label"
                    value={newLabel}
                    onChange={(e) => setNewLabel(e.target.value)}
                    placeholder="e.g. john.doe@example.com"
                    autoFocus
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="key-expires" className="text-sm font-semibold">Expires (optional)</Label>
                  <Input
                    id="key-expires"
                    type="date"
                    value={newExpiresAt}
                    onChange={(e) => setNewExpiresAt(e.target.value)}
                  />
                  <p className="text-xs text-muted-foreground">Leave blank for a key that never expires.</p>
                </div>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setCreateOpen(false)}>Cancel</Button>
                <Button onClick={createKey} disabled={creating} className="font-semibold">
                  {creating ? 'Creating…' : 'Create key'}
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>

      {/* Detail drawer */}
      <Dialog open={!!detailKey} onOpenChange={(open) => { if (!open) setDetailKey(null) }}>
        <DialogContent className="max-w-2xl max-h-[85vh] flex flex-col">
          {detailKey && (
            <KeyDetail
              apiKey={detailKey}
              usage={usageByKey[detailKey.id]}
              usageLoading={usageLoading === detailKey.id}
              onCopy={copyToClipboard}
              onRevoke={() => { revokeKey(detailKey.id); setDetailKey(null) }}
              onReactivate={() => { reactivateKey(detailKey.id); setDetailKey(null) }}
              onDelete={() => { deleteKey(detailKey.id); setDetailKey(null) }}
            />
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}

function SortableHead({
  label,
  col,
  sortKey,
  sortDir,
  onClick,
  className = '',
}: {
  label: string
  col: SortKey
  sortKey: SortKey
  sortDir: 'asc' | 'desc'
  onClick: (col: SortKey) => void
  className?: string
}) {
  const active = sortKey === col
  return (
    <th className={`py-2.5 px-3 font-semibold text-[10px] uppercase tracking-widest text-muted-foreground whitespace-nowrap ${className}`}>
      <button
        onClick={() => onClick(col)}
        className={`inline-flex items-center gap-1 hover:text-foreground transition-colors ${active ? 'text-foreground' : ''}`}
      >
        {label}
        {active ? (
          sortDir === 'asc' ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />
        ) : (
          <ArrowUpDown className="w-3 h-3 opacity-30" />
        )}
      </button>
    </th>
  )
}

function StatTile({
  label,
  value,
  icon: Icon,
  tone,
  active,
  onClick,
}: {
  label: string
  value: number
  icon: typeof ShieldCheck
  tone: 'success' | 'muted' | 'destructive' | 'primary'
  active?: boolean
  onClick?: () => void
}) {
  const toneClasses: Record<typeof tone, string> = {
    success: 'bg-success/10 text-success',
    muted: 'bg-muted text-muted-foreground',
    destructive: 'bg-destructive/10 text-destructive',
    primary: 'bg-primary/10 text-primary',
  }
  const Comp = onClick ? 'button' : 'div'
  return (
    <Comp
      onClick={onClick}
      className={`flex items-center gap-3 p-4 text-left transition-colors ${onClick ? 'hover:bg-accent/50 cursor-pointer' : ''} ${active ? 'bg-accent/60' : ''}`}
    >
      <div className={`p-2 rounded-lg shrink-0 ${toneClasses[tone]}`}>
        <Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0">
        <p className="text-xl font-black tabular-nums leading-none">{value.toLocaleString()}</p>
        <p className="tech-label mt-1">{label}</p>
      </div>
    </Comp>
  )
}

function UsagePanel({ loading, rows }: { loading: boolean; rows: UsageRow[] | undefined }) {
  if (loading) {
    return <p className="text-sm text-muted-foreground py-3">Loading…</p>
  }
  if (!rows || rows.length === 0) {
    return <p className="text-sm text-muted-foreground py-3">No requests recorded for this key yet.</p>
  }
  return (
    <div className="rounded-lg border border-border/60 bg-card/60 divide-y divide-border/40 overflow-hidden max-h-64 overflow-y-auto">
      {rows.map((u) => (
        <div key={u.id} className="flex items-center gap-3 font-mono text-[11px] px-3 py-2">
          <span className="text-muted-foreground w-32 shrink-0" title={`First seen ${formatDate(u.createdAt)}`}>
            {formatDate(u.lastSeenAt)}
          </span>
          <span className="w-28 shrink-0">{u.ip ?? 'unknown ip'}</span>
          <span className="w-16 shrink-0 text-right tabular-nums text-muted-foreground" title="Requests from this IP">
            {u.hits.toLocaleString()}×
          </span>
          <span className="flex-1 truncate text-muted-foreground" title={u.userAgent ?? ''}>
            {u.userAgent ?? '—'}
          </span>
          <span className={`text-[10px] font-bold rounded px-1.5 py-0.5 shrink-0 ${u.status === 'ok' ? 'text-success bg-success/10' : 'text-destructive bg-destructive/10'}`}>
            {u.status}
          </span>
        </div>
      ))}
    </div>
  )
}

function KeyDetail({
  apiKey,
  usage,
  usageLoading,
  onCopy,
  onRevoke,
  onReactivate,
  onDelete,
}: {
  apiKey: ApiKeyRow
  usage: UsageRow[] | undefined
  usageLoading: boolean
  onCopy: (text: string, message?: string) => void
  onRevoke: () => void
  onReactivate: () => void
  onDelete: () => void
}) {
  const okCount = usage?.reduce((n, u) => n + (u.status === 'ok' ? u.hits : 0), 0) ?? 0
  const errCount = usage?.reduce((n, u) => n + (u.status === 'ok' ? 0 : u.hits), 0) ?? 0
  const uniqueIps = new Set((usage ?? []).map((u) => u.ip).filter(Boolean)).size

  return (
    <>
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2">
          <div className="p-1.5 rounded-lg bg-primary/10 border border-primary/20">
            <KeyRound className="w-4 h-4 text-primary" />
          </div>
          <span className="truncate">{apiKey.label}</span>
          <StatusPill status={apiKey.status} />
        </DialogTitle>
      </DialogHeader>

      <div className="overflow-y-auto flex-1 -mx-6 px-6 space-y-4">
        {/* Metadata grid */}
        <div className="grid grid-cols-2 gap-3">
          <DetailField icon={Fingerprint} label="Key prefix">
            <button
              onClick={() => onCopy(apiKey.keyPrefix, 'Key prefix copied')}
              className="inline-flex items-center gap-1 font-mono text-xs hover:text-primary transition-colors"
            >
              {apiKey.keyPrefix}… <Copy className="w-3 h-3 opacity-50" />
            </button>
          </DetailField>
          <DetailField icon={Hash} label="Key ID">
            <button
              onClick={() => onCopy(apiKey.id, 'Key ID copied')}
              className="inline-flex items-center gap-1 font-mono text-xs hover:text-primary transition-colors truncate"
            >
              <span className="truncate">{apiKey.id}</span> <Copy className="w-3 h-3 opacity-50 shrink-0" />
            </button>
          </DetailField>
          <DetailField icon={Calendar} label="Created">
            <span className="text-xs">{formatDate(apiKey.createdAt)}</span>
          </DetailField>
          <DetailField icon={Clock} label="Expires">
            <span className="text-xs">{apiKey.expiresAt ? formatDate(apiKey.expiresAt) : 'Never'}</span>
          </DetailField>
          {apiKey.revokedAt && (
            <DetailField icon={ShieldOff} label="Revoked">
              <span className="text-xs text-destructive">{formatDate(apiKey.revokedAt)}</span>
            </DetailField>
          )}
          <DetailField icon={Globe} label="Last IP">
            <span className="font-mono text-xs">{apiKey.lastUsedIp ?? '—'}</span>
          </DetailField>
        </div>

        {/* Quick stats from loaded usage */}
        <div className="grid grid-cols-3 gap-2">
          <div className="rounded-lg border border-border bg-muted/30 p-3 text-center">
            <p className="text-lg font-black tabular-nums">{apiKey.requestCount.toLocaleString()}</p>
            <p className="tech-label mt-0.5">Lifetime Requests</p>
          </div>
          <div className="rounded-lg border border-border bg-muted/30 p-3 text-center">
            <p className="text-lg font-black tabular-nums text-success">{okCount}</p>
            <p className="tech-label mt-0.5">OK (logged)</p>
          </div>
          <div className="rounded-lg border border-border bg-muted/30 p-3 text-center">
            <p className={`text-lg font-black tabular-nums ${errCount > 0 ? 'text-destructive' : ''}`}>{errCount}</p>
            <p className="tech-label mt-0.5">Errors (logged)</p>
          </div>
        </div>

        {/* Connection log */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-xs font-bold uppercase tracking-widest text-muted-foreground flex items-center gap-1.5">
              <Activity className="w-3 h-3" />
              Connection Log
            </h3>
            {uniqueIps > 0 && (
              <span className="text-[10px] text-muted-foreground font-medium">{uniqueIps} unique IP{uniqueIps !== 1 ? 's' : ''}</span>
            )}
          </div>
          <UsagePanel loading={usageLoading} rows={usage} />
        </div>
      </div>

      <DialogFooter className="gap-2 sm:gap-2">
        <Button variant="destructive" size="sm" onClick={onDelete} className="mr-auto">
          <Trash2 className="w-3.5 h-3.5 mr-1" /> Delete
        </Button>
        {apiKey.status === 'revoked' ? (
          <Button variant="outline" size="sm" onClick={onReactivate}>
            <RotateCcw className="w-3.5 h-3.5 mr-1 text-success" /> Reactivate
          </Button>
        ) : (
          <Button variant="outline" size="sm" onClick={onRevoke}>
            <Ban className="w-3.5 h-3.5 mr-1" /> Revoke
          </Button>
        )}
      </DialogFooter>
    </>
  )
}

function DetailField({
  icon: Icon,
  label,
  children,
}: {
  icon: typeof ShieldCheck
  label: string
  children: React.ReactNode
}) {
  return (
    <div className="rounded-lg border border-border bg-muted/20 px-3 py-2">
      <p className="tech-label flex items-center gap-1 mb-1">
        <Icon className="w-2.5 h-2.5" />
        {label}
      </p>
      {children}
    </div>
  )
}
