# FoxGen architecture

This document describes the executable architecture on `main`. The public Mini App is outside the current implementation baseline.

## System boundaries

FoxGen is split into explicit transport, application, domain and infrastructure layers.

```text
Telegram bot                     Trusted backend callers
    |                                     |
    |                                     v
    |                                  FastAPI
    |                       ┌─────────────┼─────────────┐
    |                       |             |             |
    |                  paid task API   admin API    KIE callback
    |                       |             |             |
    └──────────────┬────────┴─────────────┴─────────────┘
                   v
             application/domain
          generation | billing | admin
                   |
        ┌──────────┼───────────┐
        v          v           v
   PostgreSQL    Redis      S3-compatible
   durable truth  FSM/locks   private media
        |
        v
   foxgen-worker
   ├─ provider submission/polling
   ├─ callback processing
   ├─ archive/delivery
   └─ admin/support/campaign jobs
```

Module responsibilities:

- `foxgen.bot` — Telegram transport, FSM, keyboards and orchestration;
- `foxgen.api` — FastAPI routes, authentication and transport validation;
- `foxgen.application` — generation admission/lifecycle/reconciliation use cases;
- `foxgen.admin` — shared administrative policy/services/workers;
- `foxgen.domain` — provider-independent business states and transition rules;
- `foxgen.infra` — PostgreSQL repositories/models, Redis, storage and durable queues;
- `foxgen.providers` — KIE adapters, contracts and webhook/status normalization.

Provider payload construction must not leak into Telegram handlers. Administrative write logic must not live only in Telegram/HTTP/web handlers.

## Durable data ownership

### PostgreSQL

PostgreSQL is authoritative for:

- users and block state;
- generations and lifecycle timestamps;
- provider callback inbox;
- transactional outbox;
- wallets, prices, reservations and immutable ledger entries;
- archived media metadata;
- Telegram delivery state;
- admin users, command ledger and audit events;
- payments/operations used by the admin contour;
- support tickets/messages/outbox;
- tariff and CMS versions;
- notification campaigns/deliveries;
- partner/promo/prompt/runtime/moderation admin data.

### Redis

Redis is ephemeral and non-authoritative for money/provider work. It owns:

- Telegram FSM state/data TTL;
- per-FSM-key event isolation;
- request rate counters;
- distributed locks/caches used by runtime services.

A Redis TTL expiry may discard a conversation draft, but it cannot erase a committed paid generation or wallet movement.

### S3-compatible storage

Private object storage owns media bytes:

- `inputs/` — temporary Telegram references;
- deterministic generation result keys — durable archived outputs.

PostgreSQL remains authoritative for durable result/media lifecycle. Provider source URLs are not forwarded to users.

## Paid task admission

Paid creation is fail-closed. Before queue admission FoxGen requires:

1. `FOXGEN_TASK_SUBMISSION_ENABLED=true`;
2. valid trusted internal bearer authentication;
3. a positive `X-FoxGen-User-Id`;
4. valid `Idempotency-Key`;
5. production-ready model contract;
6. runtime model availability not disabled by admin policy;
7. user not administratively blocked;
8. Redis rate limits satisfied;
9. PostgreSQL active-generation limits satisfied;
10. active model price;
11. sufficient wallet balance.

The admission transaction then atomically persists generation, reservation, immutable ledger movement and submission outbox. A request cannot become billable provider work without the matching local durable state.

## Atomic admission and billing

Conceptually:

```text
BEGIN
  ensure/update user
  reject blocked user
  enforce active-generation limits
  insert generation(status=queued, request_hash, idempotency_key)
  lock wallet
  resolve active price
  move available -> reserved
  insert balance_reservation(status=reserved)
  insert immutable ledger reserve entry
  insert outbox generation.submit
COMMIT
```

The unique `(user_id, idempotency_key)` generation key and ledger/outbox uniqueness converge duplicate confirmation requests onto one local billable generation.

## Billable provider submission boundary

KIE task creation is treated as a potentially non-idempotent billable POST. It is never blindly retried.

For `generation.submit` the worker:

1. claims the local event;
2. verifies the generation can legally submit;
3. moves generation to `submitting`;
4. consumes the submission outbox boundary so a crash cannot replay it;
5. performs one provider create call;
6. persists `submitted` + `provider_task_id`, deterministic failure, or `submission_unknown`.

`submission_unknown` means the provider may have accepted a billable request but the response was not safely recorded. Funds stay reserved until evidence resolves the ambiguity. The stale-submitting watchdog converts abandoned `submitting` work to `submission_unknown`; it does not submit again.

## Callback inbox and polling convergence

KIE callback requests are authenticated with the provider webhook HMAC and replay-age window. The callback path normalizes task identity, records a deduplicated provider event and schedules local processing.

Provider polling is read-only and may retry within bounded policies. Callback and polling share the same legal state transitions, so whichever produces verifiable state first wins without creating a second generation or provider charge.

The callback URL can include the local generation identifier so an accepted provider task can be correlated even if the create-task response was lost.

## Generation lifecycle

Current durable states:

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

Normal success path:

```text
queued
 -> submitting
 -> submitted
 -> processing
 -> result_ready
 -> storing_media
 -> delivery_pending
 -> succeeded
```

