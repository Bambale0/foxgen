# Architecture

## Boundaries

FoxGen uses explicit layers:

- `bot`: Telegram transport, navigation and FSM only;
- `api`: health, authenticated internal admission and provider callbacks;
- `application`: idempotent use cases, lifecycle and delivery orchestration;
- `domain`: provider-independent capabilities and business state;
- `infra`: PostgreSQL, Redis, S3-compatible storage and Telegram integrations;
- `providers`: external generation API adapters and protocol validation.

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

The internal token is intended for trusted FoxGen services such as the Telegram bot. It must not be shipped to Telegram clients, web browsers or mini apps.

## Transactional admission and outbox

The API never calls KIE directly. Admission is one PostgreSQL transaction:

```text
BEGIN
  insert user when missing
  insert generation(status=queued, idempotency_key, request_hash)
  insert outbox event(type=generation.submit, unique deduplication_key)
COMMIT
```

If the transaction fails, neither the generation nor provider work becomes visible. If the API process exits after commit, the outbox row remains claimable by a worker.

Workers claim rows with `FOR UPDATE SKIP LOCKED`. A processing lease allows another worker to reclaim ordinary non-billable work after a crash. Attempts, availability time, worker identity and the final dead-letter state are persisted.

## Billable POST boundary

KIE `createTask` is a non-idempotent, billable POST. FoxGen never retries it automatically.

For a `generation.submit` event, the worker performs this sequence:

1. verify that the generation is still `queued`;
2. atomically move it to `submitting`;
3. mark the submission outbox event completed;
4. call KIE exactly once;
5. store `submitted` and `provider_task_id`, or store `submission_unknown`/`failed`.

Completing the outbox event before the provider call is intentional. A process crash after step 3 cannot replay the billable POST. A watchdog moves stale `submitting` records to `submission_unknown` without resubmitting them.

The per-generation callback URL contains `generation_id`. If KIE accepted the task but the create response was lost, a later callback can still correlate the provider task with the local generation and complete it safely.

Read-only provider status requests may use bounded retries. Invalid credentials, insufficient credits and validation failures are never retried without a state change.

## Callback inbox and polling convergence

KIE callbacks may expose a task ID at the top level or inside `data`, using either `taskId` or `task_id`. The API:

1. normalizes the task ID;
2. verifies HMAC and replay age;
3. validates and stores the local generation identity from the callback URL;
4. hashes the normalized payload;
5. inserts a unique `provider_events` inbox row;
6. inserts a `kie.callback` outbox event in the same transaction;
7. returns HTTP 200.

Duplicate callback payloads are harmless because `event_hash` and the callback outbox deduplication key are unique.

The worker resolves the generation through the local generation ID first and `provider_task_id` second, normalizes terminal provider states and parses string `resultJson` into structured JSON. Submitted generations also receive a scheduled polling fallback. Callback and polling paths use the same legal terminal transitions, so whichever arrives first wins without duplicating completion.

## Media archive

A successful terminal transition inserts a unique `generation.archive` outbox event in the same transaction.

The archive worker:

1. extracts HTTPS result URLs from the normalized payload;
2. rejects credentials in URLs, non-HTTPS schemes, private/reserved DNS targets and redirects;
3. enforces response timeout, declared-size and streamed byte limits;
4. writes the response to a temporary file while calculating SHA-256;
5. stores it under a deterministic S3-compatible key;
6. inserts an idempotent `media_assets` record;
7. creates one delivery and `generation.deliver` outbox event.

Deterministic object keys and unique `(generation_id, source_url)` rows make archive retries safe. Provider URLs are never forwarded directly to users.

Local development uses MinIO. Production should use a private managed S3-compatible bucket. Telegram receives short-lived presigned `GetObject` URLs.

## Telegram delivery boundary

Telegram send operations are not idempotent. FoxGen prepares all presigned URLs first, then atomically moves delivery from `pending` to `sending` and completes the delivery outbox event before calling Telegram.

A successful call stores Telegram message IDs and marks the delivery `sent`. A timeout or transport-ambiguous failure becomes `delivery_unknown`; it is not automatically replayed, avoiding duplicate files in the chat. Operators can inspect and explicitly reconcile unknown deliveries later.

## Generation states

The persisted lifecycle defines:

- `draft`;
- `queued`;
- `submitting`;
- `submitted`;
- `submission_unknown`;
- `succeeded`;
- `failed`;
- `cancelled`.

A database check constraint prevents unknown states. Terminal transitions set `completed_at`; submitted tasks receive `next_poll_at`.

## Delivery states

- `pending` — stored assets are ready;
- `sending` — the non-idempotent Telegram boundary has started;
- `sent` — Telegram message IDs were stored;
- `delivery_unknown` — Telegram may have accepted the send, so automatic replay is forbidden;
- `failed` — a deterministic terminal failure requiring support action.

## Outbox states

- `pending` — eligible after `available_at`;
- `processing` — leased by a worker;
- `completed` — handled successfully or deliberately consumed;
- `failed` — retry budget exhausted and requires inspection.

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

Production admission requires:

```env
FOXGEN_TASK_SUBMISSION_ENABLED=true
FOXGEN_INTERNAL_API_TOKEN=<long-random-secret>
FOXGEN_KIE_API_KEY=<provider-key>
FOXGEN_TELEGRAM_BOT_TOKEN=<bot-token>
FOXGEN_S3_BUCKET=<private-bucket>
```

Worker tuning is controlled with `FOXGEN_WORKER_*`, `FOXGEN_PROVIDER_POLL_INTERVAL_SECONDS`, media limits and S3 settings.

Do not enable paid admission until pricing and atomic balance reservation are configured under issue #7.

## Data ownership

PostgreSQL owns users, generations, outbox events, provider events, media assets, deliveries, future transactions, referrals, partner commissions, payments and audit events. Redis owns temporary sessions, request-rate counters, locks and caches. S3-compatible storage owns durable media bytes. PostgreSQL remains the source of truth for lifecycle, archive and delivery idempotency.
