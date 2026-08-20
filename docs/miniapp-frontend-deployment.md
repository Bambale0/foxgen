# NEUROMIX Mini App frontend deployment

## 1. Актуальная схема

| Компонент | Значение |
| --- | --- |
| Публичный URL | `https://cdn.chillcreative.ru/mini-app/` |
| Frontend server | `91.200.84.187` |
| Frontend web root | `/var/www/cdn.chillcreative.ru` |
| Source checkout на frontend | `/opt/banano-kling-src` |
| Source branch | `tanyapi` |
| Backend origin | `https://tanyapi.chillcreative.ru` |
| Remote deploy profile | `tanyafrontend` |
| Operator script | `/root/tanya/banano_kling/cdn.sh` |

Frontend является статическим Next.js export. Node.js используется только для install/build, но не для обслуживания production traffic.

## 2. Маршрутизация

Frontend Nginx должен обеспечивать:

```text
/                         -> redirect /mini-app/
/mini-app/                -> static export
/mini-app/api/*           -> HTTPS backend tanyapi.chillcreative.ru
/api/v1/*                 -> HTTPS backend при необходимости route contract
/frontend-health          -> local health response
```

Backend proxy должен:

- использовать HTTPS;
- передавать `Host: tanyapi.chillcreative.ru`;
- использовать SNI `tanyapi.chillcreative.ru`;
- проверять сертификат upstream;
- передавать forwarded headers;
- иметь timeout, достаточный для upload/generation API;
- не проксировать на публичный raw port `1888`.

Media ленты рекомендуется загружать напрямую с `media.chillcreative.ru`, а не проксировать тяжёлые файлы через frontend.

## 3. Cache policy

### HTML

```text
Cache-Control: no-cache, no-store, must-revalidate
```

HTML должен быстро обновляться после deploy.

### Hashed assets

```text
/mini-app/_next/static/*
Cache-Control: public, max-age=31536000, immutable
```

### Telegram bridge script

Можно использовать короткий cache TTL, но не годовой immutable, если имя файла не versioned.

### Почему нельзя удалять старые chunks сразу

Telegram WebView может держать HTML предыдущего release и после deploy запросить старые JS chunks. Если deploy использует `rsync --delete`, старый chunk исчезнет, WebView получит 404 и останется на loader/white screen.

Обычный deploy должен сохранять assets минимум предыдущих release. Удаление выполняется отдельной ротацией после безопасного окна.

## 4. Frontend source и build

Каталог:

```text
frontend/miniapp-v0
```

Build command из `package.json`:

```bash
npm run build
```

Он выполняет static export через:

```text
NEXT_EXPORT=1 next build --webpack
```

и затем patch Telegram head script.

Результат:

```text
frontend/miniapp-v0/out/index.html
```

## 5. Локальный pre-deploy gate

```bash
cd /root/tanya/banano_kling/frontend/miniapp-v0

npm ci
npm run lint
npm test
npm run build

test -f out/index.html
```

На production remote deploy installer может выполнять собственный gate. Локальная проверка полезна перед важным release, но не заменяет remote build.

`npm audit` рассматривается отдельно: warning не должен автоматически ломать emergency deploy, если installer profile не требует audit gate.

## 6. Remote profile `tanyafrontend`

`cdn.sh` хранит remote profiles в root-only state directory. Профиль содержит:

```text
REMOTE_NAME=tanyafrontend
REMOTE_SSH_HOST=root@91.200.84.187
REMOTE_SOURCE_DIR=/opt/banano-kling-src
REMOTE_DOMAIN=cdn.chillcreative.ru
REMOTE_BRANCH=tanyapi
REMOTE_USE_SUDO=0
```

Если используется не root user, выставить `REMOTE_USE_SUDO=1` и настроить ограниченный passwordless sudo для deploy-команд.

Проверить SSH:

```bash
ssh \
  -o BatchMode=yes \
  -o ConnectTimeout=15 \
  -o ServerAliveInterval=15 \
  -o ServerAliveCountMax=3 \
  root@91.200.84.187 \
  'echo SSH_OK'
```

## 7. Стандартный remote deploy

На backend/operator host:

```bash
cd /root/tanya/banano_kling

git fetch --prune origin tanyapi
git switch tanyapi
git reset --hard origin/tanyapi

git log -1 --oneline
sudo bash cdn.sh --remote-deploy tanyafrontend
```

Deploy выполняется синхронно. Терминал должен оставаться подключённым до финального сообщения.

После завершения отдельной командой:

```bash
sudo bash cdn.sh --remote-status tanyafrontend
```

Не запускать status через `&&` сразу после команды, которую планируется прервать вручную.

## 8. Что делает `--remote-deploy`

1. Загружает remote profile.
2. Подключается по SSH.
3. Проверяет наличие Git, curl, bash и checkout.
4. Проверяет отсутствие локальных изменений.
5. Выполняет `fetch --prune origin tanyapi`.
6. Переключается на `tanyapi`.
7. Делает hard reset до `origin/tanyapi`.
8. Запускает на frontend host:

   ```text
   cdn.sh --deploy-domain cdn.chillcreative.ru
   ```

9. Installer обновляет служебный checkout и выполняет build/deploy.
10. Проверяются `/frontend-health` и `/mini-app/`.
11. Печатается deployed commit.

## 9. Требования к clean checkout

Remote deploy прекращается, если в `/opt/banano-kling-src` есть local changes.

Проверка:

```bash
ssh root@91.200.84.187 '
git -C /opt/banano-kling-src status --short
'
```

Не выполнять автоматический `reset --hard`, пока не понятно происхождение изменений. Если это временные build artifacts, исправить `.gitignore` или удалить их осознанно.

