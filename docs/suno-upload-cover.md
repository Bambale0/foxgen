# Suno V5 Upload & Cover

FoxGen exposes Suno V5 Upload & Cover as an owner-scoped paid product in Telegram and Happy Fox. The public client never supplies a trusted provider URL. It uploads audio into FoxGen private input storage and submits only the resulting owner-bound storage key.

## Provider contract

Reviewed KIE operation:

```text
POST /api/v1/generate/upload-cover
model = V5
```

FoxGen stores the model as `suno-v5-upload-cover` with `api_family=suno_upload_cover`.

Supported modes:

```text
simple
  input_storage_key
  custom_mode = false
  instrumental = false
  prompt <= 500

custom vocal
  input_storage_key
  custom_mode = true
  instrumental = false
  prompt <= 5000
  style <= 1000
  title <= 100

custom instrumental
  input_storage_key
  custom_mode = true
  instrumental = true
  style <= 1000
  title <= 100
  prompt may be empty
```

Optional advanced custom-only values remain server-validated and bounded by the reviewed contract.

Simple mode intentionally does not expose the instrumental/custom controls. The client sends `instrumental=false`, empty style/title/advanced fields and only the prompt plus owner storage key.

## Ownership and provider URL boundary

The durable generation payload contains an internal storage key, never `uploadUrl`:

```json
{
  "input_storage_key": "inputs/miniapp/<user-id>/<opaque-file>",
  "custom_mode": true,
  "instrumental": false,
  "prompt": "...",
  "style": "...",
  "title": "..."
}
```

Before paid admission the owner service verifies:

- the key belongs to the authenticated user's input prefix;
- the object exists;
- the object is within FoxGen input-size limits;
- the stored content type is `audio/*`.

Alembic revision `20260817_0017` adds a PostgreSQL owner-prefix guard for `suno-v5-upload-cover` generation rows. A future/internal caller cannot successfully commit a generation using another user's input key through generic task admission.

Immediately before the provider POST, the worker re-opens the private input metadata and creates a fresh short-lived signed FoxGen URL. Only that URL is mapped to KIE `uploadUrl`. `input_storage_key` itself is never sent to KIE.

If the input was deleted, expired or no longer resolves as audio before the provider side effect, submission fails deterministically through the normal generation/refund lifecycle.

## Duration limitation

KIE documents a maximum uploaded-audio duration of 8 minutes. FoxGen's current private upload contour has reliable content type, byte size and ownership metadata but does not derive trustworthy audio duration. Therefore FoxGen cannot claim local duration rejection yet; KIE remains authoritative for the 8-minute duration check.

Do not infer duration from byte size. A future media-probe slice should add durable duration metadata and pre-admission validation before changing this limitation.

## Telegram flow

```text
Создать музыку
  -> Cover из аудио
  -> upload audio / voice / audio document
  -> simple | custom

simple
  -> prompt
  -> price/balance
  -> submit

custom
  -> vocal | instrumental
  -> prompt when vocal
  -> style
  -> title
  -> price/balance
  -> submit
```

`/menu` and cancel clear the FSM and delete unsubmitted temporary input through the existing input-media cleanup boundary. After a generation is admitted, the uploaded source is retained until the worker has resolved the provider side effect; normal retention cleanup handles the temporary object afterwards.

No price is embedded in the bot. Missing active `model_prices` for `suno-v5-upload-cover` keeps the confirmation fail-closed.

## Happy Fox flow

`/mini-app/suno-upload-cover.js` adds a Music action without exposing the low-level raw model row.

1. Authenticate through Telegram Mini App JWT.
2. Select an `audio/*` file.
3. Choose simple or custom mode.
4. In simple mode, only prompt is shown.
5. In custom mode, choose instrumental/vocal and provide the relevant style/title/prompt fields.
6. Read price and balance from `/v1/miniapp/bootstrap`.
7. Upload the bytes to `/v1/miniapp/input-media`.
8. Submit the owner key through `/v1/miniapp/music/suno/upload-cover` with `Idempotency-Key`.

Replacing/closing an unsubmitted file requests deletion. Submitted input is not deleted client-side because the worker still needs it.

## Billing and lifecycle

Upload & Cover reuses the standard paid lifecycle:

```text
owner verification
  -> active price lookup
  -> atomic CREDIT reserve
  -> generation.submit outbox
  -> worker resolves fresh uploadUrl
  -> KIE upload-cover POST
  -> capture reservation after provider acceptance
  -> poll/result normalization
  -> archive all canonical audio tracks
  -> Telegram delivery
  -> SUCCEEDED
```

Provider helper URLs (`sourceAudioUrl`, stream URLs, artwork) are not promoted to result assets. Only canonical generated audio URLs are archived through FoxGen storage.

## Required tests

Release CI must cover:

- strict simple/custom contract validation;
- rejection of external/provider URL fields;
- foreign owner and non-audio input rejection before paid submission;
- Alembic `0017` upgrade/schema/downgrade/re-upgrade;
- real PostgreSQL generic-task bypass rejection without wallet/reservation/ledger/outbox effects;
- worker-side fresh `uploadUrl` generation and absence of `input_storage_key` in KIE body;
- deterministic missing-input failure before external provider POST;
- Telegram simple/custom FSM and fail-closed pricing;
- Happy Fox private upload, simple/custom UI and no direct KIE access;
- cross-layer E2E through owner upload -> paid admission -> KIE Upload & Cover -> two generated MP3 assets -> archive/delivery -> `SUCCEEDED`;
- production image and Trivy gates.

Only external KIE/media/Telegram network boundaries may be faked in E2E. FoxGen HTTP/auth, PostgreSQL billing, outbox, lifecycle and ownership checks remain real.

## Rollback

Do not downgrade `20260817_0017` while code that advertises Upload & Cover remains deployed. Removing the guard before removing the product re-opens generic task admission to unverified input-storage keys.

A safe rollback order is:

1. disable/remove the Upload & Cover user entrypoints;
2. disable `suno-v5-upload-cover` submission;
3. drain/reconcile in-flight generations;
4. deploy code that no longer depends on the guard;
5. only then downgrade the migration if required.
