# Telegram input media lifecycle

Telegram references are stored privately under the `inputs/` object prefix. This document distinguishes cleanup implemented by application code from the bucket lifecycle rule that production infrastructure must currently provide.

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

Therefore production object storage must enforce lifecycle cleanup for the temporary prefix independently of conversational state.

## Current production requirement

**Current `main` does not automatically install or verify the bucket lifecycle rule.**

The storage administrator must configure an equivalent rule externally. Recommended baseline:

```text
prefix: inputs/
expire current objects after: 2 days
abort incomplete multipart uploads after: 1 day
```

The exact retention must remain longer than:

- the maximum legitimate provider fetch delay for a confirmed input URL;
- the expected Telegram FSM interaction lifetime;
- any operational grace period required by the deployment.

Do not apply the short temporary-input retention to durable generation results.

```text
inputs/       -> short temporary retention
result media  -> product retention policy, not the input rule
```

An open implementation may automate this infrastructure rule in the future, but documentation must not assume that automation until it is merged and revalidated on the current production branch.

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

1. Inspect the bucket lifecycle configuration.
2. Verify the temporary rule targets only `inputs/`.
3. Verify current-object expiration is configured.
4. Verify incomplete multipart cleanup is configured when the storage supports it.
5. Verify no equivalent short-expiry rule targets durable generated result objects.
6. Verify the bucket has no public ACL/policy exposing user media.

## Incident handling

If abandoned `inputs/` objects accumulate:

1. do not delete all bucket content;
2. inspect the prefix and current lifecycle rule;
3. confirm no active confirmed generation still depends on an unexpired input object;
4. restore/fix the prefix-scoped lifecycle rule;
5. remove stale temporary objects through a controlled prefix-scoped operation if necessary;
6. document the retention incident.

If objects disappear before provider fetch, increase the temporary retention only after identifying the actual fetch delay; do not compensate by making the entire bucket public.

## Related docs

- `telegram-flows.md` — reference/Quick Start behavior;
- `configuration.md` — input size and presigned TTL settings;
- `architecture.md` — storage ownership;
- `production-deploy.md` — production preflight checks.