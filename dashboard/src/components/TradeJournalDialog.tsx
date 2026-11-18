'use client'

import React, { useState, useEffect } from 'react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Textarea } from '@/components/ui/textarea'
import { cn, formatCurrency, formatDate } from '@/lib/utils'
import {
  BookOpen,
  TrendingUp,
  TrendingDown,
  Tag,
  MessageSquare,
  Loader2,
  Brain,
  X,
  Sparkles,
} from 'lucide-react'

// ---- Types ----
type TagType = 'WIN' | 'LOSS' | 'BREAKEVEN' | 'SCALP' | 'NEWS' | 'FOMC' | 'TECHNICAL' | 'EMOTIONAL'

const ALL_TAGS: TagType[] = ['WIN', 'LOSS', 'BREAKEVEN', 'SCALP', 'NEWS', 'FOMC', 'TECHNICAL', 'EMOTIONAL']

const TAG_COLORS: Record<TagType, string> = {
  WIN: 'bg-success/10 text-success border border-success/20 border-emerald-200',
  LOSS: 'bg-destructive/10 text-destructive border border-destructive/20 border-rose-200',
  BREAKEVEN: 'bg-gold/10 text-gold border border-gold/20 border-amber-200',
  SCALP: 'bg-primary/10 text-primary border border-primary/20 border-sky-200',
  NEWS: 'bg-accent text-muted-foreground border border-border border-violet-200',
  FOMC: 'bg-red-100 text-destructive border-red-200',
  TECHNICAL: 'bg-indigo-100 text-indigo-700 border-indigo-200',
  EMOTIONAL: 'bg-orange-100 text-orange-700 border-orange-200',
}

const TAG_EMOJIS: Record<TagType, string> = {
  WIN: '🏆',
  LOSS: '💔',
  BREAKEVEN: '🤷',
  SCALP: '⚡',
  NEWS: '📰',
  FOMC: '🏛️',
  TECHNICAL: '📊',
  EMOTIONAL: '🧠',
}

type Trade = {
  id: string
  symbol: string
  action: string
  lotSize: number
  entryPrice: number | null
  stopLoss: number | null
  takeProfit: number | null
  profitLoss: number | null
  profitLossPips: number | null
  status: string
  createdAt: string
  closedAt: string | null
}

type JournalEntry = {
  notes: string
  tags: string[]
}

// ---- Props ----
interface TradeJournalDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  trade: Trade
  journal: JournalEntry
  onSave: (tradeId: string, data: { notes?: string; tags?: string[] }) => void
  saving?: boolean
}

