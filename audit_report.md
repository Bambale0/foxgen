# 🔴 AUDIT REPORT — banano_kling

**Дата:** 2026-07-07 (повторный аудит, подтверждение + дополнение от 2026-07-04)
**Аудитор:** OpenClaw (Cline) с привлечением 5 параллельных под-агентов
**Методология:** полный статический анализ ~140 файлов, построение карты связей, аудит безопасности, анализ архитектуры
**Предыдущий аудит:** 2026-07-04 — все находки подтверждены, добавлены новые

---

## 1. Executive Summary

| Параметр | Значение |
|----------|----------|
| **Проект запускается?** | Требует проверки — не проверялся живой запуск |
| **P0 рисков** | 12 |
| **P1 рисков** | 28 |
| **P2 рисков** | 19 |
| **P3 рисков** | 8 |
| **Главная угроза деньгам** | Отсутствие атомарных транзакций при списании баланса + двойное списание при race condition |
| **Главная угроза безопасности** | Отсутствие проверки Telegram initData в mini-app; IDOR через подмену task_id в callback_data |
| **Главная угроза стабильности** | 429/500 от внешних API не обрабатываются с возвратом средств; задачи застревают в статусе `processing` |
| **Готов к production** | **НЕТ** — требуется устранение P0 и P1 перед релизом |
| **Топ-5 исправлений** | 1. Транзакционное обновление баланса 2. Идемпотентность webhook'ов 3. Возврат средств при ошибке API 4. Проверка initData в mini-app 5. Обработка 429/500 от провайдеров |

---

## 2. Карта проекта

### 2.1 Стек

| Слой | Технология |
|------|-----------|
| Python | 3.x |
| Telegram Bot | aiogram 3.x |
| База данных | SQLite (dev) / PostgreSQL (prod) через aiosqlite + адаптер `postgres_aiosqlite.py` |
| Redis | redis-py 5.x (FSM storage + кэш) |
| HTTP Server | aiohttp (webhook) |
| Frontend | Next.js 14 + React + Tailwind + shadcn/ui (Telegram Mini App) |
| Платежи | YooKassa, CryptoBot, Lava.top, Telegram Stars, TBank |
| AI API | Kie.ai (Kling, Seedance, Seedream, Veo, Wan27), Google Gemini, OpenAI GPT-Image, xAI Grok, Nano Banana 2/Pro |
| Конфигурация | python-dotenv + pydantic |
| Type hints | typing-extensions |

### 2.2 Точки входа

| Точка | Файл | Тип |
|-------|------|-----|
| `main()` | `bot/main.py:701` | Запуск бота |
| `/webhook` | `bot/main.py:182` (aiohttp) | Telegram webhook |
| `/webhook/yookassa` | `bot/services/yookassa_service.py` | YooKassa webhook |
| `/webhook/cryptobot` | `bot/services/cryptobot_service.py` | CryptoBot webhook |
| `/webhook/lava` | `bot/services/lava_service.py` | Lava webhook |
| `/webhook/tbank` | `tbank_payment/webhooks.py` | TBank webhook |
| `/healthcheck` | `bot/main.py` (aiohttp) | Healthcheck |
| `/api/generation/webhook` | Сервисы Kie.ai | AI provider callback |

### 2.3 Handlers / Routes (6 роутеров)

| Router | Файл | Handler'ов | Ключевая функциональность |
|--------|------|-----------|--------------------------|
| main_router | `bot/handlers/common.py` | ~15 | /start, меню, профиль, поддержка, рефералы |
| generation_router | `bot/handlers/generation.py` | ~25 | Выбор модели, ввод промпта, генерация, статус задачи, история |
| payment_router | `bot/handlers/payments.py` | ~18 | Пополнение баланса, выбор способа оплаты, проверка баланса |
| admin_router | `bot/handlers/admin.py` | ~20 | Статистика, рассылки, промокоды, управление ценами, AI-ассистент админа |
| batch_router | `bot/handlers/batch_generation.py` | ~5 | Пакетная генерация |
| image_analyzer_router | `bot/handlers/image_analyzer.py` | ~5 | Анализ изображений |

### 2.4 Внешние API

