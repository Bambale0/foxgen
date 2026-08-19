# NEUROMIX Media: Cloudflare Free + Nginx + `static/uploads`

## 1. Цель

Отдавать публичные media-файлы NEUROMIX без отдельного платного storage/CDN-сервиса:

- файлы остаются в backend-папке `static/uploads`;
- Nginx отдаёт файлы напрямую, без передачи тела через Python;
- Cloudflare Free проксирует и кеширует публичную ленту;
- сетка использует WebP-превью примерно 50–200 КБ;
- приватные и временные uploads не получают годовой public cache;
- HTTP/3 можно временно отключить для проверки VPN-проблем.

## 2. Production topology

```text
/root/tanya/banano_kling/static/uploads
        │ существующее backend storage
        │
        ▼ bind mount, без копирования
/var/www/media.chillcreative.ru/uploads
        │
        ▼ Nginx static origin на 144.76.188.75
https://media.chillcreative.ru
        │
        ▼ Cloudflare Free
Telegram Mini App / браузер
```

| Компонент | Значение |
| --- | --- |
| Backend/media origin IP | `144.76.188.75` |
| Media domain | `media.chillcreative.ru` |
| Project | `/root/tanya/banano_kling` |
| Upload source | `/root/tanya/banano_kling/static/uploads` |
| Nginx-readable mount | `/var/www/media.chillcreative.ru/uploads` |
| Backend service | `banano-kling.service` |
| Required branch | `tanyapi` |
| Frontend | `https://cdn.chillcreative.ru/mini-app/` |

## 3. Почему нужен bind mount

Nginx worker обычно не может проходить через `/root`. Нельзя решать это ослаблением прав `/root`.

Используется постоянный bind mount:

```text
/root/tanya/banano_kling/static/uploads
-> /var/www/media.chillcreative.ru/uploads
```

Это те же файлы и inode/storage, а не копия.

Преимущества:

- backend продолжает писать в привычный путь;
- Nginx читает из безопасного public parent;
- не требуется синхронизация каталогов;
- файлы не удваиваются на диске;
- mount можно сохранить в `/etc/fstab`.

## 4. DNS и Cloudflare

Создать запись:

```text
Type: A
Name: media
Content: 144.76.188.75
TTL: Auto
Proxy status: Proxied
```

Оранжевое облако обязательно для Cloudflare cache headers и edge delivery.

Не создавать origin AAAA record, если на origin нет корректно настроенного IPv6. Cloudflare proxied A record всё равно может обслуживать IPv6-клиентов на edge.

## 5. Cloudflare API Token

Рекомендуемые permissions для зоны `chillcreative.ru`:

- Zone → Zone → Read;
- Zone → DNS → Edit;
- Zone → Zone Settings → Edit;
- Zone → Cache Rules → Edit.

Сохранение:

```bash
install -d -m 700 /root/.secrets
install -m 600 /dev/null /root/.secrets/cloudflare-media.token
nano /root/.secrets/cloudflare-media.token
```

Файл должен содержать только token.

Не использовать Global API Key, если достаточно ограниченного token.

## 6. SSL/TLS

Origin использует Let’s Encrypt certificate для `media.chillcreative.ru`.

Cloudflare SSL/TLS mode:

```text
Full (strict)
```

Не использовать Flexible: он создаёт небезопасную и трудно диагностируемую схему Cloudflare HTTPS -> origin HTTP.

Certbot может использовать:

- DNS-01 через Cloudflare token;
- HTTP-01 как fallback, если DNS/proxy/challenge route позволяют.

При HTTP-01 до первого выпуска сертификата убедиться, что ACME challenge не ломается redirect/WAF rule.

## 7. Автоматический deploy

```bash
cd /root/tanya/banano_kling

git fetch --prune origin tanyapi
git switch tanyapi
git reset --hard origin/tanyapi

chmod +x scripts/deploy_media_origin.sh

LETSENCRYPT_EMAIL='admin@example.com' \
ORIGIN_IPV4='144.76.188.75' \
sudo -E bash scripts/deploy_media_origin.sh
```

Скрипт должен остановиться, если текущая ветка не `tanyapi`.

## 8. Что делает deploy script

1. Проверяет root и required commands.
2. Проверяет project dir и `static/uploads`.
3. Проверяет текущую Git branch.
4. Устанавливает/проверяет Nginx, Certbot, curl, jq и DNS tools.
5. Создаёт backup старой Nginx configuration.
6. Создаёт public mount directory.
7. Добавляет bind mount и запись `/etc/fstab` без дублей.
8. Создаёт HTTP Nginx server для ACME/origin bootstrap.
9. Выпускает или переиспользует certificate.
10. Устанавливает HTTPS server block.
11. Проверяет `nginx -t` перед reload.
12. Создаёт renewal hook для reload Nginx.
13. Обновляет Cloudflare A record и proxy status при наличии token.
14. Отключает HTTP/3 на время диагностики, если разрешено.
15. Создаёт/обновляет Cache Rule для публичной ленты.
16. Устанавливает `STATIC_BASE_URL=https://media.chillcreative.ru`.
17. Перезапускает backend service и проверяет active state.
18. Создаёт WebP-превью существующей ленты при `BACKFILL_WEBP=1`.
19. Выполняет TLS, origin, Cloudflare и cache smoke tests.

