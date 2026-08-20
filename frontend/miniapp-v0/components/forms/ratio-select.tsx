'use client'

import { cn } from '@/lib/utils'

interface RatioSelectProps {
  ratios: string[]
  value: string
  onChange: (value: string) => void
}

const ratioIcons: Record<string, { width: number; height: number }> = {
  '1:1': { width: 16, height: 16 },
  '9:16': { width: 12, height: 20 },
  '16:9': { width: 20, height: 12 },
  '3:4': { width: 14, height: 18 },
  '4:3': { width: 18, height: 14 },
  '2:3': { width: 13, height: 19 },
  '3:2': { width: 19, height: 13 },
  'auto': { width: 16, height: 16 },
}

export function RatioSelect({ ratios, value, onChange }: RatioSelectProps) {
  return (
    <div className="grid min-w-0 grid-cols-3 gap-2 sm:grid-cols-4">
      {ratios.map((ratio) => {
        const icon = ratioIcons[ratio] || { width: 16, height: 16 }
        const isSelected = ratio === value
        
        return (
          <button
            key={ratio}
            onClick={() => onChange(ratio)}
            className={cn(
              "min-w-0 justify-center flex items-center gap-2 px-2 py-2 rounded-lg",
              "border transition-all duration-200",
              isSelected 
                ? "bg-gold/15 border-gold/50 text-gold" 
                : "bg-secondary/50 border-border/50 text-muted-foreground hover:bg-secondary hover:text-foreground"
            )}
          >
            <div 
              className={cn(
                "rounded-sm border",
                isSelected ? "border-gold/50 bg-gold/20" : "border-muted-foreground/30"
              )}
              style={{ 
                width: `${icon.width}px`, 
                height: `${icon.height}px` 
              }}
            />
            <span className="truncate text-xs font-medium">{ratio}</span>
          </button>
        )
      })}
    </div>
  )
}
