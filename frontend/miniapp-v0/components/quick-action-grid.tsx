'use client'

import { Image, Video, Sparkles, Bot } from 'lucide-react'
import { cn } from '@/lib/utils'

interface QuickActionGridProps {
  onPhotoClick: () => void
  onVideoClick: () => void
  onMotionClick?: () => void
  onBalanceClick: () => void
  onAssistantClick: () => void
}

const actionStyles = [
  'text-gold border-gold/30 bg-gold/10',
  'text-cyan border-cyan/30 bg-cyan/10',
  'text-purple-300 border-purple-400/25 bg-purple-500/10',
  'text-emerald-300 border-emerald-400/25 bg-emerald-500/10',
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
      shortLabel: 'Фото',
      icon: Image,
      onClick: onPhotoClick,
    },
    {
      label: 'Создать видео',
      shortLabel: 'Видео',
      icon: Video,
      onClick: onVideoClick,
    },
    {
      label: 'Оживить фото',
      shortLabel: 'Оживить',
      icon: Sparkles,
      onClick: onMotionClick || onVideoClick,
    },
    {
      label: 'Помощник',
      shortLabel: 'Помощник',
      icon: Bot,
      onClick: onAssistantClick,
    },
  ]

  return (
    <div className="grid grid-cols-4 gap-2 sm:gap-3 lg:mx-auto lg:max-w-[920px]">
      {items.map((item, index) => {
        const Icon = item.icon

        return (
          <button
            key={item.label}
            type="button"
            onClick={item.onClick}
            className={cn(
              'group flex min-w-0 flex-col items-center gap-2 rounded-2xl py-3 text-center lg:py-2.5',
              'transition-all duration-200 active:scale-95',
              actionStyles[index]
            )}
          >
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-current/20 bg-background/45 shadow-sm lg:h-10 lg:w-10">
              <Icon className="h-5 w-5" />
            </div>
            <span className="w-full truncate px-1 text-[11px] font-medium text-foreground sm:text-xs lg:text-[11px]">
              {item.shortLabel}
            </span>
          </button>
        )
      })}
    </div>
  )
}
