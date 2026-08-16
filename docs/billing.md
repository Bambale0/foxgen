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

User top-up/refund/promo recovery is a separate financial boundary: Telegram Stars payment validation, settlement, refund reconciliation and explicit promo redemption do not depend on `FOXGEN_TASK_SUBMISSION_ENABLED`.

## Wallet account

Each user wallet stores:

- `available_units` — spendable credits;
- `reserved_units` — credits held for admitted work whose billing outcome is not fully settled;
- `currency` — currently `CREDIT`;
- `version` — incremented on account mutation.

Database constraints prevent negative available/reserved values.

## Versioned model prices

`model_prices` is versioned by `(model_slug, version)` and keeps historical rows. Publishing a new active price disables the previous active version rather than editing history in place.

Price rows include amount in integer units, currency, enabled flag, activation window, metadata and version. Migrations do not invent commercial prices. Operations must deliberately publish prices before enabling production paid submission.

The full admin contour also maintains a versioned tariff payload for packages and broader product pricing. `model_prices` remains the runtime per-model price used by generation admission.

## Telegram Stars top-up and package bonus

Digital-credit top-up inside Telegram uses Telegram Stars (`XTR`) and the latest published tariff package data. A package is purchasable only when it explicitly contains a positive integer base CREDIT amount (`credits_units` or legacy `credits`) and positive integer Stars amount (`stars_amount` or `stars`). A package may additionally contain a non-negative integer purchase bonus (`bonus_units` or `bonus_credits`); missing bonus means zero. Negative, boolean or non-integer bonus values make the package unavailable to the Stars checkout path.

Before FoxGen calls Telegram to create an invoice link, it creates a durable `user_payment_orders` row and snapshots the commercial terms. `credits_units` on the durable order stores the **total CREDIT grant** (`base + bonus`) so existing settlement, generic payment reprocess and native refund always use the complete amount. `bonus_units` stores the auditable bonus component. Base CREDIT is therefore `credits_units - bonus_units`.

The order is idempotent on `(user_id, Idempotency-Key)`. A later tariff publication cannot change the base CREDIT, bonus CREDIT or XTR amount of an already-created order.

User package projections expose:

```text
credits_units       = total CREDIT grant (backward-compatible field)
base_credits_units  = base package CREDIT
bonus_units         = explicit package bonus
total_credits_units = base + bonus
stars_amount        = XTR price
```

Happy Fox may display the bonus but never submits or computes it. Invoice creation accepts only `package_code` plus backend-controlled owner/idempotency context.

Payment flow:

```text
latest tariff package
  -> durable payment order with base/bonus/XTR snapshot
  -> Telegram XTR invoice link
  -> pre_checkout_query validation
  -> successful_payment
  -> durable payment evidence for total CREDIT grant
  -> exactly-once total CREDIT ledger settlement
```

A verified Telegram `successful_payment` uses two durable boundaries:

1. persist charge evidence (`PaymentEvent`, Telegram charge ID and `paid` order state), with `PaymentEvent.amount_units` equal to the total CREDIT grant;
2. settle wallet and immutable ledger using:

```text
payment-credit:telegram_stars:<telegram_payment_charge_id>
```

If the second boundary fails, payment evidence survives and the admin payment reprocess worker can recover the exact same total base+bonus CREDIT exactly once.

## Telegram Stars refund

Native Stars refund is a privileged financial lifecycle. It is not a public browser/bot balance mutation.

A refund can begin only for a credited Stars payment with no active refund attempt and enough currently available CREDIT to reverse the original total grant. Because payment evidence stores the total grant, an explicit package bonus is held/reversed together with the base CREDIT. FoxGen commits the local CREDIT hold and immutable debit before the dedicated refund worker contacts Telegram:

```text
available_units -= original total credited units
ledger += payment-refund-debit:telegram_stars:<charge-id>:<attempt-id>
payment_refund_attempts += pending attempt
order/payment -> refund_pending
COMMIT
```

Successful provider refund leaves the debit final. Deterministic provider rejection restores CREDIT exactly once. Ambiguous network/server outcomes preserve the hold through bounded retry and then become `refund_unknown`; evidence-based resolution either keeps the debit (`refunded`) or appends the unique compensating `payment-refund-restore:*` ledger entry (`not_refunded`).

See `telegram-stars-payments.md` for the complete lifecycle.

## Explicit promo-code bonus

Promo redemption is a direct CREDIT grant from a server-owned `promo_codes` definition. The public client supplies only the promo code; reward amount and usage policy never come from the browser.

The transaction is:

```text
BEGIN
  lock promo_codes row
  find existing (promo_code, user_id) redemption
  validate active / reward > 0 / max_uses
  ensure user + lock/ensure CREDIT wallet
  available_units += reward_units
  ledger += promo-credit:<NORMALIZED_CODE>:<user_id>
  promo_redemptions += immutable redemption fact
  promo_codes.uses += 1
COMMIT
```

Financial/business idempotency is layered:

- unique `(promo_code, user_id)` prevents a second redemption for the same owner;
- unique deterministic `promo-credit:<CODE>:<user-id>` prevents a second ledger grant;
- the locked promo row serializes `max_uses` consumption across users.

A concurrent duplicate request from the same user waits on the promo lock, then replays the durable redemption. A different user arriving after the last remaining use fails before wallet/redemption creation.

