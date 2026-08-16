# FoxGen

FoxGen is a Telegram-first multimodal AI generation platform built on Python 3.12, FastAPI, aiogram 3, PostgreSQL, Redis, S3-compatible object storage and KIE.ai.

The public user-facing Mini App is branded **Happy Fox**. Internal repository/package/service identifiers remain `foxgen`; the brand change does not alter durable backend contracts.

## What is implemented

### Happy Fox public Mini App

- packaged public mobile surface at `/mini-app/` with dark graphite/orange UI;
- Telegram `initData` is verified server-side before a short-lived Mini App JWT is issued;
- owner-scoped `/v1/miniapp/*` APIs expose real balance, immutable ledger history, active prices, model catalog and recent generations;
- schema-driven creation studio for every submission-enabled backend model; controls, defaults, enums and media limits come from the reviewed backend `input_schema`;
- image/video/audio input modes are wired to authenticated private uploads, including Seedance text, first-frame, first+last and multimodal-reference scenarios;
- executable **ElevenLabs Turbo 2.5 TTS** Audio product with backend-owned schema and shared paid lifecycle;
- executable **Suno V5 core** Music product with simple/custom vocal/instrumental modes and multi-track audio results;
- paid launches reuse the same `SubmissionService`, model contracts, rate/concurrency gates, atomic reservation and durable outbox as Telegram;
- private authenticated input upload and short-lived result-media URLs;
- gallery/history, lifecycle polling, safe cancellation boundary, remix into a new draft and download;
- feed/profile/publication/remix, likes/comments and durable reference memory;
- tariffs, support and partner user portal;
- wallet with real balance, immutable ledger, promo redemption and **Telegram Stars (`XTR`) top-up**;
- Telegram viewport/content-safe-area and BackButton integration;
- browser-only demo mode for visual review; demo cannot perform authenticated balance/upload/paid operations.

Happy Fox Stars checkout creates a durable owner-scoped payment order before asking Telegram for an invoice link. Telegram's native `successful_payment` update is recorded server-side as durable charge evidence before CREDIT settlement. The browser cannot declare payment success or mutate the wallet.

See [`docs/miniapp.md`](docs/miniapp.md), [`docs/suno-core.md`](docs/suno-core.md) and [`docs/telegram-stars-payments.md`](docs/telegram-stars-payments.md).

### Telegram product shell

- real Happy Fox WebApp entrypoint;
- feed/profile/publication actions;
- live main-menu creation routes for image, video, ElevenLabs TTS and Suno V5 core music;
- planned product buttons remain explicitly disabled until their complete backend + Telegram + Happy Fox slices exist;
- Quick Start from the main menu;
- photo/video sent with no active FSM is accepted as a reference entrypoint;
- user chooses whether to create an image or a video from the received reference;
- user-friendly image/video screen FSM with model-specific dynamic settings;
- dedicated TTS FSM: text → voice → speed → live price/balance → shared paid submit;
- dedicated Suno core FSM: simple/custom → vocal/instrumental → required text fields → live price/balance → shared paid submit;
- durable reusable reference memory with owner-scoped multi-select/delete/reuse;
- Redis-backed FSM with back/cancel/menu, invalid-input handling, stale callback recovery and TTL expiry;
- `/start` and `/menu` are global first-priority interrupts and clear active product drafts plus known temporary inputs;
- Redis event isolation serializes concurrent updates for one FSM key;
- Telegram albums are rejected before upload;
- private local storage for Telegram reference files;
- native Telegram Stars `pre_checkout_query` / `successful_payment` transport before generic message fallbacks;
- server-authorized `/admin` panel with privileged extension callbacks registered ahead of broad fallbacks.

### Generation and provider lifecycle

- typed KIE.ai provider registry and strict model contracts;
- reviewed API-family routing: ordinary KIE Market models and dedicated Suno API family are selected by `ModelSpec.api_family`, not guessed from model names;
- free local model validation before paid admission;
- fail-closed trusted internal task API;
- mandatory user identity and `Idempotency-Key` for paid requests;
- Redis rate limits plus PostgreSQL per-user/global active-generation limits;
- atomic generation + billing reservation + immutable ledger + outbox admission;
- worker claiming through `FOR UPDATE SKIP LOCKED`;
- exactly-one-attempt boundary for billable provider submission;
- `submission_unknown` instead of unsafe automatic provider resubmission;
- callback/polling convergence where the reviewed provider family supports it;
- explicit durable lifecycle through processing, result storage and delivery;
- multi-result providers preserve each canonical result; Suno normalization excludes artwork/stream helper URLs from generic archival;
- partial media archive retry, dead-letter state and reconciliation;
- SSRF-resistant result download and private S3-compatible archive;
- duplicate-safe Telegram delivery with explicit `delivery_unknown` state.

