'use client'

import { useEffect, useMemo, useState } from 'react'
import * as DialogPrimitive from '@radix-ui/react-dialog'
import { AlertTriangle, ArrowRight, Loader2, Lock, Minus, Plus, Trash2, X, Zap } from 'lucide-react'
import { InstrumentSymbol } from '@/components/InstrumentSymbol'
import { getPipMultiplier, getPriceDigits, getOrderTypeLabel, isBuyType } from './mobile-trading-utils'

/** Pending order as returned by /api/mt5/orders (raw MT5 TradeOrder). */
export interface MobileOrder {
  ticket: number
  symbol: string
  type: number
  volume_initial: number
  volume?: number
  volume_current?: number
  price_open: number
  price_current?: number
  price_stoplimit?: number
  sl: number
  tp: number
  time_setup: string
  time_expiration?: number
  type_time?: number
  state?: number
}

/** Body accepted by /api/mt5/modify-order (mt5/app/routes/order.py). */
export interface ModifyOrderPayload {
  ticket: number
  price: number
  sl: number
  tp: number
  stoplimit_price?: number
  expiration?: string
}

// MT5 ORDER_STATE_*
const ORDER_STATE_LABELS: Record<number, string> = {
  0: 'Started', 1: 'Working', 3: 'Partially filled', 7: 'Placing', 8: 'Modifying', 9: 'Cancelling',
}

// MT5 timestamps are broker-server time encoded as epoch seconds, so they are
// displayed and parsed as UTC to round-trip exactly with the backend.
const epochToInput = (sec: number) => new Date(sec * 1000).toISOString().slice(0, 16)
const inputToIso = (v: string) => `${v}:00Z`

interface Change { label: string; from: string; to: string }

