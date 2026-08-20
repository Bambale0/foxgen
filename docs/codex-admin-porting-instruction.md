# Инструкция для Codex: перенести весь admin-контур в другой проект

Используй этот текст как рабочую инструкцию для Codex в другом проекте.

## Роль

Ты переносишь не "одну админку", а три связанных admin-поверхности из NEUROMIX:

1. Telegram `/admin` с callback/FSM flow.
2. Signed internal admin HTTP API для внешней админки.
3. Admin-only web/Mini App возможности.

Не упрощай задачу до копирования одного `admin.py`. Реализуй полный capability parity.

## Что сначала изучить в текущем репозитории

Обязательно прочитай и используй как source of truth:

- [docs/admin-contour-audit-2026-08-13.md](/root/tanya/banano_kling/docs/admin-contour-audit-2026-08-13.md:1)
- [docs/internal-admin-api.md](/root/tanya/banano_kling/docs/internal-admin-api.md:1)
- [docs/internal-admin-user-commands.md](/root/tanya/banano_kling/docs/internal-admin-user-commands.md:1)
- [docs/internal-admin-payments-tariffs.md](/root/tanya/banano_kling/docs/internal-admin-payments-tariffs.md:1)
- [docs/internal-admin-operations.md](/root/tanya/banano_kling/docs/internal-admin-operations.md:1)
- [docs/internal-admin-cms-support.md](/root/tanya/banano_kling/docs/internal-admin-cms-support.md:1)
- [docs/internal-admin-notifications.md](/root/tanya/banano_kling/docs/internal-admin-notifications.md:1)
- [bot/handlers/admin.py](/root/tanya/banano_kling/bot/handlers/admin.py:2277)
- [bot/internal_admin_dispatch.py](/root/tanya/banano_kling/bot/internal_admin_dispatch.py:212)
- [bot/keyboards.py](/root/tanya/banano_kling/bot/keyboards.py:176)
- [frontend/miniapp-v0/components/tabs/trends-tab.tsx](/root/tanya/banano_kling/frontend/miniapp-v0/components/tabs/trends-tab.tsx:71)
- [frontend/miniapp-v0/components/tabs/feed-tab.tsx](/root/tanya/banano_kling/frontend/miniapp-v0/components/tabs/feed-tab.tsx:431)

Если в новом проекте другая архитектура, не копируй старые файлы буквально. Переноси capabilities и invariants.

## Цель

Реализовать в новом проекте все административные возможности, которые существуют в NEUROMIX, но в более чистой архитектуре:

- единый RBAC/admin policy;
- единый domain-layer для admin commands;
- единый audit/idempotency контур;
- отдельные thin adapters для Telegram, HTTP admin API и web admin UI.

## Обязательная архитектура

Сделай минимум такие слои:

1. `admin_policy`
   Проверка ролей, scopes, ручных confirmations, разрешённых команд.

2. `admin_services`
   Чистые use-case сервисы:
   - users
   - partners
   - finance
   - pricing
   - promos
   - prompt moderation
   - operations replay/refund
   - payments recheck/reprocess
   - support
   - CMS
   - notifications
   - ai_admin

3. `admin_command_ledger`
   Append-only журнал для write-команд:
   - `idempotency_key`
   - `admin_user_id`
   - `request_id`
   - `action`
   - `target_id`
   - request payload
   - response payload
   - status
   - timestamps

4. `admin_http_api`
   Signed internal API:
   - network allowlist
   - HMAC-SHA256
   - timestamp skew window
   - exact-body signature
   - request correlation IDs

5. `admin_telegram_ui`
   Только UI/orchestration:
   - команды
   - callback handlers
   - FSM
   - preview/confirm screens
   - без дублирования бизнес-логики

6. `admin_web_ui`
   Admin-only web surface:
   - trends management
   - feed moderation
   - privileged preview forms
   - операторские панели для internal admin API

7. `admin_workers`
   Durable background workers:
   - support outbox
   - notification campaigns

## Полный capability scope

Реализуй parity по следующим группам.

### A. Telegram `/admin`

Нужно реализовать:

- главную admin panel;
- stats summary;
- user lookup по Telegram/internal ID;
- ручное добавление и списание кредитов;
- partner analytics;
- partner withdrawals queue/detail/actions;
- finance dashboard;
- XLS/CSV выгрузки;
- pricing editor:
  - packages
  - image prices
  - video prices
  - partner exchange
  - prompt/video prompt costs
- promo management:
  - create
  - lookup
  - activate/deactivate
- prompt library moderation:
  - list by status
  - detail
  - approve
  - reject
  - deactivate
- subscription-required toggle;
- broadcast creation с preview и confirm;
- AI admin;
- config/preset reload, если в новом проекте есть runtime config.

### B. Internal admin HTTP API

Нужно реализовать endpoints и поведение:

- `GET /internal/admin/health`
- `GET /internal/admin/summary`
- `GET /internal/admin/users`
- `POST /internal/admin/users/{id}/block`
- `POST /internal/admin/users/{id}/unblock`
- `POST /internal/admin/users/{id}/balance-adjustments`
- `GET /internal/admin/generations`
- `GET /internal/admin/finance`
- `GET /internal/admin/payments`
- `GET /internal/admin/payments/{payment_id}`
- `POST /internal/admin/payments/{payment_id}/recheck`
- `POST /internal/admin/payments/{payment_id}/reprocess`
- `GET /internal/admin/tariffs`
- `GET /internal/admin/tariffs/versions`
- `GET /internal/admin/tariffs/versions/{version_id}`
- `POST /internal/admin/tariffs/publish`
- `GET /internal/admin/operations`
- `GET /internal/admin/operations/{operation_id}`
- `GET /internal/admin/operations/{operation_id}/timeline`
- `POST /internal/admin/operations/{operation_id}/replay`
- `POST /internal/admin/operations/{operation_id}/refund`
- `GET /internal/admin/tickets`
- `GET /internal/admin/tickets/{ticket_id}`
- `POST /internal/admin/tickets/{ticket_id}/assign`
- `POST /internal/admin/tickets/{ticket_id}/update`
- `POST /internal/admin/tickets/{ticket_id}/reply`
- `GET /internal/admin/cms/documents`
- `GET /internal/admin/cms/documents/{document_id}`
- `POST /internal/admin/cms/documents`
- `POST /internal/admin/cms/documents/{document_id}/publish`
- `POST /internal/admin/notifications/preview`
- `GET /internal/admin/notifications/campaigns`
- `POST /internal/admin/notifications/campaigns`
- `GET /internal/admin/notifications/campaigns/{id}`
- `POST /internal/admin/notifications/campaigns/{id}/test`
- `POST /internal/admin/notifications/campaigns/{id}/start`
- `POST /internal/admin/notifications/campaigns/{id}/cancel`

### C. Admin-only web/Mini App affordances

Нужно реализовать:

- admin-only create/remove trends UI;
- admin feed moderation: blur/remove with elevated permissions;
- privileged generation/admin preview forms;
- отображение admin controls только при server-confirmed admin role;
- backend revalidation, не полагаться только на UI hidden state.

## Нефункциональные требования

### Security

Обязательные правила:

- никакого доступа к admin routes без явной server-side admin policy;
- каждый admin handler повторно проверяет роль, даже если UI already gated;
- HMAC считается по exact raw body bytes;
- write endpoints требуют `Idempotency-Key`, `X-Admin-User-Id`, `X-Request-Id`;
- internal routes не публикуются в публичный ingress;
- allowlist сети обязателен;
- manual confirm обязателен для destructive/expensive actions;
- request/response логи не содержат secrets;
- в operation detail редактировать/redact keys: `token`, `secret`, `password`, `authorization`, `api_key`, `webhook`, `callback`.

### Idempotency

Сделай идемпотентными:

- balance adjustments;
- user block/unblock;
- payment reprocess;
- operation replay;
- operation refund;
- ticket reply;
- tariff publish;
- campaign create/test/start/cancel.

Повтор с тем же ключом должен возвращать сохранённый результат, а не выполнять действие повторно.

### Async durability

Нельзя:

- отправлять support reply прямо из HTTP request как единственный side effect;
- рассылать кампанию напрямую внутри request lifecycle.

Нужно:

- положить событие в durable outbox/queue;
- обработать worker'ом;
- хранить delivery statuses и retries.

## Как реализовывать