### Billing and user payments

- integer internal credits; no floating-point wallet arithmetic;
- versioned model prices;
- materialized wallet accounts backed by an append-only ledger;
- atomic reserve/capture/release/refund lifecycle;
- deterministic idempotency for balance adjustments and settlement;
- reconciliation across generation, reservation, media, outbox and delivery state;
- versioned tariff packages;
- Telegram Stars package/invoice flow for digital CREDIT top-up;
- durable `user_payment_orders` with paid-before-credit recovery and native refund states;
- unique Telegram charge and deterministic payment/refund ledger keys;
- paid-but-uncredited evidence survives settlement failure for safe admin reprocessing;
- privileged native Telegram Stars refund with durable hold/retry/unknown-resolution behavior;
- explicit server-owned Stars package bonuses that settle/reprocess/refund with the full CREDIT grant;
- owner promo-code redemption with immutable ledger credit, per-user idempotency and atomic `max_uses` enforcement.

External web acquiring and dynamic/segmented bonus campaign rules remain separate reviewed follow-up slices; see [`docs/known-limitations.md`](docs/known-limitations.md).

### Administrative control plane

FoxGen has one administrative domain layer exposed through the registered Telegram `/admin`, signed backend HTTP API and internal operator web surface. Happy Fox is a separate public transport surface and cannot use administrative credentials.

Registered/current capabilities include:

- server-side RBAC policy and bootstrap/durable admin identity model;
- direct admin identity/role/scope management through signed/private web transports;
- dedicated admin analytics and privileged generation preview;
- user lookup, block/unblock and balance adjustment;
- generation, operation, payment and finance inspection;
- payment recheck/reprocess/refund with double-credit protection and evidence-based ambiguous-refund resolution;
- versioned tariff publishing;
- partner analytics and withdrawal actions, including confirmed/idempotent Telegram payout shortcut;
- promo management;
- prompt-library moderation;
- runtime flags and model availability without deployment;
- support tickets and durable support outbox;
- versioned CMS documents;
- notification preview/campaign create/test/start/cancel;
- durable campaign deliveries, retries and rate limiting;
- trends/feed moderation backend actions;
- CSV and XLS exports;
- audit browsing and read-only AI diagnostics;
- append-only admin command ledger with request/result snapshots and idempotent replay.

Every admin write is server-authorized. Signed HTTP admin requests are network allowlisted and use HMAC-SHA256 over the exact raw body. Destructive or expensive actions require explicit confirmation. The operator-web extension router is registered before generic routes so dedicated endpoints cannot be shadowed.

## Architecture at a glance

```text
Telegram bot ────────────────┐
Happy Fox Mini App ──────────┼──> FastAPI
Trusted internal clients ────┤      ├── shared paid generation admission
Telegram /admin ─────────────┤      ├── user payment/order settlement
                             │      ├── registered signed internal admin API
                             │      └── provider callbacks
                             │
                             v
                      Application services
                      ├── submissions
                      ├── generation lifecycle
                      ├── billing / payments
                      ├── reconciliation
                      └── admin services
                             │
              ┌──────────────┼──────────────┐
              v              v              v
          PostgreSQL        Redis       S3-compatible
          source of truth   FSM/locks   private media
              │
              v
          foxgen-worker
          ├── routed KIE Market / Suno submission + polling
          ├── callback processing
          ├── archive/delivery
          └── admin/support/campaign/refund work
```

Happy Fox is transport only: Telegram identity validation and owner-scoped projection happen at the API edge, while paid work and payment settlement continue through server-side application/domain services.

See [`docs/architecture.md`](docs/architecture.md) for boundaries and invariants.

## Generation lifecycle

Durable generation states:

```text
draft
  -> queued
  -> submitting
  -> submitted
  -> processing
  -> result_ready
  -> storing_media
  -> delivery_pending
  -> succeeded
```

