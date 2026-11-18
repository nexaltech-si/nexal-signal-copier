'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { createChart, IChartApi, ColorType, Time, ISeriesApi } from 'lightweight-charts';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Activity, AlertCircle, BarChart3, TrendingUp, Maximize2, Minimize2, RefreshCw, Filter, PlayCircle } from 'lucide-react';
import Link from 'next/link';
import { useChartReplay } from '@/hooks/useChartReplay';
import ChartReplayControls from '@/components/ChartReplayControls';

interface ChannelSignal {
  id: string;
  createdAt: string;
  symbol: string;
  orderType: string;
  entryPrice: number | null;
  stopLoss: number | null;
  tpLevels: number[];
  status: string;
  channelName: string | null;
  channelId: string;
  confidence: number | null;
  aiVerificationType: string | null;
  rejectionReason: string | null;
  totalPnL: number;
  hasTrades: boolean;
  allClosed: boolean;
  tradeCount: number;
}

interface OHLCData {
  time: Time;
  open: number;
  high: number;
  low: number;
  close: number;
}

interface ChannelTimelineChartProps {
  channelId: string;
  channelName?: string;
  /** If provided, filter to a single symbol */
  symbol?: string;
  height?: number;
}

function outcomeColor(sig: ChannelSignal): string {
  if (sig.status === 'REJECTED' || sig.status === 'FAILED') return '#94a3b8'; // grey
  if (!sig.hasTrades) return '#f59e0b'; // amber – no trades placed
  if (!sig.allClosed) return '#3b82f6'; // blue – still open
  return sig.totalPnL >= 0 ? '#22c55e' : '#ef4444'; // green / red
}

function outcomeLabel(sig: ChannelSignal): string {
  if (sig.status === 'REJECTED' || sig.status === 'FAILED') return 'Rejected';
  if (!sig.hasTrades) return 'No trade';
  if (!sig.allClosed) return 'Open';
  return sig.totalPnL >= 0 ? `+$${sig.totalPnL.toFixed(2)}` : `-$${Math.abs(sig.totalPnL).toFixed(2)}`;
}

