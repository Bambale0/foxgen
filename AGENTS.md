# AGENTS.md — FoxGen repository instructions

## Mission

Build FoxGen as a production-grade Telegram-first multimodal generation platform through small, reviewable changes that preserve billing, provider and delivery safety.

The public Mini App is a separate workstream unless a task explicitly includes it.

## Required discovery before editing

Inspect, at minimum:

1. `README.md` and `docs/README.md`;
2. the current issue/epic and existing open PRs;
3. nearby application/domain/infra code and tests;
4. `foxgen.core.config.Settings`, `.env.example` and production env example when configuration changes;
5. SQLAlchemy models plus Alembic migrations when durable state changes;
6. `.github/workflows/`, Compose and deployment scripts when runtime/deploy behavior changes;
7. provider registry/contracts and official KIE documentation for model changes;
8. `docs/admin-capability-matrix.md` and `docs/admin-control-plane.md` for admin work.

Documentation is part of the implementation. A behavior/API/schema/security/deployment change is incomplete until the relevant docs are updated.

## Architecture rules

- Telegram handlers are transport/orchestration only; reusable business writes belong in services.
- FastAPI routers are transport adapters; shared write logic must not live only in routes.
- PostgreSQL owns durable business state and idempotency.
- Redis owns ephemeral FSM state, event isolation, rate counters, locks and caches.
- S3-compatible storage owns private media bytes; PostgreSQL owns their lifecycle metadata.
- Provider-specific request/response details stay in provider adapters/contracts.
- Every external call has explicit timeout behavior and normalized error handling.

## Generation safety invariants

- Do not invent KIE model IDs, fields or callback payloads.
- A billable provider submission is a non-idempotent boundary and must not be blindly retried.
- `submission_unknown` is resolved through evidence, callback or polling; never by automatic resubmission.
- Telegram delivery becomes non-idempotent once send starts; `delivery_unknown` is not automatically replayed.
- Every paid admission requires authenticated internal caller, user identity, idempotency key, active price and successful atomic reservation.
- Every wallet mutation uses the immutable ledger and transactionally consistent materialized balance.
- Dead-letter/reconciliation fixes must never introduce a second provider charge or duplicate Telegram delivery.

## Telegram FSM rules

Every declared state must define:

- successful next transition;
- invalid-input behavior;
- back;
- cancel/menu;
- timeout/expired state;
- stale callback behavior;
- duplicate/concurrent update behavior.

Reference-prefilled flows must preserve the stored object key across navigation until explicit cleanup/replacement.

## Admin control-plane rules

- `AdminPolicy` is the server-side authorization source for all admin transports.
- Every admin callback/FSM continuation and every HTTP/web action must re-authorize.
- Admin writes go through shared admin services and the append-only command/audit layer.
- Idempotent admin actions replay stored results for the same request and conflict on payload drift.
- Destructive/expensive actions require explicit confirmation.
- Internal admin HTTP uses network allowlist + HMAC-SHA256 over exact raw request bytes.
- Support replies and notification campaigns are worker/outbox side effects, not request-lifecycle sends.
- Never expose internal/admin credentials to a public client.
- Redact token/secret/password/authorization/api_key/webhook/callback data from administrative output.

## Database and migrations

- Never modify an already deployed migration to change production history; add a forward migration.
- State enums/check constraints and application transition graphs must agree.
- Migrations must support CI upgrade + downgrade/re-upgrade smoke checks.
- Append-only ledger/audit invariants must remain enforceable at the database boundary where implemented.

## Testing requirements

Every behavior change needs the narrowest useful regression test plus any affected integration/contract tests.

Before PR merge, CI must cover:

- Ruff;
- formatting gate;
- strict mypy;
- pytest/coverage;
- real PostgreSQL/Redis integration path where relevant;
- migration checks;
- Compose/image validation;
- security scans.

Run `make ci` locally when the environment supports the required dependencies.

## Documentation rules

`docs/README.md` is the documentation map. Keep these documents synchronized with code:

- architecture and state changes → `docs/architecture.md`, `docs/state-gap-audit.md`;
- Telegram behavior → `docs/telegram-flows.md`, `docs/input-media-lifecycle.md`;
- provider/model changes → `docs/model-matrix.md`;
- money/pricing → `docs/billing.md`;
- lifecycle/operator actions → `docs/generation-operations.md`, `docs/postprocessing-reconciliation.md`;
- admin changes → `docs/admin-capability-matrix.md`, `docs/admin-control-plane.md`, `docs/api-reference.md`;
- env changes → `docs/configuration.md` plus env examples;
- CI/deploy changes → `docs/testing-ci.md`, `docs/production-deploy.md`, `docs/github-environment-setup.md`, `docs/operations-runbook.md`.

Do not leave roadmap wording that describes already implemented behavior as future work.

## Delivery

Use conventional commits. PR descriptions must state:

- scope;
- tests/CI;
- migration impact;
- security/operational impact when relevant;
- rollback;
- linked issue/epic.

Do not merge a red CI run or an unresolved safety ambiguity.