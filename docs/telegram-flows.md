# Telegram flows and FSM

FoxGen uses aiogram 3 with Redis-backed FSM. Telegram handlers own conversational drafts, native Telegram update transport and screen navigation; durable admission, billing, payment evidence, provider execution and delivery remain in backend application services/PostgreSQL.

## Global `/start` and `/menu`

`foxgen-global-commands` is the first runtime router. `/start` and `/menu` therefore interrupt **every** active generation screen before any state-specific text/media handler can consume the command.

The interrupt contract is:

1. collect all known temporary input keys from FSM data;
2. best-effort delete those temporary files;
3. clear Redis state/data;
4. open the canonical main menu.

Regression tests enumerate every declared `GenerationStates` value, so adding a new screen cannot silently weaken this rule.

## Screen-FSM design

The normal image/video UX follows a compact screen contract:

```text
screen = renderer + keyboard + state + transitions
```

User-facing generation screens are single-purpose and are not numbered `1/4`, `2/4`, and so on. Typical titles are:

```text
🖼 Создание фото
🎬 Создание видео
📎 Референсы
⚙️ Параметры фото / видео
📝 Промпт для фото / видео
✅ Проверьте генерацию
```

All temporary choices live in `FSMContext`. There are no process-global per-user draft dictionaries. A draft stores a stable wizard version, visible flow step, model-specific settings, temporary media keys, prompt, idempotency key, price/balance projection and presentation-only control-message metadata.

Capabilities and provider payload construction are separate from Telegram rendering:

```text
generation_capabilities.py  -> supported screens/options
generation_draft.py         -> stable draft + validation + provider payload
generation_screens.py       -> text/keyboards
generation_wizard.py        -> transitions
```

## Reference/media screen contract

Image/video reference screens display live `Загружено: X/Y`, where `Y` comes from capability/contract data rather than a global hard-coded value.

Important behavior:

- upload refreshes the remembered control message when Telegram permits editing;
- `🔄 Перезагрузить` deletes current temporary inputs and redraws the same screen;
- image `⏭ Пропустить` means continue without references and deletes already uploaded temporary references first;
- required video scenarios keep a stable Continue control but validate completeness before advancing;
- `⬅️ Назад` is the persistent sub-screen navigation action;
- `/start` and `/menu` remain global reset paths;
- editing/replacing a Telegram control message never changes media ownership.

Durable `📚 Память реф` is now backed by the separate owner-scoped reference-memory domain; temporary inputs are never silently promoted without an explicit save action.

## Create image

```text
main menu -> Создать фото
  -> model
  -> optional references
  -> dynamic model settings
  -> prompt
  -> live price + balance confirmation
  -> authenticated paid admission
```

One UI choice may resolve to different provider slugs based on media. Example: Seedream 5 Pro resolves to text or edit provider contract depending on reference presence.

Current production wizard coverage is test-locked to the production-enabled submission registry and includes the current Seedream/Nano Banana/Seedance production set. Model-specific settings remain capability-driven and are validated again by the backend before paid admission.

## Create video

```text
main menu -> Создать видео
  -> model
  -> input type
  -> media/reference screen when required
  -> dynamic model settings
  -> prompt
  -> live price + balance confirmation
  -> authenticated paid admission
```

For current Seedance flows the verified input families include text, first frame, first+last frames and multimodal references. Upload order is preserved for first/last frame. Multimodal references are split into image/video/audio lists before strict provider validation.

## Quick Start convergence

```text
main menu -> Быстрый запуск
  -> upload one photo/video
  -> choose desired result: image/video
  -> same generation screen wizard as ordinary creation
```

The uploaded local input is reused by object key; it is not downloaded/copied again. Compatible reference metadata survives navigation, while incompatible replacements are cleaned before transition.

## Durable reference memory

Compatible image/video reference screens can open `📚 Память реф`. PostgreSQL owns reference metadata/ownership and persistent S3-compatible storage owns bytes under the durable reference prefix. Telegram memory-browser selection/navigation is ephemeral Redis state only.

Selected references are owner-revalidated and capability-checked, then resolved to fresh short-lived provider URLs only near final paid admission. Delete is owner-scoped. Saved references survive `/menu`, FSM expiry and redeploys.

## Telegram Stars top-up

Stars checkout is a **native Telegram payment flow**, not a Redis generation FSM. It has its own router (`foxgen-payments`) before broad product/shell fallbacks.

User path from Happy Fox:

```text
wallet -> Пополнить баланс
  -> owner-authenticated Stars packages
  -> durable local payment order
  -> Telegram XTR invoice link
  -> Telegram.WebApp.openInvoice(...)
```

Telegram update path:

