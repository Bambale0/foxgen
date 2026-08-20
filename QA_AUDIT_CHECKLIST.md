# Senior QA Audit Checklist

Полный чеклист для глубокого аудита проекта: ботов, Mini App, API, платежей, БД, webhook, безопасности.

---

## 0. Контекст проекта

Определи фактический стек:
- backend: Python / aiogram / aiohttp / FastAPI
- bot: Telegram Bot, webhook или polling
- frontend: Mini App (JS/TS)
- внешние API: генерация изображений/видео, платежи
- БД: SQLite / PostgreSQL
- deploy: systemd, nginx, Docker

---

## 1. Карта связей

Для каждого элемента проверь:
```
Источник → Действие → Параметры → Куда передаются → Где валидируются → Где сохраняются → Где используются → Риск
```

Покрой:
- Telegram commands, callback_data, inline buttons, reply keyboards
- Deep links, Mini App links
- Frontend routes, backend endpoints, webhook endpoints
- Payment callbacks, external API calls
- File upload/download, admin actions, background jobs

Особое внимание:
- Есть ли кнопка, но нет обработчика?
- Есть ли обработчик, но нет кнопки?
- callback_data отличается от ожидаемого?
- URL строится без нужного query-параметра?
- Backend ожидает параметр, который frontend не передаёт?
- Внешний API требует поле, которое код не отправляет?
- Ответ API парсится по старой схеме?
- Статус задачи не обновляется?
- Ошибка API не обрабатывается?

---

## 2. Аудит ссылок, кнопок и параметров

Для каждой ссылки/кнопки:
1. Где создаётся?
2. Какой текст видит пользователь?
3. Какой action/callback/url вызывается?
4. Какие параметры должны передаваться?
5. Какие параметры реально передаются?
6. Кто принимает эти параметры?
7. Совпадают ли имена и типы?
8. Что будет, если параметра нет / пустой / чужой?
9. Есть ли тест на этот сценарий?
10. Есть ли логирование ошибки?

Ищи дефекты:
- `task_id` создаётся, но не передаётся в callback
- callback ожидает `generation_id`, а кнопка шлёт `task_id`
- ссылка содержит `user_id`, а backend ожидает `telegram_id`
- кнопка ведёт в старый handler
- frontend route есть, backend route отсутствует
- параметр передаётся строкой, код ожидает int
- id берётся из FSM, но FSM уже очищен
- callback_data превышен лимит Telegram
- параметр не экранируется
- пользователь может подменить id и получить чужие данные

---

## 3. Аудит внешних API и payload

Для каждого API:
```
Provider → Method → Endpoint → Required fields → Current payload → Missing/Wrong → Обработка ответа → Ошибки
```

Проверь:
- URL endpoint, HTTP method, headers, auth, API key
- content-type, required/optional fields, default values
- enum values, типы данных, вложенные объекты
- image_url/audio_url/video_url, callback_url, webhook_url
- timeout, retry, rate limit
- error mapping, idempotency
- логирование request_id/task_id
- безопасное хранение секретов
- обработку 400/401/403/404/409/422/429/500
- парсинг ответа, сохранение external_task_id
- polling, webhook update, финальный статус
- возврат средств при ошибке

Ищи дефекты:
- поле называется `callbackUrl`, а отправляется `callback_url`
- локальный путь вместо публичного URL
- API требует `image_url`, код отправляет `image`
- API требует список, код отправляет строку
- duration как int, а API ожидает string enum
- model name устарел
- negative_prompt не передаётся
- webhook принимает один формат, провайдер шлёт другой
- task_id не сохраняется
- повторный webhook повторно начисляет/списывает
- ошибка API оставляет задачу в статусе processing навсегда

---

## 4. Бизнес-логика

Entity lifecycle для каждой сущности:
- User, Balance, Transaction, Plan/Tariff, GenerationTask
- Payment, Referral, AdminAction, File/Asset
- ProviderRequest, ProviderResult

Для каждой:
- Как создаётся? Какие статусы? Кто может менять?
- Какие переходы разрешены/запрещены?
- Что при ошибке / повторном событии / отмене / timeout?
- Что при ручном админском вмешательстве?

Инварианты:
- Баланс не может стать отрицательным
- Оплата не должна начисляться дважды
- Генерация не должна списывать дважды
- Пользователь не должен видеть чужие задачи
- Обычный пользователь не должен вызывать admin-функции
- Статус задачи не должен застревать
- Результат не должен выдаваться до успешной оплаты
- Возврат должен быть связан с исходной транзакцией
- Webhook должен быть идемпотентным
- Реферальный бонус не должен начисляться повторно
- Удаление задачи не должно ломать историю

