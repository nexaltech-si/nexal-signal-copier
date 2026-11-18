'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import SignalsDataTable from '@/components/SignalsDataTable'
import TradesDataTable from '@/components/TradesDataTable'
import TradeActionsTable from '@/components/TradeActionsTable'
import type { SignalWithTrades, TradeWithRelations, TradeActionWithTrade } from '@/lib/types'

const TAB_STORAGE_KEY = 'dashboard_active_tab'
const VALID_TABS = ['signals', 'trades', 'actions'] as const
type TabValue = typeof VALID_TABS[number]

interface DashboardTabsProps {
  signals: SignalWithTrades[]
  trades: TradeWithRelations[]
  tradeActions: TradeActionWithTrade[]
  unverifiedCount?: number
}

export default function DashboardTabs({ signals, trades, tradeActions, unverifiedCount = 0 }: DashboardTabsProps) {
  const router = useRouter()
  const [activeTab, setActiveTab] = useState<TabValue>('signals')
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    const saved = localStorage.getItem(TAB_STORAGE_KEY) as TabValue | null
    if (saved && VALID_TABS.includes(saved)) {
      setActiveTab(saved)
    }
    setMounted(true)
  }, [])

  const handleTabChange = (value: string) => {
    const tab = value as TabValue
    setActiveTab(tab)
    localStorage.setItem(TAB_STORAGE_KEY, tab)
  }

  const activeTrades = trades.filter(t => t.status === 'EXECUTING' || t.status === 'PENDING')

  return (
    <Tabs value={mounted ? activeTab : 'signals'} onValueChange={handleTabChange} className="w-full">
      <TabsList className="h-9 bg-card border border-border p-1 rounded-lg shadow-sm w-full sm:w-auto flex">
        <TabsTrigger
          value="signals"
          className="flex-1 sm:flex-none text-xs font-semibold gap-1.5 data-[state=active]:bg-primary/10 data-[state=active]:text-primary data-[state=active]:shadow-none"
        >
          Signals
          {unverifiedCount > 0 && (
            <span className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full text-[10px] font-bold bg-gold/15 border border-gold/30 text-gold animate-data-blink">
              {unverifiedCount}
            </span>
          )}
          {signals.length - unverifiedCount > 0 && (
            <span className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full text-[10px] font-bold bg-muted text-muted-foreground">
              {signals.length - unverifiedCount}
            </span>
          )}
        </TabsTrigger>

        <TabsTrigger
          value="trades"
          className="flex-1 sm:flex-none text-xs font-semibold gap-1.5 data-[state=active]:bg-primary/10 data-[state=active]:text-primary data-[state=active]:shadow-none"
        >
          Trades
          {trades.length > 0 && (
            <span className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full text-[10px] font-bold bg-muted text-muted-foreground">
              {trades.length}
            </span>
          )}
          {activeTrades.length > 0 && (
            <span className="inline-flex items-center gap-0.5 h-[18px] px-1.5 rounded-full text-[10px] font-bold bg-success/10 border border-success/20 text-success">
              <span className="relative flex h-1.5 w-1.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-success opacity-75" />
                <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-success" />
              </span>
              {activeTrades.length}
            </span>
          )}
        </TabsTrigger>

        <TabsTrigger
          value="actions"
          className="flex-1 sm:flex-none text-xs font-semibold gap-1.5 data-[state=active]:bg-primary/10 data-[state=active]:text-primary data-[state=active]:shadow-none"
        >
          Actions
          {tradeActions.length > 0 && (
            <span className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full text-[10px] font-bold bg-muted text-muted-foreground">
              {tradeActions.length}
            </span>
          )}
        </TabsTrigger>
      </TabsList>

      <TabsContent value="signals" className="mt-3">
        <SignalsDataTable signals={signals} onSignalDeleted={() => router.refresh()} />
      </TabsContent>
      <TabsContent value="trades" className="mt-3">
        <TradesDataTable trades={trades} />
      </TabsContent>
      <TabsContent value="actions" className="mt-3">
        <TradeActionsTable actions={tradeActions} />
      </TabsContent>
    </Tabs>
  )
}
