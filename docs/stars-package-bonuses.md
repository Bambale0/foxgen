# Stars package purchase bonuses

This document is the focused API/testing contract for explicit Telegram Stars package bonuses.

## Server-owned tariff policy

A published Stars package may define:

```json
{
  "credits_units": 1000,
  "bonus_units": 250,
  "stars_amount": 50
}
```

Legacy aliases remain accepted: `credits`, `bonus_credits`, and `stars`.

Validation is fail-closed:

- base CREDIT must be a positive integer and not `bool`;
- bonus CREDIT must be a non-negative integer and not `bool`;
- Stars amount must be a positive integer and not `bool`;
- invalid packages are omitted from the purchasable Stars catalog.

The browser/bot never supplies or computes the bonus.

## User API projection

Both package endpoints:

```text
GET /v1/user-portal/payments/stars/packages
GET /v1/miniapp/payments/stars/packages
```

expose:

```json
{
  "code": "starter",
  "credits_units": 1250,
  "base_credits_units": 1000,
  "bonus_units": 250,
  "total_credits_units": 1250,
  "stars_amount": 50,
  "currency": "XTR"
}
```

`credits_units` intentionally remains the total grant for backward compatibility. New clients should use the explicit breakdown fields when presenting the offer.

Invoice creation remains:

```json
{"package_code": "starter"}
```

with the existing authenticated owner boundary and `Idempotency-Key`. No reward/bonus amount is accepted from the client.

## Durable snapshot

Alembic revision `20260816_0015` adds `user_payment_orders.bonus_units`.

For Stars orders:

```text
order.credits_units = total CREDIT grant
order.bonus_units   = package bonus
base CREDIT         = credits_units - bonus_units
```

The values are stored before `createInvoiceLink`; a later tariff publication cannot mutate the already-created payment order.

`PaymentEvent.amount_units`, the payment-credit ledger entry, generic payment reprocess, refund hold and refund restore all operate on the total `credits_units` amount.

## Happy Fox

`complete-menu.js` displays the total CREDIT and shows `+N бонус CREDIT` only when the server returns a positive bonus. Checkout still posts only `package_code`.

## Required tests

The normal CI release gate includes:

- Ruff formatting/lint and strict mypy;
- unit/API contract for base/bonus/total projection and package-code-only checkout;
- Alembic upgrade, critical schema check, downgrade and re-upgrade;
- real PostgreSQL package filtering and immutable invoice-time snapshot;
- real PostgreSQL duplicate successful-payment settlement proving one 1250-CREDIT wallet/payment/ledger effect;
- cross-layer E2E with only external Telegram network calls faked:
  `1000 base + 250 bonus -> 1250 CREDIT -> signed admin refund -> 1250 hold -> refund worker -> wallet 0`;
- API readiness;
- production image build/import and Trivy scan.

A change is not release-ready if unit tests pass but the real PostgreSQL/E2E or container gates fail.
