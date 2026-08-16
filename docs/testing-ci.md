# Testing and CI

FoxGen CI tests executable production assumptions rather than only mocked Python units. Dependency versions are resolved into `requirements.lock`; the production image installs that exact lock without re-resolving broad dependency ranges.

## Local environment

Recommended Python: 3.12.

```bash
python -m pip install --requirement requirements.lock
python -m pip install --no-deps --editable .
python -m pip check
```

`requirements.lock` contains runtime and development tooling used by CI. `scripts/check_lock.py` verifies lock coverage.

## Make targets

```bash
make install
make lock
make lock-check
make lint
make format
make typecheck
make test
make coverage
make ci
make up
make down
make migrate
```

Local `make ci` is stricter about formatting the whole repository than the pull-request changed-file gate.

## Coverage

Coverage is configured in `pyproject.toml` with branch coverage and repository floor `fail_under = 55`. High-risk financial/provider paths still require explicit behavior, concurrency and cross-layer tests even when aggregate coverage passes.

## Unit/contract expectations

Core regression areas include provider contracts, webhook normalization, submission/idempotency, Telegram FSM, billing/ledger, lifecycle transitions, retries/dead letters, media safety, admin HMAC/RBAC/confirmation and deploy contracts.

Stars unit/API coverage keeps owner-bound package/invoice access, pre-checkout fail-closed behavior, duplicate successful-payment exactly-once settlement, refund route security and sender failure classification.

Promo unit/API coverage keeps:

- Mini App JWT owner binding;
- trusted user route owner-header binding;
- browser payload restricted to `code` rather than reward/limit values;
- Happy Fox promo asset/auth/API contract.

## Real infrastructure integration tests

The infrastructure job runs PostgreSQL 17 and Redis 7 with:

```text
FOXGEN_RUN_INTEGRATION=1
FOXGEN_RUN_E2E=1
```

Integration coverage includes paid admission, Redis FSM/event behavior, provider lifecycle persistence, admin financial replay, support/campaign outboxes, Stars payment/refund recovery and promo redemption concurrency.

Stars refund integration proves local CREDIT hold before provider call, duplicate-command safety, one provider call on success, ambiguity -> `refund_unknown`, evidence-based restore and no double restore.

Promo integration proves:

- two concurrent same-user redeems converge to one financial grant and one replay;
- exactly one `(promo_code,user_id)` redemption row exists;
- exactly one deterministic `promo-credit:<CODE>:<user-id>` ledger entry exists;
- `promo_codes.uses` increments once;
- `max_uses=1` rejects another user before wallet/redemption creation;
- row locking and durable uniqueness jointly protect the global use limit.

## Cross-layer E2E

`tests/e2e` is required in the real-infrastructure job, after integration and before API readiness/container build.

### Stars payment/refund E2E

```text
Happy Fox JWT
  -> Stars package/invoice HTTP
  -> trusted pre_checkout / successful_payment HTTP
  -> real CREDIT/ledger settlement
  -> signed HMAC admin refund HTTP
  -> CREDIT hold + refund-attempt persistence
  -> dedicated PaymentRefundWorker
  -> fake external Telegram refund adapter only
  -> refunded order/payment + ledger assertions
```

The only fake is the external Telegram network adapter; FoxGen auth/routing/services/PostgreSQL/idempotency/worker state are real.

### Promo redemption E2E

```text
signed HMAC admin
  -> POST /internal/admin/promos
  -> durable server-owned reward/max_uses policy
Happy Fox JWT user
  -> POST /v1/miniapp/promos/redeem
  -> real wallet + immutable promo ledger + redemption + uses
  -> duplicate redeem returns replay, no second credit
trusted second user
  -> exhausted promo rejection
  -> no second-user wallet/redemption
```

This E2E uses real FastAPI authentication/routing, AdminServices, billing/promo services and PostgreSQL state. No external provider is required for the promo path.

Normal CI must not call live Telegram payment/refund APIs because that would require production-like credentials and nondeterministic financial state.

## Migration gate

CI performs:

```text
alembic upgrade head
alembic current --check-heads
critical schema smoke verification
alembic downgrade -1
alembic upgrade head
head/schema verification again
```

This catches migration syntax/metadata drift. New financial/audit tables such as `payment_refund_attempts` and `promo_redemptions` must also be imported into Alembic metadata and listed in schema smoke.

## API readiness smoke

After migrations, integration and E2E, CI starts the API against real PostgreSQL/Redis and requires `GET /health/ready` to converge.

Infrastructure diagnostics upload integration logs/XML, E2E logs/XML and API logs.

## Standard CI jobs

### Quality

- exact lock + `pip check`;
- Ruff lint;
- changed-file Ruff format gate;
- strict mypy;
- pytest with coverage/XML.

### Real infrastructure

- PostgreSQL/Redis services;
- Alembic upgrade/schema/downgrade/re-upgrade;
- integration tests;
- required cross-layer E2E;
- API readiness;
- diagnostic artifacts.

### Security/dependency

Dependency review is advisory on pull requests. Gitleaks scans secrets. Trivy scans filesystem dependencies/configuration for configured HIGH/CRITICAL classes.

### Container/Compose gate

Container build depends on quality, infrastructure, security and secret-scan success. A failed E2E blocks production image build in the main CI workflow.

The gate validates development/production Compose, deploy shell assets, deterministic production image import and image vulnerability scan.

## Test layering

Use the smallest layer that proves an invariant:

- unit — deterministic helper;
- service — policy/idempotency;
- API — auth/transport;
- FSM/UI contract — Telegram/Mini App routing/wiring;
- integration — real PostgreSQL/Redis transaction/lock/uniqueness;
- E2E — multiple real internal layers joined through public/trusted/admin boundaries;
- Compose/image smoke — production wiring;
- controlled live provider smoke — only when explicitly credentialed/budgeted.

Do not turn normal CI into billable KIE/Telegram financial provider tests.

## Admin security requirements

Admin changes preserve negative tests for invalid HMAC, stale timestamp, network denial, changed raw body, missing idempotency/confirmation, changed payload under same key and ordinary-user denial.

## Financial safety requirements

A change touching money or external/provider/commercial state needs tests demonstrating relevant invariants, including:

- duplicate paid admission cannot bill twice;
- payment reprocess cannot double-credit;
- Stars refund cannot contact Telegram before CREDIT hold commits;
- refund ambiguity cannot silently restore/lose CREDIT;
- promo client cannot choose reward amount;
- duplicate promo redemption cannot grant twice or increment uses twice;
- `max_uses` is safe under concurrency;
- exhausted/inactive promo fails before wallet mutation;
- delivery/provider ambiguity cannot be guessed away.

## CI failure triage

1. identify the first real failing step;
2. distinguish runner/service failure from code/test failure;
3. use uploaded logs/artifacts rather than guessing;
4. fix the invariant, not the gate;
5. rerun the affected head SHA;
6. merge only when full required CI and review gates are clean.

## Workflow/deployment relationship

PR CI does not deploy. After merge/push, the `main` CI run must also succeed before the protected production workflow can act.

See `production-deploy.md` and `user-promos.md`.
