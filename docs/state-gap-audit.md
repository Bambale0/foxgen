# FoxGen state gap audit

This audit records the state machines and the completed implementation order for the production generation lifecycle.

## 1. Telegram conversation state

The generation FSM includes the standard photo/video flow and the Quick Start reference path:

```text
quick_start_waiting_media
reference_choosing_product
reference_choosing_model
reference_waiting_prompt
choosing_mode
choosing_model
waiting_prompt
waiting_media
choosing_aspect_ratio
choosing_quality
choosing_duration
choosing_audio
confirming
submitting
```

### Completed — epic #35

- a typed state table covers success, back, cancel, timeout, invalid input and stale callbacks for every declared state;
- reference-prefilled navigation preserves the uploaded object key and selected settings;
- invalid input keeps the active draft and repeats the expected action;
- stale callbacks do not destroy a known active draft;
- Redis event isolation serializes updates for one FSM key across concurrent polling tasks and replicas;
- Telegram albums fail closed before download;
- Telegram download and object-storage failures have separate retryable error codes;
- explicit menu/cancel/reference replacement deletes known `inputs/` objects;
- object-storage lifecycle rules cover abandoned inputs after Redis TTL.

## 2. Durable generation state

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

### Completed — epic #36

- a central transition graph validates every durable state change;
- provider processing is visible through callback and polling paths;
- provider success becomes `result_ready`, not premature product success;
- result storage and Telegram delivery are separate durable stages;
- stage timestamps, safe reason codes and failure stages are persisted;
- success is recorded only after confirmed Telegram delivery;
- stale submitting leases move to `submission_unknown` without another provider POST;
- owner-bound status and pre-submit cancellation APIs are available;
- cancellation atomically releases billing reservations and suppresses pending submission work;
- evidence-based operator resolution is available for `submission_unknown`;
- provider-started work cannot be cancelled through the user endpoint.

The billable provider POST remains single-attempt. `submission_unknown` is never automatically resubmitted.

## 3. Outbox, media, delivery and billing

```text
outbox: pending, retry_wait, processing, completed, dead_letter
media: pending, retry_wait, stored, failed
delivery: pending, retry_wait, sending, sent, delivery_unknown, failed
reservation: reserved, captured, released, refunded
```

### Completed — epic #37

- retryable and terminal outbox failures are classified separately;
- exhausted or terminal work enters observable `dead_letter` state;
- dead-lettered submission, storage and delivery work settles generation and billing atomically;
- each result URL has independent attempts, retry time and failure metadata;
- partial multi-file storage skips already durable assets on retry;
- delivery retry is allowed only before the non-idempotent Telegram send starts;
- `delivery_unknown` is never replayed automatically;
- operator controls support verified mark-sent, confirmed-not-sent retry and terminal failure/refund;
- reconciliation reports outbox, media, delivery, generation and reservation mismatches;
- safe reconciliation fixes only deterministic local invariants;
- operational procedure is documented in `docs/postprocessing-reconciliation.md`.

## Implementation order

1. #34 — Quick Start and inbound reference routing — completed.
2. #35 — Telegram FSM and recovery matrix — completed.
3. #36 — durable generation lifecycle — completed.
4. #37 — billing/outbox/media/delivery reconciliation — completed.

Production deployment remains gated by migration checks, the full CI workflow and the protected production deployment workflow.
