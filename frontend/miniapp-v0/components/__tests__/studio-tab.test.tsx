import { fireEvent, render, screen } from '@testing-library/react'
import '@testing-library/jest-dom'

import { StudioTab } from '@/components/tabs/studio-tab'
import { useApp } from '@/lib/app-context'

jest.mock('@/lib/app-context', () => ({
  useApp: jest.fn(),
}))

jest.mock('next/image', () => ({
  __esModule: true,
  default: ({ fill: _fill, ...props }: React.ImgHTMLAttributes<HTMLImageElement> & { fill?: boolean }) => (
    <img {...props} alt={props.alt || ''} />
  ),
}))

jest.mock('@/components/quick-action-grid', () => ({
  QuickActionGrid: () => <div data-testid="quick-actions" />,
}))

const mockedUseApp = useApp as jest.MockedFunction<typeof useApp>

describe('StudioTab', () => {
  const setActiveTab = jest.fn()

  beforeEach(() => {
    jest.clearAllMocks()
    mockedUseApp.mockReturnValue({
      setActiveTab,
      openBalance: jest.fn(),
      openWorkspace: jest.fn(),
    } as unknown as ReturnType<typeof useApp>)
  })

  it('does not render recent work history on the home screen', () => {
    render(<StudioTab />)

    expect(screen.queryByText('Ваши работы')).not.toBeInTheDocument()
    expect(screen.getByTestId('quick-actions')).toBeInTheDocument()
  })

  it('opens trends and feed from the inspiration section', () => {
    render(<StudioTab />)

    fireEvent.click(screen.getByRole('button', { name: 'Открыть подборку трендов' }))
    expect(setActiveTab).toHaveBeenCalledWith(5)

    fireEvent.click(screen.getByRole('button', { name: 'Открыть работы сообщества' }))
    expect(setActiveTab).toHaveBeenCalledWith(4)
  })
})
