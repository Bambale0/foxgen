import type { Metadata, Viewport } from 'next'
import { BRAND_DESCRIPTION, BRAND_LOGO, BRAND_NAME } from '@/lib/brand'
import './globals.css'

const miniAppBridgeLoaderScript = `
(function () {
  var rawHash = window.location.hash || '';
  var rawSearch = window.location.search || '';
  var launch = new URLSearchParams(rawHash.charAt(0) === '#' ? rawHash.slice(1) : rawHash);
  var search = new URLSearchParams(rawSearch.charAt(0) === '?' ? rawSearch.slice(1) : rawSearch);

  search.forEach(function (value, key) {
    if (!launch.has(key)) launch.set(key, value);
  });

  var hostname = String(window.location.hostname || '').toLowerCase();
  var maxHost = hostname === 'max.happy-fox.online';
  var hasMaxLaunch =
    launch.has('WebAppData') ||
    launch.has('WebAppPlatform') ||
    launch.has('WebAppVersion') ||
    launch.has('WebAppStartParam');
  var hasTelegramLaunch =
    launch.has('tgWebAppData') ||
    launch.has('tgWebAppPlatform') ||
    launch.has('tgWebAppVersion') ||
    launch.has('tgWebAppStartParam');

  var useMax = maxHost || (hasMaxLaunch && !hasTelegramLaunch);
  var src = useMax
    ? 'https://st.max.ru/js/max-web-app.js'
    : '/mini-app/telegram-web-app.js';

  window.__BANANO_BRIDGE_KIND__ = useMax ? 'max' : 'telegram';
  document.write('<script src="' + src + '"><\\/script>');
})();
`

const miniAppBootstrapScript = `
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

    var maxWebApp = window.WebApp;
    if (maxWebApp && remember('max', maxWebApp.initData)) {
      try { if (maxWebApp.ready) maxWebApp.ready(); } catch (e) {}
      try { if (maxWebApp.expand) maxWebApp.expand(); } catch (e) {}
      return;
    }

    var telegramWebApp = window.Telegram && window.Telegram.WebApp;
    if (telegramWebApp && remember('telegram', telegramWebApp.initData)) {
      try { if (telegramWebApp.ready) telegramWebApp.ready(); } catch (e) {}
      try { if (telegramWebApp.expand) telegramWebApp.expand(); } catch (e) {}
      try { if (telegramWebApp.setHeaderColor) telegramWebApp.setHeaderColor('#050505'); } catch (e) {}
      try { if (telegramWebApp.setBackgroundColor) telegramWebApp.setBackgroundColor('#050505'); } catch (e) {}
      try { if (telegramWebApp.setBottomBarColor) telegramWebApp.setBottomBarColor('#080808'); } catch (e) {}
      return;
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
          id="telegram-early-ready"
          dangerouslySetInnerHTML={{ __html: miniAppBootstrapScript }}
        />
      </head>
      <body className="font-sans antialiased">
        {children}
      </body>
    </html>
  )
}
