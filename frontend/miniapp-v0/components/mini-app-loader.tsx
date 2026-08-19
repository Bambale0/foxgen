'use client'

import { LoaderCircle, Send } from 'lucide-react'
import { BRAND_NAME } from '@/lib/brand'

export function MiniAppLoader() {
  return (
    <main
      className="relative flex min-h-svh items-center justify-center overflow-hidden px-5 py-10"
      aria-live="polite"
      aria-busy="true"
    >
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_35%,rgba(210,146,38,0.12),transparent_32%),radial-gradient(circle_at_50%_80%,rgba(40,74,120,0.10),transparent_45%)]" />

      <section
        className="relative w-full max-w-sm overflow-hidden rounded-[28px] border border-white/10 bg-card/80 p-7 shadow-2xl shadow-black/40 backdrop-blur-xl"
        role="status"
      >
        <div className="absolute inset-x-12 top-0 h-px bg-gradient-to-r from-transparent via-gold/70 to-transparent" />

        <div className="flex flex-col items-center text-center">
          <div className="relative mb-7 flex h-24 w-24 items-center justify-center">
            <div className="absolute inset-0 rounded-full border border-gold/15" />
            <div className="absolute inset-2 rounded-full border border-dashed border-gold/25" />
            <div className="absolute inset-0 animate-spin rounded-full border-2 border-transparent border-r-gold/40 border-t-gold" />
            <div className="flex h-16 w-16 items-center justify-center rounded-full border border-gold/30 bg-gold/10 text-gold shadow-lg shadow-gold/10">
              <Send className="h-7 w-7" />
            </div>
          </div>

          <h1 className="text-2xl font-semibold tracking-[0.12em] text-foreground">
            {BRAND_NAME}
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Загружаем Mini App
          </p>

          <div className="mt-7 h-1.5 w-full overflow-hidden rounded-full bg-white/5">
            <div className="h-full w-1/2 animate-[pulse_1.2s_ease-in-out_infinite] rounded-full bg-gradient-to-r from-gold/60 via-gold to-gold/60" />
          </div>

          <div className="mt-5 flex items-center gap-2 text-xs text-muted-foreground/80">
            <LoaderCircle className="h-3.5 w-3.5 animate-spin text-gold" />
            Получаем данные Telegram
          </div>
        </div>
      </section>
    </main>
  )
}
