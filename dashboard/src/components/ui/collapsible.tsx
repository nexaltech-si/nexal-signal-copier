"use client"

import * as React from "react"
import { cn } from "@/lib/utils"

interface CollapsibleContextValue {
  isOpen: boolean
  onToggle: () => void
}

const CollapsibleContext = React.createContext<CollapsibleContextValue | null>(null)

const useCollapsible = () => {
  const context = React.useContext(CollapsibleContext)
  if (!context) {
    throw new Error("Collapsible components must be used within a Collapsible")
  }
  return context
}

interface CollapsibleProps {
  children: React.ReactNode
  open?: boolean
  onOpenChange?: (open: boolean) => void
  className?: string
}

const Collapsible = React.forwardRef<HTMLDivElement, CollapsibleProps>(
  ({ children, open, onOpenChange, className }, ref) => {
    const [isOpen, setIsOpen] = React.useState(open ?? true)

    React.useEffect(() => {
      if (open !== undefined) {
        setIsOpen(open)
      }
    }, [open])

    const handleToggle = React.useCallback(() => {
      const newState = !isOpen
      setIsOpen(newState)
      onOpenChange?.(newState)
    }, [isOpen, onOpenChange])

    const contextValue = React.useMemo(
      () => ({ isOpen, onToggle: handleToggle }),
      [isOpen, handleToggle]
    )

    return (
      <CollapsibleContext.Provider value={contextValue}>
        <div ref={ref} className={cn(className)} data-state={isOpen ? "open" : "closed"}>
          {children}
        </div>
      </CollapsibleContext.Provider>
    )
  }
)
Collapsible.displayName = "Collapsible"

interface CollapsibleTriggerProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {}

const CollapsibleTrigger = React.forwardRef<HTMLButtonElement, CollapsibleTriggerProps>(
  ({ children, className, onClick, ...props }, ref) => {
    const { onToggle } = useCollapsible()
    
    return (
      <button
        ref={ref}
        type="button"
        onClick={(e) => {
          onToggle()
          onClick?.(e)
        }}
        className={className}
        {...props}
      >
        {children}
      </button>
    )
  }
)
CollapsibleTrigger.displayName = "CollapsibleTrigger"

interface CollapsibleContentProps extends React.HTMLAttributes<HTMLDivElement> {}

const CollapsibleContent = React.forwardRef<HTMLDivElement, CollapsibleContentProps>(
  ({ children, className, ...props }, ref) => {
    const { isOpen } = useCollapsible()
    
    if (!isOpen) return null
    
    return (
      <div
        ref={ref}
        className={cn("overflow-hidden", className)}
        {...props}
      >
        {children}
      </div>
    )
  }
)
CollapsibleContent.displayName = "CollapsibleContent"

export { Collapsible, CollapsibleTrigger, CollapsibleContent }
