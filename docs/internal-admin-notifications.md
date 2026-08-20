# Internal Admin Notification Campaigns

## Endpoints

```text
POST /internal/admin/notifications/preview
GET  /internal/admin/notifications/campaigns
POST /internal/admin/notifications/campaigns
GET  /internal/admin/notifications/campaigns/{id}
POST /internal/admin/notifications/campaigns/{id}/test
POST /internal/admin/notifications/campaigns/{id}/start
POST /internal/admin/notifications/campaigns/{id}/cancel
```

Все запросы используют private-network allowlist и exact-body HMAC. Write-команды дополнительно требуют `Idempotency-Key`, `X-Admin-User-Id` и `X-Request-Id`.

## Segments

Поддерживаются строго типизированные сегменты:

- `all` — все незаблокированные пользователи;
- `paid` / `unpaid`;
- `recent` / `inactive` с `days`;
- `balance_gte` / `balance_lt` с `amount`;
- `explicit` с массивом до 1000 Telegram ID.

Произвольный SQL, WHERE или имя таблицы из административного payload не принимаются.

## Campaign flow

1. `preview` возвращает размер аудитории без создания кампании.
2. `POST /campaigns` создаёт draft после подтверждения `SAVE CAMPAIGN`.
3. `test` отправляет сообщение только указанному Telegram ID после `TEST {id}`.
4. `start` после `START {id}` один раз материализует аудиторию в `notification_deliveries`.
5. bot-owned worker отправляет сообщения, обновляет отчёт и завершает кампанию.
6. `cancel` после `CANCEL {id}` отменяет ещё не отправленные deliveries.

## Delivery safety

- `FOR UPDATE SKIP LOCKED` для конкурентного claim;
- lease на `sending`, просроченный lease возвращается в retry;
- экспоненциальный backoff и Telegram `retry_after`;
- максимум 5 попыток;
- blocked/deactivated chats учитываются отдельно;
- уникальность `(campaign_id, telegram_id)` исключает дубли;
- текст отправляется как plain text;
- кнопка разрешает только `https://` или `tg://`.

## Repeat button compatibility

Старые result keyboards использовали `repeat_result_*`, а безопасный repeat-flow слушает `repeat_image_*`. Compatibility router сохраняет работу уже отправленных сообщений и направляет оба callback-формата в один экран подтверждения.
