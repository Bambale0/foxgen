# Post-processing reconciliation

FoxGen treats provider submission, result storage, Telegram delivery and billing as separate recoverable stages. The reconciliation controls never repeat an ambiguous external side effect automatically.

## Outbox states

- `pending` — ready for the first attempt;
- `retry_wait` — retryable failure with a future `available_at`;
- `processing` — leased by one worker;
- `completed` — handled or deliberately suppressed;
- `dead_letter` — terminal failure or exhausted retry budget;
- `failed` — legacy compatibility value; migration converts existing rows to `dead_letter`.

Each failed event records a low-cardinality `failure_class`, bounded error text and `dead_lettered_at`. A dead-lettered submission, archive or delivery event moves the generation to an explicit terminal failure and settles the reservation in the same transaction. Provider callback dead letters do not fail the generation because polling can still recover it.

## Partial media storage

Each result URL has its own `media_assets` row before download starts.

- `pending` — one storage attempt is active;
- `retry_wait` — a retryable download/storage failure occurred;
- `stored` — the object and checksum are durable;
- `failed` — a terminal validation or provider result error occurred.

A multi-file result may therefore contain both `stored` and `retry_wait` assets. The next archive attempt skips durable assets and resumes only incomplete files. Delivery is created only after every result URL is stored.

## Delivery states

- `pending` — safe to begin a send;
- `retry_wait` — failure happened before Telegram send started;
- `sending` — the non-idempotent Telegram request started;
- `sent` — Telegram message IDs are stored;
- `delivery_unknown` — the send may have succeeded but the response was lost;
- `failed` — operator-confirmed or terminal delivery failure.

`delivery_unknown` is never retried automatically. An administrator must inspect Telegram history and choose exactly one action:

1. `mark_sent` with verified message IDs;
2. `retry` only with `confirmed_not_sent=true` and a new idempotency key;
3. `failed` to terminate the generation and refund the captured amount.

## Admin API

Read-only report:

```text
GET /v1/admin/reconciliation?limit=100
```

Safe reconciliation:

```text
POST /v1/admin/reconciliation/run
{
  "apply_safe_fixes": true,
  "limit": 100
}
```

Safe fixes are limited to deterministic local invariants:

- capture a reservation after verified provider acceptance;
- release/refund reservations for terminal generations;
- mark a `delivery_pending` generation successful when its delivery is already durably `sent`.

The reconciler does not submit provider tasks, redownload arbitrary URLs, or resend ambiguous Telegram messages.

Manual delivery resolution:

```text
POST /v1/admin/generations/{generation_id}/resolve-delivery
```

Retry example:

```json
{
  "action": "retry",
  "confirmed_not_sent": true,
  "idempotency_key": "delivery-retry-20260725-001",
  "reason": "Telegram history and recipient chat confirm no message"
}
```

Mark-sent example:

```json
{
  "action": "mark_sent",
  "telegram_message_ids": [123456],
  "reason": "Message verified in recipient chat"
}
```

## Operational checklist

1. Run the read-only report first.
2. Resolve `delivery_unknown` manually before applying broad safe fixes.
3. Run safe reconciliation.
4. Confirm `dead_letter`, `retry_wait`, reservation mismatches and delivery mismatches decreased.
5. Investigate recurring failure classes before requeueing dead letters.
6. Keep provider submission and ambiguous Telegram sends outside automatic retry policies.
