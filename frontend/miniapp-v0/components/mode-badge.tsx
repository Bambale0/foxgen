'use client'

import type { AppMode } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Radio, Wifi } from 'lucide-react'

interface ModeBadgeProps {
  mode: AppMode
}

export function ModeBadge({ mode }: ModeBadgeProps) {
  const isLive = mode === 'live'

  return (
    <div className={cn(
      "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium",
      "transition-all duration-300",
      isLive 
        ? "bg-success/15 text-success border border-success/30" 
        : "bg-cyan/15 text-cyan border border-cyan/30"
    )}>
      {isLive ? (
        <>
          <Wifi className="w-3 h-3" />
          <span>Онлайн</span>
          <span className="w-1.5 h-1.5 rounded-full bg-success animate-pulse" />
        </>
      ) : (
        <>
          <Radio className="w-3 h-3" />
          <span>Telegram</span>
        </>
      )}
    </div>
  )
}
