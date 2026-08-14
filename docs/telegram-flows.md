# Telegram flows and FSM

FoxGen uses aiogram 3 with Redis-backed FSM. Telegram handlers own only conversational drafts and screen navigation; durable admission, billing, provider execution, reference-memory ownership and delivery remain in the internal API/PostgreSQL/worker lifecycle.

## Global `/start` and `/menu`

`foxgen-global-commands` is the first runtime router. `/start` and `/menu` therefore interrupt **every** active generation or reference-memory screen before any state-specific text/media handler can consume the command.

The interrupt contract is:

1. collect all known temporary `inputs/` keys from FSM data;
2. best-effort delete those temporary files;
3. clear Redis state/data;
4. open the canonical main menu.

Durable saved references are never deleted by this reset path. Regression tests enumerate every declared `GenerationStates` value, so adding a new screen cannot silently weaken the global interrupt rule.

## Screen-FSM design

The normal image/video UX follows a compact screen contract derived from the proven `banano_kling` `v7_kate` interaction pattern:

```text
screen = renderer + keyboard + state + transitions
```

User-facing generation screens are single-purpose and are not numbered `1/4`, `2/4`, `1/5`, and so on. Titles describe the current action directly, for example:

```text
🖼 Создание фото
🎬 Создание видео
📎 Референсы
⚙️ Параметры фото / видео
📝 Промпт для фото / видео
✅ Проверьте генерацию
```

All temporary choices live in `FSMContext`. There are no process-global per-user draft dictionaries. A draft stores a stable `wizard_version`, a visible `*_flow_step`, selected UI model, model-specific settings, temporary media keys and/or durable reference UUIDs, prompt, idempotency key, the latest price/balance result and, while useful, the Telegram chat/message id of the current control screen.

The remembered control-message id is presentation state only. It does not own media and is never durable business state. If Telegram can no longer edit that message, the bot creates one replacement control message and remembers the new id.

Capabilities and provider payload construction are separate from Telegram rendering:

```text
generation_capabilities.py  -> which screens/options a model supports
generation_draft.py         -> stable draft + validation + provider payload
generation_screens.py       -> text/keyboards for each user-visible screen
generation_wizard.py        -> ordinary wizard transitions
reference_memory.py          -> saved-reference browser + reference-aware transitions
```

## Compact reference-screen contract

Image and video reference/media screens use the same visual hierarchy:

```text
📎 Референсы

Загружено: X/Y
<short instruction for the selected model/scenario>

[        Загружено: X/Y        ]
[ ⏭ Пропустить ] [ ✅ Продолжить ]   # when skipping is valid
[ 📚 Память реф ] [ 🔄 Перезагрузить ]
[          ⬅️ Назад            ]
```

Important behavior:

- `X/Y` is live and re-rendered after accepted uploads or memory selection;
- `Y` comes from FoxGen capability/contract data, not from a global hard-coded value;
- `🔄 Перезагрузить` removes all references from the current draft and deletes only its temporary `inputs/` objects;
- image `⏭ Пропустить` means continue **without** references; temporary files are deleted first, durable library assets are only detached from the draft;
- required video scenarios keep `✅ Продолжить` visible for a stable layout, but pressing it before the required media is complete returns the exact requirement and does not advance state;
- `⬅️ Назад` is the only persistent bottom navigation button on generation sub-screens;
- `/start` and `/menu` remain the global safe reset/exit paths.

After an upload, FoxGen tries to edit the remembered control message instead of sending another keyboard block. The memory browser itself uses one replaceable preview/control message and removes the previous preview when navigating.

## Durable `📚 Память реф`

`📚 Память реф` opens a private, owner-scoped saved-image library. Durable metadata belongs to PostgreSQL and durable bytes belong to private S3-compatible storage under `references/<user>/...`; Redis stores only the browser cursor, transient selection and reference UUIDs used by the current draft.

The browser supports:

```text
private image preview
selected X/Y
previous / next
select / unselect
➕ add photo
💾 save currently uploaded temporary images  # when present
🗑 delete with confirmation
✅ use selected
⬅️ back without applying changes
```

