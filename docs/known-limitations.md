# Known limitations and deferred hardening

This file records known gaps that must not be silently described as completed production behavior.

## Current status

### Happy Fox balance top-up

Happy Fox exposes the real materialized wallet balance and immutable ledger history, and paid generation uses the normal atomic FoxGen admission path. The public **Пополнить** affordance does not create a payment invoice yet because the public payment-provider/invoice/webhook portion of EPIC #7 is still open.

The frontend therefore performs no balance mutation and explicitly reports that top-up is not connected. Do not describe Mini App payments as complete until EPIC #7 lands a user-facing payment flow with idempotent provider webhooks and ledger credit.

This is intentionally different from admin payment inspection/recheck/reprocess, which is a private operator capability and must not be exposed as a user payment API.

### Publication feed integration

Happy Fox currently presents the authenticated owner's generation history. The separate publication/feed/profile/remix domain from issue #58 / PR #63 is not treated as merged production behavior by the Mini App until that work lands in `main` and is integrated explicitly.

Storage provisioning is explicit: application request/worker code never creates S3 buckets, repository Compose provisions its bundled private MinIO bucket through `minio-init`, and external S3-compatible deployments must provision a private bucket before FoxGen startup.

## Documentation rule

When a new limitation is discovered:

1. create/identify the tracked issue;
2. document only executable current behavior and the exact gap;
3. do not describe prepared/unwired code as production-active.

When a limitation is resolved:

1. merge executable code and tests first;
2. remove/update the limitation in the same PR;
3. update the relevant API/configuration/runbook documentation;
4. update env examples and production preflight when operational setup changes.
