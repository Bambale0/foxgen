# Telegram Stars payments

FoxGen uses Telegram Stars (`XTR`) for user purchases of digital FoxGen credits inside Telegram bot / Happy Fox. The same durable payment identity is retained for privileged native Stars refunds.

Official references:

- https://core.telegram.org/bots/payments-stars
- https://core.telegram.org/bots/api#payments
- https://core.telegram.org/bots/api#refundstarpayment

## Product boundary

Stars top-up is independent from generation reservation/capture/refund. A completed top-up increases the user's available `CREDIT` balance through the immutable ledger; later generation admission spends that balance through the existing reservation lifecycle.

The browser and Telegram bot never mutate wallet rows directly. User payment settlement and Stars refunds remain server-side financial operations.

## Tariff package contract

Top-up offers come from the latest published `tariff_versions.payload.packages` object. Existing non-Stars packages remain valid tariff data but are not purchasable through the Stars transport until they explicitly publish a Stars amount.

Example with explicit package bonus:

```json
{
  "packages": {
    "starter": {
      "title": "Starter",
      "description": "1000 FoxGen credits + 250 bonus",
      "credits": 1000,
      "bonus_units": 250,
      "price": 199,
      "stars": 50
    }
  }
}
```

Accepted base CREDIT fields are `credits_units` or legacy `credits`. Accepted Stars fields are `stars_amount` or `stars`; both must be positive integers. An optional purchase bonus may be supplied as `bonus_units` or `bonus_credits` and must be a non-negative integer. Missing bonus means zero. Negative, boolean or non-integer bonus values make that package unavailable to the Stars purchase flow.

The public package projection exposes:

```text
credits_units       total CREDIT grant (base + bonus; backward-compatible field)
base_credits_units  base package CREDIT
bonus_units         explicit package bonus
total_credits_units base + bonus
stars_amount        XTR price
```

Commercial package terms are snapshotted into `user_payment_orders` before the external Telegram invoice-link call. The durable order stores total CREDIT in `credits_units` and the bonus component in `bonus_units`; base CREDIT is `credits_units - bonus_units`. Later tariff changes cannot change base CREDIT, bonus CREDIT or XTR price of an already-created order. User-supplied titles/descriptions are normalized to Telegram invoice field limits before provider submission.

The browser cannot submit a bonus amount. Happy Fox invoice creation sends only `package_code` plus authenticated/idempotency context.

## Durable order states

`user_payment_orders.status`:

```text
created -> invoice_ready -> paid -> credited
                     \                 |
                      \-> failed       +-> refund_pending -> refunded
                                           |
                                           +-> refund_unknown
                                                 |
                                                 +-> refunded
                                                 +-> credited
```

`created` is durable before `createInvoiceLink`. Repeating invoice creation with the same `(user_id, Idempotency-Key)` returns the same order. A request using the same key with a different package fails with an idempotency conflict.

`paid` is the external payment side-effect boundary: Telegram has confirmed a unique charge, its `PaymentEvent` and charge ID are durably committed, but CREDIT settlement may still be pending. `pre_checkout_query` rejects a `paid` order so an already charged invoice cannot be approved again while recovery is in progress.

`refund_pending` means the granted CREDIT has already been removed from the user's available balance and a durable refund attempt is waiting for/processing the Telegram refund call. `refund_unknown` means the external refund result is ambiguous after bounded retries; the CREDIT hold remains until evidence-based operator resolution.

## Checkout flow

1. FoxGen creates or replays the durable payment order and snapshots base/bonus/XTR terms.
2. Backend calls Telegram `createInvoiceLink` with `currency=XTR`, one price item and the opaque local invoice payload.
3. Telegram sends `pre_checkout_query`; the bot asks the trusted backend to validate owner, payload, currency and snapshotted XTR amount.
4. Telegram sends `successful_payment` after payment.
5. Backend commits charge evidence and moves the order to `paid`.
6. Backend performs a separate idempotent total-CREDIT settlement and moves the order to `credited`.

