# Suno V5 Upload & Extend

This runbook documents the executable FoxGen `suno-v5-upload-extend` product slice.

## User flow

Telegram and Happy Fox both keep the source audio private inside FoxGen.

1. The user uploads one supported audio file.
2. FoxGen stores it under an owner-scoped `input_storage_key`.
3. The user selects either default/quick continuation or custom continuation.
4. FoxGen validates the owner input and model contract before paid admission.
5. Shared billing reserves the published CREDIT price; no commercial price is hardcoded in this product.
6. The generation worker re-checks the private input and creates a fresh short-lived provider URL immediately before the KIE request.
7. KIE receives the provider URL, never FoxGen's durable `input_storage_key`.
8. Generated tracks enter the common result-normalization, archive and Telegram delivery pipeline.

## Provider routing

Model slug: `suno-v5-upload-extend`

Provider model: `V5`

API family: `suno_upload_extend`

KIE endpoint: `POST /api/v1/generate/upload-extend`

Task polling uses the existing dedicated Suno record-info endpoint and canonical Suno multi-track normalization.

## Input contract

### Default mode

`default_param_flag=false` stores only the owner input plus prompt. FoxGen forces `instrumental=false` and does not emit custom-only fields in the provider request.

Required:

- `input_storage_key` — FoxGen-owned private input identity;
- `prompt`.

### Custom mode

`default_param_flag=true` requires:

- `style`;
- `title`;
- positive `continue_at`;
- `prompt` when `instrumental=false`.

Optional reviewed fields:

- `negative_tags`;
- `vocal_gender` (`m` or `f`);
- `style_weight`, `weirdness_constraint`, `audio_weight` in `[0, 1]`;
- `persona_id`.

Unknown fields are rejected by the strict Pydantic contract.

## Trust boundary

Public clients must never supply a provider `uploadUrl`.

The durable generation payload contains `input_storage_key`, which must belong to the generation user. The application service verifies owner prefix, object existence, non-empty byte size and `audio/*` type before shared paid admission.

PostgreSQL revision `20260817_0018` adds `trg_generations_suno_upload_extend_input`. It rejects a forged `suno-v5-upload-extend` generation if a future caller attempts to bypass the dedicated owner service through generic task admission.

The worker/provider adapter repeats existence/audio validation and creates the short-lived provider URL immediately before the billable POST.

## Duration boundary

KIE documents a maximum uploaded-audio duration of 8 minutes for the Upload & Extend endpoint. Custom `continueAt` must be greater than zero and lower than source duration.

FoxGen currently has reliable owner/content-type/byte-size metadata but does not derive trustworthy audio duration for private uploads. Therefore:

- FoxGen validates `continue_at > 0` locally;
- KIE remains authoritative for the upper source-duration bound;
- do not claim local 8-minute/duration enforcement until a media-probe metadata slice is implemented.

## Billing and lifecycle

Admission reuses the normal `SubmissionService` and billing-aware repository. Missing price, insufficient balance, invalid owner input or invalid contract fails before provider submission.

Expected successful state path:

`QUEUED -> SUBMITTING -> SUBMITTED -> RESULT_READY -> STORING_MEDIA -> DELIVERY_PENDING -> SUCCEEDED`

The reservation is captured once on successful provider completion. Multiple canonical Suno generated audio tracks are archived and delivered; source/helper/stream/artwork URLs are excluded from canonical result media.

## Cross-layer E2E

`tests/e2e/test_suno_upload_extend_e2e.py` exercises:

- Telegram-derived Mini App JWT;
- private `audio/mpeg` upload;
- foreign-owner rejection;
- paid owner submission;
- worker routing to `/api/v1/generate/upload-extend`;
- a provider request containing a fresh `uploadUrl` but no `input_storage_key`;
- two generated result tracks;
- archive and Telegram delivery;
- final `SUCCEEDED` state;
- captured CREDIT reservation and immutable ledger balance.

Only the external KIE HTTP transport is mocked. PostgreSQL, application services, HTTP routing, JWT boundary, billing, outbox, lifecycle and media pipeline remain real.

## CI requirement

The release gate must propagate the actual exit status of every command piped through `tee`. CI uses `set -o pipefail` for Ruff, mypy, unit, integration and E2E pytest steps. A missing/failed collection therefore fails the job rather than producing a false green run.

## Rollback

Application rollback can return to the previous image while the database remains on revision `20260817_0018`; the trigger affects only `suno-v5-upload-extend` rows.

If a full schema rollback is explicitly required and no new Upload & Extend generation depends on the guard, run one Alembic downgrade to remove the trigger/function and return to `20260817_0017`.

Do not disable the owner guard while the product remains enabled for paid submission.
