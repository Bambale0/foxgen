# Переменные окружения NEUROMIX

Документ описывает группы env-переменных ветки `tanyapi`. Полный программный источник истины — `bot/config.py`.

## 1. Общие правила

- production `.env` хранится вне Git;
- права файла — `600`, владелец — пользователь systemd service или root;
- перед изменением создаётся backup;
- секреты нельзя печатать в issue, документацию, CI logs и shell screenshots;
- пустое значение не всегда равно выключенной функции: проверять код и feature flags;
- после изменения runtime-переменной обычно требуется restart `banano-kling.service`;
- frontend static build использует только переменные, начинающиеся с `NEXT_PUBLIC_`, и встраивает их на этапе сборки.

## 2. Рекомендуемый production skeleton

```dotenv
# Telegram
BOT_TOKEN=REPLACE_ME

# Public backend
WEBHOOK_HOST=https://tanyapi.chillcreative.ru
WEBHOOK_PATH=/webhook
WEBHOOK_BIND_HOST=127.0.0.1
WEBHOOK_PORT=1888

# Mini App
MINI_APP_PATH=/mini-app
MINI_APP_URL=https://cdn.chillcreative.ru/mini-app/
STATIC_BASE_URL=https://media.chillcreative.ru

# Storage
DATABASE_URL=REPLACE_ME
REDIS_URL=redis://127.0.0.1:6379/0
REDIS_PREFIX=neuromix

# Security
INTERNAL_API_SECRET=REPLACE_ME
HEALTH_CHECK_SECRET=REPLACE_ME

# Providers and payments
KIE_AI_API_KEY=REPLACE_ME
PAYMENT_PROVIDER=REPLACE_ME

# Admin
ADMIN_IDS=123456789
```

Это шаблон, а не готовый `.env`: конкретный набор providers/payments зависит от включённого production-функционала.

## 3. Telegram

### `BOT_TOKEN`

Токен Telegram-бота. Обязателен для webhook, initData validation и Telegram API.

Никогда не использовать один token одновременно в двух активных production runtimes без понимания webhook/polling conflict.

### `ADMIN_IDS`

Список Telegram ID через запятую:

```dotenv
ADMIN_IDS=123456789,987654321
```

Пробелы допустимы только если parser их обрабатывает; безопаснее писать без пробелов.

## 4. Backend HTTP и webhook

### `WEBHOOK_HOST`

Публичная база backend:

```dotenv
WEBHOOK_HOST=https://tanyapi.chillcreative.ru
```

Без trailing slash.

### `WEBHOOK_PATH`

Telegram webhook path:

```dotenv
WEBHOOK_PATH=/webhook
```

Должен совпадать с Nginx route и установленным webhook Telegram.

### `WEBHOOK_BIND_HOST`

Рекомендуемое production-значение:

```dotenv
WEBHOOK_BIND_HOST=127.0.0.1
```

Frontend обращается к backend через `https://tanyapi.chillcreative.ru`, поэтому открывать aiohttp наружу не требуется.

### `WEBHOOK_PORT`

Локальный порт aiohttp:

```dotenv
WEBHOOK_PORT=1888
```

Если значение меняется, обновить backend Nginx upstream и health commands.

## 5. Mini App

### `MINI_APP_PATH`

Base path API/static fallback:

```dotenv
MINI_APP_PATH=/mini-app
```

Frontend export также собирается с `/mini-app` basePath.

### `MINI_APP_URL`

Публичный URL, который открывает Telegram:

```dotenv
MINI_APP_URL=https://cdn.chillcreative.ru/mini-app/
```

Trailing slash рекомендуется сохранить.

### `STATIC_BASE_URL`

Публичная база сохранённых uploads:

```dotenv
STATIC_BASE_URL=https://media.chillcreative.ru
```

Backend формирует URLs вида:

```text
https://media.chillcreative.ru/uploads/...
```

Не добавлять `/uploads` в значение, если код уже добавляет этот segment.

### `PERSIST_PROVIDER_RESULTS`

Включает сохранение provider result в локальное storage там, где поддерживается. Перед включением проверить disk capacity и cleanup policy.

## 6. Database

### `DATABASE_URL`

Формат зависит от выбранного backend.

SQLite example:

```dotenv
DATABASE_URL=sqlite:///bot.db
```

PostgreSQL example:

```dotenv
DATABASE_URL=postgresql://USER:PASSWORD@127.0.0.1:5432/DBNAME
```

Не копировать примерные credentials. Перед переключением использовать migration/verification scripts и документацию PostgreSQL.

## 7. Redis

