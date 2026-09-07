import React from 'react'
import { render, screen } from '@testing-library/react'
import '@testing-library/jest-dom'

jest.mock('next/image', () => ({
  __esModule: true,
  default: (props: any) => React.createElement('img', { ...props, fill: undefined, priority: undefined }),
}))

import LandingPage, { metadata } from '@/app/landing/page'
import robots from '@/app/robots'
import sitemap from '@/app/sitemap'

describe('HappyFox landing', () => {
  it('renders a concrete conversion-focused value proposition and working Telegram CTAs', () => {
    const { container } = render(<LandingPage />)

    expect(
      screen.getByRole('heading', {
        name: /Создавайте фото и видео нейросетями без десятка сервисов/i,
      }),
    ).toBeInTheDocument()

    const telegramLinks = screen.getAllByRole('link').filter((link) =>
      link.getAttribute('href') === 'https://t.me/AlePolbot?start=ref_M9SHFF25',
    )
    expect(telegramLinks.length).toBeGreaterThanOrEqual(4)
    for (const link of telegramLinks) {
      expect(link).toHaveAttribute('target', '_blank')
      expect(link).toHaveAttribute('rel', 'noopener noreferrer')
      expect(link.getAttribute('href')).not.toContain('startapp')
    }

    expect(
      screen.getByRole('link', { name: 'Открыть HappyFox в Telegram из демо' }),
    ).toHaveAttribute('href', 'https://t.me/AlePolbot?start=ref_M9SHFF25')

    expect(
      screen.getAllByRole('link').some((link) =>
        link.getAttribute('href') === 'https://t.me/PolyakovaAll',
      ),
    ).toBe(true)
    expect(
      screen.getAllByRole('link').some((link) =>
        link.getAttribute('href') === 'https://www.instagram.com/polyakovaall/',
      ),
    ).toBe(true)

    expect(screen.queryByText('https://t.me/AlePolbot?start=ref_M9SHFF25')).not.toBeInTheDocument()
    expect(container.querySelectorAll('[data-brand-icon="telegram"]').length).toBeGreaterThanOrEqual(4)
    expect(container.querySelectorAll('[data-brand-icon="instagram"]').length).toBeGreaterThanOrEqual(2)

    expect(screen.getByRole('link', { name: /Смотреть работы/i })).toHaveAttribute(
      'href',
      'https://www.instagram.com/polyakovaall/',
    )
    expect(screen.getAllByText('База промптов').length).toBeGreaterThanOrEqual(1)

    expect(
      container.querySelector('img[src="/mini-app/happyfox-brand.webp"]'),
    ).toBeInTheDocument()
    expect(
      container.querySelector('img[src="/mini-app/happyfox-icon.webp"]'),
    ).toBeInTheDocument()

    expect(screen.getByRole('heading', { name: 'Фото' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Видео' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Музыка' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'AI-инструменты' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Изменить волосы, одежду или фон' })).toBeInTheDocument()
  })

  it('keeps the public surface on the HappyFox brand', () => {
    render(<LandingPage />)

    expect(screen.queryByText(/FoxGen/i)).not.toBeInTheDocument()
    expect(screen.getAllByText('HappyFox').length).toBeGreaterThan(0)
  })

  it('publishes canonical search and social metadata for the landing domain', () => {
    expect(metadata.title).toBe('HappyFox — нейросеть для фото, видео и музыки в Telegram')
    expect(metadata.description).toMatch(/редактируйте фото/i)
    expect(metadata.metadataBase?.toString()).toBe('https://happy-fox.online/')
    expect(metadata.alternates).toMatchObject({ canonical: '/' })
    expect(metadata.robots).toMatchObject({ index: true, follow: true })
    expect(metadata.openGraph).toMatchObject({
      type: 'website',
      url: '/',
      siteName: 'HappyFox',
    })
  })

  it('publishes crawl directives and a canonical sitemap entry', () => {
    expect(robots()).toEqual({
      rules: [
        {
          userAgent: '*',
          allow: '/',
          disallow: ['/mini-app/api/', '/mini-app/landing/'],
        },
      ],
      sitemap: 'https://happy-fox.online/sitemap.xml',
      host: 'https://happy-fox.online',
    })

    expect(sitemap()).toEqual([
      {
        url: 'https://happy-fox.online/',
        changeFrequency: 'weekly',
        priority: 1,
      },
    ])
  })
})