### Phase 1. Capability inventory

Составь matrix:

- capability
- source files в NEUROMIX
- target modules в новом проекте
- transport: Telegram / HTTP / Web
- read/write
- required audit
- required idempotency
- required worker

Не начинай код до завершения этой matrix.

### Phase 2. Domain model

Определи сущности:

- AdminUser
- AdminCommand
- AdminAuditEvent
- TariffVersion
- PaymentEvent
- OperationEvent
- SupportTicket
- SupportMessage
- SupportOutbox
- CmsDocument
- CmsDocumentVersion
- NotificationCampaign
- NotificationDelivery

Определи статусы и allowed transitions заранее.

### Phase 3. Shared admin services

Сначала реализуй use-cases и tests:

- `adjust_user_balance`
- `block_user`
- `unblock_user`
- `recheck_payment`
- `reprocess_payment`
- `publish_tariffs`
- `replay_operation`
- `refund_operation`
- `assign_ticket`
- `update_ticket`
- `reply_ticket`
- `save_cms_document`
- `publish_cms_document`
- `preview_campaign`
- `create_campaign`
- `start_campaign`
- `cancel_campaign`

### Phase 4. Internal HTTP API

Подними явный admin router/subapp.

Не повторяй неявную схему "write routes живут только через middleware interception". В новом проекте routes должны быть видимыми и тестируемыми.

### Phase 5. Telegram admin UI

Построй `/admin` как thin shell:

- keyboards
- callback routing
- FSM screens
- preview/confirm
- вызовы shared admin services

Не допускай прямых SQL/ORM-операций внутри handler'ов, если это write-admin действие.

### Phase 6. Web admin UI

Сделай admin-only страницы/controls для:

- trends
- feed moderation
- support
- CMS
- notifications
- payments
- operations
- tariffs
- users

Все действия идут только через signed/admin-protected backend.

### Phase 7. Workers

Добавь:

- support outbox worker
- notification campaign worker

С ретраями, lease, `FOR UPDATE SKIP LOCKED` или эквивалентом.

## Тесты, которые обязательно должны появиться

### Unit

- HMAC verification
- allowlist check
- idempotency reservation/replay
- confirmation parsing
- role checks
- payload validation
- redaction of secret fields
- tariff validation
- campaign segment validation

### Integration

- signed `GET /internal/admin/health`
- signed `POST /internal/admin/users/{id}/balance-adjustments`
- duplicate `Idempotency-Key` returns same result
- `reprocess` completed payment does not double-credit
- `replay` creates child operation without double-charge
- `reply ticket` creates outbox record, not direct send
- `start campaign` materializes deliveries once

### Telegram/FSM

- non-admin cannot open `/admin`
- non-admin cannot execute any admin callback
- non-admin cannot continue admin FSM state
- admin can complete user lookup
- admin can preview and start broadcast
- admin can moderate prompts

### Web UI

- admin-only controls hidden for regular user
- backend still rejects forged admin action from regular user

## Implementation traps to avoid

- Не копируй только `setup_internal_admin_routes()` из NEUROMIX. Там только read-only GET routes.
- Не прячь critical routing behind unrelated middleware.
- Не дублируй write-logic отдельно в Telegram и HTTP слоях.
- Не делай "UI hidden значит secure".
- Не отправляй массовые уведомления напрямую из request handler.
- Не делай тарифы mutable without version history.
- Не делай support/CMS версии редактируемыми in place.

## Что должно быть в финальном результате

1. Capability matrix.
2. Архитектурная схема нового admin-контура.
3. Реализованные shared services.
4. Реализованный signed internal admin API.
5. Telegram `/admin` thin UI.
6. Web admin UI.
7. Durable workers.
8. Automated tests.
9. Короткий runbook:
   - env vars
   - rollout order
   - smoke checks
   - rollback notes

## Definition of done

Работа завершена только если:

- все перечисленные capability groups реализованы;
- нет write-admin логики, живущей только в UI handlers;
- есть audit/idempotency слой;
- есть contract/integration tests;
- есть worker-based delivery для support и notifications;
- все admin transports используют один и тот же domain layer;
- regular user не может выполнить ни одну admin action ни через Telegram, ни через HTTP, ни через web UI.
