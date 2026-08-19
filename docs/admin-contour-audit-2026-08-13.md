# Аудит админского контура NEUROMIX

Дата аудита: 2026-08-13

## Executive summary

В проекте есть три административных поверхности:

1. Telegram admin panel внутри бота через `/admin` и callback/FSM flow в [bot/handlers/admin.py](/root/tanya/banano_kling/bot/handlers/admin.py:2277).
2. Внутренний HTTP admin API для внешней админки `tanya_admin`, который фактически маршрутизируется через middleware-dispatch в [bot/services/rate_limiter.py](/root/tanya/banano_kling/bot/services/rate_limiter.py:94) и [bot/internal_admin_dispatch.py](/root/tanya/banano_kling/bot/internal_admin_dispatch.py:212).
3. Admin-only возможности в Mini App UI, завязанные на `state.user.isAdmin`, например управление трендами и moderation actions в [frontend/miniapp-v0/components/tabs/trends-tab.tsx](/root/tanya/banano_kling/frontend/miniapp-v0/components/tabs/trends-tab.tsx:71), [feed-tab.tsx](/root/tanya/banano_kling/frontend/miniapp-v0/components/tabs/feed-tab.tsx:431) и отдельная admin-форма в [seedance25-admin-form.tsx](/root/tanya/banano_kling/frontend/miniapp-v0/components/forms/seedance25-admin-form.tsx:182).

По функциональности контур богатый и уже покрывает статистику, пользователей, партнёров, финансы, цены, промокоды, moderation prompt library, durable campaigns, support/CMS, операции, платежи и тарифы. Главные проблемы не в объёме возможностей, а в консистентности и переносимости:

- часть legacy Telegram admin-flow до сих пор живёт отдельно от более строгого internal admin API;
- полный HTTP admin API поднимается неочевидно, через middleware, а не через явную route registration;
- automated coverage admin-контура почти отсутствует;
- в нескольких FSM message-handlers нет локальной проверки `is_admin`.

Вердикт: контур функционально зрелый, но для безопасного переноса в другой проект его нужно переносить как систему из нескольких слоёв, а не как один файл/роутер.

## Карта админского контура

### 1. Telegram `/admin`

Основная клавиатура собирается в [bot/keyboards.py](/root/tanya/banano_kling/bot/keyboards.py:176) и даёт доступ к:

- статистике;
- управлению пользователями;
- партнёрам;
- финансам и реферальной аналитике;
- редактированию цен;
- промокодам;
- moderation prompt library;
- AI admin;
- включению/выключению обязательной подписки;
- массовой рассылке.

Основной entrypoint: [bot/handlers/admin.py](/root/tanya/banano_kling/bot/handlers/admin.py:2277).

Подтверждённые блоки возможностей:

- `/admin` и `/admin_ai` команды: [bot/handlers/admin.py](/root/tanya/banano_kling/bot/handlers/admin.py:2277)
- цены и прайс-редактирование через FSM: [bot/handlers/admin.py](/root/tanya/banano_kling/bot/handlers/admin.py:2613)
- промокоды create/lookup/toggle: [bot/handlers/admin.py](/root/tanya/banano_kling/bot/handlers/admin.py:2907)
- финансы и XLS выгрузки: [bot/handlers/admin.py](/root/tanya/banano_kling/bot/handlers/admin.py:3045)
- moderation prompt library: [bot/handlers/admin.py](/root/tanya/banano_kling/bot/handlers/admin.py:3151)
- партнёрская аналитика и withdrawals: [bot/handlers/admin.py](/root/tanya/banano_kling/bot/handlers/admin.py:3537)
- пользователи и ручные credit adjustments: [bot/handlers/admin.py](/root/tanya/banano_kling/bot/handlers/admin.py:3759)
- broadcast campaigns: [bot/handlers/admin.py](/root/tanya/banano_kling/bot/handlers/admin.py:3937)

### 2. Internal admin API для `tanya_admin`

Документированные контракты:

