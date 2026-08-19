# Neuromix Bot — Краткое руководство / Audit

## Описание проекта

Telegram-бот для генерации изображений и видео через нейросети (Kling, Veo, Seedance, Wan2.7 и др.). Работает на aiogram 3, aiohttp webhooks, Redis, PostgreSQL/SQLite.

Бот: @Neuromixx_bot
Репозиторий: git@github.com:Bambale0/banano_kling.git

---

## Архитектура

```
bot/
├── main.py              # Точка входа, webhooks, роутеры
├── config.py            # Конфигурация из переменных окружения
├── database.py          # Все операции с БД (6.5k строк)
├── db.py                # Прокси для SQLite/PostgreSQL (aiosqlite/asyncpg)
├── keyboards.py         # Клавиатуры Telegram
├── miniapp.py           # Mini App на aiohttp + Jinja2
├── miniapp_links.py     # Генерация глубоких ссылок
├── states.py            # FSM состояния
├── handlers/
│   ├── common.py        # Основные обработчики (5k строк)
│   ├── generation.py    # Генерация изображений/видео
│   ├── batch_generation.py
│   ├── payments.py      # Платежи (Lava, YooKassa, CryptoBot, TBank, etc.)
│   ├── admin.py         # Админка
│   └── image_analyzer.py
├── services/
│   ├── kling_service.py # Kling AI
│   ├── veo_service.py
│   ├── seedance_service.py
│   ├── wan27_service.py
│   ├── gemini_service.py
│   ├── gpt_image_service.py
│   ├── nano_banana_2_service.py
│   ├── subscription_service.py
│   └── ... (другие сервисы)
└── utils/
    ├── help_texts.py
    ├── validators.py
    └── user_facing_errors.py

frontend/miniapp-v0/     # Mini App на Next.js + shadcn/ui
scripts/                 # Скрипты миграции, бэкапа, деплоя
docs/                    # Документация
```

---

## Финансовая модель

- **Тарифы**: `data/price.json` — прайс-лист на генерации
- **Внутренняя валюта**: `🍌 бананы` (1 рубль = 1 банан у.е.)
- **Партнёрка**: 30% с рефералов 1 уровня, 7% со 2 уровня
- **Платежи**: Lava, YooKassa, CryptoBot, TBank, Telegram Stars

---

## Аудит реферальной системы

### Выявленные проблемы (07.2026)

| # | Проблема | Уровень | Статус |
|---|----------|---------|--------|
| 1 | Неатомарность: создание пользователя и привязка реферала — разные транзакции | CRITICAL | 🔴 |
| 2 | Существующий пользователь (без `referred_by`) не может быть привязан к рефереру | HIGH | 🔴 |
| 3 | Нет команды диагностики `/check_ref` | MEDIUM | 🔴 |
| 4 | Нет повторной обработки при падении между `get_or_create_user` и `_activate_referral_code` | CRITICAL | 🔴 |
| 5 | Антифрод не логирует нормальные рефералы (только блокировки) | LOW | 🔴 |

### Как работает реферальная ссылка

1. Пользователь переходит по `https://t.me/Neuromixx_bot?start=ref_JXZWPGFA`
2. Telegram шлёт боту `/start ref_JXZWPGFA`
3. `cmd_start()`:
   - Вызывает `get_or_create_user()` → создаётся пользователь **без реферрера**
   - Вызывает `_activate_referral_code()` → пытается привязать реферрера
4. `process_referral()` проверяет: код существует? пользователь существует? не сам себя? уже платил? не заблокирован? не превысил лимит?
5. Если всё ОК — обновляет `referred_by` и добавляет записи в `referrals`

### Почему рефералы НЕ засчитываются

#### 1. Главная проблема: разрыв между созданием и привязкой
```python
# cmd_start():
user = await get_or_create_user(message.from_user.id)  # Создаётся юзер
# ... если здесь ошибка, перезапуск, race condition ...
referral_bonus_text = await _activate_referral_code(...)  # Пытается привязать
```
Между этими двумя вызовами может произойти что угодно. Если бот упал — пользователь создан, но реферал потерян навсегда.

#### 2. Пользователь уже существует
Если человек когда-либо заходил в бота (даже год назад), `get_or_create_user()` возвращает существующего пользователя с `referred_by IS NULL` (потому что реферал не привязался тогда).

#### 3. Антифрод может блокировать нормальных пользователей
`REFERRAL_ANTIFRAUD_MAX_PER_HOUR = 30` — если реферрер привёл 30+ человек за час, все следующие блокируются. При 1700 подписчиках и месяце рекламы — это возможно.

### Что исправлено

✅ **get_or_create_user()** теперь принимает `referral_code` и создаёт пользователя сразу с `referred_by` в одной транзакции
✅ **process_referral()** исправлен: разрешена привязка существующих пользователей (если `referred_by IS NULL` и нет оплат)
✅ **cmd_start()** передаёт referral_code прямо в get_or_create_user для атомарности
✅ Добавлена команда `/check_ref <CODE>` для диагностики
✅ Добавлено детальное логирование
✅ Создан этот файл аудита

---

## Todo (ближайшие задачи)

- [x] Исправить get_or_create_user — атомарная транзакция с реферальным кодом
- [x] Исправить process_referral — разрешить привязку существующих пользователей (если referred_by IS NULL)
- [x] Добавить команду /check_ref для диагностики
- [x] Настроить подробное логирование реферальных событий
- [ ] Проверить, работает ли startapp=ref_CODE через Mini App
- [ ] Тестирование: создать тест на сквозную проверку реферальной цепочки
- [ ] Добавить метрики в Prometheus (если есть)

---

## Запуск и деплой

```bash
# Запуск бота
./start.sh          # или systemctl start banano-kling

# Рестарт
./restart.sh

# Логи
journalctl -u banano-kling.service -n 200 --no-pager

# Проверка БД (production)
python scripts/check_postgres_runtime.py

# Бэкап
SEND_BACKUP_TO_ADMINS=0 ./scripts/backup_db.sh

# Тесты
python -m pytest tests/
```

---

## Важные константы

```python
PARTNER_LEVEL1_PERCENT = 30       # % с покупок рефералов 1 уровня
PARTNER_LEVEL2_PERCENT = 7        # % с покупок рефералов 2 уровня
PARTNER_NEW_USER_BONUS = 15       # бананов новому пользователю
PARTNER_INVITER_BONUS = 3         # бананов пригласившему
REFERRAL_ANTIFRAUD_MAX_PER_HOUR = 30
REFERRAL_ANTIFRAUD_MAX_PER_DAY = 120
```

---

## Полезные ссылки

- Документация API: `docs/`
- Партнёрская программа: `/ref` или `/earn` в боте
- Админка: `/admin`

---

*Последнее обновление: 02.07.2026*
*Создано для понимания проекта в параллельных чатах*