# Telegram input media lifecycle

Telegram references are stored privately under the `inputs/` path inside a shared local filesystem volume mounted into `foxgen-bot` and `foxgen-api`. This document distinguishes cleanup implemented by application code from the best-effort retention that the local storage adapter enforces for abandoned temporary inputs.

## Current application behavior

One Telegram message equals one upload operation.

The bot:

- accepts supported photo/video inputs;
- rejects Telegram albums/media groups before download;
- serializes updates for one FSM key using Redis event isolation;
- stores accepted reference bytes in private local storage;
- keeps only storage keys in FSM draft data;
- creates provider-readable signed URLs only at final confirmation;
- deletes known input files on explicit `/menu`/cancel, reference replacement and selected broken/old-state recovery paths;
- classifies Telegram download failures separately from storage failures;
- does not advance FSM when upload fails.

## Why lifecycle cleanup is still required

Redis FSM state has a TTL. After expiry, the application may no longer know which private storage keys belonged to an abandoned draft. A process crash or client abandonment can have the same effect.

FoxGen therefore combines explicit per-draft cleanup with best-effort expiry on the local input-storage adapter. Before writing a new file, the adapter prunes expired files by modification time using `FOXGEN_TELEGRAM_INPUT_RETENTION_SECONDS`.

## Private storage invariant

The storage root is private. Telegram users and public clients do not receive:

- filesystem paths;
- storage credentials;
- permanent provider URLs;
- permanent object URLs.

At final confirmation the bot generates a fresh signed URL with `FOXGEN_TELEGRAM_INPUT_PRESIGNED_URL_TTL_SECONDS`. The provider can read the reference for that bounded interval through the public API origin. The underlying file remains private on disk.

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

### Retryable local-storage failure

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
2. Confirm an `inputs/<user>/...` file exists privately under the shared input-storage root.
3. Cancel; verify known object cleanup is attempted and the FSM clears.
4. Send a Telegram album; verify no objects are uploaded for it.
5. Simulate Telegram download failure; verify state remains at the expected input step.
6. Simulate local write failure; verify no successful upload transition occurs.
7. Navigate back/edit in a reference-prefilled draft; verify the same stored object key is retained.

### Infrastructure

1. Verify `bot` and `api` mount the same private input-storage volume.
2. Verify the configured public API origin can reach `/v1/input-media/...`.
3. Verify expired signed URLs are rejected.
4. Verify files older than `FOXGEN_TELEGRAM_INPUT_RETENTION_SECONDS` are eventually pruned.
5. Verify the storage root is not exposed as a public Docker bind or web static directory.

## Incident handling

If abandoned `inputs/` files accumulate:

1. inspect bot logs for repeated cleanup failures;
2. do not delete the entire shared volume;
3. confirm no active confirmed generation still depends on an unexpired input file;
4. increase `FOXGEN_TELEGRAM_INPUT_RETENTION_SECONDS` only after confirming real provider fetch delays;
5. remove stale temporary files only through a controlled prefix-scoped operation if necessary;
6. document the retention incident.

## Related docs

- `telegram-flows.md` — reference/Quick Start behavior;
- `configuration.md` — input, storage and lifecycle settings;
- `architecture.md` — storage ownership;
- `production-deploy.md` — production startup gating;
- `minio-lifecycle-runbook.md` — bootstrap verification, failure recovery and rollback.
