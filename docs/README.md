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
| [`api-reference.md`](api-reference.md) | Core, billing/generation and signed internal-admin HTTP surface |
| [`telegram-flows.md`](telegram-flows.md) | User Telegram flows, Quick Start, FSM and `/admin` shell |
| [`model-matrix.md`](model-matrix.md) | KIE model readiness and contract policy |
| [`billing.md`](billing.md) | Pricing, wallet, immutable ledger and settlement |
| [`generation-operations.md`](generation-operations.md) | Status/cancel/operator resolution for durable generations |
| [`postprocessing-reconciliation.md`](postprocessing-reconciliation.md) | Retry/dead-letter/media/delivery reconciliation |
| [`input-media-lifecycle.md`](input-media-lifecycle.md) | Telegram input object lifecycle and cleanup requirements |
| [`minio-lifecycle-runbook.md`](minio-lifecycle-runbook.md) | Compose MinIO lifecycle bootstrap, verification and recovery |
| [`admin-capability-matrix.md`](admin-capability-matrix.md) | Admin capability/domain/transport matrix |
| [`admin-control-plane.md`](admin-control-plane.md) | Admin security, HMAC, RBAC, workers and rollout |
| [`security.md`](security.md) | Consolidated trust boundaries and prohibited shortcuts |
| [`testing-ci.md`](testing-ci.md) | Reproducible CI and local quality gates |
| [`release-checklist.md`](release-checklist.md) | Pre-merge, pre-deploy and post-deploy checklist |
| [`production-deploy.md`](production-deploy.md) | Exact-SHA production deployment workflow |
| [`github-environment-setup.md`](github-environment-setup.md) | GitHub `production` Environment setup |
| [`operations-runbook.md`](operations-runbook.md) | Day-2 operations, smoke checks and incident handling |
| [`known-limitations.md`](known-limitations.md) | Known gaps that must not be described as active production behavior |
| [`state-gap-audit.md`](state-gap-audit.md) | Historical state-gap audit with current completion status |
| [`documentation-policy.md`](documentation-policy.md) | Documentation source-of-truth and maintenance rules |

## Scope boundary

The public Mini App is intentionally excluded from the current documentation baseline. Backend contracts that may later support an admin web/Mini App are documented as backend capabilities only. Do not infer a finished public UI from those routes.

## Current production architecture

```text
Telegram bot / trusted services
          |
          v
       FastAPI
       |  |  \
       |  |   +--> signed internal admin control plane
       |  +------> provider callback intake
       +---------> paid generation admission
          |
          v
      PostgreSQL <----> foxgen-worker
          |                 |
          |                 +--> KIE status/submission
          |                 +--> archive/delivery
          |                 +--> admin/support/campaign jobs
          |
       Redis             S3-compatible storage
       FSM/locks         private media
```

## Durable state ownership

PostgreSQL is the source of truth for generations, billing, outbox/inbox events, media metadata, delivery, administrative commands/audit, support, campaigns, tariffs and runtime admin data. Redis is intentionally non-authoritative for business state: it stores Telegram FSM data, per-key event isolation and rate/lock data. S3-compatible storage stores private input/result bytes.

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
10. Compose-managed MinIO must verify the prefix-scoped temporary `inputs/` lifecycle before API, worker and bot startup.

## Known limitations are first-class documentation

`known-limitations.md` records discrepancies such as currently unwired admin extension routers and the reserved/inactive `FOXGEN_S3_CREATE_BUCKET` application setting. This prevents roadmap/prepared code from being mistaken for production behavior.

## How to update documentation

When code changes, update documentation by behavior area rather than adding an isolated note. Remove obsolete roadmap language. For a schema change, update architecture/schema/state docs and operational rollback notes. For a new admin capability, update capability matrix, API/runbook and limitation status. For new configuration, update `configuration.md`, `.env.example` and `deploy/production.env.example` together.

Review [`documentation-policy.md`](documentation-policy.md) and [`../AGENTS.md`](../AGENTS.md) for maintenance rules.
