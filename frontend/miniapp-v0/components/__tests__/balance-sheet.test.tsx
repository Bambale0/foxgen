import { fireEvent, render, screen } from '@testing-library/react'
import '@testing-library/jest-dom'

import { BalanceSheet } from '@/components/balance-sheet'
import { createPayment } from '@/lib/payment-api'
import { useApp } from '@/lib/app-context'

jest.mock('@/lib/app-context', () => ({
  useApp: jest.fn(),
}))

jest.mock('@/lib/payment-api', () => ({
  createPayment: jest.fn(),
}))

const mockedUseApp = useApp as jest.MockedFunction<typeof useApp>
const mockedCreatePayment = createPayment as jest.MockedFunction<typeof createPayment>

describe('BalanceSheet', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    mockedUseApp.mockReturnValue({
      state: {
        paymentPackages: [
          {
            id: 'mini',
            name: 'Mini',
            credits: 15,
            price_rub: 150,
            price_stars: 120,
            lava_offer_id: 'lava-offer-mini',
            lava_currency: 'EUR',
            description: 'Для пробы',
          },
        ],
        user: {
          credits: 5,
        },
        recentTasks: [],
        mode: 'live',
      },
      isBalanceOpen: true,
      closeBalance: jest.fn(),
      refreshTasks: jest.fn(),
    } as ReturnType<typeof useApp>)
  })

  it('renders EUR and YooKassa actions for packages with an EUR offer', () => {
    render(<BalanceSheet />)

    expect(screen.getByRole('button', { name: 'ЮKassa' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'EUR' })).toBeInTheDocument()
  })

  it('creates an EUR payment when the EUR button is pressed', async () => {
    mockedCreatePayment.mockResolvedValue({
      ok: true,
      provider: 'lava',
      order_id: 'order-1',
      payment_id: 'payment-1',
      payment_url: 'https://pay.example/lava',
      credits: 15,
    })
    const openSpy = jest.spyOn(window, 'open').mockReturnValue({} as Window)

    render(<BalanceSheet />)
    fireEvent.click(screen.getByRole('button', { name: 'EUR' }))

    expect(await screen.findByRole('button', { name: 'EUR' })).toBeInTheDocument()
    expect(mockedCreatePayment).toHaveBeenCalledWith({ packageId: 'mini', provider: 'lava' })

    openSpy.mockRestore()
  })
})
