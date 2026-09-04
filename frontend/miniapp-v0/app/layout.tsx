import type { Metadata, Viewport } from 'next'
import { BRAND_DESCRIPTION, BRAND_ICON, BRAND_NAME } from '@/lib/brand'
import './globals.css'

const telegramBootstrapScript = `
(function () {
  var attempts = 0;

  try {
    window.__BANANO_INITIAL_LAUNCH__ = {
      hash: window.location.hash || '',
      search: window.location.search || ''
    };
    if (window.sessionStorage) {
      window.sessionStorage.setItem('__banano_initial_hash', window.location.hash || '');
      window.sessionStorage.setItem('__banano_initial_search', window.location.search || '');
    }
  } catch (e) {}

  function configureTelegram() {
    attempts += 1;
    var webApp = window.Telegram && window.Telegram.WebApp;

    if (!webApp) {
      if (attempts < 50) {
        window.setTimeout(configureTelegram, 100);
      }
      return;
    }

    try { if (webApp.ready) webApp.ready(); } catch (e) {}
    try { if (webApp.expand) webApp.expand(); } catch (e) {}
    try { if (webApp.setHeaderColor) webApp.setHeaderColor('#050505'); } catch (e) {}
    try { if (webApp.setBackgroundColor) webApp.setBackgroundColor('#050505'); } catch (e) {}
    try { if (webApp.setBottomBarColor) webApp.setBottomBarColor('#080808'); } catch (e) {}

    try {
      var initData = String(webApp.initData || '').trim();
      if (initData) {
        window.__BANANO_TG_INIT_DATA__ = initData;
        if (window.sessionStorage) {
          window.sessionStorage.setItem('__banano_tg_init_data', initData);
        }
      }
    } catch (e) {}
  }

  configureTelegram();
  window.addEventListener('load', configureTelegram, { once: true });
})();
`

export const metadata: Metadata = {
  title: BRAND_NAME,
  description: BRAND_DESCRIPTION,
  applicationName: BRAND_NAME,
  generator: BRAND_NAME,
  manifest: '/mini-app/manifest.webmanifest',
  icons: {
    icon: [
      { url: BRAND_ICON, type: 'image/png', sizes: '512x512' },
      { url: '/mini-app/happyfox-icon-192.png', type: 'image/png', sizes: '192x192' },
      { url: '/mini-app/icon-light-32x32.png', type: 'image/png', sizes: '32x32', media: '(prefers-color-scheme: light)' },
      { url: '/mini-app/icon-dark-32x32.png', type: 'image/png', sizes: '32x32', media: '(prefers-color-scheme: dark)' },
    ],
    apple: [{ url: '/mini-app/apple-icon.png', type: 'image/png', sizes: '180x180' }],
    shortcut: ['/mini-app/favicon.ico'],
  },
}

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  themeColor: '#050505',
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="ru" className="bg-background">
      <head>
        <script src="/mini-app/telegram-web-app.js" />
        <script
          id="telegram-early-ready"
          dangerouslySetInnerHTML={{ __html: telegramBootstrapScript }}
        />
      </head>
      <body className="font-sans antialiased">
        {children}
      </body>
    </html>
  )
}