## 9. Cache policy

### Публичная лента

Path:

```text
/uploads/feed/*
```

Origin response:

```text
Cache-Control: public, max-age=31536000, s-maxage=31536000, immutable
```

Условие безопасности: filename должен быть content-addressed/unique или никогда не перезаписываться другим содержимым.

Если файл может измениться по тому же URL, не использовать immutable — менять filename/version.

### WebP thumbnails

Path:

```text
/uploads/feed/thumbs/*.webp
```

Рекомендуется та же cache policy, что для публичной feed media.

### Остальные uploads

Path:

```text
/uploads/*
```

за исключением публичного feed.

Рекомендуемый response:

```text
Cache-Control: no-store
```

Причина: пользовательские референсы, временные загрузки или файлы с неявной приватностью нельзя кешировать на public edge на год.

## 10. Cloudflare Cache Rule

Expression:

```text
(http.host eq "media.chillcreative.ru" and
 starts_with(http.request.uri.path, "/uploads/feed/"))
```

Actions:

```text
Cache eligibility: Eligible for cache
Edge TTL: Respect origin
Browser TTL: Respect origin
```

Не применять blanket `Cache Everything` ко всему `/uploads/*`.

## 11. HTTP/3

На время проверки проблемных VPN HTTP/3 можно отключить в Cloudflare.

Проверка рекламы HTTP/3:

```bash
curl -sSI https://media.chillcreative.ru/uploads/feed/<real-file.webp> \
  | grep -i '^alt-svc:'
```

Если header содержит `h3`, настройка ещё активна или не распространилась.

Отключение HTTP/3 — диагностический шаг, а не постоянное решение любой проблемы сети.

## 12. WebP previews

Preview builder:

```text
scripts/build_media_previews.py
```

Цели:

- ограничить dimensions;
- использовать WebP;
- подобрать quality;
- стремиться к размеру 50–200 КБ;
- сохранять atomically;
- не повреждать original;
- не пересоздавать без необходимости.

Размер 50–200 КБ — operational target. Очень сложное изображение может потребовать уменьшения dimensions или lower quality.

Проверка размеров:

```bash
find static/uploads/feed/thumbs \
  -type f \
  -name '*.webp' \
  -printf '%s %p\n' \
  | sort -nr \
  | head -n 50
```

## 13. Nginx behavior

Nginx должен:

- обслуживать только ожидаемый host;
- отдавать `/uploads/` из public mount;
- использовать `sendfile`;
- поддерживать range requests;
- отдавать правильный content type;
- добавлять cache headers по классу path;
- добавлять `X-Content-Type-Options: nosniff`;
- при необходимости CORS для публичной media;
- не индексировать directory listing;
- возвращать 404 для отсутствующих файлов;
- не передавать file body через Python.

## 14. Проверка mount

```bash
findmnt /var/www/media.chillcreative.ru/uploads
mountpoint /var/www/media.chillcreative.ru/uploads
```

Сравнение source и target:

```bash
SOURCE=/root/tanya/banano_kling/static/uploads
TARGET=/var/www/media.chillcreative.ru/uploads

stat "$SOURCE"
stat "$TARGET"
ls -la "$TARGET" | head
```

После reboot:

```bash
sudo mount -a
findmnt /var/www/media.chillcreative.ru/uploads
```

## 15. Проверка Nginx

```bash
sudo nginx -t
sudo systemctl is-active nginx
sudo systemctl status nginx --no-pager
```

Local origin test с Host header до Cloudflare:

```bash
curl -k --resolve media.chillcreative.ru:443:127.0.0.1 \
  -sSI \
  https://media.chillcreative.ru/uploads/feed/<real-file.webp>
```

Использовать `-k` только для узкой local diagnostic, если certificate resolution вызывает проблему. Обычные public tests должны проверять certificate.

## 16. Public diagnostics

### DNS

```bash
dig +short A media.chillcreative.ru
dig +short AAAA media.chillcreative.ru
```

При proxied record будут видны Cloudflare edge IP, а не origin IP.

### Headers

```bash
curl --http2 -sSI \
  https://media.chillcreative.ru/uploads/feed/<real-file.webp>
```

### Cache warm-up

