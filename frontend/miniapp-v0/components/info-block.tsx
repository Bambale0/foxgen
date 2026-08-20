'use client'

import { cn } from '@/lib/utils'
import { Lightbulb, RefreshCw, Gift } from 'lucide-react'

const tips = [
  {
    icon: Lightbulb,
    title: 'Референсы',
    description: 'Добавляйте референсы для лучшего контроля над результатом генерации.',
    color: 'gold',
  },
  {
    icon: RefreshCw,
    title: 'Синхронизация',
    description: 'Статусы задач обновляются автоматически, а готовые результаты появляются в истории.',
    color: 'cyan',
  },
  {
    icon: Gift,
    title: 'Стартовый бонус',
    description: 'На старте доступно 25🍌, чтобы спокойно протестировать первые сценарии.',
    color: 'success',
  },
]

const colorClasses: Record<string, { bg: string; icon: string; border: string }> = {
  gold: {
    bg: 'bg-gold/5',
    icon: 'text-gold',
    border: 'border-gold/20',
  },
  cyan: {
    bg: 'bg-cyan/5',
    icon: 'text-cyan',
    border: 'border-cyan/20',
  },
  success: {
    bg: 'bg-success/5',
    icon: 'text-success',
    border: 'border-success/20',
  },
}

export function InfoBlock() {
  return (
    <div className="space-y-3">
      <h3 className="font-serif text-lg font-semibold text-foreground">
        Полезные советы
      </h3>
      
      <div className="space-y-3">
        {tips.map((tip) => {
          const Icon = tip.icon
          const colors = colorClasses[tip.color]
          
          return (
            <div
              key={tip.title}
              className={cn(
                "flex items-start gap-3 p-4 rounded-xl",
                colors.bg,
                "border",
                colors.border
              )}
            >
              <div className={cn(
                "w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0",
                "bg-background/50"
              )}>
                <Icon className={cn("w-4 h-4", colors.icon)} />
              </div>
              <div>
                <h4 className="text-sm font-medium text-foreground mb-0.5">
                  {tip.title}
                </h4>
                <p className="text-xs text-muted-foreground leading-relaxed">
                  {tip.description}
                </p>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
