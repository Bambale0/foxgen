# Known limitations and deferred hardening

This file records known gaps that must not be silently described as completed production behavior.

## Current status

No repository-level production limitation is currently listed here.

This does **not** mean the whole FoxGen product roadmap is complete. Open product/model/feed/payment/referral issues remain tracked in GitHub. This document is reserved for mismatches where code/configuration could otherwise be mistaken for active production behavior.

Storage provisioning is now explicit: application request/worker code never creates S3 buckets, repository Compose provisions its bundled private MinIO bucket through `minio-init`, and external S3-compatible deployments must provision a private bucket before FoxGen startup.

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
