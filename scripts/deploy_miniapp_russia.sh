#!/usr/bin/env bash
set -euo pipefail

FRONTEND_DIR="$(cd "$(dirname "$0")/../frontend/miniapp-v0" && pwd)"
REMOTE_HOST="91.200.84.187"
REMOTE_USER="root"
REMOTE_WWW="/var/www/cdn.chillcreative.ru"
REMOTE_NGINX_CONF="/etc/nginx/sites-enabled/cdn.chillcreative.ru"
BACKEND_HOST="144.76.188.75"
BACKEND_PORT="1888"
TMP_CONF="/tmp/cdn.chillcreative.ru.conf"

echo "=== Build frontend ==="
cd "$FRONTEND_DIR"
npm ci
npm run build
test -f out/index.html

echo "=== Create backup on remote ==="
sshpass -p 'F2ZYlgByTA5074cy9n' ssh -o StrictHostKeyChecking=no "${REMOTE_USER}@${REMOTE_HOST}" \
  "mkdir -p /srv/banano-miniapp-backup-\$(date +%Y%m%d-%H%M%S) && cp -r ${REMOTE_WWW}/* /srv/banano-miniapp-backup-\$(date +%Y%m%d-%H%M%S)/ && echo 'Backup created'"

echo "=== Rsync frontend ==="
sshpass -p 'F2ZYlgByTA5074cy9n' rsync -az --delete \
  -e "ssh -o StrictHostKeyChecking=no" \
  "${FRONTEND_DIR}/out/" \
  "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_WWW}/"

echo "=== Upload nginx config ==="
cat > "$TMP_CONF" <<EOF
server {
    server_name cdn.chillcreative.ru;

    client_max_body_size 60m;

    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    location ~* ^/(?:\.env(?:\..*)?|\.git|\.svn|\.DS_Store|package(?:-lock)?\.json|Dockerfile|docker-compose\.ya?ml) {
        access_log off;
        return 404;
    }

    root ${REMOTE_WWW};

    location = /mini-app {
        return 302 /mini-app/;
    }

    location /mini-app/ {
        try_files \$uri \$uri/ /index.html;
    }

    location /mini-app/_next/static/ {
        alias ${REMOTE_WWW}/_next/static/;
    }

    location = /mini-app/telegram-web-app.js {
        alias ${REMOTE_WWW}/telegram-web-app.js;
    }

    location /mini-app/api/ {
        proxy_pass http://${BACKEND_HOST}:${BACKEND_PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Host \$host;
        proxy_connect_timeout 5s;
        proxy_send_timeout 60s;
        proxy_read_timeout 120s;
        proxy_request_buffering off;
        proxy_buffering off;
    }

    listen 443 ssl;
    listen [::]:443 ssl;
    ssl_certificate /etc/letsencrypt/live/cdn.chillcreative.ru/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/cdn.chillcreative.ru/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;
}
server {
    if (\$host = cdn.chillcreative.ru) {
        return 301 https://\$host\$request_uri;
    }
    listen 80;
    listen [::]:80;
    server_name cdn.chillcreative.ru;
    return 404;
}
EOF

sshpass -p 'F2ZYlgByTA5074cy9n' ssh -o StrictHostKeyChecking=no "${REMOTE_USER}@${REMOTE_HOST}" \
  "cat > ${REMOTE_NGINX_CONF} <<'REMOTE_EOF'
$(cat "$TMP_CONF")
REMOTE_EOF
nginx -t && systemctl reload nginx && echo 'nginx reloaded'"

rm -f "$TMP_CONF"

echo "=== Verify ==="
curl -fsSI "https://cdn.chillcreative.ru/mini-app/" >/dev/null
curl -fsSI "https://cdn.chillcreative.ru/mini-app/_next/static/" >/dev/null || true
curl -fsSI "https://cdn.chillcreative.ru/mini-app/telegram-web-app.js" >/dev/null || true
curl -i -X POST "https://cdn.chillcreative.ru/mini-app/api/bootstrap" \
  -H 'Content-Type: application/json' --data '{}' >/dev/null || true

echo "=== Done ==="
echo "Frontend deployed to https://cdn.chillcreative.ru/mini-app/"
echo "Backend proxy: http://${BACKEND_HOST}:${BACKEND_PORT}/mini-app/api/"