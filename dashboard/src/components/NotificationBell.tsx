'use client'

import React, { useState } from 'react'
import { APP_NAME } from '@/lib/brand'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { useNotifications, AppNotification } from './NotificationProvider'
import {
  Bell, BellRing, BellOff, AlertCircle, TrendingUp, Info, CheckCircle2, ShieldAlert,
  ArrowRightLeft, AlertTriangle, X, Share, Loader2, Send, CheckCheck,
} from 'lucide-react'
import { cn } from "@/lib/utils"
import { formatDistanceToNow } from 'date-fns'

function NotificationIcon({ n }: { n: AppNotification }) {
  if (n.severity === 'ERROR') return <AlertCircle className="h-4 w-4 text-destructive" />
  if (n.severity === 'WARNING') return <AlertTriangle className="h-4 w-4 text-gold" />
  switch (n.type) {
    case 'SIGNAL': return <TrendingUp className="h-4 w-4 text-primary" />
    case 'TRADE': return n.severity === 'SUCCESS'
      ? <CheckCircle2 className="h-4 w-4 text-emerald-500" />
      : <ArrowRightLeft className="h-4 w-4 text-primary" />
    case 'CONNECTION': return <ShieldAlert className="h-4 w-4 text-gold" />
    default: return <Info className="h-4 w-4 text-muted-foreground" />
  }
}

function PushBanner() {
  const { pushStatus, pushBusy, enablePush, disablePush, sendTest } = useNotifications()

  if (pushStatus === 'loading') return null

  if (pushStatus === 'on') {
    return (
      <div className="px-4 py-2.5 border-b border-border/50 flex items-center gap-2 text-[11px]">
        <BellRing className="h-3.5 w-3.5 text-emerald-500 shrink-0" />
        <span className="text-muted-foreground flex-1 min-w-0 truncate">Push is on for this device</span>
        <button onClick={sendTest} className="flex items-center gap-1 font-semibold text-primary hover:underline">
          <Send className="h-3 w-3" /> Test
        </button>
        <button onClick={disablePush} disabled={pushBusy} className="font-semibold text-muted-foreground hover:text-foreground disabled:opacity-50">
          Turn off
        </button>
      </div>
    )
  }

  const message = {
    'ios-install': (
      <>On iPhone, tap <Share className="inline h-3 w-3 -mt-0.5" /> Share → <b>Add to Home Screen</b>, then open {APP_NAME} from the Home Screen to turn on notifications.</>
    ),
    unsupported: <>This browser doesn&apos;t support push notifications.</>,
    denied: <>Notifications are blocked. Allow them in your browser or phone settings for this site, then reload.</>,
    off: <>Get trade and signal alerts on this device, even when {APP_NAME} is closed.</>,
  }[pushStatus]

  return (
    <div className="px-4 py-3 border-b border-border/50 bg-primary/5 flex items-start gap-3">
      <BellOff className="h-4 w-4 text-primary mt-0.5 shrink-0" />
      <p className="text-[11px] leading-relaxed text-muted-foreground flex-1">{message}</p>
      {pushStatus === 'off' && (
        <button
          onClick={enablePush}
          disabled={pushBusy}
          className="shrink-0 text-[11px] bg-primary text-primary-foreground px-3 py-1.5 rounded-full font-bold hover:bg-primary/90 transition-colors disabled:opacity-60 flex items-center gap-1"
        >
          {pushBusy && <Loader2 className="h-3 w-3 animate-spin" />}
          Enable
        </button>
      )}
    </div>
  )
}

