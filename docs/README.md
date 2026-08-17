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
| [`miniapp-user-parity-hardening.md`](miniapp-user-parity-hardening.md) | Multi-result media, playback, publish/unpublish and real Stars affordance hardening for Happy Fox |
| [`telegram-flows.md`](telegram-flows.md) | User Telegram flows, Quick Start, FSM and `/admin` shell |
| [`model-matrix.md`](model-matrix.md) | KIE model readiness and contract policy |
| [`suno-core.md`](suno-core.md) | Suno V5 dedicated API routing, simple/custom contract, multi-track archive and E2E |
| [`suno-extend.md`](suno-extend.md) | Owner-bound Suno V5 Extend source/API/DB guard, UX and E2E runbook |
| [`suno-upload-cover.md`](suno-upload-cover.md) | Owner-bound Suno V5 Upload & Cover private-input/provider-URL boundary, UX and E2E runbook |
| [`billing.md`](billing.md) | Pricing, wallet, immutable ledger and settlement |
| [`telegram-stars-payments.md`](telegram-stars-payments.md) | User `XTR` top-up/refund, durable payment evidence and CREDIT settlement |
| [`user-promos.md`](user-promos.md) | Owner-scoped promo redemption, max-use concurrency and immutable bonus CREDIT |
| [`generation-operations.md`](generation-operations.md) | Status/cancel/operator resolution for durable generations |
| [`postprocessing-reconciliation.md`](postprocessing-reconciliation.md) | Retry/dead-letter/media/delivery reconciliation |
| [`input-media-lifecycle.md`](input-media-lifecycle.md) | Telegram/Mini App input object lifecycle and cleanup requirements |
| [`minio-lifecycle-runbook.md`](minio-lifecycle-runbook.md) | Compose MinIO lifecycle bootstrap, verification and recovery |
| [`admin-capability-matrix.md`](admin-capability-matrix.md) | Admin capability/domain/transport matrix |
| [`admin-control-plane.md`](admin-control-plane.md) | Admin security, HMAC, RBAC, extensions, workers and rollout |
| [`security.md`](security.md) | Consolidated trust boundaries and prohibited shortcuts |
| [`testing-ci.md`](testing-ci.md) | Reproducible CI, real infrastructure and cross-layer E2E gates |
| [`release-checklist.md`](release-checklist.md) | Pre-merge, pre-deploy and post-deploy checklist |
| [`production-deploy.md`](production-deploy.md) | Exact-SHA production deployment workflow |
| [`github-environment-setup.md`](github-environment-setup.md) | GitHub `production` Environment setup |
| [`operations-runbook.md`](operations-runbook.md) | Day-2 operations, smoke checks and incident handling |
| [`known-limitations.md`](known-limitations.md) | Current executable production limitations when any are known |
| [`state-gap-audit.md`](state-gap-audit.md) | Historical state-gap audit with current completion status |
| [`documentation-policy.md`](documentation-policy.md) | Documentation source-of-truth and maintenance rules |

## Scope boundary

The public Telegram Mini App is implemented as the **Happy Fox** transport surface at `/mini-app/` with owner-scoped `/v1/miniapp/*` APIs. It reuses existing application/domain services for generation, billing, payments and promo redemption rather than duplicating business logic. The backend-only admin operator web remains a separate private operator surface.

## Current production architecture

```text
Telegram bot -----------+
                        |
Happy Fox Mini App -----+--> FastAPI
                        |    |  |  \
Trusted services -------+    |  |   +--> signed internal admin control plane
                             |  +------> provider callback intake
                             +---------> shared paid generation / wallet boundaries
                                |
                                v
                            PostgreSQL <----> foxgen-worker
                                |                 |
                                |                 +--> KIE Market / routed Suno API families
                                |                 +--> archive/delivery
                                |                 +--> admin/payment/support jobs
                                |
                             Redis             S3-compatible storage
                             FSM/locks         private media
```

## Durable state ownership

