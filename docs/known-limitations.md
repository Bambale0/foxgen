# Known limitations and deferred hardening

This file records known gaps that must not be silently described as completed production behavior.

## Current status

### User payments beyond Telegram Stars

FoxGen supports user-facing digital-credit top-up inside Telegram through Telegram Stars (`XTR`): Happy Fox can request an owner-scoped package/invoice, Telegram checkout is pre-validated against the durable local order, and `successful_payment` settles into the existing immutable `CREDIT` ledger exactly once.

The first production slice deliberately does **not** claim every EPIC #7 payment feature:

- Telegram Stars refund execution is not yet exposed to operators/users, although the Telegram charge ID is stored for that follow-up;
- external web checkout/acquiring providers are not implemented by this slice;
- promo/bonus rules are not automatically coupled to Stars top-up yet.

Do not bypass the Stars flow by mutating wallet rows from the browser/bot. Admin payment inspection/recheck/reprocess remains a private operator capability and must not be exposed as a user payment API.

### Planned generation products

Happy Fox and Telegram expose the complete product launcher, but voice/TTS, Suno/music, Motion Control/talking avatar, Prompt AI, conversational assistant and Gemini Omni remain intentionally disabled until their backend + lifecycle + bot + Mini App slices are implemented. A visible planned product is not production capability.

### Storage provisioning

Storage provisioning is explicit: application request/worker code never creates external S3 buckets, repository Compose provisions its bundled private MinIO bucket through `minio-init`, and external S3-compatible deployments must provision a private bucket before FoxGen startup.

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
