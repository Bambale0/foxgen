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

User top-up/refund recovery is a separate financial boundary: Telegram Stars payment validation, settlement and refund reconciliation do not depend on `FOXGEN_TASK_SUBMISSION_ENABLED`, because disabling new provider generations must not prevent an already paid user transaction from being recorded or reconciled.

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

## Telegram Stars top-up

Digital-credit top-up inside Telegram uses Telegram Stars (`XTR`) and the latest published tariff package data. A package is purchasable only when it explicitly contains a positive integer CREDIT amount (`credits_units` or legacy `credits`) and positive integer Stars amount (`stars_amount` or `stars`).

Before FoxGen calls Telegram to create an invoice link, it creates a durable `user_payment_orders` row and snapshots package terms. The order is idempotent on `(user_id, Idempotency-Key)`.

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

A verified Telegram `successful_payment` uses two durable boundaries:

1. persist charge evidence (`PaymentEvent`, Telegram charge ID and `paid` order state);
2. settle wallet and immutable ledger using:

```text
payment-credit:telegram_stars:<telegram_payment_charge_id>
```

If the second boundary fails, the payment evidence survives and the admin payment reprocess worker can recover CREDIT exactly once.

## Telegram Stars refund

Native Stars refund is a separate privileged financial lifecycle. It is deliberately not a public browser/bot balance mutation.

### Eligibility

A refund can begin only when:

- payment provider is `telegram_stars`;
- the payment already has a credited ledger key;
- the durable order is `credited`;
- no active refund attempt exists;
- the user still has at least the original credited CREDIT available.

The last rule is deliberate in this first refund policy: FoxGen does not create a negative wallet or partially reclaim CREDIT already spent.

### CREDIT hold before external refund

Before Telegram is contacted, FoxGen commits the local reversal intent atomically:

```text
available_units -= original credited units
ledger += payment-refund-debit:telegram_stars:<charge-id>:<attempt-id>
payment_refund_attempts += pending attempt
order/payment -> refund_pending
COMMIT
```

This debit is both a hold and the final financial reversal if Telegram successfully refunds the Stars. It prevents the user from spending the same CREDIT while an external refund is pending.

If the user lacks enough available CREDIT, the refund command fails before any Telegram side effect.

### Dedicated external-side-effect worker

`PaymentRefundWorker` owns the native `refundStarPayment` call. It uses a dedicated durable refund-attempt queue with leasing/retry state instead of the generic admin outbox.

Success:

```text
attempt -> succeeded
order/payment -> refunded
refund debit remains final
```

Deterministic provider rejection before refund:

```text
ledger += payment-refund-restore:telegram_stars:<charge-id>:<attempt-id>
available_units += held units
attempt -> failed
order -> credited
payment -> completed
```

Ambiguous network/server/rate-limit outcome:

```text
bounded retry with CREDIT hold preserved
max attempts reached -> attempt = unknown
order/payment -> refund_unknown
```

A retry that observes the original charge already refunded converges to success instead of creating another financial effect.

### Evidence resolution

`refund_unknown` is not guessed away. The privileged resolution command requires an explicit outcome and evidence.

If evidence proves refund occurred, the debit remains final and order/payment become refunded. If evidence proves refund did not occur, FoxGen appends the deterministic restore ledger entry and restores CREDIT exactly once.

Replay protection therefore exists at both levels:

- admin command idempotency protects the operator request;
- immutable debit/restore ledger keys protect the money movement itself.

See `telegram-stars-payments.md` for the complete transport/state lifecycle.

## Atomic generation reservation

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

## Generation settlement lifecycle

Reservation states:

```text
reserved -> captured
reserved -> released
captured -> refunded
```

When provider acceptance is durably verified, reserved units are captured. `submission_unknown` keeps the reservation held until evidence resolves the provider side effect. Deterministic pre-capture failure releases the reservation. Terminal post-capture failure applies the current full-generation-refund policy exactly once.

Generation refund and Telegram payment refund are different domains: the former compensates a failed generated product in CREDIT; the latter returns the original Telegram Stars payment and reverses the corresponding CREDIT grant.

## Immutable ledger

`ledger_entries` records every financial movement with user, optional generation/reservation references, entry type, available/reserved deltas, currency, unique idempotency key, actor, reason, metadata and timestamp.

The ledger is append-only. Admin adjustments, payment credits and refund restoration do not rewrite previous entries; they append new movements.

Important payment keys:

```text
payment-credit:<provider>:<external_id>
payment-refund-debit:telegram_stars:<charge-id>:<attempt-id>
payment-refund-restore:telegram_stars:<charge-id>:<attempt-id>
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

`payment_events` stores external payment evidence for operational inspection/recheck/reprocess and refund lifecycle status.

A completed payment credit is deterministic, so repeated reprocess cannot credit twice. A Telegram charge with evidence but no credited ledger key can be recovered through generic payment reprocess.

Native Stars refund uses dedicated endpoints and `payment_refund_attempts` rather than generic payment reprocess:

```text
POST /internal/admin/payments/{payment_id}/refund
POST /internal/admin/payments/{payment_id}/refund/resolve
```

The first action requires confirmation, idempotency and a reason. The second requires confirmation, idempotency, evidence and `refunded|not_refunded`.

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

The browser can request an invoice but cannot post payment success, request privileged refunds or mutate a wallet.

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

Cross-resource expectations include:

- every admitted billable generation has one reservation;
- terminal generation settlement occurs exactly once;
- a Stars `PaymentEvent` with no credited ledger key remains visible as paid-but-uncredited evidence;
- duplicate successful-payment updates cannot append duplicate payment credits;
- `refund_pending` and `refund_unknown` retain the refund debit/hold;
- successful/refunded resolution never appends a restore entry;
- `not_refunded` resolution appends at most one restore entry;
- a refund provider call never occurs before the local CREDIT hold commits.

Automated reconciliation may apply only deterministic local fixes. It does not guess ambiguous external side effects.

## Security requirements

Use separate credentials for ordinary internal generation API, legacy billing-admin API and full admin HMAC control plane. None belong in a public client or Mini App.

Every manual money mutation/refund resolution must include attributable admin context and human-readable reason/evidence. Do not bypass shared services with direct SQL.

## Change checklist

A billing/pricing/payment change must update:

- SQLAlchemy model/migration if schema changes;
- atomic settlement/refund and duplicate-event tests;
- durable external-payment/refund evidence expectations;
- E2E coverage for cross-layer financial workflows;
- reconciliation expectations;
- relevant API, billing, Telegram payment, schema, admin and operations documentation.
