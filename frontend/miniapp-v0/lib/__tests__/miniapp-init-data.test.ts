import fs from 'node:fs'
import path from 'node:path'

import { getInitData } from '../api'
import { persistTelegramInitData } from '../miniapp-init-data'

describe('Mini App Telegram initData persistence', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
    window.history.replaceState({}, '', '/mini-app/')

    window.__BANANO_MINIAPP_PLATFORM__ = undefined
    window.__BANANO_TG_INIT_DATA__ = ''
    window.__BANANO_MAX_INIT_DATA__ = ''

    if (window.Telegram?.WebApp) {
      window.Telegram.WebApp.initData = ''
      window.Telegram.WebApp.initDataUnsafe = { start_param: '' }
    }
    if (window.WebApp) {
      window.WebApp.initData = ''
      window.WebApp.initDataUnsafe = { start_param: '' }
    }
  })

  afterEach(() => {
    if (window.Telegram?.WebApp) {
      window.Telegram.WebApp.initData = 'mock_init_data'
      window.Telegram.WebApp.initDataUnsafe = { start_param: '' }
    }
  })

  it('survives a browser-auth reload even when the URL hash is no longer available', () => {
    const signedInitData = 'query_id=browser-auth&user=%7B%22id%22%3A42%7D&auth_date=1&hash=signed'

    persistTelegramInitData(signedInitData)

    expect(window.sessionStorage.getItem('__banano_tg_init_data')).toBe(signedInitData)

    // Simulate the page reload boundary: runtime globals and the launch hash are gone,
    // but sessionStorage survives in the same tab/WebView.
    window.__BANANO_MINIAPP_PLATFORM__ = undefined
    window.__BANANO_TG_INIT_DATA__ = ''
    window.history.replaceState({}, '', '/mini-app/')

    expect(getInitData()).toBe(signedInitData)
    expect(window.__BANANO_MINIAPP_PLATFORM__).toBe('telegram')
  })

  it('captures Telegram launch initData before the native SDK is synchronously loaded', () => {
    const layoutPath = path.join(process.cwd(), 'app', 'layout.tsx')
    const layout = fs.readFileSync(layoutPath, 'utf8')

    const captureIndex = layout.indexOf("window.__BANANO_TG_INIT_DATA__ = telegramInitData")
    const storageIndex = layout.indexOf("window.sessionStorage.setItem('__banano_tg_init_data', telegramInitData)")
    const sdkLoadIndex = layout.indexOf("document.write('<script src=\"' + src")

    expect(captureIndex).toBeGreaterThanOrEqual(0)
    expect(storageIndex).toBeGreaterThan(captureIndex)
    expect(sdkLoadIndex).toBeGreaterThan(storageIndex)
  })
})
