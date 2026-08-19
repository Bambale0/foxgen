import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { appMock } = vi.hoisted(() => ({
  appMock: {
    generations: [{
      id: 'gen-live', model_slug: 'seedance-2', media_kind: 'video', status: 'processing',
      prompt: 'fox running', created_at: '2026-08-20T00:00:00Z', media: [],
    }],
    focusedGeneration: null as null | Record<string, unknown>,
    refreshGenerations: vi.fn(async () => undefined),
    openGeneration: vi.fn(async () => undefined),
    clearGenerationFocus: vi.fn(),
    cancelGeneration: vi.fn(async () => undefined),
    publishGeneration: vi.fn(async () => undefined),
  },
}))

vi.mock('@/lib/app-context', () => ({ useApp: () => appMock }))

import { WorksTab } from '@/components/tabs/works-tab'

describe('Works live lifecycle', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    appMock.focusedGeneration = null
    Object.defineProperty(document, 'hidden', { configurable: true, value: false })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('polls active generations, pauses while hidden and refreshes on foreground', async () => {
    const view = render(<WorksTab />)
    await act(async () => undefined)
    expect(appMock.refreshGenerations).toHaveBeenCalledTimes(1)
    expect(screen.getByTestId('works-auto-poll')).toBeInTheDocument()

    await act(async () => { vi.advanceTimersByTime(3_000) })
    expect(appMock.refreshGenerations).toHaveBeenCalledTimes(2)

    Object.defineProperty(document, 'hidden', { configurable: true, value: true })
    await act(async () => { vi.advanceTimersByTime(6_000) })
    expect(appMock.refreshGenerations).toHaveBeenCalledTimes(2)

    Object.defineProperty(document, 'hidden', { configurable: true, value: false })
    await act(async () => { document.dispatchEvent(new Event('visibilitychange')) })
    expect(appMock.refreshGenerations).toHaveBeenCalledTimes(3)

    view.unmount()
    await act(async () => { vi.advanceTimersByTime(6_000) })
    expect(appMock.refreshGenerations).toHaveBeenCalledTimes(3)
  })

  it('opens backend generation detail from a work card', async () => {
    render(<WorksTab />)
    fireEvent.click(screen.getByRole('button', { name: 'Подробнее' }))
    expect(appMock.openGeneration).toHaveBeenCalledWith('gen-live')
  })
})
