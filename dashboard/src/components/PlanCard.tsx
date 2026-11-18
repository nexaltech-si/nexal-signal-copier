'use client'

import { useState, useEffect } from 'react'
import {
  TrendingUp, TrendingDown, Clock, ImageIcon, X,
  Layers, ChevronDown, ChevronRight, Loader2,
  AlertTriangle, AlertCircle, Play, Ban, Pencil,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogDescription,
  DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Switch } from '@/components/ui/switch'
import { formatDate } from '@/lib/utils'
import type { TradePlanWithSignal } from '@/lib/types'
import TelegramText from '@/components/TelegramText'

interface PlanCardProps {
  plan: TradePlanWithSignal
  onUpdated?: () => void
  selectable?: boolean
  selected?: boolean
  onSelect?: (id: string, selected: boolean) => void
}

function getStatusBadge(status: string) {
  const map: Record<string, string> = {
    WATCHING:         'bg-gold/10 text-gold border border-gold/20',
    PRIMARY_ACTIVE:   'bg-success/10 text-success border border-success/20',
    FALLBACK_WATCHING:'bg-primary/10 text-primary border border-primary/20',
    FALLBACK_ACTIVE:  'bg-success/10 text-success border border-success/20',
    EXPIRED:          'bg-muted text-muted-foreground',
    FILTERED:         'bg-destructive/10 text-destructive border border-destructive/20',
    CANCELLED:        'bg-muted text-muted-foreground',
  }
  return map[status] ?? 'bg-muted text-muted-foreground'
}

function useCountdown(expiresAt: Date | string) {
  const [label, setLabel] = useState('')
  useEffect(() => {
    const calc = () => {
      const diff = new Date(expiresAt).getTime() - Date.now()
      if (diff <= 0) { setLabel('Expired'); return }
      const h = Math.floor(diff / 3_600_000)
      const m = Math.floor((diff % 3_600_000) / 60_000)
      setLabel(`${h}h ${m}m`)
    }
    calc()
    const id = setInterval(calc, 30_000)
    return () => clearInterval(id)
  }, [expiresAt])
  return label
}

function tpsToString(tpsJson: string | null | undefined): string {
  try {
    const arr = JSON.parse(tpsJson || '[]') as number[]
    return arr.join(', ')
  } catch { return '' }
}

