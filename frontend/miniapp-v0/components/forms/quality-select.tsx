'use client'

import { cn } from '@/lib/utils'

interface QualitySelectProps {
  qualities: string[]
  value: string
  onChange: (value: string) => void
}

const qualityLabels: Record<string, string> = {
  basic: 'Быстро',
  high: 'Высокое',
  standard: 'Стандарт',
  hd: 'HD',
  ultra: 'Максимум',
  "1K": "1K",
  "2K": "2K",
  "4K": "4K",
}

export function QualitySelect({ qualities, value, onChange }: QualitySelectProps) {
  return (
    <div role="group" aria-label="Качество" className="flex gap-2">
      {qualities.map((quality) => {
        const isSelected = quality === value
        
        return (
          <button
            type="button"
            key={quality}
            aria-pressed={isSelected}
            onClick={() => onChange(quality)}
            className={cn(
              "flex-1 min-h-11 px-3 py-2 rounded-lg text-xs font-medium",
              "border transition-all duration-200",
              isSelected 
                ? "bg-gold/15 border-gold/50 text-gold" 
                : "bg-secondary/50 border-border/50 text-muted-foreground hover:bg-secondary hover:text-foreground"
            )}
          >
            {qualityLabels[quality] || quality}
          </button>
        )
      })}
    </div>
  )
}
