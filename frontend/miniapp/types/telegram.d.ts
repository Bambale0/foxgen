export {}

declare global {
  interface Window {
    Telegram?: {
      WebApp?: {
        initData?: string
        initDataUnsafe?: { start_param?: string; user?: Record<string, unknown> }
        colorScheme?: string
        ready?: () => void
        expand?: () => void
        close?: () => void
        openInvoice?: (url: string, callback?: (status: string) => void) => void
        showAlert?: (message: string, callback?: () => void) => void
        showConfirm?: (message: string, callback: (ok: boolean) => void) => void
        setHeaderColor?: (color: string) => void
        setBackgroundColor?: (color: string) => void
        setBottomBarColor?: (color: string) => void
        HapticFeedback?: { impactOccurred?: (style: string) => void }
      }
    }
  }
}
