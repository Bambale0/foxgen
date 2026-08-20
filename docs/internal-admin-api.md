# Telegram Internal Admin API

Read-only API связывает Telegram-бот с `Bambale0/tanya_admin` без прямого доступа админки к PostgreSQL бота.

## Требования

- production-база Telegram-бота — PostgreSQL через `DATABASE_URL`;
- API работает в существующем `aiohttp` процессе на `WEBHOOK_BIND_HOST:WEBHOOK_PORT`;
- по умолчанию разрешён только loopback;
- все запросы подписываются HMAC-SHA256;
- маршруты нельзя публиковать через Nginx или Cloudflare.

## Маршруты

```text
GET /internal/admin/health
GET /internal/admin/summary
GET /internal/admin/users?limit=50&cursor=<opaque>
GET /internal/admin/generations?limit=50&cursor=<opaque>
GET /internal/admin/finance
```

Ответы используют:

```json
{
  "channel": "telegram",
  "api_version": "1",
  "service_version": "1.0.0"
}
```

`users` и `generations` сортируются по внутреннему `id DESC` и используют непрозрачный cursor. Максимальный `limit` — 100.

## Переменные окружения Telegram-бота

```env
DATABASE_URL=postgresql://USER:PASSWORD@127.0.0.1:5432/telegram_bot

INTERNAL_API_SECRET=REPLACE_WITH_64_HEX_CHARACTERS
INTERNAL_API_SERVICE_VERSION=1.0.0
INTERNAL_API_MAX_CLOCK_SKEW_SECONDS=60
INTERNAL_API_ALLOWED_NETWORKS=127.0.0.1/32,::1/128
```

Сгенерировать секрет:

```bash
openssl rand -hex 32
```

То же значение `INTERNAL_API_SECRET` должно быть установлено в `.env` проекта `tanya_admin`.

Когда сервисы находятся на разных серверах, соедините их приватной сетью/VPN и добавьте только нужную сеть, например:

```env
INTERNAL_API_ALLOWED_NETWORKS=10.20.0.0/24
```

Не добавляйте `0.0.0.0/0` или `::/0`.

## Настройка Tanya Admin

```env
INTERNAL_API_SECRET=THE_SAME_SECRET
TELEGRAM_INTERNAL_URL=http://127.0.0.1:8443/internal/admin
CHANNEL_REQUEST_TIMEOUT_SECONDS=5
```

Если Tanya Admin находится на другом сервере, используйте приватный адрес Telegram-сервера вместо `127.0.0.1`.

## HMAC

Каноническая строка:

```text
TIMESTAMP
HTTP_METHOD
FULL_REQUEST_PATH
SHA256_BODY
```

Для `GET` body hash считается от пустого byte string. `FULL_REQUEST_PATH` включает query string в фактическом порядке и encoding.

Заголовки:

```text
X-Internal-Timestamp: <unix timestamp>
X-Internal-Signature: <hex hmac sha256>
```

Допустимое расхождение времени по умолчанию — 60 секунд. На обоих серверах должен работать NTP.

## Локальная проверка

Обычный `curl` без подписи должен получить `401`:

```bash
curl -i http://127.0.0.1:8443/internal/admin/health
```

Подписанная проверка:

```bash
export INTERNAL_API_SECRET='THE_SAME_SECRET'
python3 - <<'PY'
import hashlib
import hmac
import os
import time
import urllib.request

path = "/internal/admin/health"
timestamp = str(int(time.time()))
body_hash = hashlib.sha256(b"").hexdigest()
canonical = "\n".join([timestamp, "GET", path, body_hash])
signature = hmac.new(
    os.environ["INTERNAL_API_SECRET"].encode(),
    canonical.encode(),
    hashlib.sha256,
).hexdigest()
request = urllib.request.Request(
    "http://127.0.0.1:8443" + path,
    headers={
        "X-Internal-Timestamp": timestamp,
        "X-Internal-Signature": signature,
    },
)
print(urllib.request.urlopen(request).read().decode())
PY
```

Ожидаемый ответ:

```json
{
  "status": "ok",
  "channel": "telegram",
  "api_version": "1",
  "service_version": "1.0.0"
}
```

`health` выполняет `SELECT 1`, поэтому одновременно проверяет доступность PostgreSQL.

## Данные

### summary

Возвращает агрегаты пользователей, текущих кредитов и генераций.

### users

Возвращает только административные поля: внутренний ID, Telegram ID, имя, username, баланс, факт оплаты, бан и даты. Реферальные реквизиты и иные чувствительные поля не выдаются.

### generations

Возвращает метаданные задачи и статус. Prompt, request payload и result URL намеренно не выдаются.

### finance

Локальный платёжный статус проходит переход `pending -> processing -> completed`. Выручка считается только по `completed` транзакциям.

## Nginx

Публичная конфигурация должна явно блокировать internal path до общего `location /`:

```nginx
location ^~ /internal/admin/ {
    return 404;
}
```

Для подключения через localhost Nginx не нужен: Tanya Admin обращается напрямую к `127.0.0.1:8443`.

## Перезапуск

После обновления кода и `.env`:

```bash
sudo systemctl restart banano-kling.service
sudo systemctl restart tanya-admin-api.service
```

Проверьте реальные имена unit-файлов:

```bash
systemctl list-units --type=service | grep -Ei 'banano|tanya|telegram'
```
