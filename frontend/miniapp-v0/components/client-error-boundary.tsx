'use client'

import { Component, type ErrorInfo, type ReactNode } from 'react'
import { AlertCircle } from 'lucide-react'
import { BRAND_NAME } from '@/lib/brand'
import { Button } from '@/components/ui/button'

interface ClientErrorBoundaryProps {
  children: ReactNode
}

interface ClientErrorBoundaryState {
  hasError: boolean
}

export class ClientErrorBoundary extends Component<
  ClientErrorBoundaryProps,
  ClientErrorBoundaryState
> {
  state: ClientErrorBoundaryState = {
    hasError: false,
  }

  static getDerivedStateFromError(): ClientErrorBoundaryState {
    return { hasError: true }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Mini App client error', error, errorInfo)
    try {
      const payload = {
        event: 'react-error-boundary',
        href: String(window.location.pathname + window.location.search),
        hash_len: String(window.location.hash || '').length,
        has_tg: Boolean(window.Telegram),
        has_webapp: Boolean(window.Telegram?.WebApp),
        init_data_len: window.Telegram?.WebApp?.initData?.length || 0,
        message: String(error?.message || ''),
        name: String(error?.name || ''),
        stack: String(error?.stack || '').slice(0, 1200),
        component_stack: String(errorInfo?.componentStack || '').slice(0, 1200),
      }
      fetch('/mini-app/api/client-log', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        keepalive: true,
      }).catch(() => {})
    } catch {}
  }

  render() {
    if (!this.state.hasError) {
      return this.props.children
    }

    return (
      <div className="flex min-h-screen items-center justify-center bg-background px-5 text-foreground">
        <div className="w-full max-w-sm rounded-2xl border border-border/60 bg-secondary/30 p-5 text-center">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-destructive/15">
            <AlertCircle className="h-6 w-6 text-destructive" />
          </div>
          <h1 className="mt-4 text-lg font-semibold tracking-[0.12em]">{BRAND_NAME}</h1>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            Не удалось открыть Mini App. Обновите окно или откройте приложение заново из Telegram.
          </p>
          <Button
            className="mt-5 w-full bg-gold text-primary-foreground hover:bg-gold/90"
            onClick={() => window.location.reload()}
          >
            Обновить
          </Button>
        </div>
      </div>
    )
  }
}