| API | Сервис | Аутентификация |
|-----|--------|---------------|
| Kie.ai | `kling_service.py`, `seedance_service.py`, `seedream_service.py`, `veo_service.py`, `wan27_service.py`, `kie_file_upload_service.py`, `kie_market_service.py` | API Key в Header |
| Google Gemini | `gemini_service.py`, `gemini_omni_service.py` | API Key |
| OpenAI GPT-Image | `gpt_image_service.py` | API Key |
| xAI Grok | `grok_service.py` | API Key |
| YooKassa | `yookassa_service.py`, `services/yookassa_client.py` | Shop ID + Secret |
| CryptoBot | `cryptobot_service.py` | API Token |
| Lava.top | `lava_service.py` | Secret Key |
| TBank | `tbank_payment/` | API Token |
| NanoBanana API | `nano_banana_2_service.py`, `nano_banana_pro_service.py` | API Key |
| Redis | `redis_service.py` | Redis URL |

### 2.5 БД-сущности

| Таблица | Ключевые поля |
|---------|--------------|
| `users` | id, telegram_id, credits, referral_code, referred_by, is_admin, subscription, limits |
| `transactions` | id, user_id, type, amount, provider_payment_id, status, metadata |
| `generation_tasks` | id, user_id, service_name, prompt, status, external_task_id, result_url, credits_spent, created_at |
| `referral_codes` | id, code, created_by |
| `referral_bonuses` | id, user_id, referred_user_id, transaction_id, amount |
| `subscriptions` | user_id, plan, active_until, auto_renew |
| `feed` | id, user_id, content, media_urls, created_at |
| `presets` | id, user_id, name, prompt, negative_prompt, model, params |
| `admin_ai_logs` | id, admin_id, request_text, response_text, actions_taken |

### 2.6 Тесты

- **Фреймворк:** pytest (pytest.ini присутствует, `asyncio_mode = auto`)
- **Тестов:** **НЕ ОБНАРУЖЕНО** — в репозитории нет ни одного тестового файла
- **pytest.ini** существует, но тестовые модули отсутствуют

---

## 3. Реестр дефектов

### P0 — Критические (12)

| ID | Severity | Area | Симптом | Причина | Файл/строка | Fix |
|----|----------|------|---------|---------|-------------|-----|
| **P0-01** | P0 | БД/Баланс | Двойное списание баланса при race condition | `UPDATE users SET credits = credits - :amount WHERE id = :uid` без `SELECT ... FOR UPDATE` и без проверки текущего баланса | `bot/database.py` | Обернуть в транзакцию с `SELECT ... FOR UPDATE`, проверять `credits >= amount` внутри UPDATE |
| **P0-02** | P0 | Платежи | Webhook YooKassa не идемпотентен | Нет проверки `event_id` / дублирования при повторном webhook'е | `bot/services/yookassa_service.py` | Сохранять `webhook_event_id`, проверять уникальность перед обработкой |
| **P0-03** | P0 | Платежи | Webhook CryptoBot не идемпотентен | Аналогично P0-02 | `bot/services/cryptobot_service.py` | Добавить `UNIQUE(provider_payment_id)` constraint + проверку |
| **P0-04** | P0 | Генерация | Ошибка внешнего API не возвращает средства | При HTTP 429/500/502 от Kie.ai задача получает статус `failed`, но `credits` не возвращаются | `bot/services/kling_service.py`, `bot/handlers/generation.py` | В обработчике ошибок вызывать возврат credits с аудитом |
| **P0-05** | P0 | Генерация | Задача застревает в статусе `processing` навсегда | Нет фонового процесса/polling'а для зависших задач (только `task_watchdog.py` — требует проверки) | Все сервисы (Veo, Seedance, Wan27) | Добавить background job для опроса задач старше N минут |
| **P0-06** | P0 | Безопасность | IDOR: пользователь может получить чужую задачу | `callback_data` содержит `task_id`, но нет проверки `task.user_id == current_user.id` | `bot/handlers/generation.py:check_task_status()` | Добавить `WHERE user_id = :current_user_id` |
| **P0-07** | P0 | Безопасность | Mini-app не проверяет Telegram initData | Frontend использует WebApp.initData но backend не валидирует подпись | `bot/miniapp.py`, `bot/main.py` | Внедрить `validate_telegram_webapp_data()` на backend |
| **P0-08** | P0 | Безопасность | Webhook Kie.ai не проверяет подпись/источник | `callBackUrl` принимает любые POST-запросы без аутентификации | `bot/main.py`, webhook handler | Добавить HMAC-секрет в callback_url как query-параметр |
| **P0-09** | P0 | Платежи | Lava webhook не проверяет подпись | `bot/services/lava_service.py` — webhook handler без HMAC-валидации | `bot/services/lava_service.py` | Добавить проверку HMAC-SHA256 подписи |
| **P0-10** | P0 | Платежи | TBank webhook не проверяется | `tbank_payment/webhooks.py` — отсутствует проверка подписи уведомления | `tbank_payment/webhooks.py` | Имплементировать проверку TBank Notification Signature |
| **P0-11** | P0 | БД | Отсутствие транзакций при списании + создании задачи | `deduct_credits + insert generation_task + call external API` не в одной транзакции | `bot/handlers/generation.py` | Обернуть в DB transaction |
| **P0-12** | P0 | Конфигурация | Секреты в `config.py` без fallback по умолчанию | Вызовы `.get()` без `.required()` могут привести к None → падение с невнятной ошибкой | `bot/config.py` | Заменить на `.required()` с pydantic валидацией |

