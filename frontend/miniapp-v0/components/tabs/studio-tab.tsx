'use client'

import Image from 'next/image'
import { ArrowRight, Gauge, Sparkles, WandSparkles } from 'lucide-react'
import { BRAND_ICON, BRAND_NAME } from '@/lib/brand'
import { useApp } from '@/lib/app-context'
import { QuickActionGrid } from '../quick-action-grid'
import { TaskHistoryList } from '../task-history-list'

export function StudioTab() {
  const { setActiveTab, openBalance, openWorkspace } = useApp()

  return (
    <div className="space-y-5 px-3 pb-3 sm:px-4 lg:space-y-6 lg:px-6">
      <section className="fox-surface-accent relative overflow-hidden rounded-[28px] px-5 py-6 sm:px-6 sm:py-7">
        <div className="pointer-events-none absolute -right-10 -top-12 h-44 w-44 rounded-full border border-gold/20" />
        <div className="pointer-events-none absolute -right-20 top-3 h-56 w-56 rounded-full border border-gold/10" />
        <div className="pointer-events-none absolute right-2 top-1/2 h-36 w-36 -translate-y-1/2 opacity-[0.14] sm:h-44 sm:w-44">
          <Image
            src={BRAND_ICON}
            alt=""
            fill
            sizes="176px"
            className="object-contain"
          />
        </div>

        <div className="relative max-w-[540px]">
          <div className="inline-flex items-center gap-1.5 rounded-full border border-gold/25 bg-gold/[0.08] px-2.5 py-1 text-[9px] font-bold uppercase tracking-[0.14em] text-gold">
            <Sparkles className="h-3 w-3" />
            AI генерация фото и видео
          </div>

          <h1 className="mt-4 max-w-[390px] text-[28px] font-black leading-[1.04] tracking-[-0.035em] text-foreground sm:text-4xl">
            Ваш творческий <span className="text-gold">AI-помощник</span>
          </h1>
          <p className="mt-3 max-w-[430px] text-xs leading-relaxed text-muted-foreground sm:text-sm">
            Создавайте изображения и видео через проверенные модели без сложных меню — от идеи до результата за несколько шагов.
          </p>

          <div className="mt-5 grid max-w-[430px] grid-cols-3 gap-2">
            <div className="rounded-xl border border-white/[0.06] bg-black/20 px-2 py-2.5">
              <WandSparkles className="h-4 w-4 text-gold" />
              <div className="mt-2 text-[9px] font-semibold leading-tight text-foreground">Топовые модели</div>
            </div>
            <div className="rounded-xl border border-white/[0.06] bg-black/20 px-2 py-2.5">
              <Gauge className="h-4 w-4 text-gold" />
              <div className="mt-2 text-[9px] font-semibold leading-tight text-foreground">Быстрый старт</div>
            </div>
            <div className="rounded-xl border border-white/[0.06] bg-black/20 px-2 py-2.5">
              <Sparkles className="h-4 w-4 text-gold" />
              <div className="mt-2 text-[9px] font-semibold leading-tight text-foreground">Понятный путь</div>
            </div>
          </div>

          <button
            type="button"
            onClick={() => setActiveTab(1)}
            className="fox-cta mt-5 inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-xl px-5 text-sm font-bold transition-all active:scale-[0.99] sm:w-auto sm:min-w-56"
          >
            Начать творить
            <ArrowRight className="h-4 w-4" />
          </button>
        </div>
      </section>

      <section>
        <div className="mb-3 flex items-end justify-between gap-3 px-0.5">
          <div>
            <h2 className="text-lg font-bold tracking-[-0.02em] text-foreground">С чего начнём?</h2>
            <p className="mt-0.5 text-[11px] text-muted-foreground">Выберите действие — настройки появятся дальше</p>
          </div>
          <span className="text-[9px] font-black uppercase tracking-[0.14em] text-gold">{BRAND_NAME}</span>
        </div>
        <QuickActionGrid
          onPhotoClick={() => setActiveTab(1)}
          onVideoClick={() => setActiveTab(2)}
          onMotionClick={() => setActiveTab(3)}
          onBalanceClick={openBalance}
          onAssistantClick={() => openWorkspace('assistant')}
        />
      </section>

      <section className="pt-1">
        <div className="mb-3 flex items-center justify-between px-0.5">
          <div>
            <h2 className="text-base font-bold text-foreground">Ваши работы</h2>
            <p className="mt-0.5 text-[10px] text-muted-foreground">Последние генерации и их статус</p>
          </div>
        </div>
        <TaskHistoryList />
      </section>
    </div>
  )
}
