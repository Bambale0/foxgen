# Архитектура бота генерации медиа (Telegram → VK)

> Полное описание архитектуры, эндпоинтов и бизнес-логики оригинального Telegram-бота **Banano Kling AI** для реализации аналогичного бота под VK (VK Mini Apps / VK API).

---

## 1. Общая архитектура

### 1.1 Схема

```
┌─────────────┐     HTTPS      ┌──────────────┐    127.0.0.1:1888    ┌──────────────────┐
│  Telegram   │ ──────────────▶│    Nginx     │ ────────────────────▶│  aiohttp Server  │
│  (Webhook)  │ ◀──────────────│  (прокси)    │ ◀────────────────────│  (bot/main.py)   │
└─────────────┘               └──────────────┘                      └──────────────────┘
                                                                           │
                                                                    ┌──────┴──────┐
                                                                    │  aiogram DP  │
                                                                    │  Dispatcher  │
                                                                    └──────┬──────┘
                                                                           │
                                              ┌────────────────────────────┼────────────────────────────┐
                                              ▼                            ▼                            ▼
                                   ┌──────────────────┐       ┌──────────────────┐       ┌──────────────────┐
                                   │  Handlers        │       │  Mini App API    │       │  Services        │
                                   │  (FSM-роутеры)   │       │  (REST, JSON)    │       │  (AI провайдеры) │
                                   └──────────────────┘       └──────────────────┘       └──────────────────┘
```

### 1.2 Стек технологий

| Компонент | Технология | Назначение |
|-----------|-----------|------------|
| **Web-сервер** | aiohttp | HTTP-сервер для вебхуков и Mini App API |
| **Telegram SDK** | aiogram 3.x | Обработка команд, FSM-состояния, клавиатуры |
| **FSM Storage** | Redis (основной) / Memory (запасной) | Хранение состояний пользователей |
| **База данных** | PostgreSQL (prod) / SQLite (dev) | Пользователи, транзакции, задачи, лента |
| **Кэш** | Redis | FSM, нотификации Mini App |
| **Прокси** | Nginx | HTTPS-терминация, прокси на aiohttp |
| **Платежи** | YooKassa / Lava.top / CryptoBot / Telegram Stars | Приём оплаты |

> **Для VK:** Telegram SDK → VK API (longpoll / Callback API), aiohttp остаётся, FSM — Redis или Memory.

### 1.3 Модель данных (ключевые таблицы)

**users**
- `telegram_id` (PK) — ID пользователя в мессенджере
- `username`, `first_name`, `last_name` — профиль
- `balance_credits` (float) — баланс кредитов (🍌)
- `referral_code` — уникальный реферальный код
- `referred_by` — ID пригласившего
- `partner_balance_rub` — партнёрский баланс в рублях
- `partner_level` — уровень в партнёрской программе
- `is_banned`, `is_admin` — флаги

**generation_tasks**
- `id` (PK) — внутренний ID задачи
- `telegram_id` — пользователь
- `task_id` — ID задачи у провайдера (API)
- `type` — тип: `'image'` | `'video'`
- `model` — модель: `'banana_pro'`, `'kling_3'`, и т.д.
- `status` — статус: `'pending'` | `'processing'` | `'completed'` | `'failed'`
- `prompt` — промпт пользователя
- `result_url` / `result_urls` — ссылки на результат (JSON)
- `request_data` — полные параметры запроса (JSON)
- `cost` — стоимость в кредитах
- `is_public_feed` — опубликовано в ленте
- `ai_processed` — флаг для AI-ассистента
- `created_at`, `updated_at`

**transactions**
- `id` (PK) — ID транзакции
- `telegram_id` — пользователь
- `type` — `'purchase'` | `'generation'` | `'partner_reward'` | `'promo_bonus'` | `'admin'`
- `amount_credits` — изменение баланса (+/-)
- `amount_rub` — сумма в рублях (для покупок)
- `payment_provider` — провайдер
- `status` — `'pending'` | `'completed'` | `'failed'`
- `created_at`

