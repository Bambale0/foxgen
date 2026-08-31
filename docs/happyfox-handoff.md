# HappyFox production handoff

Status: HappyFox is an independently deployed product in `Bambale0/foxgen` with production source of truth `main`.

## Product boundary

The production core was imported from `Bambale0/banano_kling` at the recorded migration point, but HappyFox is operationally independent after that point.

Do not reuse NEUROMIX/Tanya credentials, domains, PostgreSQL data, Redis namespace, media storage, payment offers or deployment infrastructure.

Legacy FoxGen remains reference-only history under `legacy/foxgen-pre-tanyapi-20260820`.

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

Configuration contract: `.env.happyfox.example`.

Isolation gate:

```bash
python scripts/validate_happyfox_env.py .env .env.happyfox.runtime .env.postgres
```

## Release contract

```text
feature branch
 -> PR to main
 -> exact-head CI green
 -> merge
 -> exact-main CI green
 -> isolated HappyFox preflight
 -> exact-SHA deploy
 -> health/revision smoke
```

The historical `dev -> tanyapi` process belongs to the source repository history and is not a HappyFox release path.

## Current channel architecture

HappyFox now has two product delivery contours over one core:

```text
Telegram Bot + Mini App -> full product surface
Instagram -> creator acquisition/Direct/comments adapter
```

Instagram does not create a separate provider stack or balance ledger.

## Instagram delivered contract

Implemented in `main`:

- Meta Instagram Login transport and signed webhook verification;
- message/postback/comment normalization and idempotency;
- channel-neutral Instagram identity mapping;
- secure one-time Telegram account linking;
- first successful Instagram **photo** free entitlement;
- Photo -> Seedream 5 Pro High (`seedream/5-pro-image-to-image`), paid follow-ups 2.5 🐾;
- Video -> Seedance 2.5 (`bytedance/seedance-2-5`), always paid;
- video selection enters top-up flow before reference upload;
- Instagram top-up handoff exposes YooKassa and Lava Top only;
- Telegram retains its configured payment providers including CryptoBot;
- `Продолжить / Continue` resumes paid flow after balance verification;
- RU/EN automatic language detection and persisted per-Instagram-identity language;
- durable provider task/result/delivery checkpoints and refund/promotion recovery.

Canonical specification: `docs/instagram-channel.md`.

## Instagram runtime status

Instagram code can be deployed as part of HappyFox while remaining inactive. Runtime route/worker registration is gated by:

```dotenv
INSTAGRAM_ENABLED=1
```

The repository example remains fail-closed with `INSTAGRAM_ENABLED=0` until Meta credentials, permissions/access and live webhook validation are ready.

Do not report Instagram as live merely because its code is present in the production image.

## CI acceptance

The release gate for HappyFox includes:

- backend runtime compile;
- HappyFox product normalization;
- Ruff delta checks;
- safe regression suite including Instagram tests;
- Mini App dependency audit/lint/static export;
- Chromium critical journeys;
- Telegram startup on Chromium and iPhone WebKit;
- production Docker exact-source image and runtime verification.

For channel activation additionally run live Meta webhook/Direct smoke described in `instagram-channel.md`.

## Billing boundary

HappyFox has one shared ledger. Channel UX chooses how payment is presented.

```text
Instagram: YooKassa + Lava Top
Telegram: configured Telegram payment providers, CryptoBot included when enabled
```

Do not remove or globally disable a Telegram provider because it is intentionally hidden in Instagram.

## Operations and rollback

General production runbook: `docs/production-deployment.md`.

Cutover/Instagram activation: `docs/happyfox-production-cutover.md`.

Instagram-only containment:

```dotenv
INSTAGRAM_ENABLED=0
```

then redeploy/restart the verified HappyFox version.

General rollback must target a previously verified `foxgen` SHA and compatible HappyFox data backup, never a NEUROMIX runtime/database.

## Documentation rule

Future changes to models, Instagram pricing/free entitlement, language behavior, Meta fields/permissions, payment handoff or release process must update the canonical docs/FSM/QA/tracemaps in the same PR.
