'use client'

import { useApp } from '@/lib/app-context'
import { cn } from '@/lib/utils'
import {
  Flame,
  Grid3X3,
  Image,
  Images,
  LayoutDashboard,
  Sparkles,
  UserRound,
  Video,
} from 'lucide-react'

const tabs = [
  { id: 0, label: 'Студия', icon: LayoutDashboard },
  { id: 1, label: 'Фото', icon: Image },
  { id: 2, label: 'Видео', icon: Video },
  { id: 3, label: 'Motion', icon: Sparkles },
  { id: 5, label: 'Тренды', icon: Flame },
  { id: 4, label: 'Лента', icon: Images },
  { id: 6, label: 'Сервисы', icon: Grid3X3 },
  { id: 7, label: 'Профиль', icon: UserRound },
]

export function TabNav() {
  const { activeTab, setActiveTab } = useApp()

  return (
    <nav className="fixed bottom-0 left-0 right-0 z-50 px-2 sm:px-3 lg:px-4">
      <div className="mx-auto w-full max-w-[900px]">
        <div className="glass-strong safe-bottom rounded-t-[22px] border border-b-0 border-white/[0.075] shadow-[0_-12px_42px_rgba(0,0,0,0.42)] sm:rounded-[22px] sm:border-b">
          <div className="overflow-x-auto px-1.5 py-1.5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            <div className="flex min-w-max items-stretch gap-1">
              {tabs.map((tab) => {
                const isActive = activeTab === tab.id
                const Icon = tab.icon

                return (
                  <button
                    key={tab.id}
                    type="button"
                    onClick={() => setActiveTab(tab.id)}
                    className={cn(
                      'relative flex min-w-[66px] flex-col items-center justify-center gap-1 rounded-[15px] px-2 py-2',
                      'transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                      isActive
                        ? 'bg-gold/[0.11] text-gold shadow-[inset_0_0_0_1px_rgba(255,106,0,0.16)]'
                        : 'text-muted-foreground hover:bg-white/[0.035] hover:text-foreground',
                    )}
                  >
                    {isActive && (
                      <span className="fox-accent-line absolute left-3 right-3 top-0 h-px" />
                    )}
                    <Icon className={cn('h-[18px] w-[18px]', isActive && 'drop-shadow-[0_0_7px_rgba(255,106,0,0.35)]')} strokeWidth={isActive ? 2.35 : 1.9} />
                    <span className="text-[9px] font-semibold tracking-[-0.01em]">{tab.label}</span>
                  </button>
                )
              })}
            </div>
          </div>
        </div>
      </div>
    </nav>
  )
}
