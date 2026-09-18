import { createPayment } from '../payment-api'
jest.mock('../api', () => ({
  getApiBasePath: () => '/mini-app/api', getInitData: () => 'signed',
  getMiniAppPlatform: () => 'max', getStartParamFallback: () => '',
}))

afterEach(() => { jest.useRealTimers(); jest.restoreAllMocks() })

test('payment errors with an object remain readable', async () => {
  global.fetch = jest.fn().mockResolvedValue({ ok: false, text: async () => JSON.stringify({ ok: false, error: { Message: 'provider failure' } }) })
  await expect(createPayment({ packageId: 'start', provider: 'yookassa' }))
    .rejects.toThrow('Не удалось создать платёж. Попробуйте снова.')
})

test('payment creation has a deadline and allows another attempt', async () => {
  jest.useFakeTimers()
  global.fetch = jest.fn().mockImplementation((_url, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
  }))
  const request = createPayment({ packageId: 'start', provider: 'yookassa' })
  const assertion = expect(request).rejects.toThrow('не ответил вовремя')
  await jest.advanceTimersByTimeAsync(20_000)
  await assertion
  expect(jest.getTimerCount()).toBe(0)
})
