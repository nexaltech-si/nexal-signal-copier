'use client'

import React, { useState, useEffect } from 'react'
import Link from 'next/link'
import Image from 'next/image'
import { APP_ICON, APP_NAME } from '@/lib/brand'
import { usePathname, useRouter } from 'next/navigation'
import { UserButton } from "@clerk/nextjs"
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import NotificationBell from '@/components/NotificationBell'
import DarkModeToggle from '@/components/DarkModeToggle'
import LiteModeToggle from '@/components/LiteModeToggle'
import ProviderBadge from '@/components/ProviderBadge'
import { useLiteMode } from '@/hooks/useLiteMode'
import {
  LayoutDashboard,
  Settings,
  ChevronLeft,
  ChevronRight,
  BarChart3,
  History,
  Wallet,
  FileText,
  BookOpen,
  Menu,
  TrendingUp,
  Zap,
  Clock,
  Brain,
  Calendar,
  Link2,
  Layers,
  MessageSquare,
  Gamepad2,
  Monitor,
  FlaskConical,
  Workflow,
  LineChart,
  KeyRound,
  Copy,
  Shield,
} from 'lucide-react'

interface SidebarProps {
  className?: string
}

interface NavItem {
  name: string
  href: string
  icon: React.ElementType
  description: string
}

interface NavCategory {
  category: string
  items: NavItem[]
}

const navigation: NavCategory[] = [
  {
    category: 'Overview',
    items: [
      { name: 'Dashboard', href: '/', icon: LayoutDashboard, description: 'Overview & Stats' },
      { name: 'Hermes', href: '/hermes', icon: Brain, description: 'Agent chat, setups & analytics' },
    ],
  },
  {
    category: 'Trading',
    items: [
      { name: 'Account', href: '/account', icon: TrendingUp, description: 'MT5 Account Management' },
      { name: 'History', href: '/history', icon: History, description: 'All Trades & Signals' },
      { name: 'Plans', href: '/plans', icon: Layers, description: 'Conditional Trade Plans' },
      { name: 'Journal', href: '/journal', icon: BookOpen, description: 'Trade Journal & Notes' },
      { name: 'Calendar', href: '/calendar', icon: Calendar, description: 'Economic Events' },
      { name: 'Telegram', href: '/telegram-browser', icon: MessageSquare, description: 'Browse & Execute Signals' },
      { name: 'MT5 Terminal', href: '/mt5-terminal', icon: Monitor, description: 'Live MT5 Desktop (VNC)' },
    ],
  },
  {
    category: 'Analytics',
    items: [
      { name: 'Performance', href: '/performance', icon: BarChart3, description: 'Analytics & Metrics' },
      { name: 'Risk', href: '/drawdown', icon: Shield, description: 'Drawdown & Breach Protection' },
      { name: 'Simulator', href: '/simulator', icon: FlaskConical, description: 'Replay signals through the live pipeline' },
      { name: 'Flow Replay', href: '/simulator/flow', icon: Workflow, description: 'Real channel messages, real bot logic, simulated broker' },
      { name: 'gs-quant Insights', href: '/gsquant-insights', icon: LineChart, description: 'Read-only technical & performance analytics' },
    ],
  },
  {
    category: 'Configuration',
    items: [
      { name: 'Settings', href: '/settings', icon: Settings, description: 'System Configuration' },
      { name: 'Connections', href: '/connection', icon: Link2, description: 'Service Connections' },
      { name: 'Discord', href: '/discord', icon: Gamepad2, description: 'Servers & Channels to Listen to' },
      { name: 'AI & Bot', href: '/config', icon: Brain, description: 'AI & Bot Configuration' },
      { name: 'Channel Rules', href: '/channel-behavior', icon: Brain, description: 'Per-Channel Rules' },
      { name: 'Trade Copier', href: '/copier', icon: Copy, description: 'Mirror accounts & live sync' },
      { name: 'API Keys', href: '/settings/api-keys', icon: KeyRound, description: 'EA Mirror Feed Access' },
    ],
  },
  {
    category: 'System',
    items: [
      { name: 'Logs', href: '/logs', icon: FileText, description: 'System Logs' },
      { name: 'AI Usage', href: '/ai-usage', icon: Brain, description: 'AI Token & Cost Usage' },
      { name: 'Balances', href: '/balances', icon: Wallet, description: 'Credits & Account' },
    ],
  },
]

