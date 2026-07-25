# FoxGen state gap audit

This audit records the current state machines, missing states and the implementation order approved for the next delivery cycle.

## 1. Telegram conversation state

Current generation FSM before this cycle:

```text
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

Added in the Quick Start cycle:

```text
quick_start_waiting_media
reference_choosing_product
reference_choosing_model
reference_waiting_prompt
```

The reference entry path is:

```text
/menu -> Быстрый запуск -> incoming photo/video
incoming photo/video with no active FSM
  -> private object upload
  -> reference_choosing_product
  -> reference_choosing_model
  -> reference_waiting_prompt (or caption reuse)
  -> choosing_aspect_ratio
  -> existing model-specific options
  -> confirming
  -> submitting
```

A received image can start image-edit or image-to-video. A received video can start reference-to-video. Photo generation from a video uses the Telegram-provided video cover and fails closed when no cover exists.

### Completed — epic #35

- a typed state table covers success, back, cancel, timeout, invalid input and stale callbacks for every declared state;
- reference-prefilled back/edit navigation preserves the uploaded object key and selected settings;
- invalid input keeps the active draft and repeats the expected action;
- stale callbacks no longer destroy a known active draft;
- callbacks after Redis TTL expiry explain the expiry and recover to the main menu;
- unknown state names from older releases are cleared safely;
- Redis event isolation serializes updates for one FSM key across concurrent polling tasks and bot replicas;
- Telegram albums are rejected before download with an explicit single-file policy;
- Telegram download failures and object-storage failures have separate retryable error codes;
- explicit menu/cancel/reference replacement deletes known `inputs/` objects;
- the production bucket lifecycle rule for abandoned `inputs/` objects is documented in `docs/input-media-lifecycle.md`;
- cleanup failures emit a low-cardinality operational warning and remain covered by the bucket lifecycle safety net.

## 2. Durable generation state

Current states:

```text
draft
queued
submitting
submitted
submission_unknown
succeeded
failed
cancelled
```

### Remaining lifecycle gaps — epic #36

- observable provider `processing` stage;
- polling/waiting mode when callback delivery is delayed;
- result-ready and media-storage stages;
- product-level delivery pending stage;
- structured failure reason codes;
- manual resolution for `submission_unknown`;
- reconciliation for expired leases and stuck generations;
- explicit cancellation policy before and after provider acceptance.

The billable provider POST must remain single-attempt. `submission_unknown` must never trigger automatic resubmission.

## 3. Outbox, media and delivery

Current states:

```text
outbox: pending, processing, completed, failed
media: pending, stored, failed
delivery: pending, sending, sent, delivery_unknown, failed
reservation: reserved, captured, released, refunded
```

### Remaining consistency gaps — epic #37

- retryable versus terminal failure classification;
- dead-letter/reconciliation visibility for outbox work;
- partial storage state for multi-file results;
- scheduled retry state and `next_retry_at`;
- manual resolution for `delivery_unknown`;
- cross-table invariant checks for generation, reservation, outbox, media and delivery;
- periodic reconciliation of stale reservations and post-processing work.

## Implementation order

1. #34 — Quick Start and inbound reference routing — completed.
2. #35 — complete Telegram FSM/recovery matrix — completed.
3. #36 — durable generation lifecycle expansion — next.
4. #37 — billing/outbox/media/delivery reconciliation.

Each stage is delivered as a separate reviewable branch and pull request. Production deployment remains gated by CI and the production deployment workflow.
