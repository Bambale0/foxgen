# Architecture

## Boundaries

FoxGen uses explicit layers:

- `bot`: Telegram transport, navigation and FSM only;
- `api`: health, provider callbacks and future admin/API transport;
- `domain`: provider-independent capabilities and business state;
- `infra`: PostgreSQL and Redis integrations;
- `providers`: external API adapters and protocol validation.

Handlers must not construct KIE.ai payloads directly. They select a product capability, collect validated inputs and hand a draft to an application service.

## Reliability model

Every external generation uses a client-generated idempotency key stored before provider submission. The planned orchestration layer will reserve funds, persist an outbox event and submit the task asynchronously. Webhooks and polling converge on the same idempotent completion handler.

KIE callbacks may expose a task ID at the top level or inside `data`, using either `taskId` or `task_id`. The callback endpoint normalizes all supported shapes, verifies the HMAC and acknowledges accepted callbacks with HTTP 200 before durable asynchronous processing.

Provider retry policy is bounded:

- retry network timeouts, HTTP 429, KIE maintenance code 455 and transient 5xx;
- never retry invalid credentials, insufficient credits or validation failures without a state change;
- expose user-safe messages while preserving diagnostic details in structured logs.

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

## Data ownership

PostgreSQL owns users, generations, transactions, referrals, partner commissions, payments and audit events. Redis owns temporary sessions, locks, rate limits and queue transport. KIE.ai task IDs are unique and indexed to make callback processing idempotent.
