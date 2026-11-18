'use client'

import { useState, useEffect } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'

interface CollapsibleSectionProps {
  id: string
  title: string
  subtitle?: string | React.ReactNode
  children: React.ReactNode
  defaultOpen?: boolean
  collapsedContent?: React.ReactNode
}

export default function CollapsibleSection({
  id,
  title,
  subtitle,
  children,
  defaultOpen = true,
  collapsedContent,
}: CollapsibleSectionProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen)
  const [isMounted, setIsMounted] = useState(false)

  // Load state from localStorage on mount
  useEffect(() => {
    const saved = localStorage.getItem(`collapsible-${id}`)
    if (saved !== null) {
      setIsOpen(saved === 'true')
    }
    setIsMounted(true)
  }, [id])

  // Save state to localStorage when it changes
  const handleOpenChange = (open: boolean) => {
    setIsOpen(open)
    if (isMounted) {
      localStorage.setItem(`collapsible-${id}`, String(open))
    }
  }

  // Prevent hydration mismatch by not rendering until mounted
  if (!isMounted) {
    return (
      <div className="mb-4">
        <div className="flex items-center justify-between mb-2.5 px-1.5">
          <h2 className="text-[16px] font-bold text-foreground tracking-[-0.03em]">{title}</h2>
          {subtitle && (
            <div className="text-[11px] text-[#6f778f] flex items-center gap-1.5 font-medium">
              {subtitle}
            </div>
          )}
        </div>
        {children}
      </div>
    )
  }

  return (
    <Collapsible open={isOpen} onOpenChange={handleOpenChange} className="mb-3 md:mb-6">
      <div className="flex items-center justify-between mb-3 px-1.5 md:px-1">
        <h2 className="text-[16px] md:text-sm font-bold text-foreground md:uppercase tracking-[-0.03em] md:tracking-wider leading-none">{title}</h2>
        <div className="flex items-center gap-3">
          {subtitle && (
            <div className="text-[11px] md:text-xs text-[#6f778f] md:text-muted-foreground font-medium flex items-center gap-1.5">
              {subtitle}
            </div>
          )}
          <CollapsibleTrigger className="flex items-center justify-center p-1.5 text-muted-foreground/70 hover:text-foreground hover:bg-muted rounded-lg transition-all md:relative md:z-10 bg-white/60 md:bg-transparent shadow-[0_2px_8px_rgba(24,31,76,0.03)] md:shadow-none">
            {isOpen ? (
              <ChevronUp className="h-4 w-4" />
            ) : (
              <ChevronDown className="h-4 w-4" />
            )}
          </CollapsibleTrigger>
        </div>
      </div>
      
      {/* Show collapsed content when collapsed */}
      {!isOpen && collapsedContent && (
        <div className="animate-in fade-in slide-in-from-top-1 duration-200">{collapsedContent}</div>
      )}
      
      {/* Show full content when expanded */}
      <CollapsibleContent className="animate-in fade-in slide-in-from-top-1 duration-200">
        {children}
      </CollapsibleContent>
    </Collapsible>
  )
}
