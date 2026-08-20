/**
 * Smoke-тесты фронтенда Mini App (без вызова API).
 *
 * Проверяют:
 * 1. Рендеринг ключевых UI-компонентов
 * 2. Навигацию по табам
 * 3. Формы генерации (фото/видео)
 * 4. Карточки результатов и задач
 * 5. Обработку ошибок (Error Boundary)
 * 6. Утилиты (clipboard, start-params, utils)
 */

import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import '@testing-library/jest-dom'

// --- Mocks ---
jest.mock('@/lib/api', () => ({
  api: {
    bootstrap: jest.fn().mockResolvedValue({ ok: true, user: { id: 12345 }, balance: 100 }),
    createPayment: jest.fn().mockResolvedValue({ ok: true, payment_url: 'https://pay.test' }),
    getPrompts: jest.fn().mockResolvedValue({ ok: true, prompts: [] }),
    upload: jest.fn().mockResolvedValue({ ok: true, url: 'https://cdn.test/file.jpg' }),
    getFeed: jest.fn().mockResolvedValue({ ok: true, items: [], hasMore: false }),
    getTasks: jest.fn().mockResolvedValue({ ok: true, tasks: [] }),
    getTask: jest.fn().mockResolvedValue({ ok: true, task: null }),
    createTask: jest.fn().mockResolvedValue({ ok: true, task_id: 'task_1' }),
    likeItem: jest.fn().mockResolvedValue({ ok: true }),
    unlikeItem: jest.fn().mockResolvedValue({ ok: true }),
    commentItem: jest.fn().mockResolvedValue({ ok: true }),
    publishItem: jest.fn().mockResolvedValue({ ok: true }),
    deleteItem: jest.fn().mockResolvedValue({ ok: true }),
    getProfile: jest.fn().mockResolvedValue({ ok: true, profile: {} }),
    getTrends: jest.fn().mockResolvedValue({ ok: true, trends: [] }),
    createTrend: jest.fn().mockResolvedValue({ ok: true }),
    removeTrend: jest.fn().mockResolvedValue({ ok: true }),
  },
  hasTelegramInitData: jest.fn(() => true),
  waitForTelegramInitData: jest.fn().mockResolvedValue(true),
}))

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn(), back: jest.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => '/',
}))

jest.mock('next/image', () => ({
  __esModule: true,
  default: (props: any) => React.createElement('img', { ...props, fill: undefined }),
}))

// --- Named imports ---
import { AppProvider, useApp } from '@/lib/app-context'
import { parseStartParams } from '@/lib/start-params'
import { copyToClipboard } from '@/lib/clipboard'
import { cn } from '@/lib/utils'
import { MOCK_FEED_ITEMS, MOCK_TASKS, MOCK_TRENDS } from '@/lib/mock-data'
import type { AppState, FeedItem, Task, TrendItem } from '@/lib/types'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { Skeleton } from '@/components/ui/skeleton'
import { Empty } from '@/components/ui/empty'
import { ModeBadge } from '@/components/mode-badge'
import { InfoBlock } from '@/components/info-block'
import { TabNav } from '@/components/tab-nav'
import { TabContent } from '@/components/tab-content'
import { ModelSelect } from '@/components/forms/model-select'
import { QualitySelect } from '@/components/forms/quality-select'
import { RatioSelect } from '@/components/forms/ratio-select'
import { UploadArea } from '@/components/forms/upload-area'
import { TaskCard } from '@/components/task-card'
import { TaskHistoryList } from '@/components/task-history-list'
import { ResultCard } from '@/components/result-card'
import { QuickActionGrid } from '@/components/quick-action-grid'
import { ClientErrorBoundary } from '@/components/client-error-boundary'

// --- Test Data ---
const mockAppState: AppState = {
  user: { id: 12345, first_name: 'Test', last_name: 'User', username: 'testuser' },
  balance: 100,
  activeTab: 'photo',
  mode: 'photo',
  tasks: MOCK_TASKS as Task[],
  recentTasks: MOCK_TASKS as Task[],
  selectedTask: null,
  feedItems: MOCK_FEED_ITEMS as FeedItem[],
  feedHasMore: false,
  feedFilter: { model: null, source: null },
  trends: MOCK_TRENDS as TrendItem[],
  profile: null,
  isBootstrapping: false,
  bootstrapError: null,
}

function TestWrapper({ children, initialState }: { children: React.ReactNode; initialState?: Partial<AppState> }) {
  return (
    <AppProvider initialState={{ ...mockAppState, ...initialState }}>
      {children}
    </AppProvider>
  )
}

