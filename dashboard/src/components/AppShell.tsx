'use client'

import { usePathname } from 'next/navigation'
import Sidebar from '@/components/Sidebar'
import { NotificationProvider } from '@/components/NotificationProvider'
import { Toaster } from '@/components/ui/toaster'

// Auth pages get a bare page: no sidebar, no notification inbox/SSE/push,
// nothing that calls the API before the user has signed in.
const AUTH_PATHS = ['/sign-in', '/sign-up']

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const isAuthPage = AUTH_PATHS.some((p) => pathname === p || pathname?.startsWith(`${p}/`))

  if (isAuthPage) return <>{children}</>

  return (
    <NotificationProvider>
      <div className="flex h-screen overflow-hidden">
        <Sidebar />
        <main className="flex-1 overflow-y-auto overflow-x-hidden scroll-smooth overscroll-contain pb-32 md:pb-0 relative safe-area-bottom tech-canvas">
          {/* Dual ambient glow */}
          <div className="glow-primary" />
          <div className="glow-secondary" />

          <div className="relative z-10 w-full min-h-full">
            {children}
            {/* Extra spacing for mobile bottom navigation */}
            <div className="h-32 md:hidden" />
          </div>
        </main>
      </div>
      <Toaster />
    </NotificationProvider>
  )
}