## 10. Status command

```bash
sudo bash cdn.sh --remote-status tanyafrontend
```

Показывает:

- hostname;
- domain;
- commit;
- branch;
- наличие domain profile;
- состояние Nginx;
- frontend health;
- HTTP status Mini App.

Status не гарантирует, что Telegram auth и generation flow работают. Он проверяет инфраструктурную поверхность.

## 11. Логи

### Operator/backend host

```bash
tail -n 200 /var/log/banano-miniapp-cdn.log
```

### Frontend host

```bash
ssh root@91.200.84.187 '
tail -n 200 /var/log/banano-miniapp-cdn.log 2>/dev/null || true
'
```

### Npm

```bash
ssh root@91.200.84.187 '
LAST=$(ls -t /root/.npm/_logs/*.log 2>/dev/null | head -n1)
[ -n "$LAST" ] && tail -n 200 "$LAST" || echo "No npm logs"
'
```

### Nginx

```bash
ssh root@91.200.84.187 '
nginx -t
journalctl -u nginx -n 100 --no-pager
'
```

## 12. Зависание `npm ci`

`npm warn deprecated` — warning, а не причина остановки.

### Проверить процесс

```bash
ssh root@91.200.84.187 '
ps -eo pid,ppid,etime,%cpu,%mem,stat,cmd \
  | grep -E "[n]pm ci|[n]ode|[n]ext build|install_miniapp|[c]dn.sh"
'
```

### Проверить RAM/disk/network

```bash
ssh root@91.200.84.187 '
free -h
df -h /
df -i /
getent hosts registry.npmjs.org
curl -4 -I --connect-timeout 10 --max-time 20 https://registry.npmjs.org/
npm config get registry
'
```

### Остановить только зависший install

```bash
ssh root@91.200.84.187 '
PIDS=$(pgrep -f "npm ci" || true)
[ -z "$PIDS" ] || kill -TERM $PIDS
sleep 5
[ -z "$PIDS" ] || kill -KILL $PIDS 2>/dev/null || true
'
```

### Ручной verbose install

```bash
ssh root@91.200.84.187 '
set -e
cd /opt/banano-kling-src/frontend/miniapp-v0
rm -rf node_modules
npm cache verify
npm ci --no-audit --no-fund --foreground-scripts --loglevel verbose
'
```

После исправления повторить normal deploy.

## 13. Что означает code 255 после Ctrl+C

`cdn.sh` запускает remote SSH command. При ручном `Ctrl+C` SSH завершается с code 255, а trap печатает строку ошибки.

Это ожидаемое следствие прерывания. После него нужно проверить, не остались ли удалённые процессы.

Не считать code 255 доказательством ошибки Nginx, build или приложения без чтения remote logs.

## 14. Post-deploy checks

### HTML

```bash
curl -fsSI https://cdn.chillcreative.ru/mini-app/
```

### Brand

```bash
curl -fsS https://cdn.chillcreative.ru/mini-app/ \
  | grep -o '<title>[^<]*</title>'
```

Ожидается `NEUROMIX`.

### Current asset

```bash
ASSET=$(curl -fsS https://cdn.chillcreative.ru/mini-app/ \
  | grep -oE '/mini-app/_next/static/[^" ]+\.(js|css)' \
  | head -n1)

curl -fsSI "https://cdn.chillcreative.ru${ASSET}"
```

### API boundary

```bash
curl -i -X POST \
  https://cdn.chillcreative.ru/mini-app/api/bootstrap \
  -H 'Content-Type: application/json' \
  --data '{}'
```

Ожидается auth error, а не proxy error.

## 15. Telegram checks

Полностью закрыть Mini App и открыть заново.

Проверить:

- loader содержит NEUROMIX;
- gate не мигает при нормальном Telegram входе;
- header содержит NEUROMIX;
- bootstrap успешен;
- tabs открываются;
- history и balance отображаются;
- upload и generation работают;
- media preview загружается;
- публикация и deep links работают.

## 16. Backup и rollback

Installer создаёт backup предыдущего release в каталоге, указанном domain profile.

Rollback через interactive `cdn.sh`:

1. выбрать домен;
2. выбрать проверенный backup;
3. подтвердить восстановление;
4. дождаться `rsync --delete` из backup в active root;
5. пройти Nginx и HTTP checks.

`--delete` допустим в rollback, потому что восстанавливается целостный проверенный release. Он не рекомендуется для обычного incremental deploy.

## 17. Первичная настройка frontend host

Первичная установка выполняется domain installer через `cdn.sh` и profile file. Не создавать Nginx config вручную, если installer уже управляет доменом.

Перед установкой:

- DNS указывает на `91.200.84.187`;
- port 80/443 доступны;
- checkout существует;
- backend HTTPS health работает;
- Certbot email задан;
- domain profile создан.

После установки:

```bash
nginx -t
systemctl is-active nginx
curl -fsS https://cdn.chillcreative.ru/frontend-health
curl -fsSI https://cdn.chillcreative.ru/mini-app/
```

## 18. Security

- SSH только по key authentication;
- remote profile mode `600`;
- frontend не хранит backend secrets;
- `NEXT_PUBLIC_*` не содержит secrets;
- upstream TLS verification включена;
- backend runtime port не публикуется наружу;
- backups root-only;
- Nginx config применяется только после test;
- не сохранять npm auth token в world-readable config.

## 19. Связанные документы

- [production-deployment.md](production-deployment.md);
- [runbook.md](runbook.md);
- [troubleshooting.md](troubleshooting.md);
- [../frontend/miniapp-v0/README.md](../frontend/miniapp-v0/README.md);
- [../ops/media/README.md](../ops/media/README.md).
