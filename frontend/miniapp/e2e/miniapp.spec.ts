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
  // In deterministic application E2E we own the Telegram bridge. The real remote SDK
  // would replace window.Telegram while running outside Telegram and erase our signed
  // initData. The real SDK/native bridge remains covered by the later staging WebView smoke.
  await page.route('https://telegram.org/js/telegram-web-app.js**', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/javascript', body: '' })
  })
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

async function openLiveMiniApp(page: Page, startParam = '', expectedTestId = 'screen-home') {
  const pageErrors: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error.message))
  await installTelegramBridge(page, startParam)
  await page.goto('./')
  await expect.poll(async () => page.evaluate(() => window.Telegram?.WebApp?.initData?.length ?? 0)).toBeGreaterThan(0)
  await expect(page.getByTestId(expectedTestId)).toBeVisible()
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

  test('resolves a Telegram model start_param into the real create form', async ({ page }) => {
    const pageErrors = await openLiveMiniApp(page, 'model_seedream-5-pro', 'model-form')
    await expect(page.getByText('Seedream 5 Pro')).toBeVisible()
    await expect(page.getByTestId('screen-create')).toBeVisible()
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

  test('comments on a publication and opens Remix from the rendered feed', async ({ page }) => {
    const publication = {
      id: 'post-e2e',
      generation_id: 'generation-e2e',
      author: { user_id: 7, slug: 'fox_author', display_name: 'Fox Author' },
      scope: 'feed',
      active: true,
      model_slug: 'seedream-5-pro',
      media_kind: 'image',
      prompt: 'cinematic orange fox',
      prompt_actions_allowed: true,
      likes_count: 2,
      comments_count: 1,
      remix_count: 3,
      liked_by_viewer: false,
      source_publication_id: null,
      created_at: '2026-08-20T00:00:00Z',
      media: [],
    }

    await page.route('**/v1/miniapp/feed?**', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [publication], next_offset: null }) })
    })
    await page.route('**/v1/miniapp/publications/post-e2e/comments**', async (route) => {
      if (route.request().method() === 'POST') {
        const payload = route.request().postDataJSON() as { body: string }
        await route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify({
            id: 'comment-new', publication_id: 'post-e2e', surface: 'feed',
            author: { user_id: 987654321, slug: 'happyfox_e2e', display_name: 'Happy Fox' },
            body: payload.body, created_at: '2026-08-20T00:02:00Z',
          }),
        })
        return
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: [{
          id: 'comment-old', publication_id: 'post-e2e', surface: 'feed',
          author: { user_id: 7, slug: 'fox_author', display_name: 'Fox Author' },
          body: 'Первый комментарий', created_at: '2026-08-20T00:01:00Z',
        }] }),
      })
    })
    await page.route('**/v1/miniapp/publications/post-e2e/remix', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          publication_id: 'post-e2e', generation_id: 'generation-e2e', author_slug: 'fox_author',
          model_slug: 'seedream-5-pro', media_kind: 'image', prompt: 'cinematic orange fox', media: [],
        }),
      })
    })

    const pageErrors = await openLiveMiniApp(page)
    await page.getByTestId('tab-services').click()
    await page.getByTestId('service-feed').click()
    await expect(page.getByTestId('publication-post-e2e')).toBeVisible()

    await page.getByTestId('comments-post-e2e').click()
    await expect(page.getByText('Первый комментарий')).toBeVisible()
    await page.getByPlaceholder('Напишите комментарий').fill('Browser E2E комментарий')
    await page.getByRole('button', { name: 'Отправить комментарий' }).click()
    await expect(page.getByText('Browser E2E комментарий')).toBeVisible()

    await page.getByTestId('remix-post-e2e').click()
    const form = page.getByTestId('model-form')
    await expect(form).toBeVisible()
    await expect(page.getByTestId('remix-prefill')).toBeVisible()
    await expect(form.getByTestId('field-prompt')).toHaveValue('cinematic orange fox')
    expect(pageErrors).toEqual([])
  })
})
