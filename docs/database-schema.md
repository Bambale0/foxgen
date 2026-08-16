# Durable database schema map

PostgreSQL is FoxGen's durable source of truth. This document maps table responsibilities and critical constraints; SQLAlchemy models and Alembic migrations remain authoritative for exact columns/types.

## Core users and generation

### `users`

Telegram/internal user identity (`id`, optional username, creation time). Generation, wallet and user payment rows reference users.

### `user_restrictions`

Administrative block state used by paid generation admission. A blocked user is rejected transactionally even if a stale client still shows generation controls.

### `generations`

One durable generation per user/idempotency key. Key responsibilities:

- model/media/prompt/input payload;
- durable lifecycle state;
- provider task identity;
- result/error/failure metadata;
- lifecycle timestamps and polling schedule.

Unique invariant:

```text
(user_id, idempotency_key)
```

Current status constraint:

```text
draft, queued, submitting, submitted, processing,
submission_unknown, result_ready, storing_media,
delivery_pending, succeeded, failed, cancelled
```

### `provider_events`

Deduplicated provider callback inbox. Event hash uniqueness prevents the same provider event from being processed as a new callback repeatedly.

### `outbox_events`

Durable generation/local work queue with event type, aggregate ID, deduplication key, payload, status, attempts, availability, lease/worker data and failure metadata.

## Media and Telegram delivery

### `media_assets`

One result-archive row per generation/source URL with deterministic storage key metadata, content type, size, checksum, attempts/retry/error state.

### `generation_deliveries`

One Telegram delivery record per generation. States include `pending`, `retry_wait`, `sending`, `sent`, `delivery_unknown`, `failed`.

## Billing and user payments

### `wallet_accounts`

Materialized per-user balance:

- `available_units`;
- `reserved_units`;
- currency;
- version.

Database checks prevent negative available/reserved values.

### `model_prices`

Versioned runtime model price history. Uniqueness on `(model_slug, version)`; amount must be positive.

### `balance_reservations`

One generation billing reservation with settlement state:

```text
reserved, captured, released, refunded
```

### `ledger_entries`

Append-only financial movements with unique idempotency key, actor/reason and available/reserved deltas.

Payment-related deterministic keys include:

```text
payment-credit:<provider>:<external_id>
payment-refund-debit:telegram_stars:<charge-id>:<attempt-id>
payment-refund-restore:telegram_stars:<charge-id>:<attempt-id>
```

### `user_payment_orders`

Durable user checkout order introduced by Alembic revision `20260816_0012`. Commercial terms are snapshotted before external invoice creation.

Critical uniqueness:

```text
(user_id, idempotency_key)
invoice_payload
telegram_payment_charge_id
```

Revision `20260816_0013` extends the status constraint for native Stars refunds:

```text
created
invoice_ready
paid
credited
refund_pending
refund_unknown
refunded
failed
```

`paid` proves Telegram charge evidence exists before CREDIT settlement. `refund_pending` means the original CREDIT has already been removed locally and the dedicated refund worker is expected to converge. `refund_unknown` means the external refund result is ambiguous and the CREDIT hold must remain until evidence resolution.

### `payment_refund_attempts`

Introduced by Alembic revision `20260816_0013`. This table is both refund audit record and dedicated external-side-effect queue; native Stars refund does not use the generic admin outbox.

Important columns:

- `payment_id`, `order_id`, `user_id`;
- provider and original Telegram charge ID;
- CREDIT amount/currency being reversed;
- human reason and requesting admin;
- status, attempts, `available_at`, `locked_at` lease state;
- unique debit ledger key;
- optional unique restore ledger key;
- provider payload/error/evidence-resolution metadata;
- attempted/resolved/created/updated timestamps.

Allowed states:

```text
pending
processing
succeeded
failed
unknown
resolved_refunded
resolved_not_refunded
```

Critical rules:

