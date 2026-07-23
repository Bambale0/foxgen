# FoxGen

FoxGen is a Telegram-first multimodal AI generation platform built with Python 3.12, FastAPI, aiogram 3, PostgreSQL, Redis and KIE.ai.

The product is designed around a simple rule: a user should reach the target action in a few taps, always understand the next step and always have a safe way back.

## Product map

- Create video
- Create image
- Create voice
- Create music
- Motion Control and avatars
- Prompt AI
- AI assistant
- Balance and payment history
- Referrals
- Partners

## Current implementation

- async FastAPI and aiogram application entry points;
- Redis-backed Telegram FSM with menu, cancel, back, edit and stale-callback fallbacks;
- PostgreSQL entities and Alembic migrations;
- typed KIE.ai Market API client and normalized provider errors;
- KIE webhook HMAC-SHA256 verification with replay-window protection;
- versioned flagship model registry with exact provider IDs;
- strict contracts for Seedream 4.5, Seedream 5 Pro, Seedance 2, Seedance 2 Mini and Nano Banana 2/Pro;
- curated image, video and ElevenLabs Market model pack;
- JSON schemas, preflight validation and model-specific task submission endpoints;
- fail-closed internal authentication for paid provider submission;
- mandatory user identity and idempotency key for every paid request;
- persisted generation fingerprints and explicit lifecycle states;
- Redis request-rate limits and PostgreSQL active-generation limits;
- transactional PostgreSQL outbox for provider submission;
- durable, deduplicated KIE callback inbox;
- worker leasing with `FOR UPDATE SKIP LOCKED`, retry scheduling and dead-letter state;
- single-attempt KIE `createTask` submission with `submission_unknown` recovery state;
- local-generation callback correlation after a lost provider response;
- stale-`submitting` watchdog without automatic resubmission;
- polling fallback when a callback is delayed or missing;
- structured parsing of provider `resultJson` payloads;
- SSRF-resistant result downloading with byte and timeout limits;
- S3-compatible object storage with SHA-256 metadata and presigned delivery URLs;
- persisted media assets and Telegram delivery state;
- duplicate-safe Telegram delivery with explicit `delivery_unknown` state;
- local MinIO service and bucket bootstrap in Docker Compose;
- Docker Compose services for API, worker, bot, PostgreSQL, Redis, MinIO and migrations;
- GitHub Actions CI for Ruff, mypy, pytest and Docker build.

The remaining commercial release blocker is the atomic billing ledger in issue #7. Full image/video Telegram product FSMs and production hardening remain in issues #2, #5, #21 and #10.

## Current request path

```text
Trusted FoxGen service
    -> internal bearer authentication
    -> user identity + Idempotency-Key
    -> model registry + typed input contract
    -> Redis rate limit
    -> PostgreSQL transaction
         -> generation(status=queued)
         -> outbox(generation.submit)
    -> foxgen-worker claims outbox row
    -> one KIE createTask attempt
    -> submitted OR submission_unknown OR failed
    -> verified callback inbox OR polling fallback
    -> generation(status=succeeded)
    -> outbox(generation.archive)
    -> secure download + S3-compatible storage
    -> outbox(generation.deliver)
    -> presigned URL + Telegram delivery
```

The billable provider POST is never automatically replayed. The callback URL carries the local generation ID, allowing a later callback to recover an accepted task even when the original provider response was lost.

Telegram send is also treated as non-idempotent. Delivery work is consumed immediately before sending. A transport-ambiguous send becomes `delivery_unknown` instead of producing duplicate files in the user's chat.

See [architecture notes](docs/architecture.md). Provider-specific payloads stay inside provider adapters; Telegram handlers work with product capabilities rather than raw model APIs.

## Local start

```bash
cp .env.example .env
# Fill FOXGEN_TELEGRAM_BOT_TOKEN and FOXGEN_KIE_API_KEY

docker compose up --build
```

The local stack starts PostgreSQL, Redis and MinIO. The MinIO API is exposed on port `9000`; its console is exposed on `9001` for development only.

API endpoints:

- `GET /health/live`
- `GET /health/ready`
- `GET /v1/models`
- `GET /v1/models/{slug}`
- `POST /v1/models/{slug}/validate`
- `POST /v1/models/{slug}/tasks`
- `POST /webhooks/kie`

Example preflight validation:

```bash
curl -X POST http://localhost:8080/v1/models/seedance-2/validate \
  -H 'Content-Type: application/json' \
  -d '{"input":{"prompt":"A cinematic fox running through snow"}}'
```

Paid task creation is disabled by default. A trusted internal service must explicitly enable it and provide authentication:

```env
FOXGEN_TASK_SUBMISSION_ENABLED=true
FOXGEN_INTERNAL_API_TOKEN=<long-random-secret>
```

Example authenticated task request:

```bash
curl -X POST http://localhost:8080/v1/models/seedream-5-pro/tasks \
  -H 'Authorization: Bearer <internal-token>' \
  -H 'X-FoxGen-User-Id: 123456789' \
  -H 'Idempotency-Key: generation-123456789-0001' \
  -H 'Content-Type: application/json' \
  -d '{"input":{"prompt":"Premium product photo of a black watch"}}'
```

A successful admission returns a local generation in `queued` state. The worker performs the provider call asynchronously, archives the result and delivers stored media to the originating Telegram user.

Never expose the internal token or object-storage credentials to Telegram clients, browsers or mini apps. Keep paid admission disabled until issue #7 provides balance reservation and refund guarantees.

Local quality checks:

```bash
python -m pip install -e '.[dev]'
make ci
```

## Configuration

All settings use the `FOXGEN_` prefix. Secrets are read from environment variables and must never be committed. The `.env.example` file documents KIE, worker, media limits and S3-compatible storage settings.

For production callbacks set:

```env
FOXGEN_KIE_CALLBACK_BASE_URL=https://foxgen.example.com
FOXGEN_KIE_WEBHOOK_HMAC_KEY=...
```

For production storage, replace the local MinIO endpoint and development credentials with managed S3-compatible storage and keep the bucket private. Telegram receives temporary presigned URLs rather than provider URLs.

## Delivery plan

1. [Platform foundation, architecture and CI](../../issues/1)
2. [Telegram UX, navigation and complete FSM](../../issues/2)
3. [KIE.ai provider layer and model catalog](../../issues/3)
4. [Generation orchestration, queues and lifecycle](../../issues/4)
5. [Image, video, voice, music and motion-control products](../../issues/5)
6. [Prompt AI and conversational assistant](../../issues/6)
7. [Balance, pricing, payments and financial ledger](../../issues/7)
8. [Referrals, partners and growth mechanics](../../issues/8)
9. [Admin, moderation, support and analytics](../../issues/9)
10. [Reliability, security, observability and delivery](../../issues/10)
11. [Flagship KIE model pack](../../issues/12)
12. [Secure paid task submission](../../issues/17)
13. [Idempotent provider submission](../../issues/18)
14. [Durable generation lifecycle](../../issues/19)

## Repository rules

Read [AGENTS.md](AGENTS.md) before making automated changes. KIE.ai model IDs and payload fields must be verified against official documentation and protected by contract tests.