**referrals**
- `id` (PK)
- `referrer_id` (FK → users)
- `referred_id` (FK → users)
- `referral_code`
- `level` — 1 или 2 (уровень)
- `bonus_credits` — начислено бананов
- `created_at`

**prompts** (библиотека промптов)
- `id`, `author_id`, `title`, `prompt_text`, `category`, `status`, `model`, `reference_url`
- `likes_count`, `use_count`, `created_at`

**saved_references** (сохранённые референсы)
- `id`, `telegram_id`, `kind` (`'image'` | `'video'`), `file_url`, `created_at`

---

## 2. Эндпоинты (HTTP)

### 2.1 Вебхук Telegram

```
POST /telegram/webhook
Content-Type: application/json
```

**Получает:** Update от Telegram (aiogram Update object)
**Отвечает:** `200 OK` (всегда, обработка в фоновой задаче)
**Назначение:** Приём всех обновлений от Telegram

**Логика обработчика:**
1. Прочитать тело запроса (JSON)
2. Создать объект `Update`
3. Запустить фоновую задачу `dp.feed_update(bot, update)`
4. Немедленно вернуть `200 OK`
5. Фоновая задача обрабатывает апдейт через Dispatcher

> **Для VK:** Callback API VK присылает свои объекты событий. Нужен свой парсер, конвертация в унифицированные объекты.

### 2.2 Вебхуки AI провайдеров (Kie.ai / Kling)

```
POST /webhook/kie_ai
POST /webhook/kling
POST /webhook/replicate
POST /webhook/z-image-turbo
POST /webhook/wanx
```

**Назначение:** Приём уведомлений о завершении задач от AI-провайдеров

**Логика:**
1. Прочитать тело (JSON)
2. Извлечь `task_id`, `status` (`success`/`fail`), `resultJson` (URL результата)
3. Найти задачу в БД по `task_id`
4. Если success — скачать результат, отправить пользователю, обновить статус
5. Если fail — отправить пользователю сообщение об ошибке

**Пример тела Kie.ai:**
```json
{
  "code": 200,
  "data": {
    "taskId": "54208dea06f5a4e2ea07be3f149acac7",
    "state": "success",
    "model": "nano-banana-pro",
    "resultJson": "[redacted:url]",
    "creditsConsumed": 6.0,
    "completeTime": 1782651308000
  },
  "msg": "Playground task completed successfully."
}
```

### 2.3 Вебхуки платёжных систем

```
POST /telegram/webhook           — Telegram Stars (через Telegram)
POST /cryptobot/webhook           — CryptoBot
POST /lava/webhook                — Lava.top
POST /yookassa/webhook            — YooKassa
POST /webhook/yookassa            — YooKassa (альтернативный путь)
```

**Назначение:** Получение статусов платежей

**Логика:**
1. Верифицировать подпись/токен
2. Найти транзакцию по `order_id`/`invoice_payload`
3. Если оплата подтверждена — начислить кредиты пользователю
4. Отправить пользователю уведомление

### 2.4 API Mini App (REST)

> Используется Mini App (Next.js frontend) для взаимодействия с ботом.

```
POST /mini-app/api/bootstrap
POST /mini-app/api/upload
POST /mini-app/api/generate
POST /mini-app/api/generation-status
POST /mini-app/api/user/profile
POST /mini-app/api/user/balance
POST /mini-app/api/generations
POST /mini-app/api/generations/delete
POST /mini-app/api/feed
POST /mini-app/api/feed/share
POST /mini-app/api/feed/like
POST /mini-app/api/feed/comment
POST /mini-app/api/prompts
POST /mini-app/api/prompts/create
POST /mini-app/api/prompts/like
POST /mini-app/api/references/list
POST /mini-app/api/references/upload
POST /mini-app/api/references/delete
POST /mini-app/api/referral/stats
POST /mini-app/api/notifications
POST /mini-app/api/subscription/check
POST /mini-app/api/support
```

**Аутентификация:** Telegram Init Data (HMAC SHA256 верификация через `bot_token`)
**Формат ответа:** `{"ok": true/false, "result": {...}, "error": "..."}`

> **Для VK:** VK Mini Apps используют свой механизм авторизации — `VKWebAppGetAuthToken` / `launchParams`. Init Data заменяется на VK Params.

