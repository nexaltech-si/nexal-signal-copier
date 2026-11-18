'use client'

import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { createPortal } from 'react-dom'
import { Zap, X, ChevronDown } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { formatCurrency } from '@/lib/utils'

// ── Types ────────────────────────────────────────────────────────────────────
interface Position {
  ticket: number
  symbol: string
  type: number
  volume: number
  price_open: number
  price_current: number
  sl: number
  tp: number
  profit: number
  swap: number
  commission: number
}

interface AccountInfo {
  balance: number
  equity: number
}

interface TickData {
  bid: number
  ask: number
  last: number
  time: number
}

interface SymbolInfo {
  digits: number
  tickSize: number
  tickValue: number
  volumeStep: number
  volumeMin: number
  volumeMax: number
}

interface NexalPanelProps {
  account: AccountInfo | null
  positions: Position[]
  actionLoading: boolean
  externalModalOpen: boolean
  onClosePosition: (ticket: number) => void
  onHalfPosition: (ticket: number) => void
  onCloseProfitable: () => void
  onCloseLosing: () => void
  onCloseAll: () => void
}

// ── Constants ───────────────────────────────────────────────────────────────
const BE_PRESETS = [0.50, 1.00, 2.00, 3.00, 5.00, 10.00]
const TRAILS: { key: string; label: string; start: number; step: number; add: number }[] = [
  { key: 'FAST', label: 'Fast', start: 0.50, step: 2.0, add: 1.0 },
  { key: 'MED', label: 'Med', start: 0.50, step: 4.0, add: 2.0 },
  { key: 'SLOW', label: 'Slow', start: 0.50, step: 10.0, add: 8.0 },
]
const TICK_INTERVAL_MS = 1000

/** Net PnL for a position (profit + swap + commission) */
const netPnl = (p: Position): number => p.profit + (p.swap ?? 0) + (p.commission ?? 0)

const FAB_SIZE = 40  // w-10 h-10

/** Keep the floating button fully inside the viewport. */
const clampFabPos = (pos: { right: number; bottom: number }) => ({
  right: Math.max(0, Math.min(window.innerWidth - FAB_SIZE, Number(pos.right) || 0)),
  bottom: Math.max(0, Math.min(window.innerHeight - FAB_SIZE, Number(pos.bottom) || 0)),
})

