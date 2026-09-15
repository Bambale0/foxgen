#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 027

DOMAIN="${HAPPYFOX_MAX_APP_DOMAIN:-max.happy-fox.online}"
WEBROOT="${HAPPYFOX_MAX_WEBROOT:-/var/www/happyfox-max}"
ACME_ROOT="${HAPPYFOX_ACME_ROOT:-/var/www/letsencrypt}"
SITE_AVAILABLE="${HAPPYFOX_MAX_NGINX_SITE:-/etc/nginx/sites-available/happyfox-max.conf}"
SITE_ENABLED="${HAPPYFOX_MAX_NGINX_ENABLED:-/etc/nginx/sites-enabled/happyfox-max.conf}"
CERTBOT_EMAIL="${CERTBOT_EMAIL:-}"
EXPECTED_REVISION="${EXPECTED_REVISION:-}"

usage() {
  cat <<'EOF'
Usage: CERTBOT_EMAIL=ops@example.com scripts/activate_happyfox_max_domain.sh --activate

Preconditions:
  1. max.happy-fox.online DNS already resolves to the HappyFox production edge.
  2. /var/www/happyfox-max/mini-app contains the verified frontend bundle.
  3. nginx and certbot are installed.

The script stages HTTP ACME, obtains/uses a Let's Encrypt certificate, installs
an HTTPS MAX Mini App vhost, validates nginx, reloads it, and runs smoke checks.
EOF
}

[[ "${1:-}" == "--activate" ]] || {
  usage >&2
  exit 2
}
[[ "$DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]] || {
  echo "Invalid MAX domain" >&2
  exit 2
}
[[ -n "$CERTBOT_EMAIL" ]] || {
  echo "CERTBOT_EMAIL is required" >&2
  exit 2
}
command -v nginx >/dev/null 2>&1 || { echo "nginx is required" >&2; exit 1; }
command -v certbot >/dev/null 2>&1 || { echo "certbot is required" >&2; exit 1; }
command -v getent >/dev/null 2>&1 || { echo "getent is required" >&2; exit 1; }
getent ahostsv4 "$DOMAIN" >/dev/null 2>&1 || {
  echo "DNS for $DOMAIN is not resolvable yet; refusing activation" >&2
  exit 1
}
[[ -s "$WEBROOT/mini-app/index.html" && -s "$WEBROOT/mini-app/revision.txt" ]] || {
  echo "MAX webroot is not prepared: $WEBROOT/mini-app" >&2
  exit 1
}

install -d -m 0755 "$WEBROOT" "$ACME_ROOT/.well-known/acme-challenge" "$(dirname "$SITE_AVAILABLE")" "$(dirname "$SITE_ENABLED")"
backup=""
had_site=0
had_enabled=0
if [[ -e "$SITE_AVAILABLE" ]]; then
  had_site=1
  backup="${SITE_AVAILABLE}.bak.$(date -u +%Y%m%dT%H%M%SZ)"
  cp -a "$SITE_AVAILABLE" "$backup"
fi
if [[ -e "$SITE_ENABLED" || -L "$SITE_ENABLED" ]]; then
  had_enabled=1
fi

rollback() {
  rc=$?
  if [[ $rc -ne 0 ]]; then
    if [[ $had_site -eq 1 && -n "$backup" && -e "$backup" ]]; then
      cp -a "$backup" "$SITE_AVAILABLE" || true
    else
      rm -f "$SITE_AVAILABLE" || true
    fi
    if [[ $had_enabled -eq 0 ]]; then
      rm -f "$SITE_ENABLED" || true
    fi
    nginx -t >/dev/null 2>&1 && systemctl reload nginx || true
  fi
  exit "$rc"
}
trap rollback EXIT

cat >"$SITE_AVAILABLE" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN;

    location ^~ /.well-known/acme-challenge/ {
        root $ACME_ROOT;
        default_type text/plain;
        try_files \$uri =404;
    }

    location / {
        return 404;
    }
}
EOF
ln -sfn "$SITE_AVAILABLE" "$SITE_ENABLED"
nginx -t
systemctl reload nginx

certbot certonly \
  --webroot \
  --webroot-path "$ACME_ROOT" \
  --domain "$DOMAIN" \
  --non-interactive \
  --agree-tos \
  --email "$CERTBOT_EMAIL" \
  --keep-until-expiring

cert_dir="/etc/letsencrypt/live/$DOMAIN"
[[ -s "$cert_dir/fullchain.pem" && -s "$cert_dir/privkey.pem" ]] || {
  echo "Certificate files were not created for $DOMAIN" >&2
  exit 1
}

cat >"$SITE_AVAILABLE" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN;

    location ^~ /.well-known/acme-challenge/ {
        root $ACME_ROOT;
        default_type text/plain;
        try_files \$uri =404;
    }

    location / {
        return 301 https://\$host\$request_uri;
    }
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name $DOMAIN;

    root $WEBROOT;
    index index.html;

    ssl_certificate $cert_dir/fullchain.pem;
    ssl_certificate_key $cert_dir/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    location = / {
        return 302 /mini-app/;
    }

    location ^~ /mini-app/_next/static/ {
        try_files \$uri =404;
        access_log off;
        expires 1y;
        add_header Cache-Control "public, max-age=31536000, immutable" always;
        add_header X-Content-Type-Options nosniff always;
    }

    location /mini-app/api/ {
        proxy_pass http://happyfox_backend;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_socket_keepalive on;
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$remote_addr;
        proxy_set_header X-Forwarded-Proto \$scheme;
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
}
EOF

nginx -t
systemctl reload nginx

origin="https://$DOMAIN"
revision="$(curl -fsS --retry 5 --retry-delay 2 --retry-all-errors --max-time 20 "$origin/mini-app/revision.txt")"
[[ -n "$revision" ]] || { echo "MAX revision smoke returned empty body" >&2; exit 1; }
if [[ -n "$EXPECTED_REVISION" && "$revision" != "$EXPECTED_REVISION" ]]; then
  echo "MAX revision mismatch: expected $EXPECTED_REVISION got $revision" >&2
  exit 1
fi

options_status="$(curl -sS -o /dev/null -w '%{http_code}' -X OPTIONS --max-time 20 -H 'Origin: https://max.ru' "$origin/mini-app/")"
[[ "$options_status" == "204" ]] || { echo "MAX Mini App OPTIONS smoke failed: $options_status" >&2; exit 1; }
post_status="$(curl -sS -o /dev/null -w '%{http_code}' -X POST --max-time 20 "$origin/mini-app/")"
[[ "$post_status" == "200" ]] || { echo "MAX Mini App POST smoke failed: $post_status" >&2; exit 1; }
bootstrap_status="$(curl -sS -o /dev/null -w '%{http_code}' -X POST --max-time 20 -H 'Content-Type: application/json' -d '{}' "$origin/mini-app/api/bootstrap")"
[[ "$bootstrap_status" =~ ^(400|401|403)$ ]] || { echo "MAX Mini App bootstrap ingress smoke failed: $bootstrap_status" >&2; exit 1; }

trap - EXIT
echo "[happyfox-max-domain] ACTIVE origin=$origin revision=$revision"
