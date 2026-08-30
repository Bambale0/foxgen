# HappyFox production handoff

Status: production-ready and independently deployed as of 2026-08-30.

This document closes the delivery scope tracked by issue #142. It records the production boundary and the evidence used for handoff without storing any secrets.

## Product boundary

HappyFox lives in `Bambale0/foxgen` and is operated independently from NEUROMIX / `Bambale0/banano_kling`.

The imported production-core provenance remains:

```text
Bambale0/banano_kling@36f92a0504f849c0c591652a880410e33a1c89aa
```

The pre-cutover FoxGen implementation remains available only as rollback/reference history:

```text
legacy/foxgen-pre-tanyapi-20260820
```

Stable internal provider/model/database identifiers inherited from the core may retain `banana_*` / `banano_*` names for compatibility. They are not permission to reuse NEUROMIX credentials, domains or data.

## Production identity

Verified production topology:

```text
Product ID:       happyfox
Public origin:    https://alena.chillcreative.ru
Mini App:         https://alena.chillcreative.ru/mini-app/
Compose project:  foxgen-happyfox
Container:        foxgen-happyfox-bot
Database:         happyfox
Redis namespace:  foxgen_happyfox
```

Production credentials are supplied through the HappyFox runtime environment and are not committed to the repository. The canonical configuration contract is `.env.happyfox.example`.

`python scripts/validate_happyfox_env.py .env .env.happyfox.runtime .env.postgres` is the fail-closed isolation gate. Deployment must stop if known Tanya/NEUROMIX domains, a shared legacy Redis namespace, SQLite production storage, or incomplete selected-provider credentials are detected.

## Acceptance evidence

Baseline accepted before handoff closure:

```text
Commit:      6790f7fbe56cc9ac4fa8a585f245e1e9b1d9471b
CI run:      33302471114
Deploy run:  33302637128
```

CI passed all release gates for that exact commit:

- backend regression and runtime compilation;
- HappyFox product normalization and Ruff delta checks;
- Mini App locked dependency audit, lint and production static export;
- critical browser journeys in Chromium;
- Telegram startup coverage in Chromium and iPhone WebKit;
- production Docker image build and runtime verification.

The exact-SHA production deployment then passed:

- repository provenance validation;
- isolated HappyFox runtime preflight;
- dedicated PostgreSQL/Redis preparation and validation;
- healthy `foxgen-happyfox-bot` container check;
- public `/health` smoke;
- deployed Mini App `revision.txt` equality with the expected commit;
- `foxgen/production-deploy` success status publication.

A transient reverse-proxy `502` observed immediately after container replacement recovered inside the deployment smoke window; the workflow completed only after the public health endpoint returned successfully.

## Release rule after handoff

The accepted production path is:

```text
feature branch
  -> PR
  -> CI green
  -> merge to main
  -> CI green on exact main SHA
  -> isolated HappyFox preflight
  -> exact-SHA backend + Mini App deploy
  -> health + revision smoke
```

Do not deploy arbitrary working-tree state and do not deploy HappyFox changes through `banano_kling` infrastructure.

## Operations and rollback

Operational details and first-server/cutover instructions are maintained in `docs/happyfox-production-cutover.md`.

Rollback should restore a previously verified `foxgen` commit/release and its compatible HappyFox data backup. Never use a NEUROMIX runtime or database as a HappyFox rollback target.

## Remaining work outside delivery finalization

Repository-wide epics and technical-debt issues remain independent of the HappyFox handoff. In particular, the historical mypy baseline and future product/integration work should continue in separate issues/PRs rather than reopening the cutover boundary.

The next product integration may extend the shared generation domain, but Telegram and any future external channel (for example Instagram) must remain channel adapters over the same HappyFox core instead of duplicating generation/billing/provider logic.
