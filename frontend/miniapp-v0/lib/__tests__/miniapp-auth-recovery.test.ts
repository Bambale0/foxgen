import { getInitData, sendMiniAppClientLog } from '../api'
import { clearMiniAppInitData, clearTelegramInitData, persistTelegramInitData } from '../miniapp-init-data'
import { reportMiniAppEvent } from '../miniapp-telemetry'

const rejectedInitData = 'query_id=rejected&user=%7B%22id%22%3A7%7D&hash=stale'
const rejectedMaxInitData = 'query_id=max-rejected&user=%7B%22id%22%3A8%7D&hash=stale'

describe('clearTelegramInitData', () => {
  const originalFetch = global.fetch

  beforeEach(() => {
    window.sessionStorage.clear()
    window.history.replaceState({}, '', '/mini-app/')
    window.__BANANO_MINIAPP_PLATFORM__ = undefined
    window.__BANANO_TG_INIT_DATA__ = ''
    delete window.__BANANO_INITIAL_LAUNCH__

    const webApp = window.Telegram?.WebApp
    if (webApp) {
      webApp.initData = ''
      webApp.initDataUnsafe = { start_param: '' }
    }
  })

  afterEach(() => {
    global.fetch = originalFetch
  })

  it('drops every cached copy of refused launch data', () => {
    window.__BANANO_INITIAL_LAUNCH__ = {
      hash: '#tgWebAppData=rejected&tgWebAppVersion=8.0',
      search: '',
    }
    window.sessionStorage.setItem(
      '__banano_initial_hash',
      '#tgWebAppData=rejected&tgWebAppVersion=8.0',
    )
    window.sessionStorage.setItem('initParams', '{"tgWebAppData":"rejected"}')
    persistTelegramInitData(rejectedInitData)

    clearTelegramInitData()

    expect(window.__BANANO_TG_INIT_DATA__).toBe('')
    expect(window.__BANANO_INITIAL_LAUNCH__).toBeUndefined()
    expect(window.sessionStorage.getItem('__banano_tg_init_data')).toBeNull()
    expect(window.sessionStorage.getItem('__banano_initial_hash')).toBeNull()
    expect(window.sessionStorage.getItem('initParams')).toBeNull()
  })

  it('stops replaying a refused signature once the launch parameters are gone', () => {
    persistTelegramInitData(rejectedInitData)
    window.__BANANO_MINIAPP_PLATFORM__ = 'telegram'

    expect(getInitData()).toBe(rejectedInitData)

    clearTelegramInitData()

    expect(getInitData()).toBe('')
  })

  it('keeps a live launch hash usable after clearing stale cache', () => {
    persistTelegramInitData(rejectedInitData)
    window.history.replaceState(
      {},
      '',
      '/mini-app/#tgWebAppData=fresh%3D1%26hash%3Dlive&tgWebAppVersion=8.0',
    )

    clearTelegramInitData()

    expect(getInitData()).toBe('fresh=1&hash=live')
  })


  it('preserves early native launch snapshots when auth recovery clears refused cached data', () => {
    window.__BANANO_INITIAL_LAUNCH__ = {
      hash: '#tgWebAppData=fresh%3D1%26hash%3Dearly&tgWebAppVersion=8.0',
      search: '',
    }
    window.sessionStorage.setItem(
      '__banano_initial_hash',
      '#tgWebAppData=fresh%3D1%26hash%3Dearly&tgWebAppVersion=8.0',
    )
    persistTelegramInitData(rejectedInitData)

    clearMiniAppInitData('telegram', { preserveLaunchSnapshot: true })

    expect(window.__BANANO_TG_INIT_DATA__).toBe('')
    expect(window.__BANANO_INITIAL_LAUNCH__).toEqual({
      hash: '#tgWebAppData=fresh%3D1%26hash%3Dearly&tgWebAppVersion=8.0',
      search: '',
    })
    expect(window.sessionStorage.getItem('__banano_tg_init_data')).toBeNull()
    expect(window.sessionStorage.getItem('__banano_initial_hash')).toBe('#tgWebAppData=fresh%3D1%26hash%3Dearly&tgWebAppVersion=8.0')
    expect(getInitData()).toBe('fresh=1&hash=early')
  })

  it('removes the rejected native launch snapshot while preserving native recovery mode', () => {
    window.__BANANO_INITIAL_LAUNCH__ = {
      hash: '#tgWebAppData=query_id%3Drejected%26user%3D%257B%2522id%2522%253A7%257D%26hash%3Dstale&tgWebAppVersion=8.0',
      search: '',
    }
    window.sessionStorage.setItem(
      '__banano_initial_hash',
      '#tgWebAppData=query_id%3Drejected%26user%3D%257B%2522id%2522%253A7%257D%26hash%3Dstale&tgWebAppVersion=8.0',
    )

    clearMiniAppInitData('telegram', {
      preserveLaunchSnapshot: true,
      rejectedInitData,
    })

    expect(window.__BANANO_INITIAL_LAUNCH__).toBeUndefined()
    expect(window.sessionStorage.getItem('__banano_initial_hash')).toBeNull()
    expect(getInitData()).toBe('')
  })

  it('removes rejected Telegram SDK initParams from sessionStorage', () => {
    window.sessionStorage.setItem(
      '__telegram__initParams',
      JSON.stringify({ tgWebAppData: rejectedInitData, tgWebAppPlatform: 'ios' }),
    )

    clearMiniAppInitData('telegram', {
      preserveLaunchSnapshot: true,
      rejectedInitData,
    })

    expect(window.sessionStorage.getItem('__telegram__initParams')).toBeNull()
    expect(getInitData()).toBe('')
  })

  it('keeps fresh Telegram SDK initParams when clearing a different rejected signature', () => {
    window.sessionStorage.setItem(
      '__telegram__initParams',
      JSON.stringify({ tgWebAppData: 'query_id=fresh&hash=live', tgWebAppPlatform: 'ios' }),
    )

    clearMiniAppInitData('telegram', {
      preserveLaunchSnapshot: true,
      rejectedInitData,
    })

    expect(window.sessionStorage.getItem('__telegram__initParams')).not.toBeNull()
    expect(getInitData()).toBe('query_id=fresh&hash=live')
  })

  it('removes rejected in-memory SDK initParams so fresh bridge initData can be used', () => {
    const runtimeWindow = window as typeof window & {
      Telegram: {
        WebView?: { initParams?: Record<string, string> }
        WebApp?: { initData?: string; initDataUnsafe?: { start_param?: string } }
      }
    }
    runtimeWindow.Telegram = {
      WebView: { initParams: { tgWebAppData: rejectedInitData, tgWebAppPlatform: 'ios' } },
      WebApp: { initData: 'query_id=fresh&hash=bridge', initDataUnsafe: { start_param: '' } },
    }

    expect(getInitData()).toBe(rejectedInitData)

    clearMiniAppInitData('telegram', {
      preserveLaunchSnapshot: true,
      rejectedInitData,
    })

    expect(runtimeWindow.Telegram.WebView?.initParams?.tgWebAppData).toBeUndefined()
    expect(runtimeWindow.Telegram.WebView?.initParams?.tgWebAppPlatform).toBe('ios')
    expect(getInitData()).toBe('query_id=fresh&hash=bridge')
  })

  it('drops refused MAX launch data without replaying the stale signature', () => {
    window.__BANANO_MINIAPP_PLATFORM__ = 'max'
    window.__BANANO_MAX_INIT_DATA__ = rejectedMaxInitData
    window.sessionStorage.setItem('__banano_max_init_data', rejectedMaxInitData)

    expect(getInitData()).toBe(rejectedMaxInitData)

    clearMiniAppInitData('max')

    expect(window.__BANANO_MAX_INIT_DATA__).toBe('')
    expect(window.sessionStorage.getItem('__banano_max_init_data')).toBeNull()
    expect(getInitData()).toBe('')
  })

  it('keeps a live MAX launch hash usable after clearing stale cache', () => {
    window.__BANANO_MINIAPP_PLATFORM__ = 'max'
    window.__BANANO_MAX_INIT_DATA__ = rejectedMaxInitData
    window.sessionStorage.setItem('__banano_max_init_data', rejectedMaxInitData)
    window.history.replaceState(
      {},
      '',
      '/mini-app/#WebAppData=fresh%3D1%26hash%3Dmax_live&WebAppVersion=26.20.0',
    )

    clearMiniAppInitData('max')

    expect(getInitData()).toBe('fresh=1&hash=max_live')
  })

  it('does not send signed launch credentials in telemetry href', () => {
    const fetchMock = jest.fn((_input: RequestInfo | URL, _init?: RequestInit) =>
      Promise.resolve(new Response('{}')),
    )
    global.fetch = fetchMock as unknown as typeof fetch
    window.history.replaceState(
      {},
      '',
      '/mini-app/?tgWebAppData=signed-secret&WebAppData=max-secret&safe=1',
    )

    reportMiniAppEvent('launch-live', { init_data_len: 13 })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const request = fetchMock.mock.calls[0][1] as RequestInit
    const body = JSON.parse(String(request.body))
    expect(body.href).toBe('/mini-app/')
    expect(JSON.stringify(body)).not.toContain('signed-secret')
    expect(JSON.stringify(body)).not.toContain('max-secret')
  })

  it('does not send signed launch credentials in generic client logs', () => {
    const fetchMock = jest.fn((_input: RequestInfo | URL, _init?: RequestInit) =>
      Promise.resolve(new Response('{}')),
    )
    global.fetch = fetchMock as unknown as typeof fetch
    Object.defineProperty(navigator, 'sendBeacon', {
      configurable: true,
      value: undefined,
    })
    window.history.replaceState(
      {},
      '',
      '/mini-app/?tgWebAppData=signed-secret&WebAppData=max-secret&safe=1',
    )

    sendMiniAppClientLog('launch-retry')

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const request = fetchMock.mock.calls[0][1] as RequestInit
    const body = JSON.parse(String(request.body))
    expect(body.href).toBe('/mini-app/')
    expect(body.search).toBe('')
    expect(JSON.stringify(body)).not.toContain('signed-secret')
    expect(JSON.stringify(body)).not.toContain('max-secret')
  })
})