### 2.5 Статические файлы

```
GET /uploads/<path>              — Статические файлы (изображения, видео)
GET /mini-app/                   — Next.js Mini App (статический сайт)
GET /health                      — Health-check (возвращает "OK")
```

### 2.6 Карта маршрутов (aiohttp routes)

| Метод | Путь | Handler | Назначение |
|-------|------|---------|------------|
| POST | `/telegram/webhook` | `telegram_webhook_handler` | Вебхук Telegram |
| POST | `/cryptobot/webhook` | `handle_cryptobot_webhook` | Вебхук CryptoBot |
| POST | `/lava/webhook` | `handle_lava_webhook` | Вебхук Lava.top |
| POST | `/yookassa/webhook` | `handle_yookassa_webhook` | Вебхук YooKassa |
| POST | `/webhook/yookassa` | `handle_yookassa_webhook` | —//— (альтернатива) |
| POST | `/webhook/kling` | `handle_kling_webhook` | Вебхук Kling |
| POST | `/webhook/kie_ai` | `handle_kie_ai_webhook` | Вебхук Kie.ai (основной) |
| POST | `/webhook/replicate` | `handle_kling_webhook` | Вебхук Replicate |
| POST | `/webhook/z-image-turbo` | `handle_kling_webhook` | Вебхук Z-Image-Turbo |
| POST | `/webhook/wanx` | `handle_kling_webhook` | Вебхук Wanx |
| GET | `/uploads/` | `static` | Статические файлы |
| GET | `/health` | `health_check` | Health-check |
| POST | `/mini-app/api/*` | `miniapp handlers` | Mini App API |

---

## 3. Команды бота

### 3.1 Публичные команды

| Команда | Описание |
|---------|----------|
| `/start` | Главное меню + регистрация пользователя |
| `/feed` | Лента работ сообщества |
| `/prompts` | Библиотека промптов |
| `/help` | Помощь и возможности |
| `/ref` | Партнёрская программа |
| `/earn` | Заработок на рефералах |

### 3.2 Система состояний (FSM)

Бот использует FSM (Finite State Machine, aiogram) для пошаговых сценариев.

**GenerationStates — генерация:**
- `waiting_for_input` — ожидание ввода пользователя
- `waiting_for_image` — загрузка фото для генерации
- `waiting_for_video` — загрузка видео
- `waiting_for_video_prompt` — промпт для видео
- `waiting_for_reference_video` — референсное видео
- `waiting_for_motion_character_image` — фото персонажа (motion control)
- `waiting_for_motion_video` — видео движения (motion control)
- `waiting_for_video_start_image` — стартовое изображение
- `confirming_generation` — подтверждение перед запуском
- `selecting_batch_count` — количество изображений
- `uploading_reference_images` — загрузка референсов (до 14)
- `uploading_reference_videos` — загрузка референсных видео
- `confirming_reference_images` — подтверждение референсов
- `selecting_duration`, `selecting_aspect_ratio`, `selecting_quality` — настройки
- `waiting_for_veo_seed`, `waiting_for_kling_cfg_scale` — специфичные параметры

**PaymentStates — платежи:**
- `selecting_package` — выбор пакета
- `waiting_promo_code` — ввод промокода
- `confirming_payment` — подтверждение оплаты
- `waiting_payment` — ожидание оплаты
- `waiting_partner_withdraw_requisites` — реквизиты вывода

**AdminStates — администрирование:**
- `waiting_broadcast_text`, `confirming_broadcast`
- `waiting_user_id`, `waiting_credits_amount`
- `waiting_prompt_id`, `waiting_prompt_reject_reason`
- `waiting_promo_code_value`
- `waiting_ai_request`, `confirming_ai_action`

**BatchGenerationStates:**
- `selecting_mode`, `selecting_preset`, `entering_prompts`
- `uploading_references`, `confirming_batch`

**ImageAnalyzerStates:**
- `waiting_for_photo`, `waiting_for_video_prompt`

