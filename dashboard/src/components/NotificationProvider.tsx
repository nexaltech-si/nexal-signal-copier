'use client'

import React, { createContext, useContext, useEffect, useRef, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { toast, Toaster } from 'sonner'

// Notifications are produced by the bot's event pusher (src/services/event_pusher.py):
//  - inbox:   GET/PATCH/DELETE /api/notifications
//  - live:    SSE /api/notifications/stream (Redis pub/sub)
//  - devices: Web Push via public/sw.js, works with the app closed

export interface AppNotification {
  id: string
  createdAt: string
  category: string | null
  type: 'SIGNAL' | 'TRADE' | 'SYSTEM' | 'CONNECTION'
  severity: 'INFO' | 'SUCCESS' | 'WARNING' | 'ERROR'
  title: string
  body: string
  url: string | null
  data?: any
  readAt: string | null
}

// on/off: this device's push subscription. ios-install: iPhone Safari tab -
// push only works once the dashboard is added to the Home Screen.
export type PushStatus = 'loading' | 'unsupported' | 'ios-install' | 'denied' | 'off' | 'on'

interface NotificationContextType {
  notifications: AppNotification[]
  unreadCount: number
  live: boolean
  hasMore: boolean
  loadMore: () => Promise<void>
  markRead: (ids?: string[]) => Promise<void>
  clear: (ids?: string[]) => Promise<void>
  open: (notification: AppNotification) => void
  pushStatus: PushStatus
  pushBusy: boolean
  enablePush: () => Promise<void>
  disablePush: () => Promise<void>
  sendTest: () => Promise<void>
}

const NotificationContext = createContext<NotificationContextType | undefined>(undefined)

const PAGE_SIZE = 50

function urlBase64ToUint8Array(base64String: string) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(base64)
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)))
}

function detectPushSupport(): PushStatus {
  const ua = navigator.userAgent
  const isIOS = /iPad|iPhone|iPod/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
  const standalone = window.matchMedia('(display-mode: standalone)').matches || (navigator as any).standalone === true
  if (isIOS && !standalone) return 'ios-install'
  if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) return 'unsupported'
  if (Notification.permission === 'denied') return 'denied'
  return 'off'
}

