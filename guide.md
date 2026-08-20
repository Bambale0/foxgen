# Prompt Library + Feed Integration Guide

Эта инструкция описывает, как в APIX устроены публичная лента генераций и библиотека промптов, и как агенту разработки перенести такую же механику в другой проект. Документ написан как техническое задание для внедрения: сначала зафиксируй текущую архитектуру, затем реализуй слои в указанном порядке.

## 1. Что именно переносим

В APIX есть две связанные, но разные сущности:

- **Библиотека промптов**: модерируемый каталог готовых идей. Хранится в таблице `user_prompts`, показывается только после `approved + is_public`, поддерживает теги, категории, лайки, счётчик использований, AI/ручную модерацию и награды автору.
- **Лента работ**: публичная галерея готовых генераций. Хранится в таблице `generations` через флаг `is_public_feed`. Показывает результат, автора, модель, лайки, репосты, число ремиксов и позволяет запустить повтор/ремикс.

Важный нюанс текущей реализации: `generations.is_prompt_library` не создаёт карточку в `user_prompts`. Это флаг "сохранить промпт результата" на самой генерации, который используется в истории/кнопках. Если в новом проекте нужно, чтобы кнопка "в библиотеку" реально публиковала промпт в общем каталоге, добавь отдельную материализацию `Generation -> UserPrompt` и модерацию.

## 2. Карта текущих файлов

Основные backend-файлы:

- `db/models.py`: модели `Generation`, `UserPrompt`, `PromptLike`, enum `PromptCategory`, `PromptStatus`, `ImageGenerationAction`.
- `db/prompt_repository.py`: CRUD и бизнес-логика библиотеки промптов.
- `db/repository.py`: CRUD генераций, лента, публикация, лайки/шеры, feed-remix royalties.
- `api/miniapp_routes.py`: основной mini app API под `/api/v1/*`.
- `api/web/feed.py`, `api/web/prompts.py`, `api/web/schemas.py`: standalone web API под `/api/web/*`.
- `api/realtime.py`: WebSocket-события генераций, включая скрытие промпта у feed-remix.
- `api/public_files.py`: публичные URL для превью и референсов.
- `api/assistant_service.py`: AI-модерация пользовательских промптов.

Telegram-слой:

- `bot/handlers/marketplace.py`: каталог промптов, добавление, AI/ручная модерация, лайки, использование.
- `bot/handlers/feed.py`: лента, топ дня, лайк, шаринг, повтор, ремикс, публикация.
- `bot/handlers/image_gen.py`: запуск генераций из сессии и запрет публикации производных из ленты.
- `bot/keyboards/prompts.py`, `bot/keyboards/feed.py`: inline-кнопки.
- `bot/states/prompt.py`, `bot/states/__init__.py`: FSM для загрузки/модерации и применения промптов.
- `bot/utils/deep_links.py`: deep links вида `ref_CODE__feed_ID` и `ref_CODE__prompt_ID`.

Frontend:

- `webapp/src/main.jsx`: Telegram Mini App. Компоненты `PromptFeed`, `Prompts`, `Feed`, `FeedCard`, `Studio`, `GenerationResultCard`, `GenShareButtons`.
- `webapp/src/style.css`: карточки библиотеки, карточки ленты, кнопки действий.
- `landing/js/riot-site.js`: standalone web site: загрузка `/api/web/feed`, `/api/web/prompts`, применение промпта в студию, feed remix.
- `landing/css/riot-site.css`: стили standalone web site.

Миграции и seed:

