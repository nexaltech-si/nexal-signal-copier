'use client'

import { useEffect, useState } from 'react'
import { Sun, Moon } from 'lucide-react'
import { cn } from '@/lib/utils'

export default function DarkModeToggle({
  className,
  size = 'default',
}: {
  className?: string
  size?: 'default' | 'sm' | 'xs'
}) {
  const [isDark, setIsDark] = useState(true)

  useEffect(() => {
    // Read persisted preference; default to dark
    const saved = localStorage.getItem('theme')
    const dark = saved ? saved === 'dark' : true
    setIsDark(dark)
    document.documentElement.classList.toggle('dark', dark)
  }, [])

  const toggle = () => {
    const next = !isDark
    setIsDark(next)
    document.documentElement.classList.toggle('dark', next)
    localStorage.setItem('theme', next ? 'dark' : 'light')
  }

  return (
    <button
      onClick={toggle}
      aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
      title={isDark ? 'Light mode' : 'Dark mode'}
      className={cn(
        'relative flex items-center justify-center rounded-full transition-all duration-200 ease-in-out',
        'hover:bg-accent border border-border',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
        size === 'xs' ? 'h-7 w-7' : size === 'sm' ? 'h-8 w-8' : 'h-9 w-9',
        className,
      )}
    >
      <Sun className={cn(
        'h-3.5 w-3.5 text-gold absolute transition-all duration-300',
        isDark ? 'scale-0 opacity-0' : 'scale-100 opacity-100'
      )} />
      <Moon className={cn(
        'h-3.5 w-3.5 text-primary absolute transition-all duration-300',
        isDark ? 'scale-100 opacity-100' : 'scale-0 opacity-0'
      )} />
    </button>
  )
}
