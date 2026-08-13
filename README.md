# FoxGen

FoxGen is a Telegram-first multimodal AI generation platform built on Python 3.12, FastAPI, aiogram 3, PostgreSQL, Redis, S3-compatible object storage and KIE.ai.

This README describes the code currently present in `main`. The public Mini App is intentionally treated as a separate product surface and is not documented as implemented here.

## What is implemented

### Telegram product shell

- main menu for image/video creation and planned product sections;
- Quick Start from the main menu;
- photo/video sent with no active FSM is accepted as a reference entrypoint;
- user chooses whether to create an image or a video from the received reference;
- compatible model selection and model-specific settings;
- Redis-backed FSM with back/cancel/menu, invalid-input handling, stale callback recovery and TTL expiry;
- Redis event isolation serializes concurrent updates for one FSM key;
- Telegram albums are rejected before upload;
- private object storage for Telegram reference files;
- `/admin` server-authorized administrative panel.

### Generation and provider lifecycle

- typed KIE.ai provider registry and model contracts;
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

FoxGen has one administrative domain layer exposed through Telegram `/admin`, a signed backend HTTP API and an internal operator web surface. The public Mini App is not part of this implementation.

Implemented capabilities include:

- RBAC roles/scopes and bootstrap superadmins;
- user lookup, block/unblock and balance adjustment;
- generation, operation, payment and finance inspection;
- payment recheck/reprocess with double-credit protection;
- versioned tariff publishing;
- partner analytics and withdrawal actions;
- promo management;
- prompt-library moderation;
- runtime flags and model availability without deployment;
- support tickets and durable support outbox;
- versioned CMS documents;
- notification preview/campaign create/test/start/cancel;
- durable campaign deliveries, retries and rate limiting;
- trends/feed moderation backend actions;
- privileged generation preview;
- audit browsing and read-only AI diagnostics;
- append-only admin command ledger with request/result snapshots and idempotent replay.

Every admin write is server-authorized. Signed HTTP admin requests are network allowlisted and use HMAC-SHA256 over the exact raw body. Destructive or expensive actions require explicit confirmation.

## Architecture at a glance

```text
Telegram bot ────────────────┐
                            │
Trusted internal clients ───┼──> FastAPI
                            │      ├── paid generation admission
Telegram /admin ────────────┤      ├── signed internal admin API
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
# Fill required secrets for the features you are testing.
docker compose up --build
```

Local Compose provides PostgreSQL, Redis, MinIO, migrations, API, worker and bot. MinIO ports are exposed for development only.

Paid provider submission remains disabled until explicitly enabled:

```env
FOXGEN_TASK_SUBMISSION_ENABLED=true
FOXGEN_INTERNAL_API_TOKEN=<dedicated-internal-secret>
FOXGEN_KIE_API_KEY=<kie-key>
```

A test wallet also needs an active model price and enough credits before Telegram confirmation can launch a paid task.

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

Billing/generation operator routes and the full signed `/internal/admin/*` surface are documented in [`docs/api-reference.md`](docs/api-reference.md).

Never place internal API tokens, admin HMAC keys, billing credentials or object-storage credentials in Telegram clients, browsers or a public Mini App.

## Quality and CI

The reproducible CI pipeline uses the exact dependency lock and checks:

- Ruff lint;
- Ruff formatting for changed Python files;
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

See:

- [`docs/production-deploy.md`](docs/production-deploy.md)
- [`docs/github-environment-setup.md`](docs/github-environment-setup.md)
- [`docs/operations-runbook.md`](docs/operations-runbook.md)

## Documentation index

Start with [`docs/README.md`](docs/README.md). It maps architecture, API, Telegram FSM, model contracts, billing, admin, deployment, reconciliation and operational documentation.

## Source-of-truth rules

- runtime behavior: code + tests;
- database schema: Alembic migrations + SQLAlchemy models;
- model provider IDs and payload contracts: reviewed provider registry/contracts + tests;
- environment variables: `foxgen.core.config.Settings`, `.env.example`, `deploy/production.env.example`;
- deploy behavior: `.github/workflows/`, `docker-compose.prod.yml`, `scripts/deploy-production.sh`;
- admin capability contract: `docs/admin-capability-matrix.md` and the current admin service/API implementation.

If documentation disagrees with executable code or migrations, treat the executable source as authoritative and update the documentation in the same PR.

## Repository workflow

Read [`AGENTS.md`](AGENTS.md) before automated changes. Changes to behavior, APIs, schema, provider contracts, security or deployment must update the relevant documentation and tests in the same PR.