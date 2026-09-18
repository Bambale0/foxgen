> Historical diagnosis at baseline d74bf7a. Findings below describe the pre-fix system. Implementation and remaining external verification are documented in [payment-recovery.md](payment-recovery.md).

# HappyFox: backend, frontend, платежи и бизнес-логика

Дата: 18 сентября 2026. Базовый commit: d74bf7a856ce64e7e06057ca8edcdc28e2932b85.

## Основной вывод

Один публичный endpoint ЮKassa доступен, но распределения Telegram/MAX в нём нет. Оба пути `/yookassa/webhook` и `/webhook/yookassa` ведут в один Telegram-обработчик. MAX получает начисления через отдельную сверку каждые 30 секунд и ручную проверку оплаты, а не через этот webhook.

Зелёные существующие тесты не подтверждают корректность общего платежного webhook. Изолированные воспроизведения обнаружили ошибки, которые ими не покрываются.

## Проверенная среда и ограничения

- Production backend, опубликованные revision.txt Telegram и MAX совпадают с базовым SHA.
- Рабочее дерево содержит сторонние незакоммиченные изменения Mini App и CI/deploy. Во время проверки его состояние менялось. Аудитор эти изменения не выполнял.
- Backend проверялся в изолированной локальной копии с Python 3.12.14 и requirements.lock; production credentials туда не копировались.
- В копии применены два преобразования публичных текстов, которые выполняет CI. Они объясняют ошибки проверки старых текстов в исходном checkout.
- Browser E2E проверяли существующий статический тестовый артефакт .e2e-server с подменёнными API/bridge. Это не проверка оплаты настоящим пользователем в нативных клиентах.
- Реальные production записи сверялись только чтением БД и GET к ЮKassa. Платежи, начисления, генерации и сообщения пользователям аудит не создавал.
- Настройка HTTP-уведомлений в кабинете ЮKassa недоступна через имеющуюся Basic Auth интеграцию; сохранённый там URL и выбранные события не подтверждены.
- Полный обход каждого элемента на каждом экране, настоящие Telegram/MAX iOS/Android клиенты, доступ к аккаунтам покупателей, нагрузка сверх пика и полноценная финансовая сверка всей истории не выполнены. Нельзя утверждать, что найдены абсолютно все баги.

## P0: финансовые дефекты

### 1. Telegram продолжает начисление при проигранном захвате заказа

`bot/database.py:complete_payment_atomic`: если SELECT прочитал pending, а UPDATE pending→processing вернул rowcount=0, функция выходит только при старом txn_row.status=processing. При старом pending она продолжает начислять.

`bot/postgres_aiosqlite.py:translate_sql` преобразует BEGIN IMMEDIATE в обычный BEGIN. SELECT заказа не содержит FOR UPDATE. Два PostgreSQL обработчика могут прочитать pending, затем второй после commit первого получить rowcount=0 и всё равно увеличить баланс.

Воспроизведение: `audit_claim_repro.py` запускает настоящую complete_payment_atomic с DB-адаптером, моделирующим проигрыш claim. Результат: `result.ok=True; extra credits=25` при rowcount=0.

Это доказательство ошибки ветвления; настоящая конкурентная PostgreSQL транзакция и фактическое двойное начисление в production не воспроизводились.

Исправление: блокировка строки/атомарный claim с RETURNING; при отсутствии захваченного заказа никакие начисления не выполнять; проверить конкурентный webhook+polling на изолированном PostgreSQL.

### 2. Платёжная ссылка выдаётся без сохранённого Telegram-заказа

`bot/miniapp.py:miniapp_create_payment`: сначала создаёт внешний платёж, затем вызывает create_transaction, но игнорирует False. Клиент получает ok=true и ссылку, хотя локальный заказ не сохранён. Webhook не сможет верифицировать такой платёж.

Воспроизведение: `audit_checkout_repro.py`, настоящий HTTP handler, create_transaction=False → HTTP 200, ok=true, payment_url присутствует.

Исправление: сохранять локальное намерение оплаты до внешнего запроса, устойчиво связывать provider ID; обрабатывать ошибки сохранения и иметь reconciliation для неоднозначного результата создания.

## P1: платежи, доставка и бизнес-система

### 3. Общий webhook не маршрутизирует MAX

`bot/handlers/payments.py:handle_yookassa_webhook` вызывает Telegram YooKassaService, который верифицирует по transactions, затем требует Telegram transaction/user ID. MAX заказы находятся в max_payment_orders.

Воспроизведение `audit_payment_repro.py`: MAX metadata → HTTP 200, verification_error=local_transaction_not_found. До MAX complete_order обработка не доходит.

Исправление: находить локальный заказ по уникальному provider payment ID в обоих реестрах, определять канал из доверенного локального заказа, верифицировать через соответствующий сервис и доставлять уведомление соответствующему получателю. Не маршрутизировать начисление только по неподтверждённому входящему metadata.

### 4. Начисление до финального succeeded

Telegram YooKassaService.get_payment и MaxYooKassaService._verification_state используют paid=true ИЛИ succeeded. waiting_for_capture с paid=true тоже считается оплаченной покупкой.