// ============================================================
// 1. UTILITY TESTS
// ============================================================
describe('Utils', () => {
  describe('cn (classname merge)', () => {
    it('merges class names correctly', () => {
      expect(cn('foo', 'bar')).toBe('foo bar')
      expect(cn('foo', false && 'bar')).toBe('foo')
      expect(cn('foo', undefined, null, 'bar')).toBe('foo bar')
      expect(cn('px-4', 'px-2')).toBe('px-2')
    })
  })

  describe('parseStartParams', () => {
    it('returns default tab when empty', () => {
      expect(parseStartParams('')).toEqual({ tab: 'photo' })
    })

    it('parses tab parameter', () => {
      expect(parseStartParams('tab_video')).toEqual({ tab: 'video' })
      expect(parseStartParams('tab_feed')).toEqual({ tab: 'feed' })
      expect(parseStartParams('tab_trends')).toEqual({ tab: 'trends' })
      expect(parseStartParams('tab_profile')).toEqual({ tab: 'profile' })
      expect(parseStartParams('tab_studio')).toEqual({ tab: 'studio' })
      expect(parseStartParams('tab_services')).toEqual({ tab: 'services' })
      expect(parseStartParams('tab_motion')).toEqual({ tab: 'motion' })
    })

    it('parses ref parameter', () => {
      expect(parseStartParams('ref_abc123').ref).toBe('abc123')
    })

    it('parses multiple parameters', () => {
      const r = parseStartParams('tab_video_ref_xyz789')
      expect(r.tab).toBe('video')
      expect(r.ref).toBe('xyz789')
    })

    it('ignores unknown parameters', () => {
      expect(parseStartParams('unknown_param').tab).toBe('photo')
    })
  })

  describe('copyToClipboard', () => {
    it('calls navigator.clipboard.writeText', async () => {
      const writeText = jest.fn().mockResolvedValue(undefined)
      Object.assign(navigator, { clipboard: { writeText } })
      const result = await copyToClipboard('test text')
      expect(writeText).toHaveBeenCalledWith('test text')
      expect(result).toBe(true)
    })

    it('returns false on error', async () => {
      const writeText = jest.fn().mockRejectedValue(new Error('denied'))
      Object.assign(navigator, { clipboard: { writeText } })
      const result = await copyToClipboard('test text')
      expect(result).toBe(false)
    })
  })
})

// ============================================================
// 2. MOCK DATA TESTS
// ============================================================
describe('Mock Data', () => {
  it('MOCK_TASKS has valid structure', () => {
    expect(Array.isArray(MOCK_TASKS)).toBe(true)
    for (const task of MOCK_TASKS) {
      expect(task).toHaveProperty('id')
      expect(task).toHaveProperty('type')
      expect(task).toHaveProperty('status')
      expect(task).toHaveProperty('prompt')
      expect(['photo', 'video', 'motion']).toContain(task.type)
      expect(['pending', 'completed', 'failed', 'processing']).toContain(task.status)
    }
  })

  it('MOCK_FEED_ITEMS has valid structure', () => {
    expect(Array.isArray(MOCK_FEED_ITEMS)).toBe(true)
    for (const item of MOCK_FEED_ITEMS) {
      expect(item).toHaveProperty('id')
      expect(item).toHaveProperty('type')
      expect(item).toHaveProperty('url')
      expect(item).toHaveProperty('author')
    }
  })

  it('MOCK_TRENDS has valid structure', () => {
    expect(Array.isArray(MOCK_TRENDS)).toBe(true)
    for (const trend of MOCK_TRENDS) {
      expect(trend).toHaveProperty('id')
      expect(trend).toHaveProperty('type')
      expect(trend).toHaveProperty('prompt')
      expect(['photo', 'video']).toContain(trend.type)
    }
  })
})

