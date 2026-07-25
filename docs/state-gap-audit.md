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

Added in the first Quick Start slice:

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

A received image can start image-edit or image-to-video. A received video can start reference-to-video. Photo generation from a video uses the Telegram-provided video cover and the UI states this explicitly; when Telegram provides no cover, the bot asks for a separate frame instead of silently sending a video URL to an image model.

### Remaining Telegram gaps — epic #35

- explicit expired-draft and recovery UX after Redis TTL;
- upload-in-progress state and duplicate update protection;
- album/media-group aggregation;
- common retryable/terminal error state contract;
- complete back navigation for reference-prefilled option screens;
- cleanup/retention policy for abandoned input objects;
- formal state table covering success, back, cancel, timeout, invalid input and stale callback for every state.

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

1. #34 — Quick Start and inbound reference routing.
2. #35 — complete Telegram FSM/recovery matrix.
3. #36 — durable generation lifecycle expansion.
4. #37 — billing/outbox/media/delivery reconciliation.

Each stage is delivered as a separate reviewable branch and pull request. Production deployment remains gated by CI and the production deployment workflow.
