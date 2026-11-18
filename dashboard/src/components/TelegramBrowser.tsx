'use client'

import React, { useState, useEffect, useCallback, useRef, Fragment } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Dialog as SignalDialog,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import {
  RefreshCw,
  Zap,
  Loader2,
  AlertCircle,
  Search,
  FileVideo,
  FileText,
  X,
  Eye,
  EyeOff,
  ChevronLeft,
  ChevronDown,
  Send,
  Palette,
  Check,
} from 'lucide-react'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { cn } from '@/lib/utils'
import { toast } from 'sonner'
import TgWallpaper, {
  WALLPAPER_PRESETS,
  DEFAULT_PRESET_ID,
  WALLPAPER_STORAGE_KEY,
  type WallpaperPreset,
} from '@/components/TgWallpaper'
import TelegramText from '@/components/TelegramText'
import { telegramPlainText } from '@/lib/telegramMarkdown'

// ─── Types ────────────────────────────────────────────────────────────────────

interface TgChannel {
  id: string
  title: string
  username: string | null
  type: 'channel' | 'supergroup' | 'group'
  unread_count: number
  last_message_date: string | null
  last_preview: string | null
  has_photo?: boolean
}

interface TgReplyTo {
  id: number
  text: string | null
  sender_name: string | null
  has_media: boolean
  media_type: 'photo' | 'photo_group' | 'image' | 'video' | 'document' | 'other' | null
}

interface TgMessage {
  id: number
  text: string
  clean_text: string
  html_text: string | null
  date: string | null
  sender_id: string | null
  sender_name: string | null
  has_media: boolean
  media_type: 'photo' | 'photo_group' | 'image' | 'video' | 'document' | 'other' | null
  media_ids: number[]  // one entry per image; albums have multiple
  reply_to: TgReplyTo | null
}

// Editable core trade fields. String-backed so inputs can hold partial/empty
// values; converted to numbers/enums only when confirming.
type EntryMode = 'single' | 'range' | 'legs'

interface SignalEditForm {
  action: string               // OPEN, or the trade-management command read from the text
  symbol: string
  order_type: string           // BUY | SELL
  entryMode: EntryMode         // single price · range zone · discrete scale-in legs
  entry_price: string
  entry_range_min: string
  entry_range_max: string
  legs: string                 // comma-separated scale-in prices (>=2)
  stop_loss: string
  take_profit: string          // comma-separated
}

