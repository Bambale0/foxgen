import { render, screen, waitFor } from '@testing-library/react'
import { vi } from 'vitest'

const { state, bootstrap, apiMock } = vi.hoisted(() => {
  const data = {
    brand: 'Happy Fox',
    user: { id: 1, username: 'alena', display_name: 'Alena', photo_url: null, is_premium: true },
    balance: { available_units: 100, reserved_units: 0, total_units: 100, currency: 'CREDIT' },
    prices: [{ model_slug: 'nano-banana-2', amount_units: 10, enabled: true }],
    ledger: [],
    models: [{
      slug: 'nano-banana-2', title: 'Nano Banana 2', family: 'Nano Banana', media_kind: 'image', enabled: true,
      input_schema: {
        type: 'object',
        required: ['prompt'],
        properties: {
          prompt: { type: 'string', maxLength: 4000 },
          image_urls: { type: 'array', items: { type: 'string' } },
        },
      },
      defaults: {}, recommended_for: ['Изображения'], rank: 1,
    }],
    recent: [],
    features: { task_submission: true, input_media: true, feed: true, reference_memory: true },
    limits: { input_media_max_bytes: 50000000, generation_history_max: 100, ledger_history_max: 200 },
  }
  const publication = {
    id: 'post-1', generation_id: 'gen-1', author: { user_id: 7, slug: 'fox_author', display_name: 'Fox Author' },
    scope: 'feed', active: true, model_slug: 'nano-banana-2', media_kind: 'image', prompt: 'neon fox',
    likes_count: 2, comments_count: 1, remix_count: 3, liked_by_viewer: false, created_at: '2026-08-20T00:00:00Z',
    media: [{ url: 'https://storage.test/fox.webp', content_type: 'image/webp' }],
  }
  return {
    state: { startParam: '' },
    bootstrap: data,
    apiMock: {
      authenticate: vi.fn(async () => ({ access_token: 'token', token_type: 'bearer', expires_in: 3600, user: data.user })),
      bootstrap: vi.fn(async () => data),
      generation: vi.fn(async () => ({ id: 'gen-1', model_slug: 'nano-banana-2', media_kind: 'image', status: 'succeeded', prompt: 'neon fox', media: [] })),
      generations: vi.fn(async () => []),
      publicProfile: vi.fn(async () => ({ user_id: 7, slug: 'fox_author', display_name: 'Fox Author', bio: 'Public fox' })),
      profilePublications: vi.fn(async () => ({ items: [publication], next_offset: null })),
      publication: vi.fn(async () => publication),
      remixSource: vi.fn(async () => ({
        publication_id: 'post-1', generation_id: 'gen-1', author_slug: 'fox_author', model_slug: 'nano-banana-2',
        media_kind: 'image', prompt: 'neon fox', media: [{ url: 'https://storage.test/fox.webp', content_type: 'image/webp' }],
      })),
      feed: vi.fn(async () => ({ items: [], next_offset: null })),
      ownProfile: vi.fn(async () => ({ user_id: 1, slug: 'alena', display_name: 'Alena', bio: '' })),
      request: vi.fn(async () => ({ items: [] })),
      balance: vi.fn(async () => data.balance),
      prices: vi.fn(async () => data.prices),
      ledger: vi.fn(async () => []),
      starPackages: vi.fn(async () => ({ items: [] })),
      references: vi.fn(async () => ({ items: [], total: 0, used_bytes: 0, max_items: 50, max_bytes: 1_000_000 })),
      tariff: vi.fn(async () => null),
      support: vi.fn(async () => ({ items: [] })),
      partner: vi.fn(async () => ({ profile: { joined: false, earned_units: 0, withdrawn_units: 0, pending_units: 0, available_units: 0, referrals_count: 0 }, withdrawals: [] })),
    },
  }
})

vi.mock('@/lib/api', () => ({
  ApiError: class ApiError extends Error { status = 500 },
  miniAppApi: apiMock,
  telegramStartParam: () => state.startParam,
}))

import { MiniAppShell } from '@/components/mini-app-shell'
import { TabContent } from '@/components/tab-content'

function renderApp(startParam: string) {
  state.startParam = startParam
  return render(<MiniAppShell><TabContent /></MiniAppShell>)
}

describe('Happy Fox Telegram deep-link navigation', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    state.startParam = ''
  })

  it('focuses the exact generation', async () => {
    renderApp('generation_gen-1')
    expect(await screen.findByTestId('deep-link-generation')).toHaveTextContent('gen-1')
    expect(apiMock.generation).toHaveBeenCalledWith('gen-1')
  })

  it('opens the requested public profile rather than the owner editor', async () => {
    renderApp('profile_fox_author')
    expect(await screen.findByTestId('deep-link-profile')).toHaveTextContent('Fox Author')
    expect(screen.getByText('Public fox')).toBeInTheDocument()
    expect(apiMock.publicProfile).toHaveBeenCalledWith('fox_author')
  })

  it('opens the exact publication in the Feed workspace', async () => {
    renderApp('post_post-1')
    expect(await screen.findByTestId('workspace-feed')).toBeInTheDocument()
    expect(screen.getByText('Fox Author')).toBeInTheDocument()
    expect(screen.getByText('neon fox')).toBeInTheDocument()
    expect(apiMock.publication).toHaveBeenCalledWith('post-1')
  })

  it('opens Remix with backend prompt and media prefilled', async () => {
    renderApp('remix_post-1')
    expect(await screen.findByTestId('remix-prefill')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByDisplayValue('neon fox')).toBeInTheDocument())
    expect(apiMock.remixSource).toHaveBeenCalledWith('post-1')
  })

  it('opens the requested model directly', async () => {
    renderApp('model_nano-banana-2')
    expect(await screen.findByTestId('model-form')).toBeInTheDocument()
    expect(screen.getByText('Nano Banana 2')).toBeInTheDocument()
  })
})
