'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { createChart, IChartApi, ColorType, Time, ISeriesApi } from 'lightweight-charts';
import { Activity, AlertCircle, BarChart3, Maximize2, Minimize2, Filter, TrendingUp, TrendingDown, PlayCircle } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useChartReplay } from '@/hooks/useChartReplay';
import ChartReplayControls from '@/components/ChartReplayControls';

// Shape of one entry from the simulator live log / saved result trades array
export interface SimTrade {
  message_id: number;
  timestamp: string;           // ISO string
  intent?: string;
  extraction_method?: string;
  ai_symbol?: string;
  pattern_symbol?: string;
  ai_action?: string;
  pattern_action?: string;
  ai_order_type?: string;
  pattern_order_type?: string;
  ai_entry?: number;
  ai_sl?: number;
  ai_tp?: number[];
  ai_confidence?: number;
  brain_verdict?: string;      // APPROVE | REJECT | MODIFY
  extraction_error?: string;
  has_image?: boolean;
  is_reply?: boolean;
  original_message?: string;
}

interface OHLCData {
  time: Time;
  open: number;
  high: number;
  low: number;
  close: number;
}

interface SimulatorTimelineChartProps {
  trades: SimTrade[];
  height?: number;
}

// Only include OPEN signals that have enough data to show on chart
function getSignalTrades(trades: SimTrade[]) {
  return trades.filter(
    (t) =>
      t.intent === 'SIGNAL' &&
      (t.ai_action === 'OPEN' || t.ai_action === 'BUY' || t.ai_action === 'SELL') &&
      t.ai_entry != null &&
      (t.ai_symbol || t.pattern_symbol)
  );
}

// Direction comes from order_type (BUY/SELL), not ai_action (OPEN/CLOSE/MODIFY/PARTIAL_CLOSE).
// Falls back to comparing entry vs SL when order_type is missing: for a BUY, SL sits below entry.
export function isBuyTrade(t: SimTrade): boolean {
  const orderType = (t.ai_order_type || t.pattern_order_type || '').toUpperCase();
  if (orderType === 'BUY') return true;
  if (orderType === 'SELL') return false;
  if (t.ai_sl != null && t.ai_entry != null) return t.ai_sl < t.ai_entry;
  return true;
}

function markerColor(t: SimTrade): string {
  if (t.brain_verdict === 'REJECT') return '#94a3b8';   // grey = brain rejected
  if (t.extraction_error) return '#f59e0b';              // amber = extraction failed
  return isBuyTrade(t) ? '#22c55e' : '#ef4444';
}

function markerLabel(t: SimTrade): string {
  const entry = t.ai_entry;
  if (!entry) return '';
  const dec = entry < 10 ? 5 : entry < 100 ? 3 : 2;
  const entryStr = entry.toFixed(dec);
  const verdict = t.brain_verdict === 'REJECT' ? ' ✗' : t.brain_verdict === 'APPROVE' ? ' ✓' : '';
  return `${isBuyTrade(t) ? '▲' : '▼'} ${entryStr}${verdict}`;
}

