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
          <div className="relative mb-6 h-44 w-44">
            <div className="absolute -inset-3 animate-pulse rounded-[34px] border border-gold/15 shadow-[0_0_56px_rgba(255,106,0,0.18)]" />
            <div className="relative h-full w-full overflow-hidden rounded-[28px] border border-gold/35 bg-black shadow-[0_0_34px_rgba(255,106,0,0.16)]">
              <Image
                src={BRAND_LOGO}
                alt={`${BRAND_NAME} logo`}
                fill
                priority
                sizes="176px"
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
