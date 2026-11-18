'use client'

import { useState } from 'react'
import { Zap } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

interface StreakSequenceProps {
  streaks: number[]
}

export default function StreakSequence({ streaks }: StreakSequenceProps) {
  const [hovered, setHovered] = useState<number | null>(null)

  const maxAbs = streaks.reduce((m, s) => Math.max(m, Math.abs(s)), 1)
  const maxWin = streaks.reduce((m, s) => Math.max(m, s), 0)
  const maxLoss = Math.abs(streaks.reduce((m, s) => Math.min(m, s), 0))
  const current = streaks.length > 0 ? streaks[streaks.length - 1] : 0

  return (
    <Card className="border border-border shadow-sm bg-card overflow-hidden">
      <CardHeader className="py-3.5 px-5 border-b bg-muted/40">
        <CardTitle className="text-sm font-bold flex items-center gap-2 text-foreground">
          <Zap className="h-4 w-4 text-primary" />
          Win/Loss Streaks
        </CardTitle>
      </CardHeader>
      <CardContent className="p-5">
        {streaks.length === 0 ? (
          <div className="h-[180px] flex items-center justify-center text-sm text-muted-foreground">
            Not enough closed trades to compute streaks yet
          </div>
        ) : (
          <>
            <div className="grid grid-cols-3 gap-3 mb-5">
              <div className="rounded-lg border border-border/60 bg-muted/20 px-3 py-2.5 text-center">
                <p className="text-[9px] font-bold text-muted-foreground uppercase tracking-wider mb-1">Current</p>
                <p className={`text-xl font-black ${current >= 0 ? 'text-success' : 'text-destructive'}`}>
                  {Math.abs(current)}{current >= 0 ? 'W' : 'L'}
                </p>
              </div>
              <div className="rounded-lg border border-border/60 bg-muted/20 px-3 py-2.5 text-center">
                <p className="text-[9px] font-bold text-muted-foreground uppercase tracking-wider mb-1">Best Streak</p>
                <p className="text-xl font-black text-success">{maxWin}W</p>
              </div>
              <div className="rounded-lg border border-border/60 bg-muted/20 px-3 py-2.5 text-center">
                <p className="text-[9px] font-bold text-muted-foreground uppercase tracking-wider mb-1">Worst Streak</p>
                <p className="text-xl font-black text-destructive">{maxLoss}L</p>
              </div>
            </div>
            <div className="h-[140px] flex items-end gap-[3px] overflow-x-auto">
              {streaks.map((s, i) => {
                const heightPct = Math.max(8, (Math.abs(s) / maxAbs) * 100)
                const isWin = s > 0
                return (
                  <div
                    key={i}
                    className="flex flex-col justify-end items-center shrink-0 h-full"
                    style={{ width: 12 }}
                    onMouseEnter={() => setHovered(i)}
                    onMouseLeave={() => setHovered(null)}
                  >
                    {hovered === i && (
                      <span className={`text-[9px] font-bold mb-0.5 ${isWin ? 'text-success' : 'text-destructive'}`}>
                        {Math.abs(s)}{isWin ? 'W' : 'L'}
                      </span>
                    )}
                    <div
                      className="w-full rounded-t-sm transition-opacity"
                      style={{
                        height: `${heightPct}%`,
                        backgroundColor: isWin ? 'hsl(var(--success))' : 'hsl(var(--destructive))',
                        opacity: hovered === null || hovered === i ? 1 : 0.45
                      }}
                    />
                  </div>
                )
              })}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}
