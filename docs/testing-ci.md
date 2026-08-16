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

Coverage is configured in `pyproject.toml` with branch coverage and repository floor `fail_under = 55`. High-risk financial/provider paths still require explicit behavior and cross-layer tests even when aggregate coverage passes.

## Unit/contract expectations

Core regression areas include provider contracts, webhook normalization, submission/idempotency, Telegram FSM, billing/ledger, lifecycle transitions, retries/dead letters, media safety, admin HMAC/RBAC/confirmation and production deploy contracts.

For Telegram Stars specifically, unit/API coverage must keep:

- owner-bound package/invoice access;
- pre-checkout fail-closed behavior;
- duplicate successful-payment exactly-once settlement;
- signed/confirmed admin refund route contracts;
- refund sender classification for deterministic vs ambiguous provider outcomes.

## Real infrastructure integration tests

The infrastructure job runs PostgreSQL 17 and Redis 7 with:

```text
FOXGEN_RUN_INTEGRATION=1
FOXGEN_RUN_E2E=1
```

Integration coverage includes atomic paid admission, Redis FSM/event behavior, provider lifecycle persistence, admin financial replay, support/campaign outboxes and payment/refund recovery.

Stars refund integration explicitly proves:

- CREDIT is removed before the provider refund worker runs;
- duplicate admin refund command does not append a second debit;
- one refund attempt causes one provider call on the success path;
- ambiguous provider outcome becomes `refund_unknown` with CREDIT still held;
- evidence `not_refunded` restores CREDIT through one unique compensating ledger entry;
- replaying the same resolution does not restore twice.

## Cross-layer E2E

`tests/e2e` is an explicit required layer in the same real-infrastructure CI job, after integration tests and before API readiness/container build.

Current payment E2E executes:

```text
Happy Fox JWT
  -> GET Stars packages over ASGI HTTP
  -> POST durable invoice over ASGI HTTP
  -> trusted pre_checkout HTTP
  -> trusted successful_payment HTTP
  -> real PostgreSQL CREDIT/ledger settlement
  -> signed HMAC admin refund HTTP
  -> real CREDIT hold + refund-attempt persistence
  -> dedicated PaymentRefundWorker
  -> fake external Telegram refund adapter only
  -> refunded order/payment + immutable ledger assertions
```

The E2E deliberately fakes only the external Telegram network call. FoxGen HTTP routing/auth, application services, PostgreSQL transactions, idempotency, admin signature verification and worker state transitions are real.

Normal CI must not call live Telegram payment/refund APIs because that would require production-like credentials and nondeterministic external financial state.

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

This catches migration syntax/metadata drift. It does not make every production downgrade operationally safe; refund-state rollback constraints remain a runbook concern.

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

Container build depends on quality, infrastructure, security and secret-scan success. Therefore a failed E2E blocks production image build in the main CI workflow.

The gate validates development/production Compose, deploy shell assets, deterministic production image import and image vulnerability scan.

## Test layering

Use the smallest layer that proves an invariant:

- unit — deterministic helper;
- service — policy/idempotency;
- API — auth/transport;
- FSM — Telegram routing/state;
- integration — real PostgreSQL/Redis transaction/lock/uniqueness;
- E2E — multiple real internal layers joined through public/trusted/admin boundaries;
- Compose/image smoke — production wiring;
- controlled live provider smoke — only when explicitly credentialed/budgeted.

Do not turn normal CI into billable KIE/Telegram financial provider tests.

## Admin security requirements

Admin changes preserve negative tests for invalid HMAC, stale timestamp, network denial, changed raw body, missing idempotency/confirmation, changed payload under same key and ordinary-user denial.

## Billing/provider safety requirements

A change touching money or external provider side effects needs tests demonstrating relevant invariants, including:

- duplicate paid admission cannot bill twice;
- createTask ambiguity cannot blindly resubmit;
- payment reprocess cannot double-credit;
- Stars refund cannot contact Telegram before CREDIT hold commits;
- insufficient CREDIT cannot enter refund provider side effects;
- successful refund leaves one final debit;
- deterministic refund rejection restores once;
- ambiguous refund keeps the hold until evidence;
- evidence resolution cannot double-restore;
- delivery ambiguity cannot auto-resend.

## CI failure triage

1. identify the first real failing step;
2. distinguish runner/service failure from code/test failure;
3. use uploaded logs/artifacts rather than guessing;
4. fix the invariant, not the gate;
5. rerun the affected head SHA;
6. merge only when full required CI and review gates are clean.

## Workflow/deployment relationship

PR CI does not deploy. After merge/push, the `main` CI run must also succeed before the protected production workflow can act.

See `production-deploy.md`.
