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
- remembers the current Telegram generation control-message id in Redis FSM so accepted uploads can refresh one live `Загружено: X/Y` screen instead of posting another keyboard block;
- treats that control-message id as presentation state only, never as media ownership or durable generation state;
- deletes known input files on explicit `/start`/`/menu`, reference replacement, generation-screen reload, skip-without-reference and selected broken/old-state recovery paths;
- classifies Telegram download failures separately from storage failures;
- does not advance FSM when upload fails.

## Reference-screen cleanup actions

The compact generation screens have explicit input semantics:

### `🔄 Перезагрузить`

Reload means **clear the current temporary reference set and redraw the same screen from zero**.

The handler:

1. reads all current draft storage keys;
2. best-effort deletes those private temporary files through `TelegramInputMediaStorage`;
3. replaces the FSM `media` list with an empty list;
4. re-renders the live counter and controls.

It does not resend, copy or promote old inputs into persistent storage.

### Image `⏭ Пропустить`

Skip means continue without image references. If the user has already uploaded temporary image references before pressing Skip, FoxGen deletes those known files, clears `media`, resolves the text-generation provider slug and proceeds to model settings.

This avoids the misleading state where the UI says “skip” but the submitted payload still contains earlier references.

### `✅ Продолжить`

Continue preserves the accepted temporary inputs and advances only when the current scenario contract is valid. Required video scenarios validate media completeness at the transition; an early press produces a user-facing Telegram alert and leaves the draft unchanged.

## Live control-message behavior

After a successful upload, FoxGen attempts to edit the remembered generation control message with the new count and the same actions. This keeps the chat compact and makes old controls less likely to remain visible.

If Telegram reports that the remembered message cannot be edited, the bot sends one replacement control message and remembers its new chat/message id. This fallback changes only Telegram presentation; it does not duplicate media and does not cause provider or billing side effects.

`wizard_control_chat_id` and `wizard_control_message_id` live only in Redis FSM data. They are cleared with the draft and are not written to PostgreSQL generation/billing records.

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

The generation reference screen does not currently expose a persistent `Память реф` library. Temporary inputs are not silently converted into durable saved user assets; a future saved-reference feature requires its own owner-scoped storage/domain lifecycle.

## Input error classification

### Permanent validation failures

Examples:

- media group/album;
- unsupported media kind;
- empty/invalid file;
- input larger than configured maximum;
- exceeding the selected model/scenario reference limit.

The user receives an actionable validation response and remains in a recoverable flow. The live control screen is refreshed when useful so the current counter/actions stay visible.

### Retryable Telegram transfer failure

A Telegram download/network failure is classified separately from invalid user content. The FSM does not pretend the file was stored.

### Retryable local-storage failure

Failure while writing private input bytes also prevents FSM transition. Retrying the user step is allowed because no provider side effect has occurred.

### Cleanup failure

Best-effort explicit cleanup failure should be logged/observable but must not turn a successful reset/menu action into a dangerous provider operation. Retention/lifecycle cleanup remains the final orphan safety net.

## Quick Start ownership

A reference draft can hold:

- original media object key;
- optional video thumbnail/preview object key;
- reference media kind;
- selected output product/model/settings;
- prompt/caption.

Back/edit navigation preserves these keys. Replacing the reference should clean the previously known temporary objects before/while establishing the new draft according to the current cleanup helper behavior.

When Quick Start converges into the ordinary generation wizard, the same temporary keys become that wizard's prefilled `media`. The compact Telegram control-message id is separate presentation metadata and does not affect this ownership transfer.

## Media groups

Telegram albums are rejected before any member is downloaded. FoxGen does not currently aggregate an album into one multi-reference Quick Start draft. Users must send supported references as individual messages through the flow expected by the selected model.

This policy avoids ambiguous ordering, partial album upload and double-processing races.

## Verification checklist

### Application

1. Send one photo outside active FSM; verify Quick Start/reference choice appears.
2. Confirm an `inputs/<user>/...` file exists privately under the shared input-storage root.
3. Enter an image reference screen and upload several images individually; verify the same control message updates `Загружено: X/Y` whenever Telegram permits editing.
4. Press `🔄 Перезагрузить`; verify all known current reference keys are deleted and the counter returns to zero.
5. Upload references and then press image `⏭ Пропустить`; verify those temporary files are deleted before the text-only settings path continues.
6. In a required video scenario press `✅ Продолжить` before all required media exists; verify an alert is shown and no provider request occurs.
7. Cancel/reset with `/start` or `/menu`; verify known object cleanup is attempted and the FSM clears.
8. Send a Telegram album; verify no objects are uploaded for it.
9. Simulate Telegram download failure; verify state remains at the expected input step.
10. Simulate local write failure; verify no successful upload transition occurs.
11. Navigate back/edit in a reference-prefilled draft; verify the same stored object key is retained until an explicit incompatible replacement/clear path.

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

- `telegram-flows.md` — generation screens, reference/Quick Start behavior;
- `configuration.md` — input, storage and lifecycle settings;
- `architecture.md` — storage ownership;
- `production-deploy.md` — production startup gating;
- `minio-lifecycle-runbook.md` — bootstrap verification, failure recovery and rollback.
