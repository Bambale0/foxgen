'use client'

const TELEGRAM_INIT_DATA_STORAGE_KEY = '__banano_tg_init_data'

type MiniAppRuntimeWindow = Window & {
  __BANANO_MINIAPP_PLATFORM__?: 'telegram' | 'max'
  __BANANO_TG_INIT_DATA__?: string
  __BANANO_MAX_INIT_DATA__?: string
  __BANANO_INITIAL_LAUNCH__?: { hash?: string; search?: string }
}

const CACHED_LAUNCH_STORAGE_KEYS = [
  TELEGRAM_INIT_DATA_STORAGE_KEY,
  '__banano_max_init_data',
  '__banano_initial_hash',
  '__banano_initial_search',
  '__banano_initial_href',
  // Telegram SDK cache of the launch parameters.
  'initParams',
]

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

/**
 * Drop cached Telegram launch data the backend has already refused.
 *
 * Only cached copies are removed: a live native launch keeps its own URL/SDK
 * launch parameters, so this cannot sign out a working session. Without it a
 * retry would keep replaying the same rejected signature and the Mini App could
 * stay stuck on the sign-in gate.
 */
export function clearTelegramInitData(): void {
  clearMiniAppInitData('telegram')
}

export function clearMiniAppInitData(platform: 'telegram' | 'max' = 'telegram'): void {
  if (typeof window === 'undefined') return

  const runtimeWindow = window as MiniAppRuntimeWindow
  if (platform === 'max') {
    runtimeWindow.__BANANO_MAX_INIT_DATA__ = ''
  } else {
    runtimeWindow.__BANANO_TG_INIT_DATA__ = ''
  }
  delete runtimeWindow.__BANANO_INITIAL_LAUNCH__

  try {
    for (const key of CACHED_LAUNCH_STORAGE_KEYS) {
      window.sessionStorage.removeItem(key)
    }
  } catch {
    // Storage can be unavailable; the in-memory copies are already cleared.
  }
}
