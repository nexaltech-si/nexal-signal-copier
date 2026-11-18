'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts'

interface PerformanceChartProps {
  data: Array<{
    date: string
    profit: number
    trades: number
  }>
}

export default function PerformanceChart({ data }: PerformanceChartProps) {
  return (
    <Card className="col-span-4">
      <CardHeader>
        <CardTitle>Performance Over Time (Last 30 Days)</CardTitle>
      </CardHeader>
      <CardContent className="pl-2">
        <ResponsiveContainer width="100%" height={350}>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis
              dataKey="date"
              stroke="#888888"
              fontSize={12}
              tickLine={false}
              axisLine={false}
            />
            <YAxis
              stroke="#888888"
              fontSize={12}
              tickLine={false}
              axisLine={false}
              tickFormatter={(value) => `$${value}`}
            />
            <Tooltip
              contentStyle={{ 
                backgroundColor: '#0D1624', 
                border: '1px solid #e5e7eb', 
                borderRadius: '8px',
                boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)'
              }}
              labelStyle={{ color: '#1f2937', fontWeight: 600 }}
              itemStyle={{ color: '#374151' }}
              formatter={(value: number, name: string) => {
                if (name === 'profit') return [`$${value.toFixed(2)}`, 'Profit/Loss']
                return [value, 'Trades']
              }}
            />
            <Legend />
            <Line
              type="monotone"
              dataKey="profit"
              stroke="#10b981"
              strokeWidth={2}
              name="Profit/Loss"
            />
          </LineChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}
