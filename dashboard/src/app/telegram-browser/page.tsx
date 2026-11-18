import TelegramBrowser from '@/components/TelegramBrowser'

export const metadata = {
  title: 'Telegram Browser',
  description: 'Browse Telegram channels and manually execute signals',
}

export default function TelegramBrowserPage() {
  return (
    /*
     * Mobile:  position:fixed, sits between the app header (80px from top)
     *          and the bottom nav (86px from bottom).
     * Desktop: position:absolute inset-0 inside main (which has position:relative),
     *          giving a reliable fixed height so the message list can scroll
     *          without the container expanding to full content height.
     */
    <div className="fixed inset-x-0 top-[80px] bottom-[86px] z-10 md:absolute md:inset-0 md:flex md:flex-col md:px-4 md:py-6 md:gap-3">
      <div className="shrink-0 hidden md:block">
        <h1 className="text-lg font-semibold">Telegram Browser</h1>
        <p className="text-xs text-muted-foreground mt-0.5">
          Browse channel history · manually execute messages as signals
        </p>
      </div>
      {/* h-full on mobile fills the fixed container; flex-1 min-h-0 on desktop */}
      <div className="h-full md:flex-1 md:min-h-0">
        <TelegramBrowser />
      </div>
    </div>
  )
}
