'use client'

import { useEffect, useRef } from 'react'
import { ColorType, createChart, LineStyle, type IChartApi, type SeriesMarker, type Time, type UTCTimestamp } from 'lightweight-charts'

// Price chart for one replayed setup: candles from before the entry to after
// the last exit, the setup's levels, every fill / close and every channel
// message of the setup at the minute it happened.
//
// Time: bars arrive already corrected to real UTC (the broker's server clock is
// measured on the bot side), executions and messages are real UTC too. The axis
// is drawn in the viewer's local time — the same clock the chat bubbles use —
// so a message at 13:04 sits under the 13:04 candle.

export type ChartBar = [string, number, number, number, number]   // ISO time, open, high, low, close
export interface ChartExecution { time: string; kind: 'entry' | 'exit'; how: string; side: string | null; lots: number; price: number; pnl: number | null }
export interface ChartMessage { time: string; label: string }
export interface ChartLevels { sl: number | null; slNow?: number | null; tps: number[]; entries: number[] }

const sec = (iso: string) => Math.floor(new Date(iso).getTime() / 1000)
const hhmm = (t: number) => new Date(t * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })

export default function FlowReplayChart({
  bars, executions, messages, levels, from, to, height = 300,
}: {
  bars: ChartBar[]; executions: ChartExecution[]; messages: ChartMessage[]; levels: ChartLevels
  from: string; to: string; height?: number
}) {
  const host = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!host.current || !bars.length) return
    const chart: IChartApi = createChart(host.current, {
      height,
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#8a97b8', fontSize: 11 },
      grid: { vertLines: { color: 'rgba(138,151,184,0.08)' }, horzLines: { color: 'rgba(138,151,184,0.08)' } },
      rightPriceScale: { borderColor: 'rgba(138,151,184,0.2)' },
      timeScale: {
        borderColor: 'rgba(138,151,184,0.2)', timeVisible: true, secondsVisible: false,
        tickMarkFormatter: (t: Time) => hhmm(t as number),
      },
      localization: {
        timeFormatter: (t: Time) => new Date((t as number) * 1000).toLocaleString([], {
          day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
        }),
      },
      crosshair: { mode: 0 },
    })
    const series = chart.addCandlestickSeries({
      upColor: '#22c55e', downColor: '#f43f5e', borderVisible: false, wickUpColor: '#22c55e', wickDownColor: '#f43f5e',
    })
    const data = bars.map(b => ({ time: sec(b[0]) as UTCTimestamp, open: b[1], high: b[2], low: b[3], close: b[4] }))
    series.setData(data)

    // a marker belongs to the candle that contains its moment
    const times = data.map(d => d.time as number)
    const candleOf = (iso: string): UTCTimestamp | null => {
      const t = sec(iso)
      let lo = 0, hi = times.length - 1, found = -1
      while (lo <= hi) {
        const mid = (lo + hi) >> 1
        if (times[mid] <= t) { found = mid; lo = mid + 1 } else hi = mid - 1
      }
      return found >= 0 ? (times[found] as UTCTimestamp) : null
    }

    const markers: SeriesMarker<Time>[] = []
    for (const e of executions) {
      const time = candleOf(e.time)
      if (time == null) continue
      const buy = e.side === 'BUY'
      if (e.kind === 'entry') {
        markers.push({ time, position: buy ? 'belowBar' : 'aboveBar', shape: buy ? 'arrowUp' : 'arrowDown',
          color: '#3b82f6', text: `${e.side} ${e.lots}` })
      } else {
        const win = (e.pnl ?? 0) >= 0
        markers.push({ time, position: buy ? 'aboveBar' : 'belowBar', shape: 'circle', color: win ? '#22c55e' : '#f43f5e',
          text: `${e.how} ${e.price}${e.pnl != null ? ` (${e.pnl >= 0 ? '+' : ''}${e.pnl.toFixed(2)})` : ''}` })
      }
    }
    for (const m of messages) {
      const time = candleOf(m.time)
      if (time != null) markers.push({ time, position: 'inBar', shape: 'square', color: '#f59e0b', text: m.label })
    }
    markers.sort((a, b) => (a.time as number) - (b.time as number))
    series.setMarkers(markers)

    for (const price of levels.entries) {
      series.createPriceLine({ price, color: '#3b82f6', lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: true, title: 'entry' })
    }
    if (levels.sl != null) {
      series.createPriceLine({ price: levels.sl, color: '#f43f5e', lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: 'SL' })
    }
    if (levels.slNow != null) {
      series.createPriceLine({ price: levels.slNow, color: '#f59e0b', lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: 'SL moved' })
    }
    levels.tps.forEach((price, i) => {
      series.createPriceLine({ price, color: '#22c55e', lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: `TP${i + 1}` })
    })

    const first = Math.max(sec(from), times[0]), last = Math.min(sec(to), times[times.length - 1])
    if (last > first) chart.timeScale().setVisibleRange({ from: first as UTCTimestamp, to: last as UTCTimestamp })
    else chart.timeScale().fitContent()

    const resize = () => { if (host.current) chart.applyOptions({ width: host.current.clientWidth }) }
    resize()
    window.addEventListener('resize', resize)
    return () => { window.removeEventListener('resize', resize); chart.remove() }
  }, [bars, executions, messages, levels, from, to, height])

  return <div ref={host} className="w-full" style={{ height }} />
}
