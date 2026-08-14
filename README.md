# FoxGen

FoxGen is a Telegram-first multimodal AI generation platform built on Python 3.12, FastAPI, aiogram 3, PostgreSQL, Redis, S3-compatible object storage and KIE.ai.

The public user-facing Mini App is branded **Happy Fox**. Internal repository/package/service identifiers remain `foxgen`; the brand change does not alter durable backend contracts.

## What is implemented

### Happy Fox public Mini App

- packaged public mobile surface at `/mini-app/` with dark graphite/orange UI;
- user-facing brand is `Happy Fox` only;
- Telegram `initData` is verified server-side before a short-lived Mini App JWT is issued;
- owner-scoped `/v1/miniapp/*` APIs expose real balance, immutable ledger history, active prices, model catalog and recent generations;
- image creation for Seedream 5 Pro, Nano Banana 2 and Nano Banana Pro with optional private references and model-specific settings;
- video creation for Seedance 2 / Mini with text, first-frame, first+last and multimodal-reference scenarios;
- paid launches reuse the same `SubmissionService`, model contracts, rate/concurrency gates, atomic reservation and durable outbox as Telegram;
- private authenticated input upload under a user namespace and short-lived result-media URLs;
- gallery/history, lifecycle polling, safe cancellation boundary, remix into a new draft and download;
- profile/wallet screen with real balance and ledger projection;
- Telegram viewport/content-safe-area and BackButton integration;
- browser-only demo mode for visual review; demo cannot perform authenticated balance/upload/paid operations.

The public payment-provider invoice flow remains owned by EPIC #7. Happy Fox does not fake a top-up or mutate balances from the browser when that flow is not configured.

See [`docs/miniapp.md`](docs/miniapp.md).

### Telegram product shell

- main menu for image/video creation and planned product sections;
- Quick Start from the main menu;
- photo/video sent with no active FSM is accepted as a reference entrypoint;
- user chooses whether to create an image or a video from the received reference;
- user-friendly image/video screen FSM with model-specific dynamic settings;
- Redis-backed FSM with back/cancel/menu, invalid-input handling, stale callback recovery and TTL expiry;
- `/start` and `/menu` are global first-priority interrupts and clear every active generation screen plus known temporary inputs;
- Redis event isolation serializes concurrent updates for one FSM key;
- Telegram albums are rejected before upload;
- private local storage for Telegram reference files;
- server-authorized `/admin` panel with privileged extension callbacks registered ahead of broad fallbacks.

### Generation and provider lifecycle

- typed KIE.ai provider registry and strict model contracts;
- free local model validation before paid admission;
- fail-closed trusted internal task API;
- mandatory user identity and `Idempotency-Key` for paid requests;
- Redis rate limits plus PostgreSQL per-user/global active-generation limits;
- atomic generation + billing reservation + immutable ledger + outbox admission;
- worker claiming through `FOR UPDATE SKIP LOCKED`;
- exactly-one-attempt boundary for billable `createTask` submission;
- `submission_unknown` instead of unsafe automatic provider resubmission;
- HMAC-verified callback inbox plus polling fallback;
- explicit durable lifecycle through processing, result storage and delivery;
- partial media archive retry, dead-letter state and reconciliation;
- SSRF-resistant result download and private S3-compatible archive;
- duplicate-safe Telegram delivery with explicit `delivery_unknown` state.

### Billing

- integer internal credits; no floating-point wallet arithmetic;
- versioned model prices;
- materialized wallet accounts backed by an append-only ledger;
- atomic reserve/capture/release/refund lifecycle;
- deterministic idempotency for balance adjustments and settlement;
- reconciliation across generation, reservation, media, outbox and delivery state.

### Administrative control plane

FoxGen has one administrative domain layer exposed through the registered Telegram `/admin`, signed backend HTTP API and internal operator web surface. Happy Fox is a separate public transport surface and cannot use administrative credentials.

Registered/current capabilities include:

- server-side RBAC policy and bootstrap/durable admin identity model;
- direct admin identity/role/scope management through signed/private web transports;
- dedicated admin analytics and privileged generation preview;
- user lookup, block/unblock and balance adjustment;
- generation, operation, payment and finance inspection;
- payment recheck/reprocess with double-credit protection;
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

Every admin write is server-authorized. Signed HTTP admin requests are network allowlisted and use HMAC-SHA256 over the exact raw body. Destructive or expensive actions require explicit confirmation. The operator-web extension router is registered before the generic `/api/{section}` route so dedicated analytics/admin endpoints cannot be shadowed.

## Architecture at a glance

