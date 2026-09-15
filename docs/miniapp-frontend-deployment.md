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

Repository CI additionally runs critical browser journeys plus Telegram and MAX startup in Chromium and iPhone WebKit.

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

Production Mini App origins:

```text
Telegram: https://app.happy-fox.online/mini-app/
MAX:      https://max.happy-fox.online/mini-app/   # activated after DNS/TLS provisioning
```

Both origins publish the same exact-SHA static artifact. They are separate origins so platform storage and bridge state cannot leak across Telegram and MAX.

The deploy workflow/runtime owns host paths, Nginx and static-root details. Do not hardcode an old `cdn.chillcreative.ru` or Tanya source path into new HappyFox changes.

## Telegram startup contract

The normal Mini App path is Telegram WebView with signed `initData`. Manual browser/curl requests without valid Telegram auth may correctly receive an auth failure.

Browser fallback must not replace or weaken Telegram WebView authentication.

## Platform bridge isolation

The initial launch hash/search is inspected before Next.js starts. The page then loads exactly one native bridge:

- `tgWebAppData` → local Telegram WebApp SDK;
- `WebAppData` → MAX Bridge;
- neither → Telegram SDK remains the harmless default while the existing browser-auth fallback handles a genuine normal-browser open.

Telegram startup must never request `https://st.max.ru/js/max-web-app.js`. MAX startup must never request `/mini-app/telegram-web-app.js`. Chromium and iPhone WebKit E2E lock both invariants.

The dedicated MAX origin is prepared but must not be activated in runtime or partner settings before `max.happy-fox.online` has DNS and a valid HTTPS vhost.

## Instagram separation

Instagram creator UX does not use the Mini App as its primary interface. Instagram Direct is a separate channel adapter over the same HappyFox core. The Telegram Mini App can still be used for the shared Telegram account/balance after account linking.

## Canonical docs

- `../README.md`
- `development-deployment.md`
- `production-deployment.md`
- `production_auto_deploy.md`
- `environment.md`