- `amount_units > 0`;
- `attempts >= 0`;
- debit ledger key is unique;
- restore ledger key is unique when present;
- payment/order foreign keys cascade with their parent financial record;
- a successful refund keeps the debit and never creates a restore key;
- a deterministic rejection or `not_refunded` evidence resolution restores CREDIT through the unique restore key;
- `unknown` intentionally retains the debit/hold.

## Administrative control plane

### `admin_users`

Durable RBAC identity: role, explicit scopes and active flag.

### `admin_commands`

Idempotent write-command ledger. Unique key:

```text
(admin_user_id, action, idempotency_key)
```

Stars refund/refund-resolution commands are recorded here independently from financial ledger idempotency.

### `admin_audit_events`

Append-only administrative outcome/audit event with actor, request ID, action, target, outcome and redacted-safe payload.

### `admin_outbox`

Durable general administrative background work, including payment recheck/reprocess, support and campaign jobs. Native Stars refund is intentionally excluded because `payment_refund_attempts` owns that external financial side effect and its ambiguity semantics.

## Commercial/admin content

### `tariff_versions`

Immutable/versioned tariff payload history. Stars package values are copied into `user_payment_orders` before checkout.

### `payment_events`

Provider payment evidence record. Unique `(provider, external_id)`, amount/currency, raw provider payload, timestamps and optional unique credited ledger key.

For Telegram Stars, `external_id` is the Telegram payment charge ID. Payment status evolves through top-up/refund lifecycle (`completed`, `refund_pending`, `refund_unknown`, `refunded`) while the original external charge identity remains unchanged.

A charge with no credited ledger key but completed payment evidence is recoverable through payment reprocess. A credited charge entering native refund is linked to a `payment_refund_attempts` record by `payment_id`.

### `operation_events`

Administrative/operational timeline. Can reference a generation and parent operation, enabling auditable replay child chains.

## Support

### `support_tickets`

User support case with subject, status, assigned admin, priority and operator note.

### `support_messages`

Messages attached to a ticket, with sender kind/identity, body and delivery/storage status.

### `support_outbox`

Durable Telegram reply send queue with retry/lease state.

## CMS and notifications

### `cms_documents` / `cms_document_versions`

Stable document identity and immutable version history.

### `notification_campaigns` / `notification_deliveries`

Campaign definitions and durable per-recipient deliveries.

## Partners and promos

### `partner_profiles` / `partner_withdrawals`

Materialized partner state and withdrawal requests.

### `promo_codes`

Promo identity, active state, reward and usage counters.

## Prompt/runtime/moderation administration

`prompt_library_items`, `runtime_flags`, `model_availability`, `trend_items` and `feed_moderation_actions` store the corresponding admin-managed durable state.

## Foreign-key/delete intent

Operational/audit relationships use delete behavior appropriate to their lifecycle, but ORM/database cascades are not permission to delete production financial history. Retention is a product/security decision.

## Migration discipline

- Do not edit historical deployed migrations.
- Add a forward Alembic revision.
- Import new SQLAlchemy metadata into `migrations/env.py`.
- Keep check constraints synchronized with runtime state transitions.
- Extend `scripts/check_schema.py` for critical new tables/columns.
- Run upgrade/head/downgrade/re-upgrade CI.
- Document rollback consequences.

For revision `20260816_0013`, downgrade is safe before refund-state data exists. An operator must not blindly downgrade a production database containing `refund_pending`, `refund_unknown` or refund-attempt records because the prior order-status constraint does not represent those states.

## Financial/audit immutability

For normal operation:

- never UPDATE/DELETE ledger history to repair a balance;
- never discard verified external payment/refund evidence because a later local transaction failed;
- never restore an ambiguous refund hold by direct SQL;
- use compensating immutable entries and evidence-based resolution;
- never rewrite admin command/audit history to hide an action.

## Related docs

- `architecture.md` — data ownership and pipelines;
- `billing.md` — financial lifecycle;
- `telegram-stars-payments.md` — checkout/refund/evidence lifecycle;
- `api-reference.md` — public/trusted/admin routes;
- migrations/models — exact schema source of truth.
