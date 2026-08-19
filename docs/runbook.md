# Runbook NEUROMIX

## 1. Production inventory

| Компонент | Значение |
| --- | --- |
| Backend host | `144.76.188.75` |
| Backend domain | `tanyapi.chillcreative.ru` |
| Backend project | `/root/tanya/banano_kling` |
| Backend branch | `tanyapi` |
| Backend service | `banano-kling.service` |
| Backend local health | `http://127.0.0.1:1888/health` |
| Frontend host | `91.200.84.187` |
| Frontend domain | `cdn.chillcreative.ru` |
| Frontend public URL | `https://cdn.chillcreative.ru/mini-app/` |
| Frontend remote profile | `tanyafrontend` |
| Media domain | `media.chillcreative.ru` |
| Media source | `/root/tanya/banano_kling/static/uploads` |

## 2. Ежедневная проверка backend

```bash
sudo systemctl is-active banano-kling.service
sudo systemctl status banano-kling.service --no-pager
curl -fsS http://127.0.0.1:1888/health
curl -fsS https://tanyapi.chillcreative.ru/health
```

Проверка restart count:

```bash
systemctl show banano-kling.service \
  -p ActiveState \
  -p SubState \
  -p MainPID \
  -p NRestarts \
  -p MemoryCurrent
```

## 3. Логи backend

Последние сообщения:

```bash
journalctl -u banano-kling.service -n 200 --no-pager
```

Live tail:

```bash
journalctl -u banano-kling.service -f
```

Если file logging включён:

```bash
tail -n 200 /root/tanya/banano_kling/logs/bot.log
tail -f /root/tanya/banano_kling/logs/bot.log
```

Не отправлять логи целиком без очистки tokens, URLs с signatures, user data и payment payloads.

## 4. Burst-autoban anti-fraud

Партнёрский антифрод теперь автоматически банит владельца рефкода, если по нему за короткое окно приходит аномально плотная пачка новых рефералов.

Текущие runtime-пороги задаются env-переменными:

```text
REFERRAL_ANTIFRAUD_BURST_WINDOW_SECONDS
REFERRAL_ANTIFRAUD_BURST_MAX
```

По умолчанию production считает suspicious burst как `6` привязок за `10` секунд.

Что проверять оператору:

1. открыть админку `Партнёры -> Burst autobans`;
2. открыть карточку партнёра по кнопке из списка;
3. сверить `referral_code`, `visitor_telegram_id`, `source`, `start_param`;
4. при необходимости выгрузить deeper evidence через SQL по `referral_events`.

Быстрый SQL:

```sql
SELECT created_at, visitor_telegram_id, clicked_code, source, start_param
FROM referral_events
WHERE reason = 'burst_autoban'
ORDER BY created_at DESC
LIMIT 50;
```

## 5. Безопасное обновление backend

```bash
cd /root/tanya/banano_kling

git fetch --prune origin tanyapi
git switch tanyapi

git status --short
```

Если working tree чистый:

```bash
git reset --hard origin/tanyapi
git log -1 --oneline
```

Проверки:

```bash
. venv/bin/activate
python -m pytest
python -m py_compile $(find bot tests scripts -name '*.py')
```

Перезапуск:

```bash
sudo systemctl restart banano-kling.service
sudo systemctl is-active banano-kling.service
curl -fsS http://127.0.0.1:1888/health
journalctl -u banano-kling.service -n 100 --no-pager
```

## 6. Frontend deploy

### Deploy

```bash
cd /root/tanya/banano_kling

git fetch --prune origin tanyapi
git switch tanyapi
git reset --hard origin/tanyapi

git log -1 --oneline
sudo bash cdn.sh --remote-deploy tanyafrontend
```

Дождаться полного завершения. Только затем:

```bash
sudo bash cdn.sh --remote-status tanyafrontend
```

### Frontend smoke

```bash
curl -fsSI https://cdn.chillcreative.ru/mini-app/
curl -fsS https://cdn.chillcreative.ru/mini-app/ \
  | grep -o '<title>[^<]*</title>'
```

Ожидаемый title:

```html
<title>NEUROMIX</title>
```

### API proxy smoke

```bash
curl -i -X POST \
  https://cdn.chillcreative.ru/mini-app/api/bootstrap \
  -H 'Content-Type: application/json' \
  --data '{}'
```

Нормально: auth error `400/401/403`.

Ненормально:

- `502` — frontend Nginx не достучался до backend;
- `504` — timeout upstream;
- HTML вместо JSON — неверный route;
- redirect loop — ошибка Nginx/base path.

## 7. Frontend deploy logs

На операторском/backend host:

```bash
tail -n 200 /var/log/banano-miniapp-cdn.log
```

На frontend host:

```bash
ssh root@91.200.84.187 '
  tail -n 200 /var/log/banano-miniapp-cdn.log 2>/dev/null || true
  LAST=$(ls -t /root/.npm/_logs/*.log 2>/dev/null | head -n1)
  [ -n "$LAST" ] && tail -n 200 "$LAST" || true
'
```

