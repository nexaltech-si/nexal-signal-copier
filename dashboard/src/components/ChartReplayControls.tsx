'use client';

import { Play, Pause, SkipForward, Rewind, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Slider } from '@/components/ui/slider';
import { REPLAY_SPEEDS, type ReplaySpeed } from '@/hooks/useChartReplay';

interface ChartReplayControlsProps {
  isPlaying: boolean;
  speed: ReplaySpeed;
  revealedCount: number;
  totalBars: number;
  isAtEnd: boolean;
  onPlay: () => void;
  onPause: () => void;
  onStepForward: () => void;
  onStepBackward: () => void;
  onSpeedChange: (speed: ReplaySpeed) => void;
  onSeek: (index: number) => void;
  onExit: () => void;
}

export default function ChartReplayControls({
  isPlaying,
  speed,
  revealedCount,
  totalBars,
  isAtEnd,
  onPlay,
  onPause,
  onStepForward,
  onStepBackward,
  onSpeedChange,
  onSeek,
  onExit,
}: ChartReplayControlsProps) {
  return (
    <div className="flex items-center gap-2 px-3 py-2 rounded-lg border border-primary/30 bg-primary/5 flex-wrap">
      <Button
        variant="outline"
        size="sm"
        className="h-7 px-2"
        title="Step back one bar"
        onClick={onStepBackward}
        disabled={revealedCount <= 1}
      >
        <Rewind className="h-3.5 w-3.5" />
      </Button>

      <Button
        variant="default"
        size="sm"
        className="h-7 px-3"
        title={isPlaying ? 'Pause' : 'Play'}
        onClick={isPlaying ? onPause : onPlay}
        disabled={isAtEnd && !isPlaying}
      >
        {isPlaying ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
      </Button>

      <Button
        variant="outline"
        size="sm"
        className="h-7 px-2"
        title="Step forward one bar"
        onClick={onStepForward}
        disabled={isAtEnd}
      >
        <SkipForward className="h-3.5 w-3.5" />
      </Button>

      <div className="flex items-center gap-0.5 border border-border rounded-md p-0.5">
        {REPLAY_SPEEDS.map((s) => (
          <button
            key={s}
            onClick={() => onSpeedChange(s)}
            className={`text-[10px] font-semibold px-1.5 py-0.5 rounded transition-colors ${
              speed === s
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:text-foreground hover:bg-muted'
            }`}
          >
            {s}x
          </button>
        ))}
      </div>

      <div className="flex-1 min-w-[120px] flex items-center gap-2">
        <Slider
          value={[revealedCount]}
          min={1}
          max={totalBars}
          step={1}
          onValueChange={([v]) => onSeek(v - 1)}
          className="flex-1"
        />
        <span className="text-[10px] text-muted-foreground font-mono whitespace-nowrap">
          {revealedCount}/{totalBars}
        </span>
      </div>

      <Button
        variant="outline"
        size="sm"
        className="h-7 px-2"
        title="Exit replay"
        onClick={onExit}
      >
        <X className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}