export default function ChannelTimelineChart({
  channelId,
  channelName,
  symbol,
  height = 420,
}: ChannelTimelineChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  // Wrap the sections above and below the chart (header + replay controls +
  // stats bar, and the signal list) so their combined measured height can be
  // subtracted from the viewport to size the chart with no leftover overflow.
  const chromeHeaderRef = useRef<HTMLDivElement>(null);
  const chromeTopRef = useRef<HTMLDivElement>(null);
  const chromeBottomRef = useRef<HTMLDivElement>(null);

  const [signals, setSignals] = useState<ChannelSignal[]>([]);
  const [ohlcData, setOhlcData] = useState<OHLCData[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedSignal, setSelectedSignal] = useState<ChannelSignal | null>(null);
  const [symbolFilter, setSymbolFilter] = useState(symbol || '');
  const [availableSymbols, setAvailableSymbols] = useState<string[]>([]);
  const [timeframe, setTimeframe] = useState('H1');
  const isInitialRender = useRef(true);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [fullscreenHeight, setFullscreenHeight] = useState(height);
  const effectiveHeight = isFullscreen ? fullscreenHeight : height;

  // Esc key exits fullscreen; keep viewport height for the chart area in sync while fullscreen
  useEffect(() => {
    if (!isFullscreen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setIsFullscreen(false);
    };
    const OUTER_PADDING = 16; // CardContent bottom padding, roughly
    const GAP_PX = 16; // margin between chart and signal list (mt-4)
    const updateHeight = () => {
      const headerHeight = chromeHeaderRef.current?.getBoundingClientRect().height ?? 0;
      const topHeight = chromeTopRef.current?.getBoundingClientRect().height ?? 0;
      const bottomHeight = chromeBottomRef.current?.getBoundingClientRect().height ?? 0;
      setFullscreenHeight(
        Math.max(200, window.innerHeight - headerHeight - topHeight - bottomHeight - OUTER_PADDING - GAP_PX)
      );
    };
    updateHeight();
    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('resize', updateHeight);
    // Chrome height depends on content (replay controls toggling, signal list
    // count, wrapping) — a ResizeObserver keeps the chart sized to exactly
    // fill the remaining viewport regardless of what caused the chrome to change.
    const chromeObserver = new ResizeObserver(updateHeight);
    if (chromeHeaderRef.current) chromeObserver.observe(chromeHeaderRef.current);
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
      if (next) setFullscreenHeight(window.innerHeight - 260);
      return next;
    });
  };

  const BROKER_OFFSET = 3 * 3600; // UTC+3

  // Nearest candle index to the selected signal's entry time (used as the replay start point)
  const replayStartIndex = (() => {
    if (!selectedSignal || ohlcData.length === 0) return ohlcData.length - 1;
    const sigTs = Math.floor(new Date(selectedSignal.createdAt).getTime() / 1000) + BROKER_OFFSET;
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

  // Tracks the last selected signal id so we only auto-recenter the view when the
  // selection actually changes, not on every chart rebuild (which would wipe out
  // the user's manual zoom/pan).
  const lastSelectedIdRef = useRef<string | null>(null);
  // Preserves the user's manually-set visible range across chart rebuilds.
  const savedRangeRef = useRef<{ from: number; to: number } | null>(null);
  // Tracks whether replay was already active on the previous rebuild, so we only
  // snap to the latest bar once when replay starts — not on every bar tick.
  const wasReplayingRef = useRef(false);

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

  // Fetch signals for this channel
  const fetchSignals = useCallback(async () => {
    try {
      const params = new URLSearchParams({ channelId, limit: '1000' });
      if (symbolFilter) params.set('symbol', symbolFilter);
      const res = await fetch(`/api/signals/channel-timeline?${params}`);
      if (!res.ok) throw new Error('Failed to fetch signals');
      const data: ChannelSignal[] = await res.json();
      setSignals(data);
      // Collect unique symbols
      const syms = Array.from(new Set(data.map((s) => s.symbol).filter(Boolean))).sort();
      setAvailableSymbols(syms);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load signals');
    }
  }, [channelId, symbolFilter]);

  // Fetch OHLC candles for the active symbol over the signal date range
  const fetchCandles = useCallback(async (sym: string, fromTs: number, toTs: number, tf: string) => {
    try {
      const start = new Date(fromTs * 1000 - 24 * 3600 * 1000).toISOString();
      const end = new Date(toTs * 1000 + 24 * 3600 * 1000).toISOString();
      const res = await fetch(`/api/candles?symbol=${sym}&timeframe=${tf}&start=${start}&end=${end}`);
      if (!res.ok) return [];
      const data = await res.json();
      if (!Array.isArray(data) || data.length === 0) return [];
      return data
        .map((bar: { time: string; open: number; high: number; low: number; close: number }) => ({
          time: Math.floor(new Date(bar.time).getTime() / 1000) as Time,
          open: bar.open,
          high: bar.high,
          low: bar.low,
          close: bar.close,
        }))
        .sort((a: OHLCData, b: OHLCData) => (a.time as number) - (b.time as number));
    } catch {
      return [];
    }
  }, []);

  // Load data
  useEffect(() => {
    setIsLoading(true);
    setError(null);
    fetchSignals().finally(() => setIsLoading(false));
  }, [fetchSignals]);

  // Determine dominant symbol and load candles when signals change
  useEffect(() => {
    if (signals.length === 0) return;

    const sym =
      symbolFilter ||
      // Pick the most common symbol
      (() => {
        const freq: Record<string, number> = {};
        signals.forEach((s) => { freq[s.symbol] = (freq[s.symbol] || 0) + 1; });
        return Object.entries(freq).sort((a, b) => b[1] - a[1])[0]?.[0] || '';
      })();

    if (!sym) return;

    const relevantSignals = signals.filter((s) => s.symbol === sym && s.entryPrice != null);
    if (relevantSignals.length === 0) { setOhlcData([]); return; }

    const timestamps = relevantSignals.map((s) => Math.floor(new Date(s.createdAt).getTime() / 1000));
    const fromTs = Math.min(...timestamps);
    const toTs = Math.max(...timestamps);

    fetchCandles(sym, fromTs, toTs, timeframe).then((candles: OHLCData[]) => {
      setOhlcData(candles as OHLCData[]);
      isInitialRender.current = true;
    });
  }, [signals, symbolFilter, timeframe, fetchCandles]);

  // Build / rebuild chart when data changes
  useEffect(() => {
    if (!chartContainerRef.current || visibleOhlcData.length === 0) return;

    // Destroy previous instance
    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
      seriesRef.current = null;
    }

    const dark = document.documentElement.classList.contains('dark');
    const chartBg = dark ? '#0D1624' : '#ffffff';
    const gridCol = dark ? '#18243A' : '#f1f5f9';
    const textCol = dark ? '#6B7A99' : '#64748b';
    const borderCol = dark ? '#18243A' : '#e2e8f0';

    const chart = createChart(chartContainerRef.current, {
      layout: { background: { type: ColorType.Solid, color: chartBg }, textColor: textCol },
      width: chartContainerRef.current.clientWidth,
      height: effectiveHeight,
      grid: { vertLines: { color: gridCol }, horzLines: { color: gridCol } },
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: borderCol },
      timeScale: { borderColor: borderCol, timeVisible: true, secondsVisible: false },
    });

    const series = chart.addCandlestickSeries({
      upColor: '#24C87A',
      downColor: '#F23050',
      borderUpColor: '#24C87A',
      borderDownColor: '#F23050',
      wickUpColor: '#24C87A',
      wickDownColor: '#F23050',
    });

    series.setData(visibleOhlcData);

    // Determine the active symbol for filtering markers
    const freq: Record<string, number> = {};
    signals.forEach((s) => { freq[s.symbol] = (freq[s.symbol] || 0) + 1; });
    const activeSymbol =
      symbolFilter || Object.entries(freq).sort((a, b) => b[1] - a[1])[0]?.[0] || '';

    // Plot each signal as a marker on the nearest H1 candle (only signals within the revealed window).
    // When a signal is selected, show only that signal's marker and hide the rest.
    const lastVisibleTs = visibleOhlcData[visibleOhlcData.length - 1].time as number;

    const relevantSignals = signals.filter(
      (s) => s.symbol === activeSymbol && s.entryPrice != null &&
        Math.floor(new Date(s.createdAt).getTime() / 1000) + BROKER_OFFSET <= lastVisibleTs &&
        (!selectedSignal || s.id === selectedSignal.id)
    );

    const markers = relevantSignals
      .map((sig) => {
        const sigTs = Math.floor(new Date(sig.createdAt).getTime() / 1000) + BROKER_OFFSET;
        const nearest = visibleOhlcData.reduce((prev, curr) =>
          Math.abs((curr.time as number) - sigTs) < Math.abs((prev.time as number) - sigTs) ? curr : prev
        );
        const isBuy = sig.orderType?.toUpperCase().includes('BUY');
        const isSelected = selectedSignal?.id === sig.id;
        const color = isSelected ? (isBuy ? '#16a34a' : '#dc2626') : outcomeColor(sig);
        const entryTimeStr = new Date(sig.createdAt).toLocaleString('en-GB', {
          day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
        });
        const baseText = `${isBuy ? '▲' : '▼'} ${sig.entryPrice!.toFixed(
          sig.entryPrice! < 10 ? 5 : sig.entryPrice! < 100 ? 3 : 2
        )} ${outcomeLabel(sig)}`;
        return {
          time: nearest.time,
          position: isBuy ? 'belowBar' : 'aboveBar',
          color,
          shape: isBuy ? 'arrowUp' : 'arrowDown',
          text: isSelected ? `${baseText}  •  Entry ${entryTimeStr}` : baseText,
          size: 1,
          // carry signal id for tooltip lookup (not supported natively, used in click handler)
          id: sig.id,
        } as const;
      })
      // Sort by time (markers must be in ascending time order)
      .sort((a, b) => (a.time as number) - (b.time as number));

    if (markers.length > 0) {
      series.setMarkers(markers as Parameters<typeof series.setMarkers>[0]);
    }

    // Add SL and TP price lines for selected signal
    if (selectedSignal && selectedSignal.symbol === activeSymbol) {
      if (selectedSignal.stopLoss) {
        series.createPriceLine({
          price: selectedSignal.stopLoss,
          color: '#ef4444',
          lineWidth: 1,
          lineStyle: 2,
          axisLabelVisible: true,
          title: 'SL',
        });
      }
      selectedSignal.tpLevels.forEach((tp, i) => {
        series.createPriceLine({
          price: tp,
          color: '#22c55e',
          lineWidth: 1,
          lineStyle: 2,
          axisLabelVisible: true,
          title: `TP${i + 1}`,
        });
      });
      if (selectedSignal.entryPrice) {
        series.createPriceLine({
          price: selectedSignal.entryPrice,
          color: '#3b82f6',
          lineWidth: 2,
          lineStyle: 0,
          axisLabelVisible: true,
          title: 'Entry',
        });
      }
    }

    const newlySelectedId = selectedSignal?.id ?? null;
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
    } else if (selectedSignal && selectedSignal.symbol === activeSymbol && selectionChanged) {
      // A new signal was just selected — center the view on its entry candle.
      const sigTs = Math.floor(new Date(selectedSignal.createdAt).getTime() / 1000) + BROKER_OFFSET;
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
  }, [visibleOhlcData, signals, symbolFilter, selectedSignal, effectiveHeight, replay.isReplaying]);

  const handleReset = () => {
    isInitialRender.current = true;
    chartRef.current?.timeScale().fitContent();
  };

  if (isLoading) {
    return (
      <Card className="tech-card border-0">
        <CardContent className="flex items-center justify-center" style={{ height }}>
          <div className="text-center">
            <Activity className="h-8 w-8 animate-spin mx-auto mb-2 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">Loading channel timeline...</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card className="tech-card border-0">
        <CardContent className="flex items-center justify-center" style={{ height }}>
          <div className="text-center">
            <AlertCircle className="h-8 w-8 mx-auto mb-2 text-destructive" />
            <p className="text-sm text-destructive">{error}</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  const freq: Record<string, number> = {};
  signals.forEach((s) => { freq[s.symbol] = (freq[s.symbol] || 0) + 1; });
  const activeSymbol =
    symbolFilter || Object.entries(freq).sort((a, b) => b[1] - a[1])[0]?.[0] || '';

  const visibleSignals = signals.filter((s) => !symbolFilter || s.symbol === activeSymbol);
  const withTrades = visibleSignals.filter((s) => s.hasTrades);
  const profitable = withTrades.filter((s) => s.allClosed && s.totalPnL > 0);
  const winRate = withTrades.length > 0 ? ((profitable.length / withTrades.filter((s) => s.allClosed).length) * 100) : 0;

  const cardEl = (
    <Card
      className={
        isFullscreen
          ? 'border-0 fixed inset-0 z-50 overflow-y-auto rounded-none bg-background'
          : 'tech-card border-0'
      }
    >
      <CardHeader ref={chromeHeaderRef} className="flex flex-row items-center justify-between pb-2 flex-wrap gap-2">
        <div className="flex items-center gap-2 flex-wrap">
          <BarChart3 className="h-4 w-4 text-primary" />
          <CardTitle className="text-base font-semibold">
            {channelName || channelId} — Signal Timeline
          </CardTitle>
          {activeSymbol && (
            <Badge variant="outline" className="text-xs">{activeSymbol}</Badge>
          )}
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {/* Symbol filter */}
          {availableSymbols.length > 1 && (
            <div className="flex items-center gap-1">
              <Filter className="h-3 w-3 text-muted-foreground" />
              <select
                value={symbolFilter}
                onChange={(e) => { setSymbolFilter(e.target.value); isInitialRender.current = true; }}
                className="text-xs px-2 py-1 border rounded bg-background text-foreground h-7"
              >
                <option value="">All symbols</option>
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
          <Button variant="outline" size="sm" onClick={handleReset} className="h-7 px-2" title="Fit all signals">
            <Maximize2 className="h-3.5 w-3.5" />
          </Button>
          <Button variant="outline" size="sm" onClick={() => { setIsLoading(true); fetchSignals().finally(() => setIsLoading(false)); }} className="h-7 px-2" title="Refresh">
            <RefreshCw className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant={replay.isReplaying ? 'default' : 'outline'}
            size="sm"
            className="h-7 px-2 gap-1"
            title={selectedSignal ? 'Replay chart from this signal' : 'Select a signal to replay from'}
            disabled={!selectedSignal || replay.isReplaying}
            onClick={() => replay.startReplay()}
          >
            <PlayCircle className="h-3.5 w-3.5" />
            <span className="text-xs">Replay</span>
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={toggleFullscreen}
            className="h-7 px-2"
            title={isFullscreen ? 'Exit fullscreen (Esc)' : 'Fullscreen'}
          >
            {isFullscreen ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
          </Button>
        </div>
      </CardHeader>

      <CardContent className="pt-0">
        <div ref={chromeTopRef}>
        {/* Replay controls */}
        {replay.isReplaying && (
          <div className="mb-3">
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
          </div>
        )}

        {/* Stats bar */}
        <div className="flex items-center gap-4 mb-3 text-xs flex-wrap">
          <span className="text-muted-foreground">{visibleSignals.length} signals</span>
          <span className="text-muted-foreground">{withTrades.length} traded</span>
          {withTrades.filter((s) => s.allClosed).length > 0 && (
            <span className={winRate >= 50 ? 'text-green-600 font-semibold' : 'text-red-500 font-semibold'}>
              {winRate.toFixed(0)}% win rate
            </span>
          )}
          {/* Legend */}
          <div className="flex items-center gap-3 ml-auto flex-wrap">
            {[
              { color: '#22c55e', label: 'Profitable' },
              { color: '#ef4444', label: 'Loss' },
              { color: '#3b82f6', label: 'Open' },
              { color: '#f59e0b', label: 'No trade' },
              { color: '#94a3b8', label: 'Rejected' },
            ].map(({ color, label }) => (
              <span key={label} className="flex items-center gap-1">
                <span className="inline-block w-2 h-2 rounded-full" style={{ backgroundColor: color }} />
                <span className="text-muted-foreground">{label}</span>
              </span>
            ))}
          </div>
        </div>
        </div>

        {/* Chart */}
        {ohlcData.length > 0 ? (
          <div ref={chartContainerRef} style={{ height: effectiveHeight }} />
        ) : (
          <div className="flex items-center justify-center bg-muted/30 rounded-lg" style={{ height: effectiveHeight }}>
            <div className="text-center text-muted-foreground">
              <BarChart3 className="h-8 w-8 mx-auto mb-2 opacity-40" />
              <p className="text-sm">No candle data available for {activeSymbol || 'this channel'}</p>
              <p className="text-xs mt-1 opacity-60">Chart requires MT5 REST connection</p>
            </div>
          </div>
        )}

        {/* Signal list below chart */}
        {visibleSignals.length > 0 && (
          <div ref={chromeBottomRef} className="mt-4">
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
              Signals in this channel {symbolFilter ? `(${symbolFilter})` : ''}
            </p>
            <div className="space-y-1 max-h-64 overflow-y-auto pr-1">
              {[...visibleSignals].reverse().map((sig) => {
                const isBuy = sig.orderType?.toUpperCase().includes('BUY');
                const color = outcomeColor(sig);
                const label = outcomeLabel(sig);
                const isSelected = selectedSignal?.id === sig.id;
                return (
                  <div
                    key={sig.id}
                    onClick={() => setSelectedSignal(isSelected ? null : sig)}
                    className={`flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer transition-colors text-xs ${
                      isSelected
                        ? 'bg-primary/10 border border-primary/30'
                        : 'hover:bg-muted/60 border border-transparent'
                    }`}
                  >
                    <span
                      className="inline-block w-2 h-2 rounded-full flex-shrink-0"
                      style={{ backgroundColor: color }}
                    />
                    <span className="text-muted-foreground flex-shrink-0 w-28 truncate">
                      {new Date(sig.createdAt).toLocaleDateString('en-GB', {
                        day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
                      })}
                    </span>
                    <span className="font-mono font-semibold text-foreground">{sig.symbol}</span>
                    <span className={`font-semibold ${isBuy ? 'text-green-600' : 'text-red-500'}`}>
                      {isBuy ? '▲' : '▼'} {sig.orderType}
                    </span>
                    {sig.entryPrice && (
                      <span className="font-mono text-muted-foreground">
                        @{sig.entryPrice.toFixed(sig.entryPrice < 10 ? 5 : sig.entryPrice < 100 ? 3 : 2)}
                      </span>
                    )}
                    <span className="ml-auto font-semibold" style={{ color }}>
                      {label}
                    </span>
                    <Link
                      href={`/history/signals/${sig.id}`}
                      onClick={(e) => e.stopPropagation()}
                      className="text-primary hover:text-primary/70 flex-shrink-0 text-[10px] underline"
                    >
                      View
                    </Link>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {visibleSignals.length === 0 && (
          <div className="text-center py-8 text-muted-foreground text-sm">
            No signals found for this channel
          </div>
        )}
      </CardContent>
    </Card>
  );

  // Ancestor panels use backdrop-filter (.tech-card), which establishes a new
  // containing block for position:fixed descendants — that traps the "fullscreen"
  // Card to the panel's own small box instead of the viewport. Portal it to
  // <body> while fullscreen so `fixed inset-0` resolves against the real viewport.
  if (isFullscreen && typeof document !== 'undefined') {
    return createPortal(cardEl, document.body);
  }
  return cardEl;
}