> **Для VK:** VK API не имеет встроенной FSM. Нужно реализовать свою — либо на основе Redis/state storage, либо через хранение в БД. aiogram-стиль можно эмулировать.

---

## 4. AI модели и провайдеры

### 4.1 Основной провайдер — Kie.ai

Базовый URL: `https://api.kie.ai`

**Эндпоинты API (REST):**
- `POST /v1/tasks` — создание задачи
- `GET /v1/tasks/{taskId}` — статус задачи
- `POST /v1/upload` — загрузка файла

**Общий формат задачи:**
```json
{
  "model": "nano-banana-pro",
  "param": {
    "type": 2,
    "prompt": "...",
    "aspect_ratio": "1:1",
    "image_input": ["https://..."],
    "nsfw_checker": false
  },
  "webhookUrl": "https://.../webhook/kie_ai"
}
```

**Ответ:**
```json
{
  "code": 200,
  "data": {
    "taskId": "54208dea06f5a4e2ea07be3f149acac7",
    "status": "pending"
  },
  "msg": "success"
}
```

### 4.2 Модели для генерации изображений

| Кнопка в боте | Внутренний ключ | provider_model | Провайдер | Стоимость (🍌) |
|--------------|----------------|----------------|-----------|:---:|
| Nano Banana Pro | `banana_pro` | `nano-banana-pro` | Kie.ai | 2.5-3.5 |
| Nano Banana 2 | `banana_2` | `nano-banana-2` | Kie.ai | 2.5-3.5 |
| GPT Image 2 | `flux_pro` | `gpt-image-2-image-to-image` | Kie.ai (ChatGPT) | 2.5-3.5 |
| Seedream 4.5 | `seedream_edit` | `seedream/4.5-edit` | Kie.ai | 2.5-3.5 |
| Wan 2.7 Image | `wan_27` | `wan/2-7-image-pro` | Kie.ai | 2.5-3.5 |
| Grok Imagine | `grok_imagine_i2i` | `grok-imagine` | Kie.ai (xAI) | 2.5-3.5 |

### 4.3 Модели для генерации видео

| Кнопка в боте | Внутренний ключ | provider_model | Провайдер | Стоимость (🍌) |
|--------------|----------------|----------------|-----------|:---:|
| Kling 3.0 | `v3_pro` | `kling-3` | Kie.ai / PiAPI | от 8 |
| Kling v3 | `v3_std` | `kling-3-std` | Kie.ai / PiAPI | от 5 |
| Kling 2.5 Turbo Pro | `v26_pro` | `kling-2.5-turbo-image-to-video` | Kie.ai / PiAPI | от 8 |
| Kling AI Avatar Std | `avatar_std` | `kling-ai-avatar-standard` | Kie.ai / PiAPI | от 10 |
| Kling AI Avatar Pro | `avatar_pro` | `kling-ai-avatar-pro` | Kie.ai / PiAPI | от 15 |
| Veo 3.1 Quality | `veo3` | `veo/3.1-quality` | Kie.ai / Google | от 10 |
| Veo 3.1 Fast | `veo3_fast` | `veo/3.1-fast` | Kie.ai / Google | от 8 |
| Veo 3.1 Lite | `veo3_lite` | `veo/3.1-lite` | Kie.ai / Google | от 5 |
| Gemini Omni Video | `omni_video` | — | Gemini API | от 10 |
| Gemini Omni Audio | `omni_audio` | — | Gemini API | от 5 |
| Grok Video | `grok_video` | `grok-video` | Kie.ai (xAI) | от 8 |
| Kling Glow | `glow` | — | Упрощённый | от 5 |
| Seedance | `seedance` | — | Kie.ai | от 5 |

### 4.4 Параметры генераций

**Для изображений:**
- `prompt` — текстовое описание
- `aspect_ratio` — `"1:1"`, `"9:16"`, `"16:9"`, `"3:2"`, `"2:3"`, `"3:4"`, `"4:3"`
- `image_input` — массив URL референсных изображений (для i2i)
- `quality` — `"2K"` (2.5🍌) или `"4K"` (3.5🍌)
- `nsfw_checker` — `true/false`
- `user_prompt` / `original_prompt` — дополнительный промпт

