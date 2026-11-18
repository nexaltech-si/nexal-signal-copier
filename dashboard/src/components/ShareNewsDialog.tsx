'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { useToast } from '@/hooks/use-toast'
import { Image as ImageIcon, FileText, Copy, Share2, Download, Loader2, Check } from 'lucide-react'
import {
  parseNewsShareConfig,
  DEFAULT_NEWS_SHARE_CONFIG,
  type NewsShareConfig,
  type ShareEvent,
} from '@/lib/types/newsShare'
import { formatNewsText } from '@/lib/newsShareFormat'
import { renderNewsImage } from '@/lib/newsShareImage'

type Mode = 'text' | 'image'

interface ShareNewsDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Events already filtered + sorted by the calendar page. */
  events: ShareEvent[]
  /** Timezone label e.g. "GMT+3", appended when the config asks for it. */
  tzNote: string
  /** Short context for the share-sheet title, e.g. "Today" or "This Week". */
  periodLabel: string
}

function canNativeShare(): boolean {
  return typeof navigator !== 'undefined' && typeof navigator.share === 'function'
}

function canShareFiles(files: File[]): boolean {
  try {
    return (
      typeof navigator !== 'undefined' &&
      typeof navigator.canShare === 'function' &&
      navigator.canShare({ files })
    )
  } catch {
    return false
  }
}