### P1 — Высокие (28)

| ID | Severity | Area | Симптом | Fix |
|----|----------|------|---------|-----|
| P1-01 | P1 | Callback | Кнопка "Назад" не содержит state для возврата | Сохранять предыдущее состояние в callback_data или FSM |
| P1-02 | P1 | Callback | `generate_model:X` парсится через `.split(":")`, но model_name может содержать `:` | Использовать `split(":", 1)` |
| P1-03 | P1 | FSM | Состояние FSM может быть очищено middleware, но handler всё ещё ожидает его | Добавить проверку наличия state-данных |
| P1-04 | P1 | API | `callBackUrl` vs `callback_url` — несоответствие camelCase/snake_case в разных сервисах | Унифицировать: `callBackUrl` согласно API Kie.ai |
| P1-05 | P1 | API | `image_url` для референсов: локальный путь vs публичный URL | Загружать файл в публичное хранилище перед отправкой в API |
| P1-06 | P1 | API | Seedance `generate_video()` не передаёт `callBackUrl` во всех случаях | Гарантировать передачу `callBackUrl` |
| P1-07 | P1 | API | Gemini: `response_format` не всегда парсится корректно при нескольких кандидатах | Итерация по `candidates` + проверка `finish_reason` |
| P1-08 | P1 | Платежи | YooKassa: возможное расхождение копейки vs рубли | Явно документировать и валидировать единицы измерения |
| P1-09 | P1 | Платежи | CryptoBot: invoice без `expires_in` | Добавить `expires_in` для автоотмены |
| P1-10 | P1 | Referral | Начисление реферального бонуса при self-referral | Добавить проверку `referrer_id != referred_user_id` |
| P1-11 | P1 | Referral | Реферальный бонус может начислиться дважды | `UNIQUE(payment_id, bonus_type)` constraint |
| P1-12 | P1 | Админ | Не все admin handler'ы проверяют `is_admin` | Middleware `is_admin` на admin_router |
| P1-13 | P1 | Админ | `AdminStates.waiting_ai_request` — риск доступа не-admin | Проверка is_admin при входе в admin-состояние |
| P1-14 | P1 | Mini-app | Нет обработки ошибок сети между mini-app и ботом | Retry на фронтенде + graceful degradation |
| P1-15 | P1 | Mini-app | История задач без пагинации | Добавить пагинацию/cursor |
| P1-16 | P1 | БД | `referral_code` без UNIQUE constraint в SQLite (в отличие от PG) | `CREATE UNIQUE INDEX IF NOT EXISTS` |
| P1-17 | P1 | БД | `transactions.provider_payment_id` без UNIQUE constraint | `UNIQUE(provider_payment_id)` |
| P1-18 | P1 | БД | `generation_tasks.external_task_id` без индекса | `INDEX ON generation_tasks(external_task_id)` |
| P1-19 | P1 | Валидация | Prompt не валидируется на длину перед API | Обрезать/валидировать до лимитов провайдера |
| P1-20 | P1 | Валидация | Нет проверки размера загружаемого файла | Добавить лимит (Telegram: 20MB) |
| P1-21 | P1 | Ошибки | `try/except Exception` проглатывает ошибку без `exc_info=True` | Логировать с `exc_info=True` |
| P1-22 | P1 | Ошибки | 400 от Kie.ai: не парсится тело ответа с деталями | Парсить `response.json()` |
| P1-23 | P1 | Ошибки | Нет retry logic при network timeout | `tenacity` / exponential backoff |
| P1-24 | P1 | FSM | Незавершённый flow теряет состояние | Команда `cancel` или тайм-аут FSM |
| P1-25 | P1 | Логи | Нет correlation_id в логах | `structlog` с `task_id`/`user_id`/`request_id` |
| P1-26 | P1 | Mini-app | `initDataUnsafe` вместо `initData` | Проверять подпись на backend с `initData` |
| P1-27 | P1 | БД | `updated_at` не обновляется автоматически в SQLite | `updated_at = CURRENT_TIMESTAMP` в UPDATE |
| P1-28 | P1 | API | `aspect_ratio` не валидируется перед отправкой | Валидировать enum на фронте + бэкенде |

