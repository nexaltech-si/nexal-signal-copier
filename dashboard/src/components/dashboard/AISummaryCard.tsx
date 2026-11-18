'use client'

import { Sparkles } from 'lucide-react'
import { cn } from '@/lib/utils'
import WidgetCard, { WidgetEmpty } from './WidgetCard'

/** Minimal shape of the fields we read from the latest MarketAnalysis. */
export interface AISummary {
  symbol: string
  trend: string
  momentum: string
  volatility: string
  confidence: number
  positionType?: string | null
  recommendBreakeven?: boolean
  recommendTpAdjustment?: boolean
  recommendReducePosition?: boolean
  recommendTightStop?: boolean
  keepPositionOpen?: boolean
  createdAt?: string | null
}

function trendLabel(trend: string): { label: string; tone: 'success' | 'destructive' | 'muted' } {
  const t = (trend || '').toLowerCase()
  if (t.includes('up')) return { label: t.includes('strong') ? 'Strong Bullish' : 'Bullish', tone: 'success' }
  if (t.includes('down')) return { label: t.includes('strong') ? 'Strong Bearish' : 'Bearish', tone: 'destructive' }
  return { label: 'Neutral', tone: 'muted' }
}

function buildBullets(a: AISummary): string[] {
  const bullets: string[] = []
  const t = trendLabel(a.trend)
  bullets.push(`Trend is ${t.label.toLowerCase()} on ${a.symbol}.`)
  if (a.momentum) bullets.push(`Momentum reading: ${a.momentum.replace(/_/g, ' ')}.`)
  if (a.volatility) bullets.push(`Volatility is ${a.volatility}.`)
  if (a.recommendBreakeven) bullets.push('AI suggests moving stop to breakeven.')
  if (a.recommendTightStop) bullets.push('AI suggests tightening the stop loss.')
  if (a.recommendReducePosition) bullets.push('AI suggests reducing position size.')
  if (a.recommendTpAdjustment) bullets.push('AI suggests adjusting the take profit.')
  if (a.keepPositionOpen === false) bullets.push('AI recommends closing the position.')
  return bullets.slice(0, 5)
}

export default function AISummaryCard({ analysis }: { analysis: AISummary | null }) {
  if (!analysis) {
    return (
      <WidgetCard
        title="Hermes AI Summary"
        icon={<Sparkles className="h-4 w-4" />}
        actionLabel="Full analysis"
        actionHref="/hermes"
        accent="blue"
      >
        <WidgetEmpty message="No AI analysis available yet" />
      </WidgetCard>
    )
  }

  const t = trendLabel(analysis.trend)
  const confPct = Math.round((analysis.confidence || 0) * 100)
  const bullets = buildBullets(analysis)

  return (
    <WidgetCard
      title="Hermes AI Summary"
      icon={<Sparkles className="h-4 w-4" />}
      actionLabel="Full analysis"
      actionHref="/hermes"
      accent="blue"
    >
      <p className="text-sm font-semibold text-foreground mb-3">
        Market bias for {analysis.symbol} is{' '}
        <span
          className={cn(
            t.tone === 'success' && 'text-success',
            t.tone === 'destructive' && 'text-destructive',
            t.tone === 'muted' && 'text-muted-foreground',
          )}
        >
          {t.label.toLowerCase()}
        </span>
        .
      </p>

      <ul className="space-y-1.5 mb-4">
        {bullets.map((b, i) => (
          <li key={i} className="flex gap-2 text-xs text-muted-foreground">
            <span className="text-primary mt-0.5">•</span>
            <span>{b}</span>
          </li>
        ))}
      </ul>

      <div className="grid grid-cols-3 gap-2 pt-3 border-t border-border/50">
        <div>
          <div className="tech-label mb-1">Bias</div>
          <div
            className={cn(
              'text-sm font-bold',
              t.tone === 'success' && 'text-success',
              t.tone === 'destructive' && 'text-destructive',
              t.tone === 'muted' && 'text-muted-foreground',
            )}
          >
            {t.label}
          </div>
        </div>
        <div>
          <div className="tech-label mb-1">Volatility</div>
          <div className="text-sm font-bold text-foreground capitalize">
            {analysis.volatility || '—'}
          </div>
        </div>
        <div>
          <div className="tech-label mb-1">Confidence</div>
          <div
            className={cn(
              'text-sm font-bold tabular-nums',
              confPct >= 70 ? 'text-success' : 'text-gold',
            )}
          >
            {confPct}%
          </div>
        </div>
      </div>
    </WidgetCard>
  )
}
