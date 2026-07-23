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
- Redis-backed Telegram image/video FSM with explicit expiry, back, cancel, edit and stale-callback recovery;
- text-to-image, image editing, text-to-video, image-to-video and multimodal reference-to-video flows;
- model-aware options for Seedream 5 Pro, Nano Banana 2/Pro and Seedance 2/Mini;
- private S3-compatible storage for Telegram inputs with fresh presigned URLs at submission time;
- price and available-balance confirmation before the launch button is enabled;
- stable draft idempotency keys and duplicate-click protection;
- PostgreSQL entities and Alembic migrations;
- typed KIE.ai Market API client and normalized provider errors;
- KIE webhook HMAC-SHA256 verification with replay-window protection;
- versioned flagship model registry with exact provider IDs;
- strict contracts for Seedream 5 Pro, Seedance 2, Seedance 2 Mini and Nano Banana 2/Pro;
- curated image, video and ElevenLabs Market model pack;
- JSON schemas, preflight validation and model-specific task submission endpoints;
- fail-closed internal authentication for paid provider submission;
- mandatory user identity and idempotency key for every paid request;
- atomic pricing lookup and balance reservation before queue admission;
- immutable append-only balance ledger with reserve, capture, release and refund transitions;
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

Payment-provider webhooks, the remaining media products, exact contracts for the wider model catalog and production hardening remain tracked in issues #7, #5, #20, #21 and #10.

## Telegram image/video path

```text
User chooses image or video
    -> generation mode
    -> compatible model
    -> prompt
    -> required Telegram references
    -> model-specific options
    -> current price + available balance
    -> one confirmation
    -> authenticated internal API request
    -> atomic reserve + generation + outbox commit
```

The bot never contacts KIE or PostgreSQL directly. Telegram input files are stored privately by object key. A temporary provider-readable URL is generated only when the user confirms the draft.

## Durable generation path

```text
Trusted FoxGen service
    -> internal bearer authentication
    -> user identity + Idempotency-Key
    -> model registry + typed input contract
    -> Redis rate limit
    -> PostgreSQL transaction
         -> active price
         -> balance reservation + immutable ledger entry
         -> generation(status=queued)
         -> outbox(generation.submit)
    -> foxgen-worker claims outbox row
    -> one KIE createTask attempt
    -> submitted OR submission_unknown OR failed
    -> capture OR retained reserve OR release
    -> verified callback inbox OR polling fallback
    -> success OR failure/refund
    -> secure download + S3-compatible storage
    -> Telegram delivery
```

The billable provider POST is never automatically replayed. The callback URL carries the local generation ID, allowing a later callback to recover an accepted task even when the original provider response was lost.

Telegram send is also treated as non-idempotent. Delivery work is consumed immediately before sending. A transport-ambiguous send becomes `delivery_unknown` instead of producing duplicate files in the user's chat.

See [architecture notes](docs/architecture.md). Provider-specific payloads stay inside provider adapters; Telegram handlers work with product capabilities rather than raw model APIs.

## Local start

```bash
cp .env.example .env
# Fill Telegram, KIE, internal API and local storage settings.

docker compose up --build
```

The local stack starts PostgreSQL, Redis and MinIO. The MinIO API is exposed on port `9000`; its console is exposed on `9001` for development only.

Paid submissions remain fail-closed until all of these are intentionally configured:

```env
FOXGEN_TASK_SUBMISSION_ENABLED=true
FOXGEN_INTERNAL_API_TOKEN=<long-random-secret>
FOXGEN_KIE_API_KEY=<provider-key>
```

Publish active model prices and fund a test wallet through the separately protected billing-admin API before trying the Telegram launch flow.

API endpoints include:

- `GET /health/live`
- `GET /health/ready`
- `GET /v1/models`
- `GET /v1/models/{slug}`
- `POST /v1/models/{slug}/validate`
- `POST /v1/models/{slug}/tasks`
- `GET /v1/prices`
- `GET /v1/users/{user_id}/balance`
- `GET /v1/users/{user_id}/ledger`
- `POST /v1/admin/users/{user_id}/balance-adjustments`
- `PUT /v1/admin/prices/{model_slug}`
- `POST /webhooks/kie`

Example preflight validation:

```bash
curl -X POST http://localhost:8080/v1/models/seedance-2/validate \
  -H 'Content-Type: application/json' \
  -d '{"input":{"prompt":"A cinematic fox running through snow"}}'
```

A successful admission returns a local generation in `queued` state. The worker performs the provider call asynchronously, settles the reservation, archives the result and delivers stored media to the originating Telegram user.

Never expose internal API tokens, billing-admin credentials or object-storage credentials to Telegram clients, browsers or mini apps.

Local quality checks:

```bash
python -m pip install -e '.[dev]'
make ci
```

## Configuration

All settings use the `FOXGEN_` prefix. Secrets are read from environment variables and must never be committed. The `.env.example` file documents Telegram FSM expiry, internal API access, billing administration, KIE, worker, media limits and S3-compatible storage settings.

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