**Для видео:**
- `prompt` — текстовое описание
- `duration` — `5` или `10` секунд
- `aspect_ratio` — `"1:1"`, `"9:16"`, `"16:9"`
- `image_input` / `video_input` — URL исходных медиа
- `audio_input` — URL аудио (для аватаров)
- `negative_prompt` — что исключить
- `cfg_scale` — scale (для Kling 2.5 Turbo)
- `resolution` — `"480p"`, `"720p"` (зависит от модели)

---

## 5. Система оплаты и кредитов

### 5.1 Пакеты кредитов

| Пакет | Кредиты (🍌) | Цена (₽) | Бонус (🍌) |
|-------|:---:|:---:|:---:|
| Мини | 15 | 65 | — |
| Старт | 25 | 90 | — |
| Оптимальный | 50 | 160 | — |
| Про | 100 | 310 | — |
| Студия | 200 | 605 | — |
| Бизнес | 500 | 1500 | — |
| Максимум | 1000 | 2900 | — |

**Промо-бонусы:** при покупке через промокод добавляются бонусные кредиты (5/10/15/20/50).

### 5.2 Платежные провайдеры

| Провайдер | Приоритет | Тип |
|-----------|-----------|-----|
| **Lava.top** | Основной | Крипто-рубли, карты РФ |
| CryptoBot | Резервный | USDT, криптовалюты |
| YooKassa | Легаси | Карты, SBP |
| Telegram Stars | Альтернатива | Внутренняя валюта Telegram |

### 5.3 Партнёрская программа

- **Уровень 1:** 30% от покупок рефералов 1-го уровня
- **Уровень 2:** 7% от покупок рефералов 2-го уровня
- **Бонус новому:** 15 🍌 при регистрации по реферальной ссылке
- **Бонус пригласившему:** 3 🍌 за каждую регистрацию
- **Минимальный вывод:** 1000 ₽

---

## 6. Компоненты для репликации под VK

### 6.1 Что нужно заменить

| Компонент Telegram | Аналог для VK |
|-------------------|---------------|
| aiogram 3.x | VK API (vk-api-python) или кастомная обёртка |
| Telegram Bot API | VK Callback API + Longpoll API |
| aiogram FSM | Собственная FSM (Redis/B-D) |
| Telegram Init Data | VK Launch Params + Access Token |
| Telegram Mini App | VK Mini Apps (iframe) |
| Telegram Webhook | VK Callback API |
| Telegram Stars | VK Pay / VK Donut |
| Telegram Bot Token | VK Group Token + Confirmation Code |

### 6.2 Что остаётся без изменений

| Компонент | Причина |
|-----------|---------|
| aiohttp web server | Универсальный HTTP-сервер |
| Redis FSM storage | Универсально |
| PostgreSQL / SQLite | Универсально |
| AI сервисы (Kie.ai, Gemini) | Работают через REST API |
| Nginx | Универсальный прокси |
| Платежные системы (Lava, CryptoBot, YooKassa) | Работают через REST API |

### 6.3 Рекомендуемая архитектура для VK

```
┌──────────────┐     Callback API     ┌──────────────┐    127.0.0.1:1888    ┌──────────────────┐
│   VK Server  │ ◀───────────────────│    Nginx      │ ────────────────────▶│  aiohttp Server  │
│  (Longpoll)  │ ───────────────────▶│  (прокси)     │ ◀────────────────────│  (бот VK)         │
└──────────────┘                     └──────────────┘                      └──────────────────┘
                                                                                    │
                                                                             ┌──────┴──────┐
                                                                             │   Handler   │
                                                                             │   (VK API)  │
                                                                             └──────┬──────┘
                                                                                    │
                                                    ┌───────────────────────────────┼──────────────────────────────┐
                                                    ▼                               ▼                              ▼
                                         ┌────────────────────┐          ┌────────────────────┐       ┌────────────────────┐
                                         │ VK Event Handlers  │          │ VK Mini Apps API   │       │  Services          │
                                         │ (FSM-аналог)       │          │ (REST, JSON)       │       │  (AI провайдеры)   │
                                         └────────────────────┘          └────────────────────┘       └────────────────────┘
```

