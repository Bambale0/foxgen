# HappyFox Mini App Frontend

Production Telegram Mini App for `Bambale0/foxgen`.

## Stack

- Next.js 16
- React 19
- TypeScript
- static export
- Playwright release checks

## Product boundary

User-facing brand is HappyFox. Historical NEUROMIX/Tanya deployment profiles and domains are not current production instructions.

Production source is the same verified `main` SHA as the backend. The Mini App is not released from a separate branch.

## Local checks

```bash
npm ci
npm audit --omit=dev --audit-level=high
npm run lint
npm run build
```

Repository CI also runs critical browser journeys and Telegram startup on Chromium and iPhone WebKit.

## Auth

Normal runtime is Telegram WebView with signed `initData`. A direct browser/curl request without valid Telegram auth can correctly receive an auth error.

## Deploy

Current public Mini App:

```text
https://alena.chillcreative.ru/mini-app/
```

Release flow:

```text
PR -> main CI -> merge -> main CI -> exact-SHA HappyFox production deploy
```

See `../../docs/miniapp-frontend-deployment.md` and `../../docs/production-deployment.md`.

## Instagram

Instagram Direct is a separate channel adapter and does not duplicate the Mini App UI. Linked Instagram users share the same HappyFox account/balance through Telegram account linking.