- `db/migrations/versions/021_user_prompts_if_missing.py`: страховочная миграция создания `user_prompts`.
- `006_prompt_library_showcase.py`: поля витрины промптов: `preview_url`, `model`, `tags`, `likes`, `is_public`.
- `008_generation_feed_metrics.py`: `is_public_feed`, `likes_count`, `shares_count`.
- `010_prompt_likes_unique_per_user.py`: таблица `prompt_likes` с уникальностью `(user_id, prompt_id)`.
- `012_feed_remix_royalty.py`: `source_feed_gen_id`, `is_prompt_library`.
- `017_prompt_ai_moderation_audit.py`: audit-поля AI-модерации.
- `019_generation_result_urls.py`: несколько URL результата.
- `022_indexes_hot_fields.py`: индексы для ленты и GIN по `user_prompts.tags`.
- `scripts/seed_prompt_showcase.py`: демо-наполнение промптов и публичной ленты.

## 3. Модель данных

### 3.1. `user_prompts`

Нужна отдельная таблица для библиотеки промптов:

- `id`
- `author_id -> users.id`
- `title`, max 60 в модели APIX
- `description`, max 200 в модели APIX
- `category`: `art | business | marketing | photo | other`
- `prompt_text`
- `preview_url`: картинка карточки
- `model`: рекомендуемая модель, nullable
- `tags`: массив нормализованных тегов
- `likes`: денормализованный счётчик
- `uses_count`: счётчик применений
- `is_public`: видимость
- `status`: `pending | approved | rejected | deactivated`
- `reject_reason`
- `ai_moderation_decision`, `ai_moderation_risk`, `ai_moderation_reason`, `ai_moderation_recommendation`, `ai_moderation_raw`, `ai_moderated_at`
- `created_at`

Инвариант: публичный каталог выбирает только `status == approved AND is_public == true`.

### 3.2. `prompt_likes`

Нужна отдельная таблица лайков промптов:

- `id`
- `user_id -> users.id`
- `prompt_id -> user_prompts.id`
- `created_at`
- unique constraint `uq_prompt_likes_user_prompt(user_id, prompt_id)`

Лайк идемпотентный: повторный лайк не увеличивает `user_prompts.likes`.

### 3.3. `generations`

Для ленты расширь таблицу генераций:

- `result_url`: основной результат
- `result_urls`: JSON-список результатов, если модель вернула несколько изображений
- `is_public_feed`: опубликовано в ленте
- `is_prompt_library`: промпт результата сохранён в истории пользователя
- `source_feed_gen_id -> generations.id`: генерация создана как ремикс публичного feed-поста
- `parent_generation_id -> generations.id`: локальная связь варианта/ремикса
- `action_type`: `initial | remix | repeat | reference_update | animate`
- `likes_count`, `shares_count`
- `credits_spent`, `status`, `finished_at`

Инвариант: карточка ленты выбирается только если:

- `gen_type == image`
- `status == done`
- `result_url IS NOT NULL`
- `is_public_feed == true`

Инвариант приватности: если `source_feed_gen_id` заполнен, это производная от чужой ленты. Клиенту нельзя возвращать исходный prompt, нельзя копировать prompt и нельзя публиковать результат обратно в ленту/библиотеку.

### 3.4. `image_sessions`

Лента подтягивает metadata из `image_sessions`:

- `aspect_ratio`
- `quality`
- `count`
- `reference_url`
- `base_prompt`
- `last_prompt`
- `last_result_url`

Это позволяет показывать формат, использовать result как reference и восстанавливать настройки для повтора.

## 4. Репозитории и бизнес-логика

### 4.1. Библиотека промптов

Реализуй модуль, аналогичный `db/prompt_repository.py`.

Обязательные функции:

- `infer_tags(prompt_text) -> list[str]`: определяет коллекционные теги по ключевым словам.
- `infer_category(prompt_text, tags) -> PromptCategory`: грубая категоризация.
- `derive_title(prompt_text)`, `derive_description(prompt_text)`: безопасные fallback-тексты.
- `create_prompt(...)`: создаёт prompt в `pending`.
- `get_prompt_by_id(prompt_id)`.
- `count_active_prompts_by_author(author_id)`: лимит активных `pending/approved`.
- `get_top_prompts(limit)`: сортировка по `uses_count`, затем `created_at`.
- `get_popular_prompts(limit)`: сортировка по `likes`, затем `uses_count`, затем `created_at`.
- `get_prompts_by_tag(tag, limit)`: `tags.any(tag)`.
- `get_approved_prompts(category, offset, limit)`.
- `count_approved_prompts(category)`.
- `like_prompt(prompt_id, user_id)`: вставка в `prompt_likes` через upsert/do-nothing и увеличение счётчика только при новой вставке.
- `use_prompt(prompt_id, user_id, credits_spent=None)`: проверяет доступность, увеличивает `uses_count`, начисляет награды.
- `approve_prompt`, `reject_prompt`, `deactivate_prompt`.
- `get_author_prompts(author_id)`, `get_author_total_uses(author_id)`.
- `set_ai_moderation_result(...)`.