export default function MobileOrderEditSheet({
  order,
  saving,
  onClose,
  onSave,
  onDelete,
  onMarket,
}: {
  order: MobileOrder | null
  saving: boolean
  onClose: () => void
  onSave: (payload: ModifyOrderPayload) => Promise<boolean>
  onDelete: (order: MobileOrder) => void
  /** Open the same-risk market conversion for this order. */
  onMarket: (order: MobileOrder) => void
}) {
  const [price, setPrice] = useState('')
  const [sl, setSl] = useState('')
  const [tp, setTp] = useState('')
  const [expiryMode, setExpiryMode] = useState<'gtc' | 'date'>('gtc')
  const [expiry, setExpiry] = useState('')
  const [step, setStep] = useState<'edit' | 'review'>('edit')

  const pipMult = order ? getPipMultiplier(order.symbol) : 10000
  const digits = order ? getPriceDigits(order.symbol) : 5
  const pip = 1 / pipMult
  const eps = pip / 10
  const fmt = (n: number) => n.toFixed(digits)

  const initialExpiry = order?.time_expiration && order.time_expiration > 0 ? epochToInput(order.time_expiration) : ''

  // Reset form whenever a different order is opened
  useEffect(() => {
    if (!order) return
    setPrice(fmt(order.price_open))
    setSl(order.sl > 0 ? fmt(order.sl) : '')
    setTp(order.tp > 0 ? fmt(order.tp) : '')
    setExpiryMode(initialExpiry ? 'date' : 'gtc')
    setExpiry(initialExpiry)
    setStep('edit')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [order?.ticket])

  const analysis = useMemo(() => {
    if (!order) return null
    const isBuy = isBuyType(order.type)
    const nPrice = parseFloat(price)
    const nSl = sl.trim() ? parseFloat(sl) : 0
    const nTp = tp.trim() ? parseFloat(tp) : 0
    const errors: string[] = []
    const warnings: string[] = []

    if (!Number.isFinite(nPrice) || nPrice <= 0) errors.push('Enter a valid entry price.')
    if (!Number.isFinite(nSl) || nSl < 0) errors.push('Stop loss is not a valid price.')
    if (!Number.isFinite(nTp) || nTp < 0) errors.push('Take profit is not a valid price.')
    if (expiryMode === 'date' && !expiry) errors.push('Choose an expiry date or switch to Good till cancelled.')

    const validPrice = Number.isFinite(nPrice) && nPrice > 0
    if (validPrice && nSl > 0 && (isBuy ? nSl >= nPrice : nSl <= nPrice)) {
      errors.push(`Stop loss must be ${isBuy ? 'below' : 'above'} the entry for a ${isBuy ? 'buy' : 'sell'} order.`)
    }
    if (validPrice && nTp > 0 && (isBuy ? nTp <= nPrice : nTp >= nPrice)) {
      errors.push(`Take profit must be ${isBuy ? 'above' : 'below'} the entry for a ${isBuy ? 'buy' : 'sell'} order.`)
    }

    // Entry relative to market: limits sit on the favourable side, stops on the other
    const market = order.price_current ?? 0
    let marketNote: string | null = null
    if (validPrice && market > 0) {
      const distPips = Math.abs(nPrice - market) * pipMult
      marketNote = `${distPips.toFixed(1)} pips ${nPrice > market ? 'above' : 'below'} market`
      const isLimit = order.type === 2 || order.type === 3
      const shouldBeBelow = isLimit ? isBuy : !isBuy
      if (shouldBeBelow ? nPrice >= market : nPrice <= market) {
        warnings.push(`Entry is ${shouldBeBelow ? 'at or above' : 'at or below'} the current price — the broker may reject it or fill it immediately.`)
      }
    }

    const slPips = validPrice && nSl > 0 ? Math.abs(nPrice - nSl) * pipMult : null
    const tpPips = validPrice && nTp > 0 ? Math.abs(nTp - nPrice) * pipMult : null
    const rr = slPips && tpPips ? tpPips / slPips : null

    const oldSlPips = order.sl > 0 ? Math.abs(order.price_open - order.sl) * pipMult : null
    if (order.sl > 0 && nSl === 0) warnings.push('Stop loss will be removed — this order will have no downside protection once filled.')
    if (oldSlPips && slPips && slPips > oldSlPips * 1.1) {
      warnings.push(`Risk widens from ${oldSlPips.toFixed(1)} to ${slPips.toFixed(1)} pips (+${(((slPips - oldSlPips) / oldSlPips) * 100).toFixed(0)}%).`)
    }
    if (validPrice && Math.abs(nPrice - order.price_open) / order.price_open > 0.005) {
      warnings.push(`Entry moves ${(Math.abs(nPrice - order.price_open) * pipMult).toFixed(1)} pips from the original level.`)
    }

    const changes: Change[] = []
    if (validPrice && Math.abs(nPrice - order.price_open) > eps) changes.push({ label: 'Entry', from: fmt(order.price_open), to: fmt(nPrice) })
    if (Number.isFinite(nSl) && Math.abs(nSl - order.sl) > eps) changes.push({ label: 'Stop loss', from: order.sl > 0 ? fmt(order.sl) : 'None', to: nSl > 0 ? fmt(nSl) : 'None' })
    if (Number.isFinite(nTp) && Math.abs(nTp - order.tp) > eps) changes.push({ label: 'Take profit', from: order.tp > 0 ? fmt(order.tp) : 'None', to: nTp > 0 ? fmt(nTp) : 'None' })
    const newExpiry = expiryMode === 'date' ? expiry : ''
    if (newExpiry !== initialExpiry) {
      const show = (v: string) => (v ? v.replace('T', ' ') : 'Good till cancelled')
      changes.push({ label: 'Expiry', from: show(initialExpiry), to: show(newExpiry) })
    }

    return { isBuy, nPrice, nSl, nTp, errors, warnings, marketNote, slPips, tpPips, rr, changes, market }
  }, [order, price, sl, tp, expiryMode, expiry, initialExpiry, pipMult, eps, digits]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!order || !analysis) return null

  const size = order.volume_current ?? order.volume ?? order.volume_initial
  const status = ORDER_STATE_LABELS[order.state ?? 1] ?? 'Pending'
  const canSave = analysis.errors.length === 0 && analysis.changes.length > 0 && !saving
  const needsReview = analysis.warnings.length > 0

  const submit = async () => {
    const payload: ModifyOrderPayload = { ticket: order.ticket, price: analysis.nPrice, sl: analysis.nSl, tp: analysis.nTp }
    if (order.price_stoplimit && order.price_stoplimit > 0) payload.stoplimit_price = order.price_stoplimit
    // Omitting expiration makes MT5 treat the order as GTC, so an existing expiry is always re-sent
    if (expiryMode === 'date' && expiry) {
      payload.expiration = expiry === initialExpiry && order.time_expiration
        ? new Date(order.time_expiration * 1000).toISOString() // unchanged: keep exact seconds
        : inputToIso(expiry)
    }
    const ok = await onSave(payload)
    if (ok) onClose()
    else setStep('edit')
  }

  const nudge = (value: string, setter: (v: string) => void, dir: 1 | -1) => {
    const base = parseFloat(value)
    const start = Number.isFinite(base) && base > 0 ? base : analysis.nPrice || order.price_open
    setter(fmt(Math.max(0, start + dir * pip)))
  }

  return (
    <DialogPrimitive.Root open onOpenChange={o => { if (!o && !saving) onClose() }}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-[70] bg-black/60 data-[state=open]:animate-in data-[state=open]:fade-in-0" />
        <DialogPrimitive.Content
          aria-describedby={undefined}
          className="fixed inset-x-0 bottom-0 z-[71] flex max-h-[92dvh] flex-col rounded-t-2xl border-t border-border bg-popover text-popover-foreground shadow-2xl outline-none data-[state=open]:animate-in data-[state=open]:slide-in-from-bottom duration-200"
        >
          {/* Grab handle */}
          <div className="flex justify-center pt-2.5 pb-1">
            <div className="h-1 w-10 rounded-full bg-muted-foreground/30" />
          </div>

          {/* Header */}
          <div className="flex items-center gap-3 px-4 pb-3">
            <InstrumentSymbol symbol={order.symbol} size="sm" />
            <div className="min-w-0 flex-1">
              <DialogPrimitive.Title className="text-base font-bold leading-tight text-foreground">
                {step === 'review' ? 'Review changes' : `Edit ${order.symbol}`}
              </DialogPrimitive.Title>
              <p className="font-mono text-xs text-muted-foreground">#{order.ticket}</p>
            </div>
            <DialogPrimitive.Close
              disabled={saving}
              className="-mr-2 flex h-10 w-10 items-center justify-center rounded-full text-muted-foreground hover:bg-muted"
              aria-label="Close"
            >
              <X className="h-5 w-5" />
            </DialogPrimitive.Close>
          </div>

          {/* Body */}
          <div className="flex-1 overflow-y-auto overscroll-contain px-4 pb-4">
            {step === 'edit' ? (
              <>
                {/* Order facts */}
                <div className="grid grid-cols-4 divide-x divide-border border-y border-border py-2.5">
                  <Fact label="Type" value={getOrderTypeLabel(order.type).replace(/^(BUY|SELL) /, '')} />
                  <Fact label="Side" value={analysis.isBuy ? 'Buy' : 'Sell'} tone={analysis.isBuy ? 'text-success' : 'text-destructive'} />
                  <Fact label="Size" value={`${size.toFixed(2)}`} icon={<Lock className="h-3 w-3" />} />
                  <Fact label="Status" value={status} />
                </div>
                <p className="mt-2 text-[11px] leading-snug text-muted-foreground">
                  MT5 does not allow resizing a pending order. To change the size, delete it and place a new one.
                </p>

                {analysis.market > 0 && (
                  <div className="mt-3 flex items-baseline justify-between text-xs">
                    <span className="text-muted-foreground">Market <span className="font-mono font-semibold text-foreground tabular-nums">{fmt(analysis.market)}</span></span>
                    {analysis.marketNote && <span className="font-medium text-muted-foreground">{analysis.marketNote}</span>}
                  </div>
                )}

                <div className="mt-4 space-y-4">
                  <PriceField
                    label="Entry price"
                    value={price}
                    onChange={setPrice}
                    onNudge={dir => nudge(price, setPrice, dir)}
                    original={fmt(order.price_open)}
                    large
                  />
                  <PriceField
                    label="Stop loss"
                    dot="bg-destructive"
                    value={sl}
                    onChange={setSl}
                    onNudge={dir => nudge(sl, setSl, dir)}
                    original={order.sl > 0 ? fmt(order.sl) : ''}
                    hint={analysis.slPips !== null ? `${analysis.slPips.toFixed(1)} pips risk` : undefined}
                    hintTone="text-destructive"
                    onClear={() => setSl('')}
                  />
                  <PriceField
                    label="Take profit"
                    dot="bg-success"
                    value={tp}
                    onChange={setTp}
                    onNudge={dir => nudge(tp, setTp, dir)}
                    original={order.tp > 0 ? fmt(order.tp) : ''}
                    hint={analysis.tpPips !== null ? `${analysis.tpPips.toFixed(1)} pips target` : undefined}
                    hintTone="text-success"
                    onClear={() => setTp('')}
                  />
                </div>

                {analysis.rr !== null && (
                  <div className="mt-3 flex items-center justify-between border-t border-border pt-3 text-sm">
                    <span className="text-muted-foreground">Risk : Reward</span>
                    <span className={`font-mono font-bold tabular-nums ${analysis.rr >= 2 ? 'text-success' : analysis.rr >= 1 ? 'text-gold' : 'text-destructive'}`}>
                      1 : {analysis.rr.toFixed(2)}
                    </span>
                  </div>
                )}

                {/* Expiry */}
                <div className="mt-5">
                  <p className="mb-2 text-xs font-semibold text-muted-foreground">Expiry</p>
                  <div className="grid grid-cols-2 rounded-lg bg-muted p-1">
                    {(['gtc', 'date'] as const).map(m => (
                      <button
                        key={m}
                        type="button"
                        onClick={() => setExpiryMode(m)}
                        className={`h-9 rounded-md text-sm font-semibold transition-colors ${expiryMode === m ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground'}`}
                      >
                        {m === 'gtc' ? 'Good till cancelled' : 'Until date'}
                      </button>
                    ))}
                  </div>
                  {expiryMode === 'date' && (
                    <div className="mt-2">
                      <input
                        type="datetime-local"
                        value={expiry}
                        onChange={e => setExpiry(e.target.value)}
                        className="h-12 w-full rounded-lg border border-border bg-background px-3 font-mono text-base text-foreground focus:outline-none focus:ring-2 focus:ring-primary/40"
                      />
                      <p className="mt-1 text-[11px] text-muted-foreground">Broker server time</p>
                    </div>
                  )}
                </div>

                {analysis.errors.length > 0 && analysis.changes.length > 0 && (
                  <div className="mt-4 space-y-1">
                    {analysis.errors.map(e => (
                      <p key={e} className="flex items-start gap-1.5 text-xs font-medium text-destructive">
                        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{e}
                      </p>
                    ))}
                  </div>
                )}

                <button
                  type="button"
                  disabled={saving}
                  onClick={() => onMarket(order)}
                  className="mt-6 flex h-11 w-full items-center justify-center gap-2 rounded-lg border border-primary/40 text-sm font-semibold text-primary hover:bg-primary/10 disabled:opacity-50"
                >
                  <Zap className="h-4 w-4" /> Execute at market (same risk)
                </button>

                <button
                  type="button"
                  disabled={saving}
                  onClick={() => onDelete(order)}
                  className="mt-2 flex h-11 w-full items-center justify-center gap-2 rounded-lg text-sm font-semibold text-destructive hover:bg-destructive/10 disabled:opacity-50"
                >
                  <Trash2 className="h-4 w-4" /> Delete order
                </button>
              </>
            ) : (
              <>
                <div className="divide-y divide-border border-y border-border">
                  {analysis.changes.map(c => (
                    <div key={c.label} className="flex items-center justify-between gap-3 py-3">
                      <span className="text-sm text-muted-foreground">{c.label}</span>
                      <span className="flex items-center gap-2 font-mono text-sm tabular-nums">
                        <span className="text-muted-foreground line-through decoration-muted-foreground/50">{c.from}</span>
                        <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" />
                        <span className="font-bold text-foreground">{c.to}</span>
                      </span>
                    </div>
                  ))}
                </div>
                {analysis.warnings.length > 0 && (
                  <div className="mt-4 space-y-2">
                    {analysis.warnings.map(w => (
                      <p key={w} className="flex items-start gap-2 text-sm leading-snug text-gold">
                        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />{w}
                      </p>
                    ))}
                  </div>
                )}
                <p className="mt-4 text-xs text-muted-foreground">
                  {getOrderTypeLabel(order.type)} · {size.toFixed(2)} lots · {order.symbol}
                </p>
              </>
            )}
          </div>

          {/* Footer */}
          <div className="border-t border-border bg-popover px-4 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
            {step === 'edit' && analysis.changes.length > 0 && analysis.errors.length === 0 && (
              <p className="mb-2 text-center text-xs text-muted-foreground">
                {analysis.changes.length} change{analysis.changes.length !== 1 ? 's' : ''}: {analysis.changes.map(c => c.label).join(', ')}
              </p>
            )}
            <div className="grid grid-cols-2 gap-3">
              <button
                type="button"
                disabled={saving}
                onClick={() => (step === 'review' ? setStep('edit') : onClose())}
                className="h-12 rounded-lg border border-border bg-background text-sm font-semibold text-foreground hover:bg-muted disabled:opacity-50"
              >
                {step === 'review' ? 'Back' : 'Cancel'}
              </button>
              <button
                type="button"
                disabled={!canSave}
                onClick={() => (step === 'edit' && needsReview ? setStep('review') : submit())}
                className="flex h-12 items-center justify-center gap-2 rounded-lg bg-primary text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-40"
              >
                {saving && <Loader2 className="h-4 w-4 animate-spin" />}
                {step === 'edit' && needsReview ? 'Review changes' : step === 'review' ? 'Confirm & save' : 'Save Changes'}
              </button>
            </div>
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  )
}

function Fact({ label, value, tone, icon }: { label: string; value: string; tone?: string; icon?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center px-1 text-center">
      <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">{label}</span>
      <span className={`mt-0.5 flex items-center gap-1 text-sm font-semibold ${tone ?? 'text-foreground'}`}>
        {value}{icon && <span className="text-muted-foreground">{icon}</span>}
      </span>
    </div>
  )
}

function PriceField({
  label, dot, value, onChange, onNudge, original, hint, hintTone, onClear, large,
}: {
  label: string
  dot?: string
  value: string
  onChange: (v: string) => void
  onNudge: (dir: 1 | -1) => void
  original: string
  hint?: string
  hintTone?: string
  onClear?: () => void
  large?: boolean
}) {
  const changed = value.trim() !== original && !(value.trim() === '' && original === '')
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between">
        <label className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
          {dot && <span className={`h-2 w-2 rounded-full ${dot}`} />}{label}
        </label>
        <div className="flex items-center gap-3 text-xs">
          {hint && <span className={`font-semibold ${hintTone}`}>{hint}</span>}
          {onClear && value && (
            <button type="button" onClick={onClear} className="font-semibold text-muted-foreground underline-offset-2 hover:underline">
              Remove
            </button>
          )}
        </div>
      </div>
      <div className={`flex items-stretch overflow-hidden rounded-lg border bg-background ${changed ? 'border-primary' : 'border-border'} focus-within:ring-2 focus-within:ring-primary/30`}>
        <button type="button" onClick={() => onNudge(-1)} aria-label={`Decrease ${label}`} className="flex w-12 shrink-0 items-center justify-center text-muted-foreground active:bg-muted">
          <Minus className="h-4 w-4" />
        </button>
        <input
          type="text"
          inputMode="decimal"
          autoComplete="off"
          value={value}
          placeholder="None"
          onChange={e => onChange(e.target.value.replace(',', '.'))}
          className={`min-w-0 flex-1 border-x border-border bg-transparent text-center font-mono font-semibold tabular-nums text-foreground placeholder:font-sans placeholder:font-normal placeholder:text-muted-foreground/60 focus:outline-none ${large ? 'h-14 text-xl' : 'h-12 text-lg'}`}
        />
        <button type="button" onClick={() => onNudge(1)} aria-label={`Increase ${label}`} className="flex w-12 shrink-0 items-center justify-center text-muted-foreground active:bg-muted">
          <Plus className="h-4 w-4" />
        </button>
      </div>
      {changed && (
        <p className="mt-1 text-[11px] text-muted-foreground">Was <span className="font-mono">{original || 'None'}</span></p>
      )}
    </div>
  )
}
