import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'

const bootstrap = {
  brand: 'Happy Fox',
  user: { id: 1, username: 'alena', display_name: 'Alena', photo_url: null, is_premium: true },
  balance: { available_units: 100, reserved_units: 0, total_units: 100, currency: 'CREDIT' },
  prices: [{ model_slug: 'gpt-image-2', amount_units: 10, enabled: true }],
  ledger: [],
  models: [{
    slug: 'gpt-image-2', title: 'GPT Image 2', family: 'OpenAI', media_kind: 'image', enabled: true,
    input_schema: { type: 'object', required: ['prompt'], properties: { prompt: { type: 'string', maxLength: 4000 } } },
    defaults: {}, recommended_for: ['Изображения'], rank: 1,
  }],
  recent: [],
  features: { task_submission: true, input_media: true, feed: true, reference_memory: true },
  limits: { input_media_max_bytes: 50000000, generation_history_max: 100, ledger_history_max: 200 },
}

const apiMock = {
  authenticate: vi.fn(async () => ({ access_token: 'token', token_type: 'bearer', expires_in: 3600, user: bootstrap.user })),
  bootstrap: vi.fn(async () => bootstrap),
  generations: vi.fn(async () => []),
  balance: vi.fn(async () => bootstrap.balance),
  prices: vi.fn(async () => bootstrap.prices),
  ledger: vi.fn(async () => []),
  starPackages: vi.fn(async () => ({ items: [] })),
  feed: vi.fn(async () => ({ items: [], next_offset: null })),
  references: vi.fn(async () => ({ items: [], total: 0, used_bytes: 0, max_items: 50, max_bytes: 1_000_000 })),
  tariff: vi.fn(async () => null),
  support: vi.fn(async () => ({ items: [] })),
  partner: vi.fn(async () => ({ profile: { joined: false, earned_units: 0, withdrawn_units: 0, pending_units: 0, available_units: 0, referrals_count: 0 }, withdrawals: [] })),
  ownProfile: vi.fn(async () => ({ user_id: 1, slug: 'alena', display_name: 'Alena', bio: '' })),
  request: vi.fn(async () => ({ items: [] })),
}

vi.mock('@/lib/api', () => ({
  ApiError: class ApiError extends Error { status = 500 },
  miniAppApi: apiMock,
  telegramStartParam: () => '',
}))

import { MiniAppShell } from '@/components/mini-app-shell'
import { TabContent } from '@/components/tab-content'

function renderApp() {
  return render(<MiniAppShell><TabContent /></MiniAppShell>)
}

describe('Happy Fox primary navigation', () => {
  beforeEach(() => vi.clearAllMocks())

  it('changes every primary tab by direct React state', async () => {
    const user = userEvent.setup()
    renderApp()
    await screen.findByTestId('screen-home')

    const cases = [
      ['models', 'screen-models'],
      ['create', 'screen-create'],
      ['works', 'screen-works'],
      ['services', 'screen-services'],
      ['profile', 'screen-profile'],
      ['home', 'screen-home'],
    ] as const

    for (const [tab, target] of cases) {
      await user.click(screen.getByTestId(`tab-${tab}`))
      await waitFor(() => expect(screen.getByTestId(target)).toBeInTheDocument())
    }
  })

  it('opens a backend model into a real create form', async () => {
    const user = userEvent.setup()
    renderApp()
    await screen.findByTestId('screen-home')
    await user.click(screen.getByTestId('tab-models'))
    await user.click(screen.getByTestId('model-gpt-image-2'))
    expect(await screen.findByTestId('model-form')).toBeInTheDocument()
    expect(screen.getByText('GPT Image 2')).toBeInTheDocument()
  })

  it('opens a service workspace without proxy DOM clicks', async () => {
    const user = userEvent.setup()
    renderApp()
    await screen.findByTestId('screen-home')
    await user.click(screen.getByTestId('tab-services'))
    await user.click(screen.getByTestId('service-balance'))
    expect(await screen.findByTestId('workspace-balance')).toBeInTheDocument()
  })
})