export default function NexalPanel({
  account,
  positions,
  actionLoading,
  externalModalOpen,
  onClosePosition,
  onHalfPosition,
  onCloseProfitable,
  onCloseLosing,
  onCloseAll,
}: NexalPanelProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [tab, setTab] = useState<'trade' | 'live'>('trade')
  const [activeTrail, setActiveTrail] = useState<string | null>(null)
  const [mounted, setMounted] = useState(false)
  const [internalLoading, setInternalLoading] = useState(false)

  // ── Symbol & tick state ──────────────────────────────────────────────────
  const [selectedSymbol, setSelectedSymbol] = useState<string>('ALL')
  const [tickData, setTickData] = useState<TickData | null>(null)
  const [symbolInfo, setSymbolInfo] = useState<SymbolInfo | null>(null)
  const [symbolDropdownOpen, setSymbolDropdownOpen] = useState(false)

  // ── FAB position (draggable, persisted) ──────────────────────────────────
  const [fabPos, setFabPos] = useState<{ right: number; bottom: number }>(() => {
    if (typeof window !== 'undefined') {
      try {
        // Saved on a wider screen (or before rotating) it can sit off-screen here.
        const saved = localStorage.getItem('nexal-fab-pos')
        if (saved) return clampFabPos(JSON.parse(saved))
      } catch { /* ignore */ }
      if (window.innerWidth >= 768) return { right: 24, bottom: 24 }   // md:bottom-6 md:right-6
      return { right: 16, bottom: 96 }                                  // bottom-24 right-4
    }
    return { right: 24, bottom: 24 }
  })

  const loading = actionLoading || internalLoading

  // Derive unique symbols from positions
  const symbols = useMemo(() => {
    const set = new Set<string>()
    positions.forEach(p => set.add(p.symbol))
    return Array.from(set).sort()
  }, [positions])

  // When selectedSymbol disappears from positions, fall back to ALL
  useEffect(() => {
    if (symbols.length > 0 && selectedSymbol !== 'ALL' && !symbols.includes(selectedSymbol)) {
      setSelectedSymbol('ALL')
    }
  }, [symbols, selectedSymbol])

  // ── Drag state (refs only — no re-renders) ──────────────────────────────
  const panelRef = useRef<HTMLDivElement>(null)
  const mobilePanelRef = useRef<HTMLDivElement>(null)
  const isDragging = useRef(false)
  const origin = useRef({ mx: 0, my: 0, px: 0, py: 0 })
  const tickTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // ── FAB drag refs (DOM manipulation for smooth dragging) ────────────────
  const fabRef = useRef<HTMLButtonElement>(null)
  const fabDragging = useRef(false)
  const fabStartMouse = useRef({ mx: 0, my: 0 })
  const fabStartPos = useRef({ right: 0, bottom: 0 })
  const fabHasMoved = useRef(false)

  // Hydration safety
  useEffect(() => { setMounted(true) }, [])

  // Auto-close when an external modal opens
  useEffect(() => {
    if (externalModalOpen) setIsOpen(false)
  }, [externalModalOpen])

  // ── Live tick polling ──────────────────────────────────────────────────
  const fetchTick = useCallback(async (sym: string) => {
    if (sym === 'ALL') {
      if (symbols.length > 0) sym = symbols[0]
      else { setTickData(null); return }
    }
    try {
      const res = await fetch(`/api/mt5/symbol-tick?symbol=${encodeURIComponent(sym)}`)
      if (!res.ok) throw new Error('Tick fetch failed')
      const data = await res.json()
      setTickData({ bid: data.bid, ask: data.ask, last: data.last, time: data.time })
    } catch { setTickData(null) }
  }, [symbols])

  const fetchSymbolInfo = useCallback(async (sym: string) => {
    if (sym === 'ALL') { setSymbolInfo(null); return }
    try {
      const res = await fetch(`/api/symbol-info?symbol=${encodeURIComponent(sym)}`)
      if (!res.ok) throw new Error('Symbol info fetch failed')
      const data = await res.json()
      setSymbolInfo({
        digits: data.digits ?? 5,
        tickSize: data.tickSize ?? data.point ?? 0.00001,
        tickValue: data.tickValue ?? 10,
        volumeStep: data.volumeStep ?? 0.01,
        volumeMin: data.volumeMin ?? 0.01,
        volumeMax: data.volumeMax ?? 100,
      })
    } catch { setSymbolInfo(null) }
  }, [])

  useEffect(() => {
    if (!isOpen) {
      if (tickTimerRef.current) { clearInterval(tickTimerRef.current); tickTimerRef.current = null }
      return
    }
    fetchTick(selectedSymbol)
    fetchSymbolInfo(selectedSymbol)
    tickTimerRef.current = setInterval(() => fetchTick(selectedSymbol), TICK_INTERVAL_MS)
    return () => {
      if (tickTimerRef.current) { clearInterval(tickTimerRef.current); tickTimerRef.current = null }
    }
  }, [isOpen, selectedSymbol, fetchTick, fetchSymbolInfo])

  // ── Filtered positions by selected symbol ──────────────────────────────
  const filteredPositions = useMemo(() => {
    if (selectedSymbol === 'ALL') return positions
    return positions.filter(p => p.symbol === selectedSymbol)
  }, [positions, selectedSymbol])

  // ── Derived data ─────────────────────────────────────────────────────────
  const buyPositions   = filteredPositions.filter(p => p.type === 0)
  const sellPositions  = filteredPositions.filter(p => p.type === 1)
  const totalVolume    = filteredPositions.reduce((s, p) => s + p.volume, 0)
  const netPnLVal       = filteredPositions.reduce((s, p) => s + netPnl(p), 0)
  const allNetPnLVal    = positions.reduce((s, p) => s + netPnl(p), 0)

  // ── Smart enable/disable conditions ───────────────────────────────────
  const hasPositions   = filteredPositions.length > 0
  const hasBuy         = buyPositions.length > 0
  const hasSell        = sellPositions.length > 0
  const hasProfitable  = filteredPositions.some(p => netPnl(p) > 0)
  const hasLosing      = filteredPositions.some(p => netPnl(p) < 0)

  // ── Helper: dollar → price offset ──────────────────────────────────────
  const dollarToPriceOffset = (dollar: number, volume: number, info?: SymbolInfo | null): number => {
    const si = info ?? symbolInfo
    if (!si || volume <= 0) return dollar * 0.1
    const { tickSize, tickValue } = si
    if (tickValue <= 0 || tickSize <= 0) return dollar * 0.1
    return dollar * tickSize / (tickValue * volume)
  }

  /** Can any position have BE set? (position must be in profit enough for the smallest offset) */
  const canSetBE = useMemo(() => {
    if (!hasPositions) return false
    const minDollar = BE_PRESETS[0] // $0.50
    const info = symbolInfo
    return filteredPositions.some(pos => {
      const priceOff = dollarToPriceOffset(minDollar, pos.volume, info)
      // Use live tick if available, fall back to price_current
      const priceNow = pos.type === 0
        ? (tickData?.bid ?? pos.price_current)
        : (tickData?.ask ?? pos.price_current)
      if (pos.type === 0) return pos.price_open + priceOff < priceNow
      else                 return pos.price_open - priceOff > priceNow
    })
  }, [hasPositions, filteredPositions, tickData, symbolInfo])

  // ── Drag handlers (desktop only) ─────────────────────────────────────────
  const onDragStart = useCallback((e: React.MouseEvent) => {
    if (window.innerWidth <= 640 || !panelRef.current) return
    isDragging.current = true
    const rect = panelRef.current.getBoundingClientRect()
    origin.current = { mx: e.clientX, my: e.clientY, px: rect.left, py: rect.top }
    if (panelRef.current) panelRef.current.style.transition = 'none'
    e.preventDefault()
  }, [])

  const onDragMove = useCallback((e: MouseEvent) => {
    if (!isDragging.current || !panelRef.current) return
    const { mx, my, px, py } = origin.current
    let nx = px + (e.clientX - mx)
    let ny = py + (e.clientY - my)
    const pw = panelRef.current.offsetWidth
    const ph = panelRef.current.offsetHeight
    nx = Math.max(0, Math.min(window.innerWidth - pw, nx))
    ny = Math.max(0, Math.min(window.innerHeight - ph, ny))
    panelRef.current.style.left = nx + 'px'
    panelRef.current.style.top = ny + 'px'
    panelRef.current.style.right = 'auto'
    panelRef.current.style.bottom = 'auto'
  }, [])

  const onDragEnd = useCallback(() => {
    if (!isDragging.current || !panelRef.current) return
    isDragging.current = false
    if (panelRef.current) panelRef.current.style.transition = ''
  }, [])

  useEffect(() => {
    document.addEventListener('mousemove', onDragMove)
    document.addEventListener('mouseup', onDragEnd)
    return () => {
      document.removeEventListener('mousemove', onDragMove)
      document.removeEventListener('mouseup', onDragEnd)
    }
  }, [onDragMove, onDragEnd])

  // ── FAB drag handlers (pointer events: mouse, touch and pen) ────────────
  // Was mouse-only and switched off below 640px, so on a phone the button never
  // moved. Pointer capture keeps the drag on the button; touch-action: none on
  // it stops the page scrolling instead. DOM manipulation — no re-renders.
  const onFabPointerDown = useCallback((e: React.PointerEvent<HTMLButtonElement>) => {
    if (e.pointerType === 'mouse' && e.button !== 0) return
    fabDragging.current = true
    fabHasMoved.current = false
    fabStartMouse.current = { mx: e.clientX, my: e.clientY }
    fabStartPos.current = { right: fabPos.right, bottom: fabPos.bottom }
    e.currentTarget.setPointerCapture(e.pointerId)
    e.currentTarget.style.transition = 'none'
  }, [fabPos])

  const onFabPointerMove = useCallback((e: React.PointerEvent<HTMLButtonElement>) => {
    if (!fabDragging.current) return
    const dx = e.clientX - fabStartMouse.current.mx
    const dy = e.clientY - fabStartMouse.current.my
    // A finger wobbles a few px on a tap: below that it is a tap, not a drag.
    if (!fabHasMoved.current && Math.hypot(dx, dy) < 6) return
    fabHasMoved.current = true
    const { right, bottom } = clampFabPos({
      right: fabStartPos.current.right - dx,
      bottom: fabStartPos.current.bottom - dy,
    })
    e.currentTarget.style.right = right + 'px'
    e.currentTarget.style.bottom = bottom + 'px'
  }, [])

  const onFabPointerUp = useCallback((e: React.PointerEvent<HTMLButtonElement>) => {
    if (!fabDragging.current) return
    fabDragging.current = false
    e.currentTarget.style.transition = ''
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId)
    if (fabHasMoved.current) {
      const newPos = {
        right: parseFloat(e.currentTarget.style.right),
        bottom: parseFloat(e.currentTarget.style.bottom),
      }
      setFabPos(newPos)
      try { localStorage.setItem('nexal-fab-pos', JSON.stringify(newPos)) } catch { /* ignore */ }
    }
  }, [])

  // ── Action: BE (no confirmation) ───────────────────────────────────────
  const handleBE = async (dollarOffset: number) => {
    if (!hasPositions) { toast.error('No positions'); return }
    setInternalLoading(true)
    let applied = 0; let skipped = 0
    try {
      let info = symbolInfo
      if (selectedSymbol !== 'ALL') {
        await fetchSymbolInfo(selectedSymbol)
        // Re-read symbolInfo after fetch — it's stale in closure
      }
      for (const pos of filteredPositions) {
        const currInfo = symbolInfo // will be stale for first iteration if fetch pending
        const priceOff = dollarToPriceOffset(dollarOffset, pos.volume, currInfo)
        const digits = currInfo?.digits ?? 5
        const newSL = pos.type === 0
          ? +(pos.price_open + priceOff).toFixed(digits)
          : +(pos.price_open - priceOff).toFixed(digits)
        const priceNow = pos.type === 0 ? (tickData?.bid ?? pos.price_current) : (tickData?.ask ?? pos.price_current)
        if (pos.type === 0 && newSL >= priceNow) { skipped++; continue }
        if (pos.type === 1 && newSL <= priceNow) { skipped++; continue }
        try {
          const res = await fetch('/api/mt5/modify-sltp', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ position: pos.ticket, sl: newSL, tp: pos.tp || undefined }),
          })
          if (res.ok) applied++; else skipped++
        } catch { skipped++ }
      }
      if (applied > 0) {
        toast.success(`BE +$${dollarOffset}`, { description: `${applied}/${filteredPositions.length} positions • ${selectedSymbol}` })
      } else {
        toast.error('BE failed', { description: 'No position could be breakeven-locked. Price may be too close.' })
      }
    } catch (err) {
      toast.error('BE error', { description: err instanceof Error ? err.message : 'Failed' })
    } finally { setInternalLoading(false) }
  }

  // ── Action: Trail (no confirmation) ───────────────────────────────────
  const handleTrail = (trailKey: string) => {
    if (activeTrail === trailKey) {
      setActiveTrail(null)
      toast.info('Trail stopped', { description: 'Trailing stopped' })
      return
    }
    if (!hasPositions) { toast.error('No positions to trail'); return }
    setActiveTrail(trailKey)
    const trail = TRAILS.find(t => t.key === trailKey)
    toast.success(`Trail ${trail?.label}`, { description: `Trailing ${filteredPositions.length} positions • ${selectedSymbol}` })
  }

  // ── Action: Close % (no confirmation) ─────────────────────────────────
  const handleClosePercent = async (pct: number) => {
    if (!hasPositions) { toast.error('No positions'); return }
    setInternalLoading(true)
    let ok = 0; let fail = 0
    try {
      for (const pos of filteredPositions) {
        const closeVol = +(pos.volume * pct).toFixed(2)
        if (closeVol <= 0) continue
        try {
          const res = await fetch('/api/mt5/close-partial', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ position: pos, volume: closeVol }),
          })
          if (res.ok) ok++; else fail++
        } catch { fail++ }
      }
      ok > 0
        ? toast.success(`Closed ${(pct * 100).toFixed(0)}%`, { description: `${ok} partial(s) • ${selectedSymbol}` })
        : toast.error('Close failed')
    } catch { toast.error('Close error') }
    finally { setInternalLoading(false) }
  }

  // ── Action: Close % + BE (no confirmation) ────────────────────────────
  const handleCloseAndBE = async (pct: number) => {
    if (!hasPositions) { toast.error('No positions'); return }
    setInternalLoading(true)
    try {
      let closed = 0
      for (const pos of filteredPositions) {
        const closeVol = +(pos.volume * pct).toFixed(2)
        if (closeVol <= 0) continue
        try {
          const res = await fetch('/api/mt5/close-partial', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ position: pos, volume: closeVol }),
          })
          if (res.ok) closed++
        } catch { /* continue */ }
      }
      await new Promise(r => setTimeout(r, 300))
      // BE on remaining
      const beOffset = 0.50
      if (selectedSymbol !== 'ALL') await fetchSymbolInfo(selectedSymbol)
      let beApplied = 0
      for (const pos of filteredPositions) {
        const remainingVol = +(pos.volume * (1 - pct)).toFixed(2)
        if (remainingVol <= 0) continue
        const priceOff = dollarToPriceOffset(beOffset, remainingVol)
        const digits = symbolInfo?.digits ?? 5
        const newSL = pos.type === 0
          ? +(pos.price_open + priceOff).toFixed(digits)
          : +(pos.price_open - priceOff).toFixed(digits)
        try {
          const res = await fetch('/api/mt5/modify-sltp', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ position: pos.ticket, sl: newSL, tp: pos.tp || undefined }),
          })
          if (res.ok) beApplied++
        } catch { /* continue */ }
      }
      toast.success(`${(pct * 100).toFixed(0)}% + BE`, {
        description: `Closed ${closed}, BE on ${beApplied} remaining • ${selectedSymbol}`,
      })
    } catch (err) {
      toast.error('Combo error', { description: err instanceof Error ? err.message : 'Failed' })
    } finally { setInternalLoading(false) }
  }

  // ── Action: Close Buy (no confirmation — speed) ──────────────────────
  const handleCloseBuy = async () => {
    if (!hasBuy) { toast.error('No buy positions'); return }
    setInternalLoading(true)
    let ok = 0
    for (const pos of buyPositions) {
      try {
        const res = await fetch('/api/mt5/close-position', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ position: pos }),
        })
        if (res.ok) ok++
      } catch { /* continue */ }
    }
    toast.success('Buy closed', { description: `${ok}/${buyPositions.length} • ${selectedSymbol}` })
    setInternalLoading(false)
  }

  // ── Action: Close Sell (no confirmation — speed) ─────────────────────
  const handleCloseSell = async () => {
    if (!hasSell) { toast.error('No sell positions'); return }
    setInternalLoading(true)
    let ok = 0
    for (const pos of sellPositions) {
      try {
        const res = await fetch('/api/mt5/close-position', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ position: pos }),
        })
        if (res.ok) ok++
      } catch { /* continue */ }
    }
    toast.success('Sell closed', { description: `${ok}/${sellPositions.length} • ${selectedSymbol}` })
    setInternalLoading(false)
  }

  // ── Action: Close All (symbol-scoped, no confirmation — speed) ───────
  const handleCloseAllSymbol = async () => {
    if (!hasPositions) { toast.error('No positions'); return }
    // ALL mode delegates to parent (which has its own confirmation — but we bypass)
    if (selectedSymbol === 'ALL') { onCloseAll(); return }
    setInternalLoading(true)
    let ok = 0
    for (const pos of filteredPositions) {
      try {
        const res = await fetch('/api/mt5/close-position', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ position: pos }),
        })
        if (res.ok) ok++
      } catch { /* continue */ }
    }
    toast.success('All closed', { description: `${ok}/${filteredPositions.length} • ${selectedSymbol}` })
    setInternalLoading(false)
  }

  // ── Action: Close Profitable (no confirmation — speed) ───────────────
  const handleCloseProfitableSpeed = async () => {
    const profitable = filteredPositions.filter(p => netPnl(p) > 0)
    if (profitable.length === 0) { toast.error('No profitable positions'); return }
    setInternalLoading(true)
    let ok = 0
    for (const pos of profitable) {
      try {
        const res = await fetch('/api/mt5/close-position', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ position: pos }),
        })
        if (res.ok) ok++
      } catch { /* continue */ }
    }
    toast.success('Profit closed', { description: `${ok}/${profitable.length} • ${selectedSymbol}` })
    setInternalLoading(false)
  }

  // ── Action: Close Losing (no confirmation — speed) ───────────────────
  const handleCloseLosingSpeed = async () => {
    const losing = filteredPositions.filter(p => netPnl(p) < 0)
    if (losing.length === 0) { toast.error('No losing positions'); return }
    setInternalLoading(true)
    let ok = 0
    for (const pos of losing) {
      try {
        const res = await fetch('/api/mt5/close-position', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ position: pos }),
        })
        if (res.ok) ok++
      } catch { /* continue */ }
    }
    toast.success('Loss cut', { description: `${ok}/${losing.length} • ${selectedSymbol}` })
    setInternalLoading(false)
  }

  if (!mounted) return null

  // ── Shared button classes ─────────────────────────────────────────────────
  const clsPct  = "rounded-md border border-border bg-card text-muted-foreground font-mono text-[9px] font-bold py-1.5 transition-colors hover:border-primary/40 hover:text-primary"
  const clsOk   = "rounded-md border border-success/30 bg-success/5 text-success font-mono text-[9px] font-bold py-1.5 transition-colors hover:bg-success/10"
  const clsErr  = "rounded-md border border-destructive/30 bg-destructive/5 text-destructive font-mono text-[9px] font-bold py-1.5 transition-colors hover:bg-destructive/10"
  const clsWarn = "rounded-md border border-gold/30 bg-gold/5 text-gold font-mono text-[9px] font-bold py-1.5 transition-colors hover:bg-gold/10"
  const clsMuted = "rounded-md border border-border bg-card text-muted-foreground font-mono text-[9px] font-bold py-1.5 opacity-40 cursor-not-allowed"

  // ── FAB Button ────────────────────────────────────────────────────────────
  return (
    <>
      <button
        ref={fabRef}
        type="button"
        onPointerDown={onFabPointerDown}
        onPointerMove={onFabPointerMove}
        onPointerUp={onFabPointerUp}
        onPointerCancel={onFabPointerUp}
        onClick={() => {
          if (!fabHasMoved.current) setIsOpen(!isOpen)
        }}
        aria-label="Nexal trading panel"
        style={{
          position: 'fixed',
          right: fabPos.right,
          bottom: fabPos.bottom,
          zIndex: 55,
          touchAction: 'none',
        }}
        className={cn(
          "nexal-fab w-10 h-10 rounded-full",
          "bg-primary text-primary-foreground",
          "flex items-center justify-center",
          "shadow-lg border border-primary/30",
          "transition-all duration-200 hover:scale-105",
          "focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 focus:ring-offset-background"
        )}
      >
        <Zap className="h-4 w-4" />
        {positions.length > 0 && !isOpen && (
          <span className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-destructive text-destructive-foreground text-[7px] font-bold flex items-center justify-center border-2 border-background">
            {positions.length}
          </span>
        )}
      </button>

      {/* ── Desktop Floating Panel ────────────────────────────────────────── */}
      <div
        ref={panelRef}
        className={cn(
          "fixed z-[56]",
          "hidden md:flex flex-col",
          "bottom-[90px] right-5",
          "w-[272px]",
          "tech-card border-border",
          "rounded-xl",
          "shadow-2xl shadow-black/50",
          "transition-all duration-200",
          isOpen ? "opacity-100 translate-y-0 pointer-events-auto" : "opacity-0 translate-y-2 pointer-events-none"
        )}
      >
        <PanelContent
          tab={tab} setTab={setTab} activeTrail={activeTrail}
          onDragStart={onDragStart} isMobile={false} onClose={() => setIsOpen(false)}
          buyPositions={buyPositions} sellPositions={sellPositions}
          totalVolume={totalVolume} netPnL={netPnLVal} allNetPnL={allNetPnLVal}
          positions={filteredPositions} allPositions={positions}
          tickData={tickData}
          selectedSymbol={selectedSymbol} symbols={symbols}
          symbolDropdownOpen={symbolDropdownOpen}
          setSymbolDropdownOpen={setSymbolDropdownOpen}
          setSelectedSymbol={setSelectedSymbol}
          loading={loading}
          // Smart disabled states
          hasPositions={hasPositions} hasBuy={hasBuy} hasSell={hasSell}
          hasProfitable={hasProfitable} hasLosing={hasLosing}
          canSetBE={canSetBE}
          // Speed handlers
          handleBE={handleBE} handleTrail={handleTrail}
          handleClosePercent={handleClosePercent} handleCloseAndBE={handleCloseAndBE}
          handleCloseBuy={handleCloseBuy} handleCloseSell={handleCloseSell}
          handleCloseAllSymbol={handleCloseAllSymbol}
          handleCloseProfitableSpeed={handleCloseProfitableSpeed}
          handleCloseLosingSpeed={handleCloseLosingSpeed}
          // Live tab callbacks (use parent = confirmation)
          onClosePosition={onClosePosition} onHalfPosition={onHalfPosition}
          clsPct={clsPct} clsOk={clsOk} clsErr={clsErr} clsWarn={clsWarn} clsMuted={clsMuted}
        />
      </div>

      {/* ── Mobile: Backdrop + Bottom Sheet ───────────────────────────────────
          Portalled to <body> so page-level stacking contexts can't trap it
          beneath the floating bottom nav / top bar. */}
      {createPortal(<>
      {/* Backdrop overlay */}
      <div
        className={cn(
          "fixed inset-0 z-[80] md:hidden",
          "bg-black/60 backdrop-blur-sm",
          "transition-opacity duration-300",
          isOpen ? "opacity-100 pointer-events-auto" : "opacity-0 pointer-events-none"
        )}
        onClick={() => setIsOpen(false)}
        aria-hidden="true"
      />

      {/* Bottom Sheet Panel */}
      <div
        ref={mobilePanelRef}
        className={cn(
          "fixed z-[81] md:hidden flex flex-col",
          "left-0 right-0 bottom-0",
          "max-h-[88dvh] rounded-t-2xl overflow-hidden",
          "bg-background border-t border-border",
          "shadow-2xl shadow-black/60",
          "pb-[env(safe-area-inset-bottom,0px)]",
          "transition-[transform,visibility] duration-300 ease-out",
          // Closed: fully off-screen AND invisible, so iOS toolbar collapse /
          // overscroll can never reveal the sheet's top edge or shadow.
          isOpen ? "translate-y-0 visible" : "translate-y-[110%] invisible pointer-events-none"
        )}
        aria-hidden={!isOpen}
      >
        {/* Swipe handle */}
        <div className="flex-shrink-0 flex justify-center pt-3 pb-1"
          onTouchStart={(e) => {
            const startY = e.touches[0].clientY
            const onMove = (ev: TouchEvent) => {
              const dy = ev.touches[0].clientY - startY
              if (dy > 60) { setIsOpen(false); document.removeEventListener('touchmove', onMove) }
            }
            document.addEventListener('touchmove', onMove, { once: false })
            const onEnd = () => document.removeEventListener('touchmove', onMove)
            document.addEventListener('touchend', onEnd, { once: true })
          }}
        >
          <div className="w-10 h-1 rounded-full bg-border" />
        </div>

        <PanelContent
          tab={tab} setTab={setTab} activeTrail={activeTrail}
          onDragStart={undefined} isMobile={true} onClose={() => setIsOpen(false)}
          buyPositions={buyPositions} sellPositions={sellPositions}
          totalVolume={totalVolume} netPnL={netPnLVal} allNetPnL={allNetPnLVal}
          positions={filteredPositions} allPositions={positions}
          tickData={tickData}
          selectedSymbol={selectedSymbol} symbols={symbols}
          symbolDropdownOpen={symbolDropdownOpen}
          setSymbolDropdownOpen={setSymbolDropdownOpen}
          setSelectedSymbol={setSelectedSymbol}
          loading={loading}
          hasPositions={hasPositions} hasBuy={hasBuy} hasSell={hasSell}
          hasProfitable={hasProfitable} hasLosing={hasLosing}
          canSetBE={canSetBE}
          handleBE={handleBE} handleTrail={handleTrail}
          handleClosePercent={handleClosePercent} handleCloseAndBE={handleCloseAndBE}
          handleCloseBuy={handleCloseBuy} handleCloseSell={handleCloseSell}
          handleCloseAllSymbol={handleCloseAllSymbol}
          handleCloseProfitableSpeed={handleCloseProfitableSpeed}
          handleCloseLosingSpeed={handleCloseLosingSpeed}
          onClosePosition={onClosePosition} onHalfPosition={onHalfPosition}
          clsPct={clsPct} clsOk={clsOk} clsErr={clsErr} clsWarn={clsWarn} clsMuted={clsMuted}
        />
      </div>
      </>, document.body)}
    </>
  )
}

