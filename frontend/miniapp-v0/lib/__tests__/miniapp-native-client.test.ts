import { getInitData, isNativeMiniAppClient } from '../api'

type MutableWindow = Window & {
  TelegramWebviewProxy?: { postEvent?: () => void }
  Telegram?: {
    WebView?: { initParams?: Record<string, string> }
    WebApp?: { initData?: string; initDataUnsafe?: { start_param?: string }; initParams?: Record<string, string>; platform?: string }
  }
  WebApp?: { initData?: string; initDataUnsafe?: { start_param?: string } }
  __BANANO_INITIAL_LAUNCH__?: { hash?: string; search?: string }
}

function resetRuntime() {
  const runtimeWindow = window as MutableWindow

  window.sessionStorage.clear()
  window.history.replaceState({}, '', '/mini-app/')
  window.__BANANO_MINIAPP_PLATFORM__ = undefined
  window.__BANANO_TG_INIT_DATA__ = ''
  window.__BANANO_MAX_INIT_DATA__ = ''
  delete runtimeWindow.__BANANO_INITIAL_LAUNCH__
  delete runtimeWindow.TelegramWebviewProxy
  delete runtimeWindow.WebApp
  ;(window as unknown as { external?: unknown }).external = undefined

  if (runtimeWindow.Telegram?.WebView) {
    delete runtimeWindow.Telegram.WebView
  }

  const webApp = runtimeWindow.Telegram?.WebApp
  if (webApp) {
    webApp.initData = ''
    webApp.initDataUnsafe = { start_param: '' }
    webApp.platform = 'unknown'
  }
}

describe('isNativeMiniAppClient', () => {
  beforeEach(resetRuntime)
  afterEach(resetRuntime)

  it('keeps the browser fallback when only the SDK script is present', () => {
    // The Telegram SDK script is loaded on the public origin for every visitor,
    // so its mere presence must not be treated as a native client.
    expect(window.Telegram?.WebApp).toBeTruthy()
    expect(isNativeMiniAppClient()).toBe(false)
  })

  it('detects a Telegram launch from the signed platform marker', () => {
    window.__BANANO_MINIAPP_PLATFORM__ = 'telegram'

    expect(isNativeMiniAppClient()).toBe(true)
  })

  it('detects a MAX launch from the MAX bridge', () => {
    ;(window as MutableWindow).WebApp = { initData: 'max_init_data' }

    expect(isNativeMiniAppClient()).toBe(true)
  })

  it('detects the native Telegram WebView through its injected proxy', () => {
    ;(window as MutableWindow).TelegramWebviewProxy = { postEvent: () => {} }

    expect(isNativeMiniAppClient()).toBe(true)
  })

  it('detects the native Telegram WebView when launch params survive a hash loss', () => {
    const runtimeWindow = window as MutableWindow
    runtimeWindow.Telegram = {
      ...runtimeWindow.Telegram,
      WebView: { initParams: { tgWebAppPlatform: 'ios' } },
    }

    expect(isNativeMiniAppClient()).toBe(true)
  })


  it('recovers Telegram initData from SDK initParams after the URL hash is gone', () => {
    const runtimeWindow = window as MutableWindow
    runtimeWindow.Telegram = {
      ...runtimeWindow.Telegram,
      WebView: { initParams: { tgWebAppData: 'query_id=sdk&hash=ok', tgWebAppPlatform: 'ios' } },
    }

    expect(getInitData()).toBe('query_id=sdk&hash=ok')
    expect(isNativeMiniAppClient()).toBe(true)
  })

  it('recovers Telegram initData from the SDK sessionStorage cache', () => {
    window.sessionStorage.setItem(
      '__telegram__initParams',
      JSON.stringify({ tgWebAppData: 'query_id=session&hash=ok', tgWebAppPlatform: 'tdesktop' }),
    )

    expect(getInitData()).toBe('query_id=session&hash=ok')
    expect(isNativeMiniAppClient()).toBe(true)
  })

  it('exposes the browser fallback while no launch data can be resolved', () => {
    expect(getInitData()).toBe('')
    expect(isNativeMiniAppClient()).toBe(false)
  })
})
