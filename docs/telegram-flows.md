# Telegram flows and FSM

FoxGen uses aiogram 3 with Redis-backed FSM. Telegram handlers are transport/orchestration code; durable admission, billing, publication and administrative writes are delegated to application/admin services or the internal API.

## Main menu

The current main menu exposes active image/video generation actions plus social entrypoints:

- `🌐 Лента`;
- `👤 Профиль`;
- `📣 Опубликовать генерацию`;
- Quick Start and generation product actions.

Some other menu sections may still be planned product surfaces; documentation must not treat a visible placeholder callback as an implemented generator.

## Global `/start` and `/menu` interrupt

`foxgen-global-commands` is registered before every state-specific router. `/start` and `/menu` therefore **always interrupt the current FSM state**, including generation and feed/profile/comment/publish states.

The command handler:

1. reads known temporary input keys;
2. performs best-effort temporary input cleanup;
3. clears Redis FSM state/data;
4. for `/start <payload>`, dispatches a recognized post/profile/remix deep link;
5. otherwise opens the current main menu.

A state-specific `F.text` handler must never consume `/start` as a prompt, comment, profile field or generation ID. Regression tests enumerate every declared `GenerationStates` and `FeedStates` value.

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
  -> file is stored privately on local shared input storage
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

- the original temporary input storage key;
- optional preview/thumbnail key;
- selected model;
- prompt when already entered;
- applicable model settings.

The bot does not infer reference semantics just because a media list is non-empty.

## Feed and public profile flow

```text
main menu -> Лента
  -> recent/top-day/top publication card
  -> like/unlike
  -> surface comments
  -> author profile
  -> remix when server says allowed
```

The Telegram card does not expose storage credentials or provider result URLs. It requests an authenticated short-lived publication media URL from the internal API.

Profile flow:

```text
main menu -> Профиль
  -> own public slug/name/bio
  -> profile publications
  -> own publication management
  -> edit slug/name/bio
```

Public profile links open through `profile_<slug>` start payloads. Product-facing profile slugs are constrained so the complete Telegram `start` payload stays within 64 characters.

## Publish flow

`📣 Опубликовать генерацию` is an explicit Telegram wizard:

```text
enter completed generation UUID
  -> choose feed or profile
  -> server validates owner + succeeded + all media stored
  -> publication row is created/reactivated
```

The bot does not assume that a UUID is publishable because the user entered it. Eligibility and derivative restrictions are server-side.

A derivative generation can be published to `profile`; publishing it to `feed` is rejected.

## Comments

`FeedStates.waiting_comment` stores the target publication UUID and the requested surface (`feed` or `profile`). The server verifies surface equality again before write. A copied callback cannot post into a different surface thread.

Comments are currently flat messages up to 1000 characters.

## Remix flow

A remix starts only from an eligible active publication.

```text
publication -> Remix
  -> server returns remix contract
  -> bot stores source publication ID + source prompt in FSM
  -> choose compatible model
  -> ordinary aspect/quality/duration/audio settings
  -> ordinary price/balance confirmation
  -> final source revalidation
  -> fetch fresh short-lived durable-result media URLs
  -> paid submission with source publication header
```

The source publication ID is carried separately from the provider payload. The backend includes it in the idempotency fingerprint and commits lineage in the same transaction as paid admission.

A derivative publication has no public prompt actions and is rejected as a remix source server-side.

## Deep links

Recognized Telegram start payloads:

```text
post_<publication UUID>
profile_<slug>
remix_<publication UUID>
```

Opening any deep link first clears the previous FSM due to the global `/start` rule, then dispatches the new product entrypoint.

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

`fsm_contract.py` defines behavior expectations for every declared generation state.

## Declared feed FSM states

```text
waiting_comment
editing_profile_slug
editing_profile_name
editing_profile_bio
waiting_publish_generation
choosing_publish_scope
```

These are transport-only drafts; publication/profile/comment state is durable only after the internal API succeeds.

## Required state behavior

Every state has an explicit user-recovery contract for:

- valid next transitions;
- cancel/menu/start;
- timeout/expiry;
- invalid message/input;
- stale callback where applicable.

Known active generation state is preserved when a user presses an unrelated old button or sends input that belongs to another step. `/start` and `/menu` are the deliberate exception: they always clear the current state. A missing/expired Redis state recovers to the menu with an expiry explanation. An unknown state name left by old deployed code is cleared fail-closed.

## Concurrency and duplicate protection

Redis event isolation serializes updates for one FSM storage key. Two near-simultaneous reference messages from one user therefore cannot both observe the same empty state and race through upload/state mutation.