Текущие константы APIX:

- `MAX_ACTIVE_PROMPTS_PER_USER = 5`
- `PROMPT_AUTHOR_SHARE = 0.30`
- `PROMPT_REF_L2_SHARE = 0.07`
- `PROMPT_REF_L3_SHARE = 0.03`
- `TOP_PROMPTS_LIMIT = 10`

Если переносишь без кредитной экономики, оставь `use_prompt` только со счётчиком, а награды вынеси за feature flag.

### 4.2. Лента генераций

Реализуй функции, аналогичные блокам `db/repository.py`:

- `create_generation(..., source_feed_gen_id=None, parent_generation_id=None, action_type=None)`.
- `finish_generation(gen_id, result_url, result_urls=None)`: переводит в `done`, сохраняет `result_urls`, публикует realtime-событие и начисляет feed-remix royalty.
- `get_feed_generations(limit)`.
- `get_user_feed_generations(user_id, limit)`.
- `get_top_day_generations(limit)`.
- `get_feed_generation_card(gen_id)`.
- `get_public_feed_generation(gen_id)`.
- `share_to_feed(gen_id, user_id)`.
- `remove_from_feed(gen_id, user_id)`.
- `share_to_library(gen_id, user_id)`.
- `remove_from_library(gen_id, user_id)`.
- `like_feed_generation(gen_id)`.
- `increment_feed_share(gen_id)`.

`share_to_feed` и `share_to_library` должны блокировать производные:

```python
Generation.source_feed_gen_id.is_(None)
```

Иначе пользователь сможет открыть чужой hidden prompt через публикацию результата.

### 4.3. Feed score

APIX считает score карточки так:

```python
generation_count = 1 + remix_count
score = likes_count * 1 + remix_count * 3 + shares_count * 5 + generation_count * 4
if created_at within last 2 hours:
    score *= 1.5
```

`remix_count` считается по `parent_generation_id` среди done-генераций. Карточки сначала берутся с запасом из БД, затем сортируются в памяти по score.

### 4.4. Feed remix royalty

Если генерация завершилась и у неё есть `source_feed_gen_id`, APIX начисляет автору исходного feed-поста 5% от `credits_spent`.

Правила:

- не начислять, если source не найден;
- не начислять self-remix;
- не начислять при `credits_spent <= 0`;
- округлять до 0.001 кредита.

Если в новом проекте нет ledger/credits, сохрани событие в отдельной таблице `feed_remix_events` или отключи этот блок.

## 5. API-контракты

### 5.1. Mini App API

В APIX актуальный mini app API смонтирован под `/api/v1/*` из `api/miniapp_routes.py`. В старых документах/скриптах может встречаться `/api/webapp/*`; не копируй старый префикс без проверки `main.py`.

Лента:

- `GET /api/v1/feed?source=recent|top_day|top&limit=40`
- `GET /api/v1/me/feed?limit=200`
- `POST /api/v1/generations/{gen_id}/share`
- `POST /api/v1/feed/{gen_id}/remove`
- `POST /api/v1/feed/{gen_id}/like`
- `POST /api/v1/feed/{gen_id}/remix`
- `GET /api/v1/feed/{gen_id}/link`
- `POST /api/v1/generations/{gen_id}/share-library`
- `POST /api/v1/generations/{gen_id}/remove-library`
- `POST /api/v1/generations/{gen_id}/publish`