Saving is explicit. A normal Telegram upload remains temporary until the user chooses `➕ Добавить фото` inside memory or `💾 Сохранить загруженные`. The internal API accepts only a temporary key under the authenticated user's own `inputs/<user-id>/` prefix, reserves quota, de-duplicates identical active bytes by SHA-256 for that owner, copies the image into durable private S3 storage and activates the PostgreSQL row only after storage succeeds.

Selection is constrained by the current generation capability before it can be applied:

- image models: `max_references`;
- first-frame video: one image total;
- first+last-frame video: two ordered images total;
- multimodal video: both global total-reference and per-model image-reference limits;
- text-only video: memory is not exposed because the scenario accepts no image input.

For first+last-frame video, selection order is frame order. Existing temporary inputs remain first, followed by saved references in the order selected.

Deletion changes the durable row to `delete_pending`, hides it immediately from list/resolve, and writes a deduplicated `reference.delete` outbox event. `foxgen-worker` performs idempotent S3 deletion and marks the row `deleted`.

An old Redis draft may still contain a UUID that was deleted in another flow. Final confirmation therefore re-resolves every durable reference through the owner-scoped internal API immediately before payload construction. A missing, deleted or foreign UUID fails closed before provider submission.

See `reference-memory.md` for quotas, storage and recovery details.

## Create image

Image flow:

```text
main menu -> Создать фото
  -> model
  -> optional temporary/saved references with live X/Y
  -> dynamic model settings
  -> prompt
  -> live price + balance confirmation
  -> re-resolve saved refs + fresh signed URLs
  -> authenticated paid admission
```

### Image UI models

The UI model is intentionally separate from the provider slug. For example, the user sees one `Seedream 5 Pro` choice:

- no references -> `seedream-5-pro`;
- one or more references -> `seedream-5-pro-edit`.

Current reference limits are capability-driven:

- Seedream 5 Pro: up to 10 image references;
- Nano Banana 2: up to 14 image references;
- Nano Banana Pro: up to 14 image references.

Current production wizard coverage is required by test to equal the production-enabled KIE submission allowlist:

```text
seedream-5-pro
seedream-5-pro-edit
nano-banana-2
nano-banana-pro
seedance-2
seedance-2-mini
```

### Dynamic image settings

Settings are capability-driven and update on the same control message. Seedream exposes only its verified aspect ratios/quality/formats; Nano Banana exposes its verified aspect ratios/resolutions/formats. A model never receives a UI option absent from its verified local provider contract.

## Create video

Video flow:

```text
main menu -> Создать видео
  -> model
  -> input type
  -> temporary/saved media screen when required
  -> dynamic model settings
  -> prompt
  -> live price + balance confirmation
  -> re-resolve saved refs + fresh signed URLs
  -> authenticated paid admission
```

### Video input types

For Seedance 2 / Seedance 2 Mini the wizard exposes the verified modes:

```text
text
first_frame
first_last
references
```

The live media limit follows the scenario:

- `first_frame`: 1 image;
- `first_last`: 2 ordered images;
- `references`: up to the local total multimodal reference limit (currently 6), additionally constrained by per-type model limits.

Multimodal references are separated before provider admission into image/video/audio URL lists. Saved memory currently contributes image references; temporary uploads can still contribute image/video/audio. The local contract enforces per-type and total limits before a billable provider request exists.

### Dynamic video settings

The Seedance screen exposes only verified options: aspect ratio, 5/10/15-second duration, supported resolution, generated audio, return-last-frame and web search. A toggle updates FSM data and re-renders the same screen.

## Quick Start convergence

Quick Start remains the fastest temporary reference-ingestion path:

```text
main menu -> Быстрый запуск
  -> upload one photo/video
  -> choose desired result: image/video
  -> same generation screen wizard as ordinary creation
```

The uploaded local input is not downloaded again or copied. It becomes prefilled temporary `media`. The user may then explicitly save compatible temporary image inputs into reference memory from the reference screen.

Default video interpretation:

- image reference -> `first_frame`;
- video reference -> multimodal `references`.

If a new video input type cannot accept existing media, only temporary input keys are deleted; durable saved-reference assets are detached from the draft and remain in the library.

Legacy reference/generic generation states remain routed after the new screens so older Redis drafts can recover.

## Declared generation FSM states

Current screen states:

```text
image_selecting_model
image_uploading_references
image_configuring
image_waiting_prompt
video_selecting_model
video_selecting_type
video_uploading_media
video_configuring
video_waiting_prompt
reference_memory_browsing
reference_memory_adding
```

Quick Start/reference compatibility states:

```text
quick_start_waiting_media
reference_choosing_product
reference_choosing_model
reference_waiting_prompt
```

Migration-compatibility generic states:

```text
choosing_mode
choosing_model
waiting_prompt
waiting_media
choosing_aspect_ratio
choosing_quality
choosing_duration
choosing_audio
```

Shared terminal states:

```text
confirming
submitting
```

`fsm_contract.py` defines success/back/cancel/timeout/invalid/stale behavior for every declared state.

## Back / invalid input / stale callback

Each normal generation screen has an explicit backwards edge. Reference-memory Back returns to the originating generation reference screen **without applying the transient browser selection**. Adding a new memory photo has its own Back edge to the browser.

Invalid messages do not destroy a valid draft. Button-only screens tell the user to use current controls; media screens restate exact requirements; the memory add screen accepts one photo/image document; prompt screens request text. An unrelated stale callback keeps a known active state and points the user to the latest controls.

## Confirmation and billing

Confirmation resolves final provider model slug, current price and wallet balance through trusted internal services. Launch is enabled only when price, balance and draft are valid.

At final launch:

1. temporary `storage_key` inputs become fresh signed local URLs;
2. durable `reference_id` inputs are owner/active-state re-resolved through `/v1/reference-memory/resolve` to fresh signed S3 URLs;
3. the ordinary strict provider payload is built;
4. authenticated paid admission performs idempotency, limits and atomic balance reservation.

The memory browser never calls KIE and never mutates a wallet.

## Duplicate confirmation

Each draft owns one stable `idempotency_key`. During `submitting`, repeated launch presses are rejected conversationally; the internal API/PostgreSQL idempotency boundary remains the durable final guard.

## Media safety

- one Telegram message equals one upload operation;
- albums/media groups are rejected before download;
- unsupported documents fail as user validation errors;
- temporary input size is bounded by `FOXGEN_TELEGRAM_INPUT_MAX_BYTES`;
- save/list/delete memory operations create no provider side effect;
- temporary files stay private and are cleaned on `/start`, `/menu`, reset/reload, replacement and explicit save staging cleanup;
- saved references stay private and survive FSM expiry/reset/redeploy until owner deletion;
- `inputs/` cleanup ignores durable `reference_id` locators;
- private S3 URLs are short-lived and generated on demand;
- final saved-reference ownership/state validation occurs before provider admission.

See `input-media-lifecycle.md` and `reference-memory.md`.

## Runtime router order

Router order is a correctness contract:

```text
foxgen-global-commands
foxgen-admin-extras
foxgen-admin
foxgen-quick-start-wizard
foxgen-reference-memory
foxgen-generation-wizard
foxgen-quick-start
foxgen-generation
foxgen-shell
```

Reasons:

- global commands preempt every FSM;
- Quick Start bridge handles its post-upload convergence;
- reference-memory owns its browser states and must intercept reference-aware clear/type/final-confirm callbacks before the generic generation wizard;
- generation wizard owns ordinary generation controls;
- legacy routers remain reachable only for older Redis drafts;
- shell catch-all stays last.

`register_runtime_routers()` and its regression test protect this ordering.

## `/admin`

`/admin` remains a separate privileged Telegram shell. Reference memory does not relax signed admin API, RBAC or audit boundaries.

## Testing expectations

Reference memory/generation work is incomplete unless tests preserve:

- `STATE_CONTRACTS == all declared GenerationStates`;
- `/start` interruption for every declared state;
- exact runtime router order including `foxgen-reference-memory` before the ordinary wizard;
- compact reference keyboard and live model/scenario counters;
- owner-scoped temporary-save and durable resolve/delete;
- reference item/byte quotas and checksum de-duplication;
- saved-reference preview/navigation/multi-selection/delete/apply controls;
- temporary-vs-durable cleanup separation;
- Seedream text/edit slug selection by reference presence;
- first/last-frame ordering;
- multimodal total/per-kind limits;
- stale/deleted durable reference fail-closed behavior before paid admission;
- price/balance gating and existing submission idempotency tests.
