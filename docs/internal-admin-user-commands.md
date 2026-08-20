# Telegram internal user administration

Этот контракт дополняет read-only API из `docs/internal-admin-api.md` контролируемыми административными командами.

## Маршруты

```text
GET  /internal/admin/users?query=<text>&is_banned=<true|false>&limit=25&cursor=<opaque>
POST /internal/admin/users/{id}/block
POST /internal/admin/users/{id}/unblock
POST /internal/admin/users/{id}/balance-adjustments
```

Поиск проверяет внутренний ID, Telegram ID, username, имя и фамилию. Сортировка остаётся `id DESC`, пагинация — cursor-based.

## Обязательные заголовки POST

```text
X-Internal-Timestamp: <unix timestamp>
X-Internal-Signature: <hmac sha256>
Idempotency-Key: <unique command key>
X-Admin-User-Id: <Tanya Admin UUID>
X-Request-Id: <correlation id>
Content-Type: application/json
```

HMAC рассчитывается по точным bytes JSON-body. Нельзя пересериализовать body после вычисления подписи.

## Блокировка

```json
{
  "reason": "Нарушение правил сервиса",
  "comment": "Проверено оператором по обращению #123"
}
```

Разблокировка использует то же тело. Повтор команды безопасен: состояние устанавливается явно, а не переключается.

## Баланс

```json
{
  "amount": 50,
  "reason": "Возврат после ошибочной генерации",
  "comment": "Операция generation #987"
}
```

- `amount` — целое число от `-1000000` до `1000000`, кроме нуля;
- итоговый баланс не может стать отрицательным;
- успешный результат сохраняется в `internal_admin_commands`;
- повтор с тем же `Idempotency-Key` возвращает сохранённый результат и не меняет баланс повторно;
- тот же ключ нельзя использовать для другой команды или пользователя.

## Ответ

```json
{
  "channel": "telegram",
  "api_version": "1",
  "service_version": "1.0.0",
  "data": {
    "id": 42,
    "telegram_id": 339795159,
    "username": "igor",
    "credits": 65,
    "has_paid": true,
    "is_banned": false,
    "created_at": "2026-07-11T10:00:00",
    "updated_at": "2026-07-11T17:30:00"
  }
}
```

## Ответственность сервисов

Telegram-бот:

- проверяет HMAC, timestamp и network allowlist;
- проверяет служебные заголовки;
- обеспечивает идемпотентность;
- выполняет транзакционное изменение PostgreSQL;
- не принимает роль администратора от клиента.

Tanya Admin:

- аутентифицирует администратора;
- проверяет RBAC;
- требует ручное подтверждение и причину;
- создаёт `X-Admin-User-Id`, `X-Request-Id`, `Idempotency-Key`;
- пишет append-only audit events `requested`, `success` или `failed`.

## Rollout

1. Сначала развернуть Telegram PR и перезапустить Telegram-сервис.
2. Проверить подписанный `GET /internal/admin/users?query=...`.
3. Развернуть Tanya Admin PR и применить его Alembic migration.
4. Проверить блокировку на тестовом пользователе.
5. Проверить повтор той же balance-команды с одним idempotency key: баланс должен измениться один раз.

Internal path нельзя публиковать через публичный Nginx.