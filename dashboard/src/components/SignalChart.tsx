'use client';

import { useEffect, useRef, useState } from 'react';
import { createChart, IChartApi, ColorType, Time, LineData, CandlestickData } from 'lightweight-charts';
import { brokerTimeToTvTime, formatBrokerTime } from '@/lib/utils/timezone';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Activity, AlertCircle, BarChart3, TrendingUp, Maximize2 } from 'lucide-react';

interface PlanLevel {
  entryMin: number;
  entryMax: number;
  sl?: number;
  tps?: number[];
  slCondition?: string;
  orderType?: string;
}

interface SignalChartProps {
  symbol: string;
  signalTime?: number;
  signalPrice?: number;
  signalType?: 'BUY' | 'SELL';
  stopLoss?: number;
  takeProfit?: number;
  takeProfitLevels?: number[];
  entryRangeMin?: number;
  entryRangeMax?: number;
  planData?: {
    primary: PlanLevel;
    fallback?: PlanLevel;
  } | null;
  provider?: string;
  height?: number;
}

interface LineChartData {
  time: Time;
  value: number;
}

interface OHLCData {
  time: Time;
  open: number;
  high: number;
  low: number;
  close: number;
}

export default function SignalChart({
  symbol,
  signalTime,
  signalPrice,
  signalType = 'BUY',
  stopLoss,
  takeProfit,
  takeProfitLevels,
  entryRangeMin,
  entryRangeMax,
  planData,
  provider = 'mt5rest',
  height = 400,
}: SignalChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<any>(null);
  const seriesRef = useRef<any>(null);
  const isInitialRender = useRef<boolean>(true);
  const [ohlcData, setOhlcData] = useState<OHLCData[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentPrice, setCurrentPrice] = useState<number | null>(null);
  const [chartError, setChartError] = useState<string | null>(null);
  const [detectedTimezoneOffset, setDetectedTimezoneOffset] = useState<number>(0);
  const [chartType, setChartType] = useState<'line' | 'candle'>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('chartType');
      return (saved === 'line' || saved === 'candle') ? saved : 'candle';
    }
    return 'candle';
  });

  // Persist chart type to localStorage and reset initial render flag
  useEffect(() => {
    if (typeof window !== 'undefined') {
      localStorage.setItem('chartType', chartType);
    }
    // Reset initial render flag when chart type changes to fit content for new chart type
    isInitialRender.current = true;
  }, [chartType]);

  // Reset chart view to fit all content (both X and Y axes)
  const handleResetView = () => {
    if (chartRef.current) {
      chartRef.current.timeScale().fitContent();
      // Reset price scale to fit all visible data
      chartRef.current.timeScale().scrollToPosition(0, false);
    }
  };

  // Fetch historical OHLCV data from MT5 REST API via new /api/candles endpoint with Redis caching
  useEffect(() => {
    if (provider !== 'mt5rest' || !symbol) {
      setIsLoading(false);
      return;
    }

    const fetchHistoricalData = async () => {
      try {
        setIsLoading(true);
        setError(null);

        // Calculate date range: from signal time to now (or last 24 hours if no signal time)
        const endTime = new Date();
        const startTime = signalTime 
          ? new Date(signalTime * 1000)
          : new Date(endTime.getTime() - 24 * 60 * 60 * 1000);

        const response = await fetch(
          `/api/candles?symbol=${symbol}&timeframe=M15&start=${startTime.toISOString()}&end=${endTime.toISOString()}`
        );

        if (!response.ok) {
          throw new Error(`Failed to fetch data: ${response.statusText}`);
        }

        const data = await response.json();

        if (!data || !Array.isArray(data) || data.length === 0) {
          throw new Error('No historical data available');
        }

        // Convert MT5 data to TradingView OHLC format
        console.log('[SignalChart] Raw data sample:', data[0]);
        console.log('[SignalChart] Signal time (seconds):', signalTime);
        console.log('[SignalChart] Signal time (ISO):', signalTime ? new Date(signalTime * 1000).toISOString() : 'N/A');
        console.log('[SignalChart] Signal time (local):', signalTime ? new Date(signalTime * 1000).toLocaleString() : 'N/A');
        
        // First pass: convert timestamps without offset
        const rawTvData: OHLCData[] = data.map((bar: any) => {
          // MT5 returns time as ISO string, convert to Unix timestamp in seconds
          const timestamp = Math.floor(new Date(bar.time).getTime() / 1000);
          return {
            time: timestamp as Time,
            open: bar.open,
            high: bar.high,
            low: bar.low,
            close: bar.close,
          };
        }).sort((a, b) => (a.time as number) - (b.time as number));
        
        console.log('[SignalChart] First candle time (raw, seconds):', rawTvData[0]?.time);
        console.log('[SignalChart] First candle time (raw, ISO):', rawTvData[0] ? new Date((rawTvData[0].time as number) * 1000).toISOString() : 'N/A');
        
        // Broker sends candles in UTC+3, no conversion needed
        // Signal is stored in UTC0, need to convert to broker time (UTC+3) for display
        const timezoneOffsetSeconds = 3 * 3600; // 10800 seconds = 3 hours (UTC+3)
        
        console.log('[SignalChart] Using broker timezone: UTC+3');
        console.log('[SignalChart] Signal time (UTC):', signalTime, '=', signalTime ? new Date(signalTime * 1000).toISOString() : 'N/A');
        
        // Store the offset for signal time conversion only
        setDetectedTimezoneOffset(timezoneOffsetSeconds);
        
        // DON'T convert candle times - broker already sends them in UTC+3
        const tvData: OHLCData[] = rawTvData;

        setOhlcData(tvData);
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : 'Failed to load chart data';
        console.error('[SignalChart] Error fetching historical data:', errorMessage);
        setError(errorMessage);
      } finally {
        setIsLoading(false);
      }
    };

    fetchHistoricalData();
  }, [symbol, signalTime, provider]);

  // Poll for real-time updates using REST API
  useEffect(() => {
    if (provider !== 'mt5rest' || !symbol || !seriesRef.current) {
      return;
    }

    const pollInterval = setInterval(async () => {
      try {
        // Fetch latest candle data
        const endTime = new Date();
        const startTime = new Date(endTime.getTime() - 30 * 60 * 1000); // Last 30 minutes
        
        const response = await fetch(
          `/api/candles?symbol=${symbol}&timeframe=M15&start=${startTime.toISOString()}&end=${endTime.toISOString()}`
        );

        if (response.ok) {
          const data = await response.json();
          
          if (data && Array.isArray(data) && data.length > 0) {
            const latestCandle = data[data.length - 1];
            const newPrice = latestCandle.close;
            
            setCurrentPrice(newPrice);

            // Update chart with new candle data WITHOUT triggering re-render
            if (seriesRef.current) {
              const tvData: OHLCData[] = data.map((bar: any) => {
                // MT5 returns time as ISO string, convert to Unix timestamp in seconds
                const timestamp = Math.floor(new Date(bar.time).getTime() / 1000);
                return {
                  time: timestamp as Time,
                  open: bar.open,
                  high: bar.high,
                  low: bar.low,
                  close: bar.close,
                };
              }).sort((a, b) => (a.time as number) - (b.time as number)); // Ensure data is sorted by time

              // Update the last data point only (don't trigger full re-render)
              const lastBar = tvData[tvData.length - 1];
              seriesRef.current.update(lastBar);
              
              // DON'T update ohlcData state here - it would trigger chart re-initialization
              // The chart series is already updated via seriesRef.current.update()
            }
          }
        }
      } catch (error) {
        console.error('[SignalChart] Error polling for updates:', error);
      }
    }, 15000); // Poll every 15 seconds

    return () => clearInterval(pollInterval);
  }, [symbol, provider]);

  // Re-apply chart colors when dark/light mode changes
  useEffect(() => {
    const observer = new MutationObserver(() => {
      if (!chartRef.current) return;
      const isDark = document.documentElement.classList.contains('dark');
      chartRef.current.applyOptions({
        layout: {
          background: { type: ColorType.Solid, color: isDark ? '#0D1624' : '#ffffff' },
          textColor: isDark ? '#6B7A99' : '#64748b',
        },
        grid: {
          vertLines: { color: isDark ? '#18243A' : '#f1f5f9' },
          horzLines: { color: isDark ? '#18243A' : '#f1f5f9' },
        },
        rightPriceScale: { borderColor: isDark ? '#18243A' : '#e2e8f0' },
        timeScale: { borderColor: isDark ? '#18243A' : '#e2e8f0', timeVisible: true, secondsVisible: false },
      });
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, []);

  // Initialize chart
  useEffect(() => {
    if (!chartContainerRef.current || ohlcData.length === 0) return;

    try {
      const isDark = document.documentElement.classList.contains('dark')
      const chartBg   = isDark ? '#0D1624' : '#ffffff'
      const gridCol   = isDark ? '#18243A' : '#f1f5f9'
      const textCol   = isDark ? '#6B7A99' : '#64748b'
      const borderCol = isDark ? '#18243A' : '#e2e8f0'

      const chart = createChart(chartContainerRef.current, {
        layout: {
          background: { type: ColorType.Solid, color: chartBg },
          textColor: textCol,
        },
        width: chartContainerRef.current.clientWidth,
        height: height,
        grid: {
          vertLines: { color: gridCol },
          horzLines: { color: gridCol },
        },
        crosshair: {
          mode: 1,
        },
        rightPriceScale: {
          borderColor: borderCol,
        },
        timeScale: {
          borderColor: borderCol,
          timeVisible: true,
          secondsVisible: false,
        },
      });

      let series: any;
      
      if (chartType === 'candle') {
        // Add candlestick series
        series = chart.addCandlestickSeries({
          upColor: '#24C87A',
          downColor: '#F23050',
          borderUpColor: '#24C87A',
          borderDownColor: '#F23050',
          wickUpColor: '#24C87A',
          wickDownColor: '#F23050',
        });
        
        console.log('[SignalChart] Setting candlestick data:', ohlcData.length, 'candles');
        console.log('[SignalChart] First candle:', ohlcData[0]);
        console.log('[SignalChart] Last candle:', ohlcData[ohlcData.length - 1]);
        series.setData(ohlcData);
      } else {
        // Add line series
        series = chart.addLineSeries({
          color: signalType === 'BUY' ? '#24C87A' : '#F23050',
          lineWidth: 2,
        });
        
        // Convert OHLC to line data (using close price)
        const lineData: LineChartData[] = ohlcData.map(bar => ({
          time: bar.time,
          value: bar.close,
        }));
        
        console.log('[SignalChart] Setting line data:', lineData.length, 'points');
        series.setData(lineData);
      }

      // Add marker for signal entry point
      // Markers are now placed inside the range/plan logic below.
      // This single-entry marker handles the legacy case with no range data.
      if (signalTime && signalPrice && !entryRangeMin && !entryRangeMax) {
        const signalTimeInBrokerTz = signalTime + detectedTimezoneOffset;
        const nearestCandle = ohlcData.reduce((prev, curr) => {
          const prevDiff = Math.abs((prev.time as number) - signalTimeInBrokerTz);
          const currDiff = Math.abs((curr.time as number) - signalTimeInBrokerTz);
          return currDiff < prevDiff ? curr : prev;
        });
        const markerTime = nearestCandle.time;
        const priceDecimals = signalPrice < 10 ? 5 : signalPrice < 100 ? 3 : 2;
        const priceStr = signalPrice.toFixed(priceDecimals);

        series.setMarkers([
          {
            time: markerTime,
            position: signalType === 'BUY' ? 'belowBar' : 'aboveBar',
            color: signalType === 'BUY' ? '#24C87A' : '#F23050',
            shape: signalType === 'BUY' ? 'arrowUp' : 'arrowDown',
            text: `${signalType} @ ${priceStr}`,
          },
        ]);
      }

      // Add markers and price lines for entry points
      const hasRange = entryRangeMin != null && entryRangeMax != null && entryRangeMin !== entryRangeMax;
      const effectivePrice = signalPrice ?? (hasRange ? (entryRangeMin! + entryRangeMax!) / 2 : (entryRangeMin ?? entryRangeMax));

      // Draw range zone as a shaded rectangle area (using area series or price lines)
      if (hasRange) {
        // Draw range zone with two boundary lines and shaded area markers
        const decimals = entryRangeMin! < 10 ? 5 : entryRangeMin! < 100 ? 3 : 2;
        const minStr = entryRangeMin!.toFixed(decimals);
        const maxStr = entryRangeMax!.toFixed(decimals);

        // Lower bound price line
        series.createPriceLine({
          price: entryRangeMin!,
          color: '#29ADFF',
          lineWidth: 1,
          lineStyle: 3, // dotted
          axisLabelVisible: true,
          title: `Entry min`,
        });

        // Upper bound price line
        series.createPriceLine({
          price: entryRangeMax!,
          color: '#29ADFF',
          lineWidth: 1,
          lineStyle: 3, // dotted
          axisLabelVisible: true,
          title: `Entry max`,
        });

        // Add midline as solid line
        const midPrice = (entryRangeMin! + entryRangeMax!) / 2;
        series.createPriceLine({
          price: midPrice,
          color: '#29ADFF',
          lineWidth: 2,
          lineStyle: 2, // dashed
          axisLabelVisible: true,
          title: 'Entry mid',
        });

        // Add markers at both range boundaries and midpoint
        const markerTime = signalTime ? (() => {
          const signalTimeInBrokerTz = signalTime + detectedTimezoneOffset;
          const nearestCandle = ohlcData.reduce((prev, curr) => {
            const prevDiff = Math.abs((prev.time as number) - signalTimeInBrokerTz);
            const currDiff = Math.abs((curr.time as number) - signalTimeInBrokerTz);
            return currDiff < prevDiff ? curr : prev;
          });
          return nearestCandle.time;
        })() : undefined;

        if (markerTime) {
          series.setMarkers([
            {
              time: markerTime,
              position: signalType === 'BUY' ? 'belowBar' : 'aboveBar',
              color: signalType === 'BUY' ? '#24C87A' : '#F23050',
              shape: signalType === 'BUY' ? 'arrowUp' : 'arrowDown',
              text: `${signalType} ${minStr} – ${maxStr}`,
            },
          ]);
        }
      } else if (signalPrice) {
        // Single entry price line (legacy behavior)
        series.createPriceLine({
          price: signalPrice,
          color: '#29ADFF',
          lineWidth: 2,
          lineStyle: 2,
          axisLabelVisible: true,
          title: 'Entry',
        });
      }

      // Draw plan entry levels (primary + fallback)
      if (planData) {
        const planColors = { primary: '#8B5CF6', fallback: '#F59E0B' }; // purple & amber
        const planLabels = { primary: 'Primary', fallback: 'Fallback' };

        for (const leg of ['primary', 'fallback'] as const) {
          const plan = leg === 'primary' ? planData.primary : planData.fallback;
          if (!plan) continue;

          const isRange = plan.entryMin !== plan.entryMax;
          const lineColor = planColors[leg];
          const lineLabel = planLabels[leg];

          if (isRange) {
            series.createPriceLine({
              price: plan.entryMin,
              color: lineColor,
              lineWidth: 1,
              lineStyle: 3,
              axisLabelVisible: true,
              title: `${lineLabel} min`,
            });
            series.createPriceLine({
              price: plan.entryMax,
              color: lineColor,
              lineWidth: 1,
              lineStyle: 3,
              axisLabelVisible: true,
              title: `${lineLabel} max`,
            });
          } else {
            series.createPriceLine({
              price: plan.entryMin,
              color: lineColor,
              lineWidth: 2,
              lineStyle: 2,
              axisLabelVisible: true,
              title: lineLabel,
            });
          }

          if (plan.sl) {
            series.createPriceLine({
              price: plan.sl,
              color: '#F23050',
              lineWidth: 1,
              lineStyle: 1,
              axisLabelVisible: true,
              title: `${lineLabel} SL`,
            });
          }

          if (plan.tps) {
            plan.tps.forEach((tp, i) => {
              series.createPriceLine({
                price: tp,
                color: '#24C87A',
                lineWidth: 1,
                lineStyle: 1,
                axisLabelVisible: true,
                title: `${lineLabel} TP${i + 1}`,
              });
            });
          }
        }
      }

      // Stop Loss line (for non-plan signals)
      if (stopLoss && !planData) {
        series.createPriceLine({
          price: stopLoss,
          color: '#F23050',
          lineWidth: 2,
          lineStyle: 2,
          axisLabelVisible: true,
          title: 'SL',
        });
      }

      // Take Profit lines
      if (takeProfitLevels && takeProfitLevels.length > 0) {
        takeProfitLevels.forEach((tp, i) => {
          series.createPriceLine({
            price: tp,
            color: '#24C87A',
            lineWidth: 1,
            lineStyle: 2,
            axisLabelVisible: true,
            title: `TP${i + 1}`,
          });
        });
      } else if (takeProfit && !planData) {
        series.createPriceLine({
          price: takeProfit,
          color: '#24C87A',
          lineWidth: 2,
          lineStyle: 2,
          axisLabelVisible: true,
          title: 'TP',
        });
      }

      // Only fit content on initial render, preserve zoom/pan on updates
      if (isInitialRender.current) {
        chart.timeScale().fitContent();
        isInitialRender.current = false;
      }

      chartRef.current = chart;
      seriesRef.current = series;

      const handleResize = () => {
        if (chartContainerRef.current && chartRef.current) {
          chartRef.current.applyOptions({
            width: chartContainerRef.current.clientWidth,
          });
        }
      };

      window.addEventListener('resize', handleResize);

      return () => {
        window.removeEventListener('resize', handleResize);
        chartRef.current?.remove();
      };
    } catch (err) {
      console.error('[SignalChart] Chart initialization error:', err);
      setChartError(err instanceof Error ? err.message : 'Failed to initialize chart');
    }
  }, [ohlcData, signalPrice, signalTime, signalType, height, chartType, stopLoss, takeProfit]);


  if (provider !== 'mt5rest') {
    return null;
  }

  return (
    <Card className="tech-card border-0">
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-primary" />
          <CardTitle className="text-lg font-semibold">
            {symbol} Chart
          </CardTitle>
          <Badge variant="outline" className="text-xs">
            {signalType}
          </Badge>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1 border rounded-md p-1">
            <Button
              variant={chartType === 'line' ? 'default' : 'ghost'}
              size="sm"
              onClick={() => setChartType('line')}
              className="h-7 px-2"
            >
              <TrendingUp className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant={chartType === 'candle' ? 'default' : 'ghost'}
              size="sm"
              onClick={() => setChartType('candle')}
              className="h-7 px-2"
            >
              <BarChart3 className="h-3.5 w-3.5" />
            </Button>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={handleResetView}
            className="h-7 px-2"
            title="Reset chart view"
          >
            <Maximize2 className="h-3.5 w-3.5" />
          </Button>
          {currentPrice && (
            <span className="font-mono text-xs">
              {currentPrice.toFixed(5)}
            </span>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="flex items-center justify-center h-[400px]">
            <div className="text-center">
              <Activity className="h-8 w-8 animate-spin mx-auto mb-2 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">Loading chart data...</p>
            </div>
          </div>
        ) : error || chartError ? (
          <div className="flex items-center justify-center h-[400px]">
            <div className="text-center">
              <AlertCircle className="h-8 w-8 mx-auto mb-2 text-destructive" />
              <p className="text-sm text-destructive">{error || chartError}</p>
            </div>
          </div>
        ) : (
          <div ref={chartContainerRef} />
        )}
        {signalTime && signalPrice && (
          <div className="mt-3 space-y-1">
            <div className="flex items-center gap-4 text-xs text-muted-foreground">
              <span>Signal Time: {(() => {
                const signalDate = new Date(signalTime * 1000);
                // Convert to broker timezone for display
                const signalBrokerTime = new Date((signalTime + detectedTimezoneOffset) * 1000);
                const brokerTimeStr = signalBrokerTime.toISOString().substring(0, 10) + ', ' + signalBrokerTime.toISOString().substring(11, 19);
                const utcTime = signalDate.toISOString().replace('T', ' ').substring(0, 19);
                const offsetHours = detectedTimezoneOffset / 3600;
                return `${brokerTimeStr.replace('-', '/').replace('-', '/')} (UTC${offsetHours >= 0 ? '+' : ''}${offsetHours.toFixed(0)}: ${utcTime})`;
              })()}</span>
              <span>Signal Price: {signalPrice.toFixed(5)}</span>
              {currentPrice && (
                <span className={currentPrice > signalPrice ? 'text-green-600' : 'text-destructive'}>
                  Current: {currentPrice.toFixed(5)} 
                  ({currentPrice > signalPrice ? '+' : ''}{((currentPrice - signalPrice) / signalPrice * 100).toFixed(2)}%)
                </span>
              )}
            </div>
            {ohlcData.length > 0 && (() => {
              // Convert signal time to broker timezone for comparison
              const signalTimeInBrokerTz = signalTime + detectedTimezoneOffset;
              
              const nearestCandle = ohlcData.reduce((prev, curr) => {
                const prevDiff = Math.abs((prev.time as number) - signalTimeInBrokerTz);
                const currDiff = Math.abs((curr.time as number) - signalTimeInBrokerTz);
                return currDiff < prevDiff ? curr : prev;
              });
              const candleTime = nearestCandle.time as number;
              const timeDiff = Math.abs(signalTimeInBrokerTz - candleTime);
              const candleDate = new Date(candleTime * 1000);
              const signalBrokerDate = new Date(signalTimeInBrokerTz * 1000);
              const offsetHours = detectedTimezoneOffset / 3600;
              
              return (
                <div className="text-[10px] text-muted-foreground/70 space-y-1">
                  <div>
                    Chart uses M15 candles in broker time (UTC{offsetHours >= 0 ? '+' : ''}{offsetHours.toFixed(0)}). 
                    Signal at {signalBrokerDate.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })} (broker time)
                    {' '}appears on {candleDate.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })} candle
                    {timeDiff > 0 && ` (${Math.floor(timeDiff / 60)}m ${timeDiff % 60}s difference)`}.
                  </div>
                  {detectedTimezoneOffset !== 0 && (
                    <div className="bg-primary/10 dark:bg-blue-950/20 border border-blue-200 dark:border-blue-800 rounded-md p-2 space-y-1">
                      <div className="flex items-start gap-1.5">
                        <span className="text-primary dark:text-blue-400 flex-shrink-0">ℹ️</span>
                        <div className="text-primary dark:text-blue-300 space-y-0.5">
                          <div className="font-semibold">Timezone Information:</div>
                          <div>
                            • <strong>Signal Time Display:</strong> Shows your local time ({new Date(signalTime * 1000).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })}) and UTC ({new Date(signalTime * 1000).toISOString().substring(11, 19)})
                          </div>
                          <div>
                            • <strong>Chart Time:</strong> Uses broker time (UTC{offsetHours >= 0 ? '+' : ''}{offsetHours.toFixed(0)}) = {signalBrokerDate.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })}
                          </div>
                          <div>
                            • <strong>Why Different?</strong> Signals are stored in UTC but the broker's MT5 server uses UTC{offsetHours >= 0 ? '+' : ''}{offsetHours.toFixed(0)}. The chart automatically converts signal times to match broker time for accurate candle placement.
                          </div>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              );
            })()}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