### P2 — Средние (19)

| ID | Area | Симптом | Fix |
|----|------|---------|-----|
| P2-01 | UX | Кнопка "Назад" возвращает в главное меню, а не на предыдущий шаг | Сохранять историю навигации в FSM |
| P2-02 | UX | Технические сообщения об ошибках вместо user-friendly | Использовать `user_facing_errors.py` систематически |
| P2-03 | Кэш | Redis не используется для кэширования результатов | Кэшировать результаты для одинаковых prompt |
| P2-04 | Rate Limit | Нет rate limiting на API endpoints | `aiogram-throttling` или Redis rate limiter |
| P2-05 | Документация | `docs/kling_api.md` устарели | Обновить документацию |
| P2-06 | CI | Нет CI/CD pipeline | GitHub Actions для lint + test |
| P2-07 | Lint | `requirements.txt` не закрепляет минорные версии | `pip freeze` или `poetry.lock` |
| P2-08 | Docker | Нет Dockerfile | Добавить Dockerfile и docker-compose |
| P2-09 | Логи | `print()` вместо `logging` | Заменить на `logging.getLogger(__name__)` |
| P2-10 | Graceful | Нет graceful shutdown | Сохранение состояния при SIGTERM |
| P2-11 | Конфиг | `postgres_aiosqlite.py` транслирует SQLite-диалект на лету — хрупкий подход | SQLAlchemy + Alembic |
| P2-12 | Schema | `schema_postgres.sql` и `bot/database.py` могут расходиться | Автоматизировать генерацию схемы |
| P2-13 | Мёртвый код | `bot/neuromix_copy.py`, `bot/partner_copy.py`, `bot/support_copy.py` — старые версии | Удалить или отрефакторить |
| P2-14 | Тесты | Нет ни одного теста | Создать базовый test suite |
| P2-15 | Webhook | `allowed_updates` не настроен | `allowed_updates=["message", "callback_query"]` |
| P2-16 | N+1 | Загрузка истории задач: N отдельных запросов | JOIN или batch query |
| P2-17 | Реферал | Реферальный код генерируется без проверки коллизий | Retry при генерации |
| P2-18 | Ошибки | `user_facing_errors.py` не интегрирован систематически | Интегрировать во все handler'ы |
| P2-19 | Цены | `data/price.json` и `bot/pricing_final.py` — два источника истины | Оставить один источник |

### P3 — Улучшения (8)

| ID | Area | Fix |
|----|------|-----|
| P3-01 | UX | Инлайн-прогресс (progress bar) во время генерации |
| P3-02 | UX | Превью результата перед отправкой пользователю |
| P3-03 | Аналитика | Сбор метрик: conversion rate, среднее время генерации |
| P3-04 | i18n | Все тексты захардкожены на русском — добавить i18n |
| P3-05 | Мониторинг | Healthcheck для каждого внешнего API |
| P3-06 | Документация | Архитектурная схема (C4 model) |
| P3-07 | Type Hints | `Dict[str, Any]` → TypedDict/Pydantic модели |
| P3-08 | Зависимости | `openai` в `admin_ai_service.py` — проверить наличие в `requirements.txt` |

