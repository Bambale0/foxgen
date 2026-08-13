# FoxGen state-machine audit

This document began as a gap analysis. It is now a completion/status record for the state machines implemented through the Telegram FSM, durable generation lifecycle, post-processing reconciliation and administrative control plane.

## 1. Telegram conversation state

Declared generation states:

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

Implemented invariants:

- every declared state has a behavior contract for success/back/cancel/timeout/invalid input/stale callback;
- known active drafts survive unrelated stale callbacks/messages;
- expired/unknown state recovers fail-closed;
- reference-prefilled drafts preserve stored media across back/edit navigation;
- Quick Start and no-active-FSM photo/video inputs route into reference product/model/settings flow;
- Redis event isolation serializes concurrent updates for one FSM key;
- Telegram albums are rejected before download;
- transfer/storage failures do not advance FSM;
- duplicate paid confirmation converges through durable idempotency.

See `telegram-flows.md`.

## 2. Temporary input object state

Application-known temporary objects under `inputs/` are cleaned on explicit draft abandonment/replacement paths where the keys remain known.

Remaining infrastructure hardening gap:

- Redis TTL can orphan input objects after draft state disappears;
- current `main` therefore requires an external bucket lifecycle rule;
- automatic lifecycle bootstrap/verification remains tracked by open issue #50 and is **not** treated as merged production behavior.

Recommended rule is documented in `input-media-lifecycle.md`.

## 3. Durable generation state

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

Completed lifecycle behavior:

- central legal transition validation;
- provider processing visible through callback/poll convergence;
- provider success enters `result_ready` before archive;
- storage and Telegram delivery are separate durable stages;
- stage/failure metadata and timestamps persist;
- `succeeded` only follows confirmed delivery;
- stale `submitting` becomes `submission_unknown`, never another provider POST;
- owner-scoped status and safe pre-provider cancellation exist;
- cancellation releases reserved funds/suppresses pending submit work atomically;
- evidence-based `submission_unknown` resolution exists;
- provider-started work cannot be user-cancelled through the local endpoint.

## 4. Outbox state

```text
pending
retry_wait
processing
completed
dead_letter
failed   # legacy compatibility where present
```

Completed behavior:

- retryable vs terminal failures are classified;
- retry scheduling persists availability/attempt metadata;
- workers claim with row locks/`SKIP LOCKED`;
- retry budget exhaustion becomes observable dead-letter state;
- event-type semantics prevent unsafe retries at non-idempotent boundaries;
- failure/dead-letter reconciliation keeps generation/billing consistent where deterministically possible.

## 5. Media archive state

```text
pending
retry_wait
stored
failed
```

Completed behavior:

- one durable row per result URL;
- partial multi-file archive is represented explicitly;
- retries skip already stored assets;
- safe source/download/storage constraints are enforced;
- delivery starts only after all required assets are durable.

## 6. Telegram delivery state

```text
pending
retry_wait
sending
sent
delivery_unknown
failed
```

Completed behavior:

- retry is allowed only before the ambiguous send boundary;
- `sending` marks the non-idempotent Telegram boundary;
- transport ambiguity becomes `delivery_unknown`;
- no automatic resend from `delivery_unknown`;
- operator can mark sent, retry only after confirmed-not-sent evidence, or fail/refund;
- successful durable delivery drives generation success.

## 7. Billing reservation state

```text
reserved
captured
released
refunded
```

Completed behavior:

- reservation is atomic with paid admission;
- provider acceptance captures;
- ambiguous submission keeps reserved funds;
- deterministic pre-capture failure releases;
- terminal post-capture failure uses current refund policy;
- immutable ledger idempotency makes repeated settlement safe;
- reconciliation checks wallet/reservation/generation consistency.

## 8. Admin command state

Administrative writes use append-only command/audit records.

```text
reserved -> succeeded
         -> failed
```

The same admin/action/idempotency request replays the stored result. Reuse of the key with changed request content conflicts.

## 9. Support states

Ticket lifecycle follows the allowed service transitions around:

```text
open -> pending -> resolved -> closed
 ^                         |
 +---------- reopen -------+
```

Support reply side effects are durable:

```text
SupportMessage: queued -> sent/failed according to worker outcome
SupportOutbox: pending -> processing -> sent
                         |-> retry_wait -> processing
                         |-> dead_letter
```

HTTP/Telegram admin handlers do not rely on direct message send as their only committed effect.

## 10. Notification campaign states

Campaign:

```text
draft -> ready -> running -> completed
  |       |        |
  +-------+--------+-> cancelled
```

Delivery rows:

```text
pending -> processing -> sent
              |
              +-> retry_wait -> processing
              +-> failed/dead-letter according to current worker model
```

Starting a campaign materializes each recipient once under durable uniqueness constraints.

## 11. Payments and admin operations

Administrative payment processing stores explicit durable request/processing state. Payment credit is protected by deterministic ledger idempotency so repeated reprocess cannot double-credit.

Operation replay creates a child operation and is restricted to safe non-billable local work. Provider task submission is never an admin-replay target.

## 12. Versioned administrative content

### Tariffs

Published tariff payloads have immutable version history rather than mutable in-place commercial history.

### CMS

Documents own versions; published versions are retained rather than overwritten.

### Prompt moderation

Operational flow includes pending review, approval/rejection and deactivation of previously approved content according to shared service rules.

### Partner withdrawals

Durable transitions cover pending review through approval/payment or rejection. Actions are RBAC/audit/idempotency protected.

## Completed implementation sequence

Historical delivery epics:

1. #34 — Quick Start and inbound reference routing — completed.
2. #35 — Telegram FSM/recovery matrix — completed.
3. #36 — durable generation lifecycle — completed.
4. #37 — outbox/media/delivery/billing reconciliation — completed.
5. #9 — administrative control plane — completed through PR #54.

## Remaining known state/ops gap

At this documentation revision, the explicit known infrastructure state gap is issue #50: automatic/verified short-retention lifecycle configuration for abandoned `inputs/` objects. Until merged, operations must enforce that rule externally.

Other future product epics can introduce new model/product/payment/referral states. When they do, this file must be updated at the same time as domain transitions, database constraints and tests.

## Invariant for new states

A new durable/FSM/admin state is not complete until all applicable items exist:

- allowed incoming/outgoing transitions;
- timeout/lease/retry semantics;
- idempotency behavior;
- billing consequence;
- cancellation behavior;
- operator visibility/recovery;
- database constraint/migration where durable;
- tests;
- documentation.