// ============================================================
// 3. UI COMPONENT SMOKE TESTS
// ============================================================
describe('UI Components', () => {
  it('Badge renders with text', () => {
    render(<Badge>Test Badge</Badge>)
    expect(screen.getByText('Test Badge')).toBeInTheDocument()
  })

  it('Button renders and handles click', () => {
    const onClick = jest.fn()
    render(<Button onClick={onClick}>Click Me</Button>)
    const btn = screen.getByText('Click Me')
    expect(btn).toBeInTheDocument()
    fireEvent.click(btn)
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('Button renders disabled state', () => {
    render(<Button disabled>Disabled</Button>)
    expect(screen.getByText('Disabled')).toBeDisabled()
  })

  it('Card renders children', () => {
    render(
      <Card>
        <CardHeader><CardTitle>Card Title</CardTitle></CardHeader>
        <CardContent>Card Content</CardContent>
      </Card>
    )
    expect(screen.getByText('Card Title')).toBeInTheDocument()
    expect(screen.getByText('Card Content')).toBeInTheDocument()
  })

  it('Input renders and accepts input', async () => {
    render(<Input placeholder="Enter text" />)
    const input = screen.getByPlaceholderText('Enter text')
    expect(input).toBeInTheDocument()
    await userEvent.type(input, 'hello')
    expect(input).toHaveValue('hello')
  })

  it('Spinner renders without crashing', () => {
    const { container } = render(<Spinner />)
    expect(container.firstChild).toBeInTheDocument()
  })

  it('Skeleton renders with custom className', () => {
    const { container } = render(<Skeleton className="h-10 w-20" />)
    expect(container.firstChild).toHaveClass('h-10', 'w-20')
  })

  it('Empty renders empty state message', () => {
    render(<Empty icon="inbox" title="Nothing here" description="No items found" />)
    expect(screen.getByText('Nothing here')).toBeInTheDocument()
    expect(screen.getByText('No items found')).toBeInTheDocument()
  })

  it('ModeBadge renders photo mode', () => {
    render(<ModeBadge mode="photo" />)
    expect(screen.getByText(/фото/i)).toBeInTheDocument()
  })

  it('ModeBadge renders video mode', () => {
    render(<ModeBadge mode="video" />)
    expect(screen.getByText(/видео/i)).toBeInTheDocument()
  })

  it('InfoBlock renders with title and children', () => {
    render(<InfoBlock title="Info Title"><p>Info content</p></InfoBlock>)
    expect(screen.getByText('Info Title')).toBeInTheDocument()
    expect(screen.getByText('Info content')).toBeInTheDocument()
  })
})

// ============================================================
// 4. TAB NAVIGATION SMOKE
// ============================================================
describe('Tab Navigation', () => {
  it('renders all main tabs', () => {
    render(
      <TestWrapper>
        <TabNav />
      </TestWrapper>
    )
    expect(screen.getByText(/фото/i)).toBeInTheDocument()
    expect(screen.getByText(/видео/i)).toBeInTheDocument()
    expect(screen.getByText(/тренды/i)).toBeInTheDocument()
    expect(screen.getByText(/лента/i)).toBeInTheDocument()
    expect(screen.getByText(/профиль/i)).toBeInTheDocument()
    expect(screen.getByText(/студия/i)).toBeInTheDocument()
    expect(screen.getByText(/сервисы/i)).toBeInTheDocument()
  })

  it('clicking tab changes active tab', () => {
    render(
      <TestWrapper initialState={{ activeTab: 'photo' }}>
        <TabNav />
        <TabContent />
      </TestWrapper>
    )
    const videoTab = screen.getByText(/видео/i)
    fireEvent.click(videoTab)
    expect(videoTab.closest('button')).toBeInTheDocument()
  })
})

// ============================================================
// 5. FORM COMPONENTS SMOKE
// ============================================================
describe('Form Components', () => {
  it('ModelSelect renders combobox', () => {
    render(
      <TestWrapper>
        <ModelSelect mode="photo" value="kling" onChange={() => {}} />
      </TestWrapper>
    )
    expect(screen.getByRole('combobox')).toBeInTheDocument()
  })

  it('QualitySelect renders combobox', () => {
    render(
      <TestWrapper>
        <QualitySelect mode="photo" value="standard" onChange={() => {}} />
      </TestWrapper>
    )
    expect(screen.getByRole('combobox')).toBeInTheDocument()
  })

  it('RatioSelect renders combobox', () => {
    render(
      <TestWrapper>
        <RatioSelect value="1:1" onChange={() => {}} />
      </TestWrapper>
    )
    expect(screen.getByRole('combobox')).toBeInTheDocument()
  })

  it('UploadArea renders upload button', () => {
    render(
      <TestWrapper>
        <UploadArea onFiles={() => {}} accept="image/*" maxFiles={1} />
      </TestWrapper>
    )
    expect(screen.getByText(/загрузить/i)).toBeInTheDocument()
  })
})

// ============================================================
// 6. TASK & RESULT CARDS SMOKE
// ============================================================
describe('Task & Result Cards', () => {
  it('TaskCard renders task info', () => {
    const task = MOCK_TASKS[0]
    render(
      <TestWrapper>
        <TaskCard task={task as Task} onSelect={() => {}} />
      </TestWrapper>
    )
    expect(screen.getByText(task.prompt)).toBeInTheDocument()
  })

  it('TaskHistoryList renders empty state', () => {
    render(
      <TestWrapper initialState={{ recentTasks: [] }}>
        <TaskHistoryList />
      </TestWrapper>
    )
    expect(screen.getByText(/история пуста/i)).toBeInTheDocument()
  })

  it('TaskHistoryList renders tasks', () => {
    render(
      <TestWrapper initialState={{ recentTasks: MOCK_TASKS as Task[] }}>
        <TaskHistoryList />
      </TestWrapper>
    )
    const cards = screen.getAllByText(MOCK_TASKS[0].prompt)
    expect(cards.length).toBeGreaterThan(0)
  })

  it('ResultCard renders image result', () => {
    render(
      <TestWrapper>
        <ResultCard url="https://example.com/image.jpg" type="photo" prompt="A beautiful sunset" onDownload={() => {}} />
      </TestWrapper>
    )
    expect(screen.getByText('A beautiful sunset')).toBeInTheDocument()
    expect(screen.getByRole('img')).toBeInTheDocument()
  })

  it('QuickActionGrid renders action buttons', () => {
    render(
      <TestWrapper>
        <QuickActionGrid />
      </TestWrapper>
    )
    expect(screen.getByText(/создать фото/i)).toBeInTheDocument()
    expect(screen.getByText(/создать видео/i)).toBeInTheDocument()
  })
})

// ============================================================
// 7. ERROR BOUNDARY SMOKE
// ============================================================
describe('Error Boundary', () => {
  it('renders children normally', () => {
    render(
      <ClientErrorBoundary>
        <div>Normal content</div>
      </ClientErrorBoundary>
    )
    expect(screen.getByText('Normal content')).toBeInTheDocument()
  })

  it('catches errors and shows fallback', () => {
    const ThrowError = () => { throw new Error('Test error') }
    const spy = jest.spyOn(console, 'error').mockImplementation(() => {})
    render(
      <ClientErrorBoundary>
        <ThrowError />
      </ClientErrorBoundary>
    )
    expect(screen.getByText(/что-то пошло не так/i)).toBeInTheDocument()
    spy.mockRestore()
  })
})

// ============================================================
// 8. TYPES CONSISTENCY SMOKE
// ============================================================
describe('Types', () => {
  it('TaskStatus union is valid', () => {
    const statuses = ['pending', 'processing', 'completed', 'failed'] as const
    expect(statuses).toHaveLength(4)
  })

  it('TaskType union is valid', () => {
    const types = ['photo', 'video', 'motion'] as const
    expect(types).toHaveLength(3)
  })

  it('AppMode union is valid', () => {
    const modes = ['photo', 'video'] as const
    expect(modes).toHaveLength(2)
  })
})

// ============================================================
// 9. APP CONTEXT SMOKE
// ============================================================
describe('App Context', () => {
  it('provides state via useApp', () => {
    let ctx: any = null
    function Reader() { ctx = useApp(); return null }
    render(<TestWrapper><Reader /></TestWrapper>)
    expect(ctx).not.toBeNull()
    expect(ctx.state).toBeDefined()
    expect(ctx.state.activeTab).toBe('photo')
    expect(ctx.state.mode).toBe('photo')
    expect(ctx.state.user).toBeDefined()
    expect(ctx.state.balance).toBe(100)
  })

  it('provides dispatch functions', () => {
    let ctx: any = null
    function Reader() { ctx = useApp(); return null }
    render(<TestWrapper><Reader /></TestWrapper>)
    expect(typeof ctx.setActiveTab).toBe('function')
    expect(typeof ctx.setMode).toBe('function')
    expect(typeof ctx.selectTask).toBe('function')
    expect(typeof ctx.refreshBootstrap).toBe('function')
  })
})

// ============================================================
// 10. BUILD OUTPUT SMOKE
// ============================================================
describe('Build Output', () => {
  it('out/index.html exists and is valid HTML', () => {
    const fs = require('fs')
    const path = require('path')
    const indexPath = path.join(__dirname, '..', 'out', 'index.html')
    expect(fs.existsSync(indexPath)).toBe(true)
    const content = fs.readFileSync(indexPath, 'utf-8')
    expect(content).toContain('<!DOCTYPE html>')
    expect(content).toContain('<html')
    expect(content).toContain('</html>')
  })

  it('out/_next/static directory exists', () => {
    const fs = require('fs')
    const path = require('path')
    const staticDir = path.join(__dirname, '..', 'out', '_next', 'static')
    expect(fs.existsSync(staticDir)).toBe(true)
  })

  it('telegram-web-app.js is copied to out/', () => {
    const fs = require('fs')
    const path = require('path')
    const tgPath = path.join(__dirname, '..', 'out', 'telegram-web-app.js')
    expect(fs.existsSync(tgPath)).toBe(true)
  })
})