Библиотека:

- `GET /api/v1/prompts?source=catalog|top|popular|tag|collections&tag=cinematic&page=1&limit=40`
- `GET /api/v1/prompts/my`
- `GET /api/v1/prompts/{prompt_id}`
- `POST /api/v1/prompts/{prompt_id}/like`
- `GET /api/v1/prompts/{prompt_id}/link`
- `POST /api/v1/prompts/{prompt_id}/use`
- `POST /api/v1/prompts/{prompt_id}/deactivate`
- `POST /api/v1/prompts`

Генерация из библиотеки:

- `POST /api/v1/generate/image` принимает `prompt_id`.
- Сервер сам загружает `UserPrompt`, проверяет `approved + is_public` и заменяет пользовательский `prompt` на `prompt_source.prompt_text`.
- После запуска вызывает `use_prompt(..., credits_spent=model_cost.credits)`.

Ремикс из ленты:

- `POST /api/v1/feed/{gen_id}/remix` принимает выбранную пользователем модель и параметры.
- Сервер берёт `source.prompt` из публичной генерации.
- Клиенту возвращается `GenerationOut` с:

```json
{
  "prompt": "",
  "prompt_hidden": true,
  "prompt_actions_allowed": false
}
```

### 5.2. DTO для mini app

Feed card:

```json
{
  "id": 88,
  "model": "nano-banana-pro",
  "gen_type": "image",
  "result_url": "https://...",
  "result_urls": ["https://..."],
  "likes_count": 2,
  "shares_count": 1,
  "aspect_ratio": "9:16",
  "author": "username",
  "author_photo_url": "https://...",
  "is_mine": false,
  "remixes": 5,
  "score": 42.0
}
```

Prompt card:

```json
{
  "id": 7,
  "title": "Glossy card",
  "description": "make it glossy",
  "prompt_text": "full prompt",
  "category": "photo",
  "tags": ["photo", "realism"],
  "uses_count": 3,
  "likes": 2,
  "preview_url": "https://...",
  "model": "nano-banana-pro",
  "author_id": 2,
  "status": "approved",
  "reject_reason": null,
  "ai_moderation_decision": "approve",
  "created_at": "..."
}
```

Generation out:

```json
{
  "id": 701,
  "model": "nano-banana-pro",
  "gen_type": "image",
  "prompt": "",
  "prompt_hidden": true,
  "prompt_actions_allowed": false,
  "status": "processing",
  "result_url": null,
  "result_urls": [],
  "credits_spent": 4,
  "is_public_feed": false,
  "is_prompt_library": false,
  "created_at": "..."
}
```

### 5.3. Standalone web API

В APIX есть отдельный слой `/api/web/*` для сайта из `landing/`.

Лента:

- `GET /api/web/feed?source=feed|recent|top|top_day&limit=40`
- `GET /api/web/feed/top`
- `POST /api/web/feed/{generation_id}/like`
- `POST /api/web/feed/{generation_id}/share`

Промпты:

- `GET /api/web/prompts?source=catalog|top|trending|popular|best|tag|my`
- `GET /api/web/prompts/{prompt_id}`
- `POST /api/web/prompts/{prompt_id}/like`
- `POST /api/web/prompts/{prompt_id}/use`
- `POST /api/web/prompts`
- `GET /api/web/admin/prompts?status=pending`
- `POST /api/web/admin/prompts/{prompt_id}/approve|reject|deactivate`

Отличие: `/api/web/*` возвращает enveloped response:

```json
{ "ok": true, "data": ... }
```

Mini app `/api/v1/*` возвращает данные напрямую.

## 6. Скрытие чужого prompt

Это самая важная часть безопасности.

Правило:

```python
def generation_prompt_hidden(gen):
    return bool(gen.source_feed_gen_id)
```

Применить везде:

- `api/miniapp_routes.py::_gen_out`
- `api/realtime.py::generation_event_payload`
- frontend helpers `generationPromptHidden`, `generationPromptActionsAllowed`
- Telegram-кнопки публикации: `allow_publish = not bool(source_feed_gen_id)`
- backend endpoints `share_to_feed`, `share_to_library`, `publish` должны повторно проверять `source_feed_gen_id is None`

Нельзя полагаться только на frontend. Даже если кнопка скрыта, backend должен вернуть 403.

## 7. Публикация и пользовательские сценарии

### 7.1. Опубликовать генерацию в ленту

1. Пользователь получает `done` image generation.
2. UI показывает кнопку `В ленту`.
3. Клиент вызывает `POST /api/v1/generations/{id}/share`.
4. Backend проверяет:
   - генерация существует;
   - принадлежит пользователю;
   - `status == done`;
   - `result_url IS NOT NULL`;
   - `source_feed_gen_id IS NULL`.
5. Backend ставит `is_public_feed = true`.
6. Возвращает deep link на feed-пост.

### 7.2. Сохранить prompt результата

1. UI вызывает `POST /api/v1/generations/{id}/share-library`.
2. Backend проверяет те же условия и ставит `is_prompt_library = true`.
3. В APIX это не создаёт `UserPrompt`. Если нужен публичный каталог из результатов, создай `UserPrompt` со статусом `pending` и `preview_url = generation.result_url`.

### 7.3. Использовать prompt из библиотеки

1. Пользователь открывает `GET /prompts`.
2. Нажимает "В студию".
3. UI ставит `selectedPrompt = { id, title }` и заполняет textarea `prompt_text`.
4. При генерации отправляет `prompt_id`.
5. Backend игнорирует текст от клиента и использует `UserPrompt.prompt_text` из БД.
6. После списания credits и запуска генерации вызывает `use_prompt`.

### 7.4. Ремикс из ленты

1. Пользователь нажимает "Повтор/Ремикс" на feed-карточке.
2. UI передаёт только `feed_gen_id`, модель и параметры.
3. Backend берёт `source.prompt` сам.
4. Для image-mode использует `source.result_url` как reference, если пользователь не дал свой reference.
5. Создаёт generation с:
   - `prompt = source.prompt`
   - `source_feed_gen_id = source.id`
   - `parent_generation_id = source.id` для image-ремиксов
   - `action_type = remix`
6. Возвращает `prompt_hidden = true`.
7. На `finish_generation` начисляет автору исходного поста feed-remix royalty.

## 8. Telegram-бот

### 8.1. Библиотека промптов

Сценарии из `bot/handlers/marketplace.py`:

- `/prompts` или `menu:prompts`: главная библиотеки.
- `prompts:trending`, `prompts:top_today`, `prompts:best`, `prompts:collection:{tag}:0`: подборки.
- `prompt_like:{prompt_id}:{source}:{index}`: лайк с защитой от дубля.
- `prompt_share:{prompt_id}`: deep link.
- `prompt_use:{prompt_id}`: выбор модели, затем опциональный reference, затем запуск.
- `prompt_remix:{prompt_id}`: генерация с preview как reference, если модель поддерживает img2img.
- `prompts:add`: загрузка preview -> текст prompt -> confirm.
- AI moderation:
  - `approve`: сразу публикует;
  - `reject`: отклоняет;
  - `manual_review`: отправляет админам inline-кнопки.
- `prompts:my`: список своих prompt с статусами.
- `prompts:deactivate:{prompt_id}`: скрыть свой prompt.

FSM:

- `PromptUploadFSM.upload_image`
- `PromptUploadFSM.prompt_text`
- `PromptUploadFSM.confirm`
- `PromptUseFSM.model_select`
- `PromptUseFSM.reference_upload`
- `PromptModerateFSM.reject_reason`

### 8.2. Лента

Сценарии из `bot/handlers/feed.py`:

- `/feed` или `menu:feed`: публичная лента.
- `feed:top`: топ дня.
- `feed:next:{source}:{index}`: навигация.
- `feed:like:{gen_id}:{source}:{index}`: лайк.
- `feed:share:{gen_id}`: deep link.
- `feed:use:{gen_id}`: повторить prompt через выбор модели.
- `feed:again:{gen_id}`: ещё вариант своей генерации с сохранением настроек.
- `feed:remix:{gen_id}`: создать image session с `reference_url = gen.result_url`, `source_feed_gen_id = gen.id`.
- `feed:publish:{gen_id}`: поставить `is_public_feed = true` и `is_prompt_library = true`, если результат не производный.
- `feed:remove:{gen_id}`: убрать свой пост из ленты.

Кнопки под готовой генерацией (`bot/keyboards/feed.py::get_generation_result_keyboard`):

- `Ремикс`
- `В библиотеку`
- `Ещё вариант`
- `Меню`

Если generation создана из feed remix, кнопка публикации должна быть недоступна.

### 8.3. Deep links

Формат:

- referral only: `CODE`
- feed target: `ref_CODE__feed_88`
- prompt target: `ref_CODE__prompt_7`

На `/start`:

- если `target_kind == feed`, открыть конкретный feed-card;
- если `target_kind == prompt`, открыть конкретный prompt-card;
- при этом referral code продолжает работать.

## 9. Frontend Mini App

APIX mini app находится в `webapp/src/main.jsx`.

Минимальные компоненты:

- `PromptFeed`: горизонтальная подборка prompt-карточек на главной/в ленте.
- `Prompts`: полный экран библиотеки с source tabs, лайками, share link, "В студию", "Мои".
- `Feed`: экран публичной ленты.
- `FeedCard`: медиа-сетка, лайк, repeat/remix, link, delete для своих.
- `Studio`: принимает `preset` из библиотеки и `remixSource` из ленты.
- `GenShareButtons`: кнопки `В ленту` и `Сохранить промпт`.
- `GenerationResultCard`: показывает результат, скрывает prompt actions если `prompt_hidden`.

Ключевые frontend-инварианты:

```js
function generationPromptHidden(generation) {
  return Boolean(generation?.prompt_hidden) || generation?.prompt_actions_allowed === false;
}

function generationPromptActionsAllowed(generation) {
  return !generationPromptHidden(generation);
}
```

При применении prompt:

```js
setStudioPreset({
  kind: "image",
  modelKey: promptItem.model || undefined,
  prompt: promptItem.prompt_text || "",
  promptId: promptItem.id || null,
  title: promptItem.title || "Промпт",
});
```

При генерации:

```js
{
  model,
  prompt: promptForGeneration,
  prompt_id: kind === "image" ? selectedPrompt?.id : null,
  ...
}
```

При feed remix:

```js
setRemixSource({
  gen_id: feedItem.id,
  model: feedItem.model,
  gen_type: feedItem.gen_type || "image",
  result_url: feedItem.result_url || null,
});
```

И затем:

```js
POST /api/v1/feed/{gen_id}/remix
```

с пустым `prompt` в body. Prompt должен прийти только из backend.

Realtime:

- WebSocket `/api/v1/ws/generations`.
- Payload должен включать `prompt_hidden`, `prompt_actions_allowed`, `result_urls`, `is_public_feed`, `is_prompt_library`.
- Frontend обновляет текущую generation, историю, баланс и feed после final state.

## 10. Standalone Web

Если переносишь standalone сайт, повтори слой `landing/js/riot-site.js`:

- routes: `prompts`, `feed`, `studio`, `works`, `profile`, `admin`;
- data loaders:
  - `/api/web/feed?limit=9`
  - `/api/web/prompts?limit=9`
  - `/api/web/admin/prompts?status=pending`
- prompt actions:
  - like: `POST /api/web/prompts/{id}/like`
  - use: `POST /api/web/prompts/{id}/use`, затем pending prompt в studio
  - copy prompt
  - submit prompt: `POST /api/web/prompts`
