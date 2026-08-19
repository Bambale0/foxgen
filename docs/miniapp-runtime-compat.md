# Happy Fox Mini App runtime compatibility

This runbook defines the production boot contract for Happy Fox in Telegram WebViews.

## Product invariant

Happy Fox has one user-facing product experience: the catalog-first Mini App. Runtime compatibility must never silently downgrade the user to the historical feed-first interface.

The release is versioned by `foxgen.miniapp_release.MINIAPP_RELEASE`. The exact release value is present in the Telegram Mini App entry URL and every release-sensitive static asset URL so an old WebView document or asset cache cannot impersonate the current release.

## Boot pipeline

`index.html` starts three classic scripts in order:

1. `boot-guard.js` — bounded startup watchdog and visible failure/retry state.
2. `runtime-loader.js` — installs narrowly scoped compatibility helpers, probes the WebView parser and selects the core runtime.
3. `enhancement-loader.js` — waits for the authenticated `foxgen:bootstrap` event and attaches the product layer.

The modern core is `parity-app.js`. A WebView that cannot parse the reviewed modern syntax may use `app.js` as a compatibility core, but that is only an implementation detail. It is not permission to expose the old feed-first product.

## Catalog-first compatibility boundary

`product-home.js` is the critical product enhancement. It is declared first in `#foxgen-enhancement-manifest` with `data-critical-module="catalog"` and must be loaded for both modern and compatibility runtimes.

The enhancement loader therefore has no runtime-kind early return. It loads the catalog first and only then loads optional product modules. Once the catalog is ready, the document receives `data-foxgen-catalog="ready"`.

If the catalog script cannot load or does not complete within the bounded startup window, Happy Fox surfaces a visible catalog startup failure with a reload action. It must not silently leave the compatibility core looking like a valid old release.

## Compatibility rules

- The boot guard and runtime loader are deliberately classic scripts and avoid syntax that caused the original Telegram WebView parser failure.
- The runtime loader may polyfill only browser primitives needed by the reviewed Mini App code (`String.prototype.replaceAll` and `structuredClone`). Business logic is never polyfilled in the browser.
- Core authentication, prices, ownership, billing and generation validation remain server-authoritative in both runtime modes.
- Compatibility mode must publish the same `window.__FOXGEN_BOOTSTRAP__` / `foxgen:bootstrap` contract used by the modern runtime.
- Catalog, model prices, wallet entrypoints and user navigation must remain the same product contract regardless of selected core runtime.
- Optional enhancement failure may degrade only that isolated enhancement; it must not block the core catalog or hide a critical startup failure.

## Release and deployment gate

A Mini App release is considered shipped only when all of the following are true:

1. frontend contract tests pass for the exact `MINIAPP_RELEASE`;
2. the production shell declares the exact release and critical catalog asset;
3. production deployment runs from the exact tested `main` SHA;
4. the public `/mini-app/` HTML returns HTTP `Cache-Control` containing `no-store`;
5. public HTML exposes the exact shell marker and release-versioned `product-home.js` / CSS;
6. the public catalog asset contains the catalog implementation marker;
7. the Telegram menu WebApp URL exactly equals the versioned public Mini App URL.

A green backend health check alone is insufficient because JavaScript parser/runtime failures can happen entirely inside Telegram WebView without appearing in API logs.

## Incident diagnosis

If a user sees the splash indefinitely, first distinguish these states:

- old shell/version marker: deployment or document-cache problem;
- current shell but bounded startup error: core runtime/asset problem;
- current shell but old feed-first UI: compatibility product-layer regression;
- catalog renders but a dedicated model action is absent: isolated enhancement/backend readiness issue.

Do not resolve a parser problem by permanently routing users to the historical interface. Fix compatibility at the runtime boundary and keep the catalog-first product invariant intact.
