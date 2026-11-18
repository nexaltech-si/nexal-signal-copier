import { useCallback, useEffect, useRef, useState } from 'react';

export const REPLAY_SPEEDS = [1, 2, 5, 10] as const;
export type ReplaySpeed = (typeof REPLAY_SPEEDS)[number];

const BASE_STEP_MS = 700; // ms between bar reveals at 1x

interface UseChartReplayOptions {
  /** Total number of bars available once the replay window is fully revealed. */
  totalBars: number;
  /** Index of the bar the replay should start on (e.g. the signal's entry candle). */
  startIndex: number;
}

interface UseChartReplayResult {
  /** Whether replay mode is currently active. */
  isReplaying: boolean;
  /** Whether playback is currently advancing bars automatically. */
  isPlaying: boolean;
  /** Playback speed multiplier. */
  speed: ReplaySpeed;
  /** Number of bars currently revealed (from the start of the series). */
  revealedCount: number;
  /** True once revealedCount has reached totalBars. */
  isAtEnd: boolean;
  startReplay: () => void;
  stopReplay: () => void;
  play: () => void;
  pause: () => void;
  stepForward: () => void;
  stepBackward: () => void;
  setSpeed: (speed: ReplaySpeed) => void;
  /** Jump the reveal cursor to an arbitrary bar index (clamped). */
  seekTo: (index: number) => void;
}

export function useChartReplay({ totalBars, startIndex }: UseChartReplayOptions): UseChartReplayResult {
  const [isReplaying, setIsReplaying] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [speed, setSpeed] = useState<ReplaySpeed>(1);
  const [revealedCount, setRevealedCount] = useState(totalBars);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const clamp = useCallback(
    (n: number) => Math.max(1, Math.min(totalBars, n)),
    [totalBars]
  );

  const startReplay = useCallback(() => {
    setIsReplaying(true);
    setIsPlaying(false);
    setRevealedCount(clamp(startIndex + 1));
  }, [clamp, startIndex]);

  const stopReplay = useCallback(() => {
    setIsReplaying(false);
    setIsPlaying(false);
    setRevealedCount(totalBars);
  }, [totalBars]);

  const play = useCallback(() => {
    if (!isReplaying) return;
    setIsPlaying(true);
  }, [isReplaying]);

  const pause = useCallback(() => setIsPlaying(false), []);

  const stepForward = useCallback(() => {
    setRevealedCount((c) => clamp(c + 1));
  }, [clamp]);

  const stepBackward = useCallback(() => {
    setRevealedCount((c) => clamp(c - 1));
  }, [clamp]);

  const seekTo = useCallback(
    (index: number) => {
      setRevealedCount(clamp(index + 1));
    },
    [clamp]
  );

  // Auto-advance while playing
  useEffect(() => {
    if (!isPlaying || !isReplaying) {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      return;
    }

    intervalRef.current = setInterval(() => {
      setRevealedCount((c) => {
        if (c >= totalBars) {
          setIsPlaying(false);
          return c;
        }
        return c + 1;
      });
    }, BASE_STEP_MS / speed);

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [isPlaying, isReplaying, speed, totalBars]);

  // Reset the revealed window whenever the data set itself changes (new symbol/timeframe/signal)
  // while not actively replaying, so the chart shows full data by default.
  useEffect(() => {
    if (!isReplaying) {
      setRevealedCount(totalBars);
    }
  }, [totalBars, isReplaying]);

  return {
    isReplaying,
    isPlaying,
    speed,
    revealedCount,
    isAtEnd: revealedCount >= totalBars,
    startReplay,
    stopReplay,
    play,
    pause,
    stepForward,
    stepBackward,
    setSpeed,
    seekTo,
  };
}
