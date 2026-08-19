import { createHmac } from 'node:crypto'
import { expect, test, type Page } from '@playwright/test'

const botToken = process.env.E2E_TELEGRAM_BOT_TOKEN ?? '123456789:AAFoxGenBrowserE2ETestToken'

function telegramInitData(startParam = '') {
  const user = JSON.stringify({
    id: 987654321,
    first_name: 'Happy',
    last_name: 'Fox',
    username: 'happyfox_e2e',
    language_code: 'ru',
    is_premium: true,
  })
  const values: Record<string, string> = {
    auth_date: String(Math.floor(Date.now() / 1000)),
    query_id: `AAE2E${Date.now()}`,
    user,
  }
  if (startParam) values.start_param = startParam
  const dataCheckString = Object.entries(values)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, value]) => `${key}=${value}`)
    .join('\n')
  const secret = createHmac('sha256', 'WebAppData').update(botToken).digest()
  const hash = createHmac('sha256', secret).update(dataCheckString).digest('hex')
  return new URLSearchParams({ ...values, hash }).toString()
}

async function installTelegramBridge(page: Page, startParam = '') {
  const initData = telegramInitData(startParam)
  await page.addInitScript(({ rawInitData, rawStartParam }) => {
    const noop = () => undefined
    ;(window as unknown as { Telegram: unknown }).Telegram = {
      WebApp: {
        initData: rawInitData,
        initDataUnsafe: { start_param: rawStartParam || undefined },
        version: '9.0',
        platform: 'e2e',
        colorScheme: 'dark',
        themeParams: {},
        ready: noop,
        expand: noop,
        setHeaderColor: noop,
        setBackgroundColor: noop,
        setBottomBarColor: noop,
        HapticFeedback: { impactOccurred: noop },
        openInvoice: (_url: string, callback?: (status: string) => void) => callback?.('cancelled'),
      },
    }
  }, { rawInitData: initData, rawStartParam: startParam })
}

async function openLiveMiniApp(page: Page, startParam = '') {
  const pageErrors: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error.message))
  await installTelegramBridge(page, startParam)
  await page.goto('./')
  await expect(page.getByTestId('screen-home')).toBeVisible()
  await expect(page.getByTestId('happyfox-logo')).toBeVisible()
  expect(pageErrors).toEqual([])
  return pageErrors
}

test.describe('Happy Fox production browser E2E', () => {
  test('fails closed outside Telegram', async ({ page }) => {
    await page.goto('./')
    await expect(page.getByTestId('miniapp-error')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Откройте Happy Fox в Telegram' })).toBeVisible()
  })

  test('authenticates against FastAPI and every primary tab is clickable', async ({ page }) => {
    const pageErrors = await openLiveMiniApp(page)
    const cases = [
      ['models', 'screen-models'],
      ['create', 'screen-create'],
      ['works', 'screen-works'],
      ['services', 'screen-services'],
      ['profile', 'screen-profile'],
      ['home', 'screen-home'],
    ] as const

    for (const [tab, screen] of cases) {
      await page.getByTestId(`tab-${tab}`).click()
      await expect(page.getByTestId(screen)).toBeVisible()
    }

    expect(pageErrors).toEqual([])
  })

  test('opens a live backend model and renders its schema-driven form', async ({ page }) => {
    const pageErrors = await openLiveMiniApp(page)
    await page.getByTestId('tab-models').click()
    const modelCards = page.locator('[data-testid^="model-"]')
    await expect(modelCards.first()).toBeVisible()
    expect(await modelCards.count()).toBeGreaterThan(0)
    await modelCards.first().click()
    await expect(page.getByTestId('model-form').or(page.getByTestId('special-model-form'))).toBeVisible()
    expect(pageErrors).toEqual([])
  })

  test('opens a real service workspace from the rendered UI', async ({ page }) => {
    const pageErrors = await openLiveMiniApp(page)
    await page.getByTestId('tab-services').click()
    await page.getByTestId('service-balance').click()
    await expect(page.getByTestId('workspace-balance')).toBeVisible()
    await expect(page.getByText('BALANCE / LIVE')).toBeVisible()
    expect(pageErrors).toEqual([])
  })
})
