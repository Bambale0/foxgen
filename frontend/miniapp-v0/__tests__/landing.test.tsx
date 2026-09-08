import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom'

jest.mock('next/image', () => ({
  __esModule: true,
  default: (props: any) => React.createElement('img', { ...props, fill: undefined, priority: undefined }),
}))

import LandingPage, { metadata } from '@/app/landing/page'
import robots from '@/app/robots'
import sitemap from '@/app/sitemap'

describe('HappyFox landing', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/landing/')
    window.localStorage.clear()
  })

  it('renders a concrete conversion-focused value proposition and clear Telegram/web CTAs', () => {
    const { container } = render(<LandingPage />)

    expect(
      screen.getByRole('heading', {
        name: /Создавайте фото и видео нейросетями без десятка сервисов/i,
      }),
    ).toBeInTheDocument()

    const telegramLinks = screen.getAllByRole('link').filter((link) =>
      link.getAttribute('href') === 'https://t.me/AlePolbot?start=ref_AZLRXW6L',
    )
    expect(telegramLinks.length).toBeGreaterThanOrEqual(5)
    for (const link of telegramLinks) {
      expect(link).toHaveAttribute('target', '_blank')
      expect(link).toHaveAttribute('rel', 'noopener noreferrer')
      expect(link.getAttribute('href')).not.toContain('startapp')
    }

    expect(screen.getByRole('link', { name: 'Попробовать ТГ' })).toHaveAttribute(
      'href',
      'https://t.me/AlePolbot?start=ref_AZLRXW6L',
    )
    expect(screen.getByRole('link', { name: 'Попробовать на сайте' })).toHaveAttribute(
      'href',
      'https://app.happy-fox.online/mini-app/?startapp=ref_AZLRXW6L',
    )
    expect(
      screen.getByRole('link', { name: 'Попробовать HappyFox на сайте из демо' }),
    ).toHaveAttribute(
      'href',
      'https://app.happy-fox.online/mini-app/?startapp=ref_AZLRXW6L',
    )

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

    expect(screen.queryByText('https://t.me/AlePolbot?start=ref_AZLRXW6L')).not.toBeInTheDocument()
    expect(container.querySelectorAll('[data-brand-icon="telegram"]').length).toBeGreaterThanOrEqual(5)
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
    ).not.toBeInTheDocument()

    expect(screen.getByRole('heading', { name: 'Фото' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Видео' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Музыка' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'AI-инструменты' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Изменить волосы, одежду или фон' })).toBeInTheDocument()

    expect(container.querySelector('#partners')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Зарабатывайте вместе с HappyFox' })).toBeInTheDocument()
    expect(screen.getByText('Персональная ссылка')).toBeInTheDocument()
    expect(screen.getByText('Два уровня вознаграждений')).toBeInTheDocument()
    expect(screen.getByText('Статистика и выплаты')).toBeInTheDocument()
    expect(
      screen.getAllByRole('link', { name: 'Партнёрам' }).some((link) =>
        link.getAttribute('href') === '#partners',
      ),
    ).toBe(true)
    expect(screen.getByRole('link', { name: 'Ссылка на программу' })).toHaveAttribute(
      'href',
      'https://happy-fox.online/#partners',
    )
    expect(screen.getByText('happy-fox.online/#partners')).toBeInTheDocument()
  })

  it('propagates an incoming referral to both the app-domain website CTA and Telegram CTAs', async () => {
    window.history.replaceState({}, '', '/landing/?ref=partner42')
    const { container } = render(<LandingPage />)

    await waitFor(() => {
      const botLinks = Array.from(container.querySelectorAll('[data-referral-link="bot"]'))
      const webLinks = Array.from(container.querySelectorAll('[data-referral-link="web"]'))

      expect(botLinks.length).toBeGreaterThanOrEqual(5)
      expect(webLinks.length).toBeGreaterThanOrEqual(2)
      expect(botLinks.every((link) => link.getAttribute('href') === 'https://t.me/AlePolbot?start=ref_PARTNER42')).toBe(true)
      expect(webLinks.every((link) => link.getAttribute('href') === 'https://app.happy-fox.online/mini-app/?startapp=ref_PARTNER42')).toBe(true)
    })

    expect(window.localStorage.getItem('happyfox_ref_start_param')).toBe('ref_PARTNER42')
    expect(screen.queryByText('https://t.me/AlePolbot?start=ref_PARTNER42')).not.toBeInTheDocument()
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
