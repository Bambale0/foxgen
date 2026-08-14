# Telegram flows and FSM

FoxGen uses aiogram 3 with Redis-backed FSM. Telegram handlers own only conversational drafts and screen navigation; durable admission, billing, provider execution and delivery remain in the internal API/worker lifecycle.

## Global `/start` and `/menu`

`foxgen-global-commands` is the first runtime router. `/start` and `/menu` therefore interrupt **every** active generation screen before any state-specific text/media handler can consume the command.

The interrupt contract is:

1. collect all known temporary input keys from FSM data;
2. best-effort delete those temporary files;
3. clear Redis state/data;
4. open the canonical main menu.

Regression tests enumerate every declared `GenerationStates` value, so adding a new screen cannot silently weaken this rule.

## Screen-FSM design

The normal image/video UX follows the proven screen pattern used in `banano_kling:tanyapi`:

```text
screen = renderer + keyboard + state + transitions
```

All temporary choices live in `FSMContext`. There are no process-global per-user draft dictionaries. A draft stores a stable `wizard_version`, a visible `*_flow_step`, selected UI model, model-specific settings, temporary media keys, prompt, idempotency key and the latest price/balance result.

Capabilities and provider payload construction are separate from Telegram rendering:

```text
generation_capabilities.py  -> which screens/options a model supports
generation_draft.py         -> stable draft + validation + provider payload
generation_screens.py       -> text/keyboards for each user-visible screen
generation_wizard.py        -> transitions only
```

## Create image

New image flow:

```text
main menu -> Создать фото
  -> 1/4 model
  -> 2/4 optional references
  -> 3/4 dynamic model settings
  -> 4/4 prompt
  -> live price + balance confirmation
  -> authenticated paid admission
```

### Image UI models

The UI model is intentionally separate from the provider slug. For example, the user sees one `Seedream 5 Pro` choice:

- no references -> `seedream-5-pro`;
- one or more references -> `seedream-5-pro-edit`.

This removes a redundant text/edit mode screen while preserving the provider's distinct validated contracts.

Current production wizard coverage is required by test to equal the production-enabled KIE submission allowlist. The wizard currently covers:

```text
seedream-5-pro
seedream-5-pro-edit
nano-banana-2
nano-banana-pro
seedance-2
seedance-2-mini
```

### Dynamic image settings

Settings are capability-driven and update on the same screen.

Examples:

- Seedream 5 Pro: supported aspect ratios, Basic/High quality, PNG/JPG;
- Nano Banana 2/Pro: supported aspect ratios including auto, 1K/2K/4K, PNG/JPG.

A model never receives a UI option that is absent from its verified local provider contract.

## Create video

New video flow:

```text
main menu -> Создать видео
  -> 1/5 model
  -> 2/5 input type
  -> 3/5 media when required
  -> 4/5 dynamic model settings
  -> 5/5 prompt
  -> live price + balance confirmation
  -> authenticated paid admission
```

### Video input types

For Seedance 2 / Seedance 2 Mini the wizard exposes the verified input modes:

```text
text
first_frame
first_last
references
```

`first_last` preserves upload order: the first uploaded image becomes `first_frame_url`, the second becomes `last_frame_url`.

Multimodal references are separated before provider admission into image/video/audio URL lists. The local contract enforces per-type and total limits before a billable provider request exists.

### Dynamic video settings

The Seedance screen exposes only verified options:

- aspect ratio;
- duration 5/10/15 seconds;
- resolution supported by the contract;
- generated audio;
- return last frame;
- web search.

A setting toggle updates FSM data and re-renders the same screen rather than creating another one-off state.

## Quick Start convergence

Quick Start still owns the fastest reference ingestion path:

```text
main menu -> Быстрый запуск
  -> upload one photo/video
  -> choose desired result: image/video
  -> same generation screen wizard as ordinary creation
```

The uploaded local input is not downloaded again or copied. It becomes prefilled `media` in the wizard draft.

Default video interpretation:

- image reference -> `first_frame`;
- video reference -> multimodal `references`.