### 6.4 Особенности VK Mini Apps

1. **Авторизация:** `VKWebAppGetAuthToken` → token → проверка на сервере через VK API
2. **Инициализация:** `vkBridge.send('VKWebAppInit')` → получение `launchParams`
3. **Файлы:** Загрузка через VK API `photos.getUploadServer` / `docs.getUploadServer`
4. **Платежи:** VK Pay — `VKWebAppOpenPayForm` с параметрами `amount`, `merchant`
5. **Callback кнопки:** VK не поддерживает Inline-кнопки как Telegram — используйте VK Mini Apps или клавиатуру бота

### 6.5 Ключевые VK API методы

| Назначение | VK API метод |
|-----------|-------------|
| Отправить сообщение | `messages.send` |
| Отправить фото | `messages.send` с `attachment=photo{id}` |
| Клавиатура | `keyboard` (JSON) в `messages.send` |
| Загрузить фото | `photos.getMessagesUploadServer` → upload → `photos.saveMessagesPhoto` |
| Загрузить файл | `docs.getMessagesUploadServer` → upload |
| Проверить подписку | `groups.isMember` (для подписки на группу) |
| Информация о пользователе | `users.get` |
| Longpoll | `groups.getLongPollServer` → `groups.getLongPollUpdates` |
| Callback API | Настройка сервера в управлении сообществом |

---

## 7. Порядок запуска и деплой

### 7.1 Требования к окружению

- Python 3.12+
- Redis 6+
- PostgreSQL 15+ (или SQLite для разработки)
- Nginx (для продакшена)
- systemd (опционально)

### 7.2 Переменные окружения

```env
# Telegram / VK
BOT_TOKEN=                        # Telegram Bot Token / VK Group Token
VK_GROUP_ID=                      # ID группы VK
VK_CONFIRMATION_CODE=             # Код подтверждения VK Callback API
VK_SECRET_KEY=                    # Секретный ключ VK Callback API
VK_API_VERSION=5.199              # Версия VK API

# Webhook
WEBHOOK_HOST=https://example.com
WEBHOOK_PATH=/telegram/webhook    # /vk/callback для VK
WEBHOOK_PORT=1888
WEBHOOK_BIND_HOST=127.0.0.1

# Database
DATABASE_URL=postgresql://user:pass@localhost:5432/banano_kling

# Redis
REDIS_URL=redis://127.0.0.1:6379/0

# AI Providers
KIE_AI_API_KEY=...
GEMINI_API_KEY=...
NANOBANANA_API_KEY=...

# Payments
PAYMENT_PROVIDER=lava
LAVA_API_KEY=...
CRYPTOBOT_API_TOKEN=...
YOOKASSA_SHOP_ID=...
YOOKASSA_SECRET_KEY=...

# Admin
ADMIN_IDS=123456,789012
```

### 7.3 Установка

```bash
# 1. Клонировать репозиторий
git clone <repo>
cd banano_kling

# 2. Виртуальное окружение
python3 -m venv venv
source venv/bin/activate
pip install -U pip setuptools wheel
pip install -r requirements.txt

# 3. Настроить .env
cp .env.example .env
# Отредактировать .env

# 4. База данных
# Для SQLite — создаётся автоматически
# Для PostgreSQL — создать БД и пользователя

# 5. Запуск
./start.sh
```

### 7.4 Nginx конфигурация (пример)

```nginx
server {
    listen 443 ssl http2;
    server_name example.com;

    ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

    client_max_body_size 60m;

    location /telegram/webhook {
        proxy_pass http://127.0.0.1:1888;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        proxy_request_buffering off;
    }

    location /webhook/ {
        proxy_pass http://127.0.0.1:1888;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /mini-app/ {
        proxy_pass http://127.0.0.1:1888;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        proxy_pass http://127.0.0.1:1888;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /uploads/ {
        proxy_pass http://127.0.0.1:1888;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
    }

    location /health {
        proxy_pass http://127.0.0.1:1888;
    }
}
```

### 7.5 systemd-сервис

