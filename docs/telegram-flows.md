# Telegram flows and FSM

FoxGen uses aiogram 3 with Redis-backed FSM. Telegram handlers own conversational drafts, native Telegram update transport and screen navigation; durable admission, billing, provider execution and delivery remain in backend application services/PostgreSQL.

## Global `/start` and `/menu`

`foxgen-global-commands` is the first runtime router. `/start` and `/menu` interrupt every active product screen before state-specific handlers can consume the command.

The interrupt contract is:

1. collect known temporary input keys;
2. best-effort delete temporary files;
3. clear Redis state/data;
4. open the canonical main menu.

Regression tests enumerate every declared product state so new screens cannot silently weaken this rule.

## Screen-FSM design

Image/video, TTS and music UX follow the same principle:

```text
screen = renderer + keyboard + state + transitions
```

Draft choices live in `FSMContext`, not process-global per-user dictionaries. Provider payload logic is separated from Telegram rendering and is validated again by backend model contracts before paid admission.

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

Current Seedance flows include text, first-frame, first+last-frame and multimodal-reference input families.

## Voice / ElevenLabs TTS

`Создать озвучку (голос)` is a real product route, not a planned placeholder.

```text
main menu -> Создать озвучку
  -> text
  -> voice name / Voice ID
  -> speed preset
  -> live ElevenLabs Turbo 2.5 price + balance
  -> shared paid admission
  -> normal audio archive + Telegram delivery
```

The TTS FSM keeps one stable idempotency key for the draft. Missing active price or insufficient balance disables launch before paid admission. Existing old `planned:voice` callback messages forward into the current flow after deployment.

TTS does not maintain a separate wallet, worker or delivery subsystem.

## Music / Suno V5 core

`Создать музыку (песню)` is a real product route for the reviewed Suno V5 core slice.

Simple mode:

```text
main menu -> Создать музыку
  -> Быстро
  -> вокал / инструментал
  -> one prompt
  -> live price + balance
  -> shared paid admission
```

Custom vocal mode:

```text
Кастомно
  -> вокал
  -> lyrics/prompt
  -> style
  -> title
  -> price + balance
  -> submit
```

Custom instrumental mode intentionally skips lyrics input and requires only style + title before confirmation.

Provider execution uses the dedicated Suno API family selected by the backend model specification. Telegram never calls Suno/KIE directly. Suno can return multiple song variants; FoxGen archives and delivers every canonical audio track through the ordinary media pipeline.

Existing old `planned:music` callback messages forward into the current flow after deployment.

See `suno-core.md`.

## Quick Start convergence

```text
main menu -> Быстрый запуск
  -> upload one photo/video
  -> choose image/video result
  -> same generation screen wizard as ordinary creation
```

The local input object is reused rather than copied again. Incompatible replacement inputs are cleaned before transition.

## Durable reference memory

Compatible image/video screens can open `📚 Память реф`. PostgreSQL owns metadata/ownership; private S3-compatible storage owns bytes; Redis selection is ephemeral. Selected references are owner/capability revalidated and resolved to fresh short-lived provider URLs near paid admission.

## Telegram Stars top-up

Stars checkout is a native Telegram payment flow, not a generation FSM. `foxgen-payments` is registered before broad product/shell fallbacks.

Happy Fox path:

```text
wallet -> Пополнить баланс
  -> Stars package
  -> durable payment order
  -> XTR invoice link
  -> Telegram.WebApp.openInvoice(...)
```

Telegram update path:

```text
pre_checkout_query
  -> /v1/user-portal/payments/stars/pre-checkout
  -> owner/payload/currency/amount validation

successful_payment
  -> /v1/user-portal/payments/stars/success
  -> durable charge evidence
  -> exactly-once CREDIT settlement
```

The bot never modifies wallet rows directly. Duplicate payment updates reuse the deterministic ledger key. Paid-but-uncredited evidence remains recoverable through payment reprocess.

See `telegram-stars-payments.md` and `billing.md`.

## Promo-code bonus

Explicit promo redemption uses the existing `foxgen-payments` financial router but does not create an FSM draft.