---

## 5. Smoke-проверки

```text
[ ] Установка зависимостей
[ ] Импорт всех модулей
[ ] Запуск приложения
[ ] Чтение .env
[ ] Подключение к БД
[ ] Применение миграций
[ ] Старт Telegram bot/webhook
[ ] Healthcheck
[ ] Открытие Mini App
[ ] /start → главное меню
[ ] Создание тестовой задачи
[ ] Тестовый платёж
[ ] Webhook обработка
[ ] Админская команда
[ ] Graceful shutdown
```

---

## 6. Regression-матрица

Обязательные flows:
1. Новый пользователь → /start → регистрация → главное меню
2. Пополнение баланса → баланс обновился → транзакция записана
3. Создание генерации → баланс списан → задача создана → payload ушёл в API
4. API success → результат сохранён → пользователь получил файл
5. API error → задача failed → деньги возвращены или статус обработан
6. Повторное нажатие кнопки → нет двойного списания
7. Webhook дважды → нет двойного начисления
8. История → только свои задачи
9. Админ → корректные агрегаты
10. Обычный пользователь → admin callback = отказ
11. Старые callback_data → не ломают, дают понятную ошибку
12. Старые записи БД после миграции → не падает

---

## 7. Unit-тесты (должны быть)

- Расчёт цены, списание/начисление баланса
- Проверка прав, генерация/парсинг callback_data
- Сборка payload, валидация prompt
- Валидация файлов (размер, mime-type)
- Парсинг ответа API, обработка статусов
- Форматирование сообщений, расчёт реферального бонуса
- Idempotency ключи, переходы статусов
- Сериализация/десериализация

---

## 8. Security

```text
[ ] Секреты в репозитории
[ ] .env в git
[ ] Токены в логах
[ ] SQL injection
[ ] Command injection
[ ] Path traversal
[ ] SSRF через URL картинки/файла
[ ] IDOR — доступ к чужим id
[ ] CSRF для web endpoints
[ ] Проверка подписи webhook
[ ] Проверка Telegram initData для Mini App
[ ] Admin bypass
[ ] Open redirect
[ ] Небезопасные CORS
[ ] Небезопасный file upload
[ ] Слишком подробные ошибки пользователю
[ ] Rate limiting
[ ] Audit log для админов
[ ] Хранение платёжных данных
[ ] Повторное проведение webhook
[ ] Idempotency
```

---

## 9. БД и миграции

```text
[ ] Модели соответствуют миграциям
[ ] Индексы на частых запросах
[ ] Unique constraints (payment_id, task_id)
[ ] Foreign keys
[ ] Nullable поля
[ ] Default values
[ ] Enum/status поля
[ ] ORM и SQL не расходятся
[ ] Транзакции для атомарных операций
[ ] Гонки при обновлении баланса
[ ] Двойное списание
[ ] Orphan records
[ ] Timezone
[ ] created_at/updated_at
[ ] Soft delete
[ ] Rollback миграций
```

---

## 10. Специфичные проверки

### Telegram Bot:
- /start, deep links, reply/inline keyboard
- callback_data, FSM states, возврат назад
- Повторное нажатие, устаревшие callback
- edit_message vs send_message
- Лимит длины callback_data
- Права админов, обработка blocked bot
- Webhook secret, allowed_updates
- Конфликт polling/webhook
- user_id/chat_id confusion
- Race condition при двойном клике

### Платежи:
- Уникальность provider_payment_id
- Idempotency webhook, подпись webhook
- Повторный webhook, отменённый платёж
- pending → success, success → повторный success
- failed, refund, частичная оплата
- Неверная сумма/валюта
- Связь transaction ↔ user, payment ↔ invoice

### AI-генерация:
- Prompt validation, negative_prompt
- Aspect_ratio, duration, model, quality, seed
- Reference images, image_url (публичность)
- Mime-type, размер файла
- Provider task id, polling, webhook
- Result URL, download, save history
- Retry, refund on fail
- Stuck processing, moderation/safety error

---

## Severity

- **P0** — деньги, безопасность, полная неработоспособность, потеря данных
- **P1** — ключевой пользовательский flow сломан
- **P2** — частичная поломка, edge case, плохая обработка ошибок
- **P3** — улучшение, refactor, UX, техдолг

---

## Формат финального вывода

```
Готово к production: да/нет
Главная причина: ...
Топ-5 исправлений перед релизом:
  1. ...
  2. ...
Минимальный test suite перед merge:
  - ...
Что проверить вручную:
  - ...
Что автоматизировать в CI:
  - ...
```