export default function SimulatorTimelineChart({ trades, height = 400 }: SimulatorTimelineChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const isInitialRender = useRef(true);
  // Wrap the sections above and below the chart (header/replay controls, and
  // the signal list) so their combined measured height can be subtracted from
  // the viewport to size the chart with no leftover overflow.
  const chromeTopRef = useRef<HTMLDivElement>(null);
  const chromeBottomRef = useRef<HTMLDivElement>(null);

  const [ohlcData, setOhlcData] = useState<OHLCData[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [symbolFilter, setSymbolFilter] = useState('');
  const [selectedTrade, setSelectedTrade] = useState<SimTrade | null>(null);
  const [timeframe, setTimeframe] = useState('H1');
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [fullscreenHeight, setFullscreenHeight] = useState(height);
  const effectiveHeight = isFullscreen ? fullscreenHeight : height;

  // Esc key exits fullscreen; keep viewport height for the chart area in sync while fullscreen
  useEffect(() => {
    if (!isFullscreen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setIsFullscreen(false);
    };
    const OUTER_PADDING = 32; // p-4 top + bottom on the fullscreen wrapper
    const GAP_COUNT_PX = 24; // two space-y-3 (12px) gaps around the chart
    const updateHeight = () => {
      const topHeight = chromeTopRef.current?.getBoundingClientRect().height ?? 0;
      const bottomHeight = chromeBottomRef.current?.getBoundingClientRect().height ?? 0;
      setFullscreenHeight(
        Math.max(200, window.innerHeight - topHeight - bottomHeight - OUTER_PADDING - GAP_COUNT_PX)
      );
    };
    updateHeight();
    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('resize', updateHeight);
    // Chrome height depends on content (replay controls toggling, signal list
    // count, wrapping) — a ResizeObserver keeps the chart sized to exactly
    // fill the remaining viewport regardless of what caused the chrome to change.
    const chromeObserver = new ResizeObserver(updateHeight);
    if (chromeTopRef.current) chromeObserver.observe(chromeTopRef.current);
    if (chromeBottomRef.current) chromeObserver.observe(chromeBottomRef.current);
    // The app's actual scroll container is the <main> element (overflow-y-auto),
    // not document.body — freezing body alone leaves a second scrollbar behind
    // the fullscreen overlay.
    const scrollParent = document.querySelector('main');
    document.body.style.overflow = 'hidden';
    if (scrollParent) scrollParent.style.overflow = 'hidden';
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('resize', updateHeight);
      chromeObserver.disconnect();
      document.body.style.overflow = '';
      if (scrollParent) scrollParent.style.overflow = '';
    };
  }, [isFullscreen]);

  const toggleFullscreen = () => {
    setIsFullscreen((v) => {
      const next = !v;
      if (next) setFullscreenHeight(window.innerHeight - 220);
      return next;
    });
  };

  // Apply theme colors without rebuilding the chart
  useEffect(() => {
    const apply = () => {
      if (!chartRef.current) return;
      const dark = document.documentElement.classList.contains('dark');
      chartRef.current.applyOptions({
        layout: { background: { type: ColorType.Solid, color: dark ? '#0D1624' : '#ffffff' }, textColor: dark ? '#6B7A99' : '#64748b' },
        grid: { vertLines: { color: dark ? '#18243A' : '#f1f5f9' }, horzLines: { color: dark ? '#18243A' : '#f1f5f9' } },
        rightPriceScale: { borderColor: dark ? '#18243A' : '#e2e8f0' },
        timeScale: { borderColor: dark ? '#18243A' : '#e2e8f0' },
      });
    };
    const observer = new MutationObserver(apply);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, []);

  const signalTrades = getSignalTrades(trades);

  // Unique symbols that have signals
  const availableSymbols = Array.from(
    new Set(signalTrades.map((t) => (t.ai_symbol || t.pattern_symbol || '').toUpperCase()).filter(Boolean))
  ).sort();

  // Active symbol = filter if set, else most common
  const activeSymbol = symbolFilter ||
    (() => {
      const freq: Record<string, number> = {};
      signalTrades.forEach((t) => {
        const s = (t.ai_symbol || t.pattern_symbol || '').toUpperCase();
        if (s) freq[s] = (freq[s] || 0) + 1;
      });
      return Object.entries(freq).sort((a, b) => b[1] - a[1])[0]?.[0] || '';
    })();

  const relevantTrades = signalTrades.filter(
    (t) => (t.ai_symbol || t.pattern_symbol || '').toUpperCase() === activeSymbol
  );

  // Broker offset: MT5 candles are UTC+3
  const BROKER_OFFSET = 3 * 3600;

  // Nearest candle index to the selected trade's entry time (used as the replay start point)
  const replayStartIndex = (() => {
    if (!selectedTrade || ohlcData.length === 0) return ohlcData.length - 1;
    const sigTs = Math.floor(new Date(selectedTrade.timestamp).getTime() / 1000) + BROKER_OFFSET;
    let bestIdx = 0;
    let bestDiff = Infinity;
    ohlcData.forEach((d, i) => {
      const diff = Math.abs((d.time as number) - sigTs);
      if (diff < bestDiff) { bestDiff = diff; bestIdx = i; }
    });
    return bestIdx;
  })();

  const replay = useChartReplay({ totalBars: ohlcData.length, startIndex: replayStartIndex });
  const visibleOhlcData = replay.isReplaying ? ohlcData.slice(0, replay.revealedCount) : ohlcData;

  // Tracks the last selected trade id so we only auto-recenter the view when the
  // selection actually changes, not on every chart rebuild (which would wipe out
  // the user's manual zoom/pan).
  const lastSelectedIdRef = useRef<number | null>(null);
  // Preserves the user's manually-set visible range across chart rebuilds.
  const savedRangeRef = useRef<{ from: number; to: number } | null>(null);
  // Tracks whether replay was already active on the previous rebuild, so we only
  // snap to the latest bar once when replay starts — not on every bar tick.
  const wasReplayingRef = useRef(false);

  const fetchCandles = useCallback(async (sym: string, fromTs: number, toTs: number, tf: string) => {
    if (!sym) return;
    setIsLoading(true);
    setError(null);
    try {
      const start = new Date((fromTs - 86400) * 1000).toISOString();
      const end = new Date((toTs + 86400) * 1000).toISOString();
      const res = await fetch(`/api/candles?symbol=${sym}&timeframe=${tf}&start=${start}&end=${end}`);
      if (!res.ok) throw new Error(`Candle fetch failed: ${res.statusText}`);
      const data = await res.json();
      if (!Array.isArray(data) || data.length === 0) {
        setOhlcData([]);
        return;
      }
      const parsed: OHLCData[] = data
        .map((bar: { time: string; open: number; high: number; low: number; close: number }) => ({
          time: Math.floor(new Date(bar.time).getTime() / 1000) as Time,
          open: bar.open,
          high: bar.high,
          low: bar.low,
          close: bar.close,
        }))
        .sort((a: OHLCData, b: OHLCData) => (a.time as number) - (b.time as number));
      setOhlcData(parsed);
      isInitialRender.current = true;
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load chart');
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Reload candles when symbol, timeframe, or trade range changes
  useEffect(() => {
    if (!activeSymbol || relevantTrades.length === 0) {
      setOhlcData([]);
      return;
    }
    const timestamps = relevantTrades.map((t) => Math.floor(new Date(t.timestamp).getTime() / 1000));
    fetchCandles(activeSymbol, Math.min(...timestamps), Math.max(...timestamps), timeframe);
  }, [activeSymbol, relevantTrades.length, timeframe, fetchCandles]); // eslint-disable-line react-hooks/exhaustive-deps

  // Build / rebuild chart
  useEffect(() => {
    if (!chartContainerRef.current || visibleOhlcData.length === 0) return;

    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
      seriesRef.current = null;
    }

    const dark = document.documentElement.classList.contains('dark');
    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: dark ? '#0D1624' : '#ffffff' },
        textColor: dark ? '#6B7A99' : '#64748b',
      },
      width: chartContainerRef.current.clientWidth,
      height: effectiveHeight,
      grid: {
        vertLines: { color: dark ? '#18243A' : '#f1f5f9' },
        horzLines: { color: dark ? '#18243A' : '#f1f5f9' },
      },
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: dark ? '#18243A' : '#e2e8f0' },
      timeScale: { borderColor: dark ? '#18243A' : '#e2e8f0', timeVisible: true, secondsVisible: false },
    });

    const series = chart.addCandlestickSeries({
      upColor: '#24C87A', downColor: '#F23050',
      borderUpColor: '#24C87A', borderDownColor: '#F23050',
      wickUpColor: '#24C87A', wickDownColor: '#F23050',
    });

    series.setData(visibleOhlcData);

    // Plot each signal as a marker on the nearest H1 candle (only trades within the revealed window).
    // When a trade is selected, show only that trade's marker and hide the rest.
    const lastVisibleTs = visibleOhlcData[visibleOhlcData.length - 1].time as number;
    const revealedTrades = relevantTrades.filter(
      (t) => Math.floor(new Date(t.timestamp).getTime() / 1000) + BROKER_OFFSET <= lastVisibleTs &&
        (!selectedTrade || t.message_id === selectedTrade.message_id)
    );

    const markers = revealedTrades
      .map((t) => {
        const sigTs = Math.floor(new Date(t.timestamp).getTime() / 1000) + BROKER_OFFSET;
        const nearest = visibleOhlcData.reduce((prev, curr) =>
          Math.abs((curr.time as number) - sigTs) < Math.abs((prev.time as number) - sigTs) ? curr : prev
        );
        const isBuy = isBuyTrade(t);
        const isSelected = selectedTrade?.message_id === t.message_id;
        const entryTimeStr = new Date(t.timestamp).toLocaleString('en-GB', {
          day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
        });
        return {
          time: nearest.time,
          position: isBuy ? ('belowBar' as const) : ('aboveBar' as const),
          color: isSelected ? (isBuy ? '#16a34a' : '#dc2626') : markerColor(t),
          shape: isBuy ? ('arrowUp' as const) : ('arrowDown' as const),
          text: isSelected ? `${markerLabel(t)}  •  Entry ${entryTimeStr}` : markerLabel(t),
          size: 1,
        };
      })
      .sort((a, b) => (a.time as number) - (b.time as number));

    if (markers.length > 0) {
      series.setMarkers(markers);
    }

    // Price lines for selected trade
    if (selectedTrade) {
      const entry = selectedTrade.ai_entry;
      if (entry) {
        series.createPriceLine({ price: entry, color: '#3b82f6', lineWidth: 2, lineStyle: 0, axisLabelVisible: true, title: 'Entry' });
      }
      if (selectedTrade.ai_sl) {
        series.createPriceLine({ price: selectedTrade.ai_sl, color: '#ef4444', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'SL' });
      }
      (selectedTrade.ai_tp || []).forEach((tp, i) => {
        series.createPriceLine({ price: tp, color: '#22c55e', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: `TP${i + 1}` });
      });
    }

    const newlySelectedId = selectedTrade?.message_id ?? null;
    const selectionChanged = newlySelectedId !== lastSelectedIdRef.current;
    lastSelectedIdRef.current = newlySelectedId;

    const replayJustStarted = replay.isReplaying && !wasReplayingRef.current;
    wasReplayingRef.current = replay.isReplaying;

    // Subscribe before applying any programmatic range change so the resulting
    // range is captured immediately (keeps savedRangeRef in sync on this render).
    chart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (range) savedRangeRef.current = { from: range.from, to: range.to };
    });

    if (replay.isReplaying && replayJustStarted) {
      // Replay just started — the revealed window can be as small as 1-3 bars
      // (e.g. replaying from an early signal), so frame a fixed-width window
      // ending at the last revealed bar instead of scrollToRealTime(), which
      // targets the live edge and leaves a near-empty chart looking collapsed.
      const lastIdx = visibleOhlcData.length - 1;
      const windowSize = 40;
      chart.timeScale().setVisibleLogicalRange({ from: lastIdx - windowSize, to: lastIdx + 2 });
    } else if (replay.isReplaying && savedRangeRef.current) {
      // Mid-playback rebuild (bar tick) — keep the user's own zoom/pan untouched.
      chart.timeScale().setVisibleLogicalRange(savedRangeRef.current);
    } else if (replay.isReplaying) {
      chart.timeScale().scrollToRealTime();
    } else if (isInitialRender.current) {
      chart.timeScale().fitContent();
      isInitialRender.current = false;
    } else if (selectedTrade && selectionChanged) {
      // A new trade was just selected — center the view on its entry candle.
      const sigTs = Math.floor(new Date(selectedTrade.timestamp).getTime() / 1000) + BROKER_OFFSET;
      const nearest = visibleOhlcData.reduce((prev, curr) =>
        Math.abs((curr.time as number) - sigTs) < Math.abs((prev.time as number) - sigTs) ? curr : prev
      );
      const idx = visibleOhlcData.findIndex((d) => d.time === nearest.time);
      if (idx !== -1) {
        const half = 20;
        chart.timeScale().setVisibleLogicalRange({ from: idx - half, to: idx + half });
      }
    } else if (savedRangeRef.current) {
      // Not a new selection and not the initial render — restore the user's own zoom/pan.
      chart.timeScale().setVisibleLogicalRange(savedRangeRef.current);
    }

    chartRef.current = chart;
    seriesRef.current = series;

    // ResizeObserver catches any container size change (window resize, fullscreen
    // toggle, sidebar collapse, etc.) — a plain window `resize` listener misses
    // layout-only changes like entering/exiting fullscreen.
    const resizeObserver = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry && chartRef.current) {
        chartRef.current.applyOptions({ width: entry.contentRect.width });
      }
    });
    resizeObserver.observe(chartContainerRef.current);

    return () => {
      resizeObserver.disconnect();
      chartRef.current?.remove();
      chartRef.current = null;
    };
  }, [visibleOhlcData, relevantTrades, selectedTrade, effectiveHeight, replay.isReplaying]);

  if (signalTrades.length === 0) {
    return (
      <div className="flex items-center justify-center bg-muted/20 rounded-lg border border-border" style={{ height: 180 }}>
        <div className="text-center text-muted-foreground">
          <BarChart3 className="h-8 w-8 mx-auto mb-2 opacity-30" />
          <p className="text-sm">No extracted signals to chart yet</p>
          <p className="text-xs opacity-60 mt-1">Run a simulation — signals with entry prices will appear here</p>
        </div>
      </div>
    );
  }

  // Stats
  const approved = relevantTrades.filter((t) => t.brain_verdict === 'APPROVE').length;
  const rejected = relevantTrades.filter((t) => t.brain_verdict === 'REJECT').length;
  const noVerdict = relevantTrades.filter((t) => !t.brain_verdict).length;
  const withErrors = relevantTrades.filter((t) => t.extraction_error).length;
  const buys = relevantTrades.filter((t) => isBuyTrade(t)).length;
  const sells = relevantTrades.length - buys;

  const rootEl = (
    <div
      className={
        isFullscreen
          ? 'space-y-3 fixed inset-0 z-50 overflow-y-auto bg-background p-4'
          : 'space-y-3'
      }
    >
      <div ref={chromeTopRef} className="space-y-3">
      {/* Header row */}
      <div className="flex items-center gap-3 flex-wrap">
        {availableSymbols.length > 1 && (
          <div className="flex items-center gap-1.5">
            <Filter className="h-3 w-3 text-muted-foreground" />
            <select
              value={symbolFilter}
              onChange={(e) => { setSymbolFilter(e.target.value); isInitialRender.current = true; }}
              className="text-xs px-2 py-1 border rounded bg-background text-foreground h-7"
            >
              {availableSymbols.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
        )}

        {/* Timeframe switcher */}
        <div className="flex items-center gap-0.5 border border-border rounded-md p-0.5">
          {['M5', 'M15', 'H1', 'H4', 'D1'].map((tf) => (
            <button
              key={tf}
              onClick={() => { setTimeframe(tf); isInitialRender.current = true; }}
              className={`text-[10px] font-semibold px-2 py-0.5 rounded transition-colors ${
                timeframe === tf
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:text-foreground hover:bg-muted'
              }`}
            >
              {tf}
            </button>
          ))}
        </div>

        {/* mini stats */}
        <div className="flex items-center gap-2 text-xs flex-wrap">
          <span className="text-muted-foreground">{relevantTrades.length} signals</span>
          <span className="flex items-center gap-0.5 text-green-500"><TrendingUp className="h-3 w-3" />{buys}</span>
          <span className="flex items-center gap-0.5 text-red-500"><TrendingDown className="h-3 w-3" />{sells}</span>
          {approved > 0 && <Badge className="text-[10px] h-4 bg-green-500/10 text-green-400 border-green-500/20">✓ {approved} approved</Badge>}
          {rejected > 0 && <Badge className="text-[10px] h-4 bg-red-500/10 text-red-400 border-red-500/20">✗ {rejected} rejected</Badge>}
          {noVerdict > 0 && !approved && !rejected && <Badge variant="outline" className="text-[10px] h-4">{noVerdict} signals</Badge>}
          {withErrors > 0 && <Badge className="text-[10px] h-4 bg-yellow-500/10 text-yellow-400 border-yellow-500/20">⚠ {withErrors} errors</Badge>}
        </div>

        {/* legend */}
        <div className="ml-auto flex items-center gap-3 text-[10px] text-muted-foreground flex-wrap">
          {[
            { color: '#22c55e', label: 'BUY' },
            { color: '#ef4444', label: 'SELL' },
            { color: '#94a3b8', label: 'Brain rejected' },
            { color: '#f59e0b', label: 'Error' },
          ].map(({ color, label }) => (
            <span key={label} className="flex items-center gap-1">
              <span className="inline-block w-2 h-2 rounded-full" style={{ backgroundColor: color }} />
              {label}
            </span>
          ))}
          <Button
            variant="outline"
            size="sm"
            className="h-6 px-2"
            title="Fit all"
            onClick={() => { chartRef.current?.timeScale().fitContent(); }}
          >
            <Maximize2 className="h-3 w-3" />
          </Button>
          <Button
            variant={replay.isReplaying ? 'default' : 'outline'}
            size="sm"
            className="h-6 px-2 gap-1"
            title={selectedTrade ? 'Replay chart from this signal' : 'Select a signal to replay from'}
            disabled={!selectedTrade || replay.isReplaying}
            onClick={() => replay.startReplay()}
          >
            <PlayCircle className="h-3 w-3" />
            <span className="text-[10px]">Replay</span>
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="h-6 px-2"
            title={isFullscreen ? 'Exit fullscreen (Esc)' : 'Fullscreen'}
            onClick={toggleFullscreen}
          >
            {isFullscreen ? <Minimize2 className="h-3 w-3" /> : <Maximize2 className="h-3 w-3" />}
          </Button>
        </div>
      </div>

      {/* Replay controls */}
      {replay.isReplaying && (
        <ChartReplayControls
          isPlaying={replay.isPlaying}
          speed={replay.speed}
          revealedCount={replay.revealedCount}
          totalBars={ohlcData.length}
          isAtEnd={replay.isAtEnd}
          onPlay={replay.play}
          onPause={replay.pause}
          onStepForward={replay.stepForward}
          onStepBackward={replay.stepBackward}
          onSpeedChange={replay.setSpeed}
          onSeek={replay.seekTo}
          onExit={replay.stopReplay}
        />
      )}
      </div>

      {/* Chart area */}
      {isLoading ? (
        <div className="flex items-center justify-center bg-muted/20 rounded-lg" style={{ height: effectiveHeight }}>
          <Activity className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : error ? (
        <div className="flex items-center justify-center bg-muted/20 rounded-lg gap-2" style={{ height: 120 }}>
          <AlertCircle className="h-4 w-4 text-yellow-400" />
          <span className="text-xs text-muted-foreground">{error} — chart needs MT5 REST connection</span>
        </div>
      ) : ohlcData.length > 0 ? (
        <div ref={chartContainerRef} className="rounded-lg overflow-hidden" style={{ height: effectiveHeight }} />
      ) : (
        <div className="flex items-center justify-center bg-muted/20 rounded-lg" style={{ height: 120 }}>
          <span className="text-xs text-muted-foreground">No candle data for {activeSymbol}</span>
        </div>
      )}

      {/* Signal list */}
      {relevantTrades.length > 0 && (
        <div ref={chromeBottomRef} className="space-y-0.5 max-h-52 overflow-y-auto pr-1">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-1.5">
            Extracted signals — {activeSymbol} ({relevantTrades.length})
          </p>
          {[...relevantTrades].reverse().map((t) => {
            const isBuy = isBuyTrade(t);
            const isSelected = selectedTrade?.message_id === t.message_id;
            const color = markerColor(t);
            const entry = t.ai_entry;
            const dec = entry ? (entry < 10 ? 5 : entry < 100 ? 3 : 2) : 5;

            return (
              <div
                key={t.message_id}
                onClick={() => setSelectedTrade(isSelected ? null : t)}
                className={`flex items-center gap-2 px-2.5 py-1.5 rounded-lg cursor-pointer text-[11px] transition-colors ${
                  isSelected
                    ? 'bg-primary/10 border border-primary/30'
                    : 'hover:bg-muted/60 border border-transparent'
                }`}
              >
                <span className="inline-block w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: color }} />
                <span className="text-muted-foreground flex-shrink-0 w-24 truncate font-mono">
                  {new Date(t.timestamp).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })}
                  {' '}
                  {new Date(t.timestamp).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}
                </span>
                <span className={`font-bold flex-shrink-0 ${isBuy ? 'text-green-500' : 'text-red-500'}`}>
                  {isBuy ? '▲ BUY' : '▼ SELL'}
                </span>
                {entry && (
                  <span className="font-mono text-muted-foreground flex-shrink-0">@{entry.toFixed(dec)}</span>
                )}
                {t.ai_sl && (
                  <span className="font-mono text-red-400 flex-shrink-0 text-[10px]">SL {t.ai_sl.toFixed(dec)}</span>
                )}
                {t.ai_tp && t.ai_tp.length > 0 && (
                  <span className="font-mono text-green-400 flex-shrink-0 text-[10px]">
                    TP {t.ai_tp.map((v) => v.toFixed(dec)).join(' / ')}
                  </span>
                )}
                {t.brain_verdict && (
                  <span className={`ml-auto text-[10px] font-bold flex-shrink-0 ${
                    t.brain_verdict === 'APPROVE' ? 'text-green-400' :
                    t.brain_verdict === 'REJECT' ? 'text-red-400' : 'text-yellow-400'
                  }`}>
                    {t.brain_verdict === 'APPROVE' ? '✓' : t.brain_verdict === 'REJECT' ? '✗' : '~'} {t.brain_verdict}
                  </span>
                )}
                {t.extraction_error && !t.brain_verdict && (
                  <span className="ml-auto text-[10px] text-yellow-400 flex-shrink-0 truncate max-w-32" title={t.extraction_error}>
                    ⚠ {t.extraction_error}
                  </span>
                )}
                {t.has_image && (
                  <span className="text-[9px] text-cyan-400 flex-shrink-0">IMG</span>
                )}
              </div>
            );
          })}
        </div>
      )}

      <p className="text-[10px] text-muted-foreground/60 text-center">
        Click a signal row to highlight its Entry / SL / TP on the chart
      </p>
    </div>
  );

  if (isFullscreen && typeof document !== 'undefined') {
    return createPortal(rootEl, document.body);
  }
  return rootEl;
}
