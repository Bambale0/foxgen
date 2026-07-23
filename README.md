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

This first implementation PR provides:

- async FastAPI and aiogram application entry points;
- Redis-backed Telegram FSM with menu, cancel, back, edit and stale-callback fallbacks;
- PostgreSQL entities and Alembic baseline migration;
- typed KIE.ai Market API client with bounded retries and normalized errors;
- KIE webhook HMAC-SHA256 verification with replay-window protection;
- verified model registry and public model catalog endpoint;
- Docker Compose for API, bot, PostgreSQL, Redis and migrations;
- GitHub Actions CI for Ruff, formatting, mypy, pytest and Docker build.

Generation submission, billing and durable workers are deliberately split into subsequent reviewable PRs tracked by the epics.

## Architecture

```text
Telegram update
    -> aiogram router + Redis FSM
    -> application service
    -> PostgreSQL transaction/outbox
    -> worker queue
    -> typed KIE.ai adapter
    -> verified webhook or polling fallback
    -> durable result
    -> Telegram delivery
```

PostgreSQL stores durable business state. Redis is limited to ephemeral state, locks, cache and queues. Provider-specific payloads stay inside provider adapters; Telegram handlers work with product capabilities rather than raw model APIs.

See [architecture notes](docs/architecture.md) and the [model matrix](docs/model-matrix.md).

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
- `POST /webhooks/kie`

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

## Repository rules

Read [AGENTS.md](AGENTS.md) before making automated changes. KIE.ai model IDs and payload fields must be verified against official documentation and protected by contract tests.
