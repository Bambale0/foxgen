# HappyFox architecture

## 1. System purpose

HappyFox combines multiple delivery channels over one generation and infrastructure core:

- Telegram bot;
- Telegram Mini App;
- MAX bot;
- Instagram Professional Creator/Business channel;
- provider/payment webhooks;
- internal/admin APIs.

The Python backend is the runtime authority. The Next.js Mini App is built as a static export.

## 2. Production topology

```text
Telegram updates ───────────────┐
Telegram Mini App HTTPS ────────┤
MAX webhook HTTPS ──────────────┼──> HappyFox aiohttp/aiogram backend
Instagram webhook HTTPS ────────┤          │
Provider/payment webhooks ──────┘          ├─ PostgreSQL 17
                                           ├─ Redis
                                           ├─ durable static media storage
                                           ├─ provider adapters
                                           └─ billing ledgers

Public HappyFox origin: https://alena.xn--e1aikcel5c5a.online
Mini App:               https://alena.xn--e1aikcel5c5a.online/mini-app/
MAX webhook:            https://alena.xn--e1aikcel5c5a.online/max/webhook
Compose project:        foxgen-happyfox
Container:              foxgen-happyfox-bot
Database:               happyfox
Redis prefix:           foxgen_happyfox
Production branch:      main
```

Exact server/IP details are runtime/deployment configuration, not product constants.

## 3. Channel adapter principle

Telegram, MAX and Instagram are adapters around shared provider/infrastructure capabilities. A channel may define UX, message formatting, acquisition mechanics and an intentionally isolated ledger, but must not duplicate provider lifecycle or security primitives unnecessarily.

```text
Telegram adapter ───┐
MAX adapter ─────────┼─> generation/provider services -> durable result
Instagram adapter ──┘
```

Instagram users have channel-neutral identities (`channel_identities`) and can later link to the same HappyFox user used by Telegram. No fake Telegram IDs are allowed.

MAX identities are native MAX `user_id` values. MAX administrators are database-backed and must never be inferred from display names. MAX currently keeps its own balance/order tables rather than pretending a MAX account is a Telegram user.

## 4. Telegram surface

Telegram is the full-featured surface:

- `/start` and creator flows;
- Mini App bootstrap/auth;
- image/video/motion creation;
- references/history/feed/profile/remix;
- balance and configured payment providers;
- partner/support/admin contours.

Core modules include `bot/handlers/*`, `bot/miniapp.py`, `bot/database.py`, `bot/services/*`.

Telegram payments remain independent from Instagram presentation and from the MAX balance ledger.

## 5. MAX surface

MAX runtime composition lives in `bot/max_runtime.py` and uses the official MAX Bot API through `bot/max_api.py`.

Safety properties:

- Webhook secret is mandatory when `MAX_ENABLED=1`;
- events are claimed idempotently before processing;
- YooKassa orders are stored in the MAX payment ledger;
- payment reconciliation verifies remote provider state;
- admin roles are stored in `max_admins` and can be claimed through one-time hashed invite tokens;
- `MAX_BOT_NAME` is required in production so referral/payment deep links cannot silently degrade.

MAX generation workers are durable channel workers and must not create fake Telegram users.

## 6. Instagram transport

`bot/instagram_api.py` owns external Meta transport:

- settings/env parsing;
- GET webhook verification;
- raw-body HMAC-SHA256 validation;
- message/postback/comment normalization;
- echo detection;
- Redis idempotency;
- text/media/private-reply Send API calls;
- webhook subscriptions;
- publishing container/status/publish primitives.

Runtime registration occurs in `bot/internal_api.py` only when `INSTAGRAM_ENABLED=1`.

Primary Meta host is `graph.instagram.com`; default API version is `v24.0`.

## 7. Instagram identity, language and promotion

```text
bot/channel_identity.py     channel identity -> optional users.id
bot/channel_link.py         one-time hashed iglink tokens
bot/channel_promotions.py   first-photo entitlement
bot/instagram_i18n.py       persisted RU/EN language
```

The first successful Instagram photo can be free before Telegram account linking. The promotion is keyed by Instagram external identity, so relinking accounts cannot reset it.

Language is persisted per Instagram identity and resolved from meaningful RU/EN text. Attachment-first entry remains bilingual until a language is known.

## 8. Instagram creator orchestration

`bot/instagram_creator_generation.py` is the top-level creator orchestrator.

### Photo

```text
Photo -> Seedream 5 Pro High -> durable job -> image Direct delivery
```

Contract source: `bot/instagram_model_contract.py`.

```text
product_key: seedream_5_pro
provider:    seedream/5-pro-image-to-image
quality:     high
ratio:       1:1
paid cost:   2.5 🐾
```

Photo lifecycle lives in `bot/instagram_seedream_generation.py` + shared durable worker infrastructure.

### Video

```text
Video -> paywall/top-up -> Continue -> reference -> prompt
      -> Seedance 2.5 -> durable job -> video Direct delivery
```

```text
product_key: seedance_2_5
provider:    bytedance/seedance-2-5
resolution:  720p
ratio:       9:16
price:       shared HappyFox/Telegram pricing
```

