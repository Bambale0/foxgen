# HappyFox — agent brief

Updated: 2026-08-31.

Repository: `Bambale0/foxgen`
Production source: `main`
Product: **HappyFox**

This file is a concise context brief for coding/review agents. Canonical human docs start at `README.md` and `docs/README.md`.

## Product boundary

HappyFox is independent from NEUROMIX/Tanya/`Bambale0/banano_kling` after the recorded core import.

Never reuse another product's:

- bot token;
- domains;
- PostgreSQL/Redis data plane;
- media storage;
- payment offers/credentials;
- provider webhook secrets;
- deploy environment.

Production identity:

```text
public origin: https://alena.chillcreative.ru
mini app:      https://alena.chillcreative.ru/mini-app/
compose:       foxgen-happyfox
container:     foxgen-happyfox-bot
database:      happyfox
redis prefix:  foxgen_happyfox
branch:        main
```

## Architecture

```text
Telegram Bot + Mini App ─┐
                         ├─> shared HappyFox generation/billing/data core
Instagram channel ───────┘
```

Channels are adapters. Do not duplicate ledger/provider lifecycle in Instagram.

Stack: Python 3.12, aiogram 3, aiohttp, PostgreSQL, Redis, Next.js 16/React 19, Playwright, Docker, GitHub Actions.

## Instagram transport

Main files:

```text
bot/instagram_api.py
bot/instagram_channel.py
bot/internal_api.py
bot/channel_identity.py
bot/channel_link.py
bot/channel_promotions.py
bot/instagram_i18n.py
bot/instagram_creator_generation.py
bot/instagram_seedream_generation.py
bot/instagram_video_generation.py
bot/instagram_generation.py
bot/handlers/instagram_account_link.py
```

Meta contract:

```text
Instagram API with Instagram Login
graph.instagram.com
default API: v24.0
webhook: /instagram/webhook
fields: messages,messaging_postbacks,comments
```

Permissions expected:

```text
instagram_business_basic
instagram_business_manage_messages
instagram_business_manage_comments
instagram_business_content_publish
```

Webhook POST must verify raw-body `X-Hub-Signature-256` HMAC-SHA256. Redis idempotency is required. Do not weaken fail-closed behavior.

Runtime is dark unless:

```dotenv
INSTAGRAM_ENABLED=1
```

Example/default stays `0` until live Meta config is ready.

## Instagram creator product contract

First step always:

```text
Photo / Фото
Video / Видео
```

### Photo

```text
model:       Seedream 5 Pro
product key: seedream_5_pro
provider:    seedream/5-pro-image-to-image
quality:     high
ratio:       1:1
paid cost:   2.5 🐾
```

Only first **successful Instagram photo** is free per Instagram external identity. Provider failure releases the reservation; relinking accounts cannot reset the gift.

Later photo: reference -> prompt -> paid confirm -> charge once -> durable job -> result. Terminal paid failure refunds once.

### Video

```text
model:       Seedance 2.5
product key: seedance_2_5
provider:    bytedance/seedance-2-5
resolution:  720p
ratio:       9:16
price:       shared HappyFox/Telegram Seedance pricing
```

Video is always paid.

```text
Video selected
 -> immediate top-up/paywall
 -> do NOT accept new reference yet
 -> user pays
 -> Continue / Продолжить
 -> verify linked balance
 -> ask photo/video reference
 -> prompt
 -> confirm price
 -> charge/provider/result
```

## Language

Instagram auto-detects/persists RU/EN per identity.

- Russian meaningful text -> `ru`;
- English meaningful text -> `en`;
- attachment-first -> bilingual chooser;
- `English` / `Русский` explicitly switch;
- all new Instagram user-facing copy should use `bot/instagram_i18n.py`.

## Identity/linking

Never fabricate Telegram IDs for Instagram users.

`channel_identities` maps channel/account/external user to optional HappyFox `users.id`.

Paid flow links through one-time hashed `iglink_*` token in Telegram. Linked identity shares the same HappyFox balance/history.

## Payments

One shared ledger.

Instagram handoff deliberately exposes only:

```text
YooKassa
Lava Top (card/SBP)
```

Telegram keeps its configured payment providers. **CryptoBot must remain in Telegram when enabled.** Do not globally delete it to satisfy Instagram UX.

After top-up user returns to Instagram and sends `Continue / Продолжить`; backend rechecks actual shared balance.

## Durable job rules

Instagram generation job safety:

- prepare job before financial/promotion side effect;
- persist provider task ID immediately after submit;
- retry/restart resumes same provider task;
- persist result URL before delivery retry;
- persist delivery checkpoint after successful send;
- terminal paid failure -> refund once;
- terminal free-photo failure -> release promotion;
- no free video.

Do not claim perfect exactly-once Meta delivery across remote-send/local-checkpoint crash ambiguity.

## Release process

```text
branch -> PR main -> exact-head CI green -> merge
       -> main CI green -> exact-SHA production deploy -> health/revision smoke
```

Required gates include backend regression/Ruff, Mini App build, Chromium+iPhone WebKit and production Docker runtime.

Do not claim deployed/live until exact SHA/deploy is verified. “Instagram code is on production” and “Instagram live is enabled” are different statements.

## Documentation sources

Canonical:

```text
README.md
docs/README.md
docs/instagram-channel.md
docs/architecture.md
docs/environment.md
docs/development-deployment.md
docs/production-deployment.md
FSM_USER_FLOWS.md
QA_AUDIT_CHECKLIST.md
tracemap_generation.md
tracemap_payments.md
```

Provider API snapshots and old NEUROMIX documents can be historical/reference-only. Runtime code/tests win on conflicts.
