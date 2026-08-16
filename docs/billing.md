# Billing, pricing and financial invariants

FoxGen stores internal balance in integer `CREDIT` units. Floating-point wallet arithmetic is not used. A materialized wallet balance provides fast reads; the append-only ledger is the financial audit/reconciliation source.

## Admission gate

A billable generation is admitted only when all conditions pass:

1. paid submission is explicitly enabled;
2. the caller is a trusted internal service;
3. the user is not administratively blocked;
4. the model is production-ready and not runtime-disabled;
5. a currently active model price exists;
6. the user has enough available balance;
7. rate/concurrency limits pass;
8. generation, reservation, ledger movement and outbox can commit atomically.

Missing price returns a pricing failure before provider access. Insufficient funds fail before provider access. No queued paid generation can exist without its matching reservation in the successful admission path.

User top-up is a separate financial boundary: Telegram Stars payment validation/settlement does not depend on `FOXGEN_TASK_SUBMISSION_ENABLED`, because disabling new provider generations must not prevent a previously paid user transaction from being recorded or reconciled.

## Wallet account

Each user wallet stores:

- `available_units` — spendable credits;
- `reserved_units` — credits held for admitted work whose billing outcome is not fully settled;
- `currency` — currently `CREDIT`;
- `version` — incremented on account mutation.

Database constraints prevent negative available/reserved values.

## Versioned model prices

`model_prices` is versioned by `(model_slug, version)` and keeps historical rows. Publishing a new active price disables the previous active version rather than editing history in place.

Price rows include:

- amount in integer units;
- currency;
- enabled flag;
- activation window;
- metadata;
- version.

Migrations do not invent commercial prices. Operations must deliberately publish prices before enabling production paid submission.

The full admin contour also maintains a versioned tariff payload for packages and broader product pricing. `model_prices` remains the runtime per-model price used by current generation admission; tariff publishing is an administrative/version-history surface and must be kept consistent with whatever product-price projection is used by a release.

## Telegram Stars top-up

Digital-credit top-up inside Telegram uses Telegram Stars (`XTR`) and the latest published tariff package data. A package is purchasable through the Stars flow only when it explicitly contains both:

- a positive integer CREDIT amount (`credits_units` or legacy `credits`);
- a positive integer Stars amount (`stars_amount` or `stars`).

Legacy tariff packages that contain only a fiat/display `price` remain valid tariff data but are not silently converted into Stars prices.

Before FoxGen calls Telegram to create an invoice link, it creates a durable `user_payment_orders` row and snapshots package code/title/description, CREDIT amount and XTR amount. The order is idempotent on `(user_id, Idempotency-Key)`. Telegram invoice title/description are normalized to provider limits before a package is exposed as purchasable.

Payment flow:

```text
latest tariff package
  -> durable payment order
  -> Telegram XTR invoice link
  -> pre_checkout_query validation
  -> successful_payment
  -> durable payment evidence
  -> exactly-once CREDIT ledger settlement
```

The pre-checkout handler validates order ownership, invoice payload, `XTR` currency and exact snapshotted amount. It does not mutate the wallet.

A verified Telegram `successful_payment` is handled in two durable boundaries:

1. persist charge evidence (`PaymentEvent` + Telegram charge ID + paid timestamp) in its own committed transaction;
2. settle the wallet and immutable ledger in a separate transaction using deterministic key:

```text
payment-credit:telegram_stars:<telegram_payment_charge_id>
```

This separation is deliberate. If wallet settlement fails after Telegram has charged the user, the payment evidence survives and the existing admin payment reprocess worker can recover the CREDIT exactly once. Users must not be told to pay again merely because the second boundary failed.

The local order also stores the Telegram charge ID because a later refund capability needs the original charge identity. Refund execution is a separate reviewed slice.

See `telegram-stars-payments.md` for the transport/order lifecycle.

## Atomic reservation

Conceptually, generation admission executes:

```text
BEGIN
  create/idempotently find generation
  lock/ensure wallet account
  select active model price
  validate sufficient available units
  available_units -= amount
  reserved_units += amount
  create balance_reservation(status=reserved)
  append ledger(type=reserve)
  create outbox(generation.submit)
COMMIT
```

Any failure rolls back the transaction.

## Settlement lifecycle

Reservation states:

```text
reserved -> captured
reserved -> released
captured -> refunded
```

### Provider acceptance

When provider acceptance is durably verified and generation becomes `submitted`, the reservation is captured:

```text
reserved_units -= amount
reservation = captured
ledger += capture
```

### Ambiguous submission

`submission_unknown` deliberately keeps the reservation in `reserved`. FoxGen does not guess whether the provider charged and does not release/capture solely because a local timeout occurred.

Resolution requires callback, polling evidence or explicit operator reconciliation.

### Deterministic failure before capture

A reservation is released:

```text
available_units += amount
reserved_units -= amount
reservation = released
ledger += release
```

### Terminal failure after capture

Current policy applies a full refund:

```text
available_units += amount
reservation = refunded
ledger += refund
```

Repeated lifecycle events cannot create repeated settlement because reservation rows are locked and ledger operations use deterministic idempotency keys.

## Immutable ledger

`ledger_entries` records every financial movement with:

- user ID;
- optional generation/reservation references;
- entry type;
- available/reserved deltas;
- currency;
- unique idempotency key;
- actor;
- reason;
- metadata;
- timestamp.

The ledger is append-only by design and is the basis for reconciliation. Admin adjustments do not mutate prior entries; they append new adjustment/credit/debit movements through protected services.

## User/admin balance adjustment

Two protected administrative transports currently exist:

### Legacy billing-admin route

```text
POST /v1/admin/users/{user_id}/balance-adjustments
```

It requires the separately configured billing-admin credential and `Idempotency-Key`.

### Full admin control plane

```text
POST /internal/admin/users/{user_id}/balance-adjustments
```

It additionally uses signed HMAC admin authentication, server-side RBAC, command/audit ledger, idempotent replay and explicit confirmation.

For new operator surfaces, prefer the full admin domain/service path rather than duplicating financial write logic.

## Payment events and reprocessing

The admin contour stores payment events for operational inspection/recheck/reprocess. Telegram Stars `successful_payment` is also materialized here before wallet settlement so external charge evidence is not lost when the later CREDIT transaction fails.

A completed payment credit uses a deterministic immutable-ledger idempotency key:

```text
payment-credit:<provider>:<external_id>
```

Consequences:

- reprocessing the same completed payment cannot credit it twice;
- a second admin command with another request id still observes the existing payment credit;
- a Stars charge with persisted evidence but no `credited_ledger_key` can be recovered through the same generic payment reprocess worker;
- provider recheck/reprocess is durable admin worker work rather than an unsafe request-lifecycle mutation;
- when a provider recheck adapter is absent, the job fails closed instead of inventing payment state.

## Tariff history

The full admin contour exposes:

```text
GET  /internal/admin/tariffs
GET  /internal/admin/tariffs/versions
GET  /internal/admin/tariffs/versions/{version_id}
POST /internal/admin/tariffs/publish
```

Publishing is idempotent, audited and confirmation-gated. Historical published versions are retained for operational traceability.

## User payment APIs

Trusted bot transport:

```text
GET  /v1/user-portal/payments/stars/packages
POST /v1/user-portal/payments/stars/invoices
POST /v1/user-portal/payments/stars/pre-checkout
POST /v1/user-portal/payments/stars/success
```

Happy Fox browser transport:

```text
GET  /v1/miniapp/payments/stars/packages
POST /v1/miniapp/payments/stars/invoices
```

The browser can request an invoice but cannot post a successful payment or mutate a wallet. Settlement originates from the trusted Telegram bot update path.

## Financial read APIs

Trusted internal:

```text
GET /v1/prices
GET /v1/users/{user_id}/balance
GET /v1/users/{user_id}/ledger
```

Full admin:

```text
GET /internal/admin/finance
GET /internal/admin/payments
GET /internal/admin/payments/{payment_id}
GET /internal/admin/exports/finance.csv
```

See `api-reference.md` for authentication details.

## Reconciliation invariants

Operational checks include:

```text
wallet.available_units + wallet.reserved_units
= sum(ledger.available_delta + ledger.reserved_delta)
```

and cross-resource expectations such as:

- every admitted billable generation has one reservation;
- a captured reservation matches verified provider acceptance or later lifecycle;
- terminal pre-capture failures do not retain reserved funds;
- terminal post-capture failures/refunds settle exactly once;
- a Telegram Stars `PaymentEvent` with no credited ledger key is visible as paid-but-uncredited evidence, not discarded transport state;
- duplicate Telegram payment updates and duplicate admin/payment commands do not append duplicate financial effects.

Automated reconciliation exists and may apply only deterministic local fixes. It never submits a provider task or resolves ambiguous external side effects through guesswork.

See `postprocessing-reconciliation.md`.

## Security requirements

Use separate credentials for ordinary internal generation API, legacy billing-admin API and full admin HMAC control plane. None belong in a public client or Mini App.

Every manual money mutation must include a human-readable reason and be attributable to an actor/admin request. Do not bypass shared billing/admin services with direct SQL for ordinary operations.

## Change checklist

A billing/pricing/payment change must update:

- SQLAlchemy model/migration if schema changes;
- atomic admission/settlement and duplicate-event tests;
- durable external-payment evidence/recovery expectations;
- reconciliation expectations;
- `.env`/configuration docs for new switches;
- `billing.md`, `telegram-stars-payments.md`, `api-reference.md`, `telegram-flows.md` and `database-schema.md` when the payment/user transport changes.
