# Telegram Stars payments

FoxGen uses Telegram Stars (`XTR`) for user purchases of digital FoxGen credits inside Telegram bot / Happy Fox.

Official references:

- https://core.telegram.org/bots/payments-stars
- https://core.telegram.org/bots/api#payments

## Product boundary

Stars top-up is independent from generation reservation/capture/refund. A completed top-up increases the user's available `CREDIT` balance through the existing immutable ledger; later generation admission spends that balance through the existing reservation lifecycle.

The browser and Telegram bot never mutate wallet rows directly.

## Tariff package contract

Top-up offers come from the latest published `tariff_versions.payload.packages` object. Existing non-Stars packages remain valid tariff data but are not purchasable through the Stars transport until they explicitly publish a Stars amount.

Example:

```json
{
  "packages": {
    "starter": {
      "title": "Starter",
      "description": "1000 FoxGen credits",
      "credits": 1000,
      "price": 199,
      "stars": 50
    }
  }
}
```

Accepted credit fields are `credits_units` or the legacy `credits`. Accepted Stars fields are `stars_amount` or `stars`. Both must be positive integers. A package without explicit Stars pricing is filtered out of the Stars catalog and cannot create an invoice.

Commercial package terms are snapshotted into `user_payment_orders` before the external Telegram invoice-link call. Later tariff changes therefore cannot change the amount/credits of an already-created order.

## Durable states

`user_payment_orders.status`:

```text
created -> invoice_ready -> credited
                     \-> failed
credited -> refunded   # reserved for the refund slice
```

`created` is durable before `createInvoiceLink`. Repeating invoice creation with the same `(user_id, Idempotency-Key)` returns the same order. A request using the same key with a different package fails with an idempotency conflict.

Creating an invoice link is not a financial mutation. A network ambiguity may create more than one equivalent Telegram invoice link for the same local order, but only a verified `successful_payment` can credit the wallet.

## Telegram flow

1. FoxGen creates or replays the durable payment order.
2. Backend calls Telegram `createInvoiceLink` with:
   - `currency=XTR`;
   - one price item;
   - no third-party provider token;
   - opaque local `invoice_payload` (`foxgen-stars:<order UUID>`).
3. Before payment Telegram sends `pre_checkout_query` to the bot.
4. The bot asks the trusted backend to verify owner, payload, XTR currency and snapshotted amount.
5. Telegram sends a message containing `successful_payment` after payment.
6. The bot forwards only the payment identifiers/amount/payload to the trusted backend.
7. Backend atomically persists the payment and ledger credit.

The pre-checkout route is validation-only. It cannot add credits.

## Exactly-once credit

Successful payment settlement is serialized by the Telegram payment charge ID and commits these changes in one PostgreSQL transaction:

```text
user_payment_orders
  + payment_events(provider=telegram_stars, external_id=<charge id>)
  + wallet_accounts.available_units
  + ledger_entries(payment-credit:telegram_stars:<charge id>)
```

Uniqueness exists at three levels:

- one local order per `(user_id, idempotency_key)`;
- one order per `telegram_payment_charge_id`;
- one immutable ledger entry per deterministic payment-credit key.

A duplicate Telegram update returns the already-credited balance and does not append another credit.

The Telegram charge ID is retained because Telegram Stars refunds require it. Refund execution is intentionally a separate reviewed slice.

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

The Mini App receives an invoice URL, not a Telegram bot token or provider credential. Checkout completion still arrives to the bot through Telegram updates and settles server-side.

## Failure rules

- missing/changed package price: fail before invoice creation;
- Telegram invoice API timeout: local order stays durable and can retry;
- missing/foreign order at pre-checkout: reject checkout;
- amount/currency mismatch: reject checkout/settlement;
- duplicate charge on another order: idempotency conflict;
- backend failure after Telegram reports payment: user is told not to pay again; durable order/payment evidence is preserved for support/reconciliation;
- `FOXGEN_TASK_SUBMISSION_ENABLED=false` does not disable top-up validation or settlement.

## Operations

For a user reporting paid Stars without CREDIT:

1. do not ask them to pay again;
2. locate the order by user/payment payload;
3. inspect `telegram_payment_charge_id`, `payment_events` and deterministic ledger key;
4. if Telegram delivered `successful_payment`, reconcile from that evidence;
5. never create a manual duplicate payment credit when the deterministic ledger key already exists.

Admin payment inspection/reprocessing remains the operator plane. User Mini App credentials cannot access admin payment actions.
