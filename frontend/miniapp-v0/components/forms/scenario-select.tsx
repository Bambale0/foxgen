'use client'

import type { ScenarioType } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Type, ImageIcon, Video, Headphones, UserRound } from 'lucide-react'

interface ScenarioSelectProps {
  scenarios: ScenarioType[]
  value: ScenarioType
  onChange: (value: ScenarioType) => void
}

const scenarioConfig: Record<ScenarioType, {
  label: string
  icon: typeof Type
  description: string
}> = {
  'text': {
    label: 'Текст → Видео',
    icon: Type,
    description: 'Генерация из текста',
  },
  'imgtxt': {
    label: 'Фото + Текст',
    icon: ImageIcon,
    description: 'Анимация изображения',
  },
  'video': {
    label: 'Видео + Текст',
    icon: Video,
    description: 'Стилизация видео',
  },
  'audio': {
    label: 'Audio ID',
    icon: Headphones,
    description: 'Голосовой ID',
  },
  'character': {
    label: 'Character ID',
    icon: UserRound,
    description: 'ID персонажа',
  },
  'avatar': {
    label: 'Avatar',
    icon: UserRound,
    description: 'Аватар',
  },
}

export function ScenarioSelect({ scenarios, value, onChange }: ScenarioSelectProps) {
  const allScenarios: ScenarioType[] = ['text', 'imgtxt', 'video', 'audio', 'character', 'avatar']

  return (
    <div className="grid min-w-0 grid-cols-3 gap-2 sm:grid-cols-6">
      {allScenarios.map((scenario) => {
        const config = scenarioConfig[scenario]
        const Icon = config.icon
        const isSelected = scenario === value
        const isAvailable = scenarios.includes(scenario)
        
        return (
          <button
            key={scenario}
            onClick={() => isAvailable && onChange(scenario)}
            disabled={!isAvailable}
            className={cn(
              "min-h-16 min-w-0 flex flex-col items-center justify-center gap-1.5 rounded-xl p-2",
              "border transition-all duration-200",
              isSelected 
                ? "bg-cyan/15 border-cyan/50 text-cyan" 
                : isAvailable
                  ? "bg-secondary/50 border-border/50 text-muted-foreground hover:bg-secondary hover:text-foreground"
                  : "bg-secondary/20 border-border/30 text-muted-foreground/40 cursor-not-allowed"
            )}
          >
            <Icon className="h-4 w-4 shrink-0" />
            <span className="max-w-full text-center text-[10px] font-medium leading-tight">
              {config.label}
            </span>
          </button>
        )
      })}
    </div>
  )
}
