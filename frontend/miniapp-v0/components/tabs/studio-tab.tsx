'use client'

import { BRAND_NAME } from '@/lib/brand'
import { useApp } from '@/lib/app-context'
import { QuickActionGrid } from '../quick-action-grid'
import { TaskHistoryList } from '../task-history-list'

export function StudioTab() {
  const { setActiveTab, openBalance, openWorkspace } = useApp()

  return (
    <div className="space-y-5 px-3 sm:px-4 lg:space-y-6 lg:px-6">
      <section>
        <div className="mb-3 flex items-end justify-between">
          <div>
            <h1 className="font-serif text-2xl font-semibold tracking-[0.08em] text-foreground lg:text-xl">
              {BRAND_NAME}
            </h1>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Создавайте фото и видео с нейросетями
            </p>
          </div>
        </div>
        <QuickActionGrid
          onPhotoClick={() => setActiveTab(1)}
          onVideoClick={() => setActiveTab(2)}
          onMotionClick={() => setActiveTab(3)}
          onBalanceClick={openBalance}
          onAssistantClick={() => openWorkspace('assistant')}
        />
      </section>

      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-serif text-base font-semibold text-foreground">
            Ваши работы
          </h2>
        </div>
        <TaskHistoryList />
      </section>
    </div>
  )
}