Video is always paid. `video:awaiting_topup` must not accept a new media reference.

## 9. Durable job and media lifecycle

A provider URL is not durable storage. Production requires `PERSIST_PROVIDER_RESULTS=1` and a public HTTPS `STATIC_BASE_URL`.

For completed Telegram/provider results:

```text
provider result -> download -> static/uploads hash path -> public HappyFox URL
                                               -> generation_tasks.result_url(s)
```

`scripts/backfill_provider_results.py` migrates legacy completed jobs whose database rows still reference provider-hosted temporary URLs. It is dry-run by default and updates rows only after every selected URL was persisted successfully.

Durable worker safety properties should include:

1. durable job exists before charge/promotion side effect;
2. charge/reservation is recoverable;
3. provider task ID is persisted after submit;
4. retries poll the same task instead of creating a second generation;
5. result is persisted before history relies on it;
6. delivery checkpoint prevents duplicate delivery;
7. terminal paid failure refunds;
8. retry/reconciliation is idempotent.

## 10. Billing architecture

Telegram uses the shared HappyFox user ledger. Payment completion is atomic and idempotent.

YooKassa success is not trusted from the incoming webhook alone: the backend fetches the payment from YooKassa and verifies the local provider, payment/order identity, amount and RUB currency before completion.

MAX intentionally uses its own MAX order/balance tables while reusing configured YooKassa merchant credentials.

Instagram top-up handoff:

```text
Instagram -> Telegram iglink -> configured payment provider -> shared Telegram balance -> Direct Continue
```

## 11. Data layer and migrations

Production uses PostgreSQL 17. Redis is used for FSM/cache/locks/idempotency.

`schema_postgres.sql` remains the clean-install baseline. Incremental production changes are applied by the ordered registry in `bot/schema_migrations.py` and recorded in `schema_migrations`.

Migration rules:

- versions are ordered and immutable;
- startup fails closed on an unknown migration version or changed migration identity;
- migrations are committed only after successful application;
- compatibility `ensure_*_schema()` helpers may remain temporarily for SQLite tests/legacy modules, but new production schema changes belong in the migration registry;
- payment provider identities are unique by `(provider, payment_id)` for non-empty payment IDs.

Important entities include:

- `users`, `transactions`, `generation_tasks`;
- channel identity/link/promotion tables;
- MAX users/admins/payments/generation tables;
- Instagram language/session/job tables;
- internal admin command/operation/payment/support/notification ledgers.

## 12. Backups

The backend schedules PostgreSQL backup every three hours and deploys take a pre-deploy backup.

Production image ships PostgreSQL 17 `pg_dump`/`pg_restore`, matching the PostgreSQL server major. `scripts/backup_db.sh` creates a custom-format temporary dump and validates it with `pg_restore --list` before rotating `postgres-latest.dump`.

A zero-byte or unreadable temporary dump is a failed backup and must never replace the previous verified backup.

## 13. Mini App frontend

Directory: `frontend/miniapp-v0`.

Stack:

- Next.js 16;
- React 19;
- TypeScript;
- static export;
- Jest contract/unit tests;
- Playwright Chromium and WebKit journeys.

Telegram Mini App authorization is server-validated using Telegram initData HMAC. Browser Telegram Login is independently verified before a signed browser initData session is issued.

## 14. Internal/admin API

`bot/internal_api.py` registers protected internal routes and isolated external integrations. Internal admin operations use timestamped HMAC authentication, network allowlists, idempotency keys and command ledgers. The production reverse proxy does not expose `/internal/admin/*` publicly.

Instagram and MAX routes are authenticated with their channel-specific webhook contracts rather than internal HMAC.

## 15. Public HTTP trust boundary

Production backend is bound through Docker to loopback and nginx is the trusted public reverse proxy.

Nginx overwrites `X-Real-IP` with `$remote_addr`. Application rate limiting therefore trusts `X-Real-IP` before `X-Forwarded-For`; client-provided XFF must not create a new limiter bucket.

## 16. Deployment and dependency architecture

`main` is production source of truth.

```text
PR head -> CI -> merge -> main CI -> deployment preflight -> exact-SHA deploy
```

CI gates:

- locked Python dependency installation + `pip check`;
- Python dependency vulnerability audit;
- backend regression and Ruff delta;
- Mini App npm audit, lint and Jest tests;
- production build;
- Chromium + iPhone WebKit journeys;
- production Docker image/runtime verification;
- PostgreSQL 17 client verification.

Python runtime versions are pinned in `requirements.lock`; `requirements.txt` remains the human-maintained dependency intent file.

## 17. Dependency rule

Dependencies point inward:

```text
Meta/Telegram/MAX transport -> channel/application services -> shared domain/data/provider services
```

New code should be extracted into focused modules rather than extending already-large composition/handler/database modules. Do not make shared generation/billing code depend on Meta webhook payloads, MAX update envelopes or Telegram update objects.

## 18. Source of truth when documents disagree

1. runtime code;
2. regression tests;
3. CI/deploy workflows;
4. `.env.happyfox.example` and `bot/config.py`;
5. canonical docs;
6. legacy/provider reference snapshots.