---

## 4. Новые находки (дополнение от 07.07.2026)

### 4.1 Системная безопасность (bot.service)

| ID | Severity | Finding | Detail |
|----|----------|---------|--------|
| **NEW-01** | **P0** | Бот запускается от `root` | `bot.service`: `User=root`, `WorkingDirectory=/root/tanya/banano_kling`. Компрометация бота = полный root-доступ к серверу. Создать непривилегированного пользователя `banano`. |
| **NEW-02** | **P1** | `ExecStopPost` убивает все процессы на порту 1888 | `fuser -k 1888/tcp` — если другой сервис займёт порт, он будет уничтожен при каждом рестарте. |
| **NEW-03** | **P1** | Нет systemd-харденинга | Отсутствуют: `PrivateTmp=yes`, `NoNewPrivileges=yes`, `ProtectSystem=strict`, `ProtectHome=yes`, `ReadWritePaths=...`, `RestrictAddressFamilies=...`, `MemoryMax=...` |
| **NEW-04** | **P2** | `EnvironmentFile=-/root/tanya/banano_kling/.env` — `.env` в `/root` | Секреты лежат в домашней директории root. |

### 4.2 Архитектурные находки

| ID | Severity | Finding | Detail |
|----|----------|---------|--------|
| **NEW-05** | **P1** | `postgres_aiosqlite.py` — хрупкий adapter layer | Транслирует SQLite-диалект в PostgreSQL через regex. Замены: `?` → `$1`, `INSERT OR IGNORE` → `INSERT ... ON CONFLICT DO NOTHING`, `date('now')` → `NOW()`, булевы литералы. При любом изменении SQL-диалекта адаптер сломается. Рекомендация: SQLAlchemy + Alembic. |
| **NEW-06** | **P1** | Два модуля БД: `database.py` + `db.py` | Дублирование логики. Оставить один. |
| **NEW-07** | **P2** | `bot/services/__init__.py`: сервисы создаются как module-level синглтоны | Затрудняет тестирование (нет dependency injection). |
| **NEW-08** | **P2** | `bot/handlers/admin.py` — 4118 строк | Монолитный handler. Разбить на модули: `admin_stats.py`, `admin_broadcast.py`, `admin_promos.py`, `admin_pricing.py`, `admin_ai.py`. |
| **NEW-09** | **P2** | `bot/handlers/generation.py` — >25 handler'ов в одном файле | Разбить по моделям/этапам генерации. |
| **NEW-10** | **P2** | Смешанные HTTP-клиенты: синхронный `requests` и асинхронный `aiohttp` | `image_analyzer_service.py` использует синхронные `requests` в async-контексте. Унифицировать на `aiohttp`. |

### 4.3 Frontend (Next.js Mini App)

| ID | Severity | Finding | Detail |
|----|----------|---------|--------|
| **NEW-11** | **P1** | `initDataUnsafe` используется на фронтенде | `frontend/miniapp-v0/` — должен передаваться `initData` с проверкой подписи на backend. |
| **NEW-12** | **P2** | Нет обработки ошибок сети | `frontend/` — отсутствует retry/fallback при потере соединения с ботом. |
| **NEW-13** | **P2** | История задач без пагинации на фронтенде | `task-history-list.tsx` — потенциально медленно при большом количестве задач. |
| **NEW-14** | **P2** | `next.config.mjs` — нет `images` domains для API-источников | Может блокировать загрузку изображений из внешних API. |

### 4.4 Документация и скрипты

| ID | Severity | Finding | Detail |
|----|----------|---------|--------|
| **NEW-15** | **P2** | 15 скриптов в `scripts/` без документации запуска | `migrate_sqlite_to_postgres.py`, `repair_referral_cycles.py`, `backfill_feed_author_photos.py` и др. — нет README с описанием и порядком запуска. |
| **NEW-16** | **P2** | 13 файлов в `docs/` — часть устарела | `kling_api.md`, `banana_api.md` могут не соответствовать текущему API. |
| **NEW-17** | **P3** | `memory/` содержит operational notes | `2026-07-05.md` — операционные заметки. Хорошая практика, стоит расширить. |
| **NEW-18** | **P3** | `prompts/` содержит agent-промпты | `sprint-orchestrator-prompt.md`, `pr-review-checklist.md` — полезные артефакты. |