- read-only base API: [docs/internal-admin-api.md](/root/tanya/banano_kling/docs/internal-admin-api.md:1)
- users write commands: [docs/internal-admin-user-commands.md](/root/tanya/banano_kling/docs/internal-admin-user-commands.md:1)
- payments/tariffs: [docs/internal-admin-payments-tariffs.md](/root/tanya/banano_kling/docs/internal-admin-payments-tariffs.md:1)
- operations: [docs/internal-admin-operations.md](/root/tanya/banano_kling/docs/internal-admin-operations.md:1)
- CMS/support: [docs/internal-admin-cms-support.md](/root/tanya/banano_kling/docs/internal-admin-cms-support.md:1)
- notification campaigns: [docs/internal-admin-notifications.md](/root/tanya/banano_kling/docs/internal-admin-notifications.md:1)

Фактическая реализация маршрутизации:

- legacy read-only routes регистрируются в [bot/internal_admin_api.py](/root/tanya/banano_kling/bot/internal_admin_api.py:403)
- полный surface, включая POST/write, живёт в [bot/internal_admin_dispatch.py](/root/tanya/banano_kling/bot/internal_admin_dispatch.py:212)
- dispatch вызывается из middleware по path prefix `/internal/admin/` в [bot/services/rate_limiter.py](/root/tanya/banano_kling/bot/services/rate_limiter.py:94)

Подтверждённые capability-группы:

- health, summary, users, generations, finance
- block/unblock/balance adjustments пользователей
- payments detail/recheck/reprocess
- tariffs current/history/publish
- operations list/detail/timeline/replay/refund
- support tickets assign/update/reply
- CMS documents create/publish
- notification campaigns preview/create/test/start/cancel

### 3. Admin-only Mini App возможности

Подтверждённые admin-only UI-сценарии:

- создание и деактивация curated trends: [frontend/miniapp-v0/components/tabs/trends-tab.tsx](/root/tanya/banano_kling/frontend/miniapp-v0/components/tabs/trends-tab.tsx:236)
- feed moderation с правом blur/remove поверх обычных user permissions: [frontend/miniapp-v0/components/tabs/feed-tab.tsx](/root/tanya/banano_kling/frontend/miniapp-v0/components/tabs/feed-tab.tsx:431)
- отдельный Seedance 2.5 admin preview flow без user charging semantics: [frontend/miniapp-v0/components/forms/seedance25-admin-form.tsx](/root/tanya/banano_kling/frontend/miniapp-v0/components/forms/seedance25-admin-form.tsx:182) и [seedance25-public-form.tsx](/root/tanya/banano_kling/frontend/miniapp-v0/components/forms/seedance25-public-form.tsx:286)

## Что нужно переносить как обязательную функциональность

Если цель: "реализовать все возможности админки в другом проекте", то переносить нужно не только Telegram `/admin`, а весь набор:

- Telegram admin command/callback/FSM interface;
- internal signed admin API;
- append-only ledgers и idempotency для write-команд;
- background workers для support outbox и notification campaigns;
- admin-only Mini App / web UI affordances;
- конфигурационные флаги и роли (`is_admin`, `ADMIN_IDS`, HMAC secret, allowlist);
- audit trail и ручные confirmations для опасных операций.

## Findings

### High

1. Почти полное отсутствие automated tests для admin-контура.
   Факты:
   - в `tests/` найден только live smoke: [tests/live/test_kie_live_smoke.py](/root/tanya/banano_kling/tests/live/test_kie_live_smoke.py:1)
   - нет contract tests для `/internal/admin/*`
   - нет FSM tests для `/admin`
   - нет worker tests для `support_outbox` и `notification_deliveries`
   Риск:
   - регрессии в auth, idempotency, payload validation и state flows будут ловиться только вручную.
   Рекомендация:
   - перед переносом в другой проект считать отсутствие test suite ключевым техническим долгом и закрыть его первым пакетом.

2. Legacy Telegram admin writes имеют более слабые гарантии, чем internal admin API.
   Факты:
   - HTTP admin writes требуют HMAC, `Idempotency-Key`, `X-Admin-User-Id`, `X-Request-Id` и ledger-table: [bot/internal_admin_user_commands.py](/root/tanya/banano_kling/bot/internal_admin_user_commands.py:43)
   - Telegram `/admin` credit adjustments идут напрямую через `add_credits()`/`deduct_credits()`: [bot/handlers/admin.py](/root/tanya/banano_kling/bot/handlers/admin.py:3909)
   Риск:
   - разные admin surfaces дают разный уровень auditability и replay safety.
   Рекомендация:
   - в новом проекте не дублировать write-business-logic в Telegram handler'ах; вызывать общий admin command service с единым audit/idempotency контуром.

