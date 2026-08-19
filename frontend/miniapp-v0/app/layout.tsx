import type { Metadata, Viewport } from 'next'
import { BRAND_DESCRIPTION, BRAND_LOGO, BRAND_NAME } from '@/lib/brand'
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

  function postTelegramEvent(eventType, eventData) {
    if (eventData === undefined) {
      eventData = '';
    }

    var eventDataJson = JSON.stringify(eventData);
    var payload = JSON.stringify({ eventType: eventType, eventData: eventData });

    if (window.TelegramWebviewProxy && typeof window.TelegramWebviewProxy.postEvent === 'function') {
      try {
        window.TelegramWebviewProxy.postEvent(eventType, eventDataJson);
      } catch (e) {}
    }

    if (
      window.webkit &&
      window.webkit.messageHandlers &&
      window.webkit.messageHandlers.TelegramWebviewProxy &&
      typeof window.webkit.messageHandlers.TelegramWebviewProxy.postMessage === 'function'
    ) {
      try {
        window.webkit.messageHandlers.TelegramWebviewProxy.postMessage(payload);
      } catch (e) {}
    }

    if (window.external && typeof window.external.notify === 'function') {
      try {
        window.external.notify(payload);
      } catch (e) {}
    }

    if (window.parent && window.parent !== window && typeof window.parent.postMessage === 'function') {
      try {
        window.parent.postMessage(payload, window.location.origin || '*');
      } catch (e) {}
    }
  }

  function markReady() {
    attempts += 1;
    var webApp = window.Telegram && window.Telegram.WebApp;

    if (webApp) {
      try { if (webApp.ready) webApp.ready(); } catch (e) {}
      try { if (webApp.expand) webApp.expand(); } catch (e) {}
    }

    postTelegramEvent('web_app_ready');
    postTelegramEvent('web_app_expand');

    if (attempts < 30) {
      window.setTimeout(markReady, 100);
    }
  }

  markReady();
  window.addEventListener('DOMContentLoaded', markReady, false);
  window.addEventListener('load', markReady, false);
})();
`

export const metadata: Metadata = {
  title: BRAND_NAME,
  description: BRAND_DESCRIPTION,
  applicationName: BRAND_NAME,
  generator: BRAND_NAME,
  icons: {
    icon: BRAND_LOGO,
    apple: BRAND_LOGO,
  },
}

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  themeColor: '#1a1a2e',
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="ru" className="bg-background">
      <head>
        <script defer src="/mini-app/telegram-web-app.js" />
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
