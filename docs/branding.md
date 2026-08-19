# Бренд NEUROMIX

## 1. Основное правило

Пользовательский бренд продукта во всех интерфейсах и пользовательской документации:

```text
NEUROMIX
```

Не использовать как название продукта:

- Banano Studio;
- Banana Studio;
- Banano AI Studio;
- Banana AI;
- Banano Kling;
- Banana Boom;
- внутреннее имя репозитория.

## 2. Где NEUROMIX обязателен

- browser `<title>`;
- Next.js metadata/application name;
- загрузчик Mini App;
- Telegram/browser auth gate;
- основной header;
- error screens;
- welcome copy бота;
- пользовательские инструкции;
- public screenshots и marketing materials;
- название продукта в README и release notes.

## 3. Единый frontend source

Источник имени бренда:

```text
frontend/miniapp-v0/lib/brand.ts
```

Компоненты должны импортировать `BRAND_NAME` и `BRAND_DESCRIPTION`, а не создавать собственные строки.

Пример:

```ts
import { BRAND_NAME } from '@/lib/brand'
```

## 4. Названия моделей не являются брендом продукта

Не переименовывать provider/model names:

- Nano Banana;
- Nano Banana Pro;
- Kling;
- Veo;
- Grok Imagine;
- Seedream;
- Seedance;
- GPT Image;
- Gemini.

Правильно:

```text
NEUROMIX
Модель: Nano Banana Pro
```

Неправильно:

```text
Модель: NEUROMIX Pro
```

## 5. Legacy technical identifiers

В коде и инфраструктуре могут оставаться:

- repository `banano_kling`;
- systemd service `banano-kling.service`;
- Redis prefix `banano_kling`;
- log path `banano-miniapp-cdn.log`;
- env flags `BANANO_*`;
- internal function names с `banana`/`banano`;
- callback IDs и database enum values.

Они могут сохраняться для backward compatibility. Не показывать их пользователю как название продукта.

Переименование technical identifiers выполняется отдельной migration-задачей с анализом:

- systemd units;
- Redis keys;
- database values;
- callbacks/deep links;
- deploy profiles;
- monitoring;
- backups;
- external integrations.

## 6. Заголовки экранов

Главный брендовый заголовок должен включать NEUROMIX или отображаться рядом с постоянным header NEUROMIX.

Примеры:

- `NEUROMIX`;
- `NEUROMIX загружается`;
- `Добро пожаловать в NEUROMIX`;
- `NEUROMIX — фото и видео с AI`.

Функциональные заголовки внутри уже брендированного приложения могут быть короткими:

- `Создать фото`;
- `Создать видео`;
- `Ваши работы`;
- `Тренды`;
- `Профиль`.

Не требуется добавлять NEUROMIX к каждой кнопке.

## 7. Tone of voice

- понятно и без технического мусора;
- действие пользователя видно сразу;
- не обещать результат, который зависит от внешнего provider;
- ошибки объяснять человеческим языком;
- технический код ошибки можно показывать вторичной строкой;
- не использовать старый «банановый» нейминг в пользовательском тексте, если это не название модели.

## 8. Loader

Loader должен:

- сразу показывать NEUROMIX;
- сообщать, что загружается приложение/данные Telegram;
- не обвинять пользователя;
- не показывать auth gate до завершения проверки initData;
- иметь доступный `role=status`, `aria-live` и `aria-busy`.

## 9. Browser auth gate

Gate вне Telegram:

- содержит бренд NEUROMIX;
- объясняет вход через Telegram;
- не называется Banana/Banano;
- после ошибки предлагает повтор или открытие в Telegram;
- не раскрывает детали signature validation.

## 10. QA checklist бренда

После frontend build:

```bash
cd frontend/miniapp-v0
npm run build

grep -RniE 'Banano AI Studio|Banana Studio|Banano Studio|Banano Kling' \
  app components lib out \
  || true
```

Результаты нужно классифицировать:

- user-facing text — исправить;
- technical identifier — допустим при обосновании;
- provider model `Nano Banana` — не менять.

Проверить публичный title:

```bash
curl -fsS https://cdn.chillcreative.ru/mini-app/ \
  | grep -o '<title>[^<]*</title>'
```

Ожидается:

```html
<title>NEUROMIX</title>
```

## 11. Документация

Заголовки актуальных пользовательских и production-документов должны использовать NEUROMIX. Исторические provider docs и internal filenames можно не переименовывать, если переименование сломает ссылки или историю.

При упоминании репозитория использовать формулировку:

```text
NEUROMIX, репозиторий Bambale0/banano_kling, ветка tanyapi
```
