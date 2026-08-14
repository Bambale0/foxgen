# FoxGen documentation

This directory documents the executable state of FoxGen on `main`. Source code, tests and migrations remain authoritative when a mismatch is discovered; documentation must then be corrected in the same change.

## Start here

| Document | Purpose |
|---|---|
| [`../README.md`](../README.md) | Product/runtime overview and quick start |
| [`development.md`](development.md) | Local setup, Compose, migrations and debugging |
| [`architecture.md`](architecture.md) | Service boundaries, durable pipelines and safety invariants |
| [`database-schema.md`](database-schema.md) | PostgreSQL table/state/constraint map |
| [`configuration.md`](configuration.md) | Complete configuration groups and production rules |
| [`api-reference.md`](api-reference.md) | Core, billing/generation, publication and signed internal-admin HTTP surface |
| [`telegram-flows.md`](telegram-flows.md) | User Telegram flows, Quick Start, feed/profile/remix FSM and `/admin` shell |
| [`feed-profile-remix.md`](feed-profile-remix.md) | Publication/profile/remix domain, invariants, deep links and compromises |
| [`model-matrix.md`](model-matrix.md) | KIE model readiness and contract policy |
| [`billing.md`](billing.md) | Pricing, wallet, immutable ledger and settlement |
| [`generation-operations.md`](generation-operations.md) | Status/cancel/operator resolution for durable generations |
| [`postprocessing-reconciliation.md`](postprocessing-reconciliation.md) | Retry/dead-letter/media/delivery reconciliation |
| [`input-media-lifecycle.md`](input-media-lifecycle.md) | Telegram input object lifecycle and cleanup requirements |
| [`minio-lifecycle-runbook.md`](minio-lifecycle-runbook.md) | Compose MinIO lifecycle bootstrap, verification and recovery |
| [`admin-capability-matrix.md`](admin-capability-matrix.md) | Admin capability/domain/transport matrix |
| [`admin-control-plane.md`](admin-control-plane.md) | Admin security, HMAC, RBAC, extensions, workers and rollout |
| [`security.md`](security.md) | Consolidated trust boundaries and prohibited shortcuts |
| [`testing-ci.md`](testing-ci.md) | Reproducible CI and local quality gates |
| [`release-checklist.md`](release-checklist.md) | Pre-merge, pre-deploy and post-deploy checklist |
| [`production-deploy.md`](production-deploy.md) | Exact-SHA production deployment workflow |
| [`github-environment-setup.md`](github-environment-setup.md) | GitHub `production` Environment setup |
| [`operations-runbook.md`](operations-runbook.md) | Day-2 operations, smoke checks and incident handling |
| [`known-limitations.md`](known-limitations.md) | Current executable production limitations when any are known |
| [`state-gap-audit.md`](state-gap-audit.md) | Historical state-gap audit with current completion status |
| [`documentation-policy.md`](documentation-policy.md) | Documentation source-of-truth and maintenance rules |

## Scope boundary

The public Mini App is intentionally excluded from the current documentation baseline. Telegram includes the implemented publication/feed/profile/remix product surface. The backend-only admin operator web and its extension routes remain private operator surfaces; neither implies a finished public Mini App.

## Current production architecture

```text
Telegram bot / trusted services
          |
          v
       FastAPI
       |  |  | \
       |  |  |  +--> publication/profile/remix API
       |  |  +-----> signed internal admin control plane
       |  +--------> provider callback intake
       +-----------> paid generation admission
          |
          v
      PostgreSQL <----> foxgen-worker
       |  |                 |
       |  |                 +--> KIE status/submission
       |  |                 +--> archive/delivery
       |  |                 +--> admin/support/campaign jobs
       |  +--> publications/profiles/likes/comments/lineage
       |
       Redis             S3-compatible result storage
       FSM/locks         private durable media
```

Temporary Telegram input references use the current local shared input-media topology; durable generated results referenced by publications remain in private S3-compatible storage.

## Durable state ownership

PostgreSQL is the source of truth for generations, billing, outbox/inbox events, media metadata, delivery, publication/profile/remix lineage, likes/comments, administrative commands/audit, support, campaigns, tariffs and runtime admin data. Redis is intentionally non-authoritative for business state: it stores Telegram FSM data, per-key event isolation and rate/lock data. S3-compatible storage stores durable private generation result bytes.

Storage provisioning is infrastructure-owned: repository Compose provisions bundled MinIO through `minio-init`; application request/worker code never creates buckets; external S3-compatible deployments pre-provision a private bucket and equivalent lifecycle where applicable.

## Safety invariants shared by all docs

1. Billable provider submission is never blindly retried after an ambiguous external response.
2. Telegram send is not replayed automatically after an ambiguous transport result.
3. Money changes use integer units, an immutable ledger and transactional idempotency.
4. Paid admission fails closed when authentication, price, balance, model readiness or runtime availability is invalid.
5. Administrative writes are server-authorized, audited and idempotent; destructive/expensive operations require confirmation.
6. Admin HTTP is backend-only, network allowlisted and signed over exact raw request bytes.
7. User/provider media remains private; public clients never receive storage credentials.
8. Production deployment is gated by CI and deploys an exact tested `main` SHA.
9. An existing source module/branch is not documented as active until it is wired/merged and covered by runtime tests.
10. Specific privileged routes must stay ahead of generic route/callback fallbacks when matching order affects reachability.
11. Application media execution must not opportunistically provision S3 infrastructure.
12. Publication never changes generation/billing/provider state; it only projects eligible completed generations.
13. A derivative generation cannot enter the global feed, and derivative public projections never expose its prompt/actions.
14. Remix lineage is committed atomically with paid admission and is part of the request fingerprint.
15. `/start` and `/menu` are global Telegram interrupts ahead of every generation/feed FSM router.

## Known limitations are first-class documentation

`known-limitations.md` is retained even when no entry is currently listed. Add a limitation there whenever executable/configuration state could otherwise be mistaken for a completed production behavior, and remove it in the same PR that lands the tested fix. Product compromises specific to feed/profile/remix are recorded in `feed-profile-remix.md`.

## How to update documentation

When code changes, update documentation by behavior area rather than adding an isolated note. Remove obsolete roadmap language. For a schema change, update architecture/schema/state docs and operational rollback notes. For a new publication capability, update `feed-profile-remix.md`, API/Telegram docs and migration/schema docs together. For a new admin capability, update capability matrix, API/runbook and limitation status. For new configuration, update `configuration.md`, `.env.example` and `deploy/production.env.example` together.

Review [`documentation-policy.md`](documentation-policy.md) and [`../AGENTS.md`](../AGENTS.md) for maintenance rules.
