#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

DOMAIN="${DOMAIN:-media.chillcreative.ru}"
ZONE_NAME="${ZONE_NAME:-chillcreative.ru}"
ORIGIN_IPV4="${ORIGIN_IPV4:-144.76.188.75}"
PROJECT_DIR="${PROJECT_DIR:-/root/tanya/banano_kling}"
UPLOADS_DIR="${UPLOADS_DIR:-$PROJECT_DIR/static/uploads}"
PUBLIC_MOUNT="${PUBLIC_MOUNT:-/var/www/$DOMAIN/uploads}"
ACME_ROOT="${ACME_ROOT:-/var/www/letsencrypt}"
NGINX_SITE="/etc/nginx/sites-available/$DOMAIN.conf"
NGINX_LINK="/etc/nginx/sites-enabled/$DOMAIN.conf"
APP_SERVICE="${APP_SERVICE:-banano-kling.service}"
APP_ENV_FILE="${APP_ENV_FILE:-$PROJECT_DIR/.env}"
LETSENCRYPT_EMAIL="${LETSENCRYPT_EMAIL:-}"
CF_API_TOKEN_FILE="${CF_API_TOKEN_FILE:-/root/.secrets/cloudflare-media.token}"
BACKFILL_WEBP="${BACKFILL_WEBP:-1}"
RUN_RENEWAL_DRY_RUN="${RUN_RENEWAL_DRY_RUN:-1}"
BACKUP_DIR="/root/nginx-backups/$DOMAIN-$(date +%Y%m%d-%H%M%S)"
DEPLOY_COMMITTED=0
CF_TOKEN=""
CF_ZONE_ID=""
CF_RULE_DESCRIPTION="Banano media feed immutable cache"

log()  { printf '[media-deploy] %s\n' "$*"; }
warn() { printf '[media-deploy] WARNING: %s\n' "$*" >&2; }
die()  { printf '[media-deploy] ERROR: %s\n' "$*" >&2; exit 1; }

rollback() {
    local status=$?
    if [ "$DEPLOY_COMMITTED" = 0 ] && [ -d "$BACKUP_DIR" ]; then
        warn "Restoring previous Nginx configuration"
        if [ -f "$BACKUP_DIR/site.conf" ]; then
            cp -a "$BACKUP_DIR/site.conf" "$NGINX_SITE"
        else
            rm -f "$NGINX_SITE"
        fi
        if [ -f "$BACKUP_DIR/enabled-target" ]; then
            ln -sfn "$(cat "$BACKUP_DIR/enabled-target")" "$NGINX_LINK"
        else
            rm -f "$NGINX_LINK"
        fi
        nginx -t && systemctl reload nginx || true
    fi
    exit "$status"
}
trap rollback ERR

