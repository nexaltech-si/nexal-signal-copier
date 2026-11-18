'use client'

import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { formatDate } from '@/lib/utils'
import { Activity, TrendingUp, TrendingDown, X, Edit, Scissors, Search } from 'lucide-react'
 
interface TradeActionsTableProps {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  actions: any[]
}

const getActionIcon = (actionType: string) => {
  switch (actionType) {
    case 'CLOSE':
      return <X className="h-3 w-3" />
    case 'PARTIAL_CLOSE':
    case 'AUTO_PARTIAL':
      return <Scissors className="h-3 w-3" />
    case 'MODIFY_SL':
    case 'MODIFY_TP':
      return <Edit className="h-3 w-3" />
    case 'TRAILING_STOP':
    case 'BREAKEVEN':
      return <TrendingUp className="h-3 w-3" />
    case 'AUTO_TP':
      return <TrendingDown className="h-3 w-3" />
    default:
      return <Activity className="h-3 w-3" />
  }
}

const getActionColor = (actionType: string) => {
  switch (actionType) {
    case 'CLOSE':
      return 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200'
    case 'PARTIAL_CLOSE':
    case 'AUTO_PARTIAL':
      return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200'
    case 'MODIFY_SL':
      return 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200'
    case 'MODIFY_TP':
      return 'bg-primary/10 text-blue-800 dark:bg-blue-900 dark:text-blue-200'
    case 'TRAILING_STOP':
    case 'BREAKEVEN':
      return 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200'
    case 'AUTO_TP':
      return 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200'
    default:
      return 'bg-gray-100 text-gray-800 dark:bg-gray-900 dark:text-gray-200'
  }
}

const getTriggerColor = (triggeredBy: string) => {
  const colors: Record<string, string> = {
    telegram_reply: 'bg-primary/10 text-primary border border-primary/20 dark:bg-blue-900 dark:text-blue-300',
    telegram_message: 'bg-cyan-100 text-cyan-700 dark:bg-cyan-900 dark:text-cyan-300',
    system: 'bg-gray-100 text-gray-700 dark:bg-gray-900 dark:text-gray-300',
    auto_trailing: 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300',
    auto_breakeven: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900 dark:text-yellow-300',
    auto_tp: 'bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300',
    auto_position_monitor: 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900 dark:text-indigo-300',
    manual: 'bg-orange-100 text-orange-700 dark:bg-orange-900 dark:text-orange-300',
  }
  return colors[triggeredBy] || colors.system
}

