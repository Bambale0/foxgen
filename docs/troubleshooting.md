# Troubleshooting NEUROMIX

## 1. Метод диагностики

Всегда разделяйте проблему на слой:

1. Telegram client/WebView;
2. frontend HTML/CSS/JS;
3. frontend Nginx/proxy;
4. backend public Nginx/TLS;
5. aiohttp runtime;
6. database/Redis;
7. provider/payment API;
8. media/Cloudflare/origin.

Не начинайте с массового restart или очистки файлов. Сначала определите слой.

## 2. Frontend deploy завис на `npm ci`

### Симптом

Последняя строка похожа на:

```text
Installing locked frontend dependencies
npm warn deprecated ...
```

и долго нет нового вывода.

`deprecated` warning сам по себе не является ошибкой.

### Проверить процессы

```bash
ssh root@91.200.84.187 '
ps -eo pid,ppid,etime,%cpu,%mem,stat,cmd \
  | grep -E "[n]pm ci|[n]ode|[n]ext build|install_miniapp|[c]dn.sh"
'
```

### Проверить ресурсы

```bash
ssh root@91.200.84.187 '
free -h
df -h /
df -i /
'
```

### Проверить registry

```bash
ssh root@91.200.84.187 '
getent hosts registry.npmjs.org
curl -4 -I --connect-timeout 10 --max-time 20 https://registry.npmjs.org/
npm config get registry
'
```

Ожидаемый registry:

```text
https://registry.npmjs.org/
```

### Npm logs

```bash
ssh root@91.200.84.187 '
LAST=$(ls -t /root/.npm/_logs/*.log 2>/dev/null | head -n1)
[ -n "$LAST" ] && tail -n 200 "$LAST" || echo "npm log not found"
'
```

### Безопасно остановить зависший install

```bash
ssh root@91.200.84.187 '
PIDS=$(pgrep -f "npm ci" || true)
if [ -n "$PIDS" ]; then
  kill -TERM $PIDS
  sleep 5
  kill -KILL $PIDS 2>/dev/null || true
fi
'
```

### Ручная проверка

```bash
ssh root@91.200.84.187 '
set -e
cd /opt/banano-kling-src/frontend/miniapp-v0
rm -rf node_modules
npm cache verify
npm ci --no-audit --no-fund --foreground-scripts --loglevel verbose
'
```

Если ручной install успешен, повторить normal remote deploy.

## 3. После `Ctrl+C` получена ошибка строки 562, код 255

Это типичный результат прерванной SSH-команды `cdn.sh`.

```text
Ошибка на строке 562, код 255
```

Код `255` в этом контексте означает, что SSH session завершилась с ошибкой или была прервана пользователем. Он не доказывает отдельную ошибку приложения.

После прерывания:

1. проверить оставшиеся процессы на frontend host;
2. остановить только зависший `npm ci`, если он остался;
3. проверить текущую опубликованную версию;
4. изучить `/var/log/banano-miniapp-cdn.log`;
5. повторить deploy после устранения причины.

## 4. Frontend deploy завершился, но видна старая версия

### Причины

- Telegram WebView держит старый document;
- Cloudflare/browser cache;
- deploy собрал старый commit;
- checkout frontend host не обновился;
- HTML обновился, но старые assets ещё в памяти WebView.

### Проверить commit

```bash
sudo bash cdn.sh --remote-status tanyafrontend
```

Либо:

```bash
ssh root@91.200.84.187 '
git -C /opt/banano-kling-src branch --show-current
git -C /opt/banano-kling-src log -1 --oneline
'
```

### Проверить title снаружи

```bash
curl -fsS https://cdn.chillcreative.ru/mini-app/ \
  | grep -o '<title>[^<]*</title>'
```

Если curl показывает NEUROMIX, а Telegram — старое, полностью закрыть Mini App и открыть снова. Иногда требуется закрыть сам Telegram client.

## 5. Белый или пустой экран Mini App

### Проверить HTML

```bash
curl -fsSI https://cdn.chillcreative.ru/mini-app/
```

### Проверить assets из текущего HTML

```bash
curl -fsS https://cdn.chillcreative.ru/mini-app/ \
  | grep -oE '/mini-app/_next/static/[^" ]+\.(js|css)' \
  | sort -u
```

Каждый asset должен отвечать `200`.

### Частая причина

Старая WebView-сессия загрузила старый HTML, а deploy удалил старые hashed chunks. Поэтому обычный deploy не должен использовать `rsync --delete`.

