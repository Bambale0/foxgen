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
- persisted generation fingerprints, statuses and provider task IDs;
- Redis user/global rate limits and PostgreSQL active-generation limits;
- single-attempt KIE `createTask` submission with `submission_unknown` recovery state;
- Docker Compose for API, bot, PostgreSQL, Redis and migrations;
- GitHub Actions CI for Ruff, mypy, pytest and Docker build.

The full outbox/worker lifecycle, callback persistence, storage, Telegram result delivery and billing ledger remain under active implementation in issues #19 and #7.

## Current request path

```text
Trusted FoxGen service
    -> internal bearer authentication
    -> user identity + Idempotency-Key
    -> model registry + typed input contract
    -> Redis rate limit
    -> PostgreSQL generation admission
    -> one KIE createTask attempt
    -> submitted OR submission_unknown OR failed
```

The target asynchronous path is documented in [architecture notes](docs/architecture.md). Provider-specific payloads stay inside provider adapters; Telegram handlers work with product capabilities rather than raw model APIs.

## Local start

```bash
cp .env.example .env
# Fill FOXGEN_TELEGRAM_BOT_TOKEN and FOXGEN_KIE_API_KEY

docker compose up --build
```

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

Never expose the internal token to Telegram clients, browsers or mini apps. Keep submission disabled until pricing, balance reservation and the durable worker path are configured.

Local quality checks:

```bash
python -m pip install -e '.[dev]'
make ci
```

## Configuration

All settings use the `FOXGEN_` prefix. Secrets are read from environment variables and must never be committed. The `.env.example` file documents the required configuration.

For production callbacks set:

```env
FOXGEN_KIE_CALLBACK_BASE_URL=https://foxgen.example.com
FOXGEN_KIE_WEBHOOK_HMAC_KEY=...
```

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
