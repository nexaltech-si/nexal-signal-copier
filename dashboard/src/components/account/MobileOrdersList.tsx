'use client'

import { ChevronRight, Clock } from 'lucide-react'
import { InstrumentSymbol } from '@/components/InstrumentSymbol'
import { getOrderTypeLabel, getPipMultiplier, getPriceDigits, isBuyType } from './mobile-trading-utils'
import type { MobileOrder } from './MobileOrderEditSheet'

/** Pending orders on mobile. Tapping a row opens the single Edit Order sheet. */
export default function MobileOrdersList({
  orders,
  actionLoading,
  onSelect,
  onCancelAll,
}: {
  orders: MobileOrder[]
  actionLoading: boolean
  onSelect: (order: MobileOrder) => void
  onCancelAll: () => void
}) {
  if (orders.length === 0) {
    return (
      <div className="py-14 text-center">
        <Clock className="mx-auto mb-2 h-8 w-8 text-muted-foreground/40" />
        <p className="text-sm font-medium text-muted-foreground">No pending orders</p>
      </div>
    )
  }

  return (
    <div>
      <div className="flex items-center justify-between px-1 pb-3">
        <p className="text-xs text-muted-foreground">Tap an order to edit price, SL, TP or expiry</p>
        <button
          type="button"
          onClick={onCancelAll}
          disabled={actionLoading}
          className="h-9 shrink-0 rounded-full border border-destructive/40 px-4 text-xs font-semibold text-destructive disabled:opacity-40"
        >
          Cancel all
        </button>
      </div>

      <ul className="divide-y divide-border border-y border-border">
        {orders.map(order => {
          const digits = getPriceDigits(order.symbol)
          const size = order.volume_current ?? order.volume ?? order.volume_initial
          const away = order.price_current && order.price_current > 0
            ? Math.abs(order.price_open - order.price_current) * getPipMultiplier(order.symbol)
            : null
          return (
            <li key={order.ticket}>
              <button
                type="button"
                onClick={() => onSelect(order)}
                className="flex w-full items-center gap-3 px-1 py-3 text-left active:bg-muted/50"
              >
                <InstrumentSymbol symbol={order.symbol} size="sm" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline gap-2">
                    <span className="truncate text-sm font-bold text-foreground">{order.symbol}</span>
                    <span className={`text-xs font-semibold ${isBuyType(order.type) ? 'text-success' : 'text-destructive'}`}>
                      {getOrderTypeLabel(order.type)}
                    </span>
                  </div>
                  <p className="truncate font-mono text-[11px] tabular-nums text-muted-foreground">
                    {size.toFixed(2)} lots
                    <span className="ml-2">SL {order.sl > 0 ? order.sl.toFixed(digits) : '—'}</span>
                    <span className="ml-2">TP {order.tp > 0 ? order.tp.toFixed(digits) : '—'}</span>
                  </p>
                </div>
                <div className="text-right">
                  <p className="font-mono text-sm font-bold tabular-nums text-foreground">{order.price_open.toFixed(digits)}</p>
                  {away !== null && <p className="text-[11px] text-muted-foreground">{away.toFixed(1)} pips away</p>}
                </div>
                <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
