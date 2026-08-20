'use client'

import Image from 'next/image'
import { Coins, RefreshCw, Wifi } from 'lucide-react'
import { useApp } from '@/lib/app-context'
import { BRAND_LOGO, BRAND_NAME } from '@/lib/brand'
import { cn } from '@/lib/utils'

export function HeroHeader() {
  const { state, refreshTasks, openBalance } = useApp()
  const { user, mode, isLoading } = state

  return (
    <header className="sticky top-0 z-40 px-3 pb-2 pt-2 sm:px-4 lg:px-6">
      <div className="mx-auto w-full max-w-[1180px]">
        <div className="glass-strong flex items-center justify-between gap-3 rounded-2xl border border-white/[0.07] px-3 py-2.5 shadow-[0_12px_42px_rgba(0,0,0,0.3)]">
          <div className="flex min-w-0 items-center gap-2.5">
            <div className="relative h-9 w-9 shrink-0 overflow-hidden rounded-xl border border-gold/35 bg-gold/10 shadow-[0_0_24px_rgba(255,106,0,0.12)]">
              <Image
                src={BRAND_LOGO}
                alt={`${BRAND_NAME} logo`}
                fill
                priority
                sizes="36px"
                className="object-cover"
              />
            </div>
            <div className="min-w-0">
              <div className="truncate text-[13px] font-black uppercase tracking-[0.18em] text-foreground">
                {BRAND_NAME}
              </div>
              <div className="mt-0.5 inline-flex items-center gap-1.5 text-[9px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                <Wifi className="h-2.5 w-2.5 text-gold" />
                <span>{mode === 'live' ? 'Mini App online' : 'Telegram mode'}</span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={refreshTasks}
              disabled={isLoading}
              aria-label="Обновить"
              className={cn(
                'inline-flex h-9 w-9 items-center justify-center rounded-full border border-white/[0.07] bg-white/[0.035] text-muted-foreground',
                'transition-all hover:border-gold/30 hover:bg-gold/10 hover:text-gold active:scale-95',
                'disabled:opacity-50',
              )}
            >
              <RefreshCw className={cn('h-3.5 w-3.5', isLoading && 'animate-spin')} />
            </button>

            <button
              type="button"
              onClick={openBalance}
              className="inline-flex items-center gap-2 rounded-full border border-gold/35 bg-gold/[0.09] px-3 py-2 transition-all hover:bg-gold/[0.14] active:scale-[0.98]"
            >
              <Coins className="h-4 w-4 text-gold" />
              <span className="text-sm font-black tabular-nums text-foreground">{user.credits}</span>
            </button>
          </div>
        </div>
      </div>
    </header>
  )
}
