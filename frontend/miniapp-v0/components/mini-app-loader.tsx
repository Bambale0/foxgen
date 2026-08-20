'use client'

import Image from 'next/image'
import { LoaderCircle, Sparkles } from 'lucide-react'
import { BRAND_LOGO, BRAND_NAME } from '@/lib/brand'

export function MiniAppLoader() {
  return (
    <main
      className="relative flex min-h-svh items-center justify-center overflow-hidden px-5 py-10"
      aria-live="polite"
      aria-busy="true"
    >
      <div className="foxgen-shell-bg pointer-events-none absolute inset-0" />

      <section
        className="fox-surface-accent relative w-full max-w-sm overflow-hidden rounded-[30px] p-7"
        role="status"
      >
        <div className="fox-accent-line absolute inset-x-12 top-0 h-px" />
        <div className="pointer-events-none absolute -right-16 -top-16 h-48 w-48 rounded-full border border-gold/15" />

        <div className="relative flex flex-col items-center text-center">
          <div className="relative mb-6 flex h-24 w-24 items-center justify-center">
            <div className="absolute inset-0 rounded-full border border-gold/15 shadow-[0_0_44px_rgba(255,106,0,0.12)]" />
            <div className="absolute inset-2 rounded-full border border-dashed border-gold/25" />
            <div className="absolute inset-0 animate-spin rounded-full border-2 border-transparent border-r-gold/40 border-t-gold" />
            <div className="relative h-16 w-16 overflow-hidden rounded-full border border-gold/30 bg-gold/10 shadow-[0_0_28px_rgba(255,106,0,0.14)]">
              <Image
                src={BRAND_LOGO}
                alt={`${BRAND_NAME} logo`}
                fill
                priority
                sizes="64px"
                className="object-cover"
              />
            </div>
          </div>

          <div className="inline-flex items-center gap-1.5 rounded-full border border-gold/20 bg-gold/[0.07] px-2.5 py-1 text-[9px] font-black uppercase tracking-[0.14em] text-gold">
            <Sparkles className="h-3 w-3" />
            Telegram Mini App
          </div>
          <h1 className="mt-3 text-2xl font-black uppercase tracking-[0.12em] text-foreground">
            {BRAND_NAME}
          </h1>
          <p className="mt-2 text-xs text-muted-foreground">
            Подготавливаем вашу студию
          </p>

          <div className="mt-6 h-1.5 w-full overflow-hidden rounded-full bg-white/[0.05]">
            <div className="h-full w-1/2 animate-[pulse_1.2s_ease-in-out_infinite] rounded-full bg-gradient-to-r from-gold/45 via-gold to-gold/45 shadow-[0_0_14px_rgba(255,106,0,0.35)]" />
          </div>

          <div className="mt-5 flex items-center gap-2 text-[10px] text-muted-foreground">
            <LoaderCircle className="h-3.5 w-3.5 animate-spin text-gold" />
            Получаем данные Telegram
          </div>
        </div>
      </section>
    </main>
  )
}
