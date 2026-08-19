import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { PartnerApprovalSheet } from '@/components/partner-approval-sheet'
import { executeMiniAppAction, fetchPartnerOverview } from '@/lib/api'
import { useApp } from '@/lib/app-context'

jest.mock('lucide-react', () => {
  const Icon = (props: React.SVGProps<SVGSVGElement>) => <svg {...props} />
  return {
    BriefcaseBusiness: Icon,
    CheckCircle2: Icon,
    Copy: Icon,
    Loader2: Icon,
    RefreshCw: Icon,
    Send: Icon,
    ShieldCheck: Icon,
    XCircle: Icon,
  }
})

jest.mock('@/lib/api', () => ({
  executeMiniAppAction: jest.fn(),
  fetchPartnerOverview: jest.fn(),
}))

jest.mock('@/lib/app-context', () => ({
  useApp: jest.fn(),
}))

jest.mock('@/components/ui/sheet', () => ({
  Sheet: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SheetContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SheetHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SheetTitle: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
  SheetDescription: ({ children }: { children: React.ReactNode }) => <p>{children}</p>,
}))

jest.mock('@/components/ui/button', () => ({
  Button: ({ children, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) => (
    <button {...props}>{children}</button>
  ),
}))

const mockedUseApp = useApp as jest.MockedFunction<typeof useApp>
const mockedFetchPartnerOverview = fetchPartnerOverview as jest.MockedFunction<typeof fetchPartnerOverview>
const mockedExecuteMiniAppAction = executeMiniAppAction as jest.MockedFunction<typeof executeMiniAppAction>

describe('PartnerApprovalSheet', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    mockedUseApp.mockReturnValue({
      activeWorkspace: 'partners',
      closeWorkspace: jest.fn(),
    } as ReturnType<typeof useApp>)
  })

  it('submits an application and moves from available to pending without exposing a referral link', async () => {
    mockedFetchPartnerOverview
      .mockResolvedValueOnce({
        is_partner: false,
        referrals_count: 0,
        balance_rub: 0,
        prompt_repeat_balance_rub: 0,
        prompt_repeat_total_rub: 0,
        channel_url: '',
        referral_link: '',
        status: 'available',
      })
      .mockResolvedValueOnce({
        is_partner: false,
        referrals_count: 0,
        balance_rub: 0,
        prompt_repeat_balance_rub: 0,
        prompt_repeat_total_rub: 0,
        channel_url: '',
        referral_link: '',
        status: 'pending',
      })
    mockedExecuteMiniAppAction.mockResolvedValue(undefined)

    render(<PartnerApprovalSheet />)

    const activateButton = await screen.findByRole('button', { name: /активировать ссылку/i })
    expect(screen.queryByText(/скопировать ссылку/i)).toBeNull()

    fireEvent.click(activateButton)

    await waitFor(() => {
      expect(mockedExecuteMiniAppAction).toHaveBeenCalledWith('partner_apply')
      expect(mockedFetchPartnerOverview).toHaveBeenCalledTimes(2)
    })

    expect(await screen.findByText('Заявка на рассмотрении')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /скопировать ссылку/i })).toBeNull()
  })

  it('shows the full cabinet and referral link only for an approved partner', async () => {
    mockedFetchPartnerOverview.mockResolvedValue({
      is_partner: true,
      referrals_count: 12,
      balance_rub: 345.5,
      prompt_repeat_balance_rub: 0,
      prompt_repeat_total_rub: 0,
      channel_url: '',
      referral_link: 'https://t.me/example_bot?start=ref_TESTCODE',
      status: 'partner',
    })

    render(<PartnerApprovalSheet />)

    expect(await screen.findByText('Партнёрский кабинет активирован')).toBeTruthy()
    expect(screen.getByText('https://t.me/example_bot?start=ref_TESTCODE')).toBeTruthy()
    expect(screen.getByRole('button', { name: /скопировать ссылку/i })).toBeTruthy()
    expect(screen.queryByRole('button', { name: /активировать ссылку/i })).toBeNull()
  })
})