export default function TradeJournalDialog({
  open,
  onOpenChange,
  trade,
  journal,
  onSave,
  saving = false,
}: TradeJournalDialogProps) {
  const [notes, setNotes] = useState(journal.notes || '')
  const [selectedTags, setSelectedTags] = useState<string[]>(journal.tags || [])

  // Sync when journal changes
  useEffect(() => {
    setNotes(journal.notes || '')
    setSelectedTags(journal.tags || [])
  }, [journal.notes, journal.tags])

  const toggleTag = (tag: string) => {
    setSelectedTags((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag]
    )
  }

  const handleSave = () => {
    onSave(trade.id, { notes, tags: selectedTags })
    onOpenChange(false)
  }

  const handleClose = () => {
    // If there are unsaved changes, save silently on close
    const hasChanges =
      notes !== (journal.notes || '') ||
      JSON.stringify(selectedTags) !== JSON.stringify(journal.tags || [])
    if (hasChanges && (notes.trim() || selectedTags.length > 0)) {
      onSave(trade.id, { notes, tags: selectedTags })
    }
    onOpenChange(false)
  }

  const isBuy = trade.action?.toUpperCase().includes('BUY')
  const pnl = Number(trade.profitLoss ?? 0)
  const hasPnl = trade.profitLoss !== null && trade.profitLoss !== undefined

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-foreground/90">
            <BookOpen className="h-5 w-5 text-primary" />
            Journal Entry
          </DialogTitle>
          <DialogDescription>
            Record your thoughts and analysis for this trade
          </DialogDescription>
        </DialogHeader>

        {/* Trade summary card */}
        <div className="bg-gradient-to-r from-blue-50/60 to-white rounded-lg border border-border p-3">
          <div className="flex items-center gap-3">
            {/* Direction icon */}
            <div
              className={cn(
                'w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0',
                isBuy ? 'bg-success/10' : 'bg-destructive/10'
              )}
            >
              {isBuy ? (
                <TrendingUp className="h-4 w-4 text-success" />
              ) : (
                <TrendingDown className="h-4 w-4 text-destructive" />
              )}
            </div>

            {/* Details */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-bold text-base text-foreground">{trade.symbol}</span>
                <Badge variant="secondary" className="text-[10px] font-semibold bg-muted text-muted-foreground">
                  {trade.action} · {trade.lotSize.toFixed(2)}L
                </Badge>
              </div>
              <div className="flex items-center gap-3 text-[11px] text-muted-foreground mt-0.5">
                <span>{formatDate(trade.createdAt)}</span>
                {trade.entryPrice && (
                  <span className="font-mono">
                    E: {trade.entryPrice.toFixed(5)}
                  </span>
                )}
              </div>
            </div>

            {/* P/L */}
            <div className="text-right flex-shrink-0">
              {hasPnl ? (
                <div
                  className={cn(
                    'font-bold text-base tabular-nums',
                    pnl >= 0 ? 'text-success' : 'text-destructive'
                  )}
                >
                  {pnl >= 0 ? '+' : ''}
                  {formatCurrency(Math.abs(pnl))}
                  {trade.profitLossPips !== null && trade.profitLossPips !== undefined && (
                    <div className="text-[10px] font-normal text-muted-foreground/70">
                      {Number(trade.profitLossPips) >= 0 ? '+' : ''}
                      {Number(trade.profitLossPips).toFixed(1)} pips
                    </div>
                  )}
                </div>
              ) : (
                <span className="text-muted-foreground/50 text-sm">—</span>
              )}
            </div>
          </div>
        </div>

        {/* Tags selector */}
        <div>
          <label className="text-xs font-semibold text-muted-foreground mb-2 flex items-center gap-1.5">
            <Tag className="h-3.5 w-3.5" /> Tags
            <span className="text-[10px] font-normal text-muted-foreground/70">
              (select all that apply)
            </span>
          </label>
          <div className="flex flex-wrap gap-1.5">
            {ALL_TAGS.map((tag) => {
              const isSelected = selectedTags.includes(tag)
              const colorClass = TAG_COLORS[tag]
              return (
                <button
                  key={tag}
                  onClick={() => toggleTag(tag)}
                  className={cn(
                    'inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-semibold transition-all',
                    isSelected
                      ? colorClass + ' ring-1 ring-offset-1 ' + colorClass.split(' ')[0].replace('bg-', 'ring-')
                      : 'border-border text-muted-foreground/70 bg-card hover:border-border hover:text-muted-foreground'
                  )}
                >
                  {TAG_EMOJIS[tag]} {tag}
                </button>
              )
            })}
          </div>
        </div>

        {/* Notes textarea */}
        <div>
          <label className="text-xs font-semibold text-muted-foreground mb-2 flex items-center gap-1.5">
            <MessageSquare className="h-3.5 w-3.5" /> Notes
            <span className="text-[10px] font-normal text-muted-foreground/70">
              (what happened, what did you learn?)
            </span>
          </label>
          <Textarea
            placeholder="Reflect on this trade. What was your thesis? What worked? What would you do differently?"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className="min-h-[120px] text-sm border-border focus:border-primary resize-y"
          />
        </div>

        {/* AI Suggestion hint */}
        <div className="flex items-center gap-2 text-[11px] text-muted-foreground/70 bg-gradient-to-r from-blue-50 to-indigo-50/50 rounded-md px-3 py-2">
          <Sparkles className="h-3.5 w-3.5 text-primary flex-shrink-0" />
          <span>
            <strong className="text-muted-foreground">Pro tip:</strong> Consistent journaling helps identify patterns in your trading.
            Tagging by setup type (SCALP, TECHNICAL) vs news (NEWS, FOMC) helps you see what works.
          </span>
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            size="sm"
            onClick={() => onOpenChange(false)}
            className="text-xs"
          >
            Cancel
          </Button>
          <Button
            size="sm"
            onClick={handleSave}
            disabled={saving}
            className="bg-primary hover:bg-primary/90 text-white text-xs"
          >
            {saving ? (
              <>
                <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" /> Saving...
              </>
            ) : (
              <>
                <BookOpen className="h-3.5 w-3.5 mr-1.5" /> Save Journal Entry
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
