import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'

const { apiMock, socialApiMock } = vi.hoisted(() => {
  const publication = {
    id: 'post-1',
    generation_id: 'gen-1',
    author: { user_id: 7, slug: 'fox_author', display_name: 'Fox Author' },
    scope: 'feed',
    active: true,
    model_slug: 'nano-banana-2',
    media_kind: 'image',
    prompt: 'neon fox',
    prompt_actions_allowed: true,
    likes_count: 2,
    comments_count: 1,
    remix_count: 3,
    liked_by_viewer: false,
    created_at: '2026-08-20T00:00:00Z',
    media: [{ url: 'https://storage.test/fox.webp', content_type: 'image/webp' }],
  }
  const data = {
    brand: 'Happy Fox',
    user: { id: 1, username: 'alena', display_name: 'Alena', photo_url: null, is_premium: true },
    balance: { available_units: 100, reserved_units: 0, total_units: 100, currency: 'CREDIT' },
    prices: [{ model_slug: 'nano-banana-2', amount_units: 10, enabled: true }],
    ledger: [],
    models: [{
      slug: 'nano-banana-2',
      title: 'Nano Banana 2',
      family: 'Nano Banana',
      media_kind: 'image',
      enabled: true,
      input_schema: {
        type: 'object',
        required: ['prompt'],
        properties: {
          prompt: { type: 'string', maxLength: 4000 },
          image_urls: { type: 'array', items: { type: 'string' } },
        },
      },
      defaults: {},
      recommended_for: ['Изображения'],
      rank: 1,
    }],
    recent: [],
    features: { task_submission: true, input_media: true, feed: true, reference_memory: true },
    limits: { input_media_max_bytes: 50_000_000, generation_history_max: 100, ledger_history_max: 200 },
  }
  return {
    apiMock: {
      authenticate: vi.fn(async () => ({ access_token: 'token', token_type: 'bearer', expires_in: 3600, user: data.user })),
      bootstrap: vi.fn(async () => data),
      generations: vi.fn(async () => []),
      feed: vi.fn(async () => ({ items: [publication], next_offset: null })),
      remixSource: vi.fn(async () => ({
        publication_id: 'post-1',
        generation_id: 'gen-1',
        author_slug: 'fox_author',
        model_slug: 'nano-banana-2',
        media_kind: 'image',
        prompt: 'neon fox',
        media: [{ url: 'https://storage.test/fox.webp', content_type: 'image/webp' }],
      })),
      setLike: vi.fn(async () => ({ liked: true, likes_count: 3 })),
      balance: vi.fn(async () => data.balance),
      prices: vi.fn(async () => data.prices),
      ledger: vi.fn(async () => []),
      starPackages: vi.fn(async () => ({ items: [] })),
      references: vi.fn(async () => ({ items: [], total: 0, used_bytes: 0, max_items: 50, max_bytes: 1_000_000 })),
      tariff: vi.fn(async () => null),
      support: vi.fn(async () => ({ items: [] })),
      partner: vi.fn(async () => ({ profile: { joined: false, earned_units: 0, withdrawn_units: 0, pending_units: 0, available_units: 0, referrals_count: 0 }, withdrawals: [] })),
      ownProfile: vi.fn(async () => ({ user_id: 1, slug: 'alena', display_name: 'Alena', bio: '' })),
      request: vi.fn(async () => ({ items: [] })),
    },
    socialApiMock: {
      comments: vi.fn(async () => ({ items: [{
        id: 'comment-1',
        publication_id: 'post-1',
        surface: 'feed',
        author: { user_id: 7, slug: 'fox_author', display_name: 'Fox Author' },
        body: 'Первый комментарий',
        created_at: '2026-08-20T00:01:00Z',
      }] })),
      addComment: vi.fn(async (_id: string, body: string) => ({
        id: 'comment-2',
        publication_id: 'post-1',
        surface: 'feed',
        author: { user_id: 1, slug: 'alena', display_name: 'Alena' },
        body,
        created_at: '2026-08-20T00:02:00Z',
      })),
    },
  }
})

vi.mock('@/lib/api', () => ({
  ApiError: class ApiError extends Error { status = 500 },
  miniAppApi: apiMock,
  telegramStartParam: () => '',
}))

vi.mock('@/lib/social-api', () => ({ socialApi: socialApiMock }))

import { MiniAppShell } from '@/components/mini-app-shell'
import { TabContent } from '@/components/tab-content'

function renderApp() {
  return render(<MiniAppShell><TabContent /></MiniAppShell>)
}

async function openFeed() {
  const user = userEvent.setup()
  renderApp()
  await screen.findByTestId('screen-home')
  await user.click(screen.getByTestId('tab-services'))
  await user.click(screen.getByTestId('service-feed'))
  await screen.findByTestId('publication-post-1')
  return user
}

describe('Happy Fox feed actions', () => {
  beforeEach(() => vi.clearAllMocks())

  it('loads and posts real publication comments from the rendered feed', async () => {
    const user = await openFeed()
    await user.click(screen.getByTestId('comments-post-1'))
    expect(await screen.findByText('Первый комментарий')).toBeInTheDocument()
    await user.type(screen.getByPlaceholderText('Напишите комментарий'), 'Новый комментарий')
    await user.click(screen.getByRole('button', { name: 'Отправить комментарий' }))
    expect(await screen.findByText('Новый комментарий')).toBeInTheDocument()
    expect(socialApiMock.addComment).toHaveBeenCalledWith('post-1', 'Новый комментарий')
  })

  it('resolves Remix from the backend and opens a prefilled model form with lineage', async () => {
    const user = await openFeed()
    await user.click(screen.getByTestId('remix-post-1'))
    expect(await screen.findByTestId('model-form')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByDisplayValue('neon fox')).toBeInTheDocument())
    expect(screen.getByTestId('remix-prefill')).toBeInTheDocument()
    expect(apiMock.remixSource).toHaveBeenCalledWith('post-1')
  })
})
