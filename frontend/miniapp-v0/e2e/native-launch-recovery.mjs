import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { chromium, devices, webkit } from 'playwright'

const baseUrl = 'http://127.0.0.1:4175/mini-app/'
const initData = 'query_id=e2e-recovery&user=%7B%22id%22%3A424242%7D&auth_date=1787972400&hash=test'

const bootstrapPayload = {
  ok: true,
  telegram_id: 424242,
  first_name: 'iOS',
  last_name: 'E2E',
  telegram_username: 'ios_e2e',
  photo_url: '',
  referral_code: 'LAUNCHRECOVERY',
  profile_link: '',
  referral_link: '',
  channel_url: '',
  prompt_repeat_balance_rub: 0,
  prompt_repeat_total_rub: 0,
  bot_username: 'test_bot',
  credits: 10,
  is_admin: false,
  actions: [],
  payment_packages: [],
  image_models: [],
  video_models: [],
  recent_tasks: [],
  saved_references: [],
}

// Three in-flight launch retries plus the first scheduled gate retry fail before
// the backend becomes healthy again.
const failuresBeforeRecovery = 4

async function waitForServer(url, timeoutMs = 20_000) {
  const started = Date.now()
  while (Date.now() - started < timeoutMs) {
    try {
      const response = await fetch(url)
      if (response.ok) return
    } catch {
      // Static server is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 200))
  }
  throw new Error(`Static server did not start: ${url}`)
}

const server = spawn(
  'python3',
  ['-m', 'http.server', '4175', '--directory', '.e2e-server'],
  { stdio: 'inherit' },
)

const targets = [
  {
    name: 'android-chromium',
    browserType: chromium,
    device: devices['Pixel 7'],
    platform: 'android',
  },
  {
    name: 'ios-webkit',
    browserType: webkit,
    device: devices['iPhone 14'],
    platform: 'ios',
  },
]

try {
  await waitForServer(baseUrl)

  for (const target of targets) {
    const browser = await target.browserType.launch({ headless: true })
    try {
      const context = await browser.newContext({ ...target.device })
      const page = await context.newPage()
      const widgetRequests = []

      page.on('request', (request) => {
        if (request.url().includes('telegram-widget.js')) widgetRequests.push(request.url())
      })

      let bootstrapAttempts = 0

      await page.route('**/mini-app/api/**', async (route) => {
        const path = new URL(route.request().url()).pathname

        if (path.endsWith('/bootstrap')) {
          bootstrapAttempts += 1
          if (bootstrapAttempts <= failuresBeforeRecovery) {
            await route.fulfill({
              status: 500,
              contentType: 'application/json',
              body: JSON.stringify({ ok: false, error: 'Mini App bootstrap failed' }),
            })
            return
          }
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(bootstrapPayload),
          })
          return
        }

        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ ok: true, bot_username: 'test_bot' }),
        })
      })

      // A native Telegram WebView injects its bridge before any page script runs.
      await page.addInitScript(() => {
        window.TelegramWebviewProxy = { postEvent: () => {} }
      })

      const launchHash = [
        `tgWebAppData=${encodeURIComponent(initData)}`,
        'tgWebAppVersion=8.0',
        `tgWebAppPlatform=${target.platform}`,
      ].join('&')

      await page.goto(`${baseUrl}#${launchHash}`, { waitUntil: 'domcontentloaded' })

      // The failed launch lands on the native recovery screen, never on the browser login.
      const retryButton = page.getByRole('button', { name: 'Попробовать снова' })
      await retryButton.waitFor({ timeout: 30_000 })
      assert.equal(
        await page.getByText(/Войдите через Telegram/).count(),
        0,
        `${target.name}: a native Telegram launch must not ask for a browser login`,
      )
      assert.equal(
        await page.locator('script[src*="telegram-widget.js"]').count(),
        0,
        `${target.name}: a native Telegram launch must not render the browser login widget`,
      )
      assert.ok(
        bootstrapAttempts >= 2,
        `${target.name}: the launch handshake must be retried before locking`,
      )

      // Recovery must arrive from the automatic retry, without any user action.
      await page.waitForFunction(() => document.body.textContent?.includes('Онлайн'), null, {
        timeout: 30_000,
      })

      assert.equal(
        widgetRequests.length,
        0,
        `${target.name}: the browser login widget must never load for a native launch`,
      )
      assert.ok(
        bootstrapAttempts > failuresBeforeRecovery,
        `${target.name}: the Mini App must recover through an automatic retry`,
      )
      assert.equal(
        await retryButton.count(),
        0,
        `${target.name}: the recovery screen must be gone once the launch succeeded`,
      )

      await context.close()
      console.log(`Native launch recovery E2E passed: ${target.name}`)
    } finally {
      await browser.close()
    }
  }
} finally {
  server.kill('SIGTERM')
}