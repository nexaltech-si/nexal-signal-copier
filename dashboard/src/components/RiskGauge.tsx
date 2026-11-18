interface RiskGaugeProps {
  value: number
  max: number
  status: 'Low Risk' | 'Medium Risk' | 'High Risk' | 'Critical'
}

export default function RiskGauge({ value, max, status }: RiskGaugeProps) {
  const percentage = (value / max) * 100
  
  // Calculate the rotation for the gauge based on percentage
  const rotation = (percentage / 100) * 360
  
  // Determine color based on status
  const getStatusColor = () => {
    switch (status) {
      case 'Low Risk':
        return '#22c55e'
      case 'Medium Risk':
        return '#f59e0b'
      case 'High Risk':
        return '#ef4444'
      case 'Critical':
        return '#dc2626'
      default:
        return '#22c55e'
    }
  }

  return (
    <div className="relative">
      <div 
        className="w-[180px] h-[180px] rounded-full relative"
        style={{
          background: `conic-gradient(
            ${getStatusColor()} ${rotation}deg,
            #e5e7eb ${rotation}deg 360deg
          )`
        }}
      >
        <div className="absolute inset-[18px] rounded-full bg-card shadow-sm" />
        <div className="absolute inset-0 flex flex-col items-center justify-center z-10 text-center">
          <div className="text-[38px] font-extrabold leading-none text-foreground">
            {value}
          </div>
          <div className="text-sm text-muted-foreground mt-1">
            / {max}
          </div>
          <div 
            className="text-xs font-bold mt-2"
            style={{ color: getStatusColor() }}
          >
            {status}
          </div>
        </div>
      </div>
    </div>
  )
}