The pre-checkout route is validation-only. It cannot add credits.

## Exactly-once credit and durable recovery

Settlement is serialized by the Telegram payment charge ID and intentionally uses two PostgreSQL transactions.

### Boundary 1 — external payment evidence

```text
successful_payment
  -> user_payment_orders.telegram_payment_charge_id
  -> user_payment_orders.status = paid
  -> user_payment_orders.paid_at
  -> payment_events(provider=telegram_stars, external_id=<charge id>, amount_units=<base+bonus>)
COMMIT
```

This commit happens before wallet mutation. If the later CREDIT settlement fails, FoxGen still knows Telegram charged the user and the user does not need to pay again. `PaymentEvent.amount_units` is the full snapshotted CREDIT grant, so generic reprocess cannot lose the bonus component.

### Boundary 2 — CREDIT settlement

```text
payment event + paid order
  -> wallet_accounts.available_units += total credits (base + bonus)
  -> ledger_entries(payment-credit:telegram_stars:<charge id>)
  -> payment_events.credited_ledger_key
  -> user_payment_orders.status = credited
  -> user_payment_orders.credited_at
COMMIT
```

Uniqueness exists at three levels:

- one local order per `(user_id, idempotency_key)`;
- one order per `telegram_payment_charge_id`;
- one immutable ledger entry per deterministic payment-credit key.

Duplicate Telegram updates reuse the same evidence/ledger key and do not append another base or bonus credit. If Boundary 2 fails, the generic admin `payment.reprocess` path recovers the same total CREDIT exactly once.

## Native Telegram Stars refund

Refund execution is private admin functionality. The browser and ordinary Telegram user handlers cannot request or complete it.

Admin routes:

```text
POST /internal/admin/payments/{payment_id}/refund
POST /internal/admin/payments/{payment_id}/refund/resolve
```

Both are signed/RBAC-protected writes, require `Idempotency-Key` and explicit admin confirmation. The initial refund additionally requires a human-readable reason. Manual resolution additionally requires evidence text and one explicit outcome: `refunded` or `not_refunded`.

### Boundary 3 — CREDIT hold before provider refund

A refund can start only when:

- provider is `telegram_stars`;
- the payment has already been credited;
- the durable order is `credited`;
- no active refund attempt exists;
- the user still has at least the original total credited amount in available CREDIT.

FoxGen first commits the full original grant, including any package bonus:

```text
wallet.available_units -= total credited amount
ledger += payment-refund-debit:telegram_stars:<charge id>:<attempt id>
payment_refund_attempts(status=pending, amount_units=<base+bonus>)
user_payment_orders.status = refund_pending
payment_events.status = refund_pending
COMMIT
```

Only after that local financial boundary can the dedicated refund worker call Telegram `refundStarPayment(user_id, telegram_payment_charge_id)`. This prevents the user from spending the same CREDIT while an external refund is being attempted.

If available CREDIT is insufficient, FoxGen rejects the refund before any Telegram refund side effect. This slice intentionally does not create debt or partially reclaim previously spent credits.

### Dedicated refund worker

`PaymentRefundWorker` claims `payment_refund_attempts` with a lease and `FOR UPDATE SKIP LOCKED`-style durable ownership. It does not use the generic admin outbox for the external financial side effect.

Outcomes:

```text
Telegram confirms refund
  -> attempt = succeeded
  -> order/payment = refunded
  -> refund debit remains final

Telegram deterministically rejects refund before side effect
  -> restore CREDIT exactly once
  -> attempt = failed
  -> order = credited
  -> payment = completed

network/server/rate-limit ambiguity
  -> bounded retry with the CREDIT hold preserved
  -> after max attempts: attempt = unknown
  -> order/payment = refund_unknown
```

A retry after Telegram already performed the refund converges safely when Telegram reports the charge as already refunded. The original Telegram charge ID remains the idempotency/evidence identity.

### Ambiguous refund resolution

`refund_unknown` is not guessed away automatically.

