import assert from 'node:assert/strict'
import { execFileSync, spawn } from 'node:child_process'
import { cpSync, mkdirSync, rmSync } from 'node:fs'
import { chromium, devices, webkit } from 'playwright'

const baseUrl = 'http://127.0.0.1:4174/mini-app/'
const serverDir = '.e2e-max'
const miniAppDir = `${serverDir}/mini-app`
const initData = 'query_id=max-e2e&user=%7B%22id%22%3A515151%2C%22first_name%22%3A%22Max%22%7D&auth_date=1787972400&hash=test'

const bootstrapPayload = {
  ok: true,
  platform: 'max',
  max_user_id: 515151,
  first_name: 'MAX',
  last_name: 'E2E',
  telegram_username: 'max_e2e',
  photo_url: '',
  referral_code: '515151',
  profile_link: '',
  referral_link: '',
  channel_url: '',
  prompt_repeat_balance_rub: 0,
  prompt_repeat_total_rub: 0,
  bot_username: 'happyfoxmax',
  credits: 25,
  is_admin: false,
  actions: ['generate_image', 'generate_video'],
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
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 200))
  }
  throw new Error(`Static server did not start: ${url}`)
}

rmSync(serverDir, { recursive: true, force: true })
mkdirSync(serverDir, { recursive: true })
cpSync('out', miniAppDir, { recursive: true })
execFileSync('python3', ['../../scripts/render_happyfox_miniapp_channel.py', miniAppDir, 'max'], {
  stdio: 'inherit',
})

const server = spawn('python3', ['-m', 'http.server', '4174', '--directory', serverDir], {
  stdio: 'inherit',
})

const targets = [
  { name: 'max-android-chromium', browserType: chromium, device: devices['Pixel 7'], bridgePlatform: 'android' },
  { name: 'max-ios-webkit', browserType: webkit, device: devices['iPhone 14'], bridgePlatform: 'ios' },
]

try {
  await waitForServer(baseUrl)
  for (const target of targets) {
    const browser = await target.browserType.launch({ headless: true })
    try {
      const context = await browser.newContext({ ...target.device })
      const page = await context.newPage()
      let bootstrapRequest = null

      await page.addInitScript(
        ({ initDataValue, bridgePlatform }) => {
          window.WebApp = {
            initData: initDataValue,
            initDataUnsafe: { start_param: 'max_e2e_start' },
            platform: bridgePlatform,
            version: '26.20.0',
            ready() { window.__MAX_READY_CALLED__ = true },
            expand() { window.__MAX_EXPAND_CALLED__ = true },
            openLink() {},
          }
        },
        { initDataValue: initData, bridgePlatform: target.bridgePlatform },
      )

      await page.route('https://st.max.ru/js/max-web-app.js', async (route) => {
        await route.fulfill({ status: 200, contentType: 'application/javascript', body: '// E2E MAX bridge stub\n' })
      })
      await page.route('**/mini-app/api/**', async (route) => {
        const request = route.request()
        const path = new URL(request.url()).pathname
        if (path.endsWith('/bootstrap')) {
          bootstrapRequest = JSON.parse(request.postData() || '{}')
          await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(bootstrapPayload) })
          return
        }
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) })
      })

      const launchHash = [
        `WebAppData=${encodeURIComponent(initData)}`,
        'WebAppPlatform=android',
        'WebAppVersion=26.20.0',
        'WebAppStartParam=max_e2e_start',
      ].join('&')
      await page.goto(`${baseUrl}#${launchHash}`, { waitUntil: 'networkidle' })
      await page.waitForFunction(() => window.__BANANO_MINIAPP_PLATFORM__ === 'max')
      await page.waitForFunction(() => !document.querySelector('[aria-busy="true"]'))

      assert.ok(bootstrapRequest, `${target.name}: bootstrap request missing`)
      assert.equal(bootstrapRequest.platform, 'max', `${target.name}: frontend must identify MAX platform`)
      assert.equal(bootstrapRequest.init_data, initData, `${target.name}: MAX initData must reach bootstrap`)

      const state = await page.evaluate(() => ({
        platform: window.__BANANO_MINIAPP_PLATFORM__,
        cached: window.__BANANO_MAX_INIT_DATA__,
        bridgeInitData: window.WebApp?.initData || '',
        readyCalled: Boolean(window.__MAX_READY_CALLED__),
        expandCalled: Boolean(window.__MAX_EXPAND_CALLED__),
        text: document.body.textContent || '',
        scripts: Array.from(document.head.querySelectorAll('script')).map((script) => script.getAttribute('src') || ''),
      }))
      assert.equal(state.platform, 'max', `${target.name}: platform cache mismatch`)
      assert.equal(state.cached, initData, `${target.name}: MAX initData cache mismatch`)
      assert.equal(state.bridgeInitData, initData, `${target.name}: MAX initData mismatch`)
      assert.equal(state.readyCalled, true, `${target.name}: MAX ready() was not called`)
      assert.equal(state.expandCalled, true, `${target.name}: MAX expand() was not called`)
      assert.equal(state.text.includes('Войдите через Telegram'), false, `${target.name}: Telegram browser gate appeared`)
      assert.ok(state.scripts.includes('https://st.max.ru/js/max-web-app.js'), `${target.name}: MAX Bridge missing`)
      assert.equal(state.scripts.includes('/mini-app/telegram-web-app.js'), false, `${target.name}: Telegram SDK must not load`)

      await context.close()
      console.log(`MAX startup E2E passed: ${target.name}`)
    } finally {
      await browser.close()
    }
  }
} finally {
  server.kill('SIGTERM')
  rmSync(serverDir, { recursive: true, force: true })
}
