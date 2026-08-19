# Internal Admin Payments and Tariffs API

API предназначено только для `Bambale0/tanya_admin` и работает внутри существующего `aiohttp` процесса Telegram-бота.

## Платежи

```text
GET  /internal/admin/payments
GET  /internal/admin/payments/{payment_id}
POST /internal/admin/payments/{payment_id}/recheck
POST /internal/admin/payments/{payment_id}/reprocess
```

Список поддерживает:

```text
query
status
provider
user_id
limit
cursor
```

### Recheck

```json
{
  "reason": "support requested provider verification",
  "comment": "ticket 901",
  "confirmation": "RECHECK 123"
}
```

`recheck` только повторно запрашивает состояние у платёжного провайдера. Баланс пользователя и локальный статус транзакции не меняются.

### Reprocess

```json
{
  "reason": "recover payment after webhook outage",
  "comment": "ticket 902",
  "confirmation": "REPROCESS 123"
}
```

`reprocess`:

1. повторно запрашивает состояние у провайдера;
2. не принимает webhook payload из административного запроса;
3. при подтверждённой оплате вызывает существующий атомарный payment completion;
4. повтор для уже завершённой транзакции не начисляет кредиты второй раз;
5. при подтверждённом отказе переводит только `pending/processing` в `failed`;
6. сохраняет стабильный результат по `Idempotency-Key`.

Telegram Stars нельзя реконструировать без исходного Telegram `successful_payment` update. Для завершённых Stars-транзакций повтор безопасно возвращает `already_completed`; незавершённые требуют расследования по Telegram update/logs.

## Платёжные события

`internal_admin_payment_events` — append-only ledger. PostgreSQL trigger фиксирует:

- создание транзакции;
- смену локального статуса;
- изменение внешнего payment ID.

Административные проверки и reprocess добавляют отдельные события с actor ID, request ID и idempotency key. Сырые ответы провайдеров, токены и webhook payload в API не возвращаются.

## Тарифы

```text
GET  /internal/admin/tariffs
GET  /internal/admin/tariffs/versions
GET  /internal/admin/tariffs/versions/{version_id}
POST /internal/admin/tariffs/publish
```

Канонический runtime-источник остаётся `data/price.json`. Админка редактирует только тарифные разделы:

- currency и названия кредитов;
- packages;
- costs_reference;
- batch_pricing;
- partner_exchange;
- service_prices.

`admin_ids`, support contacts и иные нетарифные поля сохраняются из текущего файла и не принимаются от административного клиента.

### Публикация

```json
{
  "reason": "update starter package price",
  "confirmation": "PUBLISH TARIFFS",
  "config": {
    "currency": "RUB",
    "packages": [],
    "costs_reference": {}
  }
}
```

Перед записью выполняется структурная проверка пакетов и стоимости моделей. Новый файл:

1. записывается во временный файл в том же каталоге;
2. синхронизируется на диск;
3. атомарно заменяет `data/price.json`;
4. загружается через `preset_manager.reload()`;
5. сохраняется как новая версия с SHA-256 checksum.

При ошибке загрузки или записи версии прежние bytes файла восстанавливаются, после чего выполняется повторный reload старой конфигурации.

`internal_admin_tariff_versions` является append-only. Загрузка старой версии в редактор не изменяет историю: возврат цен оформляется новой публикацией.

## Защита

Все маршруты требуют:

- private network allowlist;
- exact-body HMAC-SHA256;
- NTP на обоих серверах.

Write-команды дополнительно требуют:

```text
Idempotency-Key
X-Admin-User-Id
X-Request-Id
```

DDL выполняется напрямую через psycopg только после успешной network/HMAC-проверки.

## Rollout

1. Обновить Telegram-бот до ветки `tanyapi`.
2. Проверить signed `GET /internal/admin/payments?limit=1`.
3. Проверить signed `GET /internal/admin/tariffs`.
4. Обновить Tanya Admin.
5. На тестовом платеже выполнить `recheck`.
6. Для уже завершённого тестового платежа выполнить `reprocess` и подтвердить отсутствие второго начисления.
7. Опубликовать тарифную версию без изменения значений и получить `no_change`.
8. Изменить тестовый пакет, опубликовать новую версию и проверить историю/checksum.
