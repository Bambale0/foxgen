import type { Metadata, Viewport } from 'next'
import { BRAND_DESCRIPTION, BRAND_LOGO, BRAND_NAME } from '@/lib/brand'
import './globals.css'

const miniAppBridgeLoaderScript = `
(function () {
  function parseParams(raw) {
    try {
      var value = String(raw || '');
      if (value.charAt(0) === '#' || value.charAt(0) === '?') value = value.slice(1);
      return new URLSearchParams(value);
    } catch (e) {
      return new URLSearchParams();
    }
  }

  var hash = window.location.hash || '';
  var search = window.location.search || '';

  try {
    window.__BANANO_INITIAL_LAUNCH__ = { hash: hash, search: search };
    if (window.sessionStorage) {
      window.sessionStorage.setItem('__banano_initial_hash', hash);
      window.sessionStorage.setItem('__banano_initial_search', search);
    }
  } catch (e) {}

  var hashParams = parseParams(hash);
  var searchParams = parseParams(search);
  function launchValue(name) {
    return String(hashParams.get(name) || searchParams.get(name) || '').trim();
  }

  var telegramData = launchValue('tgWebAppData');
  var maxData = launchValue('WebAppData');
  var platform = maxData && !telegramData ? 'max' : 'telegram';
  window.__BANANO_MINIAPP_PLATFORM_HINT__ = platform;

  var src = platform === 'max'
    ? 'https://st.max.ru/js/max-web-app.js'
    : '/mini-app/telegram-web-app.js';
  document.write('<script src="' + src + '"><\\/script>');
})();
`

const miniAppBootstrapScript = `
(function () {
  var attempts = 0;

  function remember(platform, initData) {
    var value = String(initData || '').trim();
    if (!value) return false;
    try {
      window.__BANANO_MINIAPP_PLATFORM__ = platform;
      if (platform === 'max') {
        window.__BANANO_MAX_INIT_DATA__ = value;
        if (window.sessionStorage) window.sessionStorage.setItem('__banano_max_init_data', value);
      } else {
        window.__BANANO_TG_INIT_DATA__ = value;
        if (window.sessionStorage) window.sessionStorage.setItem('__banano_tg_init_data', value);
      }
    } catch (e) {}
    return true;
  }

  function configureMiniApp() {
    attempts += 1;

    if (window.__BANANO_MINIAPP_PLATFORM_HINT__ === 'max') {
      var maxWebApp = window.WebApp;
      if (maxWebApp && remember('max', maxWebApp.initData)) {
        try { if (maxWebApp.ready) maxWebApp.ready(); } catch (e) {}
        try { if (maxWebApp.expand) maxWebApp.expand(); } catch (e) {}
        return;
      }
    } else {
      var telegramWebApp = window.Telegram && window.Telegram.WebApp;
      if (telegramWebApp && remember('telegram', telegramWebApp.initData)) {
        try { if (telegramWebApp.ready) telegramWebApp.ready(); } catch (e) {}
        try { if (telegramWebApp.expand) telegramWebApp.expand(); } catch (e) {}
        try { if (telegramWebApp.setHeaderColor) telegramWebApp.setHeaderColor('#050505'); } catch (e) {}
        try { if (telegramWebApp.setBackgroundColor) telegramWebApp.setBackgroundColor('#050505'); } catch (e) {}
        try { if (telegramWebApp.setBottomBarColor) telegramWebApp.setBottomBarColor('#080808'); } catch (e) {}
        return;
      }
    }

    if (attempts < 50) window.setTimeout(configureMiniApp, 100);
  }

  configureMiniApp();
  window.addEventListener('load', configureMiniApp, { once: true });
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
        <script
          id="miniapp-bridge-loader"
          dangerouslySetInnerHTML={{ __html: miniAppBridgeLoaderScript }}
        />
        <script
          id="miniapp-early-ready"
          dangerouslySetInnerHTML={{ __html: miniAppBootstrapScript }}
        />
      </head>
      <body className="font-sans antialiased">
        {children}
      </body>
    </html>
  )
}
