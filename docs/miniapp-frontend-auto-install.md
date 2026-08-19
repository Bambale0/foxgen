# Автоматическая установка отдельного Mini App frontend

Схема развёртывания:

```text
Telegram WebView
      ↓ HTTPS
frontend-domain:443 (Nginx + static export)
      ↓ HTTPS
backend-domain:443 (Nginx)
      ↓ HTTP localhost
127.0.0.1:1888 (aiohttp / banano-kling.service)
```

Frontend-сервер не подключается к порту aiohttp напрямую. Порт `1888` не открывается в интернет, а `WEBHOOK_BIND_HOST` не требуется менять на `0.0.0.0`.

Для production используется защищённая точка входа:

```text
scripts/install_miniapp_frontend_https_host.sh
```

Она запускает основной инсталлятор в ограниченном режиме и не позволяет случайно переключиться на прямой `http://IP:1888`.

Скрипт устанавливает на чистый Ubuntu-сервер:

- Nginx;
- Node.js 22;
- Certbot и TLS;
- UFW;
- исходники ветки `tanyapi`;
- production static export Mini App;
- HTTPS-проксирование `/mini-app/api/`, `/api/v1/`, `/uploads/` на публичный Nginx backend-сервера;
- обязательную проверку TLS-сертификата backend;
- SNI и `Host`, соответствующие backend-домену;
- immutable cache для hashed chunks и no-store для HTML;
- резервное копирование текущей сборки;
- smoke-проверки frontend, assets, TLS, backend `/health` и auth boundary.

## 1. DNS

Создайте A-запись нового frontend-домена на IPv4 frontend-сервера. Backend-домен уже должен вести на backend Nginx и иметь действующий публичный TLS-сертификат.

## 2. Конфигурация

```bash
cp deploy/miniapp-frontend.env.example /root/miniapp-frontend.env
nano /root/miniapp-frontend.env
chmod 600 /root/miniapp-frontend.env
```

Минимальная конфигурация:

```dotenv
FRONTEND_DOMAIN=app.example.ru
BACKEND_ORIGIN=https://api.example.ru
BACKEND_HOST_HEADER=api.example.ru
BACKEND_TLS_NAME=api.example.ru
CERTBOT_EMAIL=admin@example.ru
```

`BACKEND_ORIGIN` принимает только публичный HTTPS-домен на порту `443`. Значения вида `http://IP:1888` намеренно отклоняются.

Если репозиторий закрытый, заранее добавьте на сервер read-only GitHub deploy key:

```dotenv
REPO_URL=git@github.com:Bambale0/banano_kling.git
```

Пароль или GitHub token в конфигурационный файл не помещается.

## 3. Первая установка

```bash
sudo bash scripts/install_miniapp_frontend_https_host.sh \
  --config /root/miniapp-frontend.env \
  --install
```

## 4. Последующие обновления

```bash
sudo bash /opt/banano-kling-src/scripts/install_miniapp_frontend_https_host.sh \
  --config /root/miniapp-frontend.env \
  --deploy-only
```

Обновление выполняет `git fetch`, синхронизирует checkout с `origin/tanyapi`, запускает `npm ci`, lint и production build, затем копирует `out/` без `--delete`. Старые hashed chunks остаются доступны закешированным Telegram WebView.

## 5. Backend Nginx

На backend-сервере публичный домен должен принимать запросы на `443` и проксировать Mini App API внутрь:

```nginx
server {
    listen 443 ssl http2;
    server_name api.example.ru;

    ssl_certificate /etc/letsencrypt/live/api.example.ru/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.example.ru/privkey.pem;

    client_max_body_size 60M;

    location / {
        proxy_pass http://127.0.0.1:1888;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
    }
}
```

Aiohttp остаётся на:

```dotenv
WEBHOOK_BIND_HOST=127.0.0.1
```

или на текущем локальном bind-адресе. Открывать `1888/tcp` во внешнем firewall не нужно.

## 6. Автонастройка backend

При наличии SSH-ключа можно добавить:

```dotenv
BACKEND_SSH_HOST=root@203.0.113.10
BACKEND_ENV_FILE=/root/tanya/banano_kling/.env
BACKEND_SERVICE=banano-kling.service
```

Защищённый entrypoint только:

- сохранит backup `.env`;
- установит `MINI_APP_URL=https://FRONTEND_DOMAIN/mini-app/`;
- перезапустит `banano-kling.service`.

Он не меняет `WEBHOOK_BIND_HOST`, не открывает порт `1888` и не редактирует firewall backend-сервера.

## 7. Проверки

```bash
curl -fsS https://api.example.ru/health
curl -fsSI https://app.example.ru/mini-app/
curl -fsS https://app.example.ru/frontend-health
curl -i -X POST https://app.example.ru/mini-app/api/bootstrap \
  -H 'Content-Type: application/json' --data '{}'
```

Последний запрос должен вернуть отказ авторизации `400`, `401` или `403`, а не `404` или `502`.

## 8. Откат

Перед каждым обновлением создаётся hard-link backup:

```text
/var/backups/banano-miniapp/DOMAIN/YYYYMMDD-HHMMSS
```

Для отката:

```bash
sudo rsync -a --delete \
  /var/backups/banano-miniapp/DOMAIN/BACKUP/ \
  /var/www/DOMAIN/mini-app/
sudo nginx -t && sudo systemctl reload nginx
```

`--delete` допустим при осознанном rollback на целостную сохранённую сборку. В обычном deploy скрипт его не применяет.