### Medium

3. Полный internal admin API поднимается скрыто через middleware-dispatch, а не через явный route setup.
   Факты:
   - `setup_internal_admin_routes()` регистрирует только GET read-only routes: [bot/internal_admin_api.py](/root/tanya/banano_kling/bot/internal_admin_api.py:403)
   - write/read full dispatch идёт через [bot/services/rate_limiter.py](/root/tanya/banano_kling/bot/services/rate_limiter.py:94) и [bot/internal_admin_dispatch.py](/root/tanya/banano_kling/bot/internal_admin_dispatch.py:212)
   Риск:
   - при переносе в другой runtime легко скопировать только route registration и потерять весь write API.
   Рекомендация:
   - в новом проекте делать явный `admin_router`/`admin_subapp` и отдельный auth middleware, без скрытой зависимости от rate limiter.

4. В нескольких FSM message-handlers Telegram admin нет локальной проверки `is_admin`.
   Подтверждённые точки:
   - [bot/handlers/admin.py](/root/tanya/banano_kling/bot/handlers/admin.py:2884)
   - [bot/handlers/admin.py](/root/tanya/banano_kling/bot/handlers/admin.py:3733)
   - [bot/handlers/admin.py](/root/tanya/banano_kling/bot/handlers/admin.py:3777)
   - [bot/handlers/admin.py](/root/tanya/banano_kling/bot/handlers/admin.py:3894)
   - [bot/handlers/admin.py](/root/tanya/banano_kling/bot/handlers/admin.py:3957)
   Контекст:
   - глобальный `AccessGuardMiddleware` освобождает от обычных ограничений только `/admin`, `/admin_ai` и callback'и `admin_*`, но не stateful admin messages: [bot/main.py](/root/tanya/banano_kling/bot/main.py:405)
   Риск:
   - текущая эксплуатация держится на том, что state выставляется админскими входами; это хрупкая гарантия.
   Рекомендация:
   - в новом проекте каждая admin state handler должна сама проверять роль.

5. Telegram admin handler остаётся монолитом на тысячи строк.
   Факт:
   - [bot/handlers/admin.py](/root/tanya/banano_kling/bot/handlers/admin.py:1)
   Риск:
   - высокая стоимость изменений, слабая локализация регрессий, сложный review.
   Рекомендация:
   - при переносе разрезать по bounded contexts: `users`, `partners`, `finance`, `pricing`, `promos`, `prompts`, `broadcast`, `ai_admin`.

### Low

6. Админский контур распределён по Telegram bot, HTTP API и Mini App, но в документации это описано в нескольких файлах, без единой capability matrix.
   Риск:
   - при переносе легко упустить Mini App admin affordances.
   Рекомендация:
   - использовать отдельную capability matrix как source of truth.

## Сильные стороны текущего решения

- write HTTP API в основном сделан безопасно: HMAC, allowlist, timestamp window, idempotency, request IDs;
- опасные операции вынесены в append-only ledgers и versioned tables;
- support и notifications спроектированы как durable async workflows, а не "отправить прямо из HTTP";
- есть явное разделение между read-only summary routes и command-style write operations;
- Mini App admin affordances завязаны на `isAdmin`, а не просто на наличие скрытых кнопок.

## Рекомендованная модель переноса

1. Сначала переносить доменные admin services и audit/idempotency слой.
2. Затем поднимать signed internal admin API.
3. Затем строить Telegram `/admin` как thin UI над теми же services.
4. Затем переносить admin-only web/Mini App affordances.
5. Только после этого переносить AI admin и broadcast-specific UX.

## Минимальный acceptance checklist для нового проекта

- есть единый `is_admin`/RBAC слой;
- все write-admin операции проходят через один command service;
- все опасные write-команды требуют confirmation и пишут audit trail;
- все external admin requests защищены allowlist + HMAC + timestamp window;
- есть idempotency для replayable команд;
- support replies и notification campaigns выполняются worker'ами через outbox/queue;
- Telegram `/admin` не содержит отдельной бизнес-логики, только orchestration;
- есть contract tests для HTTP admin API;
- есть FSM/handler tests для Telegram admin;
- есть UI tests хотя бы на admin-only web flows.