A replay remains valid even if the promo is disabled/exhausted after the original redemption because replay does not create a new financial effect.

`promo_redemptions` references the promo definition with restrictive deletion semantics so a definition cannot be removed while redemption audit rows exist. Normal retirement uses `active=false`.

Promo-code bonuses and Stars package bonuses are separate policies. Promo reward comes from `promo_codes`; purchase bonus comes only from the published Stars package and is snapshotted into its payment order. Neither amount is client-controlled.

See `user-promos.md`.

## Atomic generation reservation

Generation admission executes conceptually:

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

## Generation settlement lifecycle

Reservation states:

```text
reserved -> captured
reserved -> released
captured -> refunded
```

When provider acceptance is durably verified, reserved units are captured. `submission_unknown` keeps the reservation held until evidence resolves the provider side effect. Deterministic pre-capture failure releases the reservation. Terminal post-capture failure applies the current full-generation-refund policy exactly once.

Generation refund and Telegram payment refund are different domains: the former compensates a failed generated product in CREDIT; the latter returns the original Stars payment and reverses its CREDIT grant.

## Immutable ledger

`ledger_entries` records every financial movement with user, optional generation/reservation references, entry type, available/reserved deltas, currency, unique idempotency key, actor, reason, metadata and timestamp.

The ledger is append-only. Admin adjustments, payment credits, refund restoration and promo bonuses append new movements rather than rewriting history.

Important commercial keys:

```text
payment-credit:<provider>:<external_id>
payment-refund-debit:telegram_stars:<charge-id>:<attempt-id>
payment-refund-restore:telegram_stars:<charge-id>:<attempt-id>
promo-credit:<promo-code>:<user-id>
```

## User/admin balance adjustment

Legacy billing admin:

```text
POST /v1/admin/users/{user_id}/balance-adjustments
```

Full control plane:

```text
POST /internal/admin/users/{user_id}/balance-adjustments
```

New operator surfaces must use shared billing/admin services rather than direct SQL.

## Payment events, reprocessing and refunds

`payment_events` stores external payment evidence for operational inspection/recheck/reprocess and refund lifecycle status. Completed payment credit is deterministic; a charge with evidence but no credited ledger key can be recovered through generic payment reprocess. For Stars packages with a bonus, `PaymentEvent.amount_units` is the total base+bonus grant and therefore reprocess/refund cannot silently drop the bonus component.

Native Stars refund uses:

```text
POST /internal/admin/payments/{payment_id}/refund
POST /internal/admin/payments/{payment_id}/refund/resolve
```

The first requires confirmation, idempotency and reason. The second requires confirmation, idempotency, evidence and `refunded|not_refunded`.

## Promo definition and redemption APIs

Admin definition:

```text
GET  /internal/admin/promos/{code}
POST /internal/admin/promos
POST /internal/admin/promos/{code}/active
```

Owner redemption:

```text
POST /v1/user-portal/promos/redeem
POST /v1/miniapp/promos/redeem
```

The redemption request contains only a code. Server-side promo reward/limit policy is authoritative.

## Tariff history

The full admin contour exposes:

```text
GET  /internal/admin/tariffs
GET  /internal/admin/tariffs/versions
GET  /internal/admin/tariffs/versions/{version_id}
POST /internal/admin/tariffs/publish
```

Publishing is idempotent, audited and confirmation-gated. Historical versions are retained.

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

The browser can request an invoice or redeem a code, but cannot post payment success, request privileged refunds, choose a package bonus/reward amount or directly mutate a wallet.

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

## Reconciliation invariants

Operational checks include:

```text
wallet.available_units + wallet.reserved_units
= sum(ledger.available_delta + ledger.reserved_delta)
```

Cross-resource expectations include:

- every admitted billable generation has one reservation;
- terminal generation settlement occurs exactly once;
- a Stars `PaymentEvent` with no credited ledger key remains recoverable evidence;
- duplicate successful-payment updates cannot append duplicate payment credits;
- a Stars order with `bonus_units > 0` settles/reprocesses/refunds exactly `credits_units` total and preserves `credits_units - bonus_units > 0`;
- `refund_pending` / `refund_unknown` retain the refund debit/hold;
- `not_refunded` resolution appends at most one restore entry;
- a refund provider call never occurs before the local CREDIT hold commits;
- every successful promo redemption has exactly one matching `promo-credit:*` ledger movement;
- `(promo_code,user_id)` can consume at most one promo use;
- `promo_codes.uses` cannot exceed `max_uses` through concurrent redemption.

Automated reconciliation may apply only deterministic local fixes. It does not guess ambiguous external side effects or fabricate promo/package rewards.

## Security requirements

Use separate credentials for ordinary internal generation API, legacy billing-admin API and full admin HMAC control plane. None belong in a public client or Mini App.

Every manual money mutation/refund resolution must include attributable admin context. Promo and Stars package reward/bonus amounts remain server-side policy; the public client sends only the promo code or package code.

## Change checklist

A billing/pricing/payment/promo change must update:

- SQLAlchemy model/migration when schema changes;
- atomic settlement/redemption and duplicate/concurrency tests;
- durable external evidence expectations when relevant;
- E2E coverage for cross-layer financial workflows;
- reconciliation expectations;
- API, billing, schema, Mini App/testing documentation.