```text
/promo FOX500
  -> trusted POST /v1/user-portal/promos/redeem
  -> server normalizes/locks promo definition
  -> atomic wallet + immutable ledger + redemption + uses
  -> reply with granted/current CREDIT
```

The bot sends only the code and owner identity. It never receives/submits a reward amount or increments a balance itself.

See `user-promos.md`.

## Declared product FSM states

Current declared groups include:

- `GenerationStates` for image/video/reference/Quick Start compatibility;
- `VoiceStates` for ElevenLabs TTS text/voice/speed/confirmation/submission;
- `MusicStates` for Suno mode/vocal/prompt/style/title/confirmation/submission;
- social/feed states.

`fsm_contract.py` defines success/back/cancel/timeout/invalid/stale behavior for every declared generation/voice/music state. Tests compare the declared state sets against this mapping so adding a new state without lifecycle behavior fails CI.

## Back / invalid input / stale callback

Each product screen has an explicit backwards edge. Invalid input does not destroy a valid draft. Unrelated stale callbacks keep a known active state and point to the latest controls; unknown/expired old state names fail closed to the menu.

## Confirmation and billing

Confirmation resolves the final model slug, current price and wallet balance. Final launch enters the same authenticated paid admission boundary for image, video, TTS and Suno:

```text
authenticated internal request
  -> model/runtime validation
  -> idempotency
  -> rate/concurrency limits
  -> atomic price/balance reservation
  -> generation + durable submit outbox
```

Telegram never calls KIE directly and never performs its own wallet mutation.

## Duplicate confirmation

Each product draft owns one stable idempotency key. During `submitting`, repeated launch presses are rejected conversationally; API/PostgreSQL idempotency is the durable guard.

Stars invoices have their own durable order idempotency. Promo redemption has business idempotency through unique `(promo_code,user_id)` plus deterministic immutable ledger key.

## Media safety

- one Telegram message equals one upload operation;
- albums/media groups are rejected before upload;
- unsupported documents fail as validation errors;
- upload size is bounded;
- storage failures do not advance the screen;
- temporary files are cleaned on explicit exits/reloads/replacement;
- provider URLs are generated only near final admission;
- durable reference memory uses separate ownership/prefix rules;
- Suno multi-track normalization archives canonical `audioUrl` results only, excluding artwork and stream helper URLs.

## Runtime router order

Router order is a correctness contract:

```text
foxgen-global-commands
foxgen-admin-extras
foxgen-admin
foxgen-payments
foxgen-feed
foxgen-feed-publish
foxgen-feed-remix
voice-tts
music-suno
foxgen-quick-start-wizard
foxgen-reference-memory
foxgen-generation-wizard
foxgen-quick-start
foxgen-generation
foxgen-shell
```

Reasons include:

- global `/start`/`/menu` must preempt every FSM;
- admin extension callbacks must precede broad fallbacks;
- payment transport must consume financial updates before generic message handling;
- dedicated TTS/Suno routers must consume their live and legacy callbacks before broad generation/shell fallbacks;
- feed/reference/current-wizard routers must precede legacy compatibility routers;
- shell catch-all remains last.

`register_runtime_routers()` and router-order regression tests lock this contract.

## `/admin`

`/admin` is a privileged Telegram shell. Every privileged callback/FSM continuation re-authorizes through the signed server-side admin API. Payment refund/reprocess and promo-definition management remain privileged and are never exposed through ordinary user identity.

## Testing expectations

A Telegram/product change is incomplete unless tests preserve relevant contracts, including:

- every declared product state has a state contract;
- `/start`/`/menu` can interrupt product drafts;
- exact runtime router order;
- stale/invalid/back behavior;
- strict model payload validation before paid admission;
- price/balance admission idempotency;
- TTS missing-price fail-closed behavior and exact provider input;
- Suno simple/custom/instrumental mode transitions;
- Suno missing-price fail-closed behavior;
- real PostgreSQL exactly-once reservation/outbox for TTS/Suno;
- cross-layer TTS audio archive/delivery E2E;
- cross-layer Suno multi-track archive/delivery E2E;
- Stars and promo financial invariants.
