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

Durable generation/local work queue. Important fields include event type, aggregate ID, deduplication key, payload, status, attempts, availability, lease/worker data and failure metadata.

Current status family:

```text
pending, retry_wait, processing, completed, dead_letter, failed
```

`failed` remains for compatibility; newer retry/dead-letter behavior uses explicit retry/failure classification.

## Media and Telegram delivery

### `media_assets`

One result-archive row per generation/source URL with deterministic storage key metadata, content type, size, checksum, attempts/retry/error state.

Unique constraints prevent duplicate `(generation_id, source_url)` and storage-key ownership.

States:

```text
pending, retry_wait, stored, failed
```

### `generation_deliveries`

One Telegram delivery record per generation.

States:

```text
pending, retry_wait, sending, sent, delivery_unknown, failed
```

Stores recipient, attempts/retry scheduling, returned Telegram message IDs, last error and send time.

## Billing and user payments

### `wallet_accounts`

Materialized per-user balance:

- `available_units`;
- `reserved_units`;
- currency;
- version.

Database checks prevent negative available/reserved values.

### `model_prices`

Versioned runtime model price history. Uniqueness on `(model_slug, version)`; amount must be positive. A new active version replaces active status rather than overwriting old history.

### `balance_reservations`

One billing reservation per generation. Stores user, price, amount/currency and settlement state:

```text
reserved, captured, released, refunded
```

### `ledger_entries`

Append-only financial movements with unique idempotency key, actor/reason and available/reserved deltas. Each entry must have a non-zero financial delta.

Ledger entry types include credit/debit/reserve/capture/release/refund/adjustment semantics represented by the current domain enum/constraint.

### `user_payment_orders`

Durable user checkout order introduced by Alembic revision `20260816_0012`. The first transport is Telegram Stars.

The row snapshots commercial terms before an external invoice-link call:

- user/provider and request idempotency key;
- request hash and package code/title/description;
- CREDIT amount;
- provider amount/currency (`XTR` for Stars);
- opaque invoice payload and returned invoice URL;
- Telegram/provider charge IDs;
- raw verified payment projection;
- paid/credited timestamps.

Critical uniqueness:

```text
(user_id, idempotency_key)
invoice_payload
telegram_payment_charge_id   # nullable until Telegram confirms payment
```

Current status constraint:

```text
created, invoice_ready, paid, credited, failed, refunded
```

`created` is committed before `createInvoiceLink`. A verified Telegram `successful_payment` commits the charge ID, `paid_at` and `status=paid` before wallet settlement. `credited_at` and `status=credited` are populated only after the CREDIT settlement succeeds.

The `paid` state prevents another pre-checkout from being approved for an already charged order and makes paid-but-uncredited recovery observable: an order/payment can prove Telegram charged the user even if the later wallet transaction failed.

## Administrative control plane

Alembic revision `20260813_0008_admin_contour.py` introduces the main administrative schema groups below.

### `admin_users`

Durable RBAC identity: role, explicit scopes and active flag.

### `admin_commands`

Idempotent write-command ledger. Unique key:

```text
(admin_user_id, action, idempotency_key)
```

Stores request ID, target, request hash/payload, response payload, error and status:

```text
reserved, succeeded, failed
```

### `admin_audit_events`

Append-only administrative outcome/audit event with actor, request ID, action, target, outcome and redacted-safe payload.

### `admin_outbox`

Durable administrative background work, including payment/replay jobs. Unique deduplication key; leased retry/dead-letter states:

```text
pending, processing, retry_wait, completed, dead_letter
```

## Commercial/admin content

### `tariff_versions`

Immutable/versioned tariff payload history with positive version number and publishing admin/time. Stars-enabled user packages live inside the latest published payload but their values are copied into `user_payment_orders` before checkout, so later tariff publication cannot mutate an existing order.

### `payment_events`

Provider payment operational/evidence record. Unique `(provider, external_id)`, amount/currency, raw provider payload, check/process timestamps and optional unique credited ledger key.

