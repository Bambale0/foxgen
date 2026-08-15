# Happy Fox Telegram Mini App

`Happy Fox` is the public browser/WebView product surface for the FoxGen backend. The user-facing brand is **Happy Fox only**; internal Python packages, database resources and service names retain `foxgen` so product branding does not destabilize backend contracts.

## Telegram entrypoints

The Mini App is a real Telegram Web App, not a callback-only bot screen.

When a public URL is configured, FoxGen exposes Happy Fox through two Telegram entrypoints:

- the first button in the bot `/start` and `/menu` keyboard: **🦊 Открыть Happy Fox**;
- the default Telegram chat menu button: **Happy Fox**.

`FOXGEN_MINIAPP_PUBLIC_URL` is the preferred explicit production URL and should point to the HTTPS `/mini-app/` path. If it is omitted, FoxGen falls back to `FOXGEN_KIE_CALLBACK_BASE_URL + /mini-app/`. If neither public URL exists, the bot fails closed and shows an unavailable alert instead of pretending the Mini App is connected.

## Product surface

The FastAPI process serves the packaged frontend at `/mini-app/`. Public Mini App API routes live under `/v1/miniapp/*`.

The browser UI is now a schema-driven transport over the complete user-safe Mini App API rather than a second hard-coded implementation of provider contracts. The backend model registry and Pydantic JSON schemas remain the source of truth for enabled models, defaults, enums, lengths, numeric bounds and media fields.

Current navigation:

- **Главная** — Telegram identity, real available balance, active jobs, backend-ranked model shortcuts and recent work;
- **Модели** — every currently submission-enabled backend model, capabilities, recommendations, tier and real active price;
- **Создать** — one adaptive studio that renders model fields from `input_schema`, applies backend defaults, supports the exact media modes accepted by the selected contract and performs server validation before paid admission;
- **Работы** — up to the backend-advertised 100 most recent owner-scoped generations with kind/status/model filters, lifecycle polling, detail, cancellation, remix and download;
- **Баланс** — materialized available/reserved/total credit balance, current model prices and immutable ledger history up to the backend-advertised 200 entries;
- **Generation detail** — lifecycle state, stored media, normalized public error information, progress, safe cancel boundary and retry-as-new-draft behavior.

The base visual language remains dark graphite/orange Happy Fox. A secondary `studio.css` layer adds restrained grunge accents to selected hero/card surfaces, stamps and dividers only. Form controls, gallery media, navigation and wallet rows remain clean; the design token `--grunge-opacity` is capped below `0.30` and is regression-tested.

The layout is mobile-first and uses Telegram content-safe-area CSS variables plus `WebApp.BackButton` for in-app navigation.

## Schema-driven model UI

Every enabled model returned by `/v1/miniapp/models` includes:

- stable slug and display metadata;
- media kind, capabilities, recommendations, tier and rank;
- reviewed provider input contract name;
- backend defaults;
- Pydantic-generated `input_schema`.

The frontend maps this schema to controls:

- `boolean` → switch;
- enum → compact segmented control or select;
- long string / `prompt` → bounded textarea;
- number/integer → bounded numeric input;
- image/video/audio URL fields → authenticated private media picker rather than a raw URL text field.

Before `POST /v1/miniapp/tasks`, the draft is sent to `POST /v1/miniapp/models/{slug}/validate`. Validation errors are projected onto the matching field where possible. The paid task endpoint validates the payload again, so browser validation is UX rather than a trust boundary.

Seedance frame mode and multimodal-reference mode remain mutually exclusive because that is a backend contract invariant. The UI exposes text-only, first-frame, first+last-frame and multimodal-reference modes without inventing combinations the provider contract rejects.

## Authentication

The browser never receives an internal FoxGen credential.

1. The Telegram WebView provides `Telegram.WebApp.initData`.
2. `POST /v1/miniapp/auth` sends that opaque string to FoxGen.
3. FoxGen validates the Telegram HMAC over the sorted data-check string, validates `auth_date`, and parses the signed user payload.
4. FoxGen returns a short-lived HS256 JWT with audience `happy-fox-miniapp`.
5. Every user-scoped `/v1/miniapp/*` call requires that JWT.

`FOXGEN_MINIAPP_JWT_SECRET` is a dedicated backend-only secret. Do not reuse the Telegram bot token, KIE key, internal API token, webhook secret or admin HMAC key.

If the page is opened outside Telegram it renders a visual demo using local fixture data. Demo mode cannot call authenticated balance, upload, cancellation or paid-generation endpoints.

## Public API boundary

