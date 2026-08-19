# Happy Fox Mini App runtime compatibility

This runbook defines the production boot contract for Happy Fox in Telegram WebViews.

## Product invariant

Happy Fox has one user-facing product experience: the catalog-first Mini App. Runtime compatibility must never silently downgrade the user to the historical feed-first interface.

The release is versioned by `foxgen.miniapp_release.MINIAPP_RELEASE`. The exact release value is present in the Telegram Mini App entry URL and every release-sensitive static asset URL so an old WebView document or asset cache cannot impersonate the current release.

## Boot pipeline

`index.html` starts the boot guard and runtime loader before optional enhancements:

1. `boot-guard.js` — bounded startup watchdog plus a visible fatal/retry state.
2. `runtime-loader.js` — installs narrowly scoped browser compatibility helpers, probes the WebView parser and loads the only supported core runtime, `parity-app.js`.
3. `runtime-loader.js` then loads `product-home.js` as a mandatory core product layer, not as an optional enhancement.
4. `enhancement-loader.js` waits for authenticated bootstrap and for `main[data-product-catalog="1"]`; only then may optional product modules load.

There is no `app.js` compatibility runtime and no `legacy=1` redirect. If the Telegram WebView cannot parse the current runtime, Happy Fox fails closed with a clear update/retry message instead of opening an obsolete application.

## Catalog-first boundary

`product-home.js` is mandatory. The runtime manifest exposes it through `data-product-home-src`; loading it is part of successful core startup.

The enhancement loader considers the Mini App ready only after the catalog marks the active main surface with `data-product-catalog="1"`. The document then receives `data-foxgen-catalog="ready"`.

If the catalog script cannot load or does not render within the bounded startup window, `__FOXGEN_BOOT_FATAL__` replaces the surface with a startup error. The historical feed-first screen is never accepted as a valid fallback.

## Compatibility rules

- `boot-guard.js` and `runtime-loader.js` remain classic scripts and avoid syntax that originally caused Telegram WebView parser failures.
- The runtime loader may polyfill only browser primitives needed by the reviewed Mini App code (`String.prototype.replaceAll` and `structuredClone`). Business logic is never polyfilled in the browser.
- Core authentication, prices, ownership, billing and generation validation remain server-authoritative.
- `window.__FOXGEN_BOOTSTRAP__` / `foxgen:bootstrap` is the single browser bootstrap contract.
- Optional enhancement failure may degrade only that isolated enhancement; it must not replace or downgrade the current catalog.
- A WebView too old for the current runtime must show a clear unsupported-runtime error, not another product version.

## Release and deployment gate

A Mini App release is considered shipped only when all of the following are true:

1. frontend contract tests pass for the exact `MINIAPP_RELEASE`;
2. the production shell declares only `parity-app.js` plus mandatory `product-home.js` as core runtime assets;
3. no `data-legacy-src`, `legacy=1` redirect or `/mini-app/app.js` production reference exists;
4. production deployment runs from the exact tested `main` SHA;
5. the public `/mini-app/` HTML returns HTTP `Cache-Control` containing `no-store`;
6. public HTML exposes the exact shell marker and release-versioned catalog assets;
7. the public catalog asset contains the catalog implementation marker;
8. the Telegram menu WebApp URL exactly equals the versioned public Mini App URL.

A green backend health check alone is insufficient because JavaScript parser/runtime failures can happen entirely inside Telegram WebView without appearing in API logs.

## Incident diagnosis

If a user sees the splash indefinitely, distinguish these states:

- old shell/version marker: deployment or document-cache problem;
- current shell but bounded startup error: current runtime/core asset problem;
- current shell but historical feed-first start screen: release regression and merge blocker;
- catalog renders but a dedicated model action is absent: isolated enhancement/backend readiness issue.

Do not solve parser or loading problems by routing users to an obsolete UI. The production entrypoint must expose one current Mini App only.
