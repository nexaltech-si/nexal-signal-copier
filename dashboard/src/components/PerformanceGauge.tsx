'use client'

import { ResponsiveContainer, PieChart, Pie, Cell } from 'recharts'

interface PerformanceGaugeProps {
  value: number
  label: string
  subLabel?: string
  size?: number
  color?: string
}

export default function PerformanceGauge({ 
  value, 
  label, 
  subLabel, 
  size = 120, 
  color = '#10b981' 
}: PerformanceGaugeProps) {
  const data = [
    { value: value },
    { value: 100 - value }
  ]

  return (
    <div className="flex flex-col items-center justify-center relative" style={{ width: size, height: size }}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={data}
            cx="50%"
            cy="50%"
            innerRadius="70%"
            outerRadius="90%"
            startAngle={90}
            endAngle={-270}
            paddingAngle={0}
            dataKey="value"
            stroke="none"
          >
            <Cell fill={color} />
            <Cell fill="rgba(0,0,0,0.05)" />
          </Pie>
        </PieChart>
      </ResponsiveContainer>
      
      <div className="absolute inset-0 flex flex-col items-center justify-center pt-1">
        <span className="text-xl font-black tracking-tighter" style={{ color }}>
          {value.toFixed(0)}%
        </span>
        <span className="text-[9px] text-muted-foreground font-bold uppercase tracking-wider">
          {label}
        </span>
        {subLabel && (
           <span className="text-[8px] text-muted-foreground/60">
             {subLabel}
           </span>
        )}
      </div>
    </div>
  )
}
