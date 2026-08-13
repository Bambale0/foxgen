# Local development

FoxGen development uses Python 3.12 plus Docker Compose for PostgreSQL, Redis and MinIO. This guide covers the repository as implemented on `main`; public Mini App development is a separate workstream.

## Prerequisites

- Python 3.12;
- Docker Engine + Docker Compose plugin;
- Git;
- optional KIE credentials only when intentionally testing provider integration;
- Telegram bot token only when running the bot against Telegram.

## Clone and configure

```bash
git clone https://github.com/Bambale0/foxgen.git
cd foxgen
cp .env.example .env
```

The local example intentionally keeps paid submission and full admin access disabled.

## Install exact Python dependencies

```bash
python -m pip install --requirement requirements.lock
python -m pip install --no-deps --editable .
python -m pip check
python scripts/check_lock.py
```

Do not `pip install` ad-hoc newer packages into a change and assume CI will resolve the same environment. Update dependency declarations/lock deliberately.

## Run infrastructure/application with Compose

```bash
docker compose up --build
```

Local stack includes PostgreSQL, Redis, MinIO, migration job, API, worker and bot service definitions. Whether bot/API features become operational depends on the secrets/switches you configure.

Stop:

```bash
docker compose down
```

Destroy local volumes only when you deliberately want to remove development state:

```bash
docker compose down -v
```

Never use that command on production Compose/state.

## Database migrations

```bash
alembic upgrade head
```

or:

```bash
make migrate
```

For a schema change:

- add a forward Alembic revision;
- update SQLAlchemy metadata;
- update `scripts/check_schema.py` for critical new schema;
- test upgrade and downgrade/re-upgrade;
- update `database-schema.md` and affected lifecycle docs.

## Run processes outside Compose

Installed console scripts:

```bash
foxgen-api
foxgen-worker
foxgen-bot
```

When running locally outside Compose, adjust `FOXGEN_DATABASE_URL`, `FOXGEN_REDIS_URL`, `FOXGEN_INTERNAL_API_BASE_URL` and storage endpoint to addresses reachable from the host rather than Docker service names.

## Telegram bot

Minimum bot runtime requires:

```env
FOXGEN_TELEGRAM_BOT_TOKEN=...
FOXGEN_INTERNAL_API_TOKEN=...
```

The bot talks to the internal API for price/balance/submission and uses Redis FSM plus S3-compatible storage for references.

Quick Start can be tested without launching a paid provider request through cancel/navigation/media validation steps. Paid confirmation should be tested only with intentional pricing/balance/provider setup.

## Enable paid KIE test deliberately

Required classes include:

```env
FOXGEN_TASK_SUBMISSION_ENABLED=true
FOXGEN_INTERNAL_API_TOKEN=<secret>
FOXGEN_KIE_API_KEY=<secret>
```

You also need:

- a production-ready model in the registry;
- runtime availability enabled;
- an active model price;
- a funded test wallet;
- KIE callback configuration when testing callbacks.

A provider call may cost money. Normal unit/integration CI does not need to call KIE live.

## Admin development

Minimal full admin backend setup:

```env
FOXGEN_ADMIN_API_ENABLED=true
FOXGEN_ADMIN_HMAC_KEY=<dedicated-secret>
FOXGEN_ADMIN_NETWORK_ALLOWLIST=127.0.0.1/32,::1/128,172.16.0.0/12
FOXGEN_ADMIN_SUPERUSER_IDS=<your-telegram-id>
```

For backend operator web development also set:

```env
FOXGEN_ADMIN_WEB_ENABLED=true
```

Do not use the admin HMAC key in browser/public frontend code. The existing operator surface is backend/private; public Mini App work must use a server-mediated design.

See `known-limitations.md`: selected admin extension modules currently exist but are not wired by current runtime entrypoints.

## Tests

Fast local suite:

```bash
make ci
```

Individual commands:

```bash
ruff check .
ruff format --check .
mypy src
pytest -q
pytest -q --cov=foxgen --cov-report=term-missing
```

Real infrastructure integration tests are normally run by CI with PostgreSQL/Redis services and `FOXGEN_RUN_INTEGRATION=1`.

## Debugging provider contracts

Do not change provider payloads by trial-and-error in Telegram handlers. Inspect:

- `foxgen.providers.kie.registry`;
- provider contracts;
- provider adapter;
- contract tests;
- official KIE documentation when changing a contract.

Run free local validation first:

```text
POST /v1/models/{slug}/validate
```

before any paid task request.

## Debugging FSM

Check:

- current state name;
- state data entrypoint/media keys;
- Redis availability/TTL;
- event isolation;
- latest message/callback handler order;
- cleanup of temporary input keys.

Do not use FSM as evidence that a committed paid generation does or does not exist; query durable generation state.

## Debugging worker/lifecycle

Inspect PostgreSQL generation/outbox/media/delivery/reservation states rather than repeatedly restarting/recreating a task. A restart is not a provider-retry strategy.

For ambiguity/reconciliation use the documented operator paths in `generation-operations.md` and `postprocessing-reconciliation.md`.

## Documentation/change checklist

Before PR:

- behavior tests updated;
- affected docs updated;
- env examples updated if configuration changed;
- migration/schema docs updated if durable state changed;
- `make ci` passes where local environment allows;
- no secret/test media accidentally added;
- PR explains migration, operational and rollback impact.