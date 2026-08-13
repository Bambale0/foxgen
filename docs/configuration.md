# Configuration reference

FoxGen configuration is defined by `foxgen.core.config.Settings`. All variables use the `FOXGEN_` prefix. Empty optional values from `.env` are ignored by pydantic-settings.

This document groups settings by responsibility. Exact validation ranges remain enforced by the `Settings` model. A declared setting is not assumed to be operational unless runtime code consumes it; reserved/inactive settings are called out explicitly.

## Runtime

| Variable | Default | Purpose |
|---|---:|---|
| `FOXGEN_ENV` | `local` | `local`, `test`, `staging` or `production` |
| `FOXGEN_LOG_LEVEL` | `INFO` | Application log level |
| `FOXGEN_API_HOST` | `0.0.0.0` | FastAPI bind address inside the container |
| `FOXGEN_API_PORT` | `8080` | FastAPI container port |

## Telegram

| Variable | Default | Purpose |
|---|---:|---|
| `FOXGEN_TELEGRAM_BOT_TOKEN` | empty | Bot credential; required to run `foxgen-bot` |
| `FOXGEN_TELEGRAM_FSM_TTL_SECONDS` | `3600` | Redis state/data TTL |
| `FOXGEN_TELEGRAM_INPUT_MAX_BYTES` | `52428800` | Maximum accepted input upload size |
| `FOXGEN_TELEGRAM_INPUT_PRESIGNED_URL_TTL_SECONDS` | `21600` | Provider-readable URL lifetime for stored input references |

Telegram input objects are private. See `input-media-lifecycle.md` for cleanup requirements.

## PostgreSQL and Redis

| Variable | Default/local example | Purpose |
|---|---|---|
| `FOXGEN_DATABASE_URL` | PostgreSQL async URL | Durable source of truth |
| `FOXGEN_REDIS_URL` | Redis URL | FSM, event isolation, rate limits and locks |

Production Compose also uses `FOXGEN_POSTGRES_DB`, `FOXGEN_POSTGRES_USER`, `FOXGEN_POSTGRES_PASSWORD` and `FOXGEN_REDIS_PASSWORD` for infrastructure containers. Keep those credentials consistent with the application URLs.

## Internal generation API

| Variable | Default | Purpose |
|---|---:|---|
| `FOXGEN_INTERNAL_API_BASE_URL` | `http://localhost:8080` | Bot/trusted-service API origin |
| `FOXGEN_INTERNAL_API_TIMEOUT_SECONDS` | `30` | Trusted internal client timeout |
| `FOXGEN_TASK_SUBMISSION_ENABLED` | `false` | Master paid-submission gate |
| `FOXGEN_INTERNAL_API_TOKEN` | empty | Bearer secret for paid submission/balance reads |
| `FOXGEN_SUBMISSION_USER_RATE_LIMIT_PER_MINUTE` | `10` | Per-user Redis admission limit |
| `FOXGEN_SUBMISSION_GLOBAL_RATE_LIMIT_PER_MINUTE` | `100` | Global Redis admission limit |
| `FOXGEN_SUBMISSION_USER_CONCURRENCY_LIMIT` | `2` | Active durable generations per user |
| `FOXGEN_SUBMISSION_GLOBAL_CONCURRENCY_LIMIT` | `20` | Active durable generations globally |

Paid admission is intentionally fail-closed. Enabling the switch without the token, active price, wallet funds, provider key or production-ready model does not bypass those checks.

## KIE.ai

| Variable | Default | Purpose |
|---|---:|---|
| `FOXGEN_KIE_API_KEY` | empty | Provider API credential |
| `FOXGEN_KIE_BASE_URL` | `https://api.kie.ai` | KIE API origin |
| `FOXGEN_KIE_CALLBACK_BASE_URL` | empty | Public HTTPS origin used to construct `/webhooks/kie` |
| `FOXGEN_KIE_WEBHOOK_HMAC_KEY` | empty | Dedicated callback verification secret |
| `FOXGEN_WEBHOOK_MAX_AGE_SECONDS` | `300` | Allowed callback timestamp/replay window |

Do not reuse the KIE API key as a webhook, internal API or admin secret.

## Legacy billing-admin API

| Variable | Default | Purpose |
|---|---:|---|
| `FOXGEN_BILLING_ADMIN_API_ENABLED` | `false` | Enables legacy `/v1/admin/*` billing/reconciliation controls |
| `FOXGEN_BILLING_ADMIN_API_TOKEN` | empty | Separate credential for those routes |

The full administrative control plane uses its own HMAC/RBAC security and does not replace the need to protect any legacy billing route that remains enabled.

## Full administrative control plane

