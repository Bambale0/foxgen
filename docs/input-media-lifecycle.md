# Telegram input media lifecycle

Telegram generation inputs first enter FoxGen as private temporary files under the local `inputs/` path shared by `foxgen-bot` and `foxgen-api`. Explicitly saved image references are a separate durable ownership class: PostgreSQL stores their metadata and private S3-compatible storage stores their bytes under `references/`.

This separation is a hard invariant. Temporary retention/cleanup applies to `inputs/`; it must never delete durable `references/` objects.

## Current temporary-input behavior

One Telegram message equals one upload operation.

The bot:

- accepts supported photo/video/audio inputs according to the active flow;
- rejects Telegram albums/media groups before download;
- serializes updates for one FSM key using Redis event isolation;
- stores accepted temporary reference bytes in private local storage;
- keeps temporary `storage_key` locators in FSM draft data;
- creates provider-readable signed URLs only at final confirmation;
- remembers the current Telegram generation control-message id in Redis FSM so accepted uploads can refresh one live `Загружено: X/Y` screen instead of posting another keyboard block;
- treats that control-message id as presentation state only;
- deletes known temporary files on `/start`, `/menu`, replacement, generation-screen reload, skip-without-reference and selected recovery paths;
- classifies Telegram download failures separately from storage failures;
- does not advance FSM when upload fails.

## Reference-screen cleanup actions

### `🔄 Перезагрузить`

Reload means clear the current generation draft's references and redraw the same screen from zero.

For temporary inputs, the handler best-effort deletes known `inputs/` files. For durable saved references, it removes only their UUID locators from the Redis draft. The underlying `references/` objects remain in the user's library.

### Image `⏭ Пропустить`

Skip means continue without image references. Any known temporary images are deleted; saved-reference UUIDs are detached from the draft. The durable library is unchanged.

### `✅ Продолжить`

Continue preserves accepted temporary and/or saved inputs and advances only when the current model/scenario contract is valid. Required video scenarios validate completeness before transition.

## Live control-message behavior

After a successful temporary upload, FoxGen attempts to edit the remembered generation control message with the new count and current actions. If Telegram cannot edit it, the bot sends one replacement control message.

The durable reference-memory browser uses a private Telegram image preview with its own replaceable control message. Navigating the library deletes/replaces the previous preview instead of accumulating stale preview keyboards.

Control-message IDs live only in Redis FSM data and are not media ownership or durable business state.

## Temporary retention

Redis FSM has a TTL. After expiry, application code can lose the list of abandoned temporary keys. FoxGen therefore combines explicit per-draft deletion with best-effort local expiry: before writing a new input, the adapter prunes files older than `FOXGEN_TELEGRAM_INPUT_RETENTION_SECONDS`.

This mechanism is only for `inputs/` local storage. Durable saved references are not subject to that TTL.

## Durable reference-memory promotion

Temporary images become durable only through an explicit user action:

- `➕ Добавить фото` from the `📚 Память реф` browser uploads one image and immediately saves it; or
- `💾 Сохранить загруженные` explicitly saves compatible temporary image inputs already present in the current generation draft.

The trusted internal API accepts a save request only when the temporary key is under exactly `inputs/<authenticated-user-id>/`. It reads the private file, validates it as an image, computes/uses SHA-256 metadata, reserves the owner's item/byte quota in PostgreSQL and copies bytes into private S3 storage under `references/<user-id>/<uuid>.<ext>`.

The PostgreSQL `reference_assets` row moves from `uploading` to `active` only after the S3 write succeeds. On a caught storage failure, the row becomes `failed` and any partial object is deleted best-effort. Within one owner's active library, identical bytes are de-duplicated by SHA-256 and the existing durable asset is reused.

After a direct memory upload is promoted successfully, its temporary `inputs/` staging file is deleted.

## Durable reference deletion

Deletion is not ordinary draft cleanup. It is an explicit owner action:

```text
active -> delete_pending
       -> reference.delete outbox event
       -> worker deletes private S3 object
       -> deleted
```

`delete_pending` assets disappear immediately from list/resolve. The shared durable outbox lets the worker retry S3 deletion without keeping Telegram open. The S3 delete operation and final metadata transition are idempotent.

## Private storage invariant

Telegram users and public clients never receive:

- local filesystem paths;
- S3 credentials;
- permanent object URLs;
- permanent provider URLs.

Temporary inputs use fresh local signed URLs with `FOXGEN_TELEGRAM_INPUT_PRESIGNED_URL_TTL_SECONDS`. Durable saved references use fresh private S3 signed URLs with `FOXGEN_REFERENCE_MEMORY_PRESIGNED_URL_TTL_SECONDS` for preview/provider reads.

Redis stores only saved reference UUIDs, not signed URLs. Immediately before paid admission the bot asks the owner-scoped internal API to re-resolve all durable UUIDs; deleted, inactive or foreign references fail closed before provider submission.

