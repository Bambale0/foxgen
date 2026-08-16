# Telegram flows and FSM

FoxGen uses aiogram 3 with Redis-backed FSM. Telegram handlers own conversational drafts, native Telegram update transport and screen navigation; durable admission, billing, payment/promo evidence, provider execution and delivery remain in backend application services/PostgreSQL.

## Global `/start` and `/menu`

`foxgen-global-commands` is the first runtime router. `/start` and `/menu` interrupt every active generation screen before state-specific handlers can consume the command.

The interrupt contract is:

1. collect known temporary input keys;
2. best-effort delete temporary files;
3. clear Redis state/data;
4. open the canonical main menu.

Regression tests enumerate every declared generation state so new screens cannot silently weaken this rule.

## Screen-FSM design

Image/video UX follows:

```text
screen = renderer + keyboard + state + transitions
```

Draft choices live in `FSMContext`, not process-global per-user dictionaries. Capability/provider payload logic is separated from Telegram rendering through generation capability/draft/screen/wizard modules.

Reference screens display live upload counts from model contracts, preserve explicit back/reload/skip semantics and never silently promote temporary files into durable reference memory.

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

Model-specific settings remain capability-driven and are validated again by the backend before paid admission.

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

## Quick Start convergence

```text
main menu -> Быстрый запуск
  -> upload one photo/video
  -> choose image/video result
  -> same generation screen wizard as ordinary creation
```

The local input object is reused rather than copied again. Incompatible replacement inputs are cleaned before transition.

## Durable reference memory

Compatible screens can open `📚 Память реф`. PostgreSQL owns metadata/ownership; private S3-compatible storage owns bytes; Redis selection is ephemeral. Selected references are owner/capability revalidated and resolved to fresh short-lived provider URLs near paid admission.

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

Explicit promo redemption also uses the existing `foxgen-payments` financial router but does not create an FSM draft.

Telegram user flow:

```text
/promo FOX500
  -> trusted POST /v1/user-portal/promos/redeem
  -> server normalizes/locks promo definition
  -> atomic wallet + immutable ledger + redemption + uses
  -> reply with granted/current CREDIT
```

`/promo` with no code returns usage help and makes no API call. Backend validation errors are surfaced as a user-readable failure without local financial mutation.

The bot sends only the code and owner identity. It never receives/submits a reward amount or increments a balance itself. A repeated code for the same user returns the durable replay result; the bot explicitly says the promo was already activated and does not show another “Начислено” message.

The command is handled by `foxgen-payments`, which is registered before generation/product/shell fallbacks. It can therefore be used without adding another Redis FSM. It does not clear an existing generation draft; users can continue their prior flow after the command.

Happy Fox exposes the same owner capability through `/v1/miniapp/promos/redeem` and its wallet input control.

See `user-promos.md`.

## Declared generation FSM states

Current image/video states include model selection, reference/media upload, configuration and prompt states; Quick Start/reference compatibility states remain declared for migration compatibility. Shared terminal conversational states include `confirming` and `submitting`.

`fsm_contract.py` defines success/back/cancel/timeout/invalid/stale behavior for every declared state.

## Back / invalid input / stale callback

Each generation screen has an explicit backwards edge. Invalid input does not destroy a valid draft. Unrelated stale callbacks keep a known active state and point to the latest controls; unknown/expired old state names fail closed to the menu.

## Confirmation and billing

Confirmation resolves the final provider slug, current price and wallet balance. Final launch converts private input/reference keys into fresh short-lived URLs and enters the authenticated paid admission boundary:

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

Each generation draft owns one stable idempotency key. During `submitting`, repeated launch presses are rejected conversationally; API/PostgreSQL idempotency is the durable guard.

Stars invoices have their own durable order idempotency. Promo redemption has business idempotency through unique `(promo_code,user_id)` plus deterministic immutable ledger key.

## Media safety

- one Telegram message equals one upload operation;
- albums/media groups are rejected before upload;
- unsupported documents fail as validation errors;
- upload size is bounded;
- storage failures do not advance the screen;
- temporary files are cleaned on explicit exits/reloads/replacement;
- provider URLs are generated only near final admission;
- durable reference memory uses separate ownership/prefix rules.

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
- `foxgen-payments` must consume `/promo`, `pre_checkout_query` and `successful_payment` before generic message handling;
- feed/reference/current-wizard routers must precede legacy compatibility routers;
- shell catch-all remains last.

`register_runtime_routers()` and router-order regression tests lock this contract.

## `/admin`

`/admin` is a privileged Telegram shell. Every privileged callback/FSM continuation re-authorizes through the signed server-side admin API. Payment refund/reprocess and promo-definition management remain privileged and are never exposed through ordinary user identity.

## Testing expectations

A Telegram/product change is incomplete unless tests preserve relevant contracts, including:

- every declared generation state has a state contract;
- `/start` interrupts every generation state;
- exact runtime router order;
- stale/invalid/back behavior;
- strict model payload and media cleanup boundaries;
- price/balance admission idempotency;
- Stars pre-checkout fail-closed behavior;
- duplicate `successful_payment` cannot double-credit;
- paid-but-uncredited evidence remains recoverable;
- `/promo` requires a code;
- `/promo` uses the trusted owner API and reports CREDIT projection;
- replayed promo does not present a second grant;
- promo backend errors are surfaced without local wallet mutation.