| Variable | Default | Purpose |
|---|---:|---|
| `FOXGEN_ADMIN_API_ENABLED` | `false` | Enables signed `/internal/admin/*` API |
| `FOXGEN_ADMIN_WEB_ENABLED` | `false` | Enables backend-only `/internal/admin/ui` operator surface |
| `FOXGEN_ADMIN_HMAC_KEY` | empty | Dedicated HMAC-SHA256 secret |
| `FOXGEN_ADMIN_HMAC_MAX_SKEW_SECONDS` | `300` | Maximum request timestamp skew |
| `FOXGEN_ADMIN_NETWORK_ALLOWLIST` | loopback | Comma-separated source CIDRs |
| `FOXGEN_ADMIN_SUPERUSER_IDS` | empty | Comma-separated bootstrap admin IDs |
| `FOXGEN_ADMIN_SESSION_TTL_SECONDS` | `900` | Short operator web session TTL |
| `FOXGEN_ADMIN_WORKER_BATCH_SIZE` | `50` | Admin/support/campaign worker batch |
| `FOXGEN_ADMIN_WORKER_LEASE_SECONDS` | `120` | Admin work lease |
| `FOXGEN_ADMIN_WORKER_MAX_ATTEMPTS` | `8` | Retry budget |
| `FOXGEN_ADMIN_NOTIFICATION_RATE_PER_SECOND` | `20` | Campaign delivery rate limit |

Production should use the narrowest practical backend CIDR. Never use `0.0.0.0/0` as a workaround. Bootstrap IDs are for initial access; durable administrators belong in `admin_users`.

## Generation worker

| Variable | Default | Purpose |
|---|---:|---|
| `FOXGEN_WORKER_LOOP_INTERVAL_SECONDS` | `1` | Main worker idle interval |
| `FOXGEN_WORKER_OUTBOX_BATCH_SIZE` | `10` | Generation outbox claim batch |
| `FOXGEN_WORKER_OUTBOX_LEASE_SECONDS` | `120` | Claim lease |
| `FOXGEN_WORKER_OUTBOX_MAX_ATTEMPTS` | `8` | Safe-work retry budget |
| `FOXGEN_PROVIDER_POLL_INTERVAL_SECONDS` | `20` | Provider polling cadence |
| `FOXGEN_STALE_SUBMITTING_SECONDS` | `600` | Watchdog threshold before `submission_unknown` |

The worker retry budget does not authorize a second billable provider POST. Provider submission has separate single-attempt semantics.

## Result media

| Variable | Default | Purpose |
|---|---:|---|
| `FOXGEN_MEDIA_DOWNLOAD_TIMEOUT_SECONDS` | `60` | Provider result download timeout |
| `FOXGEN_MEDIA_MAX_BYTES` | `536870912` | Maximum archived result object size |
| `FOXGEN_MEDIA_PRESIGNED_URL_TTL_SECONDS` | `3600` | Telegram delivery URL lifetime |

## S3-compatible storage

| Variable | Default | Purpose |
|---|---|---|
| `FOXGEN_S3_ENDPOINT_URL` | empty | S3/MinIO endpoint |
| `FOXGEN_S3_REGION` | `us-east-1` | Region |
| `FOXGEN_S3_BUCKET` | `foxgen-media` | Private bucket name; application storage expects it to exist |
| `FOXGEN_S3_ACCESS_KEY_ID` | empty | Storage credential |
| `FOXGEN_S3_SECRET_ACCESS_KEY` | empty | Storage credential |
| `FOXGEN_S3_FORCE_PATH_STYLE` | `true` | Compatibility switch for MinIO/S3 implementations |
| `FOXGEN_S3_CREATE_BUCKET` | `false` | **Reserved/inactive in current runtime.** Declared by `Settings` but not consumed by `S3MediaStorage`; setting it to `true` does not create a bucket. Tracked by issue #57. |

Current `S3MediaStorage` writes/reads the configured bucket and can health-check it, but it does not perform application-level bucket creation. Local/production MinIO Compose bootstrap ensures its configured bucket exists; deployments using an external S3-compatible endpoint must provision the private bucket separately.

Do not depend on `FOXGEN_S3_CREATE_BUCKET=true` for production provisioning until #57 is explicitly implemented or the setting is removed.

Local `.env.example` contains development MinIO credentials. They are forbidden in production; `scripts/deploy-production.sh` rejects known development secrets.

Temporary input lifecycle is a separate concern: even an existing bucket still needs the externally configured `inputs/` lifecycle rule described in `input-media-lifecycle.md` until issue #50 is resolved.

## Production-only Compose variables

`deploy/production.env.example` also documents:

- `FOXGEN_PUBLIC_API_PORT` — loopback host port exposed to the reverse proxy;
- PostgreSQL/Redis infrastructure credentials;
- the same application/provider/admin/storage settings listed above.

The production API is bound to host loopback by Compose. PostgreSQL, Redis and MinIO have no public host ports.

## Secret separation

Use independent random secrets for:

1. `FOXGEN_INTERNAL_API_TOKEN`;
2. `FOXGEN_KIE_WEBHOOK_HMAC_KEY`;
3. `FOXGEN_BILLING_ADMIN_API_TOKEN` if enabled;
4. `FOXGEN_ADMIN_HMAC_KEY`;
5. PostgreSQL password;
6. Redis password;
7. S3 access credentials.

Do not commit `.env`. Do not place any of these secrets in Telegram messages, public frontend code, Mini App JavaScript, audit payloads or support content.

## Configuration rollout rule

When adding/changing a setting, update together:

- `src/foxgen/core/config.py`;
- every runtime consumer of the setting;
- `.env.example`;
- `deploy/production.env.example` when production-relevant;
- this document;
- Compose/deploy validation if the setting changes container wiring.

A setting is not considered operational merely because it exists in `Settings`; documentation must reflect whether executable code actually consumes it.