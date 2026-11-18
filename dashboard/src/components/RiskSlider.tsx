import { useState } from 'react'

interface RiskSliderProps {
  label: string
  value: number
  min: number
  max: number
  unit?: string
  info?: string
  onChange: (value: number) => void
  currentUsage?: string
}

export default function RiskSlider({ 
  label, 
  value, 
  min, 
  max, 
  unit = '%',
  info,
  onChange,
  currentUsage 
}: RiskSliderProps) {
  const percentage = ((value - min) / (max - min)) * 100
  const [isHovering, setIsHovering] = useState(false)
  const [isDragging, setIsDragging] = useState(false)
  const [showTooltip, setShowTooltip] = useState(false)

  return (
    <div className="p-4 border-b border-border/50 last:border-0">
      <div className="flex justify-between items-center gap-2 mb-3">
        <div className="flex items-center gap-2">
          <span className="text-sm font-bold text-foreground">{label}</span>
          {info && (
            <div className="relative">
              <span 
                className="w-4 h-4 inline-flex items-center justify-center rounded-full bg-primary/10 text-primary text-[10px] font-bold cursor-help"
                onMouseEnter={() => setShowTooltip(true)}
                onMouseLeave={() => setShowTooltip(false)}
              >
                i
              </span>
              {showTooltip && (
                <div className="absolute left-0 top-6 z-50 w-64 p-3 bg-popover border border-border text-foreground text-xs rounded-lg shadow-lg">
                  {info}
                </div>
              )}
            </div>
          )}
        </div>
        {currentUsage && (
          <span className="text-sm font-bold text-foreground/80">{currentUsage}</span>
        )}
      </div>
      <div className="grid grid-cols-[52px_1fr_52px] gap-3 items-center">
        <span className="text-xs text-muted-foreground text-center">{min}{unit}</span>
        <div className="relative">
          <input
            type="range"
            min={min}
            max={max}
            value={value}
            onChange={(e) => onChange(parseFloat(e.target.value))}
            onMouseEnter={() => setIsHovering(true)}
            onMouseLeave={() => {
              setIsHovering(false)
              setIsDragging(false)
            }}
            onMouseDown={() => setIsDragging(true)}
            onMouseUp={() => setIsDragging(false)}
            className="w-full h-1.5 rounded-full appearance-none cursor-pointer"
            style={{
              background: `linear-gradient(90deg, #29ADFF 0%, #06b6d4 100%)`,
            }}
          />
          {(isHovering || isDragging) && (
            <div
              className="absolute -top-10 transform -translate-x-1/2 bg-popover border border-border text-foreground text-xs font-bold px-2 py-1 rounded shadow-lg whitespace-nowrap"
              style={{ left: `${percentage}%` }}
            >
              {value}{unit}
            </div>
          )}
          <style jsx>{`
            input[type="range"]::-webkit-slider-thumb {
              appearance: none;
              width: 18px;
              height: 18px;
              border-radius: 50%;
              background: #0D1624;
              border: 3px solid #29ADFF;
              box-shadow: 0 2px 8px rgba(41, 173, 255, 0.3);
              cursor: pointer;
            }
            input[type="range"]::-moz-range-thumb {
              width: 18px;
              height: 18px;
              border-radius: 50%;
              background: #0D1624;
              border: 3px solid #29ADFF;
              box-shadow: 0 2px 8px rgba(41, 173, 255, 0.3);
              cursor: pointer;
            }
          `}</style>
        </div>
        <span className="text-xs text-muted-foreground text-center">{max}{unit}</span>
      </div>
    </div>
  )
}