```ini
[Unit]
Description=banano_kling AI Bot
After=network.target redis.service postgresql.service

[Service]
Type=simple
WorkingDirectory=/root/tanya/banano_kling
ExecStart=/root/tanya/banano_kling/venv/bin/python -m bot.main
Restart=on-failure
RestartSec=5
User=root
PIDFile=/root/tanya/banano_kling/bot.pid

[Install]
WantedBy=multi-user.target
```

---

## 8. Структура проекта (для репликации)

```
bot/
├── __init__.py
├── main.py                  # Точка входа, webhook handlers, middleware
├── config.py                # Конфигурация из .env
├── env.py                   # Загрузка .env файлов
├── database.py              # Все SQL-запросы, ORM-слой
├── db.py                    # Подключение к БД
├── keyboards.py             # Inline-клавиатуры / кнопки
├── states.py                # FSM-состояния
├── miniapp.py               # Mini App API (REST handlers)
├── miniapp_links.py         # Формирование ссылок Mini App
├── payment_utils.py         # Утилиты платежей
├── banana_packages.py       # Пакеты кредитов
├── pricing_final.py         # Цены моделей
├── quality_pricing.py       # Стоимость качества (2K/4K)
├── video_reference_policy.py # Политика видео-референсов
├── postgres_aiosqlite.py    # Адаптер PostgreSQL ↔ SQLite
│
├── handlers/
│   ├── __init__.py          # Экспорт роутеров
│   ├── common.py            # Команды /start, /help, /feed, /prompts
│   ├── generation.py        # Основные сценарии фото/видео
│   ├── admin.py             # Админ-панель
│   ├── payments.py          # Платежи и вебхуки
│   ├── batch_generation.py  # Пакетная генерация
│   └── image_analyzer.py    # Анализ изображений в промпт
│
├── services/
│   ├── __init__.py
│   ├── preset_manager.py    # Менеджер пресетов
│   ├── redis_service.py     # Подключение к Redis
│   ├── subscription_service.py   # Проверка подписки на канал
│   ├── crypto_service.py    # CryptoBot API
│   ├── lava_service.py      # Lava.top API
│   ├── yookassa_service.py  # YooKassa API
│   ├── kling_service.py     # Kling / Kie.ai tasks
│   ├── nano_banana_pro_service.py  # Nano Banana Pro API
│   ├── nano_banana_2_service.py    # Nano Banana 2 API
│   ├── gpt_image_service.py # GPT Image 2 API
│   ├── seedream_service.py  # Seedream API
│   ├── gemini_service.py    # Gemini API
│   ├── gemini_omni_service.py # Gemini Omni Video/Audio
│   ├── grok_service.py      # Grok API
│   ├── veo_service.py       # Veo API
│   ├── wan27_service.py     # Wan 2.7 API
│   ├── seedance_service.py  # Seedance API
│   ├── batch_service.py     # Пакетная генерация
│   ├── ai_assistant_service.py   # AI-помощник
│   ├── admin_ai_service.py  # AI-админ
│   ├── photo_prompt_service.py   # Промпт по фото
│   ├── video_prompt_service.py   # Промпт по видео
│   ├── image_analyzer_service.py # Анализ изображений
│   ├── media_input_utils.py # Утилиты загрузки медиа
│   ├── reference_storage_service.py # Хранение референсов
│   └── kie_file_upload_service.py   # Загрузка файлов в Kie.ai
│
├── utils/
│   ├── __init__.py
│   ├── help_texts.py        # Тексты помощи
│   ├── user_facing_errors.py # Человеческие ошибки
│   ├── validators.py        # Валидация ввода
│   └── ai_assistant_instructions.json
│
├── data/
│   ├── presets.json         # Пресеты моделей
│   └── price.json           # Цены (легаси)
│
├── static/uploads/          # Загруженные пользователями файлы
│
├── tests/                   # Тесты
├── scripts/                 # Скрипты деплоя
├── frontend/                # Next.js Mini App
│
├── .env                     # Переменные окружения
├── requirements.txt         # Зависимости
├── start.sh                 # Скрипт запуска
├── stop.sh                  # Скрипт остановки
└── restart.sh               # Скрипт перезапуска
```

