# HappyFox environment contract

Programmatic sources of truth are `bot/config.py`, channel settings classes and `.env.happyfox.example`.

## Rules

- Production secrets live outside Git.
- Never copy NEUROMIX/Tanya `.env` wholesale into HappyFox.
- Production uses PostgreSQL, not SQLite.
- Redis namespace/data plane must be isolated for HappyFox.
- Secret values must never appear in issues, docs or CI logs.
- `NEXT_PUBLIC_*` values are public bundle data and must not contain secrets.
- Changing runtime env normally requires an exact-SHA redeploy/restart.

## Canonical production skeleton

```dotenv
PRODUCT_ID=happyfox
BOT_TOKEN=
ADMIN_IDS=
SUPPORT_CONTACT=

WEBHOOK_HOST=https://api.happyfox.example
WEBHOOK_PATH=/webhook
WEBHOOK_BIND_HOST=127.0.0.1
WEBHOOK_PORT=1888
MINI_APP_URL=https://app.happyfox.example/mini-app/
STATIC_BASE_URL=https://media.happyfox.example

DATABASE_URL=postgresql://happyfox:change-me@127.0.0.1:5432/happyfox
REDIS_URL=redis://127.0.0.1:6379/3
REDIS_PREFIX=foxgen_happyfox

KIE_AI_API_KEY=
KIE_AI_WEBHOOK_PATH=/webhook/kie_ai
KIE_AI_WEBHOOK_SECRET=
INTERNAL_API_SECRET=
HEALTH_CHECK_SECRET=
```

Use `.env.happyfox.example` as the actual template.

## Telegram

`BOT_TOKEN` identifies the HappyFox Telegram bot and is also used for Telegram Web App authentication/signature logic.

`ADMIN_IDS` is a comma-separated allow-list for admin functionality.

Do not reuse one bot token in competing active runtimes.

## Public HTTP

Recommended:

```dotenv
WEBHOOK_HOST=https://<happyfox-backend-origin>
WEBHOOK_PATH=/webhook
WEBHOOK_BIND_HOST=127.0.0.1
WEBHOOK_PORT=1888
```

The aiohttp port should normally remain private behind Nginx/reverse proxy.

`MINI_APP_URL` is the public Telegram Mini App URL.

`STATIC_BASE_URL` is the public base used when generated/uploaded media must be reachable from external providers.

## Data plane

Production:

```dotenv
DATABASE_URL=postgresql://...
REDIS_URL=redis://...
REDIS_PREFIX=foxgen_happyfox
```

The production validator must reject SQLite and known shared/legacy Redis namespaces.

## Instagram

Instagram routes are fail-closed. Code may be deployed while the channel remains inactive.

Default:

```dotenv
INSTAGRAM_ENABLED=0
```

Live configuration:

```dotenv
INSTAGRAM_ENABLED=1
INSTAGRAM_APP_ID=
INSTAGRAM_APP_SECRET=
INSTAGRAM_VERIFY_TOKEN=
INSTAGRAM_ACCESS_TOKEN=
INSTAGRAM_IG_USER_ID=
INSTAGRAM_API_VERSION=v24.0
INSTAGRAM_WEBHOOK_PATH=/instagram/webhook
INSTAGRAM_REQUEST_TIMEOUT_SECONDS=30
INSTAGRAM_IDEMPOTENCY_TTL_SECONDS=604800
INSTAGRAM_SUBSCRIBED_FIELDS=messages,messaging_postbacks,comments
```

Meaning:

- `APP_ID` — Meta app identifier;
- `APP_SECRET` — used for webhook HMAC verification; secret;
- `VERIFY_TOKEN` — private value used for GET webhook verification;
- `ACCESS_TOKEN` — Instagram user access token; secret;
- `IG_USER_ID` — professional Instagram account ID;
- `API_VERSION` — Graph API version used by the client;
- `WEBHOOK_PATH` — public route registered in aiohttp/Nginx;
- `IDEMPOTENCY_TTL_SECONDS` — duplicate-event protection lifetime;
- `SUBSCRIBED_FIELDS` — fields used with `/{ig_user_id}/subscribed_apps`.

