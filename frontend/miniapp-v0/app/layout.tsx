import type { Metadata, Viewport } from 'next'
import { BRAND_DESCRIPTION, BRAND_LOGO, BRAND_NAME } from '@/lib/brand'
import './globals.css'

const miniAppLaunchSnapshotScript = `
(function () {
  try {
    var snapshot = {
      hash: window.location.hash || '',
      search: window.location.search || ''
    };
    window.__BANANO_PRE_MAX_LAUNCH__ = snapshot;
    window.__BANANO_INITIAL_LAUNCH__ = snapshot;
    if (window.sessionStorage) {
      window.sessionStorage.setItem('__banano_pre_max_hash', snapshot.hash);
      window.sessionStorage.setItem('__banano_pre_max_search', snapshot.search);
      window.sessionStorage.setItem('__banano_initial_hash', snapshot.hash);
      window.sessionStorage.setItem('__banano_initial_search', snapshot.search);
    }
  } catch (e) {}
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

  function launchData(name) {
    var snapshot = window.__BANANO_PRE_MAX_LAUNCH__ || window.__BANANO_INITIAL_LAUNCH__ || {};
    var values = [
      snapshot.hash || '',
      snapshot.search || '',
      window.location.hash || '',
      window.location.search || ''
    ];
    for (var i = 0; i < values.length; i += 1) {
      try {
        var raw = String(values[i] || '');
        var params = new URLSearchParams(raw.charAt(0) === '#' || raw.charAt(0) === '?' ? raw.slice(1) : raw);
        var value = String(params.get(name) || '').trim();
        if (value) return value;
      } catch (e) {}
    }
    return '';
  }

  function configureMiniApp() {
    attempts += 1;

    var telegramWebApp = window.Telegram && window.Telegram.WebApp;
    var telegramInitData = (telegramWebApp && telegramWebApp.initData) || launchData('tgWebAppData');
    if (remember('telegram', telegramInitData)) {
      try { if (telegramWebApp && telegramWebApp.ready) telegramWebApp.ready(); } catch (e) {}
      try { if (telegramWebApp && telegramWebApp.expand) telegramWebApp.expand(); } catch (e) {}
      try { if (telegramWebApp && telegramWebApp.setHeaderColor) telegramWebApp.setHeaderColor('#050505'); } catch (e) {}
      try { if (telegramWebApp && telegramWebApp.setBackgroundColor) telegramWebApp.setBackgroundColor('#050505'); } catch (e) {}
      try { if (telegramWebApp && telegramWebApp.setBottomBarColor) telegramWebApp.setBottomBarColor('#080808'); } catch (e) {}
      return;
    }

    var maxWebApp = window.WebApp;
    var maxInitData = (maxWebApp && maxWebApp.initData) || launchData('WebAppData');
    if (remember('max', maxInitData)) {
      try { if (maxWebApp && maxWebApp.ready) maxWebApp.ready(); } catch (e) {}
      try { if (maxWebApp && maxWebApp.expand) maxWebApp.expand(); } catch (e) {}
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
        <script src="/mini-app/telegram-web-app.js" />
        <script
          id="miniapp-launch-snapshot"
          dangerouslySetInnerHTML={{ __html: miniAppLaunchSnapshotScript }}
        />
        <script src="https://st.max.ru/js/max-web-app.js" />
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
