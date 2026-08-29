import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { chromium, devices, webkit } from 'playwright'

const baseUrl = 'http://127.0.0.1:4174/mini-app/'
const initData = 'query_id=e2e-startup&user=%7B%22id%22%3A424242%7D&auth_date=1787972400&hash=test'

const bootstrapPayload = {
  ok: true,
  telegram_id: 424242,
  first_name: 'iOS',
  last_name: 'E2E',
  telegram_username: 'ios_e2e',
  photo_url: '',
  referral_code: 'IOSWEBKIT',
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
  ['-m', 'http.server', '4174', '--directory', '.e2e-server'],
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
      let bootstrapInitData = ''

      await page.route('**/mini-app/api/**', async (route) => {
        const request = route.request()
        const path = new URL(request.url()).pathname

        if (path.endsWith('/bootstrap')) {
          const payload = JSON.parse(request.postData() || '{}')
          bootstrapInitData = String(payload.init_data || '')
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
          body: JSON.stringify({ ok: true }),
        })
      })

      const themeParams = encodeURIComponent(JSON.stringify({
        bg_color: '#050505',
        text_color: '#ffffff',
      }))
      const launchHash = [
        `tgWebAppData=${encodeURIComponent(initData)}`,
        'tgWebAppVersion=8.0',
        `tgWebAppPlatform=${target.platform}`,
        `tgWebAppThemeParams=${themeParams}`,
      ].join('&')

      await page.goto(`${baseUrl}#${launchHash}`, { waitUntil: 'networkidle' })
      await page.waitForFunction(() => Boolean(window.Telegram?.WebApp?.initData))
      await page.waitForFunction(() => document.body.textContent?.includes('Онлайн'))

      assert.equal(
        bootstrapInitData,
        initData,
        `${target.name}: real Telegram SDK initData must reach bootstrap`,
      )

      const sdkState = await page.evaluate(() => ({
        initData: window.Telegram?.WebApp?.initData || '',
        version: window.Telegram?.WebApp?.version || '',
        platform: window.Telegram?.WebApp?.platform || '',
      }))
      assert.equal(sdkState.initData, initData, `${target.name}: Telegram SDK initData mismatch`)
      assert.equal(sdkState.version, '8.0', `${target.name}: Telegram SDK version mismatch`)
      assert.equal(sdkState.platform, target.platform, `${target.name}: Telegram SDK platform mismatch`)

      const headContract = await page.evaluate(() => {
        const scripts = Array.from(document.head.querySelectorAll('script'))
        const sdk = scripts.find((script) => script.getAttribute('src') === '/mini-app/telegram-web-app.js')
        const early = scripts.find((script) => script.id === 'telegram-early-ready')
        const firstNextIndex = scripts.findIndex((script) =>
          String(script.getAttribute('src') || '').startsWith('/mini-app/_next/static/'),
        )
        return {
          sdkIndex: sdk ? scripts.indexOf(sdk) : -1,
          firstNextIndex,
          sdkAsync: sdk?.async ?? null,
          sdkDefer: sdk?.defer ?? null,
          earlyText: early?.textContent || '',
        }
      })

      assert.ok(headContract.sdkIndex >= 0, `${target.name}: Telegram SDK script missing`)
      assert.ok(
        headContract.firstNextIndex < 0 || headContract.sdkIndex < headContract.firstNextIndex,
        `${target.name}: Telegram SDK must execute before Next.js runtime`,
      )
      assert.equal(headContract.sdkAsync, false, `${target.name}: Telegram SDK must not be async`)
      assert.equal(headContract.sdkDefer, false, `${target.name}: Telegram SDK must not be deferred`)
      assert.equal(
        /TelegramWebviewProxy|window\.webkit|window\.external\.notify/.test(headContract.earlyText),
        false,
        `${target.name}: application bootstrap must not bypass Telegram.WebApp SDK`,
      )

      await context.close()
      console.log(`Telegram startup E2E passed: ${target.name}`)
    } finally {
      await browser.close()
    }
  }
} finally {
  server.kill('SIGTERM')
}