```text
pre_checkout_query
  -> trusted /v1/user-portal/payments/stars/pre-checkout
  -> owner/payload/currency/amount validation
  -> query.answer(ok=true|false)

successful_payment
  -> trusted /v1/user-portal/payments/stars/success
  -> commit PaymentEvent + charge ID + paid_at
  -> exactly-once CREDIT settlement
  -> user sees credited/current balance projection
```

The bot never modifies wallet rows directly. The browser never declares payment success. `successful_payment` settlement is keyed by the Telegram charge ID and uses the immutable ledger key `payment-credit:telegram_stars:<charge-id>`.

A crucial recovery boundary exists between evidence and settlement: the backend commits Telegram charge evidence **before** attempting the wallet credit. If the second transaction fails, the user is told not to pay again; the durable `PaymentEvent` can be recovered by the existing admin payment reprocess path without a second credit.

The pre-checkout handler fails closed on backend/validation errors. It does not approve an order merely because Telegram sent a query.

See `telegram-stars-payments.md` and `billing.md`.

## Declared generation FSM states

Current screen states include:

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

Quick Start/reference compatibility states include:

```text
quick_start_waiting_media
reference_choosing_product
reference_choosing_model
reference_waiting_prompt
```

Migration-compatibility generic states remain declared so older deployed Redis drafts recover safely. Shared terminal conversational states include `confirming` and `submitting`.

`fsm_contract.py` defines success/back/cancel/timeout/invalid/stale behavior for every declared state.

## Back / invalid input / stale callback

Each generation screen has an explicit backwards edge. Invalid messages do not destroy a valid draft. Button-only screens tell the user to use the current controls; media screens restate requirements; prompt screens request text. An unrelated stale callback keeps a known active state and points to the latest controls.

Unknown/expired old state names fail closed and return safely to the menu rather than submitting stale work.

## Confirmation and billing

Confirmation resolves the final provider model slug, then reads the current price and wallet balance through the trusted internal API. Launch is enabled only when price, balance and draft validation pass.

At final launch, private input/reference storage keys are converted to fresh short-lived URLs and the strict provider payload is constructed.

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

Each draft owns one stable `idempotency_key`. During `submitting`, repeated launch presses are rejected conversationally; internal API/PostgreSQL idempotency remains the durable final guard.

Payment invoice creation follows the same principle independently: one `(user, Idempotency-Key)` maps to one durable payment order and conflicting reuse is rejected.

## Media safety

- one Telegram message equals one upload operation;
- albums/media groups are rejected before download;
- unsupported documents fail as user validation errors;
- upload size is bounded;
- storage failures do not advance the screen;
- temporary files are cleaned on explicit exits/reloads/replacement paths;
- signed provider-readable URLs are generated only near final admission;
- persistent reference memory uses its own durable prefix/ownership rules.

See `input-media-lifecycle.md`.

## Runtime router order

Router order is a correctness contract and is protected by regression tests:

```text
foxgen-global-commands
foxgen-admin-extras
foxgen-admin
foxgen-payments
foxgen-feed
foxgen-feed-publish
foxgen-feed-remix
foxgen-quick-start-wizard
foxgen-reference-memory
foxgen-generation-wizard
foxgen-quick-start
foxgen-generation
foxgen-shell
```

Reasons:

- global commands must preempt every FSM;
- admin extension callbacks must precede broad product/shell fallbacks;
- payment transport must consume `pre_checkout_query` and `successful_payment` before generic message handling;
- feed/publish/remix routers own their social/deep-link callbacks;
- Quick Start bridge owns post-upload convergence before legacy Quick Start handlers;
- reference memory owns its browser callbacks before the generic generation wizard;
- the generation wizard owns current image/video model/settings/back/confirmation callbacks;
- legacy routers remain after current routers for older Redis drafts;
- shell catch-all remains last.

`register_runtime_routers()` and `tests/test_admin_extension_wiring.py` lock this ordering.

## `/admin`

`/admin` remains a separate privileged Telegram shell. Every privileged callback/FSM continuation re-authorizes through the signed server-side admin API. Payment reprocess/refund/operator actions stay behind this privileged boundary and are never exposed through the ordinary Mini App identity.

## Testing expectations

A Telegram/product change is incomplete unless tests preserve the relevant contracts:

- every declared generation state has a state contract;
- `/start` interrupts every generation state;
- exact runtime router order;
- stale/invalid/back behavior;
- wizard production-model coverage and strict payload validation;
- media cleanup/ownership boundaries;
- price/balance admission idempotency;
- Stars pre-checkout accepts only backend-validated orders;
- Stars pre-checkout fails closed on backend error;
- duplicate `successful_payment` cannot double-credit;
- a settlement failure after charge evidence leaves durable recoverable payment state.
