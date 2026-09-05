import '@testing-library/jest-dom'

import { fireEvent, render, screen } from '@testing-library/react'

import { Button } from '@/components/ui/button'
import { copyTextToClipboard } from '@/lib/clipboard'
import { PRODUCT } from '@/lib/product'
import { parseMiniAppStartParam } from '@/lib/start-params'
import { cn } from '@/lib/utils'


describe('HappyFox Mini App smoke contracts', () => {
  it('is pinned to the HappyFox product identity', () => {
    expect(PRODUCT.id).toBe('happyfox')
    expect(PRODUCT.brandName).toBe('HappyFox')
    expect(PRODUCT.telegramAppUrl).toMatch(/^https:\/\/t\.me\/[A-Za-z0-9_]+$/)
  })

  it('keeps Tailwind class merging deterministic', () => {
    expect(cn('foo', 'bar')).toBe('foo bar')
    expect(cn('px-4', 'px-2')).toBe('px-2')
  })

  it('parses current Mini App deep-link contracts', () => {
    expect(parseMiniAppStartParam('')).toBeNull()
    expect(parseMiniAppStartParam('unknown_param')).toBeNull()
    expect(parseMiniAppStartParam('ref_abc123')).toEqual({
      kind: 'ref',
      referralCode: 'ABC123',
    })
    expect(parseMiniAppStartParam('feed_42_ref_partner7')).toEqual({
      kind: 'feed',
      genId: 42,
      referralCodeForAttribution: 'PARTNER7',
    })
    expect(parseMiniAppStartParam('task_task-123')).toEqual({
      kind: 'task',
      taskId: 'task-123',
    })
  })

  it('copies trimmed text through the browser clipboard API', async () => {
    const writeText = jest.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })

    await copyTextToClipboard('  https://happyfox.example/share  ')

    expect(writeText).toHaveBeenCalledWith('https://happyfox.example/share')
  })

  it('rejects an empty clipboard payload before touching the DOM fallback', async () => {
    await expect(copyTextToClipboard('   ')).rejects.toThrow('Ссылка пока недоступна')
  })

  it('renders and dispatches a current UI button action', () => {
    const onClick = jest.fn()
    render(<Button onClick={onClick}>Создать</Button>)

    fireEvent.click(screen.getByRole('button', { name: 'Создать' }))

    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('keeps disabled buttons inert', () => {
    const onClick = jest.fn()
    render(
      <Button disabled onClick={onClick}>
        Недоступно
      </Button>,
    )

    const button = screen.getByRole('button', { name: 'Недоступно' })
    expect(button).toBeDisabled()
    fireEvent.click(button)
    expect(onClick).not.toHaveBeenCalled()
  })
})