### 4.5 Конфигурация и безопасность

| ID | Severity | Finding | Detail |
|----|----------|---------|--------|
| **NEW-19** | **P1** | `nginx.conf.example` — только пример, нет продакшн-конфига | Нет rate limiting, нет ограничений на webhook IP, нет SSL-шаблона. |
| **NEW-20** | **P2** | `.gitignore` — требует проверки | Убедиться, что `.env`, `*.log`, `__pycache__`, `*.pyc` исключены. |
| **NEW-21** | **P2** | `set_webhook.py` — скрипт установки webhook без проверки результата | Нет валидации ответа Telegram API. |

---

## 5. Таблица links / callbacks / routes (верификация)

| UI / Button / URL | Где создано | Что передаёт | Что ожидает handler | Статус | Проблема |
|-------------------|-------------|-------------|---------------------|--------|----------|
| `btn_generate` → `generate_model:kling` | `keyboards.py` | `callback_data="generate_model:kling"` | `generation.py:process_model_selection()` | ✅ | Риск: model_name с `:` сломает split |
| `btn_task_status` → `check_task:X` | `keyboards.py` | `callback_data="check_task:{task_id}"` | `generation.py:check_task_status()` | ⚠️ | P0-06: нет проверки `user_id` |
| `btn_cancel` → `cancel_generation` | `keyboards.py` | `callback_data="cancel_generation"` | `generation.py:cancel_handler()` | ⚠️ | Не возвращает credits |
| `btn_retry` → `retry_task:X` | `generation.py` | `callback_data="retry_task:{task_id}"` | `generation.py:retry_handler()` | ⚠️ | Повторное списание без проверки статуса |
| Mini-app link | `miniapp_links.py` | `https://t.me/.../app?startapp={user_id}` | `bot/main.py` webapp handler | ⚠️ | P0-07: нет проверки подписи |
| Admin AI кнопка | `keyboards.py` | `callback_data="admin_ai"` | `admin.py:admin_ai_open()` | ✅ | P1-13: любой в FSM `AdminStates` может вызвать |
| YooKassa webhook | `yookassa_service.py` | POST `/webhook/yookassa` | `yookassa_service.py:webhook_handler()` | ⚠️ | P0-02: нет идемпотентности |
| CryptoBot webhook | `cryptobot_service.py` | POST `/webhook/cryptobot` | `cryptobot_service.py:webhook_handler()` | ⚠️ | P0-03: нет идемпотентности |
| Lava webhook | `lava_service.py` | POST `/webhook/lava` | `lava_service.py:webhook_handler()` | ⚠️ | P0-09: нет проверки подписи |
| TBank webhook | `tbank_payment/webhooks.py` | POST `/webhook/tbank` | `webhooks.py:tbank_webhook_handler()` | ⚠️ | P0-10: нет проверки подписи |
| Kie.ai callback | `kling_service.py:create_task()` | POST `{callBackUrl}` | `bot/main.py` webhook endpoint | ⚠️ | P0-08: нет аутентификации |

---

## 6. Security Findings (сводка)

| ID | Severity | Finding | Exploit Scenario | Fix |
|----|----------|---------|------------------|-----|
| SEC-01 | **CRITICAL** | Нет проверки Telegram initData в mini-app | Поддельный POST с `user_id` → доступ к любым данным от имени любого пользователя | `validate_telegram_webapp_data(bot_token, init_data)` |
| SEC-02 | **CRITICAL** | Webhook Kie.ai без аутентификации | POST с `{"status":"completed","result_url":"https://evil.com/..."}` | HMAC-секрет в callback_url |
| SEC-03 | **CRITICAL** | Lava webhook без проверки подписи | Поддельный POST с `status=success` → начисление без оплаты | HMAC-SHA256 подпись |
| SEC-04 | **CRITICAL** | TBank webhook без проверки подписи | Аналогично Lava | TBank Notification Signature |
| SEC-05 | **HIGH** | IDOR: доступ к чужим задачам | Подмена `task_id` в callback_data | `WHERE task.user_id = :current_user_id` |
| SEC-06 | **HIGH** | IDOR: admin callback'ы без универсальной проверки | Обычный пользователь шлёт callback `admin` | Middleware `is_admin` на admin_router |
| SEC-07 | **MEDIUM** | SQL Injection через callback_data | `task_id="1; DROP TABLE users;--"` (частично защищено `?` placeholders) | Параметризованные запросы + валидация |
| SEC-08 | **MEDIUM** | Отсутствие rate limiting на API/webhook | Перебор ID задач / DDoS webhook endpoint | Redis rate limiter |
| SEC-09 | **MEDIUM** | Технические ошибки утекают пользователю | `except Exception: await msg.answer(str(e))` | `UserFacingError` маппинг |
| SEC-10 | **INFO** | CORS не настроен для mini-app API | Не критично для webhook, нужно для mini-app | Настроить CORS для mini-app endpoint |

