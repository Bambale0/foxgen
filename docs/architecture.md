# Architecture

## Boundaries

FoxGen uses explicit layers:

- `bot`: Telegram transport, navigation and FSM only;
- `api`: health, authenticated internal submission and provider callbacks;
- `application`: idempotent use cases coordinating persistence and providers;
- `domain`: provider-independent capabilities and business state;
- `infra`: PostgreSQL and Redis integrations;
- `providers`: external API adapters and protocol validation.

Handlers must not construct KIE.ai payloads directly. They select a product capability, collect validated inputs and hand a draft to an application service.

## Paid submission security

Provider task creation is fail-closed:

1. `FOXGEN_TASK_SUBMISSION_ENABLED` must be explicitly enabled;
2. the caller must present the configured internal bearer token;
3. `X-FoxGen-User-Id` identifies the owning user;
4. every request must carry an `Idempotency-Key`;
5. Redis enforces user/global request-rate limits;
6. PostgreSQL enforces one generation per `(user_id, idempotency_key)`;
7. active-generation limits are checked before admission;
8. catalog-only passthrough models cannot create paid tasks.

The internal token is intended for trusted FoxGen services such as the Telegram bot and worker. It must not be shipped to Telegram clients, web browsers or mini apps.

## Reliability model

Every external generation uses a client-generated idempotency key stored before provider submission. Reusing the key with the same request returns the original generation. Reusing it with different content returns an idempotency conflict.

KIE `createTask` is submitted exactly once by the synchronous foundation path. A timeout or retryable provider response after submission is ambiguous and moves the local generation to `submission_unknown`; FoxGen does not automatically repeat the billable POST. The next orchestration PR moves submission behind a transactional outbox and worker while preserving the same rule.

Read-only provider status requests may use bounded retries. Invalid credentials, insufficient credits and validation failures are never retried without a state change.

KIE callbacks may expose a task ID at the top level or inside `data`, using either `taskId` or `task_id`. The callback endpoint normalizes all supported shapes, verifies the HMAC and acknowledges accepted callbacks with HTTP 200. Durable callback processing, polling convergence and result delivery are tracked by issue #19.

## Generation states

The persisted lifecycle currently defines:

- `draft`;
- `queued`;
- `submitting`;
- `submitted`;
- `submission_unknown`;
- `succeeded`;
- `failed`;
- `cancelled`.

A database check constraint prevents unknown states. Full transition policy and terminal-result processing are implemented under issue #19.

## FSM rules

Every flow must support:

1. valid transition;
2. invalid input with an actionable hint;
3. back;
4. cancel;
5. restart/menu;
6. stale callback recovery;
7. duplicate click protection;
8. timeout/expired draft recovery.

Redis stores active FSM state. Durable drafts that affect money or provider submission must be copied to PostgreSQL before confirmation. User-provided text is escaped before HTML rendering in Telegram.

## Configuration

Optional empty values from `.env` are ignored. This keeps the documented `cp .env.example .env` flow valid while still requiring non-empty secrets when a feature is enabled.

Production submission requires both:

```env
FOXGEN_TASK_SUBMISSION_ENABLED=true
FOXGEN_INTERNAL_API_TOKEN=<long-random-secret>
```

Do not enable the switch until pricing, balance reservation and the durable worker path are configured.

## Data ownership

PostgreSQL owns users, generations, transactions, referrals, partner commissions, payments and audit events. Redis owns temporary sessions, locks, rate limits and queue transport. KIE.ai task IDs are unique and indexed to make callback processing idempotent.
