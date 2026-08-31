# HappyFox

HappyFox — самостоятельный AI-продукт в `Bambale0/foxgen`: Telegram Bot + Telegram Mini App + Instagram Creator/Business channel поверх общего generation/billing core.

## Product boundary

С 20 августа 2026 `foxgen` использует проверенное production-ядро, перенесённое из `Bambale0/banano_kling`, но после точки переноса HappyFox является отдельным продуктом и не должен использовать NEUROMIX/Tanya credentials, domains, databases, Redis namespace, media storage или deploy infrastructure.

Источник переноса: [`MIGRATION_SOURCE.md`](MIGRATION_SOURCE.md). Legacy FoxGen сохранён только как reference history в `legacy/foxgen-pre-tanyapi-20260820`.

## Каналы

```text
                    HappyFox core
                         │
        ┌────────────────┴────────────────┐
        │                                 │
Telegram Bot + Mini App             Instagram channel
        │                                 │
full product UI                   creator acquisition/DM
        │                                 │
        └──────── generation + billing ───┘
```

Telegram остаётся полным продуктовым интерфейсом. Instagram — отдельный adapter для acquisition, Direct и comment-driven creator flow; он не дублирует provider или billing core.

### Instagram contract

- первый шаг всегда `Фото / Photo` или `Видео / Video`;
- фото: **Seedream 5 Pro**, provider `seedream/5-pro-image-to-image`, quality `high`, 1:1;
- первая **успешная фото-генерация** для Instagram identity бесплатна;
- следующие фото оплачиваются по обычному HappyFox pricing; текущий Instagram photo contract — **2.5 🐾**;
- видео: **Seedance 2.5**, provider `bytedance/seedance-2-5`, 720p, 9:16;
- видео всегда платное: при выборе `Видео / Video` сначала показывается top-up offer, media reference до готового баланса не принимается;
- Instagram top-up handoff показывает только **YooKassa** и **Lava Top**; Lava поддерживает card/SBP;
- Telegram сохраняет собственные текущие способы оплаты, включая **CryptoBot**;
- после оплаты пользователь возвращается в Direct и пишет `Продолжить / Continue`;
- RU/EN определяется автоматически по первому осмысленному тексту и хранится для Instagram identity; `English`/`Русский` переключают язык явно.

Полная спецификация: [`docs/instagram-channel.md`](docs/instagram-channel.md).

## Архитектура

```text
Telegram Updates ───────┐
Telegram Mini App ──────┼─> Python/aiogram/aiohttp core
Instagram Webhooks ─────┘       ├─ generation lifecycle
                                ├─ provider adapters
                                ├─ billing/ledger
                                ├─ PostgreSQL
                                ├─ Redis FSM/cache/idempotency
                                ├─ media delivery
                                └─ internal/admin API

Next.js 16 / React 19 Mini App -> static export -> HappyFox public origin
```

Ключевые Instagram modules:

```text
bot/instagram_api.py                 Meta transport, HMAC, normalization, client
bot/channel_identity.py              channel-neutral identity mapping
bot/channel_link.py                  one-time Telegram account link
bot/channel_promotions.py            first-photo entitlement
bot/instagram_i18n.py                RU/EN detection + persisted language
bot/instagram_creator_generation.py  Photo/Video orchestrator
bot/instagram_seedream_generation.py Seedream 5 Pro flow
bot/instagram_video_generation.py    Seedance 2.5 flow
bot/instagram_generation.py          durable jobs/worker/checkpoints
bot/handlers/instagram_account_link.py Telegram top-up handoff
```

## Production identity

```text
Product ID:       happyfox
Public origin:    https://alena.chillcreative.ru
Mini App:         https://alena.chillcreative.ru/mini-app/
Compose project:  foxgen-happyfox
Container:        foxgen-happyfox-bot
Database:         happyfox
Redis namespace:  foxgen_happyfox
Production branch: main
```

`main` — единственный production source of truth. Production deployment always uses exact tested SHA through `.github/workflows/deploy-production.yml`.

## Instagram live status

Instagram code is part of the production source, but the channel is fail-closed and is registered only when:

```dotenv
INSTAGRAM_ENABLED=1
```

Before enabling live runtime, configure Meta Instagram Login credentials, webhook verification/signature handling and subscriptions. Default/example configuration keeps `INSTAGRAM_ENABLED=0`.

## Meta integration contract

Primary setup: **Instagram API with Instagram Login** on `graph.instagram.com`, for Professional Creator/Business accounts. Required permissions for the implemented contour:

```text
instagram_business_basic
instagram_business_manage_messages
instagram_business_manage_comments
instagram_business_content_publish
```

Current runtime default API version is `v24.0`; webhook subscription fields are `messages,messaging_postbacks,comments`.

## Stack

- Python 3.12, aiogram 3, aiohttp;
- PostgreSQL production data plane;
- Redis FSM/cache/idempotency;
- Next.js 16, React 19, TypeScript;
- Playwright Chromium + iPhone WebKit gates;
- Docker Compose + Nginx;
- GitHub Actions CI/CD.

## Pricing and ledger

User-facing unit is **🐾**. Pricing source is `data/price.json` + pricing helpers/services. Do not hardcode Telegram or video prices in channel adapters when the same price exists in the shared pricing core.

Instagram-specific fixed model contract is in `bot/instagram_model_contract.py`:

- Seedream 5 Pro High: 2.5 🐾 paid price;
- Seedance 2.5: cost resolved from shared Telegram/HappyFox video pricing for duration/quality.

## Local verification

Backend:

```bash
python -m pip install -r requirements.txt
python scripts/apply_visible_copy_fixes.py
python scripts/apply_happyfox_product_copy.py
python -m compileall -q bot scripts
pytest tests/ --ignore=tests/live -m 'not live_smoke'
```

Mini App:

```bash
cd frontend/miniapp-v0
npm ci
npm audit --omit=dev --audit-level=high
npm run lint
npm run build
```

Instagram regression subset:

```bash
pytest -q \
  tests/test_instagram_transport.py \
  tests/test_instagram_channel.py \
  tests/test_instagram_creator_flow.py \
  tests/test_instagram_generation.py \
  tests/test_instagram_model_contract.py \
  tests/test_instagram_i18n.py \
  tests/test_instagram_account_link.py \
  tests/test_instagram_account_link_router.py
```

## Release path

```text
feature/fix/docs branch
  -> PR to main
  -> CI green
  -> merge
  -> CI green on exact main SHA
  -> isolated HappyFox preflight
  -> exact-SHA deploy
  -> health/revision smoke
```

Never deploy arbitrary working-tree state and never deploy HappyFox through `banano_kling` infrastructure.

## Documentation

Start with [`docs/README.md`](docs/README.md). Key documents:

- [`docs/instagram-channel.md`](docs/instagram-channel.md) — Instagram product/FSM/Meta/live activation;
- [`docs/architecture.md`](docs/architecture.md) — current channel-neutral architecture;
- [`docs/environment.md`](docs/environment.md) — env contract;
- [`docs/development-deployment.md`](docs/development-deployment.md) — development/release flow;
- [`docs/production-deployment.md`](docs/production-deployment.md) — production deploy/runbook;
- [`FSM_USER_FLOWS.md`](FSM_USER_FLOWS.md) — user state machines;
- [`QA_AUDIT_CHECKLIST.md`](QA_AUDIT_CHECKLIST.md) — release QA contract;
- [`docs/happyfox-handoff.md`](docs/happyfox-handoff.md) — production boundary and handoff evidence.