---

## 7. Бизнес-логика: верификация инвариантов

| Entity / Flow | Invariant | Нарушается? | Fix |
|---------------|-----------|-------------|-----|
| Balance | Не может быть отрицательным | ✅ Да | `WHERE credits >= :amount` |
| Balance | Списание атомарно с созданием задачи | ✅ Да | DB transaction |
| Payment | Один payment_id → одно начисление | ✅ Да | UNIQUE(provider_payment_id) |
| Payment | Webhook подпись валидна | ✅ Да (Lava, TBank) | HMAC-проверка |
| Referral | Нельзя рефералить самого себя | ✅ Да | `referrer_id != referred_user_id` |
| Referral | Один платёж → один бонус | ✅ Да | UNIQUE(payment_id, bonus_type) |
| Generation | Статусы: pending → processing → completed/failed | ⚠️ Частично | Тайм-аут для `processing` |
| Generation | Пользователь видит только свои задачи | ✅ Да | `user_id` проверка в handler |
| Generation | Отмена задачи возвращает credits | ✅ Да | `cancel_handler` возврат credits |
| Admin | Только admin вызывает admin-функции | ⚠️ Частично | Middleware `is_admin` |
| Price | Единый источник цен | ⚠️ Частично | Убрать `data/price.json` |

---

## 8. План исправлений (приоритизированный)

### Фаза 1 — P0 (перед любым релизом)

| # | Что | Файлы |
|---|------|-------|
| 1 | Атомарное обновление баланса | `bot/database.py` |
| 2 | Идемпотентность всех webhook'ов | `yookassa_service.py`, `cryptobot_service.py`, `lava_service.py`, `tbank_payment/webhooks.py` |
| 3 | Возврат credits при ошибке API | `bot/handlers/generation.py` |
| 4 | Проверка initData в mini-app | `bot/miniapp.py`, `bot/main.py` |
| 5 | Аутентификация Kie.ai webhook | `bot/main.py`, все Kie-сервисы |
| 6 | Проверка подписи Lava webhook | `bot/services/lava_service.py` |
| 7 | Проверка подписи TBank webhook | `tbank_payment/webhooks.py` |
| 8 | Проверка `user_id` при доступе к задаче | `bot/handlers/generation.py`, `admin.py` |
| 9 | DB transaction для deduct+insert | `bot/handlers/generation.py` |
| 10 | Pydantic `.required()` для всех обязательных env | `bot/config.py` |
| 11 | Фоновый polling зависших задач | `bot/services/task_watchdog.py` |
| 12 | UNIQUE constraint на `provider_payment_id` | `bot/database.py`, `schema_postgres.sql` |
| 13 | **NEW** Запуск от непривилегированного пользователя | `bot.service` |
| 14 | **NEW** Systemd security hardening | `bot.service` |

### Фаза 2 — P1

| # | Что | Файлы |
|---|------|-------|
| 1 | `split(":")` → `split(":", 1)` | `bot/handlers/generation.py` |
| 2 | Middleware `is_admin` на admin_router | `bot/handlers/admin.py`, `bot/main.py` |
| 3 | Retry logic (tenacity) для всех внешних API | Все `bot/services/*_service.py` |
| 4 | Correlation ID в логах | Все handler'ы и сервисы |
| 5 | Унификация `callBackUrl` | `bot/services/*_service.py` |
| 6 | Self-referral prevention | `bot/services/referral_service.py` |
| 7 | UNIQUE на referral bonus | `bot/database.py` |
| 8 | Индекс на `external_task_id` | `bot/database.py` |
| 9 | Валидация размера файла | `bot/handlers/common.py` |
| 10 | Пагинация истории задач | `bot/handlers/generation.py`, frontend |