export default function ShareNewsDialog({
  open,
  onOpenChange,
  events,
  tzNote,
  periodLabel,
}: ShareNewsDialogProps) {
  const { toast } = useToast()
  const [mode, setMode] = useState<Mode>('text')
  const [cfg, setCfg] = useState<NewsShareConfig>(DEFAULT_NEWS_SHARE_CONFIG)
  const [busy, setBusy] = useState<null | 'image' | 'copy' | 'share' | 'download'>(null)
  const [copied, setCopied] = useState(false)
  const [imgUrl, setImgUrl] = useState<string | null>(null)
  const imgBlobRef = useRef<Blob | null>(null)

  // Load the persisted branding/format config when the dialog opens.
  useEffect(() => {
    if (!open) return
    let cancelled = false
    fetch('/api/user-settings')
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (cancelled) return
        setCfg(parseNewsShareConfig(data?.newsShareConfig))
      })
      .catch(() => !cancelled && setCfg(DEFAULT_NEWS_SHARE_CONFIG))
    return () => {
      cancelled = true
    }
  }, [open])

  const text = useMemo(() => formatNewsText(events, cfg, tzNote), [events, cfg, tzNote])

  // (Re)render the image whenever the image tab is active and inputs change.
  useEffect(() => {
    if (!open || mode !== 'image') return
    let cancelled = false
    setBusy('image')
    setImgUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev)
      return null
    })
    renderNewsImage(events, cfg, tzNote)
      .then((blob) => {
        if (cancelled) return
        imgBlobRef.current = blob
        setImgUrl(URL.createObjectURL(blob))
      })
      .catch((err) => {
        console.error('Failed to render share image:', err)
        if (!cancelled) toast({ title: 'Could not render image', variant: 'destructive' })
      })
      .finally(() => !cancelled && setBusy(null))
    return () => {
      cancelled = true
    }
  }, [open, mode, events, cfg, tzNote, toast])

  // Clean up object URLs on close/unmount.
  useEffect(() => {
    if (open) return
    setCopied(false)
    setImgUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev)
      return null
    })
    imgBlobRef.current = null
  }, [open])

  const shareTitle = `Economic Calendar · ${periodLabel}`

  // ── Text actions ─────────────────────────────────────────────
  const copyText = async () => {
    setBusy('copy')
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1800)
      toast({ title: 'Copied to clipboard' })
    } catch {
      toast({ title: 'Copy failed', description: 'Select and copy manually.', variant: 'destructive' })
    } finally {
      setBusy(null)
    }
  }

  const shareText = async () => {
    if (!canNativeShare()) return copyText()
    setBusy('share')
    try {
      await navigator.share({ title: shareTitle, text })
    } catch (err) {
      // AbortError = user cancelled the sheet; ignore.
      if ((err as Error)?.name !== 'AbortError') {
        toast({ title: 'Share cancelled', variant: 'destructive' })
      }
    } finally {
      setBusy(null)
    }
  }

  // ── Image actions ────────────────────────────────────────────
  const imageFile = () => {
    const blob = imgBlobRef.current
    if (!blob) return null
    return new File([blob], `economic-calendar-${periodLabel.toLowerCase().replace(/\s+/g, '-')}.png`, {
      type: 'image/png',
    })
  }

  const shareImage = async () => {
    const file = imageFile()
    if (!file) return
    if (canNativeShare() && canShareFiles([file])) {
      setBusy('share')
      try {
        await navigator.share({ title: shareTitle, text: cfg.brandName || undefined, files: [file] })
      } catch (err) {
        if ((err as Error)?.name !== 'AbortError') {
          toast({ title: 'Share cancelled', variant: 'destructive' })
        }
      } finally {
        setBusy(null)
      }
    } else {
      // No file-share support (most desktops) → download instead.
      downloadImage()
      toast({ title: 'Image saved', description: 'File sharing not supported here — downloaded instead.' })
    }
  }

  const downloadImage = () => {
    if (!imgUrl) return
    setBusy('download')
    const a = document.createElement('a')
    a.href = imgUrl
    a.download = `economic-calendar-${periodLabel.toLowerCase().replace(/\s+/g, '-')}.png`
    document.body.appendChild(a)
    a.click()
    a.remove()
    setBusy(null)
  }

  const copyImage = async () => {
    const blob = imgBlobRef.current
    if (!blob) return
    setBusy('copy')
    try {
      // ClipboardItem image copy — supported on Chromium desktop.
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const CI = (window as any).ClipboardItem
      if (!CI || !navigator.clipboard?.write) throw new Error('unsupported')
      await navigator.clipboard.write([new CI({ 'image/png': blob })])
      setCopied(true)
      setTimeout(() => setCopied(false), 1800)
      toast({ title: 'Image copied' })
    } catch {
      downloadImage()
      toast({ title: 'Image saved', description: 'Clipboard image copy not supported — downloaded instead.' })
    } finally {
      setBusy(null)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Share2 className="h-4 w-4" />
            Share News · {periodLabel}
          </DialogTitle>
          <DialogDescription>
            {events.length} event{events.length === 1 ? '' : 's'} · uses your current filters &amp; branding.
          </DialogDescription>
        </DialogHeader>

        {/* Mode toggle */}
        <div className="flex items-center rounded-lg border border-border overflow-hidden w-full">
          <button
            onClick={() => setMode('text')}
            className={cn(
              'flex-1 flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-semibold transition-colors',
              mode === 'text' ? 'bg-primary text-white' : 'text-muted-foreground hover:bg-muted',
            )}
          >
            <FileText className="h-3.5 w-3.5" /> Text
          </button>
          <button
            onClick={() => setMode('image')}
            className={cn(
              'flex-1 flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-semibold transition-colors',
              mode === 'image' ? 'bg-primary text-white' : 'text-muted-foreground hover:bg-muted',
            )}
          >
            <ImageIcon className="h-3.5 w-3.5" /> Image
          </button>
        </div>

        {/* Preview */}
        <div className="rounded-lg border border-border bg-muted/30 max-h-[46vh] overflow-auto p-3">
          {mode === 'text' ? (
            <pre className="whitespace-pre-wrap break-words text-xs font-mono text-foreground/90 leading-relaxed">
              {text}
            </pre>
          ) : busy === 'image' && !imgUrl ? (
            <div className="flex items-center justify-center py-12 text-muted-foreground">
              <Loader2 className="h-5 w-5 animate-spin" />
            </div>
          ) : imgUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={imgUrl} alt="News share preview" className="w-full rounded-md" />
          ) : (
            <div className="flex items-center justify-center py-12 text-xs text-muted-foreground">
              Nothing to preview.
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="flex flex-wrap gap-2">
          {mode === 'text' ? (
            <>
              <Button onClick={shareText} disabled={!!busy || !text} className="flex-1 min-w-[8rem] font-semibold">
                {busy === 'share' ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Share2 className="h-4 w-4 mr-2" />}
                {canNativeShare() ? 'Share' : 'Copy to Share'}
              </Button>
              <Button variant="outline" onClick={copyText} disabled={!!busy || !text} className="flex-1 min-w-[8rem] font-semibold">
                {copied ? <Check className="h-4 w-4 mr-2 text-success" /> : <Copy className="h-4 w-4 mr-2" />}
                {copied ? 'Copied' : 'Copy Text'}
              </Button>
            </>
          ) : (
            <>
              <Button onClick={shareImage} disabled={!!busy || !imgUrl} className="flex-1 min-w-[8rem] font-semibold">
                {busy === 'share' ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Share2 className="h-4 w-4 mr-2" />}
                Share
              </Button>
              <Button variant="outline" onClick={copyImage} disabled={!!busy || !imgUrl} className="flex-1 min-w-[7rem] font-semibold">
                {copied ? <Check className="h-4 w-4 mr-2 text-success" /> : <Copy className="h-4 w-4 mr-2" />}
                {copied ? 'Copied' : 'Copy'}
              </Button>
              <Button variant="outline" onClick={downloadImage} disabled={!!busy || !imgUrl} className="flex-1 min-w-[7rem] font-semibold">
                <Download className="h-4 w-4 mr-2" /> Save
              </Button>
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
