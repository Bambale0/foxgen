'use client'

import { ArrowUpRight, Bot, Image, Sparkles, Video } from 'lucide-react'
import { cn } from '@/lib/utils'

interface QuickActionGridProps {
  onPhotoClick: () => void
  onVideoClick: () => void
  onMotionClick?: () => void
  onBalanceClick: () => void
  onAssistantClick: () => void
}

const actionStyles = [
  'fox-surface-accent',
  'fox-surface border-gold/20',
  'fox-surface border-gold/15',
  'fox-surface border-gold/15',
]

export function QuickActionGrid({
  onPhotoClick,
  onVideoClick,
  onMotionClick,
  onAssistantClick,
}: QuickActionGridProps) {
  const items = [
    {
      label: 'Создать фото',
      description: 'Картинки, арты, редактирование',
      icon: Image,
      onClick: onPhotoClick,
    },
    {
      label: 'Создать видео',
      description: 'Динамичные сцены и анимация',
      icon: Video,
      onClick: onVideoClick,
    },
    {
      label: 'Оживить фото',
      description: 'Motion и движение по референсу',
      icon: Sparkles,
      onClick: onMotionClick || onVideoClick,
    },
    {
      label: 'AI-помощник',
      description: 'Идея, промпт и быстрый старт',
      icon: Bot,
      onClick: onAssistantClick,
    },
  ]

  return (
    <div className="grid grid-cols-2 gap-2.5 sm:gap-3 lg:mx-auto lg:max-w-[920px]">
      {items.map((item, index) => {
        const Icon = item.icon

        return (
          <button
            key={item.label}
            type="button"
            onClick={item.onClick}
            className={cn(
              'group relative min-w-0 overflow-hidden rounded-[22px] p-3.5 text-left sm:p-4',
              'min-h-[132px] transition-all duration-200 hover:-translate-y-0.5 active:scale-[0.985]',
              actionStyles[index],
            )}
          >
            <div className="absolute -right-8 -top-10 h-24 w-24 rounded-full bg-gold/[0.08] blur-2xl transition-opacity group-hover:opacity-100" />
            <div className="relative flex h-full flex-col justify-between gap-4">
              <div className="flex items-start justify-between gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-gold/25 bg-gold/[0.09] text-gold shadow-[0_0_22px_rgba(255,106,0,0.08)]">
                  <Icon className="h-5 w-5" />
                </div>
                <ArrowUpRight className="h-4 w-4 text-muted-foreground transition-all group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-gold" />
              </div>

              <div className="min-w-0">
                <div className="text-sm font-bold text-foreground sm:text-[15px]">{item.label}</div>
                <div className="mt-1 line-clamp-2 text-[10px] leading-relaxed text-muted-foreground sm:text-[11px]">
                  {item.description}
                </div>
              </div>
            </div>
          </button>
        )
      })}
    </div>
  )
}