preflight() {
    [ "$(id -u)" -eq 0 ] || die "Run as root"
    [[ "$DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]] || die "Unsafe DOMAIN"
    [ -d "$PROJECT_DIR/.git" ] || die "Not a git checkout: $PROJECT_DIR"
    local branch
    branch="$(git -C "$PROJECT_DIR" branch --show-current)"
    [ "$branch" = tanyapi ] || die "Expected branch tanyapi, got ${branch:-detached}"
    install -d -m 0700 "$BACKUP_DIR"
    [ -e "$NGINX_SITE" ] && cp -a "$NGINX_SITE" "$BACKUP_DIR/site.conf"
    [ -L "$NGINX_LINK" ] && readlink "$NGINX_LINK" > "$BACKUP_DIR/enabled-target"
}

install_packages() {
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y nginx certbot curl jq dnsutils openssl ca-certificates
    if [ -s "$CF_API_TOKEN_FILE" ]; then
        chmod 0600 "$CF_API_TOKEN_FILE"
        apt-get install -y python3-certbot-dns-cloudflare
    fi
}

configure_cloudflare() {
    [ -s "$CF_API_TOKEN_FILE" ] || {
        warn "No Cloudflare token: DNS orange cloud, Cache Rule and HTTP/3 must already be configured manually"
        return
    }
    CF_TOKEN="$(tr -d '\r\n' < "$CF_API_TOKEN_FILE")"
    [ -n "$CF_TOKEN" ] || die "Cloudflare token file is empty"

    cf_api() {
        local method="$1" path="$2" data="${3:-}" response
        local args=(-fsS -X "$method" "https://api.cloudflare.com/client/v4$path"
            -H "Authorization: Bearer $CF_TOKEN" -H 'Content-Type: application/json')
        [ -n "$data" ] && args+=(--data "$data")
        response="$(curl "${args[@]}")"
        [ "$(jq -r '.success // false' <<<"$response")" = true ] || {
            jq -c '.errors // .' <<<"$response" >&2 || true
            die "Cloudflare API failed: $method $path"
        }
        printf '%s' "$response"
    }

    local response record_id body rulesets ruleset_id details rule_id rule_body
    response="$(cf_api GET "/zones?name=$ZONE_NAME&status=active&per_page=1")"
    CF_ZONE_ID="$(jq -r '.result[0].id // empty' <<<"$response")"
    [ -n "$CF_ZONE_ID" ] || die "Cloudflare zone not found: $ZONE_NAME"

    response="$(cf_api GET "/zones/$CF_ZONE_ID/dns_records?type=A&name=$DOMAIN&per_page=1")"
    record_id="$(jq -r '.result[0].id // empty' <<<"$response")"
    body="$(jq -nc --arg name "$DOMAIN" --arg ip "$ORIGIN_IPV4" '{type:"A",name:$name,content:$ip,ttl:1,proxied:true,comment:"Managed by banano_kling media deploy"}')"
    if [ -n "$record_id" ]; then
        cf_api PATCH "/zones/$CF_ZONE_ID/dns_records/$record_id" "$body" >/dev/null
    else
        cf_api POST "/zones/$CF_ZONE_ID/dns_records" "$body" >/dev/null
    fi
    log "Cloudflare DNS configured: $DOMAIN -> $ORIGIN_IPV4, proxied=true"

    cf_api PATCH "/zones/$CF_ZONE_ID/settings/http3" '{"value":"off"}' >/dev/null
    log "Cloudflare HTTP/3 disabled for VPN diagnostics"

    rulesets="$(cf_api GET "/zones/$CF_ZONE_ID/rulesets")"
    ruleset_id="$(jq -r '.result[] | select(.phase=="http_request_cache_settings" and .kind=="zone") | .id' <<<"$rulesets" | head -n1)"
    rule_body="$(jq -nc --arg d "$CF_RULE_DESCRIPTION" --arg e "(http.host eq \"$DOMAIN\" and starts_with(http.request.uri.path, \"/uploads/feed/\"))" '{action:"set_cache_settings",description:$d,expression:$e,enabled:true,action_parameters:{cache:true,edge_ttl:{mode:"respect_origin"},browser_ttl:{mode:"respect_origin"}}}')"

    if [ -z "$ruleset_id" ]; then
        body="$(jq -nc --argjson rule "$rule_body" '{name:"Media feed cache",description:"Banano media cache",kind:"zone",phase:"http_request_cache_settings",rules:[$rule]}')"
        cf_api POST "/zones/$CF_ZONE_ID/rulesets" "$body" >/dev/null
    else
        details="$(cf_api GET "/zones/$CF_ZONE_ID/rulesets/$ruleset_id")"
        rule_id="$(jq -r --arg d "$CF_RULE_DESCRIPTION" '.result.rules[]? | select(.description==$d) | .id' <<<"$details" | head -n1)"
        if [ -n "$rule_id" ]; then
            cf_api PATCH "/zones/$CF_ZONE_ID/rulesets/$ruleset_id/rules/$rule_id" "$rule_body" >/dev/null
        else
            cf_api POST "/zones/$CF_ZONE_ID/rulesets/$ruleset_id/rules" "$rule_body" >/dev/null
        fi
    fi
    log "Cloudflare Cache Rule configured for $DOMAIN/uploads/feed/*"

    response="$(cf_api GET "/zones/$CF_ZONE_ID/settings/ssl")"
    [ "$(jq -r '.result.value // empty' <<<"$response")" = strict ] || warn "Cloudflare SSL/TLS mode is not Full (strict); change it after the origin certificate is active"
}

prepare_storage() {
    install -d -m 0755 "$UPLOADS_DIR" "$UPLOADS_DIR/feed" "$UPLOADS_DIR/feed/thumbs"
    install -d -m 0755 "$PUBLIC_MOUNT" "$ACME_ROOT/.well-known/acme-challenge"

    # Nginx cannot normally traverse /root. The bind mount exposes the same
    # files under /var/www without moving or duplicating media.
    find "$UPLOADS_DIR" -type d -exec chmod a+rx {} +
    find "$UPLOADS_DIR" -type f -exec chmod a+r {} +
    mountpoint -q "$PUBLIC_MOUNT" || mount --bind "$UPLOADS_DIR" "$PUBLIC_MOUNT"

    local line="$UPLOADS_DIR $PUBLIC_MOUNT none bind,nofail 0 0"
    grep -Fqs "$UPLOADS_DIR $PUBLIC_MOUNT none bind" /etc/fstab || printf '%s\n' "$line" >> /etc/fstab
}

write_http_config() {
    cat > "$NGINX_SITE" <<NGINX
server {
    listen 80;
    server_name $DOMAIN;

    location ^~ /.well-known/acme-challenge/ {
        root $ACME_ROOT;
        default_type text/plain;
        try_files \$uri =404;
    }

    location = /healthz {
        access_log off;
        default_type text/plain;
        add_header Cache-Control "no-store" always;
        return 200 "ok\\n";
    }

    location / { return 404; }
}
NGINX
    ln -sfn "$NGINX_SITE" "$NGINX_LINK"
    nginx -t
    systemctl enable --now nginx
    systemctl reload nginx
}

issue_certificate() {
    local cert="/etc/letsencrypt/live/$DOMAIN/fullchain.pem"
    if [ -s "$cert" ] && openssl x509 -checkend 2592000 -noout -in "$cert"; then
        log "Certificate is already valid for more than 30 days"
        return
    fi

    local account_args=(--register-unsafely-without-email)
    [ -n "$LETSENCRYPT_EMAIL" ] && account_args=(--email "$LETSENCRYPT_EMAIL")

    if [ -s "$CF_API_TOKEN_FILE" ] && certbot plugins 2>/dev/null | grep -q dns-cloudflare; then
        local credentials="/root/.secrets/certbot/cloudflare.ini"
        install -d -m 0700 "$(dirname "$credentials")"
        printf 'dns_cloudflare_api_token = %s\n' "$(tr -d '\r\n' < "$CF_API_TOKEN_FILE")" > "$credentials"
        chmod 0600 "$credentials"
        certbot certonly --dns-cloudflare \
            --dns-cloudflare-credentials "$credentials" \
            --dns-cloudflare-propagation-seconds 30 \
            -d "$DOMAIN" --cert-name "$DOMAIN" \
            --non-interactive --agree-tos --keep-until-expiring "${account_args[@]}"
    else
        warn "Using HTTP-01. Cloudflare 'Always Use HTTPS' must not redirect the first ACME request."
        certbot certonly --webroot -w "$ACME_ROOT" \
            -d "$DOMAIN" --cert-name "$DOMAIN" \
            --non-interactive --agree-tos --keep-until-expiring "${account_args[@]}"
    fi
}

write_https_config() {
    cat > "$NGINX_SITE" <<NGINX
server {
    listen 80;
    server_name $DOMAIN;

    location ^~ /.well-known/acme-challenge/ {
        root $ACME_ROOT;
        default_type text/plain;
        try_files \$uri =404;
    }
    location / { return 301 https://\$host\$request_uri; }
}

server {
    listen 443 ssl http2;
    server_name $DOMAIN;

    ssl_certificate /etc/letsencrypt/live/$DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$DOMAIN/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:MEDIA_SSL:10m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;

    server_tokens off;
    autoindex off;
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    etag on;
    open_file_cache max=10000 inactive=60s;
    open_file_cache_valid 120s;
    open_file_cache_min_uses 2;

    add_header Strict-Transport-Security "max-age=31536000" always;

    location = /healthz {
        access_log off;
        default_type text/plain;
        add_header Cache-Control "no-store" always;
        return 200 "ok\\n";
    }

    location ~ /\. { deny all; }

    # Durable public feed. UUID filenames allow a one-year immutable cache.
    location /uploads/feed/ {
        alias $PUBLIC_MOUNT/feed/;
        limit_except GET HEAD { deny all; }
        default_type application/octet-stream;
        add_header Cache-Control "public, max-age=31536000, s-maxage=31536000, immutable" always;
        add_header Access-Control-Allow-Origin "*" always;
        add_header Cross-Origin-Resource-Policy "cross-origin" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header X-Robots-Tag "noindex, nofollow" always;
        access_log off;
        log_not_found off;
    }

    # References and temporary uploads remain public for provider access but
    # are deliberately excluded from browser and Cloudflare persistence.
    location /uploads/ {
        alias $PUBLIC_MOUNT/;
        limit_except GET HEAD { deny all; }
        default_type application/octet-stream;
        add_header Cache-Control "no-store" always;
        add_header Access-Control-Allow-Origin "*" always;
        add_header Cross-Origin-Resource-Policy "cross-origin" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header X-Robots-Tag "noindex, nofollow" always;
        access_log off;
        log_not_found off;
    }

    location / { return 404; }
}
NGINX
    nginx -t
    systemctl reload nginx
    DEPLOY_COMMITTED=1
}

configure_runtime() {
    install -d -m 0755 /etc/letsencrypt/renewal-hooks/deploy
    cat > /etc/letsencrypt/renewal-hooks/deploy/reload-nginx-media.sh <<'HOOK'
#!/usr/bin/env bash
set -euo pipefail
nginx -t
systemctl reload nginx
HOOK
    chmod 0755 /etc/letsencrypt/renewal-hooks/deploy/reload-nginx-media.sh
    systemctl enable --now certbot.timer >/dev/null 2>&1 || true

    if [ -f "$APP_ENV_FILE" ]; then
        cp -a "$APP_ENV_FILE" "$BACKUP_DIR/app.env"
        if grep -qE '^STATIC_BASE_URL=' "$APP_ENV_FILE"; then
            sed -i -E "s#^STATIC_BASE_URL=.*#STATIC_BASE_URL=https://$DOMAIN#" "$APP_ENV_FILE"
        else
            printf '\nSTATIC_BASE_URL=https://%s\n' "$DOMAIN" >> "$APP_ENV_FILE"
        fi
        chmod 0600 "$APP_ENV_FILE"
    else
        warn "Missing $APP_ENV_FILE; set STATIC_BASE_URL=https://$DOMAIN manually"
    fi

    if systemctl cat "$APP_SERVICE" >/dev/null 2>&1; then
        systemctl restart "$APP_SERVICE"
        systemctl is-active --quiet "$APP_SERVICE" || die "$APP_SERVICE failed after restart"
    else
        warn "Service $APP_SERVICE not found; restart the backend manually"
    fi
}

backfill_webp() {
    [ "$BACKFILL_WEBP" = 1 ] || return
    local py="$(command -v python3)"
    [ -x "$PROJECT_DIR/venv/bin/python" ] && py="$PROJECT_DIR/venv/bin/python"
    (
        cd "$PROJECT_DIR"
        "$py" - "$DOMAIN" <<'PY'
import sys
from pathlib import Path
from bot.services.feed_persist import ensure_feed_thumbnail

domain = sys.argv[1]
feed = Path("static/uploads/feed")
ok = failed = 0
for path in sorted(feed.iterdir()) if feed.is_dir() else []:
    if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
        url = f"https://{domain}/uploads/feed/{path.name}"
        if ensure_feed_thumbnail(url): ok += 1
        else: failed += 1
print(f"WebP backfill: processed={ok}, failed={failed}")
PY
    )
}

verify() {
    local probe="$UPLOADS_DIR/feed/system/media-cache-probe.txt"
    install -d -m 0755 "$(dirname "$probe")"
    printf 'media-cache-ok\n' > "$probe"
    chmod 0644 "$probe"

    curl -fsS --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN/healthz" | grep -qx ok
    curl -fsSI --resolve "$DOMAIN:443:127.0.0.1" \
        "https://$DOMAIN/uploads/feed/system/media-cache-probe.txt" | grep -qi 'cache-control: .*immutable'

    local headers status="" i
    for i in $(seq 1 20); do
        headers="$(curl -fsSI --http2 "https://$DOMAIN/healthz" || true)"
        grep -qi '^server: cloudflare' <<<"$headers" && break
        sleep 3
    done
    grep -qi '^server: cloudflare' <<<"$headers" || die "Cloudflare orange-cloud proxy is not active"
    grep -qi '^alt-svc:.*h3' <<<"$headers" && die "HTTP/3 is still enabled in Cloudflare"

    for i in $(seq 1 8); do
        headers="$(curl -fsS -D - -o /dev/null --http2 "https://$DOMAIN/uploads/feed/system/media-cache-probe.txt")"
        status="$(awk -F': ' 'tolower($1)=="cf-cache-status" {gsub("\r","",$2); print toupper($2)}' <<<"$headers" | tail -n1)"
        [ "$status" = HIT ] && break
        sleep 2
    done
    [ "$status" = HIT ] || die "Cloudflare cache rule is missing or ineffective; CF-Cache-Status=$status"

    [ "$RUN_RENEWAL_DRY_RUN" = 1 ] && certbot renew --cert-name "$DOMAIN" --dry-run
}

main() {
    preflight
    install_packages
    configure_cloudflare
    prepare_storage
    write_http_config
    dig +short A "$DOMAIN" | grep -qE '^[0-9]' || die "$DOMAIN has no A record"
    issue_certificate
    write_https_config
    configure_runtime
    backfill_webp
    verify

    cat <<SUMMARY

Done: https://$DOMAIN/uploads/ now serves the existing $UPLOADS_DIR directory.
Public feed: one-year immutable cache. Other uploads: no-store.
Nginx config: $NGINX_SITE
Certificate: /etc/letsencrypt/live/$DOMAIN/
Backup: $BACKUP_DIR
SUMMARY
}

main "$@"