Recovery/terminal branches include `submission_unknown`, `failed` and `cancelled`.

A billable provider POST is never automatically replayed after its side-effect boundary. A lost provider response moves the local task into an ambiguity state that must converge through reviewed callback, polling or evidence-based operator reconciliation.

## Telegram Stars lifecycle

```text
payment order created
  -> invoice_ready
  -> Telegram confirms unique charge
  -> paid              # durable external evidence committed
  -> credited          # wallet + immutable ledger settled
  -> refund_pending
       -> refunded
       -> refund_unknown -> evidence-based resolution
```

`paid` blocks another pre-checkout for the same order. If settlement fails after Telegram charged the user, the committed `PaymentEvent` remains available for the idempotent admin payment reprocess path. Users should not be asked to pay again merely because CREDIT settlement failed.

## Local development

```bash
cp .env.example .env
# Fill only the secrets needed for the feature you are testing.
docker compose up --build
```

Local Compose provides PostgreSQL, Redis, MinIO, migrations, API, worker and bot. Temporary inputs remain private; generated result archives remain in MinIO. MinIO bootstrap creates the private bucket when needed, installs the short-retention `inputs/` lifecycle rule, verifies it, configures bundled MinIO stale multipart cleanup and gates API/worker/bot startup.

The visual Happy Fox shell is available at:

```text
http://localhost:8080/mini-app/
```

Outside Telegram it runs in non-mutating demo mode. For authenticated Mini App tests configure a Telegram bot token and dedicated JWT secret:

```env
FOXGEN_MINIAPP_ENABLED=true
FOXGEN_TELEGRAM_BOT_TOKEN=<bot-token>
FOXGEN_MINIAPP_JWT_SECRET=<dedicated-miniapp-secret>
```

Paid provider submission remains disabled until explicitly enabled:

```env
FOXGEN_TASK_SUBMISSION_ENABLED=true
FOXGEN_INTERNAL_API_TOKEN=<dedicated-internal-secret>
FOXGEN_KIE_API_KEY=<kie-key>
```

A test wallet also needs an active model price and enough credits before Telegram or Happy Fox can launch a paid generation. This includes TTS and Suno: their product slices deliberately do not hardcode commercial prices. Stars top-up additionally needs an admin-published tariff package containing a positive CREDIT amount and explicit positive `stars`/`stars_amount` value.

See [`docs/development.md`](docs/development.md), [`docs/miniapp.md`](docs/miniapp.md), [`docs/suno-core.md`](docs/suno-core.md) and [`docs/telegram-stars-payments.md`](docs/telegram-stars-payments.md).

## Administrative bootstrap

The full admin control plane is disabled by default. Minimal backend setup:

```env
FOXGEN_ADMIN_API_ENABLED=true
FOXGEN_ADMIN_HMAC_KEY=<dedicated-admin-hmac-secret>
FOXGEN_ADMIN_NETWORK_ALLOWLIST=127.0.0.1/32,::1/128,172.16.0.0/12
FOXGEN_ADMIN_SUPERUSER_IDS=<telegram-admin-id>
```

Do not reuse Telegram, KIE, webhook or ordinary internal API secrets as the admin HMAC key. Restrict the network allowlist to the real backend subnet in production. See [`docs/admin-control-plane.md`](docs/admin-control-plane.md).

## Public and internal APIs

Core routes include:

```text
GET  /health/live
GET  /health/ready
GET  /v1/models
GET  /v1/models/{slug}
POST /v1/models/{slug}/validate
POST /v1/models/{slug}/tasks
POST /webhooks/kie
```

Happy Fox adds owner-scoped routes such as:

```text
POST   /v1/miniapp/auth
GET    /v1/miniapp/bootstrap
GET    /v1/miniapp/models
POST   /v1/miniapp/models/{slug}/validate
GET    /v1/miniapp/balance
GET    /v1/miniapp/prices
GET    /v1/miniapp/ledger
GET    /v1/miniapp/generations
POST   /v1/miniapp/tasks
POST   /v1/miniapp/input-media
GET    /v1/miniapp/feed
GET    /v1/miniapp/reference-memory
GET    /v1/miniapp/tariff
GET    /v1/miniapp/support
GET    /v1/miniapp/partner
GET    /v1/miniapp/payments/stars/packages
POST   /v1/miniapp/payments/stars/invoices
POST   /v1/miniapp/promos/redeem
```

