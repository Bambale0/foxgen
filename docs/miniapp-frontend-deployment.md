# HappyFox Mini App deployment

The HappyFox Mini App lives in `frontend/miniapp-v0` and is released together with the verified `foxgen/main` SHA.

## Local verification

```bash
cd frontend/miniapp-v0
npm ci
npm audit --omit=dev --audit-level=high
npm run lint
npm run build
```

Repository CI additionally runs critical browser journeys and Telegram startup in Chromium and iPhone WebKit.

## Production release

Do not follow historical NEUROMIX/Tanya CDN profile instructions for HappyFox.

Current release path:

```text
PR to main
 -> CI builds static export
 -> merge
 -> main CI rebuilds/verifies exact SHA
 -> Deploy HappyFox production
 -> public Mini App revision/smoke
```

Current public URL:

```text
https://alena.chillcreative.ru/mini-app/
```

The deploy workflow/runtime owns host paths, Nginx and static-root details. Do not hardcode an old `cdn.chillcreative.ru` or Tanya source path into new HappyFox changes.

## Telegram startup contract

The normal Mini App path is Telegram WebView with signed `initData`. Manual browser/curl requests without valid Telegram auth may correctly receive an auth failure.

Browser fallback must not replace or weaken Telegram WebView authentication.

## Instagram separation

Instagram creator UX does not use the Mini App as its primary interface. Instagram Direct is a separate channel adapter over the same HappyFox core. The Telegram Mini App can still be used for the shared Telegram account/balance after account linking.

## Canonical docs

- `../README.md`
- `development-deployment.md`
- `production-deployment.md`
- `production_auto_deploy.md`
- `environment.md`