Воспроизведение `audit_payment_repro.py`: MAX verdict=('paid', None), Telegram paid=True при waiting_for_capture.

Официальная документация различает waiting_for_capture и succeeded: https://yookassa.ru/developers/payment-acceptance/getting-started/payment-process.

В текущих checkout capture=true; непосредственная частота проявления не установлена. Тем не менее обработка статуса неверна и опасна для внешних/двухстадийных платежей.

Исправление: начислять только после подтверждённого succeeded с корректными суммой, валютой, магазином и идентификаторами заказа.

### 5. Временные ошибки webhook подтверждаются HTTP 200

handle_yookassa_webhook возвращает 200 при неудачном GET ЮKassa, отсутствии заказа, ошибке завершения и исключении. Воспроизведение: provider lookup=None → HTTP 200.

ЮKassa считает 200 подтверждением получения: https://yookassa.ru/developers/using-api/webhooks. Без устойчивого сохранения события повторная доставка при временном сбое прекращается; остаётся polling.

Исправление: сначала сохранять событие в durable inbox, затем подтверждать; либо возвращать повторяемую ошибку до устойчивого принятия. Некорректные/чужие события отличать от временной ошибки.

### 6. Уведомления об оплате не имеют устойчивой повторной доставки

Telegram complete_payment_atomic коммитит начисления до send_message. После ошибки уведомления повторный webhook видит already_completed и пропускает доставку. Telegram polling вызывает _complete_transaction, который уведомляет рефереров, но не самого покупателя.

MAX polling устанавливает completed до отправки сообщения. Ошибка отправки логируется; completed заказ больше не попадает в pending.

Начисление и уведомление — разные результаты. Нужен outbox со статусом доставки и безопасным retry. Изучено по коду; реальные сбои доставки платежных уведомлений не инъецировались.

### 7. Завершение MAX заказа распределено по нескольким commit

MAX сначала коммитит баланс покупателя, затем отдельные реферальные начисления, затем статус completed. При сбое возникает частично завершённая покупка. Идемпотентные ключи снижают риск повторного начисления, но единая атомарная операция отсутствует.

Фактическая production проверка не нашла заказа с начислением при незавершённом статусе. Это дефект устойчивости из анализа кода, а не установленное повреждение данных.

### 8. Бизнес-правила и балансы расходятся по каналам

Architecture docs явно описывают отдельный MAX баланс. AGENTS.md одновременно требует общий billing/identity core. Telegram комиссии идут в рублёвый partner_balance_rub, MAX — в balance_credits после пересчёта. Telegram promo_bonus поддерживается; MAX checkout возвращает promo_bonus_credits=0 и не применяет переданный promo_code.

Это подтверждённое различие, но требуемый продуктовый результат для единого аккаунта и партнёрки необходимо зафиксировать. Отдельные балансы нельзя автоматически объединять, не имея правил идентификации и миграции.

### 9. Mutable бизнес-значения зашиты в Telegram-код

bot/database.py: PARTNER_LEVEL1_PERCENT=30, PARTNER_LEVEL2_PERCENT=7, регистрационные бонусы и PROMO_BONUS_BY_CREDITS заданы константами. MAX берёт партнёрские настройки из своего каталога.

Это нарушает правило AGENTS.md о настройке mutable бизнес-значений через контрольную плоскость и создаёт отдельные источники правил. Нужны единые типизированные и аудируемые настройки.

## P2: frontend, диагностика и интеграционные дефекты

### 10. Полный lint ломается после подготовки browser E2E

eslint.config.mjs не исключает .e2e-server. npm run lint проверил минифицированные JS и копию Telegram SDK: 4094 errors, 248 warnings. Проверка только app/components/lib: 0 errors, 7 warnings.

Исправление: исключить generated каталог из ESLint; сохранение только в .gitignore недостаточно. Предупреждения исходников включают зависимости React hooks в trends-tab/app-context.

### 11. Платёжный API возвращает error объект вместо строки

Telegram miniapp_create_payment возвращает error=result при ошибке ЮKassa/Lava. lib/payment-api.ts объявляет error как строку и передаёт в new Error.

Воспроизведение audit_checkout_repro.py: HTTP 500, error type=dict. JS строковое преобразование объекта даёт [object Object], что делает сообщение об ошибке непонятным.

Дополнительно payment-api.ts вызывает fetch без AbortController/deadline: зависший запрос оставляет покупку в loading. Риск из анализа кода, а не измеренное зависание production.

### 12. Импорт miniapp зависит от порядка инициализации

Чистый import bot.miniapp воспроизводимо падает: partially initialized module bot.miniapp has no attribute miniapp_bootstrap. Причина: handlers/__init__.py вызывает install_seedance_25_fullstack, обращающийся к ещё не инициализированному miniapp.

При предварительном import bot.handlers импорт проходит. Основной runtime работает с подходящим порядком; дефект мешает изолированным инструментам/тестам и делает wiring хрупким.

### 13. Публичный health поверхностный и с историческим именем