interface SignalResult {
  extracted: boolean
  placed?: boolean
  signal: {
    symbol: string | null
    action: string | null
    order_type: string | null
    entry_price: number | null
    entry_range_min: number | null
    entry_range_max: number | null
    entries: number[] | null
    stop_loss: number | null
    take_profit: number[]
    confidence: number
    signal_id: string | null
    is_plan: boolean
  } | null
  error: string | null
  rejection_reason: string | null
  source?: 'text' | 'image' | 'text+image'
  notes?: string[]               // fields to fill in or double-check before placing
  has_image?: boolean
  clarification?: {
    id: string
    field: string
    order_type: string | null
    entry: number | null
    take_profit: number[]
    is_plan: boolean
  } | null
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

// Seed the editable form from a parsed signal. Entry mode is inferred: legs win
// (>=2 discrete prices), then a range, else a single price.
function signalToForm(sig: NonNullable<SignalResult['signal']>): SignalEditForm {
  const numStr = (n: number | null | undefined) => (n == null ? '' : String(n))
  const hasLegs = (sig.entries?.length ?? 0) >= 2
  const hasRange = sig.entry_range_min != null && sig.entry_range_max != null
  const entryMode: EntryMode = hasLegs ? 'legs' : hasRange ? 'range' : 'single'
  return {
    action: sig.action ?? 'OPEN',
    symbol: sig.symbol ?? '',
    order_type: sig.order_type ?? '',
    entryMode,
    entry_price: numStr(sig.entry_price),
    entry_range_min: numStr(sig.entry_range_min),
    entry_range_max: numStr(sig.entry_range_max),
    legs: (sig.entries ?? []).join(', '),
    stop_loss: numStr(sig.stop_loss),
    take_profit: (sig.take_profit ?? []).join(', '),
  }
}

const SOURCE_LABEL: Record<string, string> = {
  text: 'message text',
  image: 'chart image',
  'text+image': 'message text and chart image',
}

// Blank form for a trade typed in by hand when nothing could be read.
const EMPTY_FORM: SignalEditForm = {
  action: 'OPEN', symbol: '', order_type: '', entryMode: 'single',
  entry_price: '', entry_range_min: '', entry_range_max: '', legs: '', stop_loss: '', take_profit: '',
}

// Convert the form back into the edits payload the backend applies. Empty
// strings become null (keep parsed value); the entry mode picks which of
// single / range / legs is sent (the others are nulled). The backend re-checks
// the legs>=2 and entry_price==entries[0] invariants defensively.
function formToEdits(form: SignalEditForm) {
  const num = (s: string): number | null => {
    const t = s.trim()
    if (!t) return null
    const n = Number(t)
    return Number.isFinite(n) ? n : null
  }
  const nums = (s: string): number[] =>
    s.split(',').map(x => Number(x.trim())).filter(n => Number.isFinite(n))

  const isRange = form.entryMode === 'range'
  const isLegs = form.entryMode === 'legs'
  const legs = isLegs ? nums(form.legs) : []
  return {
    action: form.action || 'OPEN',
    symbol: form.symbol.trim() || null,
    order_type: form.order_type.trim() || null,
    // Single price only when not a range/legs entry.
    entry_price: isRange || isLegs ? (isLegs ? legs[0] ?? null : null) : num(form.entry_price),
    entry_range_min: isRange ? num(form.entry_range_min) : null,
    entry_range_max: isRange ? num(form.entry_range_max) : null,
    // >=2 legs sends the scale-in; fewer collapses to single (backend drops it).
    entries: isLegs ? legs : null,
    stop_loss: num(form.stop_loss),
    take_profit: nums(form.take_profit),
  }
}

const AVATAR_PALETTE = [
  '#E53935', '#D81B60', '#8E24AA', '#5E35B1',
  '#3949AB', '#1E88E5', '#00ACC1', '#00897B',
  '#43A047', '#FB8C00', '#F4511E', '#6D4C41',
]

function avatarColor(name: string): string {
  let h = 0
  for (let i = 0; i < name.length; i++) h = name.charCodeAt(i) + ((h << 5) - h)
  return AVATAR_PALETTE[Math.abs(h) % AVATAR_PALETTE.length]
}

export function timeStr(iso: string | null): string {
  if (!iso) return ''
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function listDateStr(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  const diff = Math.floor((Date.now() - d.getTime()) / 86400000)
  if (diff === 0) return timeStr(iso)
  if (diff === 1) return 'Yesterday'
  if (diff < 7) return d.toLocaleDateString([], { weekday: 'short' })
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

function dateSeparatorStr(iso: string): string {
  const d = new Date(iso)
  const today = new Date(); today.setHours(0,0,0,0)
  const msgDay = new Date(d); msgDay.setHours(0,0,0,0)
  const diff = Math.round((today.getTime() - msgDay.getTime()) / 86400000)
  if (diff === 0) return 'Today'
  if (diff === 1) return 'Yesterday'
  if (diff < 7) return d.toLocaleDateString('en', { weekday: 'long' })
  const diffYears = today.getFullYear() - d.getFullYear()
  return d.toLocaleDateString('en', { month: 'long', day: 'numeric', ...(diffYears > 0 && { year: 'numeric' }) })
}

function mediaUrl(channelId: string, messageId: number): string {
  return `/api/telegram-browser/media?channel_id=${channelId}&message_id=${messageId}`
}

// ─── Avatar ───────────────────────────────────────────────────────────────────

export function TgAvatar({ name, size = 40 }: { name: string; size?: number }) {
  const color = avatarColor(name)
  return (
    <div
      className="rounded-full flex items-center justify-center font-semibold text-white shrink-0 select-none"
      style={{ width: size, height: size, backgroundColor: color, fontSize: size * 0.42 }}
    >
      {name.charAt(0).toUpperCase()}
    </div>
  )
}

// Tries the real Telegram profile photo, falls back to colored letter avatar
function TgChannelAvatar({ channel, size = 46 }: { channel: TgChannel; size?: number }) {
  const [errored, setErrored] = useState(false)
  const photoUrl = `/api/telegram-browser/channel-photo/${channel.id}`

  if (!errored) {
    return (
      <div
        className="rounded-full overflow-hidden shrink-0 select-none bg-muted"
        style={{ width: size, height: size }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={photoUrl}
          alt={channel.title}
          width={size}
          height={size}
          className="w-full h-full object-cover"
          onError={() => setErrored(true)}
        />
      </div>
    )
  }
  return <TgAvatar name={channel.title} size={size} />
}

// ─── Inline Image ─────────────────────────────────────────────────────────────

function TgImage({
  src,
  onExpand,
  cover = false,
}: {
  src: string
  onExpand: (src: string) => void
  cover?: boolean   // true = square crop for album grid; false = natural height for single
}) {
  const [loaded, setLoaded] = useState(false)
  const [errored, setErrored] = useState(false)

  if (errored) return null

  return (
    <div
      className={cn(
        'relative cursor-pointer overflow-hidden bg-muted/30 group/img',
        cover ? 'aspect-square' : 'flex',
      )}
      onClick={() => onExpand(src)}
      role="button"
      tabIndex={0}
      aria-label="Open image"
      onKeyDown={e => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onExpand(src)
        }
      }}
    >
      {!loaded && (
        <Skeleton className={cn('w-full rounded-none', cover ? 'absolute inset-0 h-full' : 'h-48')} />
      )}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={src}
        alt="media"
        loading="lazy"
        onLoad={() => setLoaded(true)}
        onError={() => setErrored(true)}
        className={cn(
          'transition-[opacity,filter] duration-200',
          // Album tiles fill their square grid cell. A lone image is a *preview*
          // bounded by TG Web K's media box (420x400 desktop / 340x340 handheld,
          // src/helpers/mediaSizes.ts) — it keeps its aspect ratio and is never
          // upscaled past its natural size. Click opens the full-size lightbox.
          cover
            ? 'w-full h-full object-cover'
            : 'max-w-full max-h-[340px] sm:max-h-[400px] w-auto h-auto object-contain',
          loaded ? 'opacity-100' : 'opacity-0 absolute inset-0',
          'group-hover/img:brightness-[0.93]'
        )}
      />
    </div>
  )
}

// ─── Reply Preview ────────────────────────────────────────────────────────────
// Exported: the Flow Replay page draws its chat with the same pieces.

export function ReplyPreview({ reply, onJump }: { reply: TgReplyTo; onJump: (id: number) => void }) {
  const color = reply.sender_name ? avatarColor(reply.sender_name) : '#5E35B1'
  const mediaLabel =
    reply.media_type === 'video' ? '🎥 Video' :
    reply.media_type === 'document' ? '📄 Document' :
    (reply.media_type === 'photo' || reply.media_type === 'image' || reply.media_type === 'photo_group') ? '📷 Photo' :
    '📎 Media'
  const preview = reply.text || (reply.has_media ? mediaLabel : 'Message')

  return (
    <div
      role="button"
      tabIndex={0}
      className="flex mb-2 rounded-md overflow-hidden cursor-pointer transition-colors"
      style={{ borderLeft: `3px solid ${color}`, backgroundColor: `${color}14` }}
      onClick={() => onJump(reply.id)}
      onKeyDown={e => e.key === 'Enter' && onJump(reply.id)}
    >
      <div className="flex-1 min-w-0 px-2.5 py-1.5">
        <p className="text-[11px] font-semibold leading-none mb-0.5 truncate" style={{ color }}>
          {reply.sender_name ?? 'Unknown'}
        </p>
        <p className="text-[11px] text-muted-foreground leading-snug line-clamp-1">
          {preview}
        </p>
      </div>
    </div>
  )
}

// ─── Message Bubble ───────────────────────────────────────────────────────────

function MessageBubble({
  msg,
  channelId,
  channelType,
  onExecute,
  executing,
  onExpand,
  onScrollToMsg,
}: {
  msg: TgMessage
  channelId: string
  channelType: string
  onExecute: (msg: TgMessage) => void
  executing: boolean
  onExpand: (src: string) => void
  onScrollToMsg: (id: number) => void
}) {
  const [showRaw, setShowRaw] = useState(false)
  const isGroupChat = channelType === 'group' || channelType === 'supergroup'
  const displayText = showRaw ? msg.text : (msg.clean_text || msg.text)
  // The formatted view parses Telegram markdown; offer the raw toggle whenever
  // that would actually look different — i.e. the text carries markdown markers or
  // zero-width chars were stripped from clean_text.
  const hasMarkdown = /[*_~`]|\[.+?\]\(.+?\)/.test(displayText || '')
  const hasDiff = hasMarkdown || (msg.text !== msg.clean_text && !!msg.clean_text)
  const isImage = msg.media_type === 'photo' || msg.media_type === 'image' || msg.media_type === 'photo_group'
  const isVideo = msg.media_type === 'video'
  const isDoc = msg.media_type === 'document'
  const imageIds = msg.media_ids ?? []
  const multiImage = imageIds.length > 1
  const hasMediaAbove = isImage && imageIds.length > 0

  return (
    <div className="flex gap-2 group" data-msg-id={msg.id}>
      {/* Group avatar — left aligned */}
      {isGroupChat && msg.sender_name && (
        <TgAvatar name={msg.sender_name} size={34} />
      )}
      {isGroupChat && !msg.sender_name && <div style={{ width: 34 }} />}

      {/* Bubble */}
      <div className="flex-1 min-w-0">
        {/* Sender name for group chats */}
        {isGroupChat && msg.sender_name && (
          <p
            className="text-xs font-semibold mb-1 ml-1"
            style={{ color: avatarColor(msg.sender_name) }}
          >
            {msg.sender_name}
          </p>
        )}

        <div className={cn(
          'tg-bubble tg-bubble-accent relative rounded-2xl rounded-tl-md overflow-hidden',
          'w-fit',
          hasMediaAbove
            // Media bubbles are capped to TG's preview box (420px desktop /
            // 340px handheld). w-fit shrink-wraps, so a portrait preview gets a
            // narrow bubble instead of a letterbox. min-w keeps a small image
            // reading as a bubble (tdesktop historyPhotoBubbleMinWidth = 200px).
            ? 'max-w-full sm:max-w-[340px] md:max-w-[420px] min-w-[200px]'
            // Text-only bubbles get a wider allowance — signal posts are long and
            // 420px would wrap them awkwardly.
            : 'max-w-full sm:max-w-[82%] lg:max-w-[65%]',
        )}
        >
          {/* Reply/forward header — sits above the media, as in the TG client */}
          {msg.reply_to && (
            <div className="pl-3.5 pr-3 pt-2.5">
              <ReplyPreview reply={msg.reply_to} onJump={onScrollToMsg} />
            </div>
          )}

          {/* ── Photo / album grid ── */}
          {isImage && imageIds.length > 0 && (
            <div className={cn(
              multiImage && 'grid gap-0.5',
              imageIds.length === 2 && 'grid-cols-2',
              imageIds.length === 3 && 'grid-cols-2',
              imageIds.length >= 4 && 'grid-cols-2',
            )}>
              {imageIds.map((mid, idx) => (
                <div
                  key={mid}
                  className={cn(
                    imageIds.length === 3 && idx === 2 && 'col-span-2'
                  )}
                >
                  <TgImage
                    src={mediaUrl(channelId, mid)}
                    onExpand={onExpand}
                    cover={multiImage}
                  />
                </div>
              ))}
            </div>
          )}

          {/* Padding wrapper for text/footer — separated from the flush image grid.
              Tightens the top gap when a caption follows an image, like the TG client. */}
          <div className={cn('pl-3.5 pr-3 pb-1.5', hasMediaAbove ? 'pt-1.5' : 'pt-2.5')}>
            {/* Video placeholder */}
            {isVideo && (
              <div className="flex items-center gap-2 mb-2 rounded-lg bg-muted p-3">
                <FileVideo className="h-5 w-5 text-muted-foreground" />
                <span className="text-xs text-muted-foreground">Video attachment</span>
              </div>
            )}

            {/* Document placeholder */}
            {isDoc && (
              <div className="flex items-center gap-2 mb-2 rounded-lg bg-muted p-3">
                <FileText className="h-5 w-5 text-muted-foreground" />
                <span className="text-xs text-muted-foreground">Document attachment</span>
              </div>
            )}

            {/* Text / caption.
                - Raw view: verbatim source, monospace-ish, no parsing.
                - Formatted view: Telegram's own markdown rules (TelegramText), so
                  "**GOLD SELL **" and bold across blank lines render as in Telegram. */}
            {showRaw ? (
              <pre className="text-sm whitespace-pre-wrap font-sans leading-relaxed break-words">
                {displayText}
              </pre>
            ) : displayText ? (
              <TelegramText text={displayText} className="tg-message text-sm leading-relaxed" />
            ) : (
              !msg.has_media && (
                <p className="text-xs text-muted-foreground italic">Empty message</p>
              )
            )}

            {/* Footer row: raw toggle · time · execute */}
            <div className="flex items-center justify-end gap-2 mt-1 flex-wrap">
              {hasDiff && (
                <button
                  onClick={() => setShowRaw(v => !v)}
                  className="flex items-center gap-1 text-[10px] text-muted-foreground/70 hover:text-foreground opacity-100 md:opacity-0 md:group-hover:opacity-100 focus-visible:opacity-100 transition-opacity"
                >
                  {showRaw ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
                  {showRaw ? 'formatted' : 'raw'}
                </button>
              )}
              <span className="text-[11px] text-muted-foreground/70 leading-none tabular-nums">{timeStr(msg.date)}</span>
              <Button
                size="sm"
                variant="ghost"
                className="h-6 px-2 text-[11px] gap-1 text-muted-foreground/70 hover:text-primary hover:bg-primary/10 opacity-100 md:opacity-0 md:group-hover:opacity-100 focus-visible:opacity-100 transition-opacity"
                onClick={() => onExecute(msg)}
                disabled={executing}
                title="Parse this message and review before placing a trade"
              >
                {executing
                  ? <Loader2 className="h-3 w-3 animate-spin" />
                  : <Zap className="h-3 w-3" />
                }
                <span className="hidden sm:inline">{executing ? 'Parsing…' : 'Execute'}</span>
              </Button>
            </div>
          </div>{/* end padding wrapper */}
        </div>{/* end bubble */}
      </div>
    </div>
  )
}

// ─── Date Separator ───────────────────────────────────────────────────────────

export function DateSeparator({ iso }: { iso: string }) {
  return (
    <div className="sticky top-1 z-10 flex items-center justify-center my-4">
      <span className="bg-background/70 backdrop-blur-md border border-border/40 text-muted-foreground text-[11px] font-medium px-3 py-1 rounded-full select-none shadow-sm">
        {dateSeparatorStr(iso)}
      </span>
    </div>
  )
}

// ─── Main Component ───────────────────────────────────────────────────────────

export default function TelegramBrowser() {
  const [channels, setChannels] = useState<TgChannel[]>([])
  const [loadingChannels, setLoadingChannels] = useState(false)
  const [filter, setFilter] = useState('')

  const [selected, setSelected] = useState<TgChannel | null>(null)
  const [messages, setMessages] = useState<TgMessage[]>([])
  const [loadingMessages, setLoadingMessages] = useState(false)

  const [executing, setExecuting] = useState<number | null>(null)
  const [signalResult, setSignalResult] = useState<{ msgId: number; result: SignalResult } | null>(null)
  // The message being previewed, kept so Confirm can re-POST it with dry_run=false.
  const [previewMsg, setPreviewMsg] = useState<TgMessage | null>(null)
  // Editable copy of the parsed core trade fields (string-backed for the inputs).
  const [edits, setEdits] = useState<SignalEditForm | null>(null)
  const [placing, setPlacing] = useState(false)
  const [symbolInput, setSymbolInput] = useState('')
  const [resolvingSymbol, setResolvingSymbol] = useState(false)
  const [lightboxSrc, setLightboxSrc] = useState<string | null>(null)
  // Chat wallpaper preset (persisted). Hydrated from localStorage after mount to
  // avoid an SSR mismatch — starts on the default, then adopts the saved choice.
  const [wallpaperId, setWallpaperId] = useState<string>(DEFAULT_PRESET_ID)
  const wallpaper: WallpaperPreset =
    WALLPAPER_PRESETS.find(p => p.id === wallpaperId) ?? WALLPAPER_PRESETS[0]
  // Mobile: show either the channel list or the message view, never both
  const [mobileView, setMobileView] = useState<'list' | 'messages'>('list')
  // New message notification badge count
  const [newMsgCount, setNewMsgCount] = useState(0)

  const msgEndRef = useRef<HTMLDivElement>(null)
  const msgAreaRef = useRef<HTMLDivElement>(null)
  const latestMsgIdRef = useRef<number>(0)
  const isAtBottomRef = useRef<boolean>(true)

  // Lock main's scroll while mounted so the sidebar never enters its "isScrolled"
  // compact state (which shifts the mobile top bar and would overlap our content).
  // Also reset scrollTop so any scroll carried from a previous page is cleared.
  useEffect(() => {
    const main = document.querySelector('main')
    if (!main) return
    main.scrollTop = 0
    const prev = main.style.overflowY
    main.style.overflowY = 'hidden'
    return () => { main.style.overflowY = prev }
  }, [])

  const fetchChannels = useCallback(async () => {
    setLoadingChannels(true)
    try {
      const res = await fetch('/api/telegram-browser/dialogs')
      const data = await res.json()
      setChannels(data.dialogs ?? [])
    } catch {
      setChannels([])
    } finally {
      setLoadingChannels(false)
    }
  }, [])

  const fetchMessages = useCallback(async (channel: TgChannel) => {
    setLoadingMessages(true)
    setMessages([])
    try {
      const res = await fetch(`/api/telegram-browser/messages?channel_id=${channel.id}&limit=50`)
      const data = await res.json()
      // API returns newest-first; reverse to display oldest-first (Telegram style)
      setMessages((data.messages ?? []).slice().reverse())
    } catch {
      setMessages([])
    } finally {
      setLoadingMessages(false)
    }
  }, [])

  useEffect(() => { fetchChannels() }, [fetchChannels])

  // Hydrate the saved wallpaper choice once, after mount (client only).
  useEffect(() => {
    try {
      const saved = localStorage.getItem(WALLPAPER_STORAGE_KEY)
      if (saved && WALLPAPER_PRESETS.some(p => p.id === saved)) setWallpaperId(saved)
    } catch {}
  }, [])

  function chooseWallpaper(id: string) {
    setWallpaperId(id)
    try { localStorage.setItem(WALLPAPER_STORAGE_KEY, id) } catch {}
  }

  // Scroll to bottom immediately when messages finish loading for a channel
  useEffect(() => {
    if (loadingMessages || messages.length === 0) return
    // Use instant scroll on the viewport element for reliable positioning
    const viewport = msgAreaRef.current?.querySelector('[data-radix-scroll-area-viewport]') as HTMLElement | null
    if (viewport) {
      viewport.scrollTop = viewport.scrollHeight
    } else {
      setTimeout(() => {
        const vp = msgAreaRef.current?.querySelector('[data-radix-scroll-area-viewport]') as HTMLElement | null
        if (vp) vp.scrollTop = vp.scrollHeight
      }, 80)
    }
  }, [loadingMessages]) // eslint-disable-line react-hooks/exhaustive-deps

  // Track the highest message ID so polling can detect new ones
  useEffect(() => {
    if (messages.length > 0) {
      latestMsgIdRef.current = Math.max(...messages.map(m => m.id))
    }
  }, [messages])

  // Detect whether the user has scrolled away from the bottom
  useEffect(() => {
    if (!selected) return
    isAtBottomRef.current = true

    let viewport: HTMLElement | null = null

    const handleScroll = () => {
      if (!viewport) return
      const { scrollTop, scrollHeight, clientHeight } = viewport
      isAtBottomRef.current = scrollHeight - scrollTop - clientHeight < 120
    }

    const attach = () => {
      viewport = msgAreaRef.current?.querySelector('[data-radix-scroll-area-viewport]') as HTMLElement | null
      if (viewport) {
        viewport.addEventListener('scroll', handleScroll, { passive: true })
        return true
      }
      return false
    }

    let timer: ReturnType<typeof setTimeout>
    if (!attach()) timer = setTimeout(attach, 300)

    return () => {
      clearTimeout(timer)
      viewport?.removeEventListener('scroll', handleScroll)
    }
  }, [selected?.id])

  // Poll for new messages every 30 s while a channel is open
  useEffect(() => {
    if (!selected) return
    setNewMsgCount(0)
    latestMsgIdRef.current = 0

    // Request browser notification permission once
    if (typeof Notification !== 'undefined' && Notification.permission === 'default') {
      Notification.requestPermission()
    }

    const poll = async () => {
      const prevMax = latestMsgIdRef.current
      if (prevMax === 0) return // initial load not yet complete
      try {
        const res = await fetch(`/api/telegram-browser/messages?channel_id=${selected.id}&limit=50`)
        if (!res.ok) return
        const data = await res.json()
        const fetched: TgMessage[] = (data.messages ?? []).slice().reverse()
        const incoming = fetched.filter(m => m.id > prevMax)
        if (incoming.length === 0) return

        setMessages(prev => {
          const existing = new Set(prev.map(m => m.id))
          const toAdd = incoming.filter(m => !existing.has(m.id))
          return toAdd.length > 0 ? [...prev, ...toAdd] : prev
        })

        if (isAtBottomRef.current) {
          setTimeout(() => msgEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 50)
        } else {
          setNewMsgCount(c => c + incoming.length)
          const last = incoming[incoming.length - 1]
          const preview = last.sender_name
            ? `${last.sender_name}: ${telegramPlainText(last.clean_text || last.text).slice(0, 80)}`
            : telegramPlainText(last.clean_text || last.text).slice(0, 100)
          toast(selected.title, { description: preview || '(media)' })
          if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
            try { new Notification(selected.title, { body: preview || '(media)', icon: `/api/telegram-browser/channel-photo/${selected.id}` }) } catch {}
          }
        }
      } catch {}
    }

    const interval = setInterval(poll, 30_000)
    return () => clearInterval(interval)
  }, [selected?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  function selectChannel(ch: TgChannel) {
    setSelected(ch)
    fetchMessages(ch)
    setMobileView('messages')
  }

  // Phase 1 — parse only (dry_run). Opens the review dialog; nothing is placed.
  async function executeSignal(msg: TgMessage) {
    if (!selected) return
    setExecuting(msg.id)
    setSymbolInput('')
    try {
      const res = await fetch('/api/telegram-browser/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          channel_id: selected.id,
          message_id: msg.id,
          text: msg.clean_text || msg.text,
          dry_run: true,
        }),
      })
      const result: SignalResult = await res.json()
      setSignalResult({ msgId: msg.id, result })
      // Seed the edit form from the reading so the user can correct it. With no
      // reading the message stays selected so the trade can be typed in by hand.
      setPreviewMsg(msg)
      setEdits(result.signal ? signalToForm(result.signal) : null)
    } catch (e) {
      setSignalResult({ msgId: msg.id, result: { extracted: false, signal: null, error: String(e), rejection_reason: null } })
      setPreviewMsg(msg)
      setEdits(null)
    } finally {
      setExecuting(null)
    }
  }

  // Phase 2 — place the (possibly edited) trade.
  async function placeSignal() {
    if (!selected || !previewMsg || !edits) return
    setPlacing(true)
    try {
      const res = await fetch('/api/telegram-browser/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          channel_id: selected.id,
          message_id: previewMsg.id,
          text: previewMsg.clean_text || previewMsg.text,
          dry_run: false,
          edits: formToEdits(edits),
        }),
      })
      const result: SignalResult = await res.json()
      if (result.placed) {
        toast.success(`Trade placed — ${edits.symbol || result.signal?.symbol} ${edits.order_type}`)
        closePreview()
      } else {
        // Keep the dialog open so the user can adjust and retry.
        setSignalResult({ msgId: previewMsg.id, result })
        toast.error(result.error || 'Trade was not placed')
      }
    } catch (e) {
      toast.error(String(e))
    } finally {
      setPlacing(false)
    }
  }

  function closePreview() {
    setSignalResult(null)
    setPreviewMsg(null)
    setEdits(null)
  }

  async function resolveSymbol(clarificationId: string) {
    if (!symbolInput.trim()) return
    setResolvingSymbol(true)
    try {
      const res = await fetch('/api/telegram-browser/resolve-symbol', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ clarification_id: clarificationId, symbol: symbolInput.trim() }),
      })
      const data = await res.json()
      if (data.ok) {
        toast.success(data.message || 'Symbol saved')
        setSignalResult(null)
        setSymbolInput('')
      } else {
        toast.error(data.message || 'Could not save that symbol')
      }
    } catch (e) {
      toast.error(String(e))
    } finally {
      setResolvingSymbol(false)
    }
  }

  const filtered = filter
    ? channels.filter(c => c.title.toLowerCase().includes(filter.toLowerCase()))
    : channels

  function scrollToMsg(id: number) {
    const el = msgAreaRef.current?.querySelector(`[data-msg-id="${id}"]`) as HTMLElement | null
    if (!el) return
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    // Flash highlight
    el.style.transition = 'background 0.15s'
    el.style.background = 'hsl(var(--primary)/0.15)'
    setTimeout(() => { el.style.background = '' }, 900)
  }

  // Render messages with date separators
  let lastDateKey = ''
  const renderedMessages = messages.map(msg => {
    const dateKey = msg.date ? new Date(msg.date).toDateString() : ''
    const showSep = !!dateKey && dateKey !== lastDateKey
    lastDateKey = dateKey
    return (
      <Fragment key={msg.id}>
        {showSep && <DateSeparator iso={msg.date!} />}
        <MessageBubble
          msg={msg}
          channelId={selected!.id}
          channelType={selected!.type}
          onExecute={executeSignal}
          executing={executing === msg.id}
          onExpand={setLightboxSrc}
          onScrollToMsg={scrollToMsg}
        />
      </Fragment>
    )
  })

  return (
    <div className="flex h-full overflow-hidden rounded-none md:rounded-xl border-y md:border border-border/40 bg-card/60 backdrop-blur-sm shadow-sm">
      {/* ── Left: Channel list ─────────────────────────────────────────────── */}
      <div className={cn(
        'flex flex-col border-r',
        'md:w-72 md:shrink-0',
        // Mobile: full-width list view; hidden when message view is active
        mobileView === 'list' ? 'flex w-full' : 'hidden md:flex',
      )}>
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-border/30 bg-card/80 backdrop-blur-sm">
          <span className="font-semibold text-sm tracking-tight">Chats</span>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 rounded-lg"
            onClick={fetchChannels}
            disabled={loadingChannels}
          >
            <RefreshCw className={cn('h-3.5 w-3.5', loadingChannels && 'animate-spin')} />
          </Button>
        </div>

        {/* Search */}
        <div className="px-3 py-2 border-b border-border/20 bg-card/40">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground/40 pointer-events-none" />
            <Input
              placeholder="Search..."
              value={filter}
              onChange={e => setFilter(e.target.value)}
              className="pl-8 h-8 text-sm bg-muted/40 border-0 rounded-lg focus-visible:ring-1 focus-visible:ring-primary/20"
            />
          </div>
        </div>

        {/* List */}
        <div className="slim-scrollbar flex-1 min-h-0 overflow-y-auto overflow-x-hidden py-1">
          {loadingChannels ? (
            <div className="p-3 space-y-1">
              {Array.from({ length: 7 }).map((_, i) => (
                <div key={i} className="flex gap-3 p-2">
                  <Skeleton className="h-11 w-11 rounded-full shrink-0" />
                  <div className="flex-1 space-y-1.5 pt-1">
                    <Skeleton className="h-3 w-3/4" />
                    <Skeleton className="h-3 w-1/2" />
                  </div>
                </div>
              ))}
            </div>
          ) : filtered.length === 0 ? (
            <p className="text-xs text-muted-foreground text-center py-8">
              {filter ? 'No matches' : 'No channels'}
            </p>
          ) : (
            filtered.map(ch => (
              <button
                key={ch.id}
                onClick={() => selectChannel(ch)}
                className={cn(
                  'w-full flex items-center gap-3 px-2.5 py-2 transition-colors text-left rounded-xl mx-1.5 my-px',
                  selected?.id === ch.id
                    ? 'bg-primary text-primary-foreground'
                    : 'hover:bg-muted/60'
                )}
              >
                <TgChannelAvatar channel={ch} size={48} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="min-w-0 text-[13px] font-semibold truncate">
                      {ch.title}
                    </span>
                    <span className={cn(
                      'text-[11px] shrink-0 tabular-nums',
                      selected?.id === ch.id ? 'text-primary-foreground/70' : 'text-muted-foreground'
                    )}>
                      {listDateStr(ch.last_message_date)}
                    </span>
                  </div>
                  <div className="flex items-center justify-between gap-2 mt-1">
                    <span className={cn(
                      'min-w-0 text-xs truncate leading-tight',
                      selected?.id === ch.id ? 'text-primary-foreground/75' : 'text-muted-foreground'
                    )}>
                      {ch.last_preview ?? ch.type}
                    </span>
                    {ch.unread_count > 0 && (
                      <span className={cn(
                        'text-[10px] rounded-full px-1.5 min-w-[18px] h-[18px] flex items-center justify-center font-semibold shrink-0 tabular-nums',
                        selected?.id === ch.id
                          ? 'bg-primary-foreground text-primary'
                          : 'bg-primary text-primary-foreground'
                      )}>
                        {ch.unread_count > 99 ? '99+' : ch.unread_count}
                      </span>
                    )}
                  </div>
                </div>
              </button>
            ))
          )}
        </div>
      </div>

      {/* ── Right: Message feed ────────────────────────────────────────────── */}
      <div className={cn(
        'flex-1 flex-col min-w-0 min-h-0',
        // Mobile: full-width message view; hidden when list view is active
        mobileView === 'messages' ? 'flex' : 'hidden md:flex',
      )}>
        {!selected ? (
          <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground gap-3">
            <div className="w-16 h-16 rounded-2xl bg-muted/50 flex items-center justify-center">
              <Search className="h-7 w-7 text-muted-foreground/30" />
            </div>
            <p className="text-sm font-medium text-muted-foreground/60">Select a chat</p>
            <p className="text-xs text-muted-foreground/40">Choose a channel or group from the left</p>
          </div>
        ) : (
          <>
            {/* Channel header */}
            <div className="flex items-center gap-2 px-3 md:px-4 py-3 border-b border-border/30 bg-card/70 backdrop-blur-sm shrink-0">
              {/* Back to list — mobile only */}
              <Button
                variant="ghost"
                size="icon"
                className="md:hidden h-8 w-8 shrink-0 -ml-1"
                onClick={() => setMobileView('list')}
              >
                <ChevronLeft className="h-5 w-5" />
              </Button>
              <TgChannelAvatar channel={selected} size={36} />
              <div className="flex-1 min-w-0">
                <p className="font-semibold text-sm leading-tight truncate">{selected.title}</p>
                <p className="text-xs text-muted-foreground leading-tight">
                  {selected.username ? `@${selected.username}` : selected.type}
                </p>
              </div>
              {/* Wallpaper picker */}
              <Popover>
                <PopoverTrigger asChild>
                  <Button variant="ghost" size="icon" className="h-8 w-8" title="Change chat background">
                    <Palette className="h-4 w-4" />
                  </Button>
                </PopoverTrigger>
                <PopoverContent align="end" className="w-64 p-3">
                  <p className="text-xs font-medium mb-2">Chat background</p>
                  <div className="grid grid-cols-3 gap-2">
                    {WALLPAPER_PRESETS.map(p => (
                      <button
                        key={p.id}
                        onClick={() => chooseWallpaper(p.id)}
                        className={cn(
                          'relative h-16 rounded-lg overflow-hidden border transition-all',
                          wallpaperId === p.id
                            ? 'border-primary ring-2 ring-primary/30'
                            : 'border-border hover:border-primary/50'
                        )}
                        title={p.name}
                      >
                        {/* Swatch: a simple 2×2 of the preset colours */}
                        <div className="absolute inset-0 grid grid-cols-2 grid-rows-2">
                          {p.colors.slice(0, 4).map((c, i) => (
                            <div key={i} style={{ backgroundColor: c }} />
                          ))}
                        </div>
                        {wallpaperId === p.id && (
                          <span className="absolute inset-0 flex items-center justify-center">
                            <span className="bg-background/80 rounded-full p-0.5">
                              <Check className="h-3.5 w-3.5 text-primary" />
                            </span>
                          </span>
                        )}
                        <span className="absolute bottom-0 inset-x-0 bg-black/40 text-white text-[9px] py-0.5 text-center">
                          {p.name}
                        </span>
                      </button>
                    ))}
                  </div>
                </PopoverContent>
              </Popover>

              <Button
                variant="ghost"
                size="sm"
                className="h-8 gap-1.5 text-xs"
                onClick={() => fetchMessages(selected)}
                disabled={loadingMessages}
              >
                <RefreshCw className={cn('h-3.5 w-3.5', loadingMessages && 'animate-spin')} />
                Refresh
              </Button>
            </div>

            {/* Messages */}
            <div className="flex-1 min-h-0 relative overflow-hidden" ref={msgAreaRef}>
              {/* Telegram-style wallpaper behind the feed */}
              <TgWallpaper preset={wallpaper} className="absolute inset-0 -z-0 pointer-events-none" />
              <ScrollArea className="relative z-[1] h-full px-2 md:px-4 py-2">
                {loadingMessages ? (
                  <div className="space-y-4 pt-4">
                    {Array.from({ length: 4 }).map((_, i) => (
                      <div key={i} className="flex gap-3">
                        <Skeleton className="h-9 w-9 rounded-full shrink-0 mt-1" />
                        <div className="space-y-1.5 flex-1">
                          <Skeleton className="h-3 w-24" />
                          <Skeleton className="h-20 w-[85%] rounded-2xl" />
                        </div>
                      </div>
                    ))}
                  </div>
                ) : messages.length === 0 ? (
                  <div className="flex flex-col items-center justify-center h-full pt-16 text-muted-foreground">
                    <p className="text-sm">No messages found</p>
                  </div>
                ) : (
                  <div className="space-y-1 py-2">
                    {renderedMessages}
                    <div ref={msgEndRef} />
                  </div>
                )}
              </ScrollArea>

              {/* New messages badge */}
              {newMsgCount > 0 && (
                <div className="absolute bottom-3 inset-x-0 flex justify-center z-10 pointer-events-none">
                  <button
                    className="pointer-events-auto flex items-center gap-1.5 bg-primary text-primary-foreground text-xs font-medium px-3 py-1.5 rounded-full shadow-lg hover:bg-primary/90 transition-colors"
                    onClick={() => {
                      setNewMsgCount(0)
                      isAtBottomRef.current = true
                      msgEndRef.current?.scrollIntoView({ behavior: 'smooth' })
                    }}
                  >
                    <ChevronDown className="h-3.5 w-3.5" />
                    {newMsgCount} new message{newMsgCount > 1 ? 's' : ''}
                  </button>
                </div>
              )}
            </div>
          </>
        )}
      </div>

      {/* ── Signal review / execute dialog ──────────────────────────────────── */}
      <SignalDialog open={!!signalResult} onOpenChange={o => { if (!o) closePreview() }}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-base">
              {edits ? (
                <Eye className="h-4 w-4 text-primary shrink-0" />
              ) : signalResult?.result.clarification ? (
                <AlertCircle className="h-4 w-4 text-amber-500 shrink-0" />
              ) : (
                <AlertCircle className="h-4 w-4 text-muted-foreground shrink-0" />
              )}
              {edits
                ? signalResult?.result.signal ? 'Review before placing' : 'Enter the trade'
                : signalResult?.result.clarification
                  ? 'Needs your input'
                  : 'No signal found'}
            </DialogTitle>
          </DialogHeader>

          {signalResult?.result.error && (
            <div className="rounded-md bg-destructive/10 border border-destructive/20 px-3 py-2 text-xs text-destructive break-words">
              {signalResult.result.error}
            </div>
          )}

          {signalResult && edits ? (
            <>
              <p className="text-xs text-muted-foreground -mt-1">
                {signalResult.result.signal
                  ? <>Read from the {SOURCE_LABEL[signalResult.result.source ?? 'text'] ?? 'message'}. Check each field, edit anything
                    it misread, then place the trade.</>
                  : <>Type the trade in.</>}
                {' '}Nothing is sent to the market until you press{' '}
                <span className="font-medium text-foreground">Place Trade</span>.
              </p>

              {edits.action !== 'OPEN' && (
                <Badge variant="secondary" className="text-[10px] w-fit">Command: {edits.action}</Badge>
              )}

              {(signalResult.result.notes?.length ?? 0) > 0 && (
                <ul className="rounded-md bg-amber-500/10 border border-amber-500/30 px-3 py-2 text-xs text-amber-700 dark:text-amber-300 space-y-0.5 list-disc pl-6">
                  {signalResult.result.notes!.map(n => <li key={n}>{n}</li>)}
                </ul>
              )}

              <div className="grid grid-cols-2 gap-3">
                {/* Symbol */}
                <div className="space-y-1">
                  <Label className="text-[11px] text-muted-foreground">Symbol</Label>
                  <Input
                    value={edits.symbol}
                    onChange={e => setEdits({ ...edits, symbol: e.target.value.toUpperCase() })}
                    className="h-8 text-sm font-mono"
                  />
                </div>

                {/* Direction */}
                <div className="space-y-1">
                  <Label className="text-[11px] text-muted-foreground">Direction</Label>
                  <div className="flex gap-1">
                    {(['BUY', 'SELL'] as const).map(dir => (
                      <button
                        key={dir}
                        type="button"
                        onClick={() => setEdits({ ...edits, order_type: dir })}
                        className={cn(
                          'flex-1 h-8 rounded-md text-xs font-semibold transition-colors border',
                          edits.order_type === dir
                            ? dir === 'BUY'
                              ? 'bg-green-500/15 text-green-600 dark:text-green-400 border-green-500/40'
                              : 'bg-red-500/15 text-red-600 dark:text-red-400 border-red-500/40'
                            : 'border-border text-muted-foreground hover:bg-muted'
                        )}
                      >
                        {dir}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Entry — single price · range zone · scale-in legs */}
                <div className="space-y-1.5 col-span-2">
                  <div className="flex items-center justify-between gap-2">
                    <Label className="text-[11px] text-muted-foreground">Entry</Label>
                    <div className="flex gap-0.5 rounded-md bg-muted p-0.5">
                      {([
                        ['single', 'Single'],
                        ['range', 'Range'],
                        ['legs', 'Legs'],
                      ] as const).map(([mode, label]) => (
                        <button
                          key={mode}
                          type="button"
                          onClick={() => setEdits({ ...edits, entryMode: mode })}
                          className={cn(
                            'px-2 py-0.5 rounded text-[10px] font-medium transition-colors',
                            edits.entryMode === mode
                              ? 'bg-background text-foreground shadow-sm'
                              : 'text-muted-foreground hover:text-foreground'
                          )}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                  </div>

                  {edits.entryMode === 'range' ? (
                    <div className="flex items-center gap-2">
                      <Input
                        inputMode="decimal"
                        placeholder="min"
                        value={edits.entry_range_min}
                        onChange={e => setEdits({ ...edits, entry_range_min: e.target.value })}
                        className="h-8 text-sm font-mono"
                      />
                      <span className="text-muted-foreground text-xs">–</span>
                      <Input
                        inputMode="decimal"
                        placeholder="max"
                        value={edits.entry_range_max}
                        onChange={e => setEdits({ ...edits, entry_range_max: e.target.value })}
                        className="h-8 text-sm font-mono"
                      />
                    </div>
                  ) : edits.entryMode === 'legs' ? (
                    <>
                      <Input
                        placeholder="e.g. 4020, 4030"
                        value={edits.legs}
                        onChange={e => setEdits({ ...edits, legs: e.target.value })}
                        className="h-8 text-sm font-mono"
                      />
                      <p className="text-[10px] text-muted-foreground leading-tight">
                        {(() => {
                          const n = edits.legs.split(',').map(s => s.trim()).filter(Boolean).length
                          return n >= 2
                            ? `${n} simultaneous legs, same direction — one order each, sharing the SL & TPs below.`
                            : 'Enter 2+ comma-separated prices for a scale-in. Fewer collapses to a single entry.'
                        })()}
                      </p>
                    </>
                  ) : (
                    <Input
                      inputMode="decimal"
                      placeholder="market / price"
                      value={edits.entry_price}
                      onChange={e => setEdits({ ...edits, entry_price: e.target.value })}
                      className="h-8 text-sm font-mono"
                    />
                  )}
                </div>

                {/* Stop loss */}
                <div className="space-y-1">
                  <Label className="text-[11px] text-muted-foreground">Stop Loss</Label>
                  <Input
                    inputMode="decimal"
                    value={edits.stop_loss}
                    onChange={e => setEdits({ ...edits, stop_loss: e.target.value })}
                    className="h-8 text-sm font-mono"
                  />
                </div>

                {/* Take profit */}
                <div className="space-y-1">
                  <Label className="text-[11px] text-muted-foreground">Take Profit</Label>
                  <Input
                    placeholder="comma-separated"
                    value={edits.take_profit}
                    onChange={e => setEdits({ ...edits, take_profit: e.target.value })}
                    className="h-8 text-sm font-mono"
                  />
                </div>
              </div>

              <div className="flex items-center gap-2 flex-wrap">
                {signalResult.result.signal?.is_plan && (
                  <Badge variant="secondary" className="text-[10px]">Plan Signal</Badge>
                )}
                {!!signalResult.result.signal?.confidence && (
                  <span className="text-[11px] text-muted-foreground">
                    AI confidence {(signalResult.result.signal.confidence * 100).toFixed(0)}%
                  </span>
                )}
              </div>

              <DialogFooter className="gap-2 sm:gap-2">
                <Button variant="ghost" onClick={closePreview} disabled={placing}>
                  Cancel
                </Button>
                <Button
                  onClick={placeSignal}
                  disabled={placing || (edits.action === 'OPEN' && (!edits.symbol.trim() || !edits.order_type))}
                  className="gap-1.5"
                >
                  {placing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                  {placing ? 'Placing…' : 'Place Trade'}
                </Button>
              </DialogFooter>
            </>
          ) : signalResult?.result.clarification ? (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">
                Found a {signalResult.result.clarification.order_type ?? '?'} {signalResult.result.clarification.is_plan ? 'plan' : 'signal'} but couldn&apos;t read the
                instrument off the chart — entry{' '}
                <span className="font-medium text-foreground">{signalResult.result.clarification.entry ?? '—'}</span>
                {signalResult.result.clarification.take_profit?.length
                  ? <>, TP <span className="font-medium text-foreground">{signalResult.result.clarification.take_profit.join(', ')}</span></>
                  : null}
                . Which instrument is this?
              </p>
              <div className="flex gap-2">
                <Input
                  placeholder="e.g. XAUUSD"
                  value={symbolInput}
                  onChange={e => setSymbolInput(e.target.value.toUpperCase())}
                  onKeyDown={e => {
                    if (e.key === 'Enter' && signalResult?.result.clarification) {
                      resolveSymbol(signalResult.result.clarification.id)
                    }
                  }}
                  className="text-sm"
                  autoFocus
                />
                <Button
                  size="sm"
                  disabled={!symbolInput.trim() || resolvingSymbol}
                  onClick={() => resolveSymbol(signalResult.result.clarification!.id)}
                >
                  Submit
                </Button>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">
                {signalResult?.result.rejection_reason ?? 'The AI could not extract a trading signal from this message.'}
              </p>
              {previewMsg && (
                <DialogFooter className="gap-2 sm:gap-2">
                  <Button variant="ghost" onClick={closePreview}>Close</Button>
                  <Button onClick={() => setEdits({ ...EMPTY_FORM })} className="gap-1.5">
                    <Send className="h-4 w-4" />
                    Enter trade manually
                  </Button>
                </DialogFooter>
              )}
            </div>
          )}
        </DialogContent>
      </SignalDialog>

      {/* ── Image lightbox ──────────────────────────────────────────────────── */}
      {lightboxSrc && (
        <div
          className="fixed inset-0 z-[100] bg-black/95 flex flex-col"
          style={{
            paddingTop: 'env(safe-area-inset-top)',
            paddingBottom: 'env(safe-area-inset-bottom)',
          }}
          onClick={() => setLightboxSrc(null)}
        >
          {/* Close row */}
          <div
            className="flex items-center justify-end px-3 py-2 shrink-0"
            onClick={e => e.stopPropagation()}
          >
            <Button
              variant="ghost"
              size="icon"
              className="text-white hover:bg-white/10 h-10 w-10"
              onClick={() => setLightboxSrc(null)}
            >
              <X className="h-5 w-5" />
            </Button>
          </div>
          {/* Image — flex-1 + min-h-0 constrains height so max-h-full works */}
          <div className="flex-1 min-h-0 flex items-center justify-center p-3">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={lightboxSrc}
              alt="Full size"
              className="max-w-full max-h-full object-contain rounded-lg"
              onClick={e => e.stopPropagation()}
            />
          </div>
        </div>
      )}
    </div>
  )
}
