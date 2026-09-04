import React from 'react'
import { render, screen } from '@testing-library/react'
import '@testing-library/jest-dom'

jest.mock('next/image', () => ({
  __esModule: true,
  default: (props: any) => React.createElement('img', { ...props, fill: undefined, priority: undefined }),
}))

import LandingPage from '@/app/landing/page'

describe('HappyFox landing', () => {
  it('renders the public HappyFox value proposition and primary CTA', () => {
    render(<LandingPage />)

    expect(
      screen.getByRole('heading', { name: /Фото, видео и музыка — в одном HappyFox/i }),
    ).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: /Открыть HappyFox/i }).length).toBeGreaterThan(0)
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
