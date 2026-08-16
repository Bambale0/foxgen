# Durable database schema map

PostgreSQL is FoxGen's durable source of truth. This document maps table responsibilities and critical constraints; SQLAlchemy models and Alembic migrations remain authoritative for exact columns/types.

## Core users and generation

### `users`

Telegram/internal user identity (`id`, optional username, creation time). Generation, wallet, payment and promo-redemption rows reference users.

### `user_restrictions`

Administrative block state used by paid generation admission. A blocked user is rejected transactionally even if a stale client still shows generation controls.

### `generations`

One durable generation per user/idempotency key. Key responsibilities include model/input payload, provider identity, lifecycle/error metadata and timestamps.

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

Deduplicated provider callback inbox.

### `outbox_events`

Durable generation/local work queue with event type, aggregate ID, deduplication key, payload, status, attempts, availability and lease data.

## Media and Telegram delivery

### `media_assets`

One result-archive row per generation/source URL with deterministic storage metadata and retry/error state.

### `generation_deliveries`

One Telegram delivery record per generation with states including `pending`, `retry_wait`, `sending`, `sent`, `delivery_unknown`, `failed`.

## Billing, payments and bonuses

### `wallet_accounts`

Materialized per-user `CREDIT` balance: available/reserved units, currency and version. Database checks prevent negative available/reserved values.

### `model_prices`

Versioned runtime model price history; `(model_slug, version)` is unique and amount must be positive.

### `balance_reservations`

One generation reservation with states:

```text
reserved, captured, released, refunded
```

### `ledger_entries`

Append-only financial movements with unique idempotency key, actor/reason and available/reserved deltas.

Important deterministic keys include:

```text
payment-credit:<provider>:<external_id>
payment-refund-debit:telegram_stars:<charge-id>:<attempt-id>
payment-refund-restore:telegram_stars:<charge-id>:<attempt-id>
promo-credit:<promo-code>:<user-id>
```

### `user_payment_orders`

Durable checkout order introduced by `20260816_0012`. Commercial terms are snapshotted before external invoice creation. Revision `20260816_0013` extends the Stars refund states:

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

`paid` proves Telegram charge evidence exists before CREDIT settlement. Refund states preserve the local hold while the external Stars refund converges.

Revision `20260816_0015` adds the immutable Stars purchase-bonus component:

```text
bonus_units BIGINT NOT NULL DEFAULT 0
CHECK bonus_units >= 0
CHECK credits_units > bonus_units
```

For Stars orders, `credits_units` remains the **total CREDIT grant** consumed by settlement, generic payment reprocess and native refund. `bonus_units` records the explicit package-bonus component, so base package CREDIT is `credits_units - bonus_units`. Existing pre-bonus rows migrate as `bonus_units=0` and retain their previous semantics.

### `payment_refund_attempts`

Introduced by `20260816_0013`. This is both refund audit record and dedicated external-side-effect queue, with payment/order/user identity, original charge ID, CREDIT amount, requesting admin, lease/retry state, unique debit/restore ledger keys and evidence metadata.

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

`unknown` intentionally retains the debit/hold until evidence-based resolution. For a Stars package with an explicit bonus, `amount_units` is the same total base+bonus amount previously recorded on the payment event/order.

### `promo_codes`

Admin-defined promo policy:

- normalized code primary key;
- active flag;
- server-owned `reward_units`;
- optional `max_uses`;
- materialized `uses` counter;
- metadata and creating admin.

### `promo_redemptions`

Introduced by Alembic revision `20260816_0014`. This is the durable user-level bonus fact created in the same transaction as wallet/ledger mutation and promo-use consumption.

Columns:

```text
id
promo_code -> promo_codes.code
user_id -> users.id
reward_units
ledger_key
redeemed_at
```

Critical constraints:

```text
UNIQUE (promo_code, user_id)
UNIQUE (ledger_key)
CHECK reward_units > 0
```

`promo_code` uses `ON DELETE RESTRICT`: once a code has redemption audit rows, its definition cannot be deleted out from under those rows. Normal retirement uses `active=false`.

`user_id` follows the repository's existing user-owned financial-row delete policy. Ledger history remains the financial audit source.

The application also locks the `promo_codes` row during redemption. That lock serializes both same-user duplicate redemption and global `max_uses` consumption. The schema unique constraints remain the final durable guard.

## Administrative control plane

### `admin_users`

Durable RBAC identity: role, scopes and active flag.

### `admin_commands`

Idempotent write-command ledger unique on `(admin_user_id, action, idempotency_key)`.

### `admin_audit_events`

Append-only admin outcome/audit event.

### `admin_outbox`

Durable general administrative background work. Native Stars refund uses `payment_refund_attempts` instead because of its external financial ambiguity semantics.

## Commercial/admin content

### `tariff_versions`

Immutable/versioned tariff payload history. Stars package base CREDIT, optional explicit package bonus and XTR amount are copied into `user_payment_orders` before checkout. A later tariff publication cannot mutate an existing order snapshot.

### `payment_events`

External payment evidence unique on `(provider, external_id)`. Telegram Stars retains the original charge identity through settlement/refund states. `amount_units` records the full CREDIT grant, including an explicit Stars package bonus, so reprocess/refund converge on the same amount.

### `operation_events`

Administrative/operational timeline, optionally linked to generation/parent operation.

## Support, CMS, notifications and partners

`support_tickets`, `support_messages`, `support_outbox`, CMS version tables, notification campaign/delivery tables and partner profile/withdrawal tables own their corresponding durable state.

## Prompt/runtime/moderation administration

`prompt_library_items`, `runtime_flags`, `model_availability`, `trend_items` and `feed_moderation_actions` store their corresponding admin-managed state.

## Foreign-key/delete intent

Operational/audit relationships use delete behavior appropriate to their lifecycle, but ORM/database cascades are not permission to delete production financial history. Promo redemption deliberately restricts promo-definition deletion once redeemed.

## Migration discipline

- Do not edit historical deployed migrations.
- Add a forward Alembic revision.
- Import new SQLAlchemy metadata into `migrations/env.py`.
- Keep check constraints synchronized with runtime state transitions.
- Extend `scripts/check_schema.py` for critical new tables/columns.
- Run upgrade/head/downgrade/re-upgrade CI.
- Document rollback consequences.

Revision `20260816_0014` must not be downgraded while production code still expects user promo redemption. Downgrade drops `promo_redemptions`, so operators must treat those audit rows as retained financial/commercial evidence during rollback planning.

Revision `20260816_0015` must not be downgraded while production code expects Stars package bonus snapshots. Downgrade drops only `bonus_units`; operators must not deploy bonus-aware code against a downgraded schema, and should preserve order/payment/ledger evidence during any rollback.

## Financial/audit immutability

For normal operation:

- never UPDATE/DELETE ledger history to repair balance;
- never discard verified external payment/refund evidence because a later local transaction failed;
- never restore an ambiguous refund hold by direct SQL;
- never rewrite a Stars order's `credits_units`/`bonus_units` after invoice creation to match a later tariff;
- never credit a promo by directly incrementing wallet rows;
- use the redemption service so wallet + ledger + redemption + usage counter commit together;
- never rewrite admin command/audit history to hide an action.

## Related docs

- `billing.md` — financial lifecycle;
- `telegram-stars-payments.md` — checkout/refund/evidence and package-bonus lifecycle;
- `user-promos.md` — promo redemption lifecycle/concurrency;
- `api-reference.md` — public/trusted/admin routes;
- migrations/models — exact schema source of truth.
