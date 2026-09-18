import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom'

import { TelegramOpenGate } from '@/components/telegram-open-gate'
import { useApp } from '@/lib/app-context'

jest.mock('@/lib/app-context', () => ({
  useApp: jest.fn(),
}))

const mockedUseApp = useApp as jest.MockedFunction<typeof useApp>

type MutableWindow = Window & {
  TelegramWebviewProxy?: { postEvent?: () => void }
  WebApp?: { initData?: string; openLink?: jest.Mock; openMaxLink?: jest.Mock }
  Telegram?: {
    WebApp?: {
      initData?: string
      initDataUnsafe?: { start_param?: string }
      openTelegramLink?: jest.Mock
      platform?: string
    }
  }
}

const widgetSelector = 'script[src*="telegram-widget.js"]'

function nativeWindow(): MutableWindow {
  return window as MutableWindow
}

function mockContext(refreshTasks: jest.Mock, error: string | null = null) {
  mockedUseApp.mockReturnValue({
    state: { mode: 'locked', isLoading: false, error },
    refreshTasks,
  } as unknown as ReturnType<typeof useApp>)
}

function resetRuntime() {
  const runtimeWindow = nativeWindow()

  window.__BANANO_MINIAPP_PLATFORM__ = undefined
  delete runtimeWindow.TelegramWebviewProxy

  const webApp = runtimeWindow.Telegram?.WebApp
  if (webApp) {
    webApp.initData = ''
    webApp.initDataUnsafe = { start_param: '' }
    webApp.platform = 'unknown'
  }
}

describe('TelegramOpenGate', () => {
  const originalFetch = global.fetch

  beforeEach(() => {
    jest.clearAllMocks()
    resetRuntime()
    document.querySelectorAll(widgetSelector).forEach((node) => node.remove())
    global.fetch = jest.fn(async () => ({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => ({ ok: true, bot_username: 'AlePolbot' }),
    } as unknown as Response)) as unknown as typeof fetch
  })

  afterEach(() => {
    global.fetch = originalFetch
    jest.useRealTimers()
    resetRuntime()
  })

  it('keeps the Telegram login widget for ordinary browsers', async () => {
    mockContext(jest.fn())

    render(<TelegramOpenGate />)

    await waitFor(() => expect(document.querySelector(widgetSelector)).not.toBeNull())
    expect(screen.getByText(/Войдите через Telegram/)).toBeInTheDocument()
  })

  it('never asks a native Telegram client to log in through the browser', async () => {
    const refreshTasks = jest.fn()
    mockContext(refreshTasks)
    nativeWindow().TelegramWebviewProxy = { postEvent: () => {} }

    render(<TelegramOpenGate />)

    await waitFor(() => expect(screen.getByRole('button', { name: /Попробовать снова/ })).toBeInTheDocument())
    expect(document.querySelector(widgetSelector)).toBeNull()
    expect(screen.queryByText(/Войдите через Telegram/)).toBeNull()
    expect(screen.getByText(/откройте HappyFox заново из Telegram/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Попробовать снова/ }))

    expect(refreshTasks).toHaveBeenCalledTimes(1)
  })

  it('reopens Telegram native launches through the Telegram bridge', async () => {
    const refreshTasks = jest.fn()
    const openTelegramLink = jest.fn()
    mockContext(refreshTasks)
    nativeWindow().TelegramWebviewProxy = { postEvent: () => {} }
    const webApp = nativeWindow().Telegram?.WebApp
    if (webApp) webApp.openTelegramLink = openTelegramLink

    render(<TelegramOpenGate />)

    const reopen = await screen.findByRole('button', { name: /Открыть HappyFox в Telegram/ })
    fireEvent.click(reopen)

    expect(openTelegramLink).toHaveBeenCalledWith('https://t.me/AlePolbot?startapp')
  })

  it('reopens MAX native launches through the MAX bridge', async () => {
    const refreshTasks = jest.fn()
    const openMaxLink = jest.fn()
    mockContext(refreshTasks)
    window.__BANANO_MINIAPP_PLATFORM__ = 'max'
    nativeWindow().WebApp = { initData: '', openMaxLink }

    render(<TelegramOpenGate />)

    const reopen = await screen.findByRole('button', { name: /Открыть HappyFox в MAX/ })
    fireEvent.click(reopen)

    expect(openMaxLink).toHaveBeenCalledWith('http://localhost/mini-app/')
  })

  it('stops automatic native retries after a launch error is already visible', async () => {
    jest.useFakeTimers()
    const refreshTasks = jest.fn()
    mockContext(refreshTasks, 'Не удалось получить данные входа')
    nativeWindow().TelegramWebviewProxy = { postEvent: () => {} }

    render(<TelegramOpenGate />)
    await act(async () => {})

    await act(async () => {
      jest.advanceTimersByTime(7000)
    })

    expect(refreshTasks).not.toHaveBeenCalled()
  })

  it('keeps automatic native retries for transient bootstrap errors', async () => {
    jest.useFakeTimers()
    const refreshTasks = jest.fn()
    mockContext(refreshTasks, 'Не удалось обновить данные прямо сейчас')
    nativeWindow().TelegramWebviewProxy = { postEvent: () => {} }

    render(<TelegramOpenGate />)
    await act(async () => {})

    await act(async () => {
      jest.advanceTimersByTime(2000)
    })

    expect(refreshTasks).toHaveBeenCalledTimes(1)
  })

  it('retries a native launch automatically', async () => {
    jest.useFakeTimers()
    const refreshTasks = jest.fn()
    mockContext(refreshTasks)
    nativeWindow().TelegramWebviewProxy = { postEvent: () => {} }

    render(<TelegramOpenGate />)
    await act(async () => {})
    expect(refreshTasks).not.toHaveBeenCalled()

    await act(async () => {
      jest.advanceTimersByTime(2000)
    })

    expect(refreshTasks).toHaveBeenCalledTimes(1)
  })
})
