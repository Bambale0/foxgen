# Telegram input media lifecycle

Telegram references are stored privately under the `inputs/` object prefix. This document distinguishes cleanup implemented by application code from the storage lifecycle that Compose enforces for abandoned temporary inputs.

## Current application behavior

One Telegram message equals one upload operation.

The bot:

- accepts supported photo/video inputs;
- rejects Telegram albums/media groups before download;
- serializes updates for one FSM key using Redis event isolation;
- uploads accepted reference bytes to private object storage;
- keeps only object keys in FSM draft data;
- creates provider-readable presigned URLs only at final confirmation;
- deletes known input objects on explicit `/menu`/cancel, reference replacement and selected broken/old-state recovery paths;
- classifies Telegram download failures separately from storage failures;
- does not advance FSM when upload fails.

## Why lifecycle cleanup is still required

Redis FSM state has a TTL. After expiry, the application may no longer know which private object keys belonged to an abandoned draft. A process crash or client abandonment can have the same effect.

Storage-level lifecycle cleanup is therefore required independently of conversational state.

## Compose-enforced lifecycle

Both repository Compose stacks run `scripts/configure_minio_input_lifecycle.py` through `minio-init` before API, worker and bot startup. The bootstrap fails closed when the required rule cannot be applied and verified.

The initializer:

- creates the Compose-managed private MinIO bucket when necessary;
- reads the existing lifecycle configuration;
- preserves every lifecycle rule not owned by FoxGen;
- replaces only the managed rule with ID `foxgen-expire-telegram-inputs`;
- scopes expiration and incomplete-multipart cleanup to `inputs/`;
- reads the lifecycle configuration back after writing it;
- exits unsuccessfully unless exactly one enabled FoxGen rule matches the requested policy.

Default policy:

```text
prefix: inputs/
expire current objects after: 2 days
abort incomplete multipart uploads after: 1 day
```

Configuration:

```env
FOXGEN_INPUT_RETENTION_DAYS=2
FOXGEN_INPUT_MULTIPART_ABORT_DAYS=1
FOXGEN_MINIO_INIT_ATTEMPTS=30
FOXGEN_MINIO_INIT_RETRY_SECONDS=2
```

The retention must remain longer than:

- the maximum legitimate provider fetch delay for a confirmed input URL;
- the expected Telegram FSM interaction lifetime;
- any operational grace period required by the deployment.

Do not apply the short temporary-input retention to durable generation results.

```text
inputs/       -> short temporary retention
generations/  -> product retention policy, never the input rule
```

The repository production Compose stack manages its bundled MinIO instance and provisions that bucket through `minio-init`. A deployment that replaces the storage topology with an external S3-compatible service must provision the private bucket before FoxGen startup and enforce an equivalent `inputs/` lifecycle policy through that provider's infrastructure controls. Application request/worker code never creates buckets.

## Private storage invariant

The bucket is private. Telegram users and public clients do not receive:

- bucket credentials;
- public bucket ACLs;
- permanent provider URLs;
- permanent object URLs.

At final confirmation the bot generates a fresh presigned URL with `FOXGEN_TELEGRAM_INPUT_PRESIGNED_URL_TTL_SECONDS`. The provider can read the reference for that bounded interval. The object itself remains private.

## Input error classification

### Permanent validation failures

Examples:

- media group/album;
- unsupported media kind;
- empty/invalid file;
- input larger than configured maximum.

The user receives an actionable validation response and remains in a recoverable flow.

### Retryable Telegram transfer failure

A Telegram download/network failure is classified separately from invalid user content. The FSM does not pretend the file was stored.

### Retryable object-storage failure

Failure while writing private input bytes also prevents FSM transition. Retrying the user step is allowed because no provider side effect has occurred.

### Cleanup failure

Best-effort explicit cleanup failure should be logged/observable but must not turn a successful cancel/menu action into a dangerous provider operation. The bucket lifecycle rule is the final orphan cleanup safety net.

### Lifecycle bootstrap failure

A failed `minio-init` verification blocks API, worker and bot startup in the Compose stacks. Do not bypass that dependency with `--no-deps`; fix storage reachability, credentials or lifecycle permissions first.

## Quick Start ownership

A reference draft can hold:

- original media object key;
- optional video thumbnail/preview object key;
- reference media kind;
- selected output product/model/settings;
- prompt/caption.

Back/edit navigation preserves these keys. Replacing the reference should clean the previously known temporary objects before/while establishing the new draft according to the current cleanup helper behavior.

## Media groups

Telegram albums are rejected before any member is downloaded. FoxGen does not currently aggregate an album into one multi-reference Quick Start draft. Users must send supported references as individual messages through the flow expected by the selected model.

This policy avoids ambiguous ordering, partial album upload and double-processing races.

## Verification checklist

### Application

1. Send one photo outside active FSM; verify Quick Start/reference choice appears.
2. Confirm an `inputs/<user>/...` object exists privately.
3. Cancel; verify known object cleanup is attempted and the FSM clears.
4. Send a Telegram album; verify no objects are uploaded for it.
5. Simulate Telegram download failure; verify state remains at the expected input step.
6. Simulate S3 write failure; verify no successful upload transition occurs.
7. Navigate back/edit in a reference-prefilled draft; verify the same stored object key is retained.

### Infrastructure

1. Run or inspect `minio-init` and require a successful exit.
2. Inspect the bucket lifecycle configuration.
3. Verify exactly one enabled FoxGen-managed rule targets only `inputs/`.
4. Verify current-object expiration matches `FOXGEN_INPUT_RETENTION_DAYS`.
5. Verify incomplete multipart cleanup matches `FOXGEN_INPUT_MULTIPART_ABORT_DAYS`.
6. Verify unrelated lifecycle rules remain unchanged.
7. Verify no equivalent short-expiry rule targets `generations/` or other durable result prefixes.
8. Verify the bucket has no public ACL/policy exposing user media.
9. Verify API, worker and bot do not start if lifecycle bootstrap cannot be verified.
10. For external S3-compatible storage, verify the private bucket exists before deployment and application credentials cannot create arbitrary infrastructure.

## Incident handling

If abandoned `inputs/` objects accumulate:

1. inspect `minio-init` logs and current bucket lifecycle configuration;
2. do not delete all bucket content;
3. confirm no active confirmed generation still depends on an unexpired input object;
4. rerun the idempotent `minio-init` bootstrap after fixing credentials/reachability;
5. remove stale temporary objects only through a controlled prefix-scoped operation if necessary;
6. document the retention incident.

If objects disappear before provider fetch, increase the temporary retention only after identifying the actual fetch delay; do not compensate by making the entire bucket public.

## Related docs

- `telegram-flows.md` — reference/Quick Start behavior;
- `configuration.md` — input, storage and lifecycle settings;
- `architecture.md` — storage ownership;
- `production-deploy.md` — production startup gating;
- `minio-lifecycle-runbook.md` — bootstrap verification, failure recovery and rollback.
