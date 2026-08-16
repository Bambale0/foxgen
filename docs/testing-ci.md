# Testing and CI

FoxGen CI is designed to test executable production assumptions rather than only mocked Python units. Dependency versions are resolved into `requirements.lock`; the production image installs that exact lock without re-resolving broad dependency ranges.

## Local environment

Recommended Python: 3.12.

Install the exact lock and local package:

```bash
python -m pip install --requirement requirements.lock
python -m pip install --no-deps --editable .
python -m pip check
```

`requirements.lock` contains runtime and development tooling used by CI. `scripts/check_lock.py` verifies that the lock still covers the dependency declarations expected by the project.

## Make targets

```bash
make install      # exact lock + editable local package
make lock         # regenerate requirements.lock with pinned pip-tools
make lock-check   # validate lock coverage
make lint         # ruff check + full local format check
make format       # format and auto-fix lint where supported
make typecheck    # strict mypy over src
make test         # pytest
make coverage     # pytest + coverage report
make ci           # lock-check + lint + typecheck + coverage
make up           # docker compose up --build
make down
make migrate      # alembic upgrade head
```

Local `make ci` is stricter about formatting the whole repository than the pull-request changed-file formatting gate. New/modified Python files should always be formatter-clean.

## Coverage

Coverage is configured in `pyproject.toml` with branch coverage and a repository threshold:

```text
fail_under = 55
```

The threshold is a floor, not a target. High-risk paths need explicit behavior tests even when aggregate coverage already passes.

## Unit/contract coverage expectations

Core regression areas include:

- provider model contract validation;
- provider webhook verification/normalization;
- submission/idempotency behavior;
- Telegram FSM transitions/recovery/event isolation;
- billing price/wallet/ledger behavior;
- lifecycle transition graph;
- retry/dead-letter/reconciliation behavior;
- media storage/download safety;
- admin HMAC/network/RBAC/confirmation/redaction;
- admin validation/idempotency;
- Telegram `/admin` authorization;
- backend operator-web authorization;
- production deploy exact-image/reload/smoke ordering and bounded Happy Fox convergence deadlines.

## Real infrastructure integration tests

The CI infrastructure job runs PostgreSQL 17 and Redis 7 service containers and sets:

```text
FOXGEN_RUN_INTEGRATION=1
```

It executes the integration suite against real services rather than replacing database/Redis behavior with mocks.

Covered integration classes include:

- atomic generation admission/reservation;
- Redis FSM/event behavior;
- provider callback/lifecycle persistence;
- admin balance adjustment replay without double credit;
- support reply durable outbox;
- campaign recipient materialization once;
- payment reprocess double-credit prevention;
- safe admin operation replay;
- blocked-user rejection at transactional paid admission.

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

The purpose is to catch migration syntax/metadata drift and ensure the newest migration can participate in the expected rollback/re-upgrade test path.

This does not guarantee every production downgrade is operationally safe. Data-retention decisions still belong in the release/rollback runbook.

## API readiness smoke

After migrations/integration tests, CI starts the API against the real PostgreSQL/Redis services and polls:

```text
GET /health/ready
```

An API process that exits early or never becomes ready fails the infrastructure job. Logs/integration diagnostics are uploaded as workflow artifacts.

## Standard CI jobs

The main CI workflow includes these major gates.

### Quality

- exact lock installation;
- `pip check`;
- lock validation;
- Ruff lint;
- changed-Python-file Ruff format gate on PR/push diff;
- strict mypy;
- pytest with coverage and XML report.

### Real infrastructure

- PostgreSQL/Redis service startup;
- Alembic migration checks;
- real integration tests;
- API readiness smoke;
- diagnostic artifacts.

### Dependency review

Dependency review runs on pull requests as advisory review with configured severity policy.

### Secret scanning

Gitleaks scans repository history/content in CI. Never use this as permission to commit a secret temporarily; rotate any credential that ever reaches Git history.

### Filesystem security scanning

Trivy scans repository dependencies/configuration for configured HIGH/CRITICAL classes.

### Container/Compose gate

After quality/infrastructure/security prerequisites:

- validate development Compose;
- validate production Compose/deploy script assets;
- run deploy contract tests that require non-interactive one-shot Compose commands, exact-image assertions and 30-second elapsed-time Happy Fox/Telegram convergence windows rather than unbounded fixed retry multiplication;
- build deterministic production image;
- load/import smoke test;
- scan the built image with Trivy.

The public Happy Fox and Telegram API checks themselves remain production deploy gates rather than CI network calls. CI verifies their shell contract and bounded timing semantics without depending on live production ingress or Telegram credentials.

## Production image

The Dockerfile pins the Python patch-level base image used by the current reproducible build baseline and installs `requirements.lock` before installing FoxGen without dependency resolution.

The same application image is used with different commands for API, worker, bot and migration/admin-init style jobs. Do not add an image-level healthcheck that assumes every container runs the HTTP API.

## Formatting policy

CI must not silently mutate source and then call the run successful. Ruff checks are non-mutating gates. When formatting fails, fix the branch and rerun.

A new Python file must be both lint-clean and `ruff format` clean before merge.

## Test layering

Use the smallest layer that proves the invariant:

- pure unit test — deterministic validation/state helper;
- service test — use-case policy/idempotency;
- API test — authentication/transport contract;
- FSM test — Telegram routing/state preservation;
- integration test — PostgreSQL/Redis transaction/lock/uniqueness behavior;
- Compose/image smoke — production wiring/import/startup;
- controlled live provider smoke — only when explicitly intended, credentialed and budgeted.

Do not turn normal CI into a billable KIE provider test. Provider-live smoke is separate because it consumes external credentials/budget and is not deterministic.

## Admin security test requirements

Admin changes must preserve negative tests, not only happy paths:

- non-admin `/admin` denial;
- forged callback/FSM continuation denial;
- invalid HMAC;
- stale timestamp;
- source outside allowlist;
- changed raw body after signature;
- missing idempotency on writes;
- idempotency key reused with changed payload;
- missing destructive confirmation;
- sensitive-field redaction;
- forged operator-web action from a regular user.

## Billing/provider safety test requirements

A change touching money or provider submission needs explicit tests that demonstrate:

- duplicate confirmation/admission does not create a second billable generation;
- provider create ambiguity does not trigger another createTask;
- payment reprocess cannot double-credit;
- reservation settlement is idempotent;
- delivery ambiguity does not auto-resend.

## CI failure triage

Recommended order:

1. identify the first real failing job/step;
2. distinguish runner/service initialization failure from code/test failure;
3. use uploaded diagnostics rather than guessing from truncated log excerpts;
4. fix the invariant in code/test/config, not by weakening the gate;
5. rerun the affected commit and wait for the full required pipeline;
6. merge only after the head SHA has a successful CI run and no unresolved blocking review thread.

## Workflow/deployment relationship

The production deploy workflow is downstream of successful `main` CI. A PR CI success alone does not deploy. After merge/push to `main`, the corresponding `main` CI run must succeed before the protected deployment workflow can act.

Once deployment starts, the server-side gates are stricter than CI's API readiness smoke: an enabled Happy Fox rollout must also converge through the public Mini App and Telegram default WebApp menu checks within their bounded wall-clock windows before the script emits the final deployment-completed marker.

See `production-deploy.md`.
