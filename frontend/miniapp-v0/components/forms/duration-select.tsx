'use client'

import { cn } from '@/lib/utils'
import { PawPrint } from 'lucide-react'

interface DurationSelectProps {
  durations: number[]
  value: number
  onChange: (value: number) => void
  costs: Record<string, number>
}

export function DurationSelect({ durations, value, onChange, costs }: DurationSelectProps) {
  const formatCost = (raw: number) => Number(raw.toFixed(2)).toString()
  return (
    <div role="group" aria-label="Длительность" className="grid min-w-0 grid-cols-3 gap-2 sm:grid-cols-4">
      {durations.map((duration) => {
        const isSelected = duration === value
        const cost = costs[duration.toString()] || 0
        const perSecondCost = duration > 0 ? cost / duration : 0
        
        return (
          <button
            type="button"
            key={duration}
            aria-pressed={isSelected}
            onClick={() => onChange(duration)}
            className={cn(
              "min-w-0 justify-center flex items-center gap-1.5 min-h-11 px-2 py-2 rounded-lg",
              "border transition-all duration-200",
              isSelected 
                ? "bg-cyan/15 border-cyan/50 text-cyan" 
                : "bg-secondary/50 border-border/50 text-muted-foreground hover:bg-secondary hover:text-foreground"
            )}
          >
            <span className="shrink-0 text-xs font-medium">{duration}с</span>
            <span className={cn(
              "min-w-0 flex items-center gap-0.5 text-[11px]",
              isSelected ? "text-gold" : "text-gold/70"
            )}>
              <PawPrint className="h-3 w-3 shrink-0" />
              <span className="truncate">{formatCost(perSecondCost)}/с</span>
            </span>
          </button>
        )
      })}
    </div>
  )
}