/health отвечает status=ok, service=tanya-bot; код не проверяет БД, Redis, платёжные фоновые задачи или каналы и не включает revision. Healthy не означает готовность принимать/обрабатывать платежи.

### 14. Устаревший HMAC gate для ЮKassa

handle_yookassa_webhook при настроенном YOOKASSA_WEBHOOK_SECRET требует предполагаемые X-Webhook-Signature/X-Checkout-Signature/X-Signature и молча отвечает 200 при отсутствии. Такая обязательная подпись не установлена по официальному контракту стандартных уведомлений ЮKassa.

В production gate выключен, поэтому сейчас не блокирует события. Защиту строить на подтверждении объекта API/локального заказа и документированном механизме провайдера.

## Данные production: что подтверждено

- Telegram ЮKassa: 3 completed, 4 failed.
- Из трёх completed два remote succeeded/paid=true; третий текущим магазином возвращает 404. Причина не установлена: возможны исторический магазин, тестовый заказ или иное происхождение. Это пункт сверки, не доказательство мошенничества или потери денег.
- Все четыре Telegram failed и четыре MAX failed на стороне ЮKassa canceled, reason=expired_on_confirmation.
- MAX успешных заказов нет; реального успешного MAX webhook/уведомления история не доказывает.
- MAX balance vs SUM(completed max_transactions): 0 несовпадений.
- MAX completed order без credit ledger entry: 0.
- MAX credit ledger entry для незавершённого заказа: 0.
- Public app и MAX origins возвращают 200; оба revision.txt совпадают с backend image SHA.
- Запросы bootstrap/create-payment без init_data отклоняются. Telegram: 401; MAX: 400. Чужая покупка в MAX check-payment проверяется по локальному max_user_id.
- Последние 24 часа логов содержали timeout генерации Nano Banana Pro и отказ доставки пользователю, заблокировавшему бота. Сам по себе это не доказательство внутреннего дефекта; возврат по конкретному generation task в рамках аудита не сверялся.

## Фактические проверки

- Locked requirements в отдельном Python 3.12 окружении; uv pip check: все 52 пакета совместимы.
- python -m compileall -q bot scripts: успешно.
- CI-нормализация текстов + pytest tests/ --ignore=tests/live -m 'not live_smoke and not load' -q --tb=short: 344 passed, 1 deselected, 3 warnings.
- npm test -- --runInBand: 18 suites, 64 tests passed.
- npx tsc --noEmit --incremental false: exit 0.
- npm run lint: ошибки generated файлов; source lint: 0 errors, 7 warnings.
- npm audit --json: 0 vulnerabilities на момент проверки.
- critical-flows.mjs: passed.
- max-startup.mjs: Android Chromium/iPhone WebKit passed.
- telegram-startup.mjs: Android Chromium/iPhone WebKit passed; повторный отдельный запуск устранил конфликт порта с MAX тестом.
- native-launch-recovery.mjs: Android Chromium/iPhone WebKit passed.
- audit_payment_repro.py, audit_claim_repro.py, audit_checkout_repro.py: воспроизвели перечисленные ошибки.
- Production SQL сверка и GET ЮKassa выполнены только чтением.

## Приоритет действий

1. Закрыть проигранный claim и выдачу checkout без сохранённого заказа; добавить PostgreSQL concurrency regression.
2. Ввести настоящий единый YooKassa webhook dispatcher по локальному заказу; checkout/channel принадлежность верифицировать до начисления.
3. Принимать только succeeded; durable inbox/outbox; повторная доставка покупателю в правильном канале.
4. Проверить реальную настройку кабинета ЮKassa: один canonical URL и события payment.succeeded/payment.canceled, затем sandbox end-to-end Telegram/MAX.
5. Зафиксировать общую модель баланса, промо и партнёрских выплат; выполнять изменения отдельно от платежного hotfix.
6. Исправить frontend error contract, deadline и lint ignores; убрать цикл импортов и углубить readiness.

## Использованные инструкции и delivery

Прочитаны AGENTS.md, .agents/AGENTS.md, .agents/SKILL.md, architecture/deployment docs. Основные применённые локальные скиллы: diagnosing-bugs, frontend-ux-audit и full-audit-checklist. Дополнительно изучены Bambale0/claw QA checklist, wondelai release-it excerpt, anthropics webapp-testing. Bambale0/skills checkout в предписанном пути отсутствует; его актуальность и guidance не применялись. Пользователь явно указал использовать проектную .agents библиотеку.

Production файлы аудитом не изменены. Отчёт, копия и диагностические harness созданы вне production checkout. Миграций, config/admin изменений, PR, commit, merge и deploy нет. Exact-commit remote CI не проверен; локальный проход не заменяет этот gate. MAX/Telegram/Mini App проверены описанными тестами, платежная parity нарушена. Instagram в этом аудите проверен существующей regression suite; его платёжный handoff использует Telegram и наследует Telegram платежные риски, live Instagram сценарии не проходились.

Полностью исправленным или исчерпывающе проверенным продукт считать нельзя: перечисленные дефекты не устранены, ограничения проверки указаны выше.
