import React from 'react'
import { render, screen } from '@testing-library/react'
import '@testing-library/jest-dom'

jest.mock('next/image', () => ({
  __esModule: true,
  default: (props: any) => React.createElement('img', { ...props, fill: undefined, priority: undefined }),
}))

import LandingPage from '@/app/landing/page'

describe('HappyFox landing', () => {
  it('renders the public HappyFox value proposition and working Telegram CTAs', () => {
    const { container } = render(<LandingPage />)

    expect(
      screen.getByRole('heading', { name: /Фото, видео и музыка — в одном HappyFox/i }),
    ).toBeInTheDocument()

    const telegramLinks = screen.getAllByRole('link').filter((link) =>
      link.getAttribute('href') === 'https://t.me/AlePolbot',
    )
    expect(telegramLinks.length).toBeGreaterThanOrEqual(4)
    for (const link of telegramLinks) {
      expect(link).toHaveAttribute('target', '_blank')
      expect(link).toHaveAttribute('rel', 'noreferrer')
      expect(link.getAttribute('href')).not.toContain('startapp')
    }

    expect(
      screen.getByRole('link', { name: 'Открыть HappyFox в Telegram из демо' }),
    ).toHaveAttribute('href', 'https://t.me/AlePolbot')

    expect(
      container.querySelector('img[src="/mini-app/happyfox-brand.webp"]'),
    ).toBeInTheDocument()
    expect(
      container.querySelector('img[src="/mini-app/happyfox-icon.webp"]'),
    ).toBeInTheDocument()

    expect(screen.getByRole('heading', { name: 'Фото' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Видео' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Музыка' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'AI-сервисы' })).toBeInTheDocument()
  })

  it('keeps the public surface on the HappyFox brand', () => {
    render(<LandingPage />)

    expect(screen.queryByText(/FoxGen/i)).not.toBeInTheDocument()
    expect(screen.getAllByText('HappyFox').length).toBeGreaterThan(0)
  })
})
