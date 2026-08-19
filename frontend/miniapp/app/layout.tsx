import type { Metadata, Viewport } from 'next'
import './globals.css'
import './brand.css'

export const metadata: Metadata = {
  title: 'Happy Fox',
  description: 'Happy Fox — AI-студия в Telegram',
  applicationName: 'Happy Fox',
}

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  maximumScale: 1,
  viewportFit: 'cover',
  themeColor: '#070707',
  colorScheme: 'dark',
}

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru">
      <head>
        <meta name="foxgen-miniapp-shell" content="parity-v15" />
        <meta httpEquiv="Cache-Control" content="no-store, no-cache, must-revalidate" />
        <meta httpEquiv="Pragma" content="no-cache" />
        <script src="https://telegram.org/js/telegram-web-app.js?63" />
      </head>
      <body>{children}</body>
    </html>
  )
}
