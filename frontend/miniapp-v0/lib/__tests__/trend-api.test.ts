import fs from 'node:fs'
import path from 'node:path'

import { runTrend } from '../trend-api'

describe('runTrend', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
    window.history.replaceState({}, '', '/mini-app/')
    const webApp = window.Telegram?.WebApp
    if (!webApp) throw new Error('Telegram WebApp mock is unavailable')
    webApp.initData = 'signed-init-data'
    webApp.initDataUnsafe = { start_param: '' }
  })

  afterEach(() => {
    jest.restoreAllMocks()
    const webApp = window.Telegram?.WebApp
    if (webApp) {
      webApp.initData = 'mock_init_data'
      webApp.initDataUnsafe = { start_param: '' }
    }
  })

  it('sends only the trend id and uploaded references, never generation settings', async () => {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      text: async () =>
        JSON.stringify({
          ok: true,
          status: 'queued',
          task_id: 'trend-task-1',
          task_type: 'image',
          saved_url: null,
          credits: 4,
          cost: 1,
          model: 'banana_pro',
          model_label: 'Nano Banana Pro',
          aspect_ratio: '1:1',
          duration: null,
          prompt_hidden: true,
          prompt_actions_allowed: false,
          trend_id: 42,
        }),
    })
    global.fetch = fetchMock as unknown as typeof fetch

    const result = await runTrend(42, ['https://example.test/reference.jpg'])

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/mini-app/api/trends/run')
    expect(options.method).toBe('POST')

    const body = JSON.parse(String(options.body))
    expect(body).toEqual({
      init_data: 'signed-init-data',
      trend_id: 42,
      reference_urls: ['https://example.test/reference.jpg'],
    })
    expect(body).not.toHaveProperty('model')
    expect(body).not.toHaveProperty('prompt')
    expect(body).not.toHaveProperty('ratio')
    expect(body).not.toHaveProperty('quality')
    expect(body).not.toHaveProperty('duration')
    expect(body).not.toHaveProperty('generation_settings')

    expect(result.task.model).toBe('banana_pro')
    expect(result.task.aspect_ratio).toBe('1:1')
    expect(result.task.prompt_hidden).toBe(true)
    expect(result.task.prompt_actions_allowed).toBe(false)
  })

  it('keeps all generation controls out of the user trend runner', () => {
    const runnerPath = path.join(
      process.cwd(),
      'components',
      'trend-runner-dialog.tsx',
    )
    const source = fs.readFileSync(runnerPath, 'utf8')

    expect(source).toContain('runTrend(')
    expect(source).toContain('multiple')
    expect(source).not.toContain('resolveTrendSettings')
    expect(source).not.toContain('generateImage')
    expect(source).not.toContain('generateVideo')
    expect(source).not.toContain('<ModelSelect')
    expect(source).not.toContain('<RatioSelect')
    expect(source).not.toContain('<QualitySelect')
  })
})