```bash
URL='https://media.chillcreative.ru/uploads/feed/<real-file.webp>'

curl -sSI "$URL" | grep -Ei 'HTTP/|cache-control|cf-cache-status|age|cf-ray|alt-svc'
sleep 2
curl -sSI "$URL" | grep -Ei 'HTTP/|cache-control|cf-cache-status|age|cf-ray|alt-svc'
```

### Полный diagnostic script

```bash
bash scripts/check_media_delivery.sh \
  https://media.chillcreative.ru/uploads/feed/<real-file.webp>
```

## 17. IPv4/IPv6 и VPN

Проверка IPv4:

```bash
curl -4 -o /dev/null -sS \
  -w 'dns=%{time_namelookup} connect=%{time_connect} tls=%{time_appconnect} ttfb=%{time_starttransfer} total=%{time_total}\n' \
  https://media.chillcreative.ru/uploads/feed/<real-file.webp>
```

Проверка IPv6:

```bash
curl -6 -o /dev/null -sS \
  -w 'dns=%{time_namelookup} connect=%{time_connect} tls=%{time_appconnect} ttfb=%{time_starttransfer} total=%{time_total}\n' \
  https://media.chillcreative.ru/uploads/feed/<real-file.webp>
```

Не делать вывод по одному VPN. Сравнивать:

- direct network;
- несколько VPN locations/providers;
- IPv4 vs IPv6;
- HTTP/2 vs HTTP/3;
- DNS/connect/TLS/TTFB;
- Cloudflare Ray/colo.

## 18. Environment variables deploy script

| Variable | Default/meaning |
| --- | --- |
| `DOMAIN` | `media.chillcreative.ru` |
| `ZONE_NAME` | `chillcreative.ru` |
| `ORIGIN_IPV4` | `144.76.188.75` |
| `PROJECT_DIR` | `/root/tanya/banano_kling` |
| `UPLOADS_DIR` | `<PROJECT_DIR>/static/uploads` |
| `APP_SERVICE` | `banano-kling.service` |
| `CF_API_TOKEN_FILE` | `/root/.secrets/cloudflare-media.token` |
| `BACKFILL_WEBP` | `1` |
| `RUN_RENEWAL_DRY_RUN` | `1` |

Пример ускоренного повторного запуска:

```bash
BACKFILL_WEBP=0 \
RUN_RENEWAL_DRY_RUN=0 \
sudo -E bash scripts/deploy_media_origin.sh
```

## 19. Idempotency

Повторный запуск не должен:

- создавать duplicate DNS records;
- дублировать `/etc/fstab` entry;
- создавать duplicate Cache Rules;
- перевыпускать действующий certificate без причины;
- копировать uploads;
- перезаписывать working Nginx config без backup;
- ломать существующие thumbnails.

## 20. Backup и rollback

Backup Nginx создаётся в root-only каталоге вида:

```text
/root/nginx-backups/media.chillcreative.ru-YYYYMMDD-HHMMSS/
```

Rollback:

1. выбрать последний проверенный backup;
2. восстановить site config;
3. выполнить `nginx -t`;
4. reload Nginx;
5. проверить local origin;
6. проверить public Cloudflare URL;
7. не удалять bind mount/source uploads.

Если проблема только в Cloudflare:

- временно переключить record в DNS-only для origin test;
- проверить certificate и Nginx напрямую;
- вернуть proxied mode;
- проверить cache rule и headers.

Не оставлять DNS-only без понимания потери edge cache и раскрытия origin IP.

## 21. Частые ошибки

### 404

- неверный URL path;
- файл отсутствует;
- неправильный Nginx alias/root;
- mount не активен.

### 403

- Nginx не читает mount;
- права target;
- security policy;
- WAF rule.

### `CF-Cache-Status: DYNAMIC`

- path не совпал с Cache Rule;
- origin отдал `no-store`;
- proxy выключен;
- request не cacheable.

### `CF-Cache-Status: MISS`

Нормально для первого запроса. Повторить запрос и проверить edge behavior.

### Backend URL всё ещё старый

Проверить:

```bash
grep '^STATIC_BASE_URL=' /root/tanya/banano_kling/.env
```

Не печатать весь `.env`.

## 22. Definition of done

- [ ] DNS proxied;
- [ ] SSL Full (strict);
- [ ] certificate valid;
- [ ] Nginx config test successful;
- [ ] bind mount active и persistent;
- [ ] real feed file returns 200;
- [ ] content type correct;
- [ ] feed cache-control public immutable;
- [ ] non-feed uploads no-store;
- [ ] second request has expected Cloudflare cache behavior;
- [ ] HTTP/3 state соответствует плану диагностики;
- [ ] IPv4 работает;
- [ ] IPv6 client path проверен через Cloudflare;
- [ ] WebP thumbnails созданы;
- [ ] backend `STATIC_BASE_URL` установлен;
- [ ] backend service active;
- [ ] Mini App показывает thumbnails и открывает originals.
