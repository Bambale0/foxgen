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
| [`api-reference.md`](api-reference.md) | Core, public Mini App, billing/generation and signed internal-admin HTTP surface |
| [`miniapp.md`](miniapp.md) | Happy Fox public Telegram Mini App UX, auth, API and media boundaries |
| [`telegram-flows.md`](telegram-flows.md) | User Telegram flows, Quick Start, FSM and `/admin` shell |
| [`reference-memory.md`](reference-memory.md) | Durable private saved-reference library, quotas, selection, reuse and deletion |
| [`model-matrix.md`](model-matrix.md) | KIE model readiness and contract policy |
| [`billing.md`](billing.md) | Pricing, wallet, immutable ledger and settlement |
| [`generation-operations.md`](generation-operations.md) | Status/cancel/operator resolution for durable generations |
| [`postprocessing-reconciliation.md`](postprocessing-reconciliation.md) | Retry/dead-letter/media/delivery reconciliation |
| [`input-media-lifecycle.md`](input-media-lifecycle.md) | Telegram/Mini App input object lifecycle and cleanup requirements |
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

The public Telegram Mini App is implemented as the **Happy Fox** transport surface at `/mini-app/` with owner-scoped `/v1/miniapp/*` APIs. It reuses existing application/domain services for generation and billing rather than duplicating business logic. The backend-only admin operator web remains a separate private operator surface.

Telegram generation also exposes a durable, private **reference memory**. Saved image metadata/ownership is PostgreSQL business state and saved bytes live under the private S3 `references/` prefix. Redis stores only transient browser/selection state; temporary `inputs/` are never silently promoted into durable memory.

## Current production architecture

```text
Telegram bot -----------+
                        |
Happy Fox Mini App -----+--> FastAPI
                        |    |  |  \
Trusted services -------+    |  |   +--> signed internal admin control plane
                             |  +------> provider callback intake
                             +---------> shared paid generation admission
                                |
                                v
                            PostgreSQL <----> foxgen-worker
                                |                 |
                                |                 +--> KIE status/submission
                                |                 +--> archive/delivery
                                |                 +--> durable reference deletes
                                |                 +--> admin/support/campaign jobs
                                |
                             Redis             S3-compatible storage
                             FSM/locks         private inputs/results/references
```

## Durable state ownership

PostgreSQL is the source of truth for generations, billing, outbox/inbox events, media metadata, delivery, saved-reference ownership/lifecycle, administrative commands/audit, support, campaigns, tariffs and runtime admin data. Redis is intentionally non-authoritative for business state: it stores Telegram FSM data, reference-browser selection/navigation, per-key event isolation and rate/lock data. S3-compatible storage stores private input/result bytes and durable saved-reference bytes.

The Happy Fox browser holds only a short-lived Telegram-derived JWT and short-lived media capabilities. It does not become a business-state source of truth and never receives internal API, KIE, admin or S3 credentials.

Storage provisioning is infrastructure-owned: repository Compose provisions bundled MinIO through `minio-init`; application request/worker code never creates buckets; external S3-compatible deployments pre-provision a private bucket and equivalent temporary-input lifecycle. The short `inputs/` lifecycle must never target durable `references/` or `generations/` prefixes.

## Safety invariants shared by all docs

1. Billable provider submission is never blindly retried after an ambiguous external response.
2. Telegram send is not replayed automatically after an ambiguous transport result.
3. Money changes use integer units, an immutable ledger and transactional idempotency.
4. Paid admission fails closed when authentication, price, balance, model readiness or runtime availability is invalid.
5. Administrative writes are server-authorized, audited and idempotent; destructive/expensive operations require confirmation.
6. Admin HTTP is backend-only, network allowlisted and signed over exact raw request bytes.
7. User/provider media remains private; public clients never receive storage credentials.
8. Happy Fox validates Telegram `initData` server-side and uses owner-scoped APIs with short-lived JWT/media URLs.
9. Production deployment is gated by CI and deploys an exact tested `main` SHA.
10. An existing source module/branch is not documented as active until it is wired/merged and covered by runtime tests.
11. Specific privileged routes must stay ahead of generic route/callback fallbacks when matching order affects reachability.
12. Compose-managed MinIO must verify the prefix-scoped temporary `inputs/` lifecycle before API, worker and bot startup.
13. Application media execution must not opportunistically provision S3 infrastructure.
14. Saved references are owner-scoped, active-state checked and re-resolved to fresh signed URLs immediately before provider admission.
15. `/start`, `/menu` and ordinary draft cleanup may delete temporary `inputs/` only; they must never delete durable saved references.

## Known limitations are first-class documentation

`known-limitations.md` is retained even when no entry is currently listed. Add a limitation there whenever executable/configuration state could otherwise be mistaken for a completed production behavior, and remove it in the same PR that lands the tested fix.

## How to update documentation

When code changes, update documentation by behavior area rather than adding an isolated note. Remove obsolete roadmap language. For a schema change, update architecture/schema/state docs and operational rollback notes. For a new admin capability, update capability matrix, API/runbook and limitation status. For new configuration, update `configuration.md`, `.env.example` and `deploy/production.env.example` together. For Happy Fox changes, keep `miniapp.md`, API/security/configuration docs and user-facing branding synchronized. For reference-memory changes, keep `reference-memory.md`, Telegram flows, schema, API, configuration and input-media lifecycle semantics synchronized.

Review [`documentation-policy.md`](documentation-policy.md) and [`../AGENTS.md`](../AGENTS.md) for maintenance rules.