---

## 9. Ключевые бизнес-процессы

### 9.1 Генерация изображения

```
Пользователь → /start → выбор "Создать фото"
  → Выбор модели (Nano Banana Pro / GPT Image 2 / Seedream / ...)
  → [Опционально] Загрузка референсных изображений (до 14)
  → Выбор соотношения сторон (1:1, 9:16, 16:9, ...)
  → Выбор качества (2K=2.5🍌 / 4K=3.5🍌)
  → Ввод текстового промпта
  → Подтверждение → списание кредитов
  → Создание задачи у провайдера (Kie.ai)
  → Ожидание вебхука от провайдера
  → Получение результата → отправка пользователю
  → [Опционально] Публикация в ленту сообщества
```

### 9.2 Генерация видео

```
Пользователь → "Создать видео"
  → Выбор модели (Kling 3.0 / Veo 3.1 / Kling Glow / ...)
  → Выбор типа генерации:
     • Текст → Видео (только промпт)
     • Фото + Текст → Видео (изображение + промпт)
     • Видео + Текст → Видео (видео-референс + промпт)
     • Аватар + Аудио → Видео (фото + аудио + промпт)
  → [Опционально] Загрузка медиа-файлов
  → Выбор длительности (5с / 10с)
  → Выбор соотношения сторон
  → Ввод промпта
  → [Для Kling 2.5 Turbo] Negative prompt + CFG scale
  → Подтверждение → списание кредитов
  → Создание задачи у провайдера
  → Ожидание вебхука → отправка результата
```

### 9.3 Покупка кредитов

```
Пользователь → "Баланс" / "Пополнить"
  → Выбор пакета (Мини / Старт / Оптимальный / Про / ...)
  → [Опционально] Ввод промокода
  → Выбор способа оплаты (Lava / CryptoBot / YooKassa / Telegram Stars)
  → Перенаправление на платёжную форму
  → Ожидание вебхука от платёжной системы
  → Начисление кредитов на баланс
  → Уведомление пользователя
```

### 9.4 Реферальная программа

```
Пользователь → /ref
  → Просмотр реферальной ссылки
  → Просмотр статистики (рефералы, заработок)
  → [Опционально] Вывод средств (реквизиты + сумма)
  → [Опционально] Обмен партнёрского баланса в кредиты

Новый пользователь переходит по ссылке → /start ref_CODE
  → Регистрация пользователя
  → Начисление 15🍌 новому пользователю
  → Начисление 3🍌 пригласившему
  → Если реферал покупает пакет → 30% пригласившему (1 уровень)
  → Если реферал привёл ещё кого-то → 7% (2 уровень)
```

---

## 10. Зависимости (requirements.txt)

```
aiohttp>=3.10
aiogram>=3.13
aiosqlite>=0.20
redis>=5.2
python-dotenv>=1.1
yookassa>=3.10
cryptpay>=0.5
requests>=2.32
Pillow>=11.1
Pygments>=2.19
```

---

## 11. Обработка ошибок

### 11.1 Глобальные ошибки

- `TelegramBadRequest: chat not found` — пользователь удалил чат — игнорировать
- `TelegramBadRequest: bot was blocked by user` — пользователь заблокировал — игнорировать
- `TelegramBadRequest: user is deactivated` — пользователь удалён — игнорировать
- `TelegramBadRequest: message is not modified` — то же сообщение — игнорировать
- `TelegramBadRequest: query is too old` — устаревший callback — игнорировать
- Остальное — логировать и возвращать 200 (чтобы Telegram не повторял)

### 11.2 Ошибки AI провайдеров

- Content moderation (Google/OpenAI policy) — показывать пользователю понятное сообщение
- Timeout при загрузке референсов — повтор через fallback (requests)
- Aspect ratio не поддерживается моделью — предупреждать пользователя до старта
- Недостаточно кредитов — показывать баланс и предложение пополнить

---

> **Дата:** 28 июня 2026 г.
> **Оригинальный проект:** Banano Kling AI Bot (Telegram)
> **Назначение:** Документация для репликации бота под VK