## 6. Бесконечный loader NEUROMIX

Проверить:

- загружен ли `telegram-web-app.js`;
- получает ли frontend Telegram `initData`;
- отвечает ли bootstrap;
- нет ли JS exception;
- нет ли 404 на chunks;
- нет ли backend timeout.

API proxy smoke:

```bash
curl -i -X POST \
  https://cdn.chillcreative.ru/mini-app/api/bootstrap \
  -H 'Content-Type: application/json' \
  --data '{}'
```

Auth error ожидаем. `502/504` означает инфраструктурную проблему.

Backend logs:

```bash
journalctl -u banano-kling.service -n 200 --no-pager
```

## 7. На секунду появляется Telegram gate

Нормальная логика:

- пока `state.isLoading=true`, показывается `MiniAppLoader`;
- gate появляется только после завершённой неуспешной проверки входа.

Если gate мигает:

- убедиться, что deployed commit содержит отдельный `mini-app-loader.tsx`;
- проверить, что shell проверяет `state.isLoading` до `mode === locked`;
- исключить старый frontend cache;
- проверить current HTML/assets commit.

## 8. Bootstrap возвращает 401

## 9. Подозрение на реферальную накрутку

### Симптом

- у партнёра пачками появляются рефералы за секунды;
- в логах появляются `reason=hourly_limit`, `reason=daily_limit` или `reason=burst_autoban`;
- админы получают alert `Автобан по реферальному антифроду`.

### Что смотреть

1. Telegram admin UI: `Партнёры -> Burst autobans`;
2. карточку партнёра и его `referral_code`;
3. последние события в `referral_events`;
4. связанный `source` и `start_param`.

### Проверка в БД

```sql
SELECT created_at, visitor_telegram_id, clicked_referrer_id, clicked_code, reason, source, start_param
FROM referral_events
WHERE clicked_referrer_id = <user_id>
ORDER BY created_at DESC
LIMIT 100;
```

### Интерпретация

- `source=start` и `start_param=ref_CODE` обычно означает прямой deep link `/start ref_CODE`;
- `burst_autoban` означает, что партнёр уже автоматически заблокирован;
- `blocked_referrer` после этого означает повторные попытки по уже забаненному партнёру.

### Дальше

- проверить, не попал ли под бан честный burst из внешней рекламы;
- если это false positive, снять бан вручную через админку пользователя;
- если это накрутка, оставить бан и при необходимости добавить код в `REFERRAL_ANTIFRAUD_BLOCK_CODES`.

### Нормально

- запрос сделан через curl без Telegram `initData`;
- Mini App открыт обычной ссылкой без browser auth.

### Ненормально

- Mini App открыт внутри Telegram, но initData пустой/невалидный;
- BOT_TOKEN не соответствует боту, который открыл Mini App;
- системное время backend сильно отличается;
- frontend не отправляет auth payload;
- Nginx удаляет нужные headers/body.

Проверить время:

```bash
timedatectl status
```

## 9. Frontend API возвращает 502

Проверить backend public health:

```bash
curl -v https://tanyapi.chillcreative.ru/health
```

Проверить frontend Nginx config:

```bash
ssh root@91.200.84.187 'nginx -t'
```

Проверить SNI/Host upstream и TLS verification. Secure frontend installer должен проксировать на HTTPS backend domain, а не raw IP:1888.

## 10. Backend service не запускается

```bash
systemctl status banano-kling.service --no-pager
journalctl -u banano-kling.service -n 300 --no-pager
```

Проверить:

- syntax errors;
- missing env;
- занятый port;
- database connection;
- import errors;
- permissions;
- invalid provider configuration на startup.

Port:

```bash
ss -ltnp | grep ':1888'
```

Python syntax:

```bash
cd /root/tanya/banano_kling
. venv/bin/activate
python -m py_compile $(find bot tests scripts -name '*.py')
```

## 11. Webhook Telegram не приходит

Проверить public endpoint и Nginx logs. Убедиться, что Cloudflare/proxy settings не ломают POST.

Проверить webhook info через Telegram API безопасным способом без публикации token в истории. Token лучше читать из env внутри локального script.

Проверить:

- `WEBHOOK_HOST`;
- `WEBHOOK_PATH`;
- TLS certificate;
- Nginx route;
- backend service;
- firewall;
- allowed updates и secret token, если используется.

## 12. Media URL 404

Проверить наличие файла в source:

```bash
test -f /root/tanya/banano_kling/static/uploads/<path>
```

Проверить bind mount:

```bash
findmnt /var/www/media.chillcreative.ru/uploads
```

Проверить путь через mount:

```bash
test -f /var/www/media.chillcreative.ru/uploads/<path>
```

Проверить Nginx alias/root semantics и trailing slash.

## 13. Media 403

Причины:

- Nginx worker не может читать target;
- bind mount отсутствует;
- parent permissions;
- security module;
- Cloudflare rule/WAF.

Не выдавать `www-data` право прохода через `/root`. Восстановить bind mount в `/var/www/...`.

## 14. `CF-Cache-Status: DYNAMIC` или `BYPASS`

Проверить:

- orange cloud включён;
- request host — `media.chillcreative.ru`;
- path соответствует `/uploads/feed/*`;
- origin не отдаёт `no-store` для feed;
- Cache Rule включена и expression корректно;
- cookies/auth headers не заставляют обходить cache;
- файл имеет cacheable response status/content.

Первый request может быть MISS. Повторный должен показать ожидаемое изменение статуса, если edge cache применим.

## 15. HTTP/3 всё ещё включён

Проверить:

```bash
curl -sSI https://media.chillcreative.ru/uploads/feed/<file> \
  | grep -i '^alt-svc:'
```

Если рекламируется `h3`, проверить Cloudflare Network settings и API token permissions. Изменение может применяться не мгновенно на всех edges.

## 16. Проблема только у части VPN

Собрать отдельно:

- DNS A/AAAA;
- IPv4 request;
- IPv6 request;
- HTTP/2 request;
- response headers;
- route trace пользователя;
- время DNS/connect/TLS/TTFB.

```bash
curl -4 -o /dev/null -sS \
  -w 'v4 dns=%{time_namelookup} connect=%{time_connect} tls=%{time_appconnect} ttfb=%{time_starttransfer} total=%{time_total}\n' \
  https://media.chillcreative.ru/uploads/feed/<file>

curl -6 -o /dev/null -sS \
  -w 'v6 dns=%{time_namelookup} connect=%{time_connect} tls=%{time_appconnect} ttfb=%{time_starttransfer} total=%{time_total}\n' \
  https://media.chillcreative.ru/uploads/feed/<file>
```

Если IPv6 не настроен на origin, не добавлять origin AAAA record. Cloudflare edge может обслуживать IPv6 пользователей при корректном proxied A record.

## 17. Превью слишком тяжёлые

Запустить preview builder на конкретной директории согласно help script. Проверить WebP output и фактический размер:

```bash
find static/uploads/feed/thumbs -type f -name '*.webp' -printf '%s %p\n' \
  | sort -nr \
  | head -n 30
```

Цель 50–200 КБ является практической, а не абсолютной: сложные изображения могут потребовать снижения dimensions/quality.

## 18. Результат в Telegram есть, в Mini App pending

Проверить:

- task ID совпадает;
- backend DB status обновлён;
- bootstrap/task-detail возвращает completed result;
- frontend sync работает при visible/focus;
- initData не истёк;
- media URL доступен.

Не подменять pending mock-данными: frontend должен показывать подтверждённое backend состояние.

## 19. Платёж pending

Проверить:

- активный `PAYMENT_PROVIDER`;
- transaction row;
- webhook route;
- signature validation;
- provider status;
- reconcile loop;
- idempotency marker.

Не начислять баланс вручную до сверки provider payment ID и существующих transactions.

## 20. Redis недоступен

```bash
redis-cli -u "$REDIS_URL" ping
```

Если runtime перешёл на memory fallback:

- бот может продолжить работу;
- активные FSM состояния будут потеряны при restart;
- multiple-instance runtime становится небезопасным.

## 21. Быстрый сбор диагностического пакета

```bash
{
  date -Is
  hostname
  git -C /root/tanya/banano_kling branch --show-current
  git -C /root/tanya/banano_kling log -1 --oneline
  systemctl show banano-kling.service -p ActiveState -p SubState -p NRestarts
  curl -sS -o /dev/null -w 'backend=%{http_code}\n' https://tanyapi.chillcreative.ru/health
  curl -sS -o /dev/null -w 'frontend=%{http_code}\n' https://cdn.chillcreative.ru/mini-app/
  nginx -t 2>&1
} | tee /tmp/neuromix-diagnostic.txt
```

Перед передачей файла проверить, что в нём нет secrets или персональных данных.