## 8. Media checks

Найти реальный публичный файл в `static/uploads/feed` и проверить:

```bash
bash scripts/check_media_delivery.sh \
  https://media.chillcreative.ru/uploads/feed/<real-file.webp>
```

Либо вручную:

```bash
curl -sSI https://media.chillcreative.ru/uploads/feed/<real-file.webp>
curl -sSI https://media.chillcreative.ru/uploads/feed/<real-file.webp>
```

Проверить:

- status 200;
- `content-type` соответствует файлу;
- `cache-control` публичный только для feed;
- `cf-cache-status` становится HIT после прогрева, если rule применима;
- `age` растёт;
- `cf-ray` присутствует;
- `alt-svc` не рекламирует h3, если HTTP/3 временно отключён.

## 9. Проверка bind mount media

```bash
findmnt /var/www/media.chillcreative.ru/uploads
mountpoint /var/www/media.chillcreative.ru/uploads
ls -la /var/www/media.chillcreative.ru/uploads | head
```

Проверка записи backend и чтения Nginx:

```bash
test -d /root/tanya/banano_kling/static/uploads
sudo -u www-data test -r /var/www/media.chillcreative.ru/uploads
```

Не менять права `/root` ради Nginx. Использовать bind mount.

## 10. Nginx checks

### Backend/media host

```bash
sudo nginx -t
sudo systemctl status nginx --no-pager
sudo journalctl -u nginx -n 100 --no-pager
```

### Frontend host

```bash
ssh root@91.200.84.187 '
  nginx -t
  systemctl is-active nginx
  systemctl status nginx --no-pager
'
```

## 10. TLS checks

```bash
openssl s_client \
  -connect cdn.chillcreative.ru:443 \
  -servername cdn.chillcreative.ru \
  -verify_return_error </dev/null

openssl s_client \
  -connect media.chillcreative.ru:443 \
  -servername media.chillcreative.ru \
  -verify_return_error </dev/null
```

Certbot renewal dry-run на нужном host:

```bash
sudo certbot renew --dry-run --no-random-sleep-on-renew
```

## 11. Telegram smoke checklist

После frontend/backend deploy полностью закрыть Mini App и открыть заново.

Проверить:

- loader NEUROMIX отображается сразу;
- Telegram gate не мигает при нормальном входе;
- приложение открывается без пустого экрана;
- bootstrap загружает пользователя и баланс;
- история задач видна;
- фото/видео/референс загружаются;
- тестовая генерация создаёт task;
- pending обновляется до completed/failed;
- публикация предлагает корректный scope;
- feed/profile открывают media;
- превью загружается быстро, оригинал открывается отдельно.

## 12. Backup routines

### `.env`

```bash
install -d -m 700 /root/backups/neuromix
cp -a /root/tanya/banano_kling/.env \
  "/root/backups/neuromix/env-$(date +%Y%m%d-%H%M%S)"
chmod 600 /root/backups/neuromix/env-*
```

### Database

Использовать проектные backup scripts после чтения `docs/migration.md`. Проверить, что backup не пустой и может быть прочитан.

### Frontend

`cdn.sh`/installer создаёт release backup перед заменой файлов. Не удалять backup до post-deploy Telegram smoke.

### Nginx media

`deploy_media_origin.sh` сохраняет предыдущую конфигурацию в root-only backup directory.

## 13. Restart policy

### Backend

```bash
sudo systemctl restart banano-kling.service
```

Не использовать restart loop. Если сервис сразу падает:

```bash
sudo systemctl stop banano-kling.service
journalctl -u banano-kling.service -n 300 --no-pager
```

Сначала исправить config/code, затем start.

### Nginx

Предпочтительно reload после успешного test:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

## 14. Incident priorities

### P1

- бот и backend полностью недоступны;
- платежи подтверждаются провайдером, но не зачисляются массово;
- data corruption;
- публичный секрет раскрыт;
- Mini App недоступен всем пользователям.

### P2

- отдельный provider не работает;
- media недоступны части сетей;
- frontend deploy не проходит, но старая версия работает;
- отдельный пользовательский flow сломан.

### P3

- некритичная UI-ошибка;
- неверный текст;
- отдельный preview не создан;
- deprecated dependency warning без runtime impact.

## 15. Что не делать во время инцидента

- не удалять `static/uploads`;
- не запускать `rsync --delete` на frontend без rollback plan;
- не открывать `1888/tcp` всему интернету;
- не отключать TLS verification между frontend и backend;
- не публиковать `.env`;
- не очищать npm cache и все backups одновременно;
- не перезапускать сервис бесконечно без чтения логов;
- не считать `401` bootstrap без initData поломкой.

## 16. Связанные документы

- [production-deployment.md](production-deployment.md);
- [miniapp-frontend-deployment.md](miniapp-frontend-deployment.md);
- [troubleshooting.md](troubleshooting.md);
- [environment.md](environment.md);
- [../ops/media/README.md](../ops/media/README.md).
