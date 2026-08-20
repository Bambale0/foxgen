import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { chromium } from 'playwright'

const baseUrl = 'http://127.0.0.1:4173/mini-app/'

const bootstrapPayload = {
  ok: true,
  telegram_id: 424242,
  first_name: 'E2E',
  last_name: 'Admin',
  telegram_username: 'e2e_admin',
  photo_url: '',
  referral_code: 'E2EADMIN',
  profile_link: '',
  referral_link: '',
  channel_url: '',
  prompt_repeat_balance_rub: 0,
  prompt_repeat_total_rub: 0,
  bot_username: 'test_bot',
  credits: 125,
  is_admin: true,
  mini_app_url: baseUrl,
  actions: [],
  payment_packages: [
    {
      id: 'mini',
      name: 'Старт',
      credits: 25,
      price_rub: 299,
      price_stars: 299,
      lava_offer_id: 'offer-mini',
      lava_currency: 'RUB',
      description: 'Тестовый пакет',
    },
  ],
  image_models: [
    {
      id: 'banana_pro',
      label: 'Banana Pro',
      description: 'Image model',
      cost: 2,
      ratios: ['1:1'],
      requires_reference: false,
      max_references: 3,
    },
  ],
  video_models: [
    {
      id: 'v3_pro',
      label: 'Kling 3 Pro',
      description: 'Video model',
      durations: [5, 10],
      ratios: ['16:9'],
      supports: ['text', 'imgtxt'],
      costs: { '5': 10, '10': 20 },
    },
    {
      id: 'v3_fast',
      label: 'Kling 3 Fast',
      description: 'Video model',
      durations: [5, 10],
      ratios: ['16:9'],
      supports: ['text', 'imgtxt'],
      costs: { '5': 8, '10': 16 },
    },
  ],
  recent_tasks: [],
  saved_references: [],
}

const curatedTrend = {
  id: 11,
  title: 'Curated Video',
  description: 'Official trend',
  prompt_text: 'Create a cinematic motion scene',
  category: 'video',
  tags: ['trend', 'trend-video'],
  uses_count: 2,
  likes: 3,
  preview_url: 'https://cdn.example/curated.mp4',
  model: 'v3_pro',
  generation_settings: {
    kind: 'video',
    user_input: 'photo',
    model: 'v3_pro',
    scenario: 'imgtxt',
    ratio: '16:9',
    duration: 5,
    grok_mode: 'normal',
    grok_resolution: '480p',
    kling_negative_prompt: '',
    kling_cfg_scale: 0.5,
  },
  author_id: 1,
  status: 'approved',
}

const ordinaryPrompt = {
  id: 12,
  title: 'Ordinary Prompt',
  description: 'Must not appear in trends',
  prompt_text: 'Portrait prompt',
  category: 'photo',
  tags: ['portrait'],
  uses_count: 1,
  likes: 0,
  preview_url: 'https://cdn.example/ordinary.jpg',
  model: 'banana_pro',
  author_id: 2,
  status: 'approved',
}

