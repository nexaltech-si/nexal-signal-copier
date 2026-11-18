'use client'

import { useState } from 'react'
import { Activity, ChevronDown, Edit3, LineChart, Scissors, TrendingUpDown, X, Zap } from 'lucide-react'
import { InstrumentSymbol } from '@/components/InstrumentSymbol'
import { formatCurrency } from '@/lib/utils'
import { getOrderTypeLabel, getPriceDigits } from './mobile-trading-utils'

export interface MobilePosition {
  ticket: number
  symbol: string
  type: number
  volume: number
  price_open: number
  price_current: number
  sl: number
  tp: number
  profit: number
}

interface BulkAction { label: string; icon: React.ReactNode; onClick: () => void; disabled?: boolean; danger?: boolean }

export default function MobilePositionsList({
  positions,
  actionLoading,
  smartClose,
  getPips,
  getPossibleLoss,
  getPossibleProfit,
  onSmartClose,
  onBreakeven,
  onEdit,
  onPartial,
  onChart,
  onClose,
  bulkActions,
}: {
  positions: MobilePosition[]
  actionLoading: boolean
  smartClose: { enabled: boolean; setBreakeven: boolean; percentage: number }
  getPips: (p: MobilePosition) => string
  getPossibleLoss: (p: MobilePosition) => number | null
  getPossibleProfit: (p: MobilePosition) => number | null
  onSmartClose: (p: MobilePosition) => void
  onBreakeven: (p: MobilePosition) => void
  onEdit: (p: MobilePosition) => void
  onPartial: (p: MobilePosition) => void
  onChart: (p: MobilePosition) => void
  onClose: (p: MobilePosition) => void
  bulkActions: BulkAction[]
}) {
  const [expanded, setExpanded] = useState<number | null>(null)

  if (positions.length === 0) {
    return (
      <div className="py-14 text-center">
        <Activity className="mx-auto mb-2 h-8 w-8 text-muted-foreground/40" />
        <p className="text-sm font-medium text-muted-foreground">No open positions</p>
      </div>
    )
  }

  const floating = positions.reduce((s, p) => s + p.profit, 0)
  const slTotal = positions.reduce((s, p) => s + (getPossibleLoss(p) ?? 0), 0)
  const tpTotal = positions.reduce((s, p) => s + (getPossibleProfit(p) ?? 0), 0)

  return (
    <div>
      {/* Totals */}
      <div className="flex items-end justify-between px-1 pb-3">
        <div>
          <p className="text-xs text-muted-foreground">Floating P/L</p>
          <p className={`font-mono text-lg font-bold tabular-nums ${floating >= 0 ? 'text-success' : 'text-destructive'}`}>
            {floating >= 0 ? '+' : ''}{formatCurrency(floating)}
          </p>
        </div>
        <div className="text-right text-xs leading-relaxed">
          <p className="text-muted-foreground">All SL <span className="font-mono font-semibold text-destructive">{formatCurrency(slTotal)}</span></p>
          <p className="text-muted-foreground">All TP <span className="font-mono font-semibold text-success">+{formatCurrency(tpTotal)}</span></p>
        </div>
      </div>

      {/* Bulk actions */}
      <div className="grid gap-1.5 pb-3" style={{ gridTemplateColumns: `repeat(${bulkActions.length}, minmax(0, 1fr))` }}>
        {bulkActions.map(a => (
          <button
            key={a.label}
            type="button"
            onClick={a.onClick}
            disabled={actionLoading || a.disabled}
            className={`flex h-14 min-w-0 flex-col items-center justify-center gap-1 rounded-lg border transition-colors disabled:opacity-40 ${a.danger ? 'border-destructive/40 text-destructive active:bg-destructive/10' : 'border-border text-foreground active:bg-muted'}`}
          >
            {a.icon}
            <span className="w-full truncate px-0.5 text-[11px] font-semibold leading-none">{a.label}</span>
          </button>
        ))}
      </div>

      <ul className="divide-y divide-border border-y border-border">
        {positions.map(pos => {
          const isOpen = expanded === pos.ticket
          const digits = getPriceDigits(pos.symbol)
          const pips = parseFloat(getPips(pos))
          const beSet = Math.abs(pos.sl - pos.price_open) < 0.00001
          const smartDisabled = actionLoading || !smartClose.enabled || pos.profit <= 0 || (smartClose.setBreakeven && beSet)
          const beDisabled = actionLoading || beSet || pos.profit <= 0
          const loss = isOpen ? getPossibleLoss(pos) : null
          const gain = isOpen ? getPossibleProfit(pos) : null
          return (
            <li key={pos.ticket}>
              <button
                type="button"
                onClick={() => setExpanded(isOpen ? null : pos.ticket)}
                aria-expanded={isOpen}
                className="flex w-full items-center gap-3 px-1 py-3 text-left active:bg-muted/50"
              >
                <InstrumentSymbol symbol={pos.symbol} size="sm" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline gap-2">
                    <span className="truncate text-sm font-bold text-foreground">{pos.symbol}</span>
                    <span className={`text-xs font-semibold ${pos.type === 0 ? 'text-success' : 'text-destructive'}`}>
                      {getOrderTypeLabel(pos.type)} {pos.volume.toFixed(2)}
                    </span>
                  </div>
                  <p className="truncate font-mono text-[11px] tabular-nums text-muted-foreground">
                    {pos.price_open.toFixed(digits)} → {pos.price_current.toFixed(digits)}
                  </p>
                </div>
                <div className="text-right">
                  <p className={`font-mono text-sm font-bold tabular-nums ${pos.profit >= 0 ? 'text-success' : 'text-destructive'}`}>
                    {pos.profit >= 0 ? '+' : ''}{formatCurrency(pos.profit)}
                  </p>
                  <p className={`font-mono text-[11px] tabular-nums ${pips >= 0 ? 'text-success/80' : 'text-destructive/80'}`}>
                    {pips >= 0 ? '+' : ''}{pips.toFixed(1)} pips
                  </p>
                </div>
                <ChevronDown className={`h-4 w-4 shrink-0 text-muted-foreground transition-transform ${isOpen ? 'rotate-180' : ''}`} />
              </button>

              {isOpen && (
                <>
                <dl className="grid grid-cols-4 gap-2 px-1 pb-3 text-center">
                  <Level label="Stop loss" value={pos.sl > 0 ? pos.sl.toFixed(digits) : '—'} tone={pos.sl > 0 ? 'text-destructive' : undefined} />
                  <Level label="Take profit" value={pos.tp > 0 ? pos.tp.toFixed(digits) : '—'} tone={pos.tp > 0 ? 'text-success' : undefined} />
                  <Level label="At SL" value={loss !== null ? formatCurrency(loss) : '—'} tone={loss !== null ? 'text-destructive' : undefined} />
                  <Level label="At TP" value={gain !== null ? `+${formatCurrency(gain)}` : '—'} tone={gain !== null ? 'text-success' : undefined} />
                </dl>
                <div className="grid grid-cols-3 gap-2 px-1 pb-3">
                  <ActionButton icon={<Zap className="h-4 w-4" />} label="Smart close" onClick={() => onSmartClose(pos)} disabled={smartDisabled} />
                  <ActionButton icon={<TrendingUpDown className="h-4 w-4" />} label="Breakeven" onClick={() => onBreakeven(pos)} disabled={beDisabled} />
                  <ActionButton icon={<Edit3 className="h-4 w-4" />} label="Edit SL/TP" onClick={() => onEdit(pos)} disabled={actionLoading} />
                  <ActionButton icon={<Scissors className="h-4 w-4" />} label="Partial" onClick={() => onPartial(pos)} disabled={actionLoading} />
                  <ActionButton icon={<LineChart className="h-4 w-4" />} label="Chart" onClick={() => onChart(pos)} />
                  <ActionButton icon={<X className="h-4 w-4" />} label="Close" onClick={() => onClose(pos)} disabled={actionLoading} danger />
                </div>
                </>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}

function Level({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className={`truncate font-mono text-xs font-semibold tabular-nums ${tone ?? 'text-muted-foreground'}`}>{value}</dd>
    </div>
  )
}

function ActionButton({ icon, label, onClick, disabled, danger }: { icon: React.ReactNode; label: string; onClick: () => void; disabled?: boolean; danger?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`flex h-11 items-center justify-center gap-1.5 rounded-lg border text-xs font-semibold transition-colors disabled:opacity-40 ${danger ? 'border-destructive/40 text-destructive active:bg-destructive/10' : 'border-border text-foreground active:bg-muted'}`}
    >
      {icon}{label}
    </button>
  )
}
