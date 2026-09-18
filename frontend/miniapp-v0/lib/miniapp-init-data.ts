'use client'

const TELEGRAM_INIT_DATA_STORAGE_KEY = '__banano_tg_init_data'

type MiniAppRuntimeWindow = Window & {
  __BANANO_MINIAPP_PLATFORM__?: 'telegram' | 'max'
  __BANANO_TG_INIT_DATA__?: string
  __BANANO_MAX_INIT_DATA__?: string
  __BANANO_INITIAL_LAUNCH__?: { hash?: string; search?: string }
  Telegram?: {
    WebView?: { initParams?: Record<string, string> }
    WebApp?: { initParams?: Record<string, string> }
  }
}

const CACHED_INIT_DATA_STORAGE_KEYS = [
  TELEGRAM_INIT_DATA_STORAGE_KEY,
  '__banano_max_init_data',
]

const CACHED_LAUNCH_SNAPSHOT_KEYS = [
  '__banano_initial_hash',
  '__banano_initial_search',
  '__banano_initial_href',
  // Telegram SDK cache of the launch parameters.
  '__telegram__initParams',
  'initParams',
]

function initDataKeysFor(platform: 'telegram' | 'max') {
  return platform === 'max'
    ? { preferredKey: 'WebAppData', alternateKey: 'tgWebAppData' }
    : { preferredKey: 'tgWebAppData', alternateKey: 'WebAppData' }
}

function extractInitDataFromLaunchValue(rawValue: string | null | undefined, platform: 'telegram' | 'max'): string {
  const value = String(rawValue || '').trim()
  if (!value) return ''

  const { preferredKey, alternateKey } = initDataKeysFor(platform)
  const parseParams = (rawParams: string) => {
    const params = new URLSearchParams(
      rawParams.startsWith('#') || rawParams.startsWith('?') ? rawParams.slice(1) : rawParams,
    )
    return String(params.get(preferredKey) || params.get(alternateKey) || '').trim()
  }

  try {
    if (/^https?:\/\//i.test(value) || value.startsWith('/')) {
      const url = new URL(value, 'https://happy-fox.online')
      return parseParams(url.hash || '') || parseParams(url.search || '')
    }
  } catch {}

  try {
    return parseParams(value)
  } catch {
    return ''
  }
}

function extractInitDataFromInitParams(rawValue: string | null | undefined, platform: 'telegram' | 'max'): string {
  const value = String(rawValue || '').trim()
  if (!value) return ''

  try {
    const parsed = JSON.parse(value) as unknown
    if (!parsed || typeof parsed !== 'object') return ''
    const params = parsed as Record<string, unknown>
    const { preferredKey, alternateKey } = initDataKeysFor(platform)
    return String(params[preferredKey] || params[alternateKey] || '').trim()
  } catch {
    return ''
  }
}

function isRejectedInitData(candidate: string, rejectedInitData?: string): boolean {
  const rejected = String(rejectedInitData || '').trim()
  return Boolean(rejected && String(candidate || '').trim() === rejected)
}

function clearRejectedInitParamsObject(
  source: Record<string, string> | undefined,
  platform: 'telegram' | 'max',
  rejectedInitData?: string,
): void {
  if (!source) return
  const { preferredKey, alternateKey } = initDataKeysFor(platform)
  for (const key of [preferredKey, alternateKey]) {
    if (isRejectedInitData(String(source[key] || ''), rejectedInitData)) {
      delete source[key]
    }
  }
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

export function clearMiniAppInitData(
  platform: 'telegram' | 'max' = 'telegram',
  options: { preserveLaunchSnapshot?: boolean; rejectedInitData?: string } = {},
): void {
  if (typeof window === 'undefined') return

  const runtimeWindow = window as MiniAppRuntimeWindow
  if (platform === 'max') {
    runtimeWindow.__BANANO_MAX_INIT_DATA__ = ''
  } else {
    runtimeWindow.__BANANO_TG_INIT_DATA__ = ''
  }

  if (!options.preserveLaunchSnapshot) {
    delete runtimeWindow.__BANANO_INITIAL_LAUNCH__
  } else {
    clearRejectedInitParamsObject(runtimeWindow.Telegram?.WebView?.initParams, platform, options.rejectedInitData)
    clearRejectedInitParamsObject(runtimeWindow.Telegram?.WebApp?.initParams, platform, options.rejectedInitData)

    const launch = runtimeWindow.__BANANO_INITIAL_LAUNCH__
    if (launch) {
      const nextLaunch = { ...launch }
      if (isRejectedInitData(extractInitDataFromLaunchValue(nextLaunch.hash, platform), options.rejectedInitData)) {
        delete nextLaunch.hash
      }
      if (isRejectedInitData(extractInitDataFromLaunchValue(nextLaunch.search, platform), options.rejectedInitData)) {
        delete nextLaunch.search
      }
      if (nextLaunch.hash || nextLaunch.search) {
        runtimeWindow.__BANANO_INITIAL_LAUNCH__ = nextLaunch
      } else {
        delete runtimeWindow.__BANANO_INITIAL_LAUNCH__
      }
    }
  }

  try {
    for (const key of CACHED_INIT_DATA_STORAGE_KEYS) {
      window.sessionStorage.removeItem(key)
    }

    if (!options.preserveLaunchSnapshot) {
      for (const key of CACHED_LAUNCH_SNAPSHOT_KEYS) {
        window.sessionStorage.removeItem(key)
      }
      return
    }

    for (const key of ['__banano_initial_hash', '__banano_initial_search', '__banano_initial_href']) {
      const value = window.sessionStorage.getItem(key)
      if (isRejectedInitData(extractInitDataFromLaunchValue(value, platform), options.rejectedInitData)) {
        window.sessionStorage.removeItem(key)
      }
    }
    for (const key of ['__telegram__initParams', 'initParams']) {
      const value = window.sessionStorage.getItem(key)
      if (isRejectedInitData(extractInitDataFromInitParams(value, platform), options.rejectedInitData)) {
        window.sessionStorage.removeItem(key)
      }
    }
  } catch {
    // Storage can be unavailable; the in-memory copies are already cleared.
  }
}
