/* Service worker - Web Push delivery and notification taps.
 * Push payloads are sent by src/services/event_pusher.py in the bot. */

self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()))

self.addEventListener('push', (event) => {
  let payload = {}
  try {
    payload = event.data ? event.data.json() : {}
  } catch {
    payload = { title: 'NEXAL', body: event.data ? event.data.text() : '' }
  }

  const title = payload.title || 'NEXAL'
  const options = {
    body: payload.body || '',
    icon: '/icon-192x192.png',
    badge: '/icon-192x192.png',
    tag: payload.tag || payload.id,
    timestamp: payload.timestamp ? Date.parse(payload.timestamp) : Date.now(),
    requireInteraction: !!payload.requireInteraction,
    renotify: !!payload.requireInteraction,
    data: { url: payload.url || '/', id: payload.id },
  }

  const work = [self.registration.showNotification(title, options)]

  // Home-screen icon badge (installed PWA on iOS 16.4+ / Android / desktop)
  if (typeof payload.badge === 'number' && self.navigator.setAppBadge) {
    work.push(
      (payload.badge > 0 ? self.navigator.setAppBadge(payload.badge) : self.navigator.clearAppBadge()).catch(() => {})
    )
  }

  // Let open dashboards know immediately (the SSE stream also delivers it)
  work.push(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) =>
      clients.forEach((c) => c.postMessage({ type: 'push-received', notification: payload }))
    )
  )

  event.waitUntil(Promise.all(work))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const { url = '/', id } = event.notification.data || {}

  event.waitUntil((async () => {
    if (id) {
      fetch('/api/notifications', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: [id] }),
        credentials: 'include',
      }).catch(() => {})
    }

    const target = new URL(url, self.location.origin).href
    const clients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
    for (const client of clients) {
      if (new URL(client.url).origin === self.location.origin && 'focus' in client) {
        await client.focus()
        client.postMessage({ type: 'notification-click', url, id })
        return
      }
    }
    await self.clients.openWindow(target)
  })())
})

// Browser rotated the subscription - re-register it with the server.
self.addEventListener('pushsubscriptionchange', (event) => {
  event.waitUntil((async () => {
    const res = await fetch('/api/push/vapid-key', { credentials: 'include' })
    if (!res.ok) return
    const { publicKey } = await res.json()
    const sub = await self.registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(publicKey),
    })
    await fetch('/api/push/subscribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ subscription: sub.toJSON(), oldEndpoint: event.oldSubscription?.endpoint }),
      credentials: 'include',
    })
  })())
})

function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(base64)
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)))
}
