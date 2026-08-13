# Post-processing, retries and reconciliation

FoxGen separates provider submission, provider completion, result storage, Telegram delivery and billing settlement into distinct durable stages. Recovery is designed around one rule: **never repeat an ambiguous non-idempotent external side effect automatically**.

## Resource state summary

### Generation

```text
draft
queued
submitting
submitted
processing
submission_unknown
result_ready
storing_media
delivery_pending
succeeded
failed
cancelled
```

### Outbox

```text
pending
retry_wait
processing
completed
dead_letter
failed   # legacy compatibility where still represented
```

### Media asset

```text
pending
retry_wait
stored
failed
```

### Telegram delivery

```text
pending
retry_wait
sending
sent
delivery_unknown
failed
```

### Billing reservation

```text
reserved
captured
released
refunded
```

## Retry classification

Retry is permitted only when repeating the local/external action is known to be safe.

Examples generally safe for bounded retry:

- provider status GET;
- result download before durable storage;
- object-storage put under deterministic key/idempotent archive logic;
- local database/outbox processing before a non-idempotent boundary;
- notification/support work when the worker can prove send has not crossed an ambiguous boundary.

Examples not automatically retried after ambiguity:

- billable provider createTask POST;
- Telegram generation result send after `sending` starts;
- any operator action whose external financial/provider outcome cannot be proven.

## Outbox processing

Workers claim eligible events with row locks and `FOR UPDATE SKIP LOCKED`. Rows record attempts, available/retry time, lock/worker identity, last error and failure class.

A retryable failure schedules `retry_wait` with future availability. A terminal failure or exhausted budget enters `dead_letter`.

Dead-letter semantics depend on event type:

- provider callback processing can dead-letter while polling may still recover the generation;
- archive/delivery terminal failure must move generation/billing into a consistent terminal state;
- submission ambiguity must not be turned into a second provider create request.

## Partial media archive

Each provider result URL gets its own durable media record. A multi-file result may therefore be partially stored.

Example:

```text
asset A -> stored
asset B -> retry_wait
asset C -> stored
```

The next archive attempt:

- skips A/C;
- retries B only;
- does not create delivery until every required result is durable;
- uses deterministic storage metadata/keys to avoid duplicate archive rows/objects.

Terminal validation failures such as unsafe URL/result shape are not treated like transient network failures.

## Delivery boundary

Before Telegram send starts, a retry can be safe. Once delivery is marked `sending`, the system assumes the non-idempotent boundary may have been crossed.

Outcomes:

- definite success -> `sent` with Telegram message IDs;
- definite pre-send retryable failure -> `retry_wait`;
- ambiguous send result -> `delivery_unknown`;
- deterministic terminal/manual failure -> `failed`.

`delivery_unknown` is never automatically resent.

## Manual delivery resolution

Protected legacy reconciliation route:

```text
POST /v1/admin/generations/{generation_id}/resolve-delivery
```

Allowed operational decisions:

### Mark sent

Use only after verifying the message exists in the recipient chat/history.

```json
{
  "action": "mark_sent",
  "telegram_message_ids": [123456],
  "reason": "verified in recipient chat"
}
```

### Retry

Use only after confirming the original send did not happen.

```json
{
  "action": "retry",
  "confirmed_not_sent": true,
  "idempotency_key": "delivery-retry-20260813-001",
  "reason": "recipient/history confirm no Telegram message"
}
```

A fresh idempotency key provides an auditable operator decision; it does not change the rule that ambiguous sends require evidence.

### Fail

Use when delivery cannot/should not proceed. The generation becomes terminal and captured funds are settled according to current refund policy.

## Reconciliation report

```text
GET /v1/admin/reconciliation?limit=100
```

The report inspects cross-resource inconsistencies among generation, reservation, outbox, media and delivery state. Findings carry code/severity/resource context rather than silently modifying data.

Typical invariant classes include:

- terminal generation retaining wrong reservation state;
- accepted generation still holding a merely reserved balance;
- `delivery_pending` generation whose delivery is already sent;
- outbox/media/delivery rows inconsistent with their parent lifecycle;
- retry/dead-letter work requiring operator attention.

## Safe reconciliation

```text
POST /v1/admin/reconciliation/run
```

Request:

```json
{
  "apply_safe_fixes": true,
  "limit": 100
}
```

Safe fixes are intentionally narrow and local, for example:

- capture/release/refund reservation when the durable generation state already proves the correct settlement;
- mark a generation successful when its delivery is already durably `sent`;
- repair deterministic local lifecycle mismatches supported by the current reconciliation service.

Safe reconciliation does **not**:

- call provider createTask;
- guess whether `submission_unknown` was charged;
- redownload arbitrary unverified URLs as an operator shortcut;
- resend `delivery_unknown`;
- mutate ledger history in place.

## Full admin control-plane relation

The signed admin contour adds higher-level operation/timeline/audit tooling:

```text
GET  /internal/admin/operations
GET  /internal/admin/operations/{id}
GET  /internal/admin/operations/{id}/timeline
POST /internal/admin/operations/{id}/replay
POST /internal/admin/operations/{id}/refund
```

`replay` is worker-backed and restricted to safe non-billable local operation types. It is not a replacement for evidence-based provider ambiguity resolution.

## Operator procedure

1. Inspect `GET /v1/admin/reconciliation` before applying fixes.
2. Review `submission_unknown`, `delivery_unknown` and dead-letter counts separately.
3. Resolve ambiguous external effects with evidence first.
4. Run safe reconciliation for deterministic local mismatches.
5. Re-run the report and compare counts/codes.
6. Inspect recurring `failure_class` clusters.
7. Fix root cause before raising retry limits.
8. Confirm wallet/ledger/reservation invariants after any financial recovery.

## Database/queue checks

Useful operational aggregates include:

```sql
select status, count(*) from generations group by status;
select status, event_type, count(*) from outbox_events group by status, event_type;
select status, count(*) from media_assets group by status;
select status, count(*) from generation_deliveries group by status;
select status, count(*) from balance_reservations group by status;
```

For the admin contour also inspect support/notification/admin outboxes as documented in `admin-control-plane.md`.

## Incident rules

- Never convert a dead-lettered `generation.submit` into an automatic retry.
- Never clear `submission_unknown` just to release funds without provider evidence.
- Never resend `delivery_unknown` without confirming the first send did not occur.
- Never edit immutable ledger rows to make reconciliation totals match.
- Never treat increasing dead-letter/retry budgets as a substitute for fixing a repeated deterministic error.

## Related docs

- `architecture.md` — full pipeline;
- `billing.md` — settlement policy;
- `generation-operations.md` — cancellation/ambiguity operations;
- `operations-runbook.md` — production incident flow.