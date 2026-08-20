'use client'

import { useEffect, useRef, useState } from 'react'
import { ExternalLink, LoaderCircle, Send } from 'lucide-react'
import {
  getApiBasePath,
  getRuntimeBotUsername,
  getStartParamFallback,
} from '@/lib/api'
import { BRAND_NAME } from '@/lib/brand'
import { useApp } from '@/lib/app-context'
import { Button } from '@/components/ui/button'

type TelegramLoginUser = {
  id: number
  first_name: string
  last_name?: string
  username?: string
  photo_url?: string
  auth_date: number
  hash: string
}

declare global {
  interface Window {
    onBananoTelegramAuth?: (user: TelegramLoginUser) => void
  }
}

function setBrowserInitData(initData: string) {
  const params = new URLSearchParams(window.location.hash.replace(/^#/, ''))
  params.set('tgWebAppData', initData)
  window.location.hash = params.toString()
}

export function TelegramOpenGate() {
  const { state } = useApp()
  const widgetRef = useRef<HTMLDivElement | null>(null)
  const [botUsername, setBotUsername] = useState('')
  const [telegramUrl, setTelegramUrl] = useState('')
  const [loginStatus, setLoginStatus] = useState<'idle' | 'loading' | 'error'>('idle')
  const [widgetReady, setWidgetReady] = useState(false)

  const isConnecting = state.isLoading

  useEffect(() => {
    let cancelled = false

    async function loadBotUsername() {
      const runtimeUsername = getRuntimeBotUsername()
      if (runtimeUsername) {
        if (!cancelled) setBotUsername(runtimeUsername)
        return
      }

      try {
        const response = await fetch(`${getApiBasePath()}/browser-auth/config`, {
          headers: { Accept: 'application/json' },
          credentials: 'same-origin',
          cache: 'no-store',
        })
        const payload = await response.json() as {
          ok?: boolean
          bot_username?: string
        }
        if (!cancelled && response.ok && payload.ok && payload.bot_username) {
          setBotUsername(payload.bot_username.replace(/^@/, ''))
        }
      } catch {
        if (!cancelled) setLoginStatus('error')
      }
    }

    void loadBotUsername()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!botUsername) return
    const startParam = getStartParamFallback()
    setTelegramUrl(
      startParam
        ? `https://t.me/${botUsername}?startapp=${encodeURIComponent(startParam)}`
        : `https://t.me/${botUsername}?startapp`,
    )
  }, [botUsername])

  useEffect(() => {
    if (isConnecting || !botUsername || !widgetRef.current) return

    const container = widgetRef.current
    container.replaceChildren()
    setWidgetReady(false)

    window.onBananoTelegramAuth = async (user: TelegramLoginUser) => {
      setLoginStatus('loading')
      try {
        const response = await fetch(`${getApiBasePath()}/browser-auth`, {
          method: 'POST',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ telegram_auth: user }),
          credentials: 'same-origin',
          cache: 'no-store',
        })
        const payload = await response.json() as {
          ok?: boolean
          init_data?: string
          error?: string
        }
        if (!response.ok || !payload.ok || !payload.init_data) {
          throw new Error(payload.error || 'Telegram login failed')
        }
        setBrowserInitData(payload.init_data)
        window.location.reload()
      } catch {
        setLoginStatus('error')
      }
    }

    const script = document.createElement('script')
    script.async = true
    script.src = 'https://telegram.org/js/telegram-widget.js?22'
    script.setAttribute('data-telegram-login', botUsername)
    script.setAttribute('data-size', 'large')
    script.setAttribute('data-radius', '12')
    script.setAttribute('data-userpic', 'false')
    script.setAttribute('data-onauth', 'onBananoTelegramAuth(user)')
    script.onload = () => setWidgetReady(true)
    script.onerror = () => setLoginStatus('error')
    container.appendChild(script)

    return () => {
      delete window.onBananoTelegramAuth
      container.replaceChildren()
    }
  }, [botUsername, isConnecting])

  return (
    <main className="relative flex min-h-svh items-center justify-center overflow-hidden px-5 py-10">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_35%,rgba(210,146,38,0.10),transparent_32%),radial-gradient(circle_at_50%_80%,rgba(40,74,120,0.10),transparent_45%)]" />

      <section className="relative w-full max-w-sm overflow-hidden rounded-[28px] border border-white/10 bg-card/80 p-7 shadow-2xl shadow-black/40 backdrop-blur-xl">
        <div className="absolute inset-x-12 top-0 h-px bg-gradient-to-r from-transparent via-gold/70 to-transparent" />

        <div className="flex flex-col items-center text-center">
          <div className="relative mb-7 flex h-24 w-24 items-center justify-center">
            <div className="absolute inset-0 rounded-full border border-gold/15" />
            <div className="absolute inset-2 rounded-full border border-dashed border-gold/25" />
            <div
              className={
                isConnecting
                  ? 'absolute inset-0 animate-spin rounded-full border-2 border-transparent border-r-gold/40 border-t-gold'
                  : 'absolute inset-0 rounded-full border border-gold/25'
              }
            />
            <div className="flex h-16 w-16 items-center justify-center rounded-full border border-gold/30 bg-gold/10 text-gold shadow-lg shadow-gold/10">
              <Send className="h-7 w-7" />
            </div>
          </div>

          <h1 className="text-2xl font-semibold tracking-[0.12em] text-foreground">
            {BRAND_NAME}
          </h1>

          {isConnecting ? (
            <>
              <p className="mt-2 text-sm text-muted-foreground">Загружаем Mini App</p>
              <div className="mt-7 h-1.5 w-full overflow-hidden rounded-full bg-white/5">
                <div className="h-full w-1/2 animate-pulse rounded-full bg-gradient-to-r from-gold/60 via-gold to-gold/60" />
              </div>
            </>
          ) : (
            <>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                Продолжите через Telegram — без пароля
              </p>

              <div className="mt-7 flex min-h-12 w-full items-center justify-center">
                {loginStatus === 'loading' ? (
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <LoaderCircle className="h-4 w-4 animate-spin text-gold" />
                    Входим…
                  </div>
                ) : (
                  <div ref={widgetRef} className="flex min-h-10 items-center justify-center" />
                )}
              </div>

              {!widgetReady && loginStatus === 'idle' ? (
                <div className="mt-3 h-10 w-48 animate-pulse rounded-xl bg-white/5" />
              ) : null}

              {loginStatus === 'error' ? (
                <div className="mt-5 w-full space-y-3">
                  <p className="text-sm text-muted-foreground">Не получилось войти. Попробуйте ещё раз.</p>
                  {telegramUrl ? (
                    <Button asChild variant="secondary" className="h-11 w-full rounded-xl">
                      <a href={telegramUrl} target="_blank" rel="noreferrer">
                        <ExternalLink className="h-4 w-4" />
                        Открыть {BRAND_NAME} в Telegram
                      </a>
                    </Button>
                  ) : null}
                </div>
              ) : null}
            </>
          )}
        </div>
      </section>
    </main>
  )
}
