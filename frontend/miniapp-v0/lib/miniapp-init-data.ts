'use client'

const TELEGRAM_INIT_DATA_STORAGE_KEY = '__banano_tg_init_data'

type MiniAppRuntimeWindow = Window & {
  __BANANO_MINIAPP_PLATFORM__?: 'telegram' | 'max'
  __BANANO_TG_INIT_DATA__?: string
}

/**
 * Persist already-signed Telegram Mini App initData across a same-tab reload.
 *
 * This is transport only: the backend remains authoritative and validates the
 * Telegram signature before accepting any authenticated action.
 */
export function persistTelegramInitData(initData: string): string {
  const value = String(initData || '').trim()
  if (!value || typeof window === 'undefined') return value

  const runtimeWindow = window as MiniAppRuntimeWindow
  runtimeWindow.__BANANO_MINIAPP_PLATFORM__ = 'telegram'
  runtimeWindow.__BANANO_TG_INIT_DATA__ = value

  try {
    window.sessionStorage.setItem(TELEGRAM_INIT_DATA_STORAGE_KEY, value)
  } catch {
    // Some embedded browsers can deny storage; the runtime window fallback
    // still keeps initData alive for the current document.
  }

  return value
}
