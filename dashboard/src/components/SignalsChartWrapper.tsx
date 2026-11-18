'use client';

import { useState, useEffect } from 'react';
import SignalChart from './SignalChart';
import type { SignalWithTrades } from '@/lib/types';

interface SignalsChartWrapperProps {
  signals: SignalWithTrades[];
}

export default function SignalsChartWrapper({ signals }: SignalsChartWrapperProps) {
  const [provider, setProvider] = useState<string>('');
  const [selectedSignal, setSelectedSignal] = useState<SignalWithTrades | null>(null);
  const [chartError, setChartError] = useState<string | null>(null);

  useEffect(() => {
    const getProvider = async () => {
      try {
        const response = await fetch('/api/provider');
        if (response.ok) {
          const data = await response.json();
          setProvider(data.provider || '');
        }
      } catch (error) {
        console.error('Failed to fetch provider:', error);
      }
    };
    getProvider();
  }, []);

  // Auto-select the most recent verified trade signal
  useEffect(() => {
    if (signals.length > 0 && !selectedSignal) {
      const tradeSignal = signals.find(
        s => s.aiVerificationType === 'TRADE_SIGNAL' && s.aiVerified
      );
      setSelectedSignal(tradeSignal || signals[0]);
    }
  }, [signals, selectedSignal]);

  if (provider !== 'mt5rest') {
    return null;
  }

  if (!selectedSignal) {
    return null;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">Signal Chart</h3>
        <select
          value={selectedSignal.id}
          onChange={(e) => {
            const signal = signals.find(s => s.id === e.target.value);
            if (signal) setSelectedSignal(signal);
          }}
          className="text-xs px-2 py-1 border rounded bg-background"
        >
          {signals
            .filter(s => s.aiVerificationType === 'TRADE_SIGNAL' || !s.aiVerified)
            .map((signal) => (
              <option key={signal.id} value={signal.id}>
                {signal.symbol} - {signal.orderType} - {new Date(signal.createdAt).toLocaleString()}
              </option>
            ))}
        </select>
      </div>
      {chartError ? (
        <div className="p-4 border border-red-200 bg-red-50 rounded-md">
          <p className="text-sm text-destructive">Chart Error: {chartError}</p>
        </div>
      ) : (
        (() => {
          // Parse TP levels from JSON string
          let tpLevels: number[] = [];
          try { if (selectedSignal.takeProfit) tpLevels = JSON.parse(selectedSignal.takeProfit); } catch { /* ignore */ }

          // Parse planData from JSON string
          let planData: { primary: { entryMin: number; entryMax: number; sl?: number; tps?: number[]; slCondition?: string; orderType?: string }; fallback?: { entryMin: number; entryMax: number; sl?: number; tps?: number[]; slCondition?: string; orderType?: string } } | null = null;
          if ((selectedSignal as any).planData) {
            try {
              planData = JSON.parse((selectedSignal as any).planData);
            } catch { /* ignore */ }
          }

          return (
            <SignalChart
              symbol={selectedSignal.symbol}
              signalTime={selectedSignal.createdAt ? Math.floor(new Date(selectedSignal.createdAt).getTime() / 1000) : undefined}
              signalPrice={
                selectedSignal.entryPrice ??
                (selectedSignal.entryRangeMin != null && selectedSignal.entryRangeMax != null
                  ? (selectedSignal.entryRangeMin + selectedSignal.entryRangeMax) / 2
                  : undefined)
              }
              entryRangeMin={selectedSignal.entryRangeMin ?? undefined}
              entryRangeMax={selectedSignal.entryRangeMax ?? undefined}
              signalType={selectedSignal.orderType as 'BUY' | 'SELL'}
              stopLoss={selectedSignal.stopLoss ?? undefined}
              takeProfitLevels={tpLevels.length > 0 ? tpLevels : undefined}
              planData={planData}
              provider={provider}
            />
          );
        })()
      )}
    </div>
  );
}
