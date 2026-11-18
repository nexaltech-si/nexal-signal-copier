'use client'

/**
 * Telegram-style chat wallpaper — a static multi-colour gradient with an optional
 * tiled pattern overlay masked on top.
 *
 * The gradient maths (getGradientImageData + the 8 base positions) are ported and
 * trimmed from twallpaper (MIT, https://github.com/crashmax-dev/twallpaper). We
 * keep ONLY the static render — all of twallpaper's animation / scroll / tails /
 * frame-buffer machinery is dropped, since we render the gradient once.
 */

import { useEffect, useRef } from 'react'

// ─── Presets ──────────────────────────────────────────────────────────────────
// Each preset is 1–4 hex colours for the gradient. `pattern` is optional; when
// set it's tiled and masked over the gradient. Add your own freely.

export interface WallpaperPreset {
  id: string
  name: string
  colors: string[]
  pattern?: string        // public path to a tileable SVG/PNG, or omit for none
}

export const WALLPAPER_PRESETS: WallpaperPreset[] = [
  { id: 'day',    name: 'Day',    colors: ['#dbddbb', '#6ba587', '#d5d88d', '#88b884'], pattern: '/tg-patterns/animals.svg' },
  { id: 'dusk',   name: 'Dusk',   colors: ['#fec496', '#dd6cb9', '#962fbf', '#4f5bd5'], pattern: '/tg-patterns/animals.svg' },
  { id: 'ocean',  name: 'Ocean',  colors: ['#8dc7ff', '#5b9bd8', '#a0d3ff', '#6db3f2'], pattern: '/tg-patterns/animals.svg' },
  { id: 'slate',  name: 'Slate',  colors: ['#3a4a5a', '#2b3a4a', '#4a5a6a', '#33434f'], pattern: '/tg-patterns/animals.svg' },
  { id: 'night',  name: 'Night',  colors: ['#0e1a2e', '#14233b', '#1b2d4a', '#0f1c31'], pattern: '/tg-patterns/animals.svg' },
  { id: 'plain',  name: 'Plain',  colors: ['#c6d3c1', '#a9c0a4', '#c9d6c0', '#b3c8ad'] },
]

export const DEFAULT_PRESET_ID = 'day'
export const WALLPAPER_STORAGE_KEY = 'tg-wallpaper-preset'

// ─── Gradient maths (ported from twallpaper) ────────────────────────────────────

interface Pos { x: number; y: number }

// The 8 anchor points the gradient blobs live at; getPositions picks 4.
const BASE_POSITIONS: Pos[] = [
  { x: 0.8, y: 0.1 }, { x: 0.6, y: 0.2 }, { x: 0.35, y: 0.25 }, { x: 0.25, y: 0.6 },
  { x: 0.2, y: 0.9 }, { x: 0.4, y: 0.8 }, { x: 0.65, y: 0.75 }, { x: 0.75, y: 0.4 },
]

function hexToRgb(hex: string): { r: number; g: number; b: number } | null {
  let h = hex
  if (h.length === 4) h = `#${h[1]}${h[1]}${h[2]}${h[2]}${h[3]}${h[3]}`
  const m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(h)
  return m ? { r: parseInt(m[1], 16), g: parseInt(m[2], 16), b: parseInt(m[3], 16) } : null
}

// Every other base position → the 4 gradient colour anchors.
function pickPositions(): Pos[] {
  const out: Pos[] = []
  for (let i = 0; i < BASE_POSITIONS.length; i += 2) out.push(BASE_POSITIONS[i])
  return out
}

// The Telegram gradient blend, evaluated on a small offscreen buffer then
// upscaled by the browser (it's very low-frequency, so 64×64 is plenty).
function renderGradient(ctx: CanvasRenderingContext2D, w: number, h: number, colors: string[]) {
  const rgb = colors.map(hexToRgb).filter(Boolean).slice(0, 4) as { r: number; g: number; b: number }[]
  if (!rgb.length) return
  const positions = pickPositions()
  const id = ctx.createImageData(w, h)
  const px = id.data
  let offset = 0

  for (let y = 0; y < h; y++) {
    const dpY = y / h
    const cdY = dpY - 0.5
    const cdY2 = cdY * cdY
    for (let x = 0; x < w; x++) {
      const dpX = x / w
      const cdX = dpX - 0.5
      const centerDistance = Math.sqrt(cdX * cdX + cdY2)
      const swirl = 0.35 * centerDistance
      const theta = swirl * swirl * 0.8 * 8
      const sin = Math.sin(theta)
      const cos = Math.cos(theta)
      const pixelX = Math.max(0, Math.min(1, 0.5 + cdX * cos - cdY * sin))
      const pixelY = Math.max(0, Math.min(1, 0.5 + cdX * sin + cdY * cos))

      let sum = 0, r = 0, g = 0, b = 0
      for (let i = 0; i < rgb.length; i++) {
        const dx = pixelX - positions[i].x
        const dy = pixelY - positions[i].y
        let d = Math.max(0, 0.9 - Math.sqrt(dx * dx + dy * dy))
        d = d * d * d * d
        sum += d
        r += (d * rgb[i].r) / 255
        g += (d * rgb[i].g) / 255
        b += (d * rgb[i].b) / 255
      }
      px[offset++] = (r / sum) * 255
      px[offset++] = (g / sum) * 255
      px[offset++] = (b / sum) * 255
      px[offset++] = 0xff
    }
  }
  ctx.putImageData(id, 0, 0)
}

// ─── Component ──────────────────────────────────────────────────────────────────

const BUF = 64  // offscreen gradient resolution (upscaled via CSS)

export default function TgWallpaper({ preset, className }: { preset: WallpaperPreset; className?: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    renderGradient(ctx, BUF, BUF, preset.colors)
  }, [preset.colors])

  return (
    <div className={className} aria-hidden>
      {/* Gradient: tiny buffer stretched to fill; image-rendering keeps it smooth */}
      <canvas
        ref={canvasRef}
        width={BUF}
        height={BUF}
        className="absolute inset-0 h-full w-full"
        style={{ imageRendering: 'auto' }}
      />
      {/* Pattern overlay, masked and tiled over the gradient */}
      {preset.pattern && (
        <div
          className="absolute inset-0 mix-blend-soft-light dark:mix-blend-overlay"
          style={{
            backgroundImage: `url(${preset.pattern})`,
            backgroundRepeat: 'repeat',
            backgroundSize: '420px auto',
            backgroundPosition: 'center',
            opacity: 0.5,
          }}
        />
      )}
    </div>
  )
}