// ── Inner Panel Content ──────────────────────────────────────────────────────
function PanelContent({
  tab, setTab, activeTrail, onDragStart, isMobile, onClose,
  buyPositions, sellPositions, totalVolume, netPnL, allNetPnL,
  positions, allPositions,
  tickData,
  selectedSymbol, symbols, symbolDropdownOpen, setSymbolDropdownOpen, setSelectedSymbol,
  loading,
  hasPositions, hasBuy, hasSell, hasProfitable, hasLosing, canSetBE,
  handleBE, handleTrail, handleClosePercent, handleCloseAndBE,
  handleCloseBuy, handleCloseSell, handleCloseAllSymbol,
  handleCloseProfitableSpeed, handleCloseLosingSpeed,
  onClosePosition, onHalfPosition,
  clsPct, clsOk, clsErr, clsWarn, clsMuted,
}: {
  tab: 'trade' | 'live'; setTab: (t: 'trade' | 'live') => void
  activeTrail: string | null
  onDragStart: ((e: React.MouseEvent) => void) | undefined
  isMobile: boolean; onClose: () => void
  buyPositions: Position[]; sellPositions: Position[]
  totalVolume: number; netPnL: number; allNetPnL: number
  positions: Position[]; allPositions: Position[]
  tickData: TickData | null
  selectedSymbol: string; symbols: string[]
  symbolDropdownOpen: boolean; setSymbolDropdownOpen: (v: boolean) => void
  setSelectedSymbol: (s: string) => void
  loading: boolean
  hasPositions: boolean; hasBuy: boolean; hasSell: boolean
  hasProfitable: boolean; hasLosing: boolean; canSetBE: boolean
  handleBE: (offset: number) => void; handleTrail: (key: string) => void
  handleClosePercent: (pct: number) => void; handleCloseAndBE: (pct: number) => void
  handleCloseBuy: () => void; handleCloseSell: () => void
  handleCloseAllSymbol: () => void
  handleCloseProfitableSpeed: () => void; handleCloseLosingSpeed: () => void
  onClosePosition: (ticket: number) => void; onHalfPosition: (ticket: number) => void
  clsPct: string; clsOk: string; clsErr: string; clsWarn: string; clsMuted: string
}) {
  const posCount = allPositions.length
  return (
    <>
      {/* ── Drag Handle / Mobile Header ──────────────────────────────── */}
      <div
        onMouseDown={onDragStart}
        className={cn(
          "flex items-center gap-2 px-3 py-2 border-b border-border bg-card/90 select-none",
          !isMobile && "cursor-grab active:cursor-grabbing"
        )}
      >
        {!isMobile && (
          <div className="flex flex-col gap-0.5 opacity-30">
            <div className="flex gap-0.5">
              <span className="w-1 h-1 rounded-full bg-muted-foreground" />
              <span className="w-1 h-1 rounded-full bg-muted-foreground" />
            </div>
            <div className="flex gap-0.5">
              <span className="w-1 h-1 rounded-full bg-muted-foreground" />
              <span className="w-1 h-1 rounded-full bg-muted-foreground" />
            </div>
          </div>
        )}
        <span className={cn("tech-label flex-1", isMobile && "text-sm")}>⚡ Nexal</span>
        {isMobile && (
          <span className="font-mono text-[10px] text-muted-foreground mr-1">{selectedSymbol === 'ALL' ? 'ALL' : selectedSymbol}</span>
        )}
        {/* Close button - always visible on mobile, hidden on desktop */}
        <button
          type="button"
          className={cn(
            "rounded-md flex items-center justify-center transition-colors",
            isMobile
              ? "h-8 w-8 bg-muted/20 text-muted-foreground hover:bg-muted/40"
              : "md:hidden h-6 w-6 bg-muted/50 text-muted-foreground"
          )}
          onClick={onClose} aria-label="Close panel"
        >
          <X className={isMobile ? "h-4 w-4" : "h-3.5 w-3.5"} />
        </button>
      </div>

      {/* ── Tab Strip ────────────────────────────────────────────────── */}
      <div className={cn("flex border-b border-border bg-card/50 shrink-0", isMobile && "py-0.5")}>
        {(['trade', 'live'] as const).map(t => (
          <button key={t} type="button" onClick={() => setTab(t)}
            className={cn(
              "flex-1 tech-label text-center border-b-2 transition-colors",
              isMobile ? "py-3 text-sm font-bold" : "py-1.5",
              tab === t ? "text-primary border-primary" : "text-muted-foreground border-transparent hover:text-foreground"
            )}
          >{t === 'trade' ? 'Trade' : 'Live'}</button>
        ))}
      </div>

      {/* ── Tab Content ──────────────────────────────────────────────── */}
      {tab === 'trade' ? (
        <TradeTab
          isMobile={isMobile}
          buyPositions={buyPositions} sellPositions={sellPositions}
          totalVolume={totalVolume} tickData={tickData}
          selectedSymbol={selectedSymbol} symbols={symbols}
          symbolDropdownOpen={symbolDropdownOpen}
          setSymbolDropdownOpen={setSymbolDropdownOpen}
          setSelectedSymbol={setSelectedSymbol}
          activeTrail={activeTrail} loading={loading}
          hasPositions={hasPositions} hasBuy={hasBuy} hasSell={hasSell}
          hasProfitable={hasProfitable} hasLosing={hasLosing} canSetBE={canSetBE}
          handleBE={handleBE} handleTrail={handleTrail}
          handleClosePercent={handleClosePercent} handleCloseAndBE={handleCloseAndBE}
          handleCloseBuy={handleCloseBuy} handleCloseSell={handleCloseSell}
          handleCloseAllSymbol={handleCloseAllSymbol}
          handleCloseProfitableSpeed={handleCloseProfitableSpeed}
          handleCloseLosingSpeed={handleCloseLosingSpeed}
          clsPct={clsPct} clsOk={clsOk} clsErr={clsErr} clsWarn={clsWarn} clsMuted={clsMuted}
        />
      ) : (
        <LiveTab
          positions={positions} allPositions={allPositions} selectedSymbol={selectedSymbol}
          onClosePosition={onClosePosition} onHalfPosition={onHalfPosition}
        />
      )}

      {/* ── Status Bar ───────────────────────────────────────────────── */}
      <div className={cn(
        "flex items-center justify-between px-3 border-t border-border bg-card/50 shrink-0",
        isMobile ? "py-2.5" : "py-1.5"
      )}>
        <div className="flex items-center gap-1.5">
          <span className={cn(
            "rounded-full",
            isMobile ? "w-2 h-2" : "w-1.5 h-1.5",
            positions.length > 0 ? "bg-success animate-pulse" : "bg-muted-foreground/30"
          )} />
          <span className={cn("font-mono text-muted-foreground", isMobile ? "text-[10px]" : "text-[8.5px]")}>
            {posCount} pos{posCount !== 1 ? 's' : ''}
            {selectedSymbol !== 'ALL' && ` • ${selectedSymbol}`}
          </span>
        </div>
        <span className={cn(
          "font-mono font-bold tabular-nums",
          isMobile ? "text-[11px]" : "text-[9px]",
          allNetPnL >= 0 ? "text-success" : "text-destructive"
        )}>{allNetPnL >= 0 ? '+' : ''}{formatCurrency(allNetPnL)}</span>
      </div>
    </>
  )
}

