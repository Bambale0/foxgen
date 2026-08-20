# Internal Admin CMS and Support API

Контур предназначен для Tanya Admin и работает внутри существующего Telegram-бота. Админка не подключается к базе бота напрямую и не отправляет сообщения пользователям из HTTP-request процесса.

## Пользовательский flow

```text
/support
/support_add [ticket_id]
/cancel
```

Пользователь может создать обращение с текстом и одним Telegram-вложением:

- фото;
- документ;
- видео;
- аудио.

В базе сохраняется Telegram `file_id`, имя, MIME type и размер. Бинарные данные не копируются в Tanya Admin.

Опубликованный CMS-документ `support.intro` может заменить стандартный вводный текст `/support`. При отсутствии документа или ошибке CMS используется встроенный безопасный fallback.

## Support API

```text
GET  /internal/admin/tickets
GET  /internal/admin/tickets/{ticket_id}
POST /internal/admin/tickets/{ticket_id}/assign
POST /internal/admin/tickets/{ticket_id}/update
POST /internal/admin/tickets/{ticket_id}/reply
```

Список поддерживает:

```text
query
status
priority
assigned_admin_id
limit
cursor
```

Поиск работает по номеру обращения, Telegram ID, username и теме.

### Назначение оператора

```json
{
  "assigned_admin_id": "admin-user-uuid",
  "reason": "take ticket into work",
  "confirmation": "ASSIGN 17"
}
```

Пустой `assigned_admin_id` снимает назначение. Новый тикет при назначении переходит в `in_progress`.

### Статус, приоритет и связи

```json
{
  "status": "in_progress",
  "priority": "high",
  "linked_payment_id": 9,
  "linked_operation_id": 42,
  "reason": "linked after investigation",
  "confirmation": "UPDATE 17"
}
```

Допустимые статусы:

```text
new
in_progress
waiting_user
resolved
closed
```

Допустимые приоритеты:

```text
low
normal
high
urgent
```

`linked_payment_id` и `linked_operation_id` проверяются по существующим таблицам. Отсутствующие ключи не меняют текущую связь; `null` или пустая строка явно очищают её.

### Ответ пользователю

```json
{
  "body": "Мы проверили оплату. Баланс уже восстановлен.",
  "reason": "answer after payment investigation",
  "confirmation": "REPLY 17"
}
```

Ответ выполняется транзакционно:

1. создаётся admin message;
2. создаётся `support_outbox` запись;
3. тикет переходит в `waiting_user`;
4. сохраняется идемпотентный результат команды;
5. фоновый worker Telegram-бота доставляет сообщение.

HTTP-ответ админке означает, что сообщение надёжно поставлено в очередь, а не обязательно уже доставлено. Поле `delivery_status` меняется на `sent` или `failed`. Worker использует `FOR UPDATE SKIP LOCKED`, экспоненциальную задержку и максимум пять попыток.

## CMS API

```text
GET  /internal/admin/cms/documents
GET  /internal/admin/cms/documents/{document_id}
POST /internal/admin/cms/documents
POST /internal/admin/cms/documents/{document_id}/publish
```

Допустимые типы:

```text
announcement
help
faq
banner
legal
```

Допустимые content-поля:

```text
text
caption
button_label
button_url
media_file_id
locale
metadata
```

Произвольные executable/config поля не принимаются. `button_url` разрешает только `https://` и `tg://`.

### Сохранение новой версии

```json
{
  "document_key": "support.intro",
  "title": "Вступление поддержки",
  "kind": "help",
  "content": {
    "text": "Опишите проблему одним сообщением."
  },
  "reason": "update support instructions",
  "confirmation": "SAVE support.intro"
}
```

Каждое сохранение создаёт новую append-only версию. Существующая версия не редактируется и не удаляется.

### Публикация версии

```json
{
  "version_id": 5,
  "reason": "approved by support lead",
  "confirmation": "PUBLISH 2:5"
}
```

Публикация только меняет `published_version_id` документа. Возврат к старому тексту выполняется публикацией старой версии и сохраняется в audit/idempotency history.

## PostgreSQL tables

```text
support_tickets
support_messages
support_attachments
support_outbox
cms_documents
cms_document_versions
```

CMS versions защищены PostgreSQL-trigger от UPDATE/DELETE. Тикеты и сообщения остаются изменяемыми только через узкие команды статуса, назначения, связей и reply outbox.

## Защита

Все Internal API routes требуют:

- private network allowlist;
- exact-body HMAC-SHA256;
- timestamp window;
- PostgreSQL `DATABASE_URL`.

Write routes дополнительно требуют:

```text
Idempotency-Key
X-Admin-User-Id
X-Request-Id
```

Ответы и CMS-публикации требуют точного ручного подтверждения. Секреты, Telegram bot token и файловые bytes через API не выдаются.

## Rollout

1. Развернуть Telegram-бот из ветки `tanyapi`.
2. Перезапустить процесс и проверить, что support outbox worker стартовал.
3. Создать тестовый тикет через `/support` с фото.
4. Проверить signed list/detail endpoint.
5. Развернуть Tanya Admin.
6. Назначить тикет себе, связать с тестовым payment/operation и отправить ответ.
7. Проверить `queued → sent` в карточке обращения и получение сообщения пользователем.
8. Создать CMS-документ `support.intro`, опубликовать версию и проверить новый текст `/support`.
