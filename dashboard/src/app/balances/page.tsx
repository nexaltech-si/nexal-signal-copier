import APIBalancesCard from '@/components/APIBalancesCard'
import MobilePageHeader from '@/components/MobilePageHeader'
import { Wallet, Info, ShieldCheck, Target } from 'lucide-react'

export default function BalancesPage() {
  return (
    <div className="flex min-h-full flex-col pb-10">
      <MobilePageHeader 
        title="Balances" 
        subtitle="API & Trading Funds"
        hidden
        icon={<Wallet className="h-5 w-5" />}
      />
      
      <header className="hidden md:flex sticky top-0 z-40 w-full tech-header">
        <div className="max-w-[1800px] w-full mx-auto flex h-14 items-center px-6 gap-3">
          <div className="p-1.5 rounded-lg bg-primary/10 border border-primary/20">
            <Wallet className="h-5 w-5 text-primary" />
          </div>
          <div className="flex flex-col">
            <h1 className="text-sm font-bold text-foreground leading-none">Balances</h1>
            <p className="text-[10px] text-[#6b7288] font-bold uppercase tracking-wider mt-1">API & Trading Funds</p>
          </div>
        </div>
      </header>

      <div className="flex-1 px-3 md:px-4 py-3 md:py-4 max-w-[1800px] mx-auto w-full space-y-4">
        <div className="flex flex-col gap-4">
          <div className="max-w-4xl">
            <h2 className="text-xl font-bold tracking-tight mb-1.5 text-foreground">Financial Overview</h2>
            <p className="text-xs text-muted-foreground font-semibold leading-relaxed">
              Monitor your service consumption and capital capitalization in real-time.
              Balances are synced automatically to ensure trading continuity.
            </p>
          </div>
          
          <APIBalancesCard />

          <div className="grid gap-3 md:gap-4 grid-cols-1 md:grid-cols-3 mt-2">
            <div className="rounded-lg border border-border bg-card p-4 shadow-sm hover:shadow-md transition-all">
              <div className="w-9 h-9 rounded-md bg-orange-100 flex items-center justify-center mb-3 text-orange-600">
                <Info className="h-4 w-4" />
              </div>
              <h3 className="font-bold text-sm mb-1.5 text-foreground">DeepSeek API</h3>
              <p className="text-xs text-muted-foreground leading-relaxed font-medium">
                Powers AI signal verification. Maintain a buffer of $2.00+ for uninterrupted service.
              </p>
              <div className="mt-3 flex items-center gap-2 text-[10px] font-bold text-primary uppercase tracking-wide">
                 Bot Engine Active
              </div>
            </div>

            <div className="rounded-lg border border-border bg-card p-4 shadow-sm hover:shadow-md transition-all">
              <div className="w-9 h-9 rounded-md bg-primary/10 flex items-center justify-center mb-3 text-primary">
                <ShieldCheck className="h-4 w-4" />
              </div>
              <h3 className="font-bold text-sm mb-1.5 text-foreground">MetaAPI Credits</h3>
              <p className="text-xs text-muted-foreground leading-relaxed font-medium">
                Vital for trade execution. Order placement stops if credits are exhausted.
              </p>
              <div className="mt-3 flex items-center gap-2 text-[10px] font-bold text-primary uppercase tracking-wide">
                Priority Sync
              </div>
            </div>

            <div className="rounded-lg border border-border bg-card p-4 shadow-sm hover:shadow-md transition-all">
              <div className="w-9 h-9 rounded-md bg-success/10 flex items-center justify-center mb-3 text-success">
                <Target className="h-4 w-4" />
              </div>
              <h3 className="font-bold text-sm mb-1.5 text-foreground">Trading Capital</h3>
              <p className="text-xs text-muted-foreground leading-relaxed font-medium">
                Your live liquidity snapshot. Protected by real-time drawdown monitoring.
              </p>
              <div className="mt-3 flex items-center gap-2 text-[10px] font-bold text-primary uppercase tracking-wide">
                 Live Margin Tracking
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
