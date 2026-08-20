# Бренд HappyFox

## Основное правило

Пользовательский бренд продукта во всех интерфейсах, сообщениях бота и актуальной документации:

```text
HappyFox
```

Не показывать пользователю как название продукта:

- NEUROMIX;
- Banano Studio / Banana Studio;
- Banano Kling;
- внутреннее имя production-core;
- технические `banano_*` identifiers.

Исключение — официальные названия AI-моделей, например `Nano Banana` и `Nano Banana Pro`.

## Sources of truth

Frontend:

```text
frontend/miniapp-v0/lib/product.ts
frontend/miniapp-v0/lib/brand.ts
frontend/miniapp-v0/public/happyfox-logo.webp
```

Backend:

```text
bot/product.py
```

Компоненты должны использовать `BRAND_NAME`, `BRAND_DESCRIPTION` и `BRAND_LOGO`, а не дублировать имя продукта строковыми литералами.

## Logo / palette

- основной фон: почти чёрный;
- основной акцент: фирменный оранжевый;
- вторичный акцент: тёплый orange/red;
- зелёный используется только для success/online states;
- холодный cyan не используется как отдельный брендовый акцент;
- logo не перекрашивать и не искажать пропорции.

Глобальные frontend tokens находятся в:

```text
frontend/miniapp-v0/app/globals.css
```

## AI model names

Не переименовывать provider/model names:

- Nano Banana / Nano Banana Pro;
- Kling;
- Veo;
- Grok Imagine;
- Seedream;
- Seedance;
- GPT Image;
- Gemini;
- Wan.

Правильно:

```text
HappyFox
Модель: Nano Banana Pro
```

Неправильно:

```text
HappyFox Banana Pro
```

## Legacy technical identifiers

Для совместимости внутри production-core могут оставаться:

- env flags `BANANO_*`;
- callback IDs;
- database enum values;
- provider/model keys;
- Python module/function names с `banana`/`banano`.

Они не являются пользовательским брендом и не должны появляться в UI/copy. Runtime infrastructure нового продукта использует отдельные идентификаторы:

```text
Docker project: foxgen-happyfox
container:      foxgen-happyfox-bot
service:        foxgen-happyfox
Redis prefix:   foxgen_happyfox
```

## User-facing surfaces

HappyFox должен использоваться в:

- browser title / metadata;
- loader;
- sticky Mini App header;
- welcome copy Telegram-бота;
- auth/error screens, когда отображается product name;
- README/release notes;
- public screenshots/marketing materials.

Функциональные заголовки можно оставлять короткими: `Создать фото`, `Создать видео`, `Работы`, `Лента`, `Профиль`.

## Tone of voice

- коротко и понятно;
- сначала действие пользователя, затем детали;
- не показывать provider/internal terminology без необходимости;
- ошибки объяснять человеческим языком;
- не обещать успех, если результат зависит от внешнего AI-provider;
- technical error/correlation id можно показывать вторичной строкой.

## Loader / auth gate

Loader:

- сразу показывает HappyFox logo/name;
- вызывает Telegram ready/expand согласно runtime contract;
- сообщает, что получает данные Telegram;
- имеет `role=status`, `aria-live`, `aria-busy`.

Browser auth gate:

- использует HappyFox;
- объясняет вход через Telegram;
- не раскрывает детали signature/HMAC validation;
- предлагает повторный вход/открытие через Telegram после recoverable error.

## QA

Перед релизом:

```bash
cd frontend/miniapp-v0
NEXT_PUBLIC_PRODUCT_ID=happyfox npm run build

test -s out/happyfox-logo.webp
grep -q 'HappyFox' out/index.html
```

Также проверять user-facing runtime на старые бренды. Допустимые совпадения `NEUROMIX` могут оставаться только в migration/history/explicit compatibility config и не должны попадать в HappyFox UI.

## Repository

Актуальная формулировка:

```text
HappyFox, репозиторий Bambale0/foxgen, ветка main
```

История происхождения production-core хранится отдельно в `MIGRATION_SOURCE.md`.
