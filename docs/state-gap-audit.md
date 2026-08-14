# FoxGen state-machine audit

This document began as a gap analysis. It is now a completion/status record for the state machines implemented through the Telegram FSM, durable generation lifecycle, post-processing reconciliation and administrative control plane.

## 1. Telegram conversation state

Declared generation states:

```text
image_selecting_model
image_uploading_references
image_configuring
image_waiting_prompt
video_selecting_model
video_selecting_type
video_uploading_media
video_configuring
video_waiting_prompt
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
- `/start` and `/menu` are registered ahead of every state-specific router and always interrupt the active FSM before returning to the canonical entrypoint;
- ordinary image/video creation uses separate screen-level FSM branches rather than one generic mode chain;
- model-specific screens and settings are capability-driven and cover every production-enabled KIE submission slug;
- one UI model may resolve to different validated provider contracts, e.g. Seedream text/edit based on reference presence;
- Quick Start reference ingestion converges into the same image/video screen wizard without copying the temporary file;
- compatible prefilled references survive video type/model navigation; incompatible replacements are cleaned before transition;
- legacy generic/reference states remain declared only for deployed Redis-draft migration compatibility and are routed after the new wizard;
- known active drafts survive unrelated stale callbacks/messages;
- expired/unknown state recovers fail-closed;
- Redis event isolation serializes concurrent updates for one FSM key;
- Telegram albums are rejected before download;
- transfer/storage failures do not advance FSM;
- live price/balance confirmation precedes paid admission;
- duplicate paid confirmation converges through durable idempotency.

See `telegram-flows.md`.

## 2. Temporary input object state

Application-known temporary objects under `inputs/` are cleaned on explicit draft abandonment/replacement paths where the keys remain known.

Infrastructure orphan cleanup is also enforced for repository Compose deployments:

- Redis TTL/crash abandonment may still orphan keys after conversational state disappears;
- `minio-init` creates the bundled private bucket when necessary and installs the FoxGen-managed `inputs/` lifecycle rule;
- unrelated bucket lifecycle rules are preserved;
- the lifecycle configuration is read back and must match exactly before startup succeeds;
- API, worker and bot are gated on successful `minio-init` completion;
- the short rule never targets durable `generations/` results;
- deployments that replace bundled MinIO with external S3-compatible storage must provision the private bucket and provide equivalent lifecycle enforcement through infrastructure.

Application request/worker code intentionally has no bucket-creation toggle. Storage provisioning is explicit rather than opportunistic.

See `input-media-lifecycle.md` and `minio-lifecycle-runbook.md`.

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

Recovery/terminal branches include `submission_unknown`, `failed` and `cancelled`.

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

## 13. Admin transport reachability

The shared admin domain layer and intended transports are registered.

FastAPI runtime includes:

```text
create_admin_router(...)
create_admin_extensions_router(...)
create_admin_web_extensions_router(...)
create_admin_web_router(...)
```

The operator-web extension router deliberately precedes the generic base web router so `/analytics` and `/admins` cannot be shadowed by `GET /api/{section}`.

Telegram runtime order is:

```text
foxgen-global-commands
foxgen-admin-extras
foxgen-admin
foxgen-quick-start-wizard
foxgen-generation-wizard
foxgen-quick-start
foxgen-generation
foxgen-shell
```

The global command router is deliberately first so `/start` and `/menu` cannot be consumed by an active FSM's broad text/media handler. The Quick Start bridge and new screen wizard precede legacy generation routers so new drafts cannot be swallowed by generic handlers, while older deployed Redis drafts remain recoverable. Admin extension callbacks still run before product/shell fallbacks and perform fresh signed Admin API authorization.

Route enumeration plus enabled/disabled HTTP tests and Telegram callback tests protect this reachability contract.

See `api-reference.md`, `admin-capability-matrix.md` and `telegram-flows.md`.

## Completed implementation sequence

Historical delivery epics/tasks:

1. #34 — Quick Start and inbound reference routing — completed.
2. #35 — Telegram FSM/recovery matrix — completed.
3. #36 — durable generation lifecycle — completed.
4. #37 — outbox/media/delivery/billing reconciliation — completed.
5. #9 — administrative domain/control-plane core — completed through PR #54.
6. #50 — temporary input lifecycle automation — Compose MinIO bootstrap/verification and startup gating completed.
7. #55 — admin extension transport wiring — signed HTTP/operator-web extension routers and Telegram extras registered with reachability/security regression coverage.
8. #57 — storage provisioning contract — removed the unused `FOXGEN_S3_CREATE_BUCKET` setting; application storage never provisions buckets, Compose provisions bundled MinIO, external S3 is infrastructure-owned.

## Remaining known state/ops gaps

No known durable-state, admin-transport or ambiguous storage-provisioning gap remains from the state-gap program above.

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
- actual transport wiring where user/operator reachable;
- tests;
- documentation.