- feed actions:
  - like: `POST /api/web/feed/{id}/like`
  - share: `POST /api/web/feed/{id}/share`
  - use as reference
  - remix: сохраняет pending feed remix и открывает studio
- generation actions:
  - publish: `/api/v1/generations/{id}/publish`
  - library: `/api/v1/generations/{id}/share-library`
- admin moderation:
  - approve/reject/deactivate через `/api/web/admin/prompts/{id}/{action}`.

## 11. Static files and previews

Для Telegram/генераторов важны публичные URL с корректным расширением.

Перенеси из `api/public_files.py`:

- `public_upload_url(filename)`
- `local_upload_path_from_url(url)`
- `public_url_is_available(url)`
- `detect_image_extension(data, content_type=None)`
- `ensure_public_image_url(url)`
- `save_public_file(data, content_type=None)`
- `mirror_telegram_file(bot, file_id, is_video=False)`

Правило: preview/ref image не должен быть `.bin`, если это JPEG/PNG/WebP. Telegram и внешние генераторы часто хуже работают с неправильным suffix.

## 12. Порядок внедрения в новом проекте

### Шаг 1. Проверь исходные зависимости

Перед кодом убедись, что в целевом проекте уже есть:

- таблица пользователей;
- таблица генераций;
- async DB session/repository слой;
- auth для web/mini app;
- сервис генерации image/video;
- баланс/credits или решение отключить rewards;
- публичный static upload;
- админский список пользователей.

Если чего-то нет, создай минимальный adapter, но не смешивай prompt/feed-логику с провайдером генераций.

### Шаг 2. Добавь миграции

Добавь:

1. enum `promptcategory`.
2. enum `promptstatus`.
3. таблицу `user_prompts`.
4. таблицу `prompt_likes` с unique `(user_id, prompt_id)`.
5. поля в `generations`:
   - `result_urls`
   - `is_public_feed`
   - `is_prompt_library`
   - `source_feed_gen_id`
   - `likes_count`
   - `shares_count`
   - `parent_generation_id`
   - `action_type`
6. индексы:
   - `generations(user_id, created_at desc)`
   - `generations(is_public_feed, status, created_at desc) WHERE is_public_feed = TRUE`
   - `user_prompts(status)`
   - GIN по `user_prompts.tags`, если Postgres array

### Шаг 3. Реализуй repository слой

Сначала сделай `prompt_repository`.

Тестируй отдельно:

- pending prompt нельзя лайкать;
- duplicate like не увеличивает counter;
- `use_prompt` не работает для non-public/rejected;
- `MAX_ACTIVE_PROMPTS_PER_USER` учитывает `pending + approved`;
- tags нормализуются.

Затем расширь generation repository:

- выборки ленты;
- score;
- publish/remove;
- hidden derivatives;
- royalties или event hooks.

### Шаг 4. Реализуй API

Сначала mini app API:

- feed list;
- prompt list/detail;
- prompt use/like/link;
- prompt submit/deactivate;
- generation share/share-library/publish;
- feed remix.

Потом standalone web API, если нужен сайт.

Не дублируй бизнес-логику в routes. Routes должны только:

- валидировать auth/body/query;
- вызвать repository/service;
- собрать DTO;
- вернуть HTTP error.

### Шаг 5. Интегрируй генерацию

В image generation endpoint:

1. Собери references.
2. Если есть `prompt_id`, загрузи prompt из БД и подставь `prompt_text`.
3. Проверь model/cost/capabilities.
4. Проверь credits и concurrent limit.
5. Спиши credits.
6. Создай `image_session`.
7. Создай `generation`.
8. Запусти внешний генератор.
9. Запиши `task_id`.
10. Вызови `use_prompt(..., credits_spent=...)`, если был `prompt_id`.
11. Верни `GenerationOut`.

В feed remix endpoint:

1. Загрузи source через `get_public_feed_generation`.
2. Не принимай prompt от клиента.
3. Выбери reference: user reference имеет приоритет, иначе `source.result_url`.
4. Создай `generation` с `source_feed_gen_id`.
5. Верни hidden prompt DTO.
6. После завершения начисли royalty.

