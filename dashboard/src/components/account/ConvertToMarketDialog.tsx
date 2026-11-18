'use client'

import { useEffect, useState } from 'react'
import { AlertTriangle, ArrowRight, Loader2, Zap } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'

/** ConversionPlan from src/services/order_conversion_service.py */
interface ConversionPlan {
  order_id: string
  symbol: string
  side: string
  pending_type: string
  pending_price: number
  market_price: number | null
  stop_loss: number | null
  take_profit: number | null
  old_volume: number
  new_volume: number | null
  risk_change_pct: number | null
  warnings: string[]
  error: string | null
}

const lots = (n: number | null | undefined) => (n == null ? '—' : n.toFixed(2))

/**
 * Turn one pending order into a market order at the same money risk. Shows the
 * live price and the recalculated lot size first; the bot recalculates again on
 * the price at the moment of execution.
 */
export default function ConvertToMarketDialog({
  ticket,
  onClose,
  onDone,
}: {
  ticket: number | null
  onClose: () => void
  onDone: () => void
}) {
  const [plan, setPlan] = useState<ConversionPlan | null>(null)
  const [loading, setLoading] = useState(false)
  const [converting, setConverting] = useState(false)

  useEffect(() => {
    if (ticket == null) return
    let cancelled = false
    setPlan(null)
    setLoading(true)
    fetch(`/api/mt5/order-to-market?ticket=${ticket}`)
      .then(r => r.json())
      .then((data: ConversionPlan) => { if (!cancelled) setPlan(data) })
      .catch(e => { if (!cancelled) setPlan({ error: String(e) } as ConversionPlan) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [ticket])

  async function convert() {
    if (ticket == null) return
    setConverting(true)
    try {
      const res = await fetch('/api/mt5/order-to-market', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticket }),
      })
      const data = await res.json()
      if (data.success) {
        const p: ConversionPlan = data.plan
        toast.success(`${p.symbol} ${p.side} at market`, {
          description: `#${p.order_id} → position #${data.position_id} @ ${data.fill_price} · ${lots(p.new_volume)} lots`,
        })
        onDone()
        onClose()
      } else {
        toast.error('Not converted', { description: data.error || 'Unknown error' })
        if (data.plan) setPlan(data.plan)
      }
    } catch (e) {
      toast.error('Not converted', { description: String(e) })
    } finally {
      setConverting(false)
    }
  }

  const sameLots = plan?.new_volume != null && plan.new_volume === plan.old_volume

  return (
    <Dialog open={ticket != null} onOpenChange={o => { if (!o && !converting) onClose() }}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-base">
            <Zap className="h-4 w-4 text-primary shrink-0" />
            Execute at market
          </DialogTitle>
        </DialogHeader>

        {loading || !plan ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <div className="space-y-3">
            {plan.symbol && (
              <p className="text-sm text-muted-foreground">
                {plan.symbol} {plan.pending_type.replace('_', ' ')} #{plan.order_id}
              </p>
            )}

            {plan.market_price != null && (
              <div className="divide-y divide-border border-y border-border text-sm">
                <Row label="Entry" from={String(plan.pending_price)} to={`${plan.market_price} (market)`} />
                <Row label="Lots" from={lots(plan.old_volume)} to={lots(plan.new_volume)} />
                <div className="flex items-center justify-between py-2">
                  <span className="text-muted-foreground">SL / TP</span>
                  <span className="font-mono tabular-nums">{plan.stop_loss ?? '—'} / {plan.take_profit ?? '—'}</span>
                </div>
                {plan.risk_change_pct != null && (
                  <div className="flex items-center justify-between py-2">
                    <span className="text-muted-foreground">Risk vs original</span>
                    <span className="font-mono tabular-nums font-semibold">
                      {plan.risk_change_pct === 0 ? 'same' : `${plan.risk_change_pct > 0 ? '+' : ''}${plan.risk_change_pct}%`}
                    </span>
                  </div>
                )}
              </div>
            )}

            {plan.error && (
              <p className="flex items-start gap-2 rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{plan.error}
              </p>
            )}
            {plan.warnings?.map(w => (
              <p key={w} className="flex items-start gap-2 text-xs text-amber-600 dark:text-amber-400">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{w}
              </p>
            ))}

            {!plan.error && (
              <p className="text-[11px] text-muted-foreground leading-snug">
                {sameLots && plan.risk_change_pct == null
                  ? 'The pending order is cancelled and opened at market with the same lots.'
                  : 'The pending order is cancelled and opened at market. Lots are recalculated on the price at that moment so the money at risk to the stop loss stays the same.'}
              </p>
            )}
          </div>
        )}

        <DialogFooter className="gap-2 sm:gap-2">
          <Button variant="ghost" onClick={onClose} disabled={converting}>Close</Button>
          <Button onClick={convert} disabled={loading || converting || !plan || !!plan.error} className="gap-1.5">
            {converting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />}
            {converting ? 'Executing…' : 'Execute at market'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function Row({ label, from, to }: { label: string; from: string; to: string }) {
  return (
    <div className="flex items-center justify-between gap-3 py-2">
      <span className="text-muted-foreground">{label}</span>
      <span className="flex items-center gap-2 font-mono tabular-nums">
        <span className="text-muted-foreground line-through decoration-muted-foreground/50">{from}</span>
        <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="font-bold text-foreground">{to}</span>
      </span>
    </div>
  )
}