Do not set `INSTAGRAM_ENABLED=1` until public webhook, signature verification, permissions/access level and live subscription have been tested.

## Meta permissions

Current Instagram Login contour expects:

```text
instagram_business_basic
instagram_business_manage_messages
instagram_business_manage_comments
instagram_business_content_publish
```

These permissions are external Meta app configuration, not environment variables.

## Generation providers

KIE/provider secrets remain shared application infrastructure, not Instagram-specific credentials. Instagram Seedream 5 Pro and Seedance 2.5 use the same provider layer as HappyFox core.

Do not introduce a second Instagram-only KIE key unless isolation is an explicit operational requirement.

## Payments

HappyFox may contain several payment integrations. Availability is determined by runtime configuration and handler/service enablement.

### YooKassa

```dotenv
YOOKASSA_SHOP_ID=
YOOKASSA_SECRET_KEY=
YOOKASSA_RETURN_URL=https://app.happyfox.example/mini-app/
YOOKASSA_WEBHOOK_PATH=/yookassa/webhook
YOOKASSA_REQUEST_TIMEOUT_SECONDS=30
YOOKASSA_PENDING_TTL_HOURS=168
```

### Lava Top

```dotenv
LAVA_API_KEY=
LAVA_WEBHOOK_SECRET=
LAVA_OFFER_ID_MINI=
LAVA_OFFER_ID_START=
LAVA_OFFER_ID_OPTIMAL=
LAVA_OFFER_ID_PRO=
LAVA_OFFER_ID_STUDIO=
LAVA_OFFER_ID_BUSINESS=
```

HappyFox must use its own Lava offer IDs from environment, never imported Tanya/NEUROMIX offers.

### CryptoBot

```dotenv
CRYPTOBOT_API_TOKEN=
```

CryptoBot remains a valid Telegram payment integration. Instagram's account-link/top-up UI intentionally does **not** expose CryptoBot; that is a channel UX restriction, not removal of the Telegram provider.

### Telegram Stars

```dotenv
TELEGRAM_STARS_ENABLED=1
TELEGRAM_STARS_PER_RUB=1
TELEGRAM_STARS_FLAT_FEE=0
```

Again, Instagram handoff may intentionally hide Stars while Telegram keeps them enabled.

## Payment provider separation

Do not interpret `PAYMENT_PROVIDER` as permission to remove other working Telegram integrations. Some flows use a selected primary provider while other configured payment handlers coexist.

Instagram contract is specifically:

```text
YooKassa + Lava Top
```

Telegram contract is the configured Telegram payment menu, including CryptoBot when enabled.

## Frontend build env

Typical public variables include:

```dotenv
NEXT_PUBLIC_PRODUCT_ID=happyfox
NEXT_PUBLIC_MINIAPP_BASE_PATH=/mini-app
```

Anything beginning `NEXT_PUBLIC_` can be read by users.

## Validation

Before production deploy:

```bash
python scripts/validate_happyfox_env.py .env .env.happyfox.runtime .env.postgres
```

The preflight is expected to fail when product isolation or selected provider credentials are incomplete.

## Safe secret inventory

When diagnosing, print only whether keys are set, never values:

```bash
python3 - <<'PY'
from pathlib import Path
for line in Path('.env').read_text().splitlines():
    line = line.strip()
    if not line or line.startswith('#') or '=' not in line:
        continue
    key, value = line.split('=', 1)
    print(f'{key}: {"set" if value.strip() else "empty"}')
PY
```

## Instagram activation change control

Turning `INSTAGRAM_ENABLED` from `0` to `1` is a production channel activation. Record:

- exact deployed SHA;
- Meta app/account used;
- webhook verification result;
- subscribed fields;
- RU and EN live smoke;
- first-free-photo smoke;
- paid video top-up/resume smoke;
- rollback action (`INSTAGRAM_ENABLED=0` + redeploy/restart).