### Шаг 6. Реализуй frontend

Минимальный экран библиотеки:

- tabs: `catalog`, `top`, `popular`, 2-3 tag tabs, `my`;
- карточка: preview, title, description, model, likes, uses;
- действия: use, like, share, deactivate for own.

Минимальный экран ленты:

- grid/card с `result_url` или `result_urls`;
- author/model/stats;
- actions: like, remix/repeat, copy link for own, delete for own.

Студия:

- принимает prompt preset из библиотеки;
- принимает remix source из ленты;
- при remix скрывает textarea prompt и показывает notice "prompt автора скрыт";
- отправляет `prompt_id` только для library prompt;
- отправляет `/feed/{id}/remix` для feed remix.

### Шаг 7. Реализуй Telegram bot, если он есть

Перенеси:

- keyboard builders;
- FSM states;
- handlers catalog/feed;
- deep link parser/builder;
- admin moderation callbacks.

Не меняй существующие bot flows в целевом проекте без явного требования. Встраивай новые callbacks через отдельные routers.

### Шаг 8. Добавь seed

Добавь seed-скрипт:

- создать showcase author;
- создать 2+ prompt на каждую коллекцию;
- сделать preview images публичными;
- создать готовые `Generation` для ленты;
- поставить `status=done`, `is_public_feed=true`.

Минимальные коллекции APIX:

- `best`
- `characters`
- `cyberpunk`
- `realism`
- `cinematic`
- `nsfw`
- `music`

### Шаг 9. Добавь проверки

Минимальный набор tests:

- prompt tag/category inference;
- pending prompt hidden from others;
- pending/non-public prompt cannot be liked/shared/used;
- prompt like duplicate idempotent;
- feed query returns only public done images;
- feed like/share updates only public posts;
- share_to_feed blocks `source_feed_gen_id`;
- share_to_library blocks `source_feed_gen_id`;
- feed remix returns `prompt_hidden=true`;
- feed remix uses source prompt server-side;
- user reference overrides source result reference;
- Midjourney/blend or provider-specific branches validate refs before spending credits;
- realtime payload hides prompt for feed derivatives;
- frontend helper does not show prompt actions when hidden.

В этом репозитории перед сдачей code changes запускается:

```bash
tools/codex_static_checks.sh
```

## 13. Частые ошибки при переносе

- Публиковать feed-remix обратно в ленту. Это раскрывает чужой prompt через history/feed actions.
- Отдавать `Generation.prompt` в realtime без проверки `source_feed_gen_id`.
- Считать `is_prompt_library` полноценной карточкой каталога. В APIX это только флаг генерации.
- Увеличивать prompt likes без unique table.
- Принимать prompt text от клиента при `prompt_id`.
- Делать feed remix на frontend, передавая hidden prompt через браузер.
- Не проверять `public_url_is_available`: карточки начнут ссылаться на удалённые local upload файлы.
- Не нормализовать tags: коллекции начнут пустеть из-за `#Tag`, пробелов и разных регистров.
- Смешивать mini app response shape и standalone web envelope.

## 14. Definition of Done

Считай интеграцию законченной, когда:

- `GET /prompts` показывает только approved public prompt.
- Пользователь может отправить prompt на модерацию.
- AI/ручная модерация меняет статус и сохраняет audit.
- Prompt можно лайкнуть один раз на пользователя.
- Prompt можно применить в generation, и сервер использует prompt из БД.
- Готовую image generation можно опубликовать в feed.
- Feed показывает только public done images.
- Feed item можно лайкнуть, расшарить, открыть по deep link.
- Feed item можно ремикснуть без раскрытия prompt клиенту.
- Производные от feed нельзя повторно публиковать в feed/library.
- Realtime/history/result cards не показывают hidden prompt.
- Tests покрывают приватность prompt и публикационные запреты.