// ── Trade Tab ────────────────────────────────────────────────────────────────
function TradeTab({
  isMobile,
  buyPositions, sellPositions, totalVolume,
  tickData, selectedSymbol, symbols, symbolDropdownOpen, setSymbolDropdownOpen, setSelectedSymbol,
  activeTrail, loading,
  hasPositions, hasBuy, hasSell, hasProfitable, hasLosing, canSetBE,
  handleBE, handleTrail, handleClosePercent, handleCloseAndBE,
  handleCloseBuy, handleCloseSell, handleCloseAllSymbol,
  handleCloseProfitableSpeed, handleCloseLosingSpeed,
  clsPct, clsOk, clsErr, clsWarn, clsMuted,
}: {
  isMobile: boolean
  buyPositions: Position[]; sellPositions: Position[]
  totalVolume: number; tickData: TickData | null
  selectedSymbol: string; symbols: string[]
  symbolDropdownOpen: boolean; setSymbolDropdownOpen: (v: boolean) => void
  setSelectedSymbol: (s: string) => void
  activeTrail: string | null; loading: boolean
  hasPositions: boolean; hasBuy: boolean; hasSell: boolean
  hasProfitable: boolean; hasLosing: boolean; canSetBE: boolean
  handleBE: (offset: number) => void; handleTrail: (key: string) => void
  handleClosePercent: (pct: number) => void; handleCloseAndBE: (pct: number) => void
  handleCloseBuy: () => void; handleCloseSell: () => void
  handleCloseAllSymbol: () => void
  handleCloseProfitableSpeed: () => void; handleCloseLosingSpeed: () => void
  clsPct: string; clsOk: string; clsErr: string; clsWarn: string; clsMuted: string
}) {
  const dropdownRef = useRef<HTMLDivElement>(null)
  const m = isMobile

  useEffect(() => {
    if (!symbolDropdownOpen) return
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setSymbolDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [symbolDropdownOpen, setSymbolDropdownOpen])

  const displayBid = tickData?.bid
  const displayAsk = tickData?.ask

  const beBtnCls = (enabled: boolean) => cn(
    "rounded-md border font-mono font-bold transition-colors",
    m ? "text-[10px] py-2.5" : "text-[8px] py-1.5",
    enabled
      ? "border-border bg-card text-muted-foreground hover:border-primary hover:text-primary"
      : "border-border bg-card text-muted-foreground opacity-40 cursor-not-allowed"
  )

  const btn = (enabled: boolean, active: string) => cn(
    "rounded-md border font-mono font-bold transition-colors",
    m ? "text-[10px] py-2.5" : "text-[9px] py-1.5",
    enabled ? active : clsMuted
  )

  return (
    <div className={cn("flex flex-col", m && "flex-1 min-h-0")}>
      {/* ── Non-scrollable header: Symbol Selector + Price + Lot ────── */}
      <div className="flex-shrink-0">
        <div className={cn("relative border-b border-border bg-muted/10", m ? "px-4 py-3" : "px-3 py-2")} ref={dropdownRef}>
          <button
            type="button" onClick={() => setSymbolDropdownOpen(!symbolDropdownOpen)}
            disabled={loading}
            className={cn(
              "w-full flex items-center justify-between rounded-md border border-border bg-card text-foreground hover:border-primary/50 transition-colors",
              m ? "px-3 py-2.5 text-xs font-bold" : "px-2 py-1 text-[10px] font-mono font-bold"
            )}
          >
            <span>{selectedSymbol === 'ALL' ? 'ALL SYMBOLS' : selectedSymbol}</span>
            <ChevronDown className={cn("ml-1 transition-transform", m ? "h-4 w-4" : "h-3 w-3", symbolDropdownOpen && "rotate-180")} />
          </button>
          {symbolDropdownOpen && (
            <div className={cn(
              "absolute left-3 right-3 top-full mt-1 z-50 overflow-y-auto rounded-md border border-border bg-card shadow-xl no-scrollbar",
              m ? "max-h-[240px]" : "max-h-[160px]"
            )}>
              <button
                type="button"
                onMouseDown={(e) => { e.preventDefault(); e.stopPropagation(); setSelectedSymbol('ALL'); setSymbolDropdownOpen(false) }}
                className={cn(
                  "w-full text-left transition-colors hover:bg-muted",
                  m ? "px-3 py-2.5 text-xs font-bold" : "px-2 py-1.5 text-[10px] font-mono font-bold",
                  selectedSymbol === 'ALL' ? "text-primary bg-primary/5" : "text-muted-foreground")}
              >ALL SYMBOLS</button>
              {symbols.map(sym => (
                <button key={sym} type="button"
                  onMouseDown={(e) => { e.preventDefault(); e.stopPropagation(); setSelectedSymbol(sym); setSymbolDropdownOpen(false) }}
                  className={cn(
                    "w-full text-left transition-colors hover:bg-muted",
                    m ? "px-3 py-2.5 text-xs font-bold" : "px-2 py-1.5 text-[10px] font-mono font-bold",
                    selectedSymbol === sym ? "text-primary bg-primary/5" : "text-muted-foreground")}
                >{sym}</button>
              ))}
            </div>
          )}
        </div>

        {/* ── Price Row (Live Bid/Ask) ─────────────────────────────── */}
        <div className="grid grid-cols-2 border-b border-border">
          <div className={cn("bg-success/5 border-r border-border text-center", m ? "p-2.5" : "p-2")}>
            <p className={cn("text-success mb-0.5", m ? "text-[11px] font-bold uppercase tracking-wider" : "tech-label")}>Buy (Bid)</p>
            <p className={cn("font-mono font-bold text-success tabular-nums", m ? "text-lg" : "text-sm")}>
              {displayBid != null ? displayBid.toFixed(5) : '—'}
            </p>
          </div>
          <div className={cn("bg-destructive/5 text-center", m ? "p-2.5" : "p-2")}>
            <p className={cn("text-destructive mb-0.5", m ? "text-[11px] font-bold uppercase tracking-wider" : "tech-label")}>Sell (Ask)</p>
            <p className={cn("font-mono font-bold text-destructive tabular-nums", m ? "text-lg" : "text-sm")}>
              {displayAsk != null ? displayAsk.toFixed(5) : '—'}
            </p>
          </div>
        </div>

        {/* ── Lot Display Row ──────────────────────────────────────── */}
        <div className={cn("flex items-center justify-between border-b border-border bg-muted/10", m ? "px-4 py-3" : "px-3 py-2")}>
          <span className={cn("tech-label", m && "text-sm font-bold")}>Lot</span>
          <span className={cn("font-mono font-bold text-foreground tabular-nums", m ? "text-base" : "text-xs")}>{totalVolume.toFixed(2)}</span>
        </div>
      </div>

      {/* ── Scrollable action area (mobile only) ────────────────────── */}
      <div className={cn(m && "flex-1 min-h-0 overflow-y-auto overscroll-contain no-scrollbar")}>
        {/* ── BE & SECURE ──────────────────────────────────────────── */}
        <div className={m ? "px-4 pt-3 pb-1" : "px-3 pt-2 pb-0.5"}><span className={cn("tech-label", m && "text-sm font-bold")}>BE &amp; SECURE</span></div>
        <div className={cn("grid grid-cols-6 bg-muted/20", m ? "gap-1.5 p-3" : "gap-1 p-2")}>
          {BE_PRESETS.map(v => (
            <button key={v} type="button" disabled={loading || !canSetBE}
              onClick={() => canSetBE && !loading && handleBE(v)}
              className={beBtnCls(canSetBE && !loading)}
              title={canSetBE ? `Set breakeven + $${v}` : 'No positions in profit — BE not possible'}
            >+${v}</button>
          ))}
        </div>

        {/* ── TRAILING ─────────────────────────────────────────────── */}
        <div className={m ? "px-4 pt-3 pb-1" : "px-3 pt-2 pb-0.5"}><span className={cn("tech-label", m && "text-sm font-bold")}>TRAILING</span></div>
        <div className={cn("grid grid-cols-3 bg-muted/20", m ? "gap-2 p-3" : "gap-1.5 p-2")}>
          {TRAILS.map(t => (
            <button key={t.key} type="button" disabled={loading || !hasPositions}
              onClick={() => hasPositions && !loading && handleTrail(t.key)}
              className={cn(
                "rounded-md border font-mono font-bold uppercase tracking-wide transition-colors",
                m ? "text-[10px] py-2.5" : "text-[9px] py-1.5",
                !hasPositions ? clsMuted : activeTrail === t.key
                  ? "bg-primary/10 border-primary/50 text-primary"
                  : "border-border bg-card text-muted-foreground hover:border-primary/50 hover:text-primary"
              )}
            >{t.label}</button>
          ))}
        </div>

        {/* ── CLOSE ────────────────────────────────────────────────── */}
        <div className={m ? "px-4 pt-3 pb-1" : "px-3 pt-2 pb-0.5"}><span className={cn("tech-label", m && "text-sm font-bold")}>CLOSE</span></div>
        <div className={cn("grid grid-cols-3 bg-muted/20", m ? "gap-2 p-3" : "gap-1.5 p-2")}>
          <button type="button" disabled={loading || !hasPositions}
            onClick={() => hasPositions && !loading && handleClosePercent(0.25)}
            className={btn(hasPositions && !loading, clsPct)}>25%</button>
          <button type="button" disabled={loading || !hasPositions}
            onClick={() => hasPositions && !loading && handleClosePercent(0.50)}
            className={btn(hasPositions && !loading, clsPct)}>50%</button>
          <button type="button" disabled={loading || !hasPositions}
            onClick={() => hasPositions && !loading && handleClosePercent(0.75)}
            className={btn(hasPositions && !loading, clsPct)}>75%</button>
          <button type="button" disabled={loading || !hasBuy}
            onClick={() => hasBuy && !loading && handleCloseBuy()}
            className={btn(hasBuy && !loading, clsOk)}>Buy</button>
          <button type="button" disabled={loading || !hasSell}
            onClick={() => hasSell && !loading && handleCloseSell()}
            className={btn(hasSell && !loading, clsErr)}>Sell</button>
          <button type="button" disabled={loading || !hasPositions}
            onClick={() => hasPositions && !loading && handleCloseAllSymbol()}
            className={btn(hasPositions && !loading, clsWarn)}>All</button>
          <button type="button" disabled={loading || !hasProfitable}
            onClick={() => hasProfitable && !loading && handleCloseProfitableSpeed()}
            className={btn(hasProfitable && !loading, clsOk)}>Profit</button>
          <button type="button" disabled={loading || !hasLosing}
            onClick={() => hasLosing && !loading && handleCloseLosingSpeed()}
            className={btn(hasLosing && !loading, clsErr)}>Loss</button>
          <button type="button" disabled={loading || !hasPositions}
            onClick={() => hasPositions && !loading && handleCloseAndBE(0.50)}
            className={btn(hasPositions && !loading, clsWarn)}>50%+BE</button>
        </div>
      </div>
    </div>
  )
}

// ── Live Tab ─────────────────────────────────────────────────────────────────
function LiveTab({
  positions, allPositions, selectedSymbol,
  onClosePosition, onHalfPosition,
}: {
  positions: Position[]; allPositions: Position[]; selectedSymbol: string
  onClosePosition: (ticket: number) => void
  onHalfPosition: (ticket: number) => void
}) {
  if (positions.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center py-10">
        <span className="tech-label text-center">
          {allPositions.length === 0 ? 'No open positions' : `No positions for ${selectedSymbol}`}
        </span>
      </div>
    )
  }
  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="px-3 py-2 border-b border-border bg-muted/20">
        <span className="font-mono text-[8.5px] font-bold text-muted-foreground uppercase tracking-wider">
          {positions.length} position{positions.length !== 1 ? 's' : ''}
          {selectedSymbol !== 'ALL' && ` • ${selectedSymbol}`}
        </span>
      </div>
      <div className="flex-1 overflow-y-auto no-scrollbar">
        {positions.map(pos => {
          const pnl = netPnl(pos)
          const isProfit = pnl >= 0
          return (
            <div key={pos.ticket}
              className={cn("flex items-center gap-2 px-3 py-2 border-b border-border last:border-0",
                isProfit ? "bg-success/[0.03]" : "bg-destructive/[0.03]")}>
              <span className={cn("font-mono text-[9px] font-bold w-14 shrink-0",
                isProfit ? "text-success" : "text-destructive")}>{pos.symbol}</span>
              <span className="font-mono text-[8.5px] text-muted-foreground flex-1">
                {pos.type === 0 ? 'BUY' : 'SELL'} {pos.volume.toFixed(2)}
              </span>
              <span className={cn("font-mono text-[10px] font-bold tabular-nums w-16 text-right shrink-0",
                isProfit ? "text-success" : "text-destructive")}>
                {pnl >= 0 ? '+' : ''}{formatCurrency(pnl)}
              </span>
              <div className="flex gap-1 shrink-0">
                <button type="button" onClick={() => onHalfPosition(pos.ticket)}
                  className="h-6 w-6 rounded-md border border-border bg-card text-muted-foreground
                             hover:border-gold hover:text-gold font-mono text-[9px] font-bold
                             transition-colors flex items-center justify-center" title="Close 50%">½</button>
                <button type="button" onClick={() => onClosePosition(pos.ticket)}
                  className="h-6 w-6 rounded-md border border-destructive/30 bg-destructive/5 text-destructive
                             hover:bg-destructive/10 font-mono text-[9px] font-bold transition-colors
                             flex items-center justify-center" title="Close position">✕</button>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}