### Фаза 3 — P2/P3

- Redis-кэширование результатов
- Rate limiting
- Graceful shutdown
- Dockerfile + docker-compose
- CI/CD (GitHub Actions)
- Удалить мёртвый код (`*_copy.py`)
- i18n
- C4 architecture diagram
- `Dict[str, Any]` → TypedDict/Pydantic
- Аналитика и мониторинг
- SQLAlchemy + Alembic вместо `postgres_aiosqlite.py`
- Разбить `admin.py` (4118 строк) на модули
- Унифицировать HTTP-клиенты на `aiohttp`

---

## 9. Smoke Checklist

| # | Check | Expected | Status |
|---|-------|----------|--------|
| S1 | `pip install -r requirements.txt` | Без ошибок | ❓ |
| S2 | Импорт всех модулей | Без ошибок | ❓ |
| S3 | Чтение env | Все required переменные определены | ❓ |
| S4 | Подключение к БД | Таблицы созданы | ❓ |
| S5 | `schema_postgres.sql` vs `init_db()` | Схемы идентичны | ❓ |
| S6 | Старт бота (polling) | Бот запущен | ❓ |
| S7 | Старт бота (webhook) | Webhook установлен | ❓ |
| S8 | `curl http://localhost:8080/healthcheck` | HTTP 200 | ❓ |
| S9 | `/start` команда | Ответ с главным меню | ❓ |
| S10 | Главное меню — все кнопки | Все работают | ❓ |
| S11 | Создание тестовой генерации | Задача создана, credits списаны | ❓ |
| S12 | Webhook генерации (mock) | Статус → completed | ❓ |
| S13 | Тестовый платёж YooKassa | Баланс увеличен | ❓ |
| S14 | Тестовый платёж CryptoBot | Баланс увеличен | ❓ |
| S15 | `/admin` от admin user | Админ-панель открыта | ❓ |
| S16 | `/admin` от обычного пользователя | Отказ в доступе | ❓ |
| S17 | Mini-app открытие | Приложение загружается | ❓ |
| S18 | Mini-app история задач | Видны только свои задачи | ❓ |
| S19 | Перезагрузка во время генерации | Задачи не потеряны | ❓ |
| S20 | Graceful shutdown (SIGTERM) | Операции завершены/сохранены | ❓ |

---

## 10. Минимальный набор команд для CI

```bash
# Установка
pip install -r requirements.txt
pip install pytest pytest-asyncio pytest-mock pytest-cov ruff bandit

# Линтинг
ruff check bot/ frontend/

# Type checking
pip install mypy && mypy bot/ --ignore-missing-imports

# Тесты
pytest tests/ -v --asyncio-mode=auto --cov=bot --cov-report=html

# Security scan
bandit -r bot/ --skip B101
```

---

## 11. Финальный вердикт

| Вопрос | Ответ |
|--------|-------|
| **Готово к production?** | **НЕТ** |
| **Главная причина** | Отсутствие защиты от двойного списания, неидемпотентные webhook'и, отсутствие проверки подлинности mini-app запросов и webhook'ов внешних API, запуск от root |
| **Топ-5 исправлений** | 1. Транзакционное обновление баланса 2. Идемпотентность webhook'ов 3. Возврат credits при ошибке API 4. Проверка initData в mini-app 5. Аутентификация webhook'ов |
| **Тестов в репозитории** | **0** |
| **Минимальный test suite** | 12 unit + 8 integration + 2 smoke |
| **Что проверить вручную** | 20 пунктов smoke-checklist |

---

**Аудит завершён.** Найдено: **12 критических (P0)**, **28 высоких (P1)**, **19 средних (P2)**, **8 низких (P3)**. **+21 новая находка** от 07.07.2026 (системная безопасность, архитектура, frontend, документация). **0 тестов** в репозитории. Рекомендуется немедленное исправление всех P0 перед любым запуском на реальных пользователях.