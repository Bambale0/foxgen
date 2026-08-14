# Durable database schema map

PostgreSQL is FoxGen's durable source of truth. This document maps table responsibilities and critical constraints; SQLAlchemy models and Alembic migrations remain authoritative for exact columns/types.

## Core users and generation

### `users`

Telegram/internal user identity (`id`, optional username, creation time). Generation rows reference users.

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

Publication/feed never copies provider URLs into a social table. A publication projects these stored durable result objects.

### `generation_deliveries`

One Telegram delivery record per generation.

States:

```text
pending, retry_wait, sending, sent, delivery_unknown, failed
```

Stores recipient, attempts/retry scheduling, returned Telegram message IDs, last error and send time.

## Feed, profiles and remix lineage

Alembic revision `20260814_0009_publication_feed.py` adds social/publication state without changing existing generation/billing rows.

### `public_profiles`

One public-profile sidecar per `users.id`.

Key fields:

- `user_id` — primary key and FK to `users`;
- `slug` — unique public identifier;
- optional display name and bio;
- timestamps.

The user row remains identity; this table owns presentation only.

### `publications`

Independent social projection of a generation. Fields include generation, author user, scope, active state and timestamps.

Allowed scope:

```text
feed, profile
```

Unique invariant:

```text
(generation_id, scope)
```

Publishing an already-known generation/scope reactivates the row. Unpublish sets `active=false`; generation/media rows remain intact.

Eligibility is enforced in the service rather than encoded only in schema: owner, generation `succeeded`, all required media `stored`, and no derivative in global `feed`.

### `generation_lineage`

Optional one-to-one derivative marker:

```text
generation_id -> source_publication_id
```

`generation_id` is the primary key, so a generation has at most one social remix source. The source publication uses restrictive delete semantics so lineage cannot silently lose meaning through source deletion.

For paid remixes the lineage row is inserted in the same database transaction as generation admission, balance reservation and submit-outbox creation. The source publication ID is also part of the submission request fingerprint.

### `publication_likes`

Composite primary key:

```text
(publication_id, user_id)
```

This makes `liked=true` state-setting naturally idempotent and prevents counter drift from duplicate toggle requests. Counts are derived from rows rather than maintained by an independently mutable cached integer.

### `publication_comments`

Comment row with publication, author, body, surface and timestamps.

Allowed surface:

```text
feed, profile
```

The repository additionally verifies that the requested comment surface equals the publication's own scope, preventing feed/profile thread leakage.

## Billing

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

Immutable/versioned tariff payload history with positive version number and publishing admin/time.

### `payment_events`

Provider payment operational record. Unique `(provider, external_id)`, amount/currency, raw provider payload, check/process timestamps and optional unique credited ledger key.

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

This admin moderation overlay is not publication storage; social state lives in the publication tables above.

## Foreign-key/delete intent

Generation-owned media/delivery and similar child records use database foreign-key relationships appropriate to their lifecycle. Some operational/audit references intentionally use nullable/set-null semantics so deleting a parent business object does not erase the historical meaning of the administrative operation.

Publication lineage is intentionally stricter: deleting a source publication must not silently orphan/erase derivative meaning.

Do not infer permission to delete production business/audit data from an ORM cascade alone. Operational retention is a product/security decision.

## Migration discipline

- Do not edit historical deployed migrations to change schema truth.
- Add a new forward Alembic revision.
- Import new SQLAlchemy metadata into migration environment when required.
- Keep status/scope check constraints synchronized with domain enums/transitions.
- Ensure `scripts/check_schema.py` covers critical new tables/columns where required by production gate.
- Run upgrade/head/downgrade-reupgrade CI.
- Document operational rollback/data-retention consequences.

## Financial/audit immutability

For normal operation:

- never UPDATE/DELETE ledger history to repair a balance;
- never rewrite an admin command/audit result to hide an action;
- use compensating/refund/adjustment records and new audit events;
- use reconciliation/admin services instead of direct SQL.

Publication/unpublish is deliberately separate from this financial history and never changes ledger/reservation records.

## Related docs

- `architecture.md` — data ownership and pipelines;
- `billing.md` — financial lifecycle;
- `feed-profile-remix.md` — social projection and remix invariants;
- `postprocessing-reconciliation.md` — cross-table consistency;
- `admin-capability-matrix.md` — admin domain behavior;
- migrations/models — exact schema source of truth.
