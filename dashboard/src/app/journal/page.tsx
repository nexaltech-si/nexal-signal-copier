import { BookOpen } from 'lucide-react'
import MobilePageHeader from '@/components/MobilePageHeader'
import TradeJournal from '@/components/TradeJournal'

export default function JournalPage() {
  return (
    <div className="flex flex-col min-h-full pb-10">
      <MobilePageHeader
        title="Journal"
        subtitle="Trade Log"
        icon={<BookOpen className="h-5 w-5 text-primary" />}
      />

      <header className="hidden md:flex sticky top-0 z-40 w-full tech-header">
        <div className="max-w-[1800px] w-full mx-auto flex h-14 items-center px-6 gap-3">
          <div className="p-1.5 rounded-lg bg-primary/10 border border-primary/20">
            <BookOpen className="h-5 w-5 text-primary" />
          </div>
          <div className="flex flex-col">
            <h1 className="text-sm font-bold text-foreground leading-none">Journal</h1>
            <p className="text-[10px] text-[#697188] font-semibold uppercase tracking-wider mt-0.5">Trade Log</p>
          </div>
        </div>
      </header>

      <main className="flex-1 px-4 md:px-8 py-4 md:py-6">
        <div className="max-w-[1800px] mx-auto">
          <TradeJournal />
        </div>
      </main>
    </div>
  )
}
