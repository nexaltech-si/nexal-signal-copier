import React from 'react'

interface InstrumentIconProps {
  type: 'gold' | 'silver' | 'platinum' | 'palladium' | 'oil' | 'gas' | 'copper' | 'index' | 'crypto'
  className?: string
}

export default function InstrumentIcon({ type, className = 'w-6 h-6' }: InstrumentIconProps) {
  const icons = {
    gold: (
      <svg viewBox="0 0 24 24" fill="none" className={className}>
        <path d="M2 16L4 8H20L22 16H2Z" fill="currentColor" />
        <path d="M4 8L6 4H18L20 8H4Z" fill="currentColor" opacity="0.8" />
        <path d="M8 12H16" stroke="currentColor" strokeWidth="0.5" strokeLinecap="round" opacity="0.5" />
      </svg>
    ),
    silver: (
      <svg viewBox="0 0 24 24" fill="none" className={className}>
        <path d="M2 16L4 8H20L22 16H2Z" fill="white" />
        <path d="M4 8L6 4H18L20 8H4Z" fill="white" opacity="0.8" />
      </svg>
    ),
    platinum: (
      <svg viewBox="0 0 24 24" fill="none" className={className}>
        <path d="M4 4H20V20H4V4Z" fill="currentColor" opacity="0.2" />
        <path d="M8 8H16V16H8V8Z" fill="currentColor" />
        <path d="M2 2L22 22M22 2L2 22" stroke="currentColor" strokeWidth="1" opacity="0.3" />
      </svg>
    ),
    palladium: (
      <svg viewBox="0 0 24 24" fill="none" className={className}>
        <circle cx="12" cy="12" r="8" stroke="currentColor" strokeWidth="2" />
        <path d="M12 8V16M8 12H16" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      </svg>
    ),
    oil: (
      <svg viewBox="0 0 24 24" fill="none" className={className}>
        <path d="M12 2C12 2 6 8 6 13C6 16.3137 8.68629 19 12 19C15.3137 19 18 16.3137 18 13C18 8 12 2 12 2Z" fill="currentColor" />
        <path d="M12 6C12 6 9 9 9 12" stroke="white" strokeWidth="1" strokeLinecap="round" opacity="0.5" />
      </svg>
    ),
    gas: (
      <svg viewBox="0 0 24 24" fill="none" className={className}>
        <path d="M13 2L3 14H12V22L22 10H13V2Z" fill="currentColor" />
      </svg>
    ),
    copper: (
      <svg viewBox="0 0 24 24" fill="none" className={className}>
        <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2" />
        <path d="M12 12L16 16M12 12L8 8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      </svg>
    ),
    index: (
      <svg viewBox="0 0 24 24" fill="none" className={className}>
        <path d="M4 20L4 4M4 20L20 20M4 20L10 14L14 16L20 8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="20" cy="8" r="2" fill="currentColor" />
      </svg>
    ),
    crypto: (
      <svg viewBox="0 0 24 24" fill="none" className={className}>
        <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2" />
        <path d="M9 8H13C14.1046 8 15 8.89543 15 10C15 11.1046 14.1046 12 13 12H9M9 12H14C15.1046 12 16 12.8954 16 14C16 15.1046 15.1046 16 14 16H9M9 7V17" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      </svg>
    ),
  }

  return icons[type] || null
}