Important semantics:

- `submission_unknown` is a recovery state, never an automatic resubmit signal;
- provider success becomes `result_ready`, not user-visible success;
- `succeeded` means result storage and Telegram delivery have completed;
- cancellation is allowed only before provider submission may have started;
- state transition validation and database constraints reject unknown/illegal durable values.

## Outbox and retry model

General outbox states:

```text
pending -> processing -> completed
   |          |
   |          +-> retry_wait -> processing
   +-------------------------> dead_letter
```

`failed` remains a legacy compatibility value where present. Retry scheduling applies only to operations whose side effects are safe to retry. Exhausted/terminal work records a failure class and enters observable dead-letter state.

`FOR UPDATE SKIP LOCKED` allows multiple workers to claim independent rows without duplicate ownership. Leases allow safe local work to be reclaimed after worker failure.

## Result archive

A successful provider result advances to `result_ready`, then archive work:

1. parses normalized result URLs;
2. validates HTTPS/source constraints;
3. rejects credential-bearing/private/reserved SSRF targets and unsafe redirects;
4. enforces download timeout and byte limits;
5. calculates SHA-256 while writing temporary bytes;
6. stores under deterministic private S3 key;
7. persists per-result `media_assets` state;
8. creates one delivery only after all required assets are durable.

Media asset states:

```text
pending
retry_wait
stored
failed
```

Multi-file results can partially succeed. Retry skips already stored assets and resumes only incomplete ones.

## Telegram delivery boundary

Telegram send becomes a non-idempotent external side effect once sending begins.

Delivery states:

```text
pending
retry_wait
sending
sent
delivery_unknown
failed
```

`retry_wait` is only safe before the send boundary. A timeout/transport ambiguity after sending begins becomes `delivery_unknown`; FoxGen does not automatically resend. An administrator can later mark it sent, retry only after confirming no message was delivered, or terminate/refund according to reconciliation policy.

## Billing settlement

Reservation states:

```text
reserved
captured
released
refunded
```

Current rules:

- provider accepted (`submitted`) -> capture reserved funds;
- `submission_unknown` -> keep funds reserved;
- deterministic failure before capture -> release;
- terminal failure after capture -> full refund under current policy;
- repeated settlement attempts converge via row locks + deterministic ledger idempotency.

See `billing.md`.

## Telegram FSM architecture

Redis FSM controls only the interactive draft. Every declared state has an explicit behavior contract for success/back/cancel/timeout/invalid input/stale callback. Event isolation serializes concurrent updates for one key.

Quick Start and unsolicited photo/video reference entry store private object keys before asking whether the user wants image or video output. Reference-prefilled navigation preserves the stored reference across model/settings edits.

Paid work becomes durable only at confirmation/admission. Telegram FSM is not used as the source of truth after a generation is committed.

See `telegram-flows.md`.

## Administrative control plane

FoxGen has a shared admin domain layer:

```text
Telegram /admin ─────┐
                     ├─> AdminPolicy -> AdminServices -> PostgreSQL/ledger/outboxes
Signed admin HTTP ───┤
                     └─> backend-only operator web surface
                                      |
                                      v
                                  AdminWorker
```

Key invariants:

- all transports use server-side `AdminPolicy`;
- each privileged callback/FSM/HTTP action re-authorizes;
- writes use append-only command/audit records;
- same idempotency key + same request replays the stored result;
- key reuse with changed request conflicts;
- destructive/expensive operations require manual confirmation;
- signed HTTP is network allowlisted and HMACs exact raw body bytes;
- support replies/campaign sends are durable worker work;
- secrets are recursively redacted from admin output;
- runtime user block/model availability are enforced at paid admission.

The internal operator web surface is backend-only. It is not the public Mini App.

See `admin-control-plane.md` and `admin-capability-matrix.md`.

## Security boundaries

Secrets are intentionally separated:

- internal generation bearer token;
- KIE API key;
- KIE webhook HMAC secret;
- legacy billing-admin token if enabled;
- full admin HMAC secret;
- database/Redis/storage credentials.

No trusted secret belongs in Telegram client state or public frontend code. Public reverse proxies must deny `/internal/admin/` entirely; backend callers use the private network path.

## Production topology

`docker-compose.prod.yml` runs:

- PostgreSQL;
- Redis;
- MinIO/private storage service where used;
- migration job;
- API;
- worker;
- bot.

The API host port is loopback-only for the reverse proxy. PostgreSQL, Redis and MinIO are not published on host public interfaces.

Production deployment is exact-SHA after successful `main` CI. The server-side `.env` is preserved and tracked local modifications block deployment.

## Consistency and reconciliation

Reconciliation inspects cross-resource invariants among generation, outbox, media, delivery and reservation state. Automated fixes are limited to deterministic local state repairs. It never performs another billable provider submission and never blindly resends `delivery_unknown`.

See `postprocessing-reconciliation.md`.

## Source-of-truth hierarchy

When resolving drift:

1. migrations + database constraints for schema/history;
2. domain/application transition code for legal business state;
3. tests for explicit expected behavior;
4. transport adapters for API/FSM presentation;
5. documentation.

A discovered mismatch is a documentation/code defect to fix, not permission to silently reinterpret production state.