export default function PlanCard({ plan, onUpdated, selectable, selected, onSelect }: PlanCardProps) {
  const [expanded, setExpanded] = useState(false)
  const [isImageOpen, setIsImageOpen] = useState(false)
  const [autoExecute, setAutoExecute] = useState(plan.autoExecute)
  const [executingLeg, setExecutingLeg] = useState<'primary' | 'fallback' | null>(null)
  const [isCancelling, setIsCancelling] = useState(false)
  const [isCancelOpen, setIsCancelOpen] = useState(false)
  const [isEditOpen, setIsEditOpen] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [imageError, setImageError] = useState(false)
  const countdown = useCountdown(plan.expiresAt)

  // Edit form state — pre-filled from plan
  const [editForm, setEditForm] = useState({
    primaryEntryMin: String(plan.primaryEntryMin ?? ''),
    primaryEntryMax: String(plan.primaryEntryMax ?? ''),
    primarySl: plan.primarySl ? String(plan.primarySl) : '',
    primaryTps: tpsToString(plan.primaryTps),
    primarySlCondition: plan.primarySlCondition ?? '',
    fallbackEntryMin: plan.fallbackEntryMin ? String(plan.fallbackEntryMin) : '',
    fallbackEntryMax: plan.fallbackEntryMax ? String(plan.fallbackEntryMax) : '',
    fallbackSl: plan.fallbackSl ? String(plan.fallbackSl) : '',
    fallbackTps: tpsToString(plan.fallbackTps),
  })

  const isBuy = plan.orderType?.toUpperCase() === 'BUY'
  const hasImage = plan.signal?.hasImage
  const primaryTps: number[] = JSON.parse(plan.primaryTps || '[]')
  const fallbackTps: number[] = JSON.parse(plan.fallbackTps || '[]')

  const canExecutePrimary = plan.status === 'WATCHING'
  const canExecuteFallback = plan.status === 'FALLBACK_WATCHING'
  const isActive = ['WATCHING', 'PRIMARY_ACTIVE', 'FALLBACK_WATCHING', 'FALLBACK_ACTIVE'].includes(plan.status)

  async function handleAutoToggle(checked: boolean) {
    setAutoExecute(checked)
    await fetch(`/api/plans/${plan.id}/auto-execute`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ autoExecute: checked }),
    })
  }

  async function handleExecute(leg: 'primary' | 'fallback') {
    setError(null)
    setExecutingLeg(leg)
    try {
      const res = await fetch(`/api/plans/${plan.id}/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ leg }),
      })
      if (!res.ok) throw new Error(await res.text())
      onUpdated?.()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Execution failed')
    } finally {
      setExecutingLeg(null)
    }
  }

  async function handleCancel() {
    setIsCancelling(true)
    try {
      await fetch(`/api/plans/${plan.id}/cancel`, { method: 'POST' })
      setIsCancelOpen(false)
      onUpdated?.()
    } catch {
      setError('Failed to cancel plan')
    } finally {
      setIsCancelling(false)
    }
  }

  async function handleSaveEdit() {
    setIsSaving(true)
    setError(null)
    try {
      const body: Record<string, string | number> = {}
      if (editForm.primaryEntryMin) body.primaryEntryMin = parseFloat(editForm.primaryEntryMin)
      if (editForm.primaryEntryMax) body.primaryEntryMax = parseFloat(editForm.primaryEntryMax)
      if (editForm.primarySl) body.primarySl = parseFloat(editForm.primarySl)
      if (editForm.primaryTps) body.primaryTps = editForm.primaryTps
      if (editForm.primarySlCondition !== undefined) body.primarySlCondition = editForm.primarySlCondition
      if (editForm.fallbackEntryMin) body.fallbackEntryMin = parseFloat(editForm.fallbackEntryMin)
      if (editForm.fallbackEntryMax) body.fallbackEntryMax = parseFloat(editForm.fallbackEntryMax)
      if (editForm.fallbackSl) body.fallbackSl = parseFloat(editForm.fallbackSl)
      if (editForm.fallbackTps) body.fallbackTps = editForm.fallbackTps

      const res = await fetch(`/api/plans/${plan.id}/update`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) {
        const data = await res.json()
        throw new Error(data.error || 'Save failed')
      }
      setIsEditOpen(false)
      onUpdated?.()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <div
      className={`relative rounded-lg border bg-card transition-all hover:shadow-sm ${
        selectable ? 'cursor-pointer' : ''
      } ${selected ? 'border-primary ring-1 ring-primary/30' : 'border-border'}`}
      onClick={selectable ? () => onSelect?.(plan.id, !selected) : undefined}
    >
      {/* Selection checkbox */}
      {selectable && (
        <div className="absolute top-2.5 left-2.5 z-10">
          <div
            className={`w-4 h-4 rounded border-2 flex items-center justify-center transition-colors ${
              selected
                ? 'bg-primary border-primary'
                : 'bg-background border-muted-foreground/40'
            }`}
          >
            {selected && (
              <svg className="w-2.5 h-2.5 text-white" viewBox="0 0 10 8" fill="none">
                <path d="M1 4l3 3 5-6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            )}
          </div>
        </div>
      )}

      {/* Header */}
      <div className={`p-3 ${selectable ? 'pl-8' : ''}`}>
        <div className="flex items-start md:items-center justify-between gap-2 mb-2">
          <div className="flex items-center gap-2 min-w-0 flex-1">
            <button
              onClick={selectable ? (e) => { e.stopPropagation(); setExpanded(!expanded) } : () => setExpanded(!expanded)}
              className="flex items-center justify-center w-5 h-5 rounded hover:bg-muted flex-shrink-0"
            >
              {expanded
                ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground/70" />
                : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/70" />}
            </button>

            <div className={`flex items-center justify-center w-7 h-7 rounded-md ${isBuy ? 'bg-success/10' : 'bg-destructive/10'}`}>
              {isBuy
                ? <TrendingUp className="h-4 w-4 text-success" />
                : <TrendingDown className="h-4 w-4 text-destructive" />}
            </div>

            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5 flex-wrap">
                <Layers className="h-3.5 w-3.5 text-muted-foreground/70" />
                <span className="font-bold text-sm text-foreground">{plan.symbol}</span>
                <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-4 font-semibold border-border text-foreground/80">
                  {plan.orderType}
                </Badge>
              </div>
              {plan.signal?.channelName && (
                <span className="text-[10px] text-muted-foreground block truncate max-w-[150px]">
                  {plan.signal.channelName}
                </span>
              )}
            </div>
          </div>

          <div className="flex flex-col md:flex-row items-end md:items-center gap-1 md:gap-2 flex-shrink-0" onClick={selectable ? e => e.stopPropagation() : undefined}>
            <Badge className={`${getStatusBadge(plan.status)} text-[10px] px-1.5 py-0 h-4 font-semibold`}>
              {plan.status.replace('_', ' ')}
            </Badge>

            {/* Auto-execute toggle */}
            {isActive && !selectable && (
              <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
                <span>Auto</span>
                <Switch
                  checked={autoExecute}
                  onCheckedChange={handleAutoToggle}
                  className="h-4 w-7 data-[state=checked]:bg-emerald-500"
                />
              </div>
            )}

            {hasImage && !selectable && (
              <Button variant="ghost" size="sm"
                onClick={() => setIsImageOpen(true)}
                className="h-6 w-6 p-0 hover:bg-primary/10 hover:text-primary"
              >
                <ImageIcon className="h-3 w-3" />
              </Button>
            )}

            {isActive && !selectable && (
              <Button variant="ghost" size="sm"
                onClick={() => { setError(null); setIsEditOpen(true) }}
                className="h-6 w-6 p-0 hover:bg-accent hover:text-muted-foreground"
                title="Edit plan"
              >
                <Pencil className="h-3 w-3" />
              </Button>
            )}

            {isActive && !selectable && (
              <Button variant="ghost" size="sm"
                onClick={() => setIsCancelOpen(true)}
                className="h-6 w-6 p-0 hover:bg-destructive/10 hover:text-destructive"
                title="Cancel plan"
              >
                <Ban className="h-3 w-3" />
              </Button>
            )}
          </div>
        </div>

        {/* Price summary row */}
        <div className="flex items-center gap-3 text-xs flex-wrap mb-2">
          <div className="flex items-center gap-1">
            <span className="text-muted-foreground font-medium">Zone</span>
            <span className="font-mono font-semibold text-foreground">
              {plan.primaryEntryMin} – {plan.primaryEntryMax}
            </span>
          </div>
          <div className="flex items-center gap-1">
            <span className="text-muted-foreground font-medium">SL</span>
            {plan.primarySl ? (
              <span className="font-mono font-semibold text-destructive">{plan.primarySl}</span>
            ) : (
              <span className="font-semibold text-gold flex items-center gap-0.5">
                <AlertTriangle className="h-3 w-3" />
                No SL
              </span>
            )}
          </div>
          {plan.fallbackEntryMin && (
            <div className="flex items-center gap-1">
              <span className="text-muted-foreground font-medium">Fallback</span>
              <span className="font-mono font-semibold text-sky-700">
                {plan.fallbackEntryMin} – {plan.fallbackEntryMax}
              </span>
            </div>
          )}
        </div>

        {/* Execute buttons */}
        <div className="flex items-center gap-2 flex-wrap" onClick={selectable ? e => e.stopPropagation() : undefined}>
          {canExecutePrimary && (
            <Button size="sm"
              onClick={() => handleExecute('primary')}
              disabled={!!executingLeg}
              className="h-7 text-xs px-3 bg-emerald-600 hover:bg-emerald-700 text-white"
            >
              {executingLeg === 'primary'
                ? <Loader2 className="h-3 w-3 animate-spin mr-1" />
                : <Play className="h-3 w-3 mr-1" />}
              Execute Primary
            </Button>
          )}
          {canExecuteFallback && (
            <Button size="sm"
              onClick={() => handleExecute('fallback')}
              disabled={!!executingLeg}
              className="h-7 text-xs px-3 bg-sky-600 hover:bg-sky-700 text-white"
            >
              {executingLeg === 'fallback'
                ? <Loader2 className="h-3 w-3 animate-spin mr-1" />
                : <Play className="h-3 w-3 mr-1" />}
              Execute Fallback
            </Button>
          )}
          {error && (
            <span className="text-[10px] text-destructive flex items-center gap-1">
              <AlertCircle className="h-3 w-3" />{error}
            </span>
          )}
        </div>

        {/* Expiry */}
        {isActive && (
          <div className="flex items-center gap-1 mt-2 text-[10px] text-muted-foreground/70">
            <Clock className="h-2.5 w-2.5" />
            <span>Expires in {countdown}</span>
            <span className="mx-1">·</span>
            <span>{formatDate(plan.createdAt)}</span>
          </div>
        )}
        {plan.filterReason && (
          <div className="mt-1 text-[10px] text-destructive flex items-center gap-1">
            <AlertTriangle className="h-3 w-3" />
            {plan.filterReason}
          </div>
        )}
      </div>

      {/* Expanded details */}
      {expanded && (
        <div className="border-t bg-muted/50/60 px-3.5 pb-3.5">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-3">
            {/* Signal image */}
            {hasImage && !imageError && (
              <button
                onClick={() => setIsImageOpen(true)}
                className="relative w-full h-40 rounded-lg overflow-hidden border border-border bg-muted hover:opacity-90 transition-opacity"
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={`/api/signals/${plan.signalId}/image`}
                  alt="Signal chart"
                  className="w-full h-full object-cover"
                  onError={() => setImageError(true)}
                />
                <div className="absolute inset-0 flex items-end justify-center pb-2">
                  <span className="text-[10px] text-white bg-black/50 px-2 py-0.5 rounded">Click to enlarge</span>
                </div>
              </button>
            )}

            {/* Formatted plan */}
            <div className="space-y-3 text-xs">
              {/* Primary */}
              <div className="bg-card rounded-lg border border-border p-2.5">
                <div className="font-semibold text-foreground/80 mb-1.5 flex items-center gap-1">
                  <div className="w-2 h-2 rounded-full bg-emerald-500" />
                  Primary Entry
                </div>
                <div className="space-y-1 font-mono">
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Zone</span>
                    <span className="font-semibold">{plan.primaryEntryMin} – {plan.primaryEntryMax}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Stop Loss</span>
                    {plan.primarySl ? (
                      <span className="text-destructive font-semibold">{plan.primarySl}</span>
                    ) : (
                      <span className="text-gold font-semibold flex items-center gap-1">
                        <AlertTriangle className="h-3 w-3" />
                        Not set — edit to add SL
                      </span>
                    )}
                  </div>
                  {plan.primarySlCondition && (
                    <div className="flex justify-between gap-2">
                      <span className="text-muted-foreground shrink-0">Condition</span>
                      <span className="text-foreground/80 text-right">{plan.primarySlCondition}</span>
                    </div>
                  )}
                  <div className="mt-1.5">
                    <span className="text-muted-foreground block mb-1">Take Profits</span>
                    <div className="flex flex-wrap gap-1">
                      {primaryTps.map((tp, i) => (
                        <span key={i} className="bg-success/10 text-success px-1.5 py-0.5 rounded text-[10px] font-semibold">
                          TP{i + 1}: {tp}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              </div>

              {/* Fallback */}
              {plan.fallbackEntryMin && (
                <div className="bg-card rounded-lg border border-border p-2.5">
                  <div className="font-semibold text-foreground/80 mb-1.5 flex items-center gap-1">
                    <div className="w-2 h-2 rounded-full bg-sky-500" />
                    Fallback Entry
                    <span className="text-[10px] text-muted-foreground/70 font-normal">(if primary SL hit)</span>
                  </div>
                  <div className="space-y-1 font-mono">
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Zone</span>
                      <span className="font-semibold">{plan.fallbackEntryMin} – {plan.fallbackEntryMax}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Stop Loss</span>
                      <span className="text-destructive font-semibold">{plan.fallbackSl}</span>
                    </div>
                    {fallbackTps.length > 0 && (
                      <div className="mt-1.5">
                        <span className="text-muted-foreground block mb-1">Take Profits</span>
                        <div className="flex flex-wrap gap-1">
                          {fallbackTps.map((tp, i) => (
                            <span key={i} className="bg-primary/8 text-sky-700 px-1.5 py-0.5 rounded text-[10px] font-semibold">
                              TP{i + 1}: {tp}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Raw message */}
          {plan.signal?.rawMessage && (
            <div className="mt-3">
              <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">
                Original Signal
              </div>
              <TelegramText text={plan.signal.rawMessage} className="bg-card p-2.5 rounded-lg text-[11px] leading-relaxed max-h-32 overflow-auto border border-border/50" />
            </div>
          )}
        </div>
      )}

      {/* Image modal */}
      {isImageOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
          onClick={() => setIsImageOpen(false)}
        >
          <div className="relative max-w-3xl max-h-[90vh] w-full mx-4" onClick={e => e.stopPropagation()}>
            <div className="bg-card rounded-xl shadow-2xl overflow-hidden">
              <div className="flex items-center justify-between px-4 py-2.5 border-b">
                <div className="flex items-center gap-2 text-sm font-semibold text-foreground/90">
                  <ImageIcon className="h-4 w-4 text-primary" />
                  Plan Signal — {plan.symbol} {plan.orderType}
                </div>
                <button onClick={() => setIsImageOpen(false)} className="p-1 rounded hover:bg-muted">
                  <X className="h-4 w-4 text-muted-foreground" />
                </button>
              </div>
              <div className="p-2 flex items-center justify-center bg-muted/50 max-h-[80vh] overflow-auto">
                {imageError ? (
                  <div className="flex flex-col items-center gap-2 py-8 text-muted-foreground">
                    <ImageIcon className="h-8 w-8 opacity-40" />
                    <span className="text-xs">Image unavailable</span>
                  </div>
                ) : (
                  /* eslint-disable-next-line @next/next/no-img-element */
                  <img
                    src={`/api/signals/${plan.signalId}/image`}
                    alt={`Plan signal for ${plan.symbol}`}
                    className="max-w-full max-h-[75vh] object-contain rounded"
                    onError={() => setImageError(true)}
                  />
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Edit dialog */}
      <Dialog open={isEditOpen} onOpenChange={setIsEditOpen}>
        <DialogContent className="sm:max-w-[480px] max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <div className="flex items-center gap-3 mb-1">
              <div className="w-9 h-9 rounded-full bg-accent flex items-center justify-center">
                <Pencil className="h-4 w-4 text-muted-foreground" />
              </div>
              <div>
                <DialogTitle>Edit Plan</DialogTitle>
                <DialogDescription className="text-xs">
                  {plan.symbol} {plan.orderType} — update SL, entry zone, or take profits
                </DialogDescription>
              </div>
            </div>
          </DialogHeader>

          <div className="space-y-4 py-2">
            {/* Primary entry */}
            <div>
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2 flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" />
                Primary Entry
              </p>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <Label className="text-xs text-muted-foreground mb-1 block">Zone Min</Label>
                  <Input
                    type="number"
                    value={editForm.primaryEntryMin}
                    onChange={e => setEditForm(f => ({ ...f, primaryEntryMin: e.target.value }))}
                    className="h-8 text-xs font-mono"
                    placeholder="e.g. 4430"
                  />
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground mb-1 block">Zone Max</Label>
                  <Input
                    type="number"
                    value={editForm.primaryEntryMax}
                    onChange={e => setEditForm(f => ({ ...f, primaryEntryMax: e.target.value }))}
                    className="h-8 text-xs font-mono"
                    placeholder="e.g. 4460"
                  />
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground mb-1 block">
                    Stop Loss <span className="text-destructive">*</span>
                  </Label>
                  <Input
                    type="number"
                    value={editForm.primarySl}
                    onChange={e => setEditForm(f => ({ ...f, primarySl: e.target.value }))}
                    className="h-8 text-xs font-mono border-rose-200 focus-visible:ring-rose-400"
                    placeholder="e.g. 4410"
                  />
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground mb-1 block">Take Profits (comma-sep)</Label>
                  <Input
                    value={editForm.primaryTps}
                    onChange={e => setEditForm(f => ({ ...f, primaryTps: e.target.value }))}
                    className="h-8 text-xs font-mono"
                    placeholder="e.g. 4495, 4542, 4595"
                  />
                </div>
              </div>
              <div className="mt-2">
                <Label className="text-xs text-muted-foreground mb-1 block">SL Condition (optional)</Label>
                <Input
                  value={editForm.primarySlCondition}
                  onChange={e => setEditForm(f => ({ ...f, primarySlCondition: e.target.value }))}
                  className="h-8 text-xs"
                  placeholder="e.g. or if 4 M15 candles close below 4420"
                />
              </div>
            </div>

            {/* Fallback entry */}
            <div>
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2 flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-sky-500 inline-block" />
                Fallback Entry <span className="font-normal text-muted-foreground/70 normal-case">(optional)</span>
              </p>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <Label className="text-xs text-muted-foreground mb-1 block">Zone Min</Label>
                  <Input
                    type="number"
                    value={editForm.fallbackEntryMin}
                    onChange={e => setEditForm(f => ({ ...f, fallbackEntryMin: e.target.value }))}
                    className="h-8 text-xs font-mono"
                    placeholder="e.g. 4380"
                  />
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground mb-1 block">Zone Max</Label>
                  <Input
                    type="number"
                    value={editForm.fallbackEntryMax}
                    onChange={e => setEditForm(f => ({ ...f, fallbackEntryMax: e.target.value }))}
                    className="h-8 text-xs font-mono"
                    placeholder="e.g. 4402"
                  />
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground mb-1 block">Stop Loss</Label>
                  <Input
                    type="number"
                    value={editForm.fallbackSl}
                    onChange={e => setEditForm(f => ({ ...f, fallbackSl: e.target.value }))}
                    className="h-8 text-xs font-mono border-rose-200 focus-visible:ring-rose-400"
                    placeholder="e.g. 4365"
                  />
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground mb-1 block">Take Profits (comma-sep)</Label>
                  <Input
                    value={editForm.fallbackTps}
                    onChange={e => setEditForm(f => ({ ...f, fallbackTps: e.target.value }))}
                    className="h-8 text-xs font-mono"
                    placeholder="e.g. 4495, 4542"
                  />
                </div>
              </div>
            </div>

            {error && (
              <div className="flex items-center gap-2 text-xs text-destructive bg-destructive/10 border border-rose-200 rounded-md p-2">
                <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                {error}
              </div>
            )}
          </div>

          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setIsEditOpen(false)} disabled={isSaving} className="text-xs">
              Cancel
            </Button>
            <Button
              onClick={handleSaveEdit}
              disabled={isSaving}
              className="text-xs bg-violet-600 hover:bg-violet-700 text-white"
            >
              {isSaving ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" /> : <Pencil className="h-3.5 w-3.5 mr-1.5" />}
              Save Changes
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Cancel confirmation */}
      <Dialog open={isCancelOpen} onOpenChange={setIsCancelOpen}>
        <DialogContent className="sm:max-w-[400px]">
          <DialogHeader>
            <div className="flex items-center gap-3 mb-2">
              <div className="w-10 h-10 rounded-full bg-destructive/10 flex items-center justify-center">
                <AlertTriangle className="h-6 w-6 text-destructive" />
              </div>
              <DialogTitle>Cancel Plan?</DialogTitle>
            </div>
            <DialogDescription>
              This will cancel the {plan.symbol} {plan.orderType} plan and stop watching for entry zones. Any already-placed trades remain open.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setIsCancelOpen(false)} disabled={isCancelling}>
              Keep Plan
            </Button>
            <Button variant="destructive" onClick={handleCancel} disabled={isCancelling}
              className="bg-rose-600 hover:bg-rose-700">
              {isCancelling ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
              Cancel Plan
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
