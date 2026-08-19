'use client'

import { Boxes, CircleUserRound, Home, Images, Sparkles, WandSparkles } from 'lucide-react'
import { useApp } from '@/lib/app-context'
import type { TabId } from '@/lib/types'

const tabs: Array<{ id: TabId; label: string; icon: typeof Home }> = [
  { id: 'home', label: 'Главная', icon: Home },
  { id: 'models', label: 'Модели', icon: Sparkles },
  { id: 'create', label: 'Создать', icon: WandSparkles },
  { id: 'works', label: 'Работы', icon: Images },
  { id: 'services', label: 'Сервисы', icon: Boxes },
  { id: 'profile', label: 'Профиль', icon: CircleUserRound },
]

export function TabNav() {
  const { activeTab, setActiveTab } = useApp()

  return (
    <nav className="tab-nav" aria-label="Основная навигация">
      <div className="tab-nav-inner">
        {tabs.map((tab) => {
          const Icon = tab.icon
          const active = activeTab === tab.id
          return (
            <button
              key={tab.id}
              type="button"
              className={`tab-button${active ? ' active' : ''}`}
              data-testid={`tab-${tab.id}`}
              aria-current={active ? 'page' : undefined}
              onClick={() => setActiveTab(tab.id)}
            >
              <Icon strokeWidth={active ? 2.4 : 1.8} />
              <small>{tab.label}</small>
            </button>
          )
        })}
      </div>
    </nav>
  )
}