// Flat list for mobile nav
const allNavItems = navigation.flatMap(g => g.items)

type LogAlert = { tone: 'red' | 'amber'; reason: string } | null

// Polls the log monitor's headline status for the dot on the Logs nav item.
function useLogAlert(): LogAlert {
  const [alert, setAlert] = useState<LogAlert>(null)
  useEffect(() => {
    let cancelled = false
    const check = async () => {
      if (document.hidden) return
      try {
        const res = await fetch('/api/logs/monitor?summary=1', { cache: 'no-store' })
        if (!res.ok) return
        const d = await res.json()
        if (cancelled) return
        if (!d.botOnline) setAlert({ tone: 'red', reason: 'Bot offline' })
        else if (d.status === 'critical') setAlert({ tone: 'red', reason: d.statusReason })
        else if (d.status === 'warning') setAlert({ tone: 'amber', reason: d.statusReason })
        else setAlert(null)
      } catch { /* keep last state */ }
    }
    check()
    const t = setInterval(check, 60_000)
    return () => { cancelled = true; clearInterval(t) }
  }, [])
  return alert
}

function LogAlertDot({ alert, className }: { alert: LogAlert; className?: string }) {
  if (!alert) return null
  return (
    <span
      title={alert.reason}
      className={cn('rounded-full w-2 h-2', alert.tone === 'red' ? 'bg-red-500 animate-pulse' : 'bg-amber-500', className)}
    />
  )
}

