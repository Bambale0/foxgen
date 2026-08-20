# FreeKassa — настройка оплаты

Основной платёжный провайдер ветки `tanyapi` — Lava. FreeKassa подключена как
дополнительная интеграция и в пользовательском интерфейсе называется `KASSA`,
без логотипов FreeKassa.

## Быстро: что вставить в кабинет FreeKassa

Для текущего продакшн-домена:

```text
URL оповещения: https://tanyapi.chillcreative.ru/freekassa/webhook
Метод оповещения: POST
```

```text
URL успешной оплаты: https://tanyapi.chillcreative.ru/payment/success
Метод успешной оплаты: GET
```

```text
URL возврата в случае неудачи: https://tanyapi.chillcreative.ru/payment/fail
Метод возврата в случае неудачи: GET
```

Секреты:

```text
Секретное слово: значение FREEKASSA_SECRET_WORD из .env
Секретное слово 2: значение FREEKASSA_SECRET_WORD_2 из .env
```

Не вставляйте секреты в Git и публичные документы. Значения должны совпадать между кабинетом FreeKassa и `.env` на сервере.

## 1. Переменные окружения

Обязательные:

```env
FREEKASSA_MERCHANT_ID=12345
FREEKASSA_SECRET_WORD=secret_word_1
FREEKASSA_SECRET_WORD_2=secret_word_2
```

Рекомендуемые:

```env
FREEKASSA_API_KEY=merchant_api_key
FREEKASSA_CURRENCY=RUB
FREEKASSA_LANGUAGE=ru
FREEKASSA_WEBHOOK_PATH=/freekassa/webhook
FREEKASSA_VERIFY_IP=1
```

Опциональные overrides:

```env
FREEKASSA_PAY_BASE_URL=https://pay.fk.money/
FREEKASSA_API_BASE_URL=https://api.fk.life/v1
FREEKASSA_ALLOWED_IPS=168.119.157.136,168.119.60.227,178.154.197.79,51.250.54.238
```

`FREEKASSA_API_KEY` обязателен для методов `36` и `44`: заказ создаётся через API `POST /orders/create`. Он также используется для ручной проверки и фоновой сверки `pending`-транзакций.

## 2. Настройки магазина FreeKassa

В кабинете магазина укажите:

- **URL оповещения:** `https://<WEBHOOK_HOST>/freekassa/webhook`
- **Метод оповещения:** `POST`
- **URL успеха:** ссылка на бота или Mini App
- **URL ошибки:** ссылка на бота или Mini App
- **Секретное слово:** значение `FREEKASSA_SECRET_WORD`
- **Секретное слово 2:** значение `FREEKASSA_SECRET_WORD_2`

Альтернативный зарегистрированный путь: `/webhook/freekassa`.

После успешной и полностью обработанной транзакции endpoint отвечает строго `YES`. При временной ошибке БД ответ `YES` не отправляется, чтобы FreeKassa повторила уведомление.

## 3. Платёжный поток

1. Пользователь выбирает пакет.
2. В резервном разделе `РФ — KASSA (резерв)` пользователь выбирает метод KASSA:
   - карта РФ — `i=36`;
   - СБП — `i=44`.
3. Бот формирует локальный `order_id`, сохраняет `pending`-транзакцию и выдаёт подписанную ссылку `/freekassa/checkout`.
4. Промежуточная страница запрашивает реальный email, а сервер получает реальный IP из доверенного reverse proxy.
5. Сервер отправляет JSON в `POST https://api.fk.life/v1/orders/create` с `shopId`, уникальным `nonce`, HMAC-SHA256 `signature`, `paymentId`, `i`, `email`, `ip`, `amount` и `currency`.
6. Пользователь перенаправляется только на `location` из успешного ответа FreeKassa.
7. FreeKassa отправляет form-data на Result URL.
8. Бот проверяет:
   - IP отправителя, если `FREEKASSA_VERIFY_IP=1`;
   - `MERCHANT_ID`;
   - MD5-подпись по секретному слову 2;
   - существование заказа;
   - provider транзакции;
   - точное совпадение суммы.
9. `complete_payment_atomic()` атомарно начисляет бананы, промокод и реферальные бонусы.
10. Повторный webhook получает `YES`, но повторного начисления не происходит.

Методы `36` и `44` нельзя передавать в SCI-ссылке `pay.fk.money`: FreeKassa помечает их как API-only. Runtime разрешает только эти два метода в API `createOrder`.

## 4. Nginx

Прокси должен передавать реальный IP:

```nginx
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
```

Если перед приложением есть дополнительный доверенный proxy/CDN, настройте получение реального IP на его уровне. Не отключайте IP-проверку без необходимости.

## 5. Проверка после развёртывания

1. Запустить бота с заполненными переменными.
2. Убедиться в логе:

```text
FreeKassa routes registered: ... enabled=True
```

3. Создать минимальный платёж.
4. Проверить строку в `transactions`: provider=`freekassa`, status=`pending`.
5. Оплатить.
6. Убедиться, что:
   - status стал `completed`;
   - бананы начислены один раз;
   - пользователь получил Telegram-уведомление;
   - Mini App получил уведомление;
   - повтор той же формы webhook отвечает `YES` и не меняет баланс.

## 6. Совместимость

Внутренний символ `yookassa_service` временно оставлен как адаптер для старых импортов. Он не содержит YooKassa SDK и выполняет операции через `freekassa_service` только для legacy-вызовов. Новые основные платежи должны идти через Lava и сохраняться с provider=`lava`.
