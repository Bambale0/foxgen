import { MiniAppAuthError, bootstrapApp, getInitData } from '../api'

function jsonResponse(status: number, payload: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({ 'content-type': 'application/json' }),
    text: async () => JSON.stringify(payload),
  } as unknown as Response
}

describe('Mini App launch auth failures', () => {
  const originalFetch = global.fetch

  beforeEach(() => {
    window.__BANANO_MINIAPP_PLATFORM__ = 'telegram'
  })

  afterEach(() => {
    global.fetch = originalFetch
    jest.useRealTimers()
    window.__BANANO_MINIAPP_PLATFORM__ = undefined
  })

  it('surfaces a rejected launch as a MiniAppAuthError', async () => {
    global.fetch = jest.fn(async () =>
      jsonResponse(401, { ok: false, error: 'Откройте Mini App заново из Telegram.' }),
    ) as unknown as typeof fetch

    expect(getInitData()).not.toBe('')
    await expect(bootstrapApp()).rejects.toBeInstanceOf(MiniAppAuthError)
  })

  it('keeps transient server failures retryable', async () => {
    global.fetch = jest.fn(async () =>
      jsonResponse(500, { ok: false, error: 'Мини-приложение недоступно' }),
    ) as unknown as typeof fetch

    const error = await bootstrapApp().catch((caught: unknown) => caught)

    expect(error).toBeInstanceOf(Error)
    expect(error).not.toBeInstanceOf(MiniAppAuthError)
  })

  it('aborts a stalled bootstrap request so launch recovery can retry', async () => {
    jest.useFakeTimers()
    const aborts: AbortSignal[] = []
    global.fetch = jest.fn((_url, init) => {
      const signal = (init as RequestInit | undefined)?.signal
      if (signal) aborts.push(signal)
      return new Promise<Response>((_resolve, reject) => {
        signal?.addEventListener('abort', () => {
          reject(Object.assign(new Error('aborted'), { name: 'AbortError' }))
        })
      })
    }) as unknown as typeof fetch

    const pending = bootstrapApp()

    jest.advanceTimersByTime(8000)
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
    expect(aborts).toHaveLength(1)
    expect(aborts[0].aborted).toBe(true)
  })

  it('keeps the bootstrap deadline active while reading a stalled response body', async () => {
    jest.useFakeTimers()
    const aborts: AbortSignal[] = []
    let bodyStarted = false
    let markBodyStarted!: () => void
    const bodyStartedPromise = new Promise<void>((resolve) => {
      markBodyStarted = resolve
    })
    global.fetch = jest.fn(async (_url, init) => {
      const signal = (init as RequestInit | undefined)?.signal
      if (signal) aborts.push(signal)
      return {
        ok: true,
        status: 200,
        url: '/mini-app/api/bootstrap',
        headers: new Headers({ 'content-type': 'application/json' }),
        text: () =>
          new Promise<string>((_resolve, reject) => {
            bodyStarted = true
            markBodyStarted()
            if (signal?.aborted) {
              reject(Object.assign(new Error('body aborted'), { name: 'AbortError' }))
              return
            }
            signal?.addEventListener('abort', () => {
              reject(Object.assign(new Error('body aborted'), { name: 'AbortError' }))
            })
          }),
      } as unknown as Response
    }) as unknown as typeof fetch

    const pending = bootstrapApp()

    await bodyStartedPromise
    expect(bodyStarted).toBe(true)
    jest.advanceTimersByTime(8000)
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
    expect(aborts).toHaveLength(1)
    expect(aborts[0].aborted).toBe(true)
  })
})