### `REDIS_URL`

```dotenv
REDIS_URL=redis://127.0.0.1:6379/0
```

При недоступности Redis runtime может использовать in-memory fallback. Это ухудшает устойчивость FSM к restart.

### `REDIS_PREFIX`

Namespace keys:

```dotenv
REDIS_PREFIX=neuromix
```

При совместном Redis нескольких окружений использовать разные prefixes.

## 8. Security

### `INTERNAL_API_SECRET`

Секрет внутренних API. Должен быть длинным случайным значением.

### `HEALTH_CHECK_SECRET`

Если установлен, health route может требовать bearer token. Мониторинг нужно обновить одновременно.

### Provider webhook secrets

Возможные группы:

- `KIE_AI_WEBHOOK_SECRET`;
- `KIE_WEBHOOK_HMAC_KEY`;
- `REPLICATE_WEBHOOK_SECRET`;
- `LAVA_WEBHOOK_SECRET`;
- другие secrets, присутствующие в `bot/config.py`.

Наличие переменной не подтверждает включённый provider. Проверять route registration и active config.

## 9. Providers

Часто используемые ключи:

- `KIE_AI_API_KEY`;
- `KLING_API_KEY`;
- `PIAPI_API_KEY`;
- `GEMINI_API_KEY`;
- `NANOBANANA_API_KEY`;
- `FREEPIK_API_KEY`;
- `NOVITA_API_KEY`;
- `REPLICATE_API_TOKEN`;
- Nano Banana fallback keys/base URLs.

Правила:

- один ключ — одна строка без кавычек, если shell syntax их не требует;
- после ротации проверить и direct request, и webhook completion;
- не логировать request headers;
- fallback provider должен быть явно проверен, а не считаться рабочим из-за заполненной переменной.

## 10. Payments

### `PAYMENT_PROVIDER`

Выбирает активный основной provider там, где это предусмотрено кодом.

Возможные группы конфигурации:

- CryptoBot: `CRYPTOBOT_*`;
- Lava: `LAVA_*`;
- Telegram Stars: `TELEGRAM_STARS_*`;
- FreeKassa: `FREEKASSA_*`;
- T-Bank legacy: `TBANK_*`.

В репозитории могут оставаться legacy integrations. Не включать provider только потому, что переменные существуют.

## 11. Partner programme

- `PARTNER_OFFER_URL`;
- `PARTNER_RULES_URL`;
- `PARTNER_MIN_WITHDRAWAL_RUB`.

Изменение minimum withdrawal должно быть согласовано с UI и business rules.

## 12. Logging

Возможные runtime flags:

```dotenv
BANANO_DISABLE_FILE_LOGGING=0
BANANO_LOG_TO_STDOUT=1
```

Технический prefix `BANANO_*` legacy и не является пользовательским брендом.

## 13. Frontend build variables

Frontend может использовать:

- `NEXT_EXPORT=1` — выставляется build script автоматически;
- `NEXT_PUBLIC_MINIAPP_BASE_PATH=/mini-app`;
- runtime/public bot username variables, если они поддерживаются `lib/api.ts`.

`NEXT_PUBLIC_*` не должны содержать secrets: они попадают в клиентский bundle.

## 14. Cloudflare deploy variables

Для `scripts/deploy_media_origin.sh`:

```text
DOMAIN=media.chillcreative.ru
ZONE_NAME=chillcreative.ru
ORIGIN_IPV4=144.76.188.75
PROJECT_DIR=/root/tanya/banano_kling
UPLOADS_DIR=/root/tanya/banano_kling/static/uploads
APP_SERVICE=banano-kling.service
CF_API_TOKEN_FILE=/root/.secrets/cloudflare-media.token
BACKFILL_WEBP=1
RUN_RENEWAL_DRY_RUN=1
```

Обычно они передаются окружением запуска и не обязаны находиться в application `.env`.

## 15. Безопасное изменение `.env`

```bash
cd /root/tanya/banano_kling

BACKUP="/root/backups/neuromix/env-$(date +%Y%m%d-%H%M%S)"
install -d -m 700 /root/backups/neuromix
cp -a .env "$BACKUP"
chmod 600 "$BACKUP"

nano .env

sudo systemctl restart banano-kling.service
sudo systemctl is-active banano-kling.service
curl -fsS http://127.0.0.1:1888/health
journalctl -u banano-kling.service -n 100 --no-pager
```

## 16. Проверка без раскрытия секретов

Показывать только имена заполненных переменных:

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

Никогда не отправлять полный вывод `.env` в чат или issue.