export default function Sidebar({ className }: SidebarProps) {
  const { enabled: liteEnabled, hrefs: liteHrefs, hydrated } = useLiteMode()

  // Until localStorage has been read, render the full nav so the first client
  // paint matches the server HTML.
  const liteActive = hydrated && liteEnabled

  // Groups left entirely empty by the filter are dropped so no orphan headers
  // ("ANALYTICS" with nothing under it) remain.
  const visibleNavigation = React.useMemo(() => {
    if (!liteActive) return navigation
    return navigation
      .map(g => ({ ...g, items: g.items.filter(i => liteHrefs.includes(i.href)) }))
      .filter(g => g.items.length > 0)
  }, [liteActive, liteHrefs])

  // Mobile nav slices off this list, so it must follow the same filter —
  // otherwise the bottom bar would show items lite mode has hidden.
  const visibleNavItems = React.useMemo(
    () => visibleNavigation.flatMap(g => g.items),
    [visibleNavigation]
  )

  const [collapsed, setCollapsed] = useState(false)
  const [isScrolled, setIsScrolled] = useState(false)
  const [isMenuExpanded, setIsMenuExpanded] = useState(false)
  const [isDark, setIsDark] = useState(true)
  const pathname = usePathname()
  const router = useRouter()
  const logAlert = useLogAlert()

  useEffect(() => {
    const mainElement = document.querySelector('main')
    if (mainElement) {
      const handleScroll = () => {
        setIsScrolled(mainElement.scrollTop > 10)
      }
      mainElement.addEventListener('scroll', handleScroll)
      return () => mainElement.removeEventListener('scroll', handleScroll)
    }
  }, [])

  // Theme detection for logo switching
  useEffect(() => {
    const saved = localStorage.getItem('theme')
    const dark = saved ? saved === 'dark' : true
    setIsDark(dark)

    const observer = new MutationObserver(() => {
      const isDarkNow = document.documentElement.classList.contains('dark')
      setIsDark(isDarkNow)
    })
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
    return () => observer.disconnect()
  }, [])

  return (
    <>
      {/* ── Mobile top header ── */}
      <div className={cn(
        "mobile-top-bar md:hidden fixed z-[60] flex items-center justify-between no-select transition-all duration-300 ease-in-out",
        isScrolled
          ? "top-3 left-3 right-3 h-[60px] px-3 bg-card/90 backdrop-blur-[20px] border border-border shadow-[0_4px_24px_rgba(0,0,0,0.35)] rounded-2xl"
          : "top-0 left-0 right-0 h-[70px] px-4 bg-transparent"
      )}>
        <div className="flex items-center gap-2 min-w-0 flex-1 mr-2">
          <div className={cn("shrink-0 transition-transform duration-300", isScrolled ? "scale-90" : "scale-100")}>
            <div className="w-[34px] h-[34px] relative">
              <Image src={APP_ICON} alt={APP_NAME} fill className="object-contain rounded-lg" />
            </div>
          </div>
          {!isScrolled ? (
            <span className="font-bold text-[18px] text-foreground tracking-[-0.02em] animate-in fade-in duration-500 truncate">{APP_NAME}</span>
          ) : (
            <span className="font-bold text-[15px] text-foreground tracking-tight animate-in slide-in-from-bottom-2 duration-300 truncate">
              {pathname === '/' ? 'Dashboard' :
               pathname.includes('signals') ? 'Signal' :
               pathname.includes('trades') ? 'Trade' :
               allNavItems.find(n => n.href === pathname)?.name || APP_NAME}
            </span>
          )}
        </div>

        <div className="flex items-center gap-1.5 shrink-0">
          {/* Smart Close & Refresh controls - only on account page */}
          {pathname === '/account' && (
            <>
              <button
                onClick={() => document.dispatchEvent(new CustomEvent('open-smart-close-settings'))}
                className="rounded-full flex items-center justify-center transition-all duration-300 w-8 h-8 bg-gold/10 hover:bg-gold/20 border border-gold/20"
                title="Smart Close Settings"
              >
                <Zap className="h-[18px] w-[18px] text-gold" />
              </button>
              <button
                onClick={() => document.dispatchEvent(new CustomEvent('open-refresh-settings'))}
                className="rounded-full flex items-center justify-center transition-all duration-300 w-8 h-8 bg-primary/10 hover:bg-primary/20 border border-primary/20"
                title="Refresh Interval Settings"
              >
                <Clock className="h-[18px] w-[18px] text-primary" />
              </button>
            </>
          )}

          <NotificationBell />

          <LiteModeToggle size="xs" />

          <DarkModeToggle size="xs" />

          <div className={cn(
            "flex items-center border-l border-border/50 transition-all duration-300",
            "ml-0.5 pl-2", isScrolled ? "h-5" : "h-6"
          )}>
            <UserButton />
          </div>
        </div>
      </div>

      {/* ── Desktop sidebar ── */}
      <aside
        className={cn(
          'relative hidden md:flex flex-col border-r transition-all duration-300 ease-in-out z-[45]',
          'bg-background border-border',
          collapsed ? 'w-14' : 'w-52',
          className
        )}
      >
        {/* Logo area */}
        <div className="flex h-16 items-center justify-center border-b border-border relative overflow-hidden">
          {/* Subtle top accent line */}
          <div className="absolute top-0 left-0 right-0 h-[1px] bg-gradient-to-r from-transparent via-primary/40 to-transparent" />
          {!collapsed ? (
            <div className="flex items-center justify-center gap-2.5 w-full px-4 min-w-0">
              <Image src={APP_ICON} alt="" width={32} height={32} className="h-8 w-8 rounded-lg shrink-0" priority />
              <span className="font-bold text-[17px] text-foreground tracking-[-0.02em] truncate">{APP_NAME}</span>
            </div>
          ) : (
            <div className="flex items-center justify-center mx-auto relative">
              <Image
                src={APP_ICON}
                alt={APP_NAME}
                width={28}
                height={28}
                className="h-7 w-7 object-contain rounded-md"
                priority
              />
            </div>
          )}
        </div>

        <div className={cn('border-b border-border', collapsed ? 'px-1 py-1.5' : 'px-2 py-1.5')}>
          <ProviderBadge collapsed={collapsed} />
        </div>

        <nav className={cn("flex-1 p-2 mt-1 overflow-y-auto no-scrollbar", collapsed ? "space-y-0" : "space-y-4")}>
          {visibleNavigation.map((group, idx) => (
            <div key={group.category}>
              {!collapsed && (
                <div className={cn("px-2 mb-1.5", idx > 0 && "pt-1 border-t border-border")}>
                  <span className="font-mono text-[9px] font-semibold uppercase tracking-[0.18em] text-muted-foreground/50">
                    {group.category}
                  </span>
                </div>
              )}
              {collapsed && idx > 0 && (
                <div className="mx-2 my-0.5 h-px bg-border/40" />
              )}
              <div className="space-y-0.5">
                {group.items.map((item) => {
                  const isActive = pathname === item.href
                  const Icon = item.icon
                  return (
                    <Link key={item.name} href={item.href}>
                      <Button
                        variant="ghost"
                        className={cn(
                          'w-full justify-start group relative h-9 text-xs transition-all duration-150',
                          collapsed ? 'px-2' : 'px-2.5',
                          isActive
                            ? 'bg-primary/10 text-primary hover:bg-primary/15 hover:text-primary font-semibold border-l-2 border-primary rounded-l-none'
                            : 'text-muted-foreground hover:text-foreground hover:bg-card/5'
                        )}
                      >
                        <Icon
                          className={cn(
                            'h-4 w-4 flex-shrink-0 transition-colors',
                            collapsed ? 'mx-auto' : 'mr-2.5',
                            isActive ? 'text-primary' : 'text-muted-foreground group-hover:text-foreground'
                          )}
                        />
                        {!collapsed && (
                          <span
                            className={cn(
                              'font-semibold text-xs',
                              isActive ? 'text-primary' : 'text-muted-foreground group-hover:text-foreground'
                            )}
                          >
                            {item.name}
                          </span>
                        )}
                        {item.href === '/logs' && (
                          <LogAlertDot alert={logAlert} className={collapsed ? 'absolute right-1.5 top-1.5' : 'ml-auto'} />
                        )}
                        {/* Active indicator dot for collapsed state */}
                        {collapsed && isActive && (
                          <span className="absolute right-1.5 top-1/2 -translate-y-1/2 w-1.5 h-1.5 rounded-full bg-primary" />
                        )}
                        {/* Tooltip for collapsed */}
                        {collapsed && (
                          <div className="absolute left-full ml-2 px-2.5 py-1.5 bg-card border border-border text-foreground text-xs font-semibold rounded-md shadow-lg shadow-black/40 opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity whitespace-nowrap z-50">
                            {item.name}
                          </div>
                        )}
                      </Button>
                    </Link>
                  )
                })}
              </div>
            </div>
          ))}
        </nav>

        <div className="p-2 border-t border-border space-y-2">
          <div className={cn(
            "flex items-center gap-3 px-2 py-2 rounded-md hover:bg-card/5 transition-colors",
            collapsed && "justify-center px-0"
          )}>
            {!collapsed ? (
              <>
                <UserButton />
                <div className="flex flex-col truncate flex-1">
                  <span className="text-[11px] font-semibold text-foreground leading-none">Account</span>
                  <span className="text-[10px] text-muted-foreground mt-1">Manage profile</span>
                </div>
                <NotificationBell />
                <LiteModeToggle size="sm" />
                <DarkModeToggle size="sm" />
              </>
            ) : (
              <div className="flex flex-col items-center gap-4">
                <DarkModeToggle size="sm" />
                <LiteModeToggle size="sm" />
                <NotificationBell />
                <UserButton />
              </div>
            )}
          </div>
        </div>

        {/* Collapse toggle */}
        <Button
          variant="ghost"
          size="icon"
          onClick={() => setCollapsed(!collapsed)}
          className="absolute -right-3 top-5 h-5 w-5 rounded-full border border-border bg-card shadow-md shadow-black/40 hover:bg-accent"
        >
          {collapsed ? (
            <ChevronRight className="h-3 w-3 text-muted-foreground" />
          ) : (
            <ChevronLeft className="h-3 w-3 text-muted-foreground" />
          )}
        </Button>
      </aside>

      {/* ── Mobile bottom nav ── */}
      <nav className="mobile-bottom-nav md:hidden fixed bottom-6 left-4 right-4 z-50 no-select">
        {isMenuExpanded && (
          <div className="absolute bottom-[76px] left-0 right-0 bg-card/95 backdrop-blur-[14px] border border-border shadow-[0_12px_40px_rgba(0,0,0,0.5)] rounded-[22px] p-2 animate-in fade-in slide-in-from-bottom-4 duration-300">
            <div className="grid grid-cols-4 gap-1">
              {visibleNavItems.slice(4).map((item) => {
                const isActive = pathname === item.href
                const Icon = item.icon
                return (
                  <Link
                    key={item.name}
                    href={item.href}
                    onClick={() => setIsMenuExpanded(false)}
                    className={cn(
                      'flex flex-col items-center justify-center py-3 gap-1 rounded-[16px] transition-all',
                      isActive ? 'text-primary bg-primary/10' : 'text-muted-foreground'
                    )}
                  >
                    <span className="relative">
                      <Icon className="h-5 w-5" />
                      {item.href === '/logs' && <LogAlertDot alert={logAlert} className="absolute -right-1 -top-1" />}
                    </span>
                    <span className="text-[10px] font-medium">{item.name}</span>
                  </Link>
                )
              })}
            </div>
          </div>
        )}

        <div className="bg-card/90 backdrop-blur-[14px] border border-border shadow-[0_8px_32px_rgba(0,0,0,0.5)]  rounded-[18px]">
          <div className="grid grid-cols-5 h-[62px] px-2 py-2">
            {visibleNavItems.slice(0, 4).map((item) => {
              const isActive = pathname === item.href
              const Icon = item.icon

              return (
                <Link
                  key={item.name}
                  href={item.href}
                  onClick={() => setIsMenuExpanded(false)}
                  className={cn(
                    'flex flex-col items-center justify-center gap-1 transition-all duration-200 rounded-[14px]',
                    isActive
                      ? 'text-primary bg-primary/10 font-bold'
                      : 'text-muted-foreground hover:text-foreground'
                  )}
                >
                  <Icon className={cn(
                    'h-5 w-5 transition-colors',
                    isActive ? 'text-primary' : 'text-muted-foreground'
                  )} />
                  <span className={cn(
                    'text-[10px]',
                    isActive ? 'text-primary' : 'text-muted-foreground'
                  )}>{item.name}</span>
                </Link>
              )
            })}

            {/* Menu Toggle Button */}
            <button
              onClick={() => setIsMenuExpanded(!isMenuExpanded)}
              className={cn(
                'flex flex-col items-center justify-center gap-1 transition-all duration-200 rounded-[14px]',
                isMenuExpanded || visibleNavItems.slice(4).some(n => n.href === pathname)
                  ? 'text-primary bg-primary/10 font-bold'
                  : 'text-muted-foreground'
              )}
            >
              <Menu className="h-5 w-5" />
              <span className="text-[10px]">Menu</span>
            </button>
          </div>
        </div>
      </nav>
    </>
  )
}
