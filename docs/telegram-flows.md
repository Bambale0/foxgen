# Telegram flows and FSM

FoxGen uses aiogram 3 with Redis-backed FSM. Telegram handlers are transport/orchestration code; durable admission, billing and administrative writes are delegated to application/admin services or the internal API.

## Main menu

The current main menu exposes active image/video generation actions plus the broader product map. Quick Start is the fastest reference-driven entrypoint. Some menu sections may still be planned product surfaces; documentation must not treat a visible placeholder callback as an implemented generator.

`/start` and `/menu` clear the active user draft and return to the current main menu.

## Standard generation flow

```text
main menu
  -> image or video
  -> generation mode
  -> compatible model
  -> prompt
  -> required media inputs
  -> aspect ratio
  -> model-specific quality/duration/audio options
  -> price + available balance preview
  -> confirmation
  -> authenticated internal API admission
```

The launch button is enabled only after the draft is valid and price/balance checks succeed.

## Quick Start

Quick Start lets a user begin from a reference before choosing the product/model.

```text
main menu -> Быстрый запуск
  -> send one photo or video
  -> object is stored privately
  -> "what create: image or video?"
  -> compatible model
  -> prompt/caption reuse
  -> model settings
  -> confirmation
```

The same reference entry also works when a photo/video is sent while no FSM is active. The bot determines the media kind, stores it and enters the reference-product chooser instead of falling through to the generic menu.

### Image reference

An image reference can route to image editing or image-to-video according to model capability.

### Video reference

A video can route to compatible reference-to-video behavior. For image creation, FoxGen can use a Telegram-provided video thumbnail/cover when available. If Telegram did not provide a suitable cover, the user is asked to send the required frame as a separate photo; the bot does not silently pass a video URL to an image model.

## Reference draft preservation

Reference-prefilled navigation is explicit through `entrypoint=reference`. Back/edit actions preserve:

- the original object storage key;
- optional preview/thumbnail key;
- selected model;
- prompt when already entered;
- applicable model settings.

The bot does not infer reference semantics just because a media list is non-empty.

## Declared generation FSM states

```text
quick_start_waiting_media
reference_choosing_product
reference_choosing_model
reference_waiting_prompt
choosing_mode
choosing_model
waiting_prompt
waiting_media
choosing_aspect_ratio
choosing_quality
choosing_duration
choosing_audio
confirming
submitting
```

`fsm_contract.py` defines behavior expectations for every declared state.

## Required state behavior

Every state has an explicit contract for:

- valid next transitions;
- back;
- cancel/menu;
- timeout/expiry;
- invalid message/input;
- stale callback.

Known active state is preserved when a user presses an unrelated old button or sends input that belongs to another step. A missing/expired Redis state recovers to the menu with an expiry explanation. An unknown state name left by old deployed code is cleared fail-closed.

## Concurrency and duplicate protection

Redis event isolation serializes updates for one FSM storage key. Two near-simultaneous reference messages from one user therefore cannot both observe the same empty state and race through upload/state mutation.

Paid generation confirmation also has a stable draft idempotency key. Duplicate button presses cannot intentionally create two billable local generations for one draft; the internal API/PostgreSQL idempotency layer remains the durable final guard.

## Media validation

- one Telegram message equals one reference upload operation;
- albums/media groups are rejected before download;
- unsupported documents are rejected as user validation errors;
- media size is capped by `FOXGEN_TELEGRAM_INPUT_MAX_BYTES`;
- Telegram download failure and object-storage failure are separate retryable error classes;
- FSM does not advance when upload fails.

See `input-media-lifecycle.md`.

## Confirmation and billing preview

Before confirmation the bot obtains current model price and wallet balance from the trusted internal API. Insufficient funds disable launch rather than allowing a provider request that would later fail after user confirmation.

At final confirmation the stored private object keys are converted into fresh presigned URLs with a bounded TTL. Those provider-readable URLs are not persisted as public product URLs and are not generated at the moment the user first uploads the reference.

## Submission state

During `submitting`, duplicate/cancel/back interactions are intentionally restricted because admission can be in progress. Durable idempotency and generation lifecycle state determine recovery if the request result is ambiguous.

## `/admin`

`/admin` is a separate privileged Telegram shell. Authorization is server-side; merely knowing callback data cannot grant access.

The panel exposes operational capabilities such as:

- stats/analytics;
- user lookup and balance actions;
- finance/exports;
- payments and tariffs/pricing;
- partners/withdrawals;
- promos and prompt moderation;
- runtime/model controls;
- support/CMS/campaign operations;
- AI diagnostics and other admin tools exposed by the current bot adapter.

Every privileged callback/FSM continuation re-checks admin policy. Destructive/expensive workflows include preview/confirm semantics and ultimately use shared admin services or the signed admin API instead of duplicating domain write logic in Telegram handlers.

See `admin-control-plane.md` and `admin-capability-matrix.md`.

## Error recovery rules

- user validation error: keep the current recoverable state and explain the expected input;
- stale callback with active known state: keep the draft and direct the user to the latest controls;
- Redis TTL expiry: clear and return to menu;
- unknown old-release FSM state: clear fail-closed;
- Telegram/API infrastructure error: do not pretend a generation was submitted;
- duplicate confirm: converge through idempotency rather than creating another charge;
- provider/delivery ambiguity after durable admission: handled by durable lifecycle, not Telegram FSM guessing.

## Testing expectations

Regression coverage includes FSM contract completeness, stale callback recovery, active draft preservation, reference routing, event isolation and admin authorization. Changes that add a new state must update the state contract and tests at the same time.