Happy Fox may use only owner-scoped/user-safe routes. Internal and administrative credentials or routes are never exposed to browser JavaScript. The private admin operator web remains a separate backend-only transport.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/miniapp/auth` | validate Telegram `initData`, issue short JWT |
| `GET` | `/v1/miniapp/bootstrap` | initial user, wallet, prices, compact ledger, models, recent jobs, feature flags and frontend-safe limits |
| `GET` | `/v1/miniapp/models` | current submission-enabled model catalog with contracts/schemas |
| `GET` | `/v1/miniapp/models/{slug}` | current model detail |
| `POST` | `/v1/miniapp/models/{slug}/validate` | free server-side draft validation/normalization |
| `GET` | `/v1/miniapp/balance` | refresh current owner materialized balance |
| `GET` | `/v1/miniapp/prices` | refresh active model prices |
| `GET` | `/v1/miniapp/ledger` | owner immutable ledger projection, bounded to 200 |
| `GET` | `/v1/miniapp/generations` | owner generation history, bounded to 100 |
| `GET` | `/v1/miniapp/generations/{id}` | owner generation detail + stored media URLs |
| `POST` | `/v1/miniapp/generations/{id}/cancel` | existing safe cancellation boundary |
| `POST` | `/v1/miniapp/tasks` | paid admission through shared `SubmissionService` |
| `POST` | `/v1/miniapp/input-media` | authenticated private input upload |
| `DELETE` | `/v1/miniapp/input-media/{storage_key}` | owner-scoped temporary input cleanup |

`bootstrap.features` advertises whether task submission and authenticated input upload are currently usable. `bootstrap.limits` publishes the current input byte limit and bounded frontend history sizes so the browser does not hard-code a looser policy.

## Paid generation boundary

The Mini App does **not** implement an alternative billing or provider path.

`POST /v1/miniapp/tasks`:

1. authenticates the Telegram-derived JWT;
2. requires a caller-provided `Idempotency-Key`;
3. resolves the existing production model registry;
4. runs the existing strict KIE contract validator;
5. calls the same `SubmissionService` used by the trusted Telegram path.

The existing admission transaction therefore remains responsible for user/model availability checks, rate/concurrency gates, active price lookup, sufficient balance, immutable ledger reservation, generation persistence and durable outbox creation.

The Mini App cannot mutate a wallet directly. Wallet refresh endpoints are projections only.

## Private input media

`POST /v1/miniapp/input-media` accepts a raw authenticated body for supported image/video/audio MIME types. The endpoint:

- streams to a temporary file and enforces `FOXGEN_TELEGRAM_INPUT_MAX_BYTES`;
- stores under `inputs/miniapp/<telegram-user-id>/...`;
- returns a signed provider-readable URL, never the signing secret;
- lets the authenticated owner explicitly delete the temporary object/path;
- keeps the existing temporary-input retention policy as a final cleanup backstop.

The browser compares selected file size against the same backend-advertised limit before upload, but server enforcement remains authoritative. Switching an incompatible media mode or resetting a draft explicitly cleans temporary uploaded inputs. Stored result media reused for remix are not deleted as temporary inputs.

## Result media and ownership

Generation history is queried by the authenticated Telegram user ID. A generation owned by another user is returned as `404`, not projected cross-user.

Only archived `stored` media assets receive browser URLs. Result URLs are generated by the server with the short `FOXGEN_MINIAPP_MEDIA_URL_TTL_SECONDS` TTL. S3 credentials never enter HTML/JavaScript responses.

The gallery requests the full bounded history rather than treating the 12-item bootstrap projection as the complete account history. Generation detail is refreshed independently and active jobs are polled until a terminal state.

## Wallet behavior

Balance and ledger are real backend projections. The frontend can refresh available/reserved/total units, active model prices and immutable ledger entries, but it has no route that directly adjusts balance.

The public payment-provider invoice flow remains owned by EPIC #7. Until a user-safe payment endpoint lands in `main`, Happy Fox deliberately shows the missing payment boundary instead of rendering a fake top-up action.

## Production setup

Required backend configuration:

```env
FOXGEN_MINIAPP_ENABLED=true
FOXGEN_MINIAPP_PUBLIC_URL=https://foxgen.example.com/mini-app/
FOXGEN_MINIAPP_JWT_SECRET=<dedicated-random-secret>
FOXGEN_MINIAPP_AUTH_MAX_AGE_SECONDS=86400
FOXGEN_MINIAPP_JWT_TTL_SECONDS=3600
FOXGEN_MINIAPP_MEDIA_URL_TTL_SECONDS=300
```

The public reverse proxy must serve `/mini-app/` and `/v1/miniapp/*` to the API service while continuing to deny public `/internal/admin/*` access.

On bot startup FoxGen calls Telegram `setChatMenuButton` for the default `Happy Fox` Web App menu. The inline `/start` keyboard uses the same resolved URL. BotFather Main Mini App configuration may also point to the same HTTPS `/mini-app/` URL when a profile-level launch button is desired.

## Current product boundary

The frontend covers the complete **Mini App-safe** backend surface in `main`; that does not mean browser access is added to backend-only capabilities.

Not exposed to Happy Fox:

- signed/internal admin APIs and admin credentials;
- direct balance adjustment and tariff writes;
- operator reconciliation/unknown-resolution actions;
- provider/webhook/internal service credentials;
- unfinished branches or domains that are not merged into `main`.

Feed/profile publication from issue #58 / PR #63 and durable reference-memory work from its separate branch remain independent until merged. The Mini App must not document or simulate those branch-only capabilities as current production behavior.

## Tests and rollback

Regression coverage includes:

- valid/tampered/stale Telegram `initData`;
- JWT round-trip and missing-token rejection;
- owner binding for bootstrap/history/detail/wallet projection;
- complete enabled model catalog with JSON schemas;
- server-side model validation/normalization before paid admission;
- task submission identity + idempotency through shared `SubmissionService`;
- private upload user namespace;
- frontend contract markers for history, ledger, model validation, media lifecycle and cancel;
- restrained-grunge token capped at `0.30`;
- Telegram inline WebApp button URL and fail-closed fallback;
- packaged static shell showing `Happy Fox` rather than the old user-facing brand.

The feature is controlled by `FOXGEN_MINIAPP_ENABLED`. Disabling it removes the public Mini App router/static mount and suppresses Telegram WebApp entrypoints without changing worker, billing or provider lifecycle state.
