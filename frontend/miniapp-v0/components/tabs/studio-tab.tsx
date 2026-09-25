'use client'

import Image from 'next/image'
import { ArrowRight, Flame, Images, Sparkles } from 'lucide-react'
import { BRAND_LOGO, BRAND_NAME } from '@/lib/brand'
import { useApp } from '@/lib/app-context'
import { QuickActionGrid } from '../quick-action-grid'

export function StudioTab() {
  const { setActiveTab, openBalance, openWorkspace } = useApp()

  return (
    <div className="space-y-5 px-3 pb-3 sm:px-4 lg:space-y-6 lg:px-6">
      <section className="fox-surface-accent relative overflow-hidden rounded-[28px] px-5 py-6 sm:px-6 sm:py-7">
        <div className="pointer-events-none absolute -right-10 -top-12 h-44 w-44 rounded-full border border-gold/20" />
        <div className="pointer-events-none absolute -right-20 top-3 h-56 w-56 rounded-full border border-gold/10" />
        <div className="pointer-events-none absolute right-2 top-1/2 h-36 w-36 -translate-y-1/2 opacity-[0.12] sm:h-44 sm:w-44">
          <Image
            src={BRAND_LOGO}
            alt=""
            fill
            sizes="176px"
            className="object-contain"
          />
        </div>

        <div className="relative max-w-[540px]">
          <div className="inline-flex items-center gap-1.5 rounded-full border border-gold/25 bg-gold/[0.08] px-2.5 py-1 text-[11px] font-bold uppercase tracking-[0.14em] text-gold">
            <Sparkles className="h-3 w-3" />
            AI-студия в одном окне
          </div>

          <h1 className="mt-4 max-w-[420px] text-[28px] font-black leading-[1.04] tracking-[-0.035em] text-foreground sm:text-4xl">
            Создавайте. Повторяйте <span className="text-gold">тренды.</span>
          </h1>
          <p className="mt-3 max-w-[440px] text-xs leading-relaxed text-muted-foreground sm:text-sm">
            Фото, видео, анимация и готовые идеи сообщества — без лишних экранов и настроек.
          </p>

          <button
            type="button"
            onClick={() => setActiveTab(1)}
            className="fox-cta mt-5 inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-xl px-5 text-sm font-bold transition-all active:scale-[0.99] sm:w-auto sm:min-w-56"
          >
            Создать
            <ArrowRight className="h-4 w-4" />
          </button>
        </div>
      </section>

      <section>
        <div className="mb-3 flex items-end justify-between gap-3 px-0.5">
          <div>
            <h2 className="text-lg font-bold tracking-[-0.02em] text-foreground">Что хотите сделать?</h2>
            <p className="mt-0.5 text-[11px] text-muted-foreground">Выберите сценарий — покажем только нужные настройки</p>
          </div>
          <span className="text-[11px] font-black uppercase tracking-[0.14em] text-gold">{BRAND_NAME}</span>
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
        <div className="mb-3 px-0.5">
          <h2 className="text-lg font-bold tracking-[-0.02em] text-foreground">Вдохновение</h2>
          <p className="mt-0.5 text-[11px] text-muted-foreground">Возьмите готовую идею и запустите её под себя</p>
        </div>

        <div className="grid gap-2.5 sm:grid-cols-2 sm:gap-3">
          <button
            type="button"
            onClick={() => setActiveTab(5)}
            className="fox-surface group relative min-h-[126px] overflow-hidden rounded-[22px] border-gold/20 p-4 text-left transition-all duration-200 hover:-translate-y-0.5 active:scale-[0.985]"
          >
            <div className="pointer-events-none absolute -right-8 -top-8 h-28 w-28 rounded-full bg-gold/[0.09] blur-2xl" />
            <div className="relative flex h-full flex-col justify-between gap-5">
              <div className="flex items-start justify-between gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-gold/25 bg-gold/[0.09] text-gold">
                  <Flame className="h-5 w-5" />
                </div>
                <ArrowRight className="h-4 w-4 text-muted-foreground transition-transform group-hover:translate-x-1 group-hover:text-gold" />
              </div>
              <div>
                <div className="text-[15px] font-bold text-foreground">Тренды</div>
                <div className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                  Готовые механики, промпты и референсы — нажмите и повторите.
                </div>
              </div>
            </div>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab(4)}
            className="fox-surface group relative min-h-[126px] overflow-hidden rounded-[22px] border-gold/15 p-4 text-left transition-all duration-200 hover:-translate-y-0.5 active:scale-[0.985]"
          >
            <div className="pointer-events-none absolute -right-8 -top-8 h-28 w-28 rounded-full bg-white/[0.035] blur-2xl" />
            <div className="relative flex h-full flex-col justify-between gap-5">
              <div className="flex items-start justify-between gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-white/10 bg-white/[0.04] text-foreground">
                  <Images className="h-5 w-5" />
                </div>
                <ArrowRight className="h-4 w-4 text-muted-foreground transition-transform group-hover:translate-x-1 group-hover:text-gold" />
              </div>
              <div>
                <div className="text-[15px] font-bold text-foreground">Лента сообщества</div>
                <div className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                  Смотрите лучшие генерации, открывайте детали и делайте ремикс.
                </div>
              </div>
            </div>
          </button>
        </div>
      </section>
    </div>
  )
}