Trusted Telegram payment completion uses:

```text
POST /v1/user-portal/payments/stars/pre-checkout
POST /v1/user-portal/payments/stars/success
```

Billing/generation operator routes and the registered signed `/internal/admin/*` surface are documented in [`docs/api-reference.md`](docs/api-reference.md). Happy Fox security/transport details are in [`docs/miniapp.md`](docs/miniapp.md).

Never place internal API tokens, admin HMAC keys, billing credentials, KIE credentials, Telegram bot tokens or object-storage credentials in Telegram clients, browsers or a public Mini App.

## Quality and CI

The reproducible CI pipeline uses the exact dependency lock and checks:

- Ruff lint;
- Ruff formatting gate;
- strict mypy;
- pytest with coverage threshold;
- real PostgreSQL and Redis integration tests;
- cross-layer E2E over `tests/e2e`;
- Alembic upgrade, current-head verification and downgrade/re-upgrade;
- API readiness smoke test;
- Gitleaks;
- dependency review;
- Trivy filesystem/image scans;
- Docker Compose validation;
- deterministic production image build/import smoke test.

Financial and paid-product changes require real infrastructure assertions. TTS E2E proves paid audio admission/archive/delivery. Suno E2E proves routed dedicated-provider execution, intermediate processing and preservation/archive/delivery of multiple audio tracks.

Local commands:

```bash
python -m pip install --requirement requirements.lock
python -m pip install --no-deps --editable .
make ci
```

See [`docs/testing-ci.md`](docs/testing-ci.md).

## Production deploy

A successful CI run on `main` can trigger the protected production deployment workflow. Deployment is gated by the `production` GitHub Environment and `AUTODEPLOY_ENABLED=true`.

The server keeps its own `.env`; GitHub Actions does not upload application secrets. Deployment is exact-SHA, fast-forward only, serialized with `flock`, runs migrations before application replacement and requires `/health/ready` to pass.

Production Compose runs a fail-closed `minio-init` bootstrap before API/worker/bot startup. It preserves unrelated bucket rules, installs and reads back the short-retention `inputs/` rule, and never targets durable generation/reference results. External S3-compatible topologies must provide equivalent lifecycle enforcement themselves.

For Happy Fox, the public reverse proxy serves `/mini-app/` and `/v1/miniapp/*`; `/internal/admin/*` remains private. The deploy gate also verifies public Happy Fox and Telegram default WebApp menu convergence after exact-image recreation/reload.

See:

- [`docs/production-deploy.md`](docs/production-deploy.md)
- [`docs/miniapp.md`](docs/miniapp.md)
- [`docs/suno-core.md`](docs/suno-core.md)
- [`docs/telegram-stars-payments.md`](docs/telegram-stars-payments.md)
- [`docs/minio-lifecycle-runbook.md`](docs/minio-lifecycle-runbook.md)
- [`docs/github-environment-setup.md`](docs/github-environment-setup.md)
- [`docs/operations-runbook.md`](docs/operations-runbook.md)

## Documentation index

Start with [`docs/README.md`](docs/README.md). It maps architecture, schema, configuration, API, Happy Fox, Telegram FSM, model contracts, provider families, billing/payments, admin, security, CI, deployment, reconciliation and operations.

## Source-of-truth rules

- runtime behavior/reachability: registered code paths + tests;
- database schema: Alembic migrations + SQLAlchemy models;
- model provider IDs/payload contracts/API-family routing: reviewed provider registry/contracts/adapters + tests;
- payment evidence/settlement: durable order/payment rows + immutable ledger + integration tests;
- application environment variables: `foxgen.core.config.Settings`, `.env.example`, `deploy/production.env.example`;
- infrastructure bootstrap variables: Compose/scripts plus env examples and `docs/configuration.md`;
- deploy behavior: `.github/workflows/`, `docker-compose.prod.yml`, `scripts/deploy-production.sh`;
- current limitations: `docs/known-limitations.md` plus open tracked issue/PR state.

If documentation disagrees with executable code or migrations, treat executable state as authoritative and correct the documentation in the same PR.

## Repository workflow

Read [`AGENTS.md`](AGENTS.md) before automated changes. Changes to behavior, APIs, schema, provider contracts, security, payments or deployment must update relevant documentation and tests in the same PR.
