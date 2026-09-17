# iOS Telegram Mini App auth incident — 2026-09-17

## Task

Fix the HappyFox Telegram Mini App regression reported on iPhone: a native Telegram launch falls into the browser/login gate, and the browser-auth fallback can loop back into a missing-init-data bootstrap failure.

## Baseline

- Repository: `Bambale0/foxgen`
- Base: `main`
- Baseline SHA: `4d6421c1aaad0e47734a665e2925d6d94157061b`
- Working branch: `fix/ios-miniapp-initdata-auth`
- Production host revision observed: `4d6421c1aaad0e47734a665e2925d6d94157061b`

## Fresh audit

### Already exists

- Shared Next.js Mini App frontend with Telegram/MAX bridge isolation.
- Telegram launch-data readers in `frontend/miniapp-v0/lib/api.ts` with location, bridge, window, and sessionStorage fallbacks.
- Browser Telegram Login fallback in `TelegramOpenGate`.
- Telegram startup browser E2E on Chromium and iPhone WebKit.
- Server-side Telegram initData validation and browser Login signature verification.

### Production evidence

- Production logs on 2026-09-17 contain repeated `GET /mini-app/api/browser-auth/config` from iPhone/Safari-class user agents, proving affected launches reach the locked/browser-auth gate.
- The logs also contain `POST /mini-app/api/browser-auth` returning 200 followed immediately by `POST /mini-app/api/bootstrap` returning 401 with `Mini App bootstrap failed: Missing init_data`.
- No successful iPhone/iPad/Mac-class `POST /mini-app/api/bootstrap ... 200` was found in the current production log slice checked during diagnosis.
- The vendored `frontend/miniapp-v0/public/telegram-web-app.js` SHA differs from Telegram's current official `telegram-web-app.js?63` response, so SDK drift exists, but this is not yet treated as the primary cause.

### Partial / risky behavior

- The early bridge loader reads launch parameters but does not persist raw `tgWebAppData` before loading the Telegram SDK.
- The next early bootstrap snapshot occurs only after the bridge loader has synchronously loaded the SDK.
- Browser Login fallback writes returned signed initData only to `window.location.hash` and reloads; it does not persist the authenticated initData to the same window/sessionStorage recovery channels used by `getInitData()`.

### Missing

- A pre-SDK durable capture of Telegram initData.
- A durable browser-auth handoff across reload.
- A regression test covering initData survival when the hash/bridge state changes before React bootstrap.
- A regression test covering browser-auth persistence semantics.

## Ranked hypotheses

1. iOS launch data is lost between the initial URL and application bootstrap because it is not persisted before the SDK/bridge executes.
2. Browser-auth fallback loops because `setBrowserInitData()` relies only on the URL hash across reload.
3. The vendored Telegram SDK drift contributes to iOS-only behavior.
4. A Telegram button/domain configuration issue causes some iOS launches to become ordinary-browser launches.

## Intended fix / acceptance criteria

1. Capture and persist non-empty `tgWebAppData` synchronously before loading the Telegram SDK.
2. Preserve MAX bridge isolation; do not allow Telegram data to contaminate MAX launches.
3. Browser-auth success persists Telegram initData to the same runtime/sessionStorage channels before reload, not only the hash.
4. `getInitData()` can recover the signed browser-auth session after reload even if the URL hash is removed or rewritten.
5. Add regression coverage for the pre-SDK capture and browser-auth persistence contract.
6. Keep server-side signature validation unchanged.
7. No database, billing, pricing, provider, or cross-project changes.
8. Telegram Chromium + iPhone WebKit and MAX startup coverage remain green.
9. Exact-head CI must be green before merge; merge through PR and canonical auto-deploy only.

## Security / no-hardcode

- No authorization is moved client-side. Client persistence only transports already signed Telegram initData; server validation remains authoritative.
- No mutable business values are introduced.
- Do not log initData, hashes, Telegram Login payloads, or other credentials.

## Observability

- Existing server warning `Mini App bootstrap failed: Missing init_data` remains the production failure signal.
- Post-deploy verification must check that native iOS launches stop hitting the browser-auth gate/missing-init-data path and that normal Telegram/MAX launch telemetry remains healthy.

## Verification plan

- Focused frontend tests for initData capture/persistence.
- Existing frontend unit/contract suite.
- Production build.
- Telegram startup E2E: Chromium + iPhone WebKit.
- MAX startup E2E: Chromium + iPhone WebKit.
- Repository full CI and Docker exact-source verification.
- Standards + Spec code review against baseline `4d6421c1aaad0e47734a665e2925d6d94157061b`.
- Production revision/health/log verification after canonical deploy.

## Skills/guides used

- `Bambale0/skills`: `ask-matt`, `diagnosing-bugs`; `code-review` will be used before merge.
- `Bambale0/claw`: evidence-first repository/debugging discipline from repository instructions.
- `wondelai/skills`: searched for browser/release/testing guidance; no more specific debugging skill was selected over the repository's primary diagnosing-bugs flow.
- `anthropics/skills`: `webapp-testing` for browser/WebKit regression strategy.

## Progress

1. [x] Read repository `AGENTS.md` and production deployment docs.
2. [x] Inspect previous Mini App bridge-isolation execution record and merged PR #256.
3. [x] Inspect production revision and logs.
4. [x] Confirm real missing-init-data/browser-auth failure evidence.
5. [x] Search required skill sources and read applicable guidance.
6. [x] Create dedicated branch.
7. [ ] Add regression tests.
8. [ ] Implement smallest initData persistence fix.
9. [ ] Run focused and full checks.
10. [ ] Run Standards + Spec review and resolve findings.
11. [ ] Merge only with exact-head CI green.
12. [ ] Verify canonical deploy, revision, health, Telegram/MAX parity, and post-deploy telemetry.