PostgreSQL is the source of truth for generations, billing, user payment orders/events/refunds, promo definitions/redemptions, outbox/inbox events, media metadata, delivery, administrative commands/audit, support, campaigns, tariffs and runtime admin data. Telegram Stars payment evidence is persisted before wallet settlement; promo redemption persists the wallet credit, immutable ledger movement, redemption and usage counter in one transaction. Redis is intentionally non-authoritative for business state: it stores Telegram FSM data, per-key event isolation and rate/lock data. S3-compatible storage stores private input/result bytes.

The Happy Fox browser holds only a short-lived Telegram-derived JWT and short-lived media capabilities. It never receives internal API, KIE, admin, Telegram-bot or S3 credentials and never supplies monetary reward values.

Storage provisioning is infrastructure-owned: repository Compose provisions bundled MinIO through `minio-init`; application request/worker code never creates buckets; external S3-compatible deployments pre-provision a private bucket and equivalent temporary-input lifecycle.

## Safety invariants shared by all docs

1. Billable provider submission is never blindly retried after an ambiguous external response.
2. Telegram send/refund ambiguity is not guessed away automatically.
3. Money changes use integer units, an immutable ledger and transactional idempotency.
4. A Telegram Stars `successful_payment` is recorded by charge ID before CREDIT settlement; duplicate charge/update processing cannot create a second credit.
5. Promo reward amount comes only from the locked server-side promo definition; `(promo_code, user_id)` and its ledger key are unique.
6. Paid admission fails closed when authentication, price, balance, model readiness or runtime availability is invalid.
7. Administrative writes are server-authorized, audited and idempotent; destructive/expensive operations require confirmation.
8. Admin HTTP is backend-only, network allowlisted and signed over exact raw request bytes.
9. User/provider media remains private; public clients never receive storage credentials.
10. Happy Fox validates Telegram `initData` server-side and uses owner-scoped APIs with short-lived JWT/media URLs.
11. Production deployment is gated by CI and deploys an exact tested `main` SHA.
12. An existing source module/branch is not documented as active until it is wired/merged and covered by runtime tests.
13. Specific privileged/financial routes must stay ahead of generic route/callback fallbacks when matching order affects reachability.
14. Compose-managed MinIO must verify the prefix-scoped temporary `inputs/` lifecycle and bundled stale-multipart cleanup prerequisites before API, worker and bot startup.
15. Application media execution must not opportunistically provision S3 infrastructure.
16. Dedicated provider API families are selected from reviewed `ModelSpec.api_family`; worker code must not infer provider routing from arbitrary model-name strings.
17. Multi-result providers must preserve every canonical billable result while filtering non-result artwork/stream helper URLs before generic media archival.
18. Source-bound generation such as Suno Extend must re-verify owner/source identity before paid admission and retain a durable database guard against generic-transport bypass.
19. Upload-bound generation such as Suno Upload & Cover must persist only an owner-scoped private storage key; a short-lived provider URL is resolved server-side immediately before provider submission.

## Known limitations are first-class documentation

`known-limitations.md` is retained even when no entry is currently listed. Add a limitation there whenever executable/configuration state could otherwise be mistaken for a completed production behavior, and remove it in the same PR that lands the tested fix.

## How to update documentation

When code changes, update documentation by behavior area rather than adding an isolated note. Remove obsolete roadmap language. For schema/financial changes, update architecture/schema/billing/API/testing docs and rollback notes. For user promo changes, keep `user-promos.md`, `billing.md`, `api-reference.md`, `database-schema.md`, `miniapp.md`, `testing-ci.md` and limitation status synchronized. For new provider API families or source-bound provider operations, document the routing boundary, ownership checks, exact model/input contract, result normalization and E2E in a focused runbook. For new admin capability, update capability matrix/API/runbook. For new configuration, update `configuration.md` plus env examples. For Happy Fox changes, keep Mini App/security/user-facing behavior synchronized.

Review [`documentation-policy.md`](documentation-policy.md) and [`../AGENTS.md`](../AGENTS.md) for maintenance rules.