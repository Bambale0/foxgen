'use client'

import dynamic from 'next/dynamic'
import { type ReactNode, useEffect } from 'react'
import { ThemeProvider } from '@/components/theme-provider'
import { AppProvider, useApp } from '@/lib/app-context'
import { HeroHeader } from './hero-header'
import { TabNav } from './tab-nav'
import { Toaster } from '@/components/ui/sonner'
import { ClientErrorBoundary } from './client-error-boundary'
import { MiniAppLoader } from './mini-app-loader'
import { TelegramOpenGate } from './telegram-open-gate'
import { PartnerApprovalSheet } from './partner-approval-sheet'

const TaskDetailPanel = dynamic(() =>
  import('./task-detail-panel').then((module) => module.TaskDetailPanel),
)
const BalanceSheet = dynamic(() =>
  import('./balance-sheet').then((module) => module.BalanceSheet),
)
const WorkspaceSheet = dynamic(() =>
  import('./workspace-sheet').then((module) => module.WorkspaceSheet),
)

interface MiniAppShellProps {
  children: ReactNode
}

function MiniAppBody({ children }: MiniAppShellProps) {
  const { state, activeWorkspace } = useApp()
  const isBootstrapping = state.isLoading
  const isLocked = state.mode === 'locked'

  return (
    <div className="relative flex min-h-screen flex-col overflow-x-hidden bg-background">
      <div className="foxgen-shell-bg fixed inset-0 pointer-events-none" />

      {isBootstrapping ? (
        <MiniAppLoader />
      ) : isLocked ? (
        <TelegramOpenGate />
      ) : (
        <>
          <div className="relative flex min-h-screen min-w-0 flex-col overflow-x-hidden safe-top">
            <HeroHeader />
            <main className="min-w-0 flex-1 overflow-y-auto overflow-x-hidden pb-[calc(6rem+env(safe-area-inset-bottom))]">
              <div className="mx-auto w-full max-w-[1180px]">
                {children}
              </div>
            </main>
            <TabNav />
          </div>

          <TaskDetailPanel />
          <BalanceSheet />
          {activeWorkspace === 'partners' ? <PartnerApprovalSheet /> : <WorkspaceSheet />}
        </>
      )}
      <Toaster richColors position="top-center" />
    </div>
  )
}

export function MiniAppShell({ children }: MiniAppShellProps) {
  useEffect(() => {
    if (typeof window === 'undefined') return
    const webApp = window.Telegram?.WebApp
    webApp?.ready?.()
    webApp?.expand?.()
    webApp?.setHeaderColor?.('#050505')
    webApp?.setBackgroundColor?.('#050505')
    webApp?.setBottomBarColor?.('#080808')
  }, [])

  return (
    <ThemeProvider attribute="class" forcedTheme="dark" enableSystem={false}>
      <ClientErrorBoundary>
        <AppProvider>
          <MiniAppBody>{children}</MiniAppBody>
        </AppProvider>
      </ClientErrorBoundary>
    </ThemeProvider>
  )
}