export function NotificationProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const [notifications, setNotifications] = useState<AppNotification[]>([])
  const [unreadCount, setUnreadCount] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const [live, setLive] = useState(false)
  const [pushStatus, setPushStatus] = useState<PushStatus>('loading')
  const [pushBusy, setPushBusy] = useState(false)
  const registrationRef = useRef<ServiceWorkerRegistration | null>(null)
  const seenIdsRef = useRef<Set<string>>(new Set())
  const pushStatusRef = useRef<PushStatus>('loading')
  const [toastSettings, setToastSettings] = useState({
    notificationsEnabled: true,
    tradeNotificationsEnabled: true,
    systemNotificationsEnabled: true,
    errorNotificationsEnabled: true,
  })
  const toastSettingsRef = useRef(toastSettings)
  useEffect(() => { toastSettingsRef.current = toastSettings }, [toastSettings])
  useEffect(() => { pushStatusRef.current = pushStatus }, [pushStatus])

  // ── Inbox ────────────────────────────────────────────────────────────────

  const fetchInbox = useCallback(async () => {
    try {
      const response = await fetch(`/api/notifications?limit=${PAGE_SIZE}`, { cache: 'no-store' })
      if (!response.ok) return
      const data: { items: AppNotification[]; unreadCount: number } = await response.json()
      data.items.forEach((n) => seenIdsRef.current.add(n.id))
      setNotifications(data.items)
      setUnreadCount(data.unreadCount)
      setHasMore(data.items.length === PAGE_SIZE)
    } catch {
      // Offline - the live stream / next visibility change will retry
    }
  }, [])

  const loadMore = useCallback(async () => {
    const oldest = notifications[notifications.length - 1]
    if (!oldest) return
    const response = await fetch(`/api/notifications?limit=${PAGE_SIZE}&before=${encodeURIComponent(oldest.createdAt)}`, { cache: 'no-store' })
    if (!response.ok) return
    const data: { items: AppNotification[] } = await response.json()
    data.items.forEach((n) => seenIdsRef.current.add(n.id))
    setNotifications((prev) => [...prev, ...data.items.filter((n) => !prev.some((p) => p.id === n.id))])
    setHasMore(data.items.length === PAGE_SIZE)
  }, [notifications])

  const markRead = useCallback(async (ids?: string[]) => {
    const now = new Date().toISOString()
    setNotifications((prev) => prev.map((n) => (!ids || ids.includes(n.id)) && !n.readAt ? { ...n, readAt: now } : n))
    setUnreadCount((prev) => ids ? Math.max(0, prev - ids.length) : 0)
    try {
      const response = await fetch('/api/notifications', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(ids ? { ids } : {}),
      })
      if (response.ok) setUnreadCount((await response.json()).unreadCount)
    } catch { /* optimistic */ }
  }, [])

  const clear = useCallback(async (ids?: string[]) => {
    setNotifications((prev) => ids ? prev.filter((n) => !ids.includes(n.id)) : [])
    if (!ids) setUnreadCount(0)
    try {
      const response = await fetch('/api/notifications', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(ids ? { ids } : {}),
      })
      if (response.ok) setUnreadCount((await response.json()).unreadCount)
    } catch { /* optimistic */ }
  }, [])

  const open = useCallback((notification: AppNotification) => {
    if (!notification.readAt) markRead([notification.id])
    if (notification.url) router.push(notification.url)
  }, [markRead, router])

  const shouldToast = (n: AppNotification) => {
    const s = toastSettingsRef.current
    if (!s.notificationsEnabled) return false
    if (n.type === 'TRADE' && !s.tradeNotificationsEnabled) return false
    if ((n.type === 'SYSTEM' || n.type === 'CONNECTION') && !s.systemNotificationsEnabled) return false
    if (n.severity === 'ERROR' && !s.errorNotificationsEnabled) return false
    return true
  }

  const receive = useCallback((n: AppNotification) => {
    if (seenIdsRef.current.has(n.id)) return
    seenIdsRef.current.add(n.id)
    setNotifications((prev) => [n, ...prev])
    setUnreadCount((prev) => prev + 1)

    // Subscribed devices already get a system notification from the service worker
    if (pushStatusRef.current === 'on' || !shouldToast(n)) return
    const toastFn = n.severity === 'ERROR' ? toast.error
      : n.severity === 'WARNING' ? toast.warning
      : n.severity === 'SUCCESS' ? toast.success
      : toast.info
    toastFn(n.title, {
      description: n.body,
      duration: 6000,
      action: n.url ? { label: 'View', onClick: () => open(n) } : undefined,
    })
  }, [open])

  const receiveRef = useRef(receive)
  useEffect(() => { receiveRef.current = receive }, [receive])

  // ── Live stream ──────────────────────────────────────────────────────────

  useEffect(() => {
    let source: EventSource | null = null
    let retryTimer: ReturnType<typeof setTimeout> | null = null
    let disposed = false

    const connect = () => {
      if (disposed) return
      source = new EventSource('/api/notifications/stream')
      source.addEventListener('ready', () => {
        setLive(true)
        // Catch anything published while we were disconnected
        fetchInbox()
      })
      source.addEventListener('notification', (e) => {
        try { receiveRef.current(JSON.parse((e as MessageEvent).data)) } catch { /* bad payload */ }
      })
      source.onerror = () => {
        setLive(false)
        // EventSource retries by itself unless the server refused the stream
        if (source?.readyState === EventSource.CLOSED) {
          source.close()
          retryTimer = setTimeout(connect, 10000)
        }
      }
    }

    fetchInbox()
    connect()

    // Mobile browsers freeze background tabs - resync when we come back
    const onVisible = () => { if (document.visibilityState === 'visible') fetchInbox() }
    document.addEventListener('visibilitychange', onVisible)

    return () => {
      disposed = true
      source?.close()
      if (retryTimer) clearTimeout(retryTimer)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [fetchInbox])

  // Toast filters from Settings → Notifications (also applied to push by the bot)
  useEffect(() => {
    fetch('/api/user-settings')
      .then((r) => r.ok ? r.json() : null)
      .then((data) => data && setToastSettings({
        notificationsEnabled: data.notificationsEnabled ?? true,
        tradeNotificationsEnabled: data.tradeNotificationsEnabled ?? true,
        systemNotificationsEnabled: data.systemNotificationsEnabled ?? true,
        errorNotificationsEnabled: data.errorNotificationsEnabled ?? true,
      }))
      .catch(() => {})
  }, [])

  // Home-screen / dock icon badge
  useEffect(() => {
    const nav = navigator as any
    if (!nav.setAppBadge) return
    ;(unreadCount > 0 ? nav.setAppBadge(unreadCount) : nav.clearAppBadge()).catch(() => {})
  }, [unreadCount])

  // ── Service worker & Web Push ────────────────────────────────────────────

  const saveSubscription = async (subscription: PushSubscription) => {
    const response = await fetch('/api/push/subscribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ subscription: subscription.toJSON() }),
    })
    if (!response.ok) throw new Error('Could not register this device')
  }

  useEffect(() => {
    const support = detectPushSupport()
    if (!('serviceWorker' in navigator)) {
      setPushStatus(support)
      return
    }

    const onMessage = (event: MessageEvent) => {
      if (event.data?.type === 'notification-click' && event.data.url) {
        router.push(event.data.url)
        fetchInbox()
      }
    }
    navigator.serviceWorker.addEventListener('message', onMessage)

    navigator.serviceWorker.register('/sw.js', { scope: '/' })
      .then(async (registration) => {
        registrationRef.current = registration
        if (support !== 'off') {
          setPushStatus(support)
          return
        }
        const existing = await registration.pushManager.getSubscription()
        if (existing && Notification.permission === 'granted') {
          // Re-sync in case the server pruned it
          saveSubscription(existing).catch(() => {})
          setPushStatus('on')
        } else {
          setPushStatus('off')
        }
      })
      .catch((error) => {
        console.error('Service worker registration failed:', error)
        setPushStatus('unsupported')
      })

    return () => navigator.serviceWorker.removeEventListener('message', onMessage)
  }, [router, fetchInbox])

  const enablePush = useCallback(async () => {
    setPushBusy(true)
    try {
      const registration = registrationRef.current ?? await navigator.serviceWorker.ready
      // Must run directly from the tap - iOS only prompts inside a user gesture
      const permission = await Notification.requestPermission()
      if (permission !== 'granted') {
        setPushStatus(permission === 'denied' ? 'denied' : 'off')
        return
      }
      const keyResponse = await fetch('/api/push/vapid-key')
      if (!keyResponse.ok) throw new Error('Push service unavailable - is the bot running?')
      const { publicKey } = await keyResponse.json()

      let subscription = await registration.pushManager.getSubscription()
      // A subscription made with an old key must be replaced
      const currentKey = subscription?.options.applicationServerKey
      if (subscription && currentKey) {
        const current = btoa(String.fromCharCode(...new Uint8Array(currentKey)))
          .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
        if (current !== publicKey) {
          await subscription.unsubscribe()
          subscription = null
        }
      }
      subscription ??= await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(publicKey),
      })
      await saveSubscription(subscription)
      setPushStatus('on')
      toast.success('Push notifications enabled on this device')
    } catch (error: any) {
      toast.error('Could not enable push notifications', { description: error?.message })
    } finally {
      setPushBusy(false)
    }
  }, [])

  const disablePush = useCallback(async () => {
    setPushBusy(true)
    try {
      const registration = registrationRef.current ?? await navigator.serviceWorker.ready
      const subscription = await registration.pushManager.getSubscription()
      if (subscription) {
        await fetch('/api/push/subscribe', {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ endpoint: subscription.endpoint }),
        }).catch(() => {})
        await subscription.unsubscribe()
      }
      setPushStatus('off')
    } finally {
      setPushBusy(false)
    }
  }, [])

  const sendTest = useCallback(async () => {
    try {
      const response = await fetch('/api/push/test', { method: 'POST' })
      if (!response.ok) throw new Error('Bot API unreachable')
      const stats = await response.json()
      if (pushStatusRef.current === 'on' && stats.delivered === 0) {
        toast.warning('Test sent, but no device accepted the push', {
          description: 'Try turning push off and on again on this device.',
        })
      }
    } catch (error: any) {
      toast.error('Could not send test notification', { description: error?.message })
    }
  }, [])

  return (
    <NotificationContext.Provider value={{
      notifications, unreadCount, live, hasMore, loadMore, markRead, clear, open,
      pushStatus, pushBusy, enablePush, disablePush, sendTest,
    }}>
      {children}
      <Toaster
        position="top-center"
        expand={true}
        richColors
        closeButton
        theme="light"
        toastOptions={{
          style: {
            borderRadius: '16px',
            border: '1px solid rgba(255,255,255,0.9)',
            backdropFilter: 'blur(14px)',
            background: 'rgba(255,255,255,0.82)',
            boxShadow: '0 12px 28px rgba(24,31,76,0.06)',
            width: 'calc(100vw - 32px)',
            maxWidth: '400px'
          }
        }}
      />
    </NotificationContext.Provider>
  )
}

export const useNotifications = () => {
  const context = useContext(NotificationContext)
  if (!context) throw new Error('useNotifications must be used within NotificationProvider')
  return context
}
