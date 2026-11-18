'use client'

import { ResponsiveContainer, PieChart, Pie, Cell, Label } from 'recharts'

interface DrawdownGaugeProps {
  value: number
  limit: number
  label: string
  size?: number
}

export default function DrawdownGauge({ value, limit, label, size = 160 }: DrawdownGaugeProps) {
  const percentage = Math.min(100, (value / limit) * 100)
  const data = [
    { value: percentage },
    { value: 100 - percentage }
  ]

  const getColor = () => {
    if (percentage >= 90) return '#ef4444' // red-500
    if (percentage >= 70) return '#f97316' // orange-500
    if (percentage >= 40) return '#eab308' // yellow-500
    return '#10b981' // emerald-500
  }

  const color = getColor()

  return (
    <div className="flex flex-col items-center justify-center relative pointer-events-none" style={{ width: size, height: size }}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={data}
            cx="50%"
            cy="50%"
            innerRadius="75%"
            outerRadius="95%"
            startAngle={225}
            endAngle={-45}
            paddingAngle={0}
            dataKey="value"
            stroke="none"
          >
            <Cell fill={color} />
            <Cell fill="rgba(0,0,0,0.05)" />
          </Pie>
        </PieChart>
      </ResponsiveContainer>
      
      <div className="absolute inset-0 flex flex-col items-center justify-center pt-2">
        <span className="text-2xl font-bold tracking-tight" style={{ color }}>
          {value.toFixed(2)}%
        </span>
        <span className="text-[10px] text-muted-foreground font-medium uppercase tracking-wider">
          {label}
        </span>
        <span className="text-[9px] text-muted-foreground/60 mt-0.5">
          Limit: {limit}%
        </span>
      </div>
    </div>
  )
}
