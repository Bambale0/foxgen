#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 027

DOMAIN="max.happy-fox.online"
CERTBOT_EMAIL="${CERTBOT_EMAIL:-}"
WEB_ROOT="/var/www/happyfox-max"
MINIAPP_ROOT="$WEB_ROOT/mini-app"
SITE_AVAILABLE="/etc/nginx/sites-available/happyfox-max.conf"
SITE_ENABLED="/etc/nginx/sites-enabled/happyfox-max.conf"
CONFIG_DIR="/etc/foxgen-happyfox"
CONFIG_FILE="$CONFIG_DIR/max-miniapp.env"

log() { printf '[happyfox-max-host] %s\n' "$*"; }
die() { printf '[happyfox-max-host] ERROR: %s\n' "$*" >&2; exit 1; }

[[ -n "$CERTBOT_EMAIL" ]] || die "CERTBOT_EMAIL is required"
command -v nginx >/dev/null || die "nginx is required"
command -v certbot >/dev/null || die "certbot is required"
command -v getent >/dev/null || die "getent is required"

resolved="$(getent ahostsv4 "$DOMAIN" | awk '{print $1}' | sort -u | tr '\n' ' ')"
[[ -n "$resolved" ]] || die "$DOMAIN does not resolve yet; create DNS first"
log "DNS resolves: $DOMAIN -> $resolved"

install -d -m 0755 "$WEB_ROOT" "$MINIAPP_ROOT"
install -d -m 0755 "$CONFIG_DIR"

cat > "$SITE_AVAILABLE" <<EOF
server {
    listen 80;
    server_name $DOMAIN;
    root $WEB_ROOT;

    location ^~ /.well-known/acme-challenge/ {
        try_files \$uri =404;
    }

    location / {
        return 301 https://\$host\$request_uri;
    }
}
EOF
ln -sfn "$SITE_AVAILABLE" "$SITE_ENABLED"
nginx -t
systemctl reload nginx

if [[ ! -s "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" || ! -s "/etc/letsencrypt/live/$DOMAIN/privkey.pem" ]]; then
  certbot certonly \
    --webroot \
    --webroot-path "$WEB_ROOT" \
    --domain "$DOMAIN" \
    --non-interactive \
    --agree-tos \
    --email "$CERTBOT_EMAIL" \
    --keep-until-expiring
fi

cat > "$SITE_AVAILABLE" <<EOF
server {
    listen 80;
    server_name $DOMAIN;
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl http2;
    server_name $DOMAIN;
    root $WEB_ROOT;

    ssl_certificate /etc/letsencrypt/live/$DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$DOMAIN/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    client_max_body_size 60m;

    location ^~ /mini-app/_next/static/ {
        try_files \$uri =404;
        access_log off;
        expires 1y;
        add_header Cache-Control "public, max-age=31536000, immutable" always;
        add_header X-Content-Type-Options nosniff always;
    }

    location /mini-app/api/ {
        proxy_pass http://127.0.0.1:1888;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_socket_keepalive on;
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 900s;
        proxy_send_timeout 900s;
    }

    location = /mini-app/ {
        error_page 418 =200 /mini-app/index.html;
        if (\$request_method = OPTIONS) { return 204; }
        if (\$request_method = POST) { return 418; }
        try_files /mini-app/index.html =404;
        add_header Cache-Control "no-cache, no-store, must-revalidate" always;
        add_header Pragma "no-cache" always;
        add_header Expires "0" always;
    }

    location /mini-app/ {
        try_files \$uri \$uri/ /mini-app/index.html;
    }

    add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval' https://st.max.ru; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; media-src 'self' blob: https:; connect-src 'self' https: wss:; frame-ancestors 'self' https://max.ru https://*.max.ru; font-src 'self' data:" always;
    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;
}
EOF

nginx -t
systemctl reload nginx

cat > "$CONFIG_FILE" <<EOF
MAX_MINIAPP_ORIGIN='https://$DOMAIN'
EOF
chmod 0600 "$CONFIG_FILE"

log "READY origin=https://$DOMAIN config=$CONFIG_FILE"
log "Next: run scripts/activate_happyfox_channel_miniapps.sh <verified-main-sha>, then set the MAX partner Mini App URL to https://$DOMAIN/mini-app/"
