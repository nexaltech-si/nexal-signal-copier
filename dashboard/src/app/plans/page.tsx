'use client'

import { useState, useEffect, useCallback } from 'react'
import { Layers, RefreshCw, Trash2, CheckSquare, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useToast } from '@/hooks/use-toast'
import PlanCard from '@/components/PlanCard'
import MobilePageHeader from '@/components/MobilePageHeader'
import type { TradePlanWithSignal } from '@/lib/types'

const STATUS_FILTERS = [
  { label: 'All', value: '' },
  { label: 'Watching', value: 'WATCHING' },
  { label: 'Active', value: 'PRIMARY_ACTIVE' },
  { label: 'Fallback', value: 'FALLBACK_WATCHING' },
  { label: 'Expired', value: 'EXPIRED' },
  { label: 'Filtered', value: 'FILTERED' },
  { label: 'Cancelled', value: 'CANCELLED' },
]

export default function PlansPage() {
  const [plans, setPlans] = useState<TradePlanWithSignal[]>([])
  const [statusFilter, setStatusFilter] = useState('')
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [selectMode, setSelectMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [isDeleting, setIsDeleting] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const { toast } = useToast()

  const fetchPlans = useCallback(async () => {
    try {
      const params = new URLSearchParams({ limit: '100' })
      if (statusFilter) params.set('status', statusFilter)
      const res = await fetch(`/api/plans?${params}`)
      if (res.ok) setPlans(await res.json())
    } catch (e) {
      console.error('Error fetching plans:', e)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [statusFilter])

  useEffect(() => {
    fetchPlans()
  }, [fetchPlans])

  useEffect(() => {
    const id = setInterval(() => fetchPlans(), 30_000)
    return () => clearInterval(id)
  }, [fetchPlans])

  async function handleRefresh() {
    setRefreshing(true)
    await fetchPlans()
    toast({ title: 'Plans refreshed', description: 'Data is up to date.' })
  }

  function toggleSelectMode() {
    setSelectMode(v => !v)
    setSelectedIds(new Set())
    setConfirmDelete(false)
  }

  function handleSelect(id: string, checked: boolean) {
    setSelectedIds(prev => {
      const next = new Set(prev)
      checked ? next.add(id) : next.delete(id)
      return next
    })
  }

  function handleSelectAll() {
    const visible = [...activePlans, ...otherPlans]
    if (selectedIds.size === visible.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(visible.map(p => p.id)))
    }
  }

  async function handleBulkDelete() {
    if (!confirmDelete) {
      setConfirmDelete(true)
      return
    }
    setIsDeleting(true)
    try {
      const res = await fetch('/api/plans/bulk-delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: Array.from(selectedIds) }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error || 'Delete failed')
      toast({ title: `Deleted ${data.deleted} plan${data.deleted !== 1 ? 's' : ''}` })
      setSelectedIds(new Set())
      setSelectMode(false)
      setConfirmDelete(false)
      await fetchPlans()
    } catch (e: unknown) {
      toast({
        title: 'Delete failed',
        description: e instanceof Error ? e.message : 'Unknown error',
        variant: 'destructive',
      })
    } finally {
      setIsDeleting(false)
    }
  }

  const visiblePlans = statusFilter
    ? plans.filter(p => p.status === statusFilter)
    : plans

  const activePlans = plans.filter(p =>
    ['WATCHING', 'PRIMARY_ACTIVE', 'FALLBACK_WATCHING', 'FALLBACK_ACTIVE'].includes(p.status)
  )
  const otherPlans = plans.filter(p =>
    !['WATCHING', 'PRIMARY_ACTIVE', 'FALLBACK_WATCHING', 'FALLBACK_ACTIVE'].includes(p.status)
  )

  const allVisible = [...activePlans, ...otherPlans]
  const allSelected = allVisible.length > 0 && selectedIds.size === allVisible.length

  return (
    <div className="flex min-h-full flex-col">
      <MobilePageHeader
        title="Trade Plans"
        subtitle="Conditional Setups"
        hidden
        icon={<Layers className="h-5 w-5 text-primary" />}
      />

      {/* Desktop header */}
      <header className="hidden md:flex sticky top-0 z-40 w-full tech-header">
        <div className="max-w-[1800px] w-full mx-auto flex h-14 items-center px-6 gap-3">
          <div className="p-1.5 rounded-lg bg-primary/10 border border-primary/20">
            <Layers className="h-5 w-5 text-primary" />
          </div>
          <div>
            <h1 className="text-sm font-bold text-foreground leading-none">Trade Plans</h1>
            <p className="text-[10px] text-muted-foreground mt-0.5">Conditional multi-entry setups</p>
          </div>

          <div className="ml-auto flex items-center gap-2">
            <Button
              variant={selectMode ? 'default' : 'outline'}
              size="sm"
              onClick={toggleSelectMode}
              className={`h-8 text-xs ${selectMode ? 'bg-primary text-white' : ''}`}
            >
              <CheckSquare className="h-3.5 w-3.5 mr-1.5" />
              {selectMode ? 'Cancel Select' : 'Select'}
            </Button>
            <Button variant="outline" size="sm" onClick={handleRefresh} disabled={refreshing} className="h-8 text-xs">
              <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${refreshing ? 'animate-spin' : ''}`} />
              Refresh
            </Button>
          </div>
        </div>
      </header>

      <div className="flex-1 px-4 md:px-8 py-4 md:py-6 max-w-[1800px] mx-auto w-full">

        {/* Status filter tabs */}
        <div className="flex gap-1.5 flex-wrap mb-4">
          {STATUS_FILTERS.map(f => (
            <button
              key={f.value}
              onClick={() => setStatusFilter(f.value)}
              className={`px-3 py-1 rounded-full text-xs font-semibold transition-colors ${
                statusFilter === f.value
                  ? 'bg-primary text-white'
                  : 'bg-muted text-muted-foreground hover:bg-border'
              }`}
            >
              {f.label}
              {f.value === '' && plans.length > 0 && (
                <span className="ml-1 text-[10px] opacity-70">({plans.length})</span>
              )}
              {f.value !== '' && plans.filter(p => p.status === f.value).length > 0 && (
                <span className="ml-1 text-[10px] opacity-70">
                  ({plans.filter(p => p.status === f.value).length})
                </span>
              )}
            </button>
          ))}
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-24 text-muted-foreground/70 text-sm">
            <RefreshCw className="h-5 w-5 animate-spin mr-2" />
            Loading plans…
          </div>
        ) : plans.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-24 text-center">
            <div className="w-14 h-14 rounded-full bg-muted flex items-center justify-center mb-4">
              <Layers className="h-7 w-7 text-muted-foreground/70" />
            </div>
            <h3 className="font-semibold text-foreground/80 mb-1">No plans yet</h3>
            <p className="text-sm text-muted-foreground/70 max-w-xs">
              Conditional multi-entry setups from your signal channels will appear here automatically.
            </p>
          </div>
        ) : (
          <div className="space-y-6 pb-24">
            {/* Active plans section */}
            {activePlans.length > 0 && (
              <section>
                <h2 className="text-xs font-bold uppercase tracking-widest text-muted-foreground/70 mb-2">
                  Active Plans ({activePlans.length})
                </h2>
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                  {activePlans.map(plan => (
                    <PlanCard
                      key={plan.id}
                      plan={plan}
                      onUpdated={fetchPlans}
                      selectable={selectMode}
                      selected={selectedIds.has(plan.id)}
                      onSelect={handleSelect}
                    />
                  ))}
                </div>
              </section>
            )}

            {/* Historical plans section */}
            {otherPlans.length > 0 && (!statusFilter || !['WATCHING','PRIMARY_ACTIVE','FALLBACK_WATCHING','FALLBACK_ACTIVE'].includes(statusFilter)) && (
              <section>
                <h2 className="text-xs font-bold uppercase tracking-widest text-muted-foreground/70 mb-2">
                  History ({otherPlans.length})
                </h2>
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                  {otherPlans.map(plan => (
                    <PlanCard
                      key={plan.id}
                      plan={plan}
                      onUpdated={fetchPlans}
                      selectable={selectMode}
                      selected={selectedIds.has(plan.id)}
                      onSelect={handleSelect}
                    />
                  ))}
                </div>
              </section>
            )}
          </div>
        )}
      </div>

      {/* Bulk action bar */}
      {selectMode && (
        <div className="fixed bottom-0 left-0 right-0 z-50 border-t border-border bg-card/95 backdrop-blur-sm shadow-lg">
          <div className="max-w-[1800px] mx-auto px-4 md:px-8 py-3 flex items-center gap-3">
            <button
              onClick={handleSelectAll}
              className={`flex items-center justify-center w-5 h-5 rounded border-2 flex-shrink-0 transition-colors ${
                allSelected
                  ? 'bg-primary border-primary'
                  : 'bg-background border-muted-foreground/40 hover:border-primary/60'
              }`}
            >
              {allSelected && (
                <svg className="w-2.5 h-2.5 text-white" viewBox="0 0 10 8" fill="none">
                  <path d="M1 4l3 3 5-6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              )}
            </button>
            <span className="text-sm text-muted-foreground flex-1">
              {selectedIds.size === 0
                ? 'Select plans to delete'
                : `${selectedIds.size} plan${selectedIds.size !== 1 ? 's' : ''} selected`}
            </span>

            <Button
              variant="outline"
              size="sm"
              onClick={toggleSelectMode}
              className="h-8 text-xs"
            >
              <X className="h-3.5 w-3.5 mr-1" />
              Cancel
            </Button>

            <Button
              size="sm"
              onClick={handleBulkDelete}
              disabled={selectedIds.size === 0 || isDeleting}
              className={`h-8 text-xs ${
                confirmDelete
                  ? 'bg-destructive hover:bg-destructive/90 text-white'
                  : 'bg-rose-600 hover:bg-rose-700 text-white'
              }`}
            >
              {isDeleting ? (
                <RefreshCw className="h-3.5 w-3.5 animate-spin mr-1.5" />
              ) : (
                <Trash2 className="h-3.5 w-3.5 mr-1.5" />
              )}
              {confirmDelete ? 'Confirm Delete' : `Delete (${selectedIds.size})`}
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
