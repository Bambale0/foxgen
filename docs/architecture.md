# HappyFox architecture

## 1. System purpose

HappyFox combines multiple delivery channels over one generation, billing and data core:

- Telegram bot;
- Telegram Mini App;
- Instagram Professional Creator/Business channel;
- provider/payment webhooks;
- internal/admin APIs.

The Python backend is the runtime authority. The Next.js Mini App is built as a static export.

## 2. Production topology

```text
Telegram updates ───────────────┐
Telegram Mini App HTTPS ────────┼──> HappyFox aiohttp/aiogram backend
Instagram webhook HTTPS ────────┤          │
Provider/payment webhooks ──────┘          ├─ PostgreSQL
                                           ├─ Redis
                                           ├─ provider adapters
                                           ├─ billing/ledger
                                           └─ media delivery

Public HappyFox origin: https://alena.chillcreative.ru
Mini App:               https://alena.chillcreative.ru/mini-app/
Compose project:        foxgen-happyfox
Container:              foxgen-happyfox-bot
Database:               happyfox
Redis prefix:           foxgen_happyfox
Production branch:      main
```

Exact server/IP details are runtime/deployment configuration, not product constants.

## 3. Channel adapter principle

Telegram and Instagram are adapters around the same domain. A channel may define UX, message formatting and acquisition mechanics, but must not fork pricing, provider lifecycle or the user ledger unnecessarily.

```text
Telegram adapter ───┐
                    ├─> identities/users -> generation -> provider -> result
Instagram adapter ──┘                     -> billing -> shared ledger
```

Instagram users have channel-neutral identities (`channel_identities`) and can later link to the same HappyFox user used by Telegram. No fake Telegram IDs are allowed.

## 4. Telegram surface

Telegram is the full-featured surface:

- `/start` and creator flows;
- Mini App bootstrap/auth;
- image/video/motion creation;
- references/history/feed/profile/remix;
- balance and configured payment providers;
- partner/support/admin contours.

Core modules include `bot/handlers/*`, `bot/miniapp.py`, `bot/database.py`, `bot/services/*`.

Telegram payments remain independent from Instagram presentation. CryptoBot may stay available in Telegram even though Instagram top-up handoff intentionally shows only YooKassa and Lava Top.

## 5. Instagram transport

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

## 6. Instagram identity, language and promotion

```text
bot/channel_identity.py     channel identity -> optional users.id
bot/channel_link.py         one-time hashed iglink tokens
bot/channel_promotions.py   first-photo entitlement
bot/instagram_i18n.py       persisted RU/EN language
```

The first successful Instagram photo can be free before Telegram account linking. The promotion is keyed by Instagram external identity, so relinking accounts cannot reset it.

Language is persisted per Instagram identity and resolved from meaningful RU/EN text. Attachment-first entry remains bilingual until a language is known.

## 7. Instagram creator orchestration

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

## 8. Durable job lifecycle

`bot/instagram_generation.py` persists Instagram creator jobs and session drafts.

Core safety properties:

1. durable job exists before charge/promotion side effect;
2. promotion reservation or paid charge is recoverable;
3. provider task ID is persisted after submit;
4. retries poll the same task instead of creating a second generation;
5. result URL is persisted before delivery retry;
6. delivery checkpoint prevents repeat media delivery during later local-finalization retries;
7. terminal paid failure refunds;
8. terminal free-photo failure releases the entitlement.

The same discipline should be applied to future channel adapters.

## 9. Billing architecture

The HappyFox ledger is shared.

Instagram top-up handoff:

```text
Instagram -> Telegram iglink -> YooKassa or Lava Top -> shared balance -> Direct Continue
```

Telegram's normal balance menu can expose other configured providers, including CryptoBot. Do not encode Instagram provider restrictions in the global payment backend.

## 10. Data layer

Production uses PostgreSQL. Redis is used for FSM/cache/locks/idempotency.

Important entities added/used by the Instagram contour:

- `channel_identities`;
- `channel_link_tokens`;
- `channel_promotions` / Instagram first-image promotion state;
- `instagram_channel_languages`;
- `instagram_generation_sessions`;
- `instagram_generation_jobs`;
- existing `users`, transactions and generation history.

New schemas support SQLite tests and PostgreSQL production, but production must remain PostgreSQL.

## 11. Mini App frontend

Directory: `frontend/miniapp-v0`.

Stack:

- Next.js 16;
- React 19;
- TypeScript;
- static export;
- Playwright browser validation.

The frontend is a Telegram product surface; Instagram creator interaction happens in Direct, not by embedding the Telegram Mini App UX into Instagram.

## 12. Internal/admin API

`bot/internal_api.py` registers protected internal routes and isolated external integrations. Internal routes use timestamped HMAC auth. Instagram routes are registered through the same aiohttp application but are authenticated using the Meta webhook contract, not internal HMAC.

## 13. Deployment architecture

`main` is production source of truth.

```text
PR head -> CI -> merge -> main CI -> deployment preflight -> exact-SHA deploy
```

CI gates backend regression/Ruff, Mini App lint/build, Chromium + iPhone WebKit journeys and production Docker image/runtime verification.

## 14. Dependency rule

Dependencies point inward:

```text
Meta/Telegram transport -> channel/application services -> shared domain/data/provider services
```

Do not make shared generation/billing code depend on Meta webhook payloads or Telegram update objects.

## 15. Source of truth when documents disagree

1. runtime code;
2. regression tests;
3. CI/deploy workflows;
4. `.env.happyfox.example` and `bot/config.py`;
5. canonical docs;
6. legacy/provider reference snapshots.