For Telegram Stars, `external_id` is the Telegram payment charge ID. `successful_payment` evidence is persisted here in a committed transaction **before** the wallet/ledger settlement boundary. Thus a backend failure after Telegram charge confirmation leaves a durable completed payment event with no `credited_ledger_key`, which the existing admin payment reprocess worker can credit exactly once.

A credited payment uses deterministic billing key:

```text
payment-credit:<provider>:<external_id>
```

### `operation_events`

Administrative/operational timeline. Can reference a generation and parent operation, enabling auditable replay child chains.

## Support

### `support_tickets`

User support case with subject, status, assigned admin, priority and operator note.

Allowed states:

```text
open, pending, resolved, closed
```

### `support_messages`

Messages attached to a ticket, with sender kind/identity, body and delivery/storage status.

### `support_outbox`

Durable Telegram reply send queue. Unique deduplication key and leased status:

```text
pending, processing, retry_wait, sent, dead_letter
```

## CMS

### `cms_documents`

Stable document identity/slug/title plus pointer to the currently published version.

### `cms_document_versions`

Immutable document versions, unique on `(document_id, version)`, with body, metadata, author and optional publish time.

## Notifications

### `notification_campaigns`

Campaign definition/message/segment and lifecycle:

```text
draft, ready, running, completed, cancelled
```

### `notification_deliveries`

One recipient delivery per campaign. Unique:

```text
(campaign_id, recipient_id)
```

States:

```text
pending, processing, retry_wait, sent, failed
```

Stores attempts/lease/error and Telegram message ID.

## Partners and promos

### `partner_profiles`

Materialized partner analytics counters such as earned/withdrawn units and referral count.

### `partner_withdrawals`

Withdrawal request with positive amount, destination/reviewer metadata and states:

```text
pending, approved, paid, rejected
```

### `promo_codes`

Normalized promo identity with active flag, reward, max/current use counters, metadata and creating admin.

## Prompt/runtime/moderation administration

### `prompt_library_items`

Moderatable prompt content with author/title/text and states:

```text
pending, approved, rejected, inactive
```

### `runtime_flags`

Mutable operational flags with enabled/value payload and last updating admin.

### `model_availability`

Per-model runtime enabled/disabled override with reason/admin/timestamp. Paid admission consults this state in addition to static registry readiness.

### `trend_items`

Administrative trend content records with payload/active state.

### `feed_moderation_actions`

Durable moderation decisions against content IDs with action/reason/active flag/admin/time.

## Foreign-key/delete intent

Generation-owned media/delivery and similar child records use database foreign-key relationships appropriate to their lifecycle. Some operational/audit references intentionally use nullable/set-null semantics so deleting a parent business object does not erase the historical meaning of the administrative operation.

Do not infer permission to delete production business/audit/payment data from an ORM cascade alone. Operational retention is a product/security decision.

## Migration discipline

- Do not edit historical deployed migrations to change schema truth.
- Add a new forward Alembic revision.
- Import new SQLAlchemy metadata into migration environment when required. `payment_models` is explicitly imported by `migrations/env.py` so `user_payment_orders` participates in `Base.metadata` comparisons.
- Keep status check constraints synchronized with domain enums/transitions.
- Ensure `scripts/check_schema.py` covers critical new tables/columns.
- Run upgrade/head/downgrade-reupgrade CI.
- Document operational rollback/data-retention consequences.

## Financial/audit immutability

For normal operation:

- never UPDATE/DELETE ledger history to repair a balance;
- never discard a verified external payment merely because CREDIT settlement failed;
- never rewrite an admin command/audit result to hide an action;
- use compensating/refund/adjustment records and new audit events;
- use reconciliation/admin services instead of direct SQL.

## Related docs

- `architecture.md` — data ownership and pipelines;
- `billing.md` — financial lifecycle;
- `telegram-stars-payments.md` — Stars checkout/evidence/settlement lifecycle;
- `postprocessing-reconciliation.md` — cross-table consistency;
- `admin-capability-matrix.md` — admin domain behavior;
- migrations/models — exact schema source of truth.