```text
Telegram bot ────────────────┐
Happy Fox Mini App ──────────┼──> FastAPI
Trusted internal clients ────┤      ├── shared paid generation admission
Telegram /admin ─────────────┤      ├── registered signed internal admin API
                             │      └── provider callbacks
                             │
                             v
                      Application services
                      ├── submissions
                      ├── generation lifecycle
                      ├── billing
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
          ├── provider submission/polling
          ├── callback processing
          ├── archive/delivery
          └── admin/support/campaign work
```

Happy Fox is transport only: Telegram identity validation and owner-scoped projection happen at the API edge, while paid work continues through existing application/domain services.

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

The billable provider POST is never automatically replayed. A lost provider response moves the local task into an ambiguity state that must converge through callback, polling or evidence-based operator reconciliation.

## Local development

```bash
cp .env.example .env
# Fill only the secrets needed for the feature you are testing.
docker compose up --build
```

Local Compose provides PostgreSQL, Redis, MinIO, migrations, API, worker and bot. Telegram/Mini App temporary input files are stored in a private shared volume mounted into `bot` and `api`; generated result archives remain in MinIO. MinIO bootstrap creates the private results bucket when needed, installs the short-retention `inputs/` lifecycle rule for S3-backed deployments, verifies it and gates API/worker/bot startup. MinIO ports are exposed for development only.

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

A test wallet also needs an active model price and enough credits before Telegram or Happy Fox can launch a paid task.

See [`docs/development.md`](docs/development.md) and [`docs/miniapp.md`](docs/miniapp.md).

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

Happy Fox adds:

```text
POST   /v1/miniapp/auth
GET    /v1/miniapp/bootstrap
GET    /v1/miniapp/generations
GET    /v1/miniapp/generations/{id}
POST   /v1/miniapp/generations/{id}/cancel
POST   /v1/miniapp/tasks
POST   /v1/miniapp/input-media
DELETE /v1/miniapp/input-media/{storage_key}
```

Billing/generation operator routes and the **registered** signed `/internal/admin/*` surface are documented in [`docs/api-reference.md`](docs/api-reference.md). Happy Fox security/transport details are in [`docs/miniapp.md`](docs/miniapp.md).

Never place internal API tokens, admin HMAC keys, billing credentials or object-storage credentials in Telegram clients, browsers or a public Mini App.

## Quality and CI

The reproducible CI pipeline uses the exact dependency lock and checks:

- Ruff lint;
- Ruff formatting gate;
- strict mypy;
- pytest with coverage threshold;
- real PostgreSQL and Redis integration tests;
- Alembic upgrade, current-head verification and downgrade/re-upgrade;
- API readiness smoke test;
- Gitleaks;
- dependency review;
- Trivy filesystem/image scans;
- Docker Compose validation;
- deterministic production image build/import smoke test.

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

Production Compose runs a fail-closed `minio-init` bootstrap before API/worker/bot startup. It preserves unrelated bucket rules, installs and reads back the short-retention `inputs/` rule, and never targets durable `generations/` results. External S3-compatible topologies must provide equivalent lifecycle enforcement themselves.

For Happy Fox, the public reverse proxy serves `/mini-app/` and `/v1/miniapp/*`; `/internal/admin/*` remains private. Configure the Telegram Main Mini App URL to the public HTTPS `/mini-app/` URL after deploying the tested SHA.

See:

- [`docs/production-deploy.md`](docs/production-deploy.md)
- [`docs/miniapp.md`](docs/miniapp.md)
- [`docs/minio-lifecycle-runbook.md`](docs/minio-lifecycle-runbook.md)
- [`docs/github-environment-setup.md`](docs/github-environment-setup.md)
- [`docs/operations-runbook.md`](docs/operations-runbook.md)
- [`docs/known-limitations.md`](docs/known-limitations.md)

## Documentation index

Start with [`docs/README.md`](docs/README.md). It maps architecture, schema, configuration, API, Happy Fox, Telegram FSM, model contracts, billing, admin, security, CI, deployment, reconciliation and operations.

## Source-of-truth rules

- runtime behavior/reachability: registered code paths + tests;
- database schema: Alembic migrations + SQLAlchemy models;
- model provider IDs/payload contracts: reviewed provider registry/contracts + tests;
- application environment variables: `foxgen.core.config.Settings`, `.env.example`, `deploy/production.env.example`;
- infrastructure bootstrap variables: Compose/scripts plus the same env examples and `docs/configuration.md`;
- deploy behavior: `.github/workflows/`, `docker-compose.prod.yml`, `scripts/deploy-production.sh`;
- current limitations: `docs/known-limitations.md` plus open tracked issue/PR state.

If documentation disagrees with executable code or migrations, treat executable state as authoritative and correct the documentation in the same PR.

## Repository workflow

Read [`AGENTS.md`](AGENTS.md) before automated changes. Changes to behavior, APIs, schema, provider contracts, security or deployment must update relevant documentation and tests in the same PR.