export default function TradeActionsTable({ actions }: TradeActionsTableProps) {
  const [search, setSearch] = useState('')

  const filtered = actions.filter((a) => {
    const q = search.toLowerCase()
    return (
      !q ||
      a.trade.symbol.toLowerCase().includes(q) ||
      a.actionType.toLowerCase().includes(q) ||
      a.triggeredBy.toLowerCase().includes(q) ||
      (a.trade.positionId?.toString() || '').includes(q) ||
      (a.trade.signal?.messageId?.toString() || '').includes(q)
    )
  })

  return (
    <Card className="border-0 shadow-sm">
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-base font-semibold">Trade Actions</CardTitle>
        <div className="flex items-center gap-2">
          <Badge variant="secondary" className="text-xs">{filtered.length} actions</Badge>
          <div className="relative">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground" />
            <Input
              placeholder="Search..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="h-7 pl-7 text-xs w-40"
            />
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {/* Desktop Table View */}
        <div className="hidden md:block overflow-x-auto">
          <Table className="min-w-[1100px]">
            <TableHeader>
              <TableRow>
                <TableHead className="text-xs min-w-[130px]">Action</TableHead>
                <TableHead className="text-xs min-w-[90px]">Status</TableHead>
                <TableHead className="text-xs min-w-[70px]">Symbol</TableHead>
                <TableHead className="text-xs min-w-[110px]">Trigger</TableHead>
                <TableHead className="text-xs min-w-[130px]">SL Change</TableHead>
                <TableHead className="text-xs min-w-[130px]">TP Change</TableHead>
                <TableHead className="text-xs min-w-[80px]">Price</TableHead>
                <TableHead className="text-xs min-w-[80px]">Profit (Pips)</TableHead>
                <TableHead className="text-xs min-w-[70px]">Position</TableHead>
                <TableHead className="text-xs min-w-[70px]">Signal</TableHead>
                <TableHead className="text-xs min-w-[160px]">Details</TableHead>
                <TableHead className="text-xs min-w-[100px]">Date</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((action) => {
                const userReplyMatch = action.details?.match(/User reply: "([^"]+)"/)
                const userCommand = userReplyMatch ? userReplyMatch[1] : null
                const detailsText = action.details?.includes('User reply:')
                  ? (action.details.match(/User reply: "[^"]+" - (.+)/)?.[1] ?? action.details)
                  : action.details

                return (
                  <TableRow key={action.id} className="text-xs">
                    <TableCell>
                      <Badge className={`${getActionColor(action.actionType)} gap-1 whitespace-nowrap`}>
                        {getActionIcon(action.actionType)}
                        {action.actionType.replace(/_/g, ' ')}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={action.success ? 'default' : 'destructive'}
                        className="whitespace-nowrap"
                      >
                        {action.success ? '✓ Success' : '✗ Failed'}
                      </Badge>
                    </TableCell>
                    <TableCell className="font-semibold whitespace-nowrap">{action.trade.symbol}</TableCell>
                    <TableCell>
                      <Badge className={`${getTriggerColor(action.triggeredBy)} whitespace-nowrap`}>
                        {action.triggeredBy.replace(/_/g, ' ')}
                      </Badge>
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {action.oldStopLoss !== null && action.newStopLoss !== null ? (
                        <span>
                          <span className="text-muted-foreground">{action.oldStopLoss.toFixed(5)}</span>
                          <span className="mx-1">→</span>
                          <span className="text-orange-600">{action.newStopLoss.toFixed(5)}</span>
                        </span>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {action.oldTakeProfit !== null && action.newTakeProfit !== null ? (
                        <span>
                          <span className="text-muted-foreground">{action.oldTakeProfit.toFixed(5)}</span>
                          <span className="mx-1">→</span>
                          <span className="text-primary">{action.newTakeProfit.toFixed(5)}</span>
                        </span>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {action.currentPrice !== null ? action.currentPrice.toFixed(5) : <span className="text-muted-foreground">—</span>}
                    </TableCell>
                    <TableCell>
                      {action.profitPips !== null && action.profitPips !== undefined ? (
                        <span className={`font-medium ${action.profitPips >= 0 ? 'text-green-600' : 'text-destructive'}`}>
                          {action.profitPips >= 0 ? '+' : ''}{action.profitPips.toFixed(1)}
                        </span>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell>
                      {action.trade.positionId ? (
                        <Badge variant="outline" className="text-xs font-mono">
                          {action.trade.positionId}
                        </Badge>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell>
                      {action.trade.signal ? (
                        <Badge variant="outline" className="text-xs bg-primary/10 dark:bg-blue-950">
                          #{action.trade.signal.messageId}
                        </Badge>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="max-w-[200px]">
                      {userCommand ? (
                        <div className="rounded bg-muted/50 px-1.5 py-0.5 font-mono text-xs truncate" title={userCommand}>
                          &quot;{userCommand}&quot;
                        </div>
                      ) : detailsText ? (
                        <span className="text-muted-foreground truncate block max-w-[200px]" title={detailsText}>
                          {detailsText}
                        </span>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-muted-foreground whitespace-nowrap">
                      {formatDate(action.createdAt)}
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>

        {/* Mobile Card View */}
        <div className="md:hidden space-y-3 p-3 bg-muted/20">
          {filtered.map((action) => {
            const userReplyMatch = action.details?.match(/User reply: "([^"]+)"/)
            const userCommand = userReplyMatch ? userReplyMatch[1] : null

            return (
              <div key={action.id} className="bg-card rounded-xl border border-border p-4 shadow-sm space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Badge className={`${getActionColor(action.actionType)} gap-1 whitespace-nowrap text-[10px] h-5 px-1.5`}>
                      {getActionIcon(action.actionType)}
                      {action.actionType.replace(/_/g, ' ')}
                    </Badge>
                    <span className="font-bold text-sm text-foreground">{action.trade.symbol}</span>
                  </div>
                  <Badge
                    variant={action.success ? 'default' : 'destructive'}
                    className="text-[10px] h-5 px-1.5"
                  >
                    {action.success ? '✓' : '✗'}
                  </Badge>
                </div>

                <div className="grid grid-cols-2 gap-y-3 gap-x-2 text-xs border-y border-border/50 py-3">
                  <div>
                    <p className="text-muted-foreground text-[10px] uppercase tracking-wider font-semibold mb-0.5">Trigger</p>
                    <Badge className={`${getTriggerColor(action.triggeredBy)} text-[10px] h-4 px-1`}>
                      {action.triggeredBy.replace(/_/g, ' ')}
                    </Badge>
                  </div>
                  <div>
                    <p className="text-muted-foreground text-[10px] uppercase tracking-wider font-semibold mb-0.5">Profit (Pips)</p>
                    {action.profitPips !== null && action.profitPips !== undefined ? (
                      <span className={`font-bold ${action.profitPips >= 0 ? 'text-success' : 'text-destructive'}`}>
                        {action.profitPips >= 0 ? '+' : ''}{action.profitPips.toFixed(1)}
                      </span>
                    ) : <span className="text-muted-foreground/70">—</span>}
                  </div>
                  {(action.oldStopLoss || action.newStopLoss) && (
                    <div className="col-span-2">
                      <p className="text-muted-foreground text-[10px] uppercase tracking-wider font-semibold mb-0.5">SL Change</p>
                      <div className="font-mono text-[11px] flex items-center gap-2">
                        <span className="text-muted-foreground/70">{action.oldStopLoss?.toFixed(5) || '—'}</span>
                        <span className="text-muted-foreground/50">→</span>
                        <span className="text-orange-600 font-semibold">{action.newStopLoss?.toFixed(5) || '—'}</span>
                      </div>
                    </div>
                  )}
                  {(action.oldTakeProfit || action.newTakeProfit) && (
                    <div className="col-span-2">
                      <p className="text-muted-foreground text-[10px] uppercase tracking-wider font-semibold mb-0.5">TP Change</p>
                      <div className="font-mono text-[11px] flex items-center gap-2">
                        <span className="text-muted-foreground/70">{action.oldTakeProfit?.toFixed(5) || '—'}</span>
                        <span className="text-muted-foreground/50">→</span>
                        <span className="text-primary font-semibold">{action.newTakeProfit?.toFixed(5) || '—'}</span>
                      </div>
                    </div>
                  )}
                  {action.trade.positionId && (
                    <div>
                      <p className="text-muted-foreground text-[10px] uppercase tracking-wider font-semibold mb-0.5">Position</p>
                      <span className="font-mono font-medium">#{action.trade.positionId}</span>
                    </div>
                  )}
                  <div>
                    <p className="text-muted-foreground text-[10px] uppercase tracking-wider font-semibold mb-0.5">Time</p>
                    <span className="text-muted-foreground">{formatDate(action.createdAt)}</span>
                  </div>
                </div>

                {userCommand && (
                  <div className="bg-muted/50 rounded-lg p-2 border border-border/50 italic text-[11px] text-foreground/80">
                    &quot;{userCommand}&quot;
                  </div>
                )}
              </div>
            )
          })}
        </div>

        {filtered.length === 0 && (
          <div className="text-center text-muted-foreground py-8">
            <Activity className="h-10 w-10 mx-auto mb-2 opacity-30" />
            <p className="text-sm">{actions.length === 0 ? 'No trade actions found' : 'No results match your search'}</p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