Evidence says Telegram refunded:

```text
attempt -> resolved_refunded
order/payment -> refunded
CREDIT debit remains final
```

Evidence says Telegram did not refund:

```text
ledger += payment-refund-restore:telegram_stars:<charge id>:<attempt id>
wallet.available_units += held total amount
attempt -> resolved_not_refunded
order -> credited
payment -> completed
```

The restore ledger key is deterministic and unique, so replaying the same resolution cannot restore CREDIT twice.

## User APIs

Trusted bot transport:

```text
GET  /v1/user-portal/payments/stars/packages
POST /v1/user-portal/payments/stars/invoices
POST /v1/user-portal/payments/stars/pre-checkout
POST /v1/user-portal/payments/stars/success
```

Happy Fox user transport:

```text
GET  /v1/miniapp/payments/stars/packages
POST /v1/miniapp/payments/stars/invoices
```

Package/invoice payloads expose base, bonus and total CREDIT breakdown. Happy Fox receives an invoice URL, not a bot/provider credential. Checkout completion still arrives through Telegram updates and settles server-side. Refund endpoints are intentionally absent from the public user API.

## Failure rules

- missing/changed package price: fail before invoice creation;
- invalid base/bonus/Stars package fields: package is not purchasable;
- Telegram invoice API timeout: local order stays durable and can retry;
- missing/foreign order at pre-checkout: reject checkout;
- `paid`, `credited`, refund states, failed or refunded order at pre-checkout: reject checkout;
- amount/currency mismatch: reject checkout/settlement;
- duplicate charge on another order: idempotency conflict;
- backend failure after Telegram reports payment: durable charge evidence remains reprocessable for the same total base+bonus grant;
- insufficient available CREDIT for refund: reject before Telegram refund call;
- permanent refund rejection: restore the local CREDIT hold exactly once;
- ambiguous refund transport: retain CREDIT hold, retry within the bounded policy, then require evidence if still unknown;
- later tariff bonus changes do not alter an already-created order snapshot;
- `FOXGEN_TASK_SUBMISSION_ENABLED=false` does not disable payment settlement/refund recovery.

## Operations

### Paid Stars without CREDIT

1. Do not ask the user to pay again.
2. Locate order/payment by user, invoice payload or Telegram charge ID.
3. `user_payment_orders.status=paid` with no credited ledger key means charge evidence exists but settlement did not finish.
4. Confirm `credits_units` (total) and `bonus_units` snapshot on the order.
5. Use payment reprocess; never append a manual duplicate payment credit.

### Refund pending/unknown

1. Inspect `payment_refund_attempts`, order/payment status and debit/restore ledger keys.
2. `refund_pending` means the full CREDIT grant is already held and the worker is expected to converge.
3. `refund_unknown` means do not retry manually and do not restore CREDIT by direct SQL.
4. Obtain Telegram/provider evidence for the original charge.
5. Resolve through `/internal/admin/payments/{payment_id}/refund/resolve` with explicit evidence.
6. `refunded` keeps the debit; `not_refunded` appends exactly one compensating restore credit.

Admin payment/refund inspection remains the operator plane. User Mini App credentials cannot access admin payment actions.

## Tests

The required CI infrastructure path includes:

- Alembic upgrade/schema/downgrade/re-upgrade including `user_payment_orders.bonus_units`;
- real PostgreSQL package filtering, immutable invoice-time bonus snapshot and exactly-once total CREDIT settlement;
- real PostgreSQL refund success and idempotent command/worker execution;
- real PostgreSQL `refund_unknown -> not_refunded` recovery with exactly one restore ledger entry;
- cross-layer E2E using package `1000 CREDIT + 250 bonus` from Happy Fox package/invoice HTTP through successful payment (`1250 CREDIT`), signed admin refund (`1250` hold), dedicated worker and final refunded wallet/ledger state (`0`).

The E2E replaces only the external Telegram network adapter; FoxGen HTTP, auth, financial services, PostgreSQL state and worker behavior remain real.
