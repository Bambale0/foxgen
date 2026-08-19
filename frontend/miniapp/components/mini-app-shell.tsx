'use client'

import { useEffect, type ReactNode } from 'react'
import { AppProvider, useApp } from '@/lib/app-context'
import { TabNav } from './tab-nav'
import { WorkspaceSheet } from './workspace-sheet'

const BRAND_LOGO_SRC = '/mini-app/happyfox-logo.webp'

function TopBar() {
  const { bootstrap, openWorkspace } = useApp()
  const user = bootstrap?.user
  const balance = bootstrap?.balance?.available_units ?? 0
  return (
    <header className="topbar">
      <div className="brand">
        <div className="brand-mark" aria-hidden="true">
          <img
            className="brand-logo-mark"
            data-testid="happyfox-logo"
            src={BRAND_LOGO_SRC}
            alt=""
            draggable={false}
          />
        </div>
        <div className="brand-copy">
          <strong>Happy <span>Fox</span></strong>
          <small>AI CREATIVE STUDIO</small>
        </div>
      </div>
      <div className="top-actions">
        <button
          type="button"
          className="balance-pill"
          data-testid="open-balance"
          onClick={() => openWorkspace('balance')}
        >
          {balance.toLocaleString('ru-RU')} <i />
        </button>
        {user?.photo_url ? (
          <img className="avatar" src={user.photo_url} alt="Аватар" />
        ) : (
          <div className="avatar" aria-hidden="true" />
        )}
      </div>
    </header>
  )
}

function BrandLoader({ compact = false }: { compact?: boolean }) {
  return (
    <div className={`brand-loader${compact ? ' compact' : ''}`} aria-hidden="true">
      <img src={BRAND_LOGO_SRC} alt="" draggable={false} />
    </div>
  )
}

function Body({ children }: { children: ReactNode }) {
  const { mode, error, refreshBootstrap } = useApp()

  if (mode === 'loading') {
    return (
      <div className="loader-page" data-testid="miniapp-loading">
        <div>
          <BrandLoader />
          <h2>Happy Fox</h2>
          <p>Подключаем Telegram и загружаем модели…</p>
        </div>
      </div>
    )
  }

  if (mode === 'locked' || mode === 'error') {
    return (
      <main className="fatal" data-testid="miniapp-error">
        <div className="form-card">
          <BrandLoader compact />
          <h1>{mode === 'locked' ? 'Откройте Happy Fox в Telegram' : 'Не удалось загрузить Happy Fox'}</h1>
          <p>{error}</p>
          <button className="primary" type="button" onClick={() => void refreshBootstrap()}>
            Повторить
          </button>
        </div>
      </main>
    )
  }

  return (
    <div className="app">
      <div className="shell">
        <TopBar />
        {children}
      </div>
      <TabNav />
      <WorkspaceSheet />
    </div>
  )
}

export function MiniAppShell({ children }: { children: ReactNode }) {
  useEffect(() => {
    const webApp = window.Telegram?.WebApp
    try {
      webApp?.ready?.()
      webApp?.expand?.()
    } catch {
      // Telegram bridge may be absent in tests.
    }
  }, [])

  return (
    <AppProvider>
      <Body>{children}</Body>
    </AppProvider>
  )
}
