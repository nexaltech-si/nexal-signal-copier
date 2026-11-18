"use client"

import { GripVertical } from "lucide-react"
import { Group, Panel, Separator } from "react-resizable-panels"
import type { GroupProps, SeparatorProps } from "react-resizable-panels"

import { cn } from "@/lib/utils"

const ResizablePanelGroup = ({
  className,
  ...props
}: GroupProps) => (
  <Group
    className={cn("flex h-full w-full", className)}
    {...props}
  />
)

const ResizablePanel = Panel

const ResizableHandle = ({
  withHandle,
  className,
  ...props
}: SeparatorProps & { withHandle?: boolean }) => (
  <Separator
    className={cn(
      "relative bg-border transition-colors hover:bg-primary/30 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
      // vertical group → horizontal bar
      "h-1 w-full cursor-row-resize",
      className
    )}
    {...props}
  >
    {withHandle && (
      <div className="absolute left-1/2 top-1/2 z-10 flex h-3 w-6 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-sm border border-border bg-card shadow-sm">
        <GripVertical className="h-3 w-3 text-muted-foreground/70 rotate-90" />
      </div>
    )}
  </Separator>
)

export { ResizablePanelGroup, ResizablePanel, ResizableHandle }