export default function NotificationBell() {
  const { notifications, unreadCount, live, hasMore, loadMore, markRead, clear, open } = useNotifications()
  const [isOpen, setIsOpen] = useState(false)

  return (
    <Popover open={isOpen} onOpenChange={setIsOpen}>
      <PopoverTrigger asChild>
        <button className="relative cursor-pointer group" aria-label={`Notifications${unreadCount ? ` (${unreadCount} unread)` : ''}`}>
          <div className={cn(
            "rounded-full flex items-center justify-center transition-all duration-300 w-9 h-9",
            "bg-muted/80 hover:bg-border/80"
          )}>
            <Bell className="h-[18px] w-[18px] text-muted-foreground" />
          </div>
          {unreadCount > 0 && (
            <span className="absolute -right-0.5 -top-0.5 min-w-[18px] h-[18px] px-1 bg-primary text-white text-[10px] font-bold rounded-full border-2 border-card flex items-center justify-center animate-in zoom-in">
              {unreadCount > 99 ? '99+' : unreadCount}
            </span>
          )}
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="center"
        sideOffset={14}
        collisionPadding={16}
        className="w-[calc(100vw-32px)] sm:w-[380px] p-0 bg-popover/95 backdrop-blur-[14px] border-border shadow-xl rounded-[22px] overflow-hidden"
      >
        <div className="px-4 py-3.5 border-b border-border/50 flex items-center gap-2">
          <h3 className="font-bold text-sm text-foreground">Notifications</h3>
          <span
            className={cn("w-1.5 h-1.5 rounded-full", live ? "bg-emerald-500" : "bg-muted-foreground/40")}
            title={live ? 'Live' : 'Reconnecting…'}
          />
          {unreadCount > 0 && (
            <button
              onClick={() => markRead()}
              className="ml-auto flex items-center gap-1 text-[11px] font-semibold text-primary hover:underline"
            >
              <CheckCheck className="h-3.5 w-3.5" /> Mark all read
            </button>
          )}
        </div>

        <PushBanner />

        <div className="max-h-[min(420px,60vh)] overflow-y-auto no-scrollbar">
          {notifications.length === 0 ? (
            <div className="p-8 text-center">
              <div className="w-10 h-10 bg-muted/50 rounded-full flex items-center justify-center mx-auto mb-3">
                <Bell className="h-5 w-5 text-muted-foreground/50" />
              </div>
              <p className="text-xs text-muted-foreground/70">All caught up!</p>
            </div>
          ) : (
            <div className="flex flex-col divide-y divide-border/50">
              {notifications.map((notif) => (
                <div
                  key={notif.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => { open(notif); if (notif.url) setIsOpen(false) }}
                  onKeyDown={(e) => { if (e.key === 'Enter') { open(notif); setIsOpen(false) } }}
                  className={cn(
                    "group/item relative px-4 py-3.5 hover:bg-muted/40 transition-colors cursor-pointer",
                    !notif.readAt && "bg-primary/[0.04]"
                  )}
                >
                  <div className="flex gap-3">
                    <div className="mt-0.5 shrink-0"><NotificationIcon n={notif} /></div>
                    <div className="flex-1 min-w-0 pr-5">
                      <p className={cn(
                        "text-[13px] leading-tight mb-1 text-foreground",
                        notif.readAt ? "font-medium" : "font-semibold"
                      )}>
                        {notif.title}
                      </p>
                      {notif.body && (
                        <p className="text-[11px] text-muted-foreground line-clamp-2 mb-1.5 leading-relaxed whitespace-pre-line">{notif.body}</p>
                      )}
                      <p className="text-[10px] text-muted-foreground/70 font-medium">
                        {formatDistanceToNow(new Date(notif.createdAt), { addSuffix: true })}
                      </p>
                    </div>
                  </div>
                  {!notif.readAt && (
                    <span className="absolute left-1.5 top-[22px] w-1.5 h-1.5 rounded-full bg-primary" />
                  )}
                  <button
                    onClick={(e) => { e.stopPropagation(); clear([notif.id]) }}
                    className="absolute right-2.5 top-2.5 p-1 rounded-full text-muted-foreground/60 hover:text-foreground hover:bg-muted opacity-0 group-hover/item:opacity-100 focus:opacity-100 [@media(hover:none)]:opacity-100 transition-opacity"
                    aria-label="Dismiss"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
              {hasMore && (
                <button
                  onClick={loadMore}
                  className="py-3 text-[11px] font-semibold text-muted-foreground hover:text-primary transition-colors"
                >
                  Load older
                </button>
              )}
            </div>
          )}
        </div>

        {notifications.length > 0 && (
          <div className="p-3 bg-muted/40 text-center border-t border-border/50">
            <button
              onClick={() => clear()}
              className="text-[11px] font-bold text-muted-foreground hover:text-destructive transition-colors"
            >
              Clear all
            </button>
          </div>
        )}
      </PopoverContent>
    </Popover>
  )
}