async function waitForServer(url, timeoutMs = 20_000) {
  const started = Date.now()
  while (Date.now() - started < timeoutMs) {
    try {
      const response = await fetch(url)
      if (response.ok) return
    } catch {
      // Server is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 200))
  }
  throw new Error(`Static server did not start: ${url}`)
}

const server = spawn(
  'python3',
  ['-m', 'http.server', '4173', '--directory', '.e2e-server'],
  { stdio: 'inherit' },
)

let browser
try {
  await waitForServer(baseUrl)

  browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({ viewport: { width: 430, height: 900 } })
  const page = await context.newPage()

  let paymentPayload = null
  let promptsPayload = null
  let trendGenerationPayload = null
  let trendPhotoUploadExpected = false

  await page.addInitScript(() => {
    window.__openedLinks = []
    window.Telegram = {
      WebApp: {
        initData: 'query_id=e2e',
        initDataUnsafe: {},
        ready() {},
        expand() {},
        openLink(url) {
          window.__openedLinks.push(url)
        },
        openInvoice(_url, callback) {
          callback?.('paid')
        },
      },
    }
  })

  // The production export ships a local Telegram SDK copy. Prevent that file
  // from replacing the deterministic WebApp bridge injected above.
  await page.route('**/telegram-web-app.js', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/javascript',
      body: '// Telegram WebApp is provided by the E2E init script.\n',
    })
  })

  await page.route('**/mini-app/api/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname

    if (path.endsWith('/bootstrap')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(bootstrapPayload),
      })
      return
    }

    if (path.endsWith('/create-payment')) {
      paymentPayload = JSON.parse(request.postData() || '{}')
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          provider: 'lava',
          order_id: 'e2e-order',
          payment_id: 'e2e-payment',
          payment_url: 'https://pay.example/e2e',
          credits: 25,
        }),
      })
      return
    }

    if (path.endsWith('/prompts')) {
      promptsPayload = JSON.parse(request.postData() || '{}')
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          prompts: [curatedTrend, ordinaryPrompt],
        }),
      })
      return
    }

    if (path.endsWith('/trends/run')) {
      trendGenerationPayload = JSON.parse(request.postData() || '{}')
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          status: 'done',
          task_id: 'trend-e2e-task',
          saved_url: 'https://cdn.example/trend-result.mp4',
          task_type: 'video',
          credits: 115,
          cost: 10,
          model: 'v3_pro',
          model_label: 'Kling 3 Pro',
          aspect_ratio: '16:9',
          duration: 5,
          prompt_hidden: true,
          prompt_actions_allowed: false,
          trend_id: curatedTrend.id,
        }),
      })
      return
    }

    if (path.endsWith('/upload')) {
      const isTrendPhoto = trendPhotoUploadExpected
      trendPhotoUploadExpected = false
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          url: isTrendPhoto
            ? 'https://cdn.example/user-trend-photo.jpg'
            : 'https://cdn.example/trend-upload.mp4',
          kind: isTrendPhoto ? 'image' : 'video',
          filename: isTrendPhoto ? 'user-photo.jpg' : 'trend.mp4',
          reference: null,
        }),
      })
      return
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true }),
    })
  })

  await page.goto(`${baseUrl}?tgWebAppData=query_id%3De2e`, {
    waitUntil: 'networkidle',
  })
  await page.getByText('Онлайн', { exact: true }).waitFor()

  // Payment E2E: form email -> backend payload -> Telegram WebApp.openLink.
  await page.locator('header button').last().click()
  await page.getByLabel('Почта для карты и СБП').fill('Buyer2026@Mail.ru')
  await page.getByRole('button', { name: 'Карта / СБП', exact: true }).click()

  await page.waitForFunction(() => (
    Array.isArray(window.__openedLinks)
      && window.__openedLinks.includes('https://pay.example/e2e')
  ))

  assert.equal(paymentPayload?.provider, 'lava')
  assert.equal(paymentPayload?.customer_email, 'buyer2026@mail.ru')
  await page.getByRole('button', { name: 'Закрыть пополнение' }).click()

  // Trends E2E: server-side tag query + client-side filtering.
  await page.getByRole('button', { name: /Тренды/ }).click()
  await page.getByText('Curated Video', { exact: true }).waitFor()
  assert.equal(promptsPayload?.source, 'tag')
  assert.equal(promptsPayload?.tag, 'trend')
  assert.equal(await page.getByText('Ordinary Prompt', { exact: true }).count(), 0)

  // User trend E2E: references only, no settings, immediate server-side run.
  await page.getByRole('button', { name: 'Повторить', exact: true }).click()
  const trendRunner = page.getByRole('dialog')
  await trendRunner.getByText('Загрузите свои фото', { exact: true }).waitFor()
  assert.equal(await trendRunner.locator('select').count(), 0)
  assert.equal(await trendRunner.getByText('Модель', { exact: true }).count(), 0)
  assert.equal(await trendRunner.getByText('Формат', { exact: true }).count(), 0)
  assert.equal(await trendRunner.getByText('Длительность', { exact: true }).count(), 0)

  trendPhotoUploadExpected = true
  const generatedResponse = page.waitForResponse((response) =>
    new URL(response.url()).pathname.endsWith('/trends/run'),
  )
  await trendRunner.locator('input[type="file"]').setInputFiles({
    name: 'user-photo.jpg',
    mimeType: 'image/jpeg',
    buffer: Buffer.from([255, 216, 255, 224, 0, 16, 74, 70, 73, 70]),
  })
  await generatedResponse

  assert.equal(trendGenerationPayload?.trend_id, curatedTrend.id)
  assert.deepEqual(
    trendGenerationPayload?.reference_urls,
    ['https://cdn.example/user-trend-photo.jpg'],
  )
  for (const forbiddenField of [
    'model',
    'prompt',
    'ratio',
    'quality',
    'duration',
    'generation_settings',
  ]) {
    assert.equal(
      Object.hasOwn(trendGenerationPayload || {}, forbiddenField),
      false,
      `User trend request must not contain ${forbiddenField}`,
    )
  }

  const taskDetailTitle = page.getByText('Детали задачи', { exact: true })
  await taskDetailTitle.waitFor()
  await page.mouse.click(10, 10)
  await taskDetailTitle.waitFor({ state: 'hidden' })

  // Admin upload E2E: uploaded preview survives duration/model changes.
  await page.getByRole('button', { name: 'Добавить', exact: true }).click()
  await page.getByRole('button', { name: 'Видео-тренд', exact: true }).click()
  await page.locator('input[type="file"]').setInputFiles({
    name: 'trend.mp4',
    mimeType: 'video/mp4',
    buffer: Buffer.from([0, 0, 0, 24, 102, 116, 121, 112]),
  })

  const uploadedPreview = page.locator('video[src="https://cdn.example/trend-upload.mp4"]')
  await uploadedPreview.waitFor()

  await page.locator('label').filter({ hasText: 'Длительность' }).locator('select').selectOption('10')
  assert.equal(await uploadedPreview.count(), 1)

  await page.locator('label').filter({ hasText: 'Видео-нейросеть' }).locator('select').selectOption('v3_fast')
  assert.equal(await uploadedPreview.count(), 1)

  console.log('Mini App critical browser E2E passed')
} finally {
  await browser?.close()
  server.kill('SIGTERM')
}