Paid generation confirmation also has a stable draft idempotency key. Duplicate button presses cannot intentionally create two billable local generations for one draft; the internal API/PostgreSQL idempotency layer remains the durable final guard.

Remix idempotency also includes `source_publication_id`, so reusing the same key for another source conflicts rather than silently changing lineage.

## Media validation

- one Telegram message equals one reference upload operation;
- albums/media groups are rejected before download;
- unsupported documents are rejected as user validation errors;
- media size is capped by `FOXGEN_TELEGRAM_INPUT_MAX_BYTES`;
- Telegram download failure and local-storage failure are separate retryable error classes;
- FSM does not advance when upload fails.

See `input-media-lifecycle.md`.

## Confirmation and billing preview

Before confirmation the bot obtains current model price and wallet balance from the trusted internal API. Insufficient funds disable launch rather than allowing a provider request that would later fail after user confirmation.

For normal reference generation, stored private temporary keys are converted into fresh signed URLs with bounded TTL at final confirmation.

For remix, durable result media remains in S3-compatible storage. The bot requests fresh presigned result URLs immediately before paid admission. It does not copy a `generations/` object into local temporary input state.

## Submission state

During `submitting`, duplicate/cancel/back interactions are intentionally restricted because admission can be in progress. Durable idempotency and generation lifecycle state determine recovery if the request result is ambiguous.

## `/admin`

`/admin` is a separate privileged Telegram shell. Authorization is server-side; merely knowing callback data cannot grant access.

The registered admin routers expose the operational transport for:

- summary/statistics;
- user lookup, block/unblock and balance actions;
- finance;
- payments;
- partners and withdrawal queue/actions;
- tariffs/pricing;
- promos;
- prompt moderation;
- broadcast/campaign flow;
- support;
- operations;
- runtime/subscription/model controls;
- AI diagnostics;
- CMS;
- CSV export actions;
- dedicated analytics callback;
- XLS user/finance exports;
- approved-withdrawal listing and confirmed payment shortcut.

Every privileged callback/FSM continuation re-checks admin policy through the signed server-side admin API. Destructive/expensive workflows use preview/confirm semantics and shared admin services rather than direct write SQL in Telegram handlers.

### Runtime router order

Registration order is explicit:

```text
foxgen-global-commands
foxgen-admin-extras
foxgen-admin
foxgen-feed
foxgen-feed-publish
foxgen-feed-remix
foxgen-quick-start
foxgen-generation
foxgen-shell
```

The first router protects the global `/start`/`/menu` interrupt contract. Admin extension handlers stay before broad shell fallbacks. Feed-remix handlers stay before the ordinary generation router so a remix draft can intercept model choice/final confirmation and preserve its source lineage instead of being treated as an ordinary generation draft.

`register_runtime_routers()` centralizes this order so tests can verify it without starting polling.

### Extension callback security

`src/foxgen/bot/admin_extras.py` is active runtime transport for:

- `adm:analytics` → signed `GET /internal/admin/analytics`;
- `adm:exportxls:users` / `adm:exportxls:finance` → signed XLS download;
- `adm:withdrawals:approved` → signed filtered withdrawal read;
- `adm:wdpay:{withdrawal_id}` → signed confirmed/idempotent `mark_paid` write.

Every one of these callbacks calls Admin API health/authorization first. The payment shortcut generates a fresh idempotency key and sends explicit confirmation through the shared partner action endpoint. No payout state is mutated directly in Telegram code.

See `admin-control-plane.md`, `admin-capability-matrix.md`, `api-reference.md` and `feed-profile-remix.md`.

## Error recovery rules

- user validation error: keep the current recoverable state and explain the expected input;
- `/start` or `/menu`: always clear current state and temporary input references;
- stale callback with active known generation state: keep the draft and direct the user to the latest controls;
- Redis TTL expiry: clear and return to menu;
- unknown old-release FSM state: clear fail-closed;
- Telegram/API infrastructure error: do not pretend a generation/publication/comment was committed;
- duplicate confirm: converge through idempotency rather than creating another charge;
- provider/delivery ambiguity after durable admission: handled by durable lifecycle, not Telegram FSM guessing.

## Testing expectations

Regression coverage includes FSM contract completeness, global `/start` interruption for every generation/feed state, stale callback recovery, active draft preservation, reference routing, event isolation, feed deep-link parsing, remix media validation, router precedence, publication integration invariants, main admin authorization and extension transport reachability.

A new generation/feed/admin FSM state or privileged callback must update its state/authorization tests at the same time.