If the user switches to a compatible video input type, the prefilled reference survives. If the new type cannot accept the stored media, the old temporary file is deleted before the state changes.

Quick Start also preserves its original reference metadata so Back from the first wizard model screen can return to the image/video product choice while the source is still valid. Abandoning an invalid/cleared Quick Start draft cleans all known reference keys.

Legacy `reference_choosing_model` / generic generation states remain temporarily declared and routed **after** the new wizard so Redis drafts created by an older deployed release can still recover instead of becoming unknown state names.

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

Shared terminal conversational states:

```text
confirming
submitting
```

`fsm_contract.py` defines success/back/cancel/timeout/invalid/stale behavior for every declared state.

## Back / invalid input / stale callback

Each new screen has an explicit backwards edge:

```text
image model <- references <- settings <- prompt <- confirmation
video model <- type <- media/settings <- settings <- prompt <- confirmation
```

For text-only video, Back from settings returns to input type because there is no media screen.

Invalid messages do not destroy a valid draft. Button-only screens tell the user to use the current buttons; media screens restate their exact media requirement; prompt screens request text. An unrelated stale callback keeps a known active state and points the user to the latest controls.

## Confirmation and billing

Confirmation does not synthesize a provider payload just to calculate price. It resolves the final provider model slug from the current draft, then reads current price and wallet balance through the trusted internal API.

Launch is enabled only when:

- the current model has an active price;
- the wallet has enough available units;
- the draft remains valid.

At final launch, private local storage keys are converted to fresh signed URLs and only then is the strict provider payload constructed.

Paid admission remains unchanged:

```text
authenticated internal request
  -> model/runtime validation
  -> idempotency
  -> rate/concurrency limits
  -> atomic price/balance reservation
  -> generation + durable submit outbox
```

The Telegram wizard never calls KIE directly and never performs its own wallet mutation.

## Duplicate confirmation

Each draft owns one stable `idempotency_key`. During `submitting`, repeated launch presses are rejected conversationally; the internal API/PostgreSQL idempotency boundary remains the durable final guard if transport ambiguity occurs.

## Media safety

- one Telegram message equals one upload operation;
- albums/media groups are rejected before download;
- unsupported documents fail as user validation errors;
- input size is bounded by `FOXGEN_TELEGRAM_INPUT_MAX_BYTES`;
- upload/storage failures do not advance the screen;
- temporary files stay private and are cleaned on `/start`, `/menu`, cancel and explicit replacement/clear paths;
- signed provider-readable URLs are generated only near final admission.

See `input-media-lifecycle.md`.

## Runtime router order

Router order is a correctness contract:

```text
foxgen-global-commands
foxgen-admin-extras
foxgen-admin
foxgen-quick-start-wizard
foxgen-generation-wizard
foxgen-quick-start
foxgen-generation
foxgen-shell
```

Reasons:

- global commands must preempt every FSM;
- Quick Start bridge must intercept post-upload product/back actions before legacy Quick Start handlers;
- the new generation wizard must own ordinary `create:image`, `create:video`, its settings/back/confirmation callbacks before the generic legacy generation router;
- legacy routers remain reachable only for older Redis drafts and unchanged reference ingestion paths;
- shell catch-all remains last.

`register_runtime_routers()` and its regression test protect this ordering.

## `/admin`

`/admin` remains a separate privileged Telegram shell. Every privileged callback/FSM continuation re-authorizes through the signed server-side admin API; screen-wizard work does not bypass or alter that boundary.

## Testing expectations

The generation screen change is incomplete unless tests preserve:

- `STATE_CONTRACTS == all declared GenerationStates`;
- `/start` interruption for every declared state;
- exact runtime router order;
- wizard provider-slug coverage equals all production-enabled KIE submission models;
- Seedream text/edit slug selection by reference presence;
- per-model dynamic settings visibility;
- first/last frame order;
- multimodal reference separation;
- media-completion rules;
- Quick Start reference preservation into the same wizard;
- price/balance gating and existing submission idempotency tests.