## Input error classification

### Permanent validation failures

Examples:

- media group/album;
- unsupported media kind;
- empty/invalid file;
- input larger than configured maximum;
- exceeding the selected model/scenario reference limit;
- trying to save a non-image into durable reference memory;
- trying to save a temporary key outside `inputs/<authenticated-user-id>/`;
- exceeding the owner's reference-memory item or total-byte quota.

The user receives an actionable response and remains in a recoverable flow. No provider side effect exists at this stage.

### Retryable Telegram transfer failure

A Telegram download/network failure is distinct from invalid content. FSM does not pretend the input was stored.

### Retryable temporary-storage failure

Failure while writing private local input bytes prevents the generation draft from advancing.

### Retryable durable-storage failure

Failure while copying an explicitly saved reference into S3 prevents the row from becoming `active`. The save path records failure and cleans the partial durable object best-effort.

### Cleanup failure

Best-effort temporary cleanup failure is observable but must not convert a safe menu/reset into a provider operation. Local retention is the orphan safety net for temporary files. Durable reference deletion instead uses the shared outbox and worker retry path.

## Quick Start ownership

Quick Start stores only temporary input keys. When it converges into the ordinary generation wizard, the same private keys become prefilled `media`; they are not copied again.

A compatible temporary image may then be explicitly saved into durable reference memory. The normal Quick Start Back/edit behavior retains temporary ownership until an explicit clear/replacement/reset path.

## Mixed drafts

A generation draft may contain both locator types:

```json
{"kind": "image", "storage_key": "inputs/42/temporary.png"}
{"kind": "image", "reference_id": "7a39..."}
```

Temporary inputs and durable saved references participate in the same current model/scenario limits. For first+last video, order in the draft determines first/last frame. For multimodal video, saved memory contributes image references while temporary uploads may contribute images, video and audio.

Global cleanup helpers look only for `storage_key` values under `inputs/`; a durable `reference_id` is never interpreted as a disposable temporary file.

## Media groups

Telegram albums are rejected before any member is downloaded. Users add supported references as individual messages or select multiple durable saved images in reference memory. This avoids ambiguous album ordering, partial ingestion and duplicate races.

## Verification checklist

### Temporary inputs

1. Send one supported Telegram file; verify an `inputs/<user>/...` private file exists.
2. Verify the live generation control updates rather than stacking keyboards when Telegram permits editing.
3. Press `🔄 Перезагрузить`; verify temporary keys are deleted and saved library objects, if any, remain untouched.
4. Press image `⏭ Пропустить`; verify temporary references are deleted and saved references are detached only.
5. `/start` or `/menu`; verify temporary cleanup is attempted and durable memory survives.
6. Send an album; verify no member is stored.
7. Simulate Telegram/local-storage failure; verify no false successful transition.

### Durable reference memory

1. Save one image; verify an active `reference_assets` row and one private `references/<user>/...` object.
2. Reopen `/menu`/start a new generation; verify the same reference remains available.
3. Save identical bytes again; verify the existing active asset is reused.
4. Attempt to save another user's `inputs/<other-user>/...` key; verify fail-closed authorization.
5. Fill item/byte quota; verify additional save is rejected before durable activation.
6. Select multiple saved images and reuse them in compatible image/video flows; verify model/scenario limits and first+last order.
7. Delete one saved image; verify immediate disappearance from resolve/list, worker S3 deletion and final `deleted` state.
8. Keep its UUID in an old Redis draft; verify final resolve rejects it before provider admission.

### Infrastructure

1. Verify `bot` and `api` mount the same private temporary input volume.
2. Verify `/v1/input-media/...` signed access works and expires.
3. Verify S3/MinIO bucket stays private while signed `references/` reads work.
4. Verify the MinIO `inputs/` lifecycle rule never matches `references/` or `generations/`.
5. Verify `foxgen-worker` can delete `references/` objects.

## Incident handling

For abandoned `inputs/` files, use the existing retention/runbook path. Do not delete the entire shared volume.

For durable reference incidents, inspect PostgreSQL row status and the corresponding `reference.delete` outbox event before changing S3 manually. `uploading` should normally be short-lived; `delete_pending` indicates metadata is already hidden and storage cleanup is awaiting/retrying worker execution. Never reactivate/delete rows solely to silence an alarm without reconciling the private object.

## Related docs

- `reference-memory.md` — durable library domain, quotas, API and deletion lifecycle;
- `telegram-flows.md` — generation/reference-memory FSM and UX;
- `configuration.md` — temporary and durable media settings;
- `database-schema.md` — `reference_assets` ownership/state;
- `architecture.md` — storage and trust boundaries;
- `production-deploy.md` — production startup/migration gating;
- `minio-lifecycle-runbook.md` — temporary `inputs/` lifecycle bootstrap and recovery.
