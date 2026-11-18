'use client'

import { useState } from 'react'
import { Monitor, Maximize2, Minimize2, RefreshCw, AlertCircle } from 'lucide-react'

export default function MT5TerminalPage() {
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [frameKey, setFrameKey] = useState(0)
  const [error, setError] = useState(false)

  const reload = () => {
    setError(false)
    setFrameKey(k => k + 1)
  }

  const toggleFullscreen = () => {
    const el = document.getElementById('vnc-container')
    if (!el) return
    if (!document.fullscreenElement) {
      el.requestFullscreen().then(() => setIsFullscreen(true)).catch(() => {})
    } else {
      document.exitFullscreen().then(() => setIsFullscreen(false)).catch(() => {})
    }
  }

  return (
    <div className="fixed inset-x-0 top-[80px] bottom-[86px] z-10 md:absolute md:inset-0 md:flex md:flex-col md:px-4 md:py-6 md:gap-3">
      {/* Header — desktop only */}
      <div className="shrink-0 hidden md:flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold flex items-center gap-2">
            <Monitor className="h-5 w-5 text-primary" />
            MT5 Terminal
          </h1>
          <p className="text-xs text-muted-foreground mt-0.5">
            Live desktop access via secure proxy · proxied through <code className="text-[10px] bg-muted px-1 py-0.5 rounded">/vnc-proxy</code>
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={reload}
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors px-2.5 py-1.5 rounded-md hover:bg-muted"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Reload
          </button>
          <button
            onClick={toggleFullscreen}
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors px-2.5 py-1.5 rounded-md hover:bg-muted"
          >
            {isFullscreen ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
            {isFullscreen ? 'Exit' : 'Fullscreen'}
          </button>
        </div>
      </div>

      {/* VNC iframe container */}
      <div
        id="vnc-container"
        className="h-full md:flex-1 md:min-h-0 rounded-xl overflow-hidden border border-border bg-black relative"
      >
        {error ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 text-muted-foreground">
            <AlertCircle className="h-10 w-10 text-destructive/60" />
            <div className="text-center">
              <p className="font-semibold text-sm">MT5 VNC unavailable</p>
              <p className="text-xs mt-1 max-w-xs">Make sure the MT5 container is running on the <code className="bg-muted px-1 rounded">mt5-net</code> network.</p>
            </div>
            <button
              onClick={reload}
              className="flex items-center gap-2 text-xs px-3 py-1.5 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Try again
            </button>
          </div>
        ) : (
          <iframe
            key={frameKey}
            src="/vnc-proxy/"
            className="w-full h-full border-0"
            title="MT5 Terminal"
            allowFullScreen
            onError={() => setError(true)}
          />
        )}
      </div>
    </div>
  )
}
