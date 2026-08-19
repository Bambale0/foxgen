# Internal Admin Operations API

API предназначено только для `Bambale0/tanya_admin` и работает внутри существующего `aiohttp` процесса Telegram-бота.

## Маршруты

```text
GET  /internal/admin/operations
GET  /internal/admin/operations/{operation_id}
GET  /internal/admin/operations/{operation_id}/timeline
POST /internal/admin/operations/{operation_id}/replay
POST /internal/admin/operations/{operation_id}/refund
```

Список поддерживает `query`, `status`, `type`, `user_id`, `limit` и непрозрачный `cursor`.

## Защита

Для всех запросов обязательны private network allowlist и HMAC-SHA256. Подпись включает:

```text
TIMESTAMP
HTTP_METHOD
FULL_REQUEST_PATH
SHA256_BODY
```

Для write-команд также обязательны:

```text
Idempotency-Key
X-Admin-User-Id
X-Request-Id
```

## Повтор операции

```json
{
  "reason": "provider outage",
  "comment": "support ticket 77",
  "confirmation": "REPLAY 123"
}
```

Повтор:

- создаёт новую дочернюю `generation_tasks` запись;
- связывает её с исходной через `parent_generation_id`;
- устанавливает `action_type=admin_replay`;
- не списывает кредиты повторно;
- использует сохранённый request snapshot и действующие provider adapters;
- отклоняется, если обязательные исходные референсы больше недоступны;
- сохраняет стабильный успешный или неуспешный результат по idempotency key.

## Возврат кредитов

```json
{
  "amount": 10,
  "reason": "failed generation refund",
  "comment": "support ticket 78",
  "confirmation": "REFUND 10"
}
```

Возврат выполняется в одной транзакции с записью timeline и завершением idempotency-команды. Сумма всех успешных возвратов не может превышать исходную стоимость операции.

## Timeline

`internal_admin_operation_events` хранит административные события отдельно от исходной операции:

- `operation.replay`;
- `operation.replayed_from`;
- `credits.refund`.

API также формирует системные события создания и финализации из `generation_tasks`.

## Данные и секреты

Карточка операции возвращает prompt, result metadata и очищенный request snapshot. Ключи, содержащие `token`, `secret`, `password`, `authorization`, `api_key`, `webhook` или `callback`, заменяются на `[redacted]`.

## PostgreSQL

Write API требует PostgreSQL `DATABASE_URL`. Таблица timeline создаётся напрямую через `psycopg` только после успешных network и HMAC-проверок. `generation_tasks.request_data` остаётся текстовым JSON-полем; replay не меняет тип существующей колонки.

## Rollout

1. Развернуть Telegram-бот из ветки `tanyapi`.
2. Проверить signed `GET /internal/admin/operations?limit=1`.
3. Развернуть Tanya Admin.
4. На тестовом пользователе выполнить повтор неуспешной операции.
5. Выполнить частичный возврат и проверить timeline и баланс.
