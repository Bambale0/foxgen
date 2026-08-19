#!/usr/bin/env bash
# Fully automated installer/deployer for the Banano Kling Mini App frontend host.
# Ubuntu 22.04/24.04, root privileges required.
#
# Production deployments should use install_miniapp_frontend_https_host.sh,
# which enforces backend HTTPS/443 and disables direct aiohttp exposure.

set -Eeuo pipefail
IFS=$'\n\t'
umask 027

SCRIPT_NAME="$(basename "$0")"
LOG_FILE="${LOG_FILE:-/var/log/banano-miniapp-installer.log}"
CONFIG_FILE=""
MODE="install"

usage() {
  cat <<USAGE
Usage:
  sudo bash ${SCRIPT_NAME} --config /path/to/frontend.env [--install|--deploy-only]

Recommended production entrypoint:
  sudo bash install_miniapp_frontend_https_host.sh --config /path/to/frontend.env --install

Required configuration variables:
  FRONTEND_DOMAIN       Public domain, e.g. app.example.ru
  BACKEND_ORIGIN        Backend origin without a trailing slash
  CERTBOT_EMAIL         Email for Let's Encrypt, unless SKIP_TLS=1

Main optional variables:
  REPO_URL              Default: https://github.com/Bambale0/banano_kling.git
  REPO_BRANCH           Default: tanyapi
  SOURCE_DIR            Default: /opt/banano-kling-src
  WEB_ROOT              Default: /var/www/FRONTEND_DOMAIN
  BACKEND_HOST_HEADER   Default: host parsed from BACKEND_ORIGIN
  SKIP_TLS              Default: 0
  SKIP_DNS_CHECK        Default: 0
  ENABLE_UFW            Default: 1
  RUN_NPM_AUDIT         Default: 1
  FORCE_RESET_SOURCE    Default: 0

Optional backend automation over SSH:
  BACKEND_SSH_HOST      Example: root@144.76.188.75
  BACKEND_PROJECT_DIR   Default: /root/tanya/banano_kling
  BACKEND_ENV_FILE      Default: BACKEND_PROJECT_DIR/.env
  BACKEND_SERVICE       Default: banano-kling.service
  BACKEND_PORT          Backend aiohttp/runtime port. Default: 1888
  CONFIGURE_BACKEND_UFW Default: 1
USAGE
}

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG_FILE"
}

warn() {
  printf '[%s] WARNING: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG_FILE" >&2
}

die() {
  printf '[%s] ERROR: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG_FILE" >&2
  exit 1
}

on_error() {
  local exit_code=$?
  local line_no=${1:-unknown}
  warn "Command failed at line ${line_no}, exit code ${exit_code}. See ${LOG_FILE}."
  exit "$exit_code"
}
trap 'on_error $LINENO' ERR

require_root() {
  [[ "${EUID}" -eq 0 ]] || die "Run this script as root or through sudo."
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --config)
        [[ $# -ge 2 ]] || die "--config requires a file path"
        CONFIG_FILE="$2"
        shift 2
        ;;
      --install)
        MODE="install"
        shift
        ;;
      --deploy-only)
        MODE="deploy"
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        die "Unknown argument: $1"
        ;;
    esac
  done

  [[ -n "$CONFIG_FILE" ]] || die "Pass --config /path/to/frontend.env"
  [[ -f "$CONFIG_FILE" ]] || die "Config file not found: $CONFIG_FILE"

  # shellcheck disable=SC1090
  source "$CONFIG_FILE"
}

validate_domain() {
  local domain="$1"
  [[ "$domain" =~ ^([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$ ]] \
    || die "Invalid FRONTEND_DOMAIN: $domain"
}

validate_origin() {
  local origin="$1"
  [[ "$origin" =~ ^https?://[^/]+$ ]] \
    || die "BACKEND_ORIGIN must look like https://api.example.ru or http://IP:1888"
}

load_defaults() {
  : "${FRONTEND_DOMAIN:?FRONTEND_DOMAIN is required}"
  : "${BACKEND_ORIGIN:?BACKEND_ORIGIN is required}"

  REPO_URL="${REPO_URL:-https://github.com/Bambale0/banano_kling.git}"
  REPO_BRANCH="${REPO_BRANCH:-tanyapi}"
  SOURCE_DIR="${SOURCE_DIR:-/opt/banano-kling-src}"
  WEB_ROOT="${WEB_ROOT:-/var/www/${FRONTEND_DOMAIN}}"
  MINIAPP_ROOT="${MINIAPP_ROOT:-${WEB_ROOT}/mini-app}"
  ACME_ROOT="${ACME_ROOT:-/var/www/_letsencrypt}"
  BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/banano-miniapp/${FRONTEND_DOMAIN}}"
  KEEP_BACKUPS="${KEEP_BACKUPS:-7}"
  NGINX_SITE_NAME="${NGINX_SITE_NAME:-banano-miniapp-${FRONTEND_DOMAIN//./-}}"
  CERTBOT_EMAIL="${CERTBOT_EMAIL:-}"
  SKIP_TLS="${SKIP_TLS:-0}"
  SKIP_DNS_CHECK="${SKIP_DNS_CHECK:-0}"
  ENABLE_UFW="${ENABLE_UFW:-1}"
  RUN_NPM_AUDIT="${RUN_NPM_AUDIT:-1}"
  FORCE_RESET_SOURCE="${FORCE_RESET_SOURCE:-0}"
  NODE_MAJOR="${NODE_MAJOR:-22}"
  CLIENT_MAX_BODY_SIZE="${CLIENT_MAX_BODY_SIZE:-60M}"
  PROXY_TIMEOUT_SECONDS="${PROXY_TIMEOUT_SECONDS:-600}"

  BACKEND_SSH_HOST="${BACKEND_SSH_HOST:-}"
  BACKEND_PROJECT_DIR="${BACKEND_PROJECT_DIR:-/root/tanya/banano_kling}"
  BACKEND_ENV_FILE="${BACKEND_ENV_FILE:-${BACKEND_PROJECT_DIR}/.env}"
  BACKEND_SERVICE="${BACKEND_SERVICE:-banano-kling.service}"
  CONFIGURE_BACKEND_UFW="${CONFIGURE_BACKEND_UFW:-1}"

  validate_domain "$FRONTEND_DOMAIN"
  validate_origin "$BACKEND_ORIGIN"

  BACKEND_SCHEME="${BACKEND_ORIGIN%%://*}"
  local backend_authority="${BACKEND_ORIGIN#*://}"
  BACKEND_HOST="${backend_authority%%:*}"
  if [[ "$backend_authority" == *:* ]]; then
    BACKEND_ORIGIN_PORT="${backend_authority##*:}"
  elif [[ "$BACKEND_SCHEME" == "https" ]]; then
    BACKEND_ORIGIN_PORT="443"
  else
    BACKEND_ORIGIN_PORT="80"
  fi
  BACKEND_PORT="${BACKEND_PORT:-1888}"
  BACKEND_HOST_HEADER="${BACKEND_HOST_HEADER:-${BACKEND_HOST}}"
  BACKEND_TLS_NAME="${BACKEND_TLS_NAME:-${BACKEND_HOST}}"

  if [[ "$SKIP_TLS" != "1" && -z "$CERTBOT_EMAIL" ]]; then
    die "CERTBOT_EMAIL is required unless SKIP_TLS=1"
  fi

  [[ "$KEEP_BACKUPS" =~ ^[0-9]+$ ]] || die "KEEP_BACKUPS must be a number"
  [[ "$PROXY_TIMEOUT_SECONDS" =~ ^[0-9]+$ ]] || die "PROXY_TIMEOUT_SECONDS must be a number"
}

install_base_packages() {
  log "Installing system packages"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends \
    ca-certificates curl git gnupg nginx rsync certbot openssl dnsutils ufw

  if ! command -v node >/dev/null 2>&1 || [[ "$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)" -lt "$NODE_MAJOR" ]]; then
    log "Installing Node.js ${NODE_MAJOR}.x"
    install -d -m 0755 /etc/apt/keyrings
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
      | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
    chmod 0644 /etc/apt/keyrings/nodesource.gpg
    cat > /etc/apt/sources.list.d/nodesource.list <<NODE_REPO

deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main
NODE_REPO
    apt-get update
    apt-get install -y nodejs
  fi

  command -v npm >/dev/null 2>&1 || die "npm was not installed"
  log "Node $(node -v), npm $(npm -v), nginx $(nginx -v 2>&1)"
}

configure_firewall() {
  [[ "$ENABLE_UFW" == "1" ]] || return 0
  log "Configuring UFW"
  ufw allow OpenSSH >/dev/null
  ufw allow 'Nginx Full' >/dev/null
  if ! ufw status | grep -q '^Status: active'; then
    ufw --force enable >/dev/null
  fi
}

prepare_directories() {
  install -d -m 0755 "$WEB_ROOT" "$MINIAPP_ROOT" "$ACME_ROOT"
  install -d -m 0700 "$BACKUP_ROOT"
  touch "$LOG_FILE"
  chmod 0640 "$LOG_FILE"
}

public_ipv4() {
  curl -4 -fsS --max-time 10 https://api.ipify.org 2>/dev/null || true
}

resolved_ipv4s() {
  getent ahostsv4 "$FRONTEND_DOMAIN" 2>/dev/null \
    | awk '{print $1}' \
    | sort -u
}

check_dns() {
  [[ "$SKIP_DNS_CHECK" == "1" ]] && return 0

  local server_ip dns_ips
  server_ip="$(public_ipv4)"
  dns_ips="$(resolved_ipv4s || true)"

  [[ -n "$server_ip" ]] || die "Could not determine this server's public IPv4. Set SKIP_DNS_CHECK=1 only if intentional."
  [[ -n "$dns_ips" ]] || die "${FRONTEND_DOMAIN} has no IPv4 record yet. Point DNS to ${server_ip}."

  if ! grep -qxF "$server_ip" <<<"$dns_ips"; then
    die "DNS for ${FRONTEND_DOMAIN} points to [${dns_ips//$'\n'/, }], but this server is ${server_ip}."
  fi
  log "DNS is ready: ${FRONTEND_DOMAIN} -> ${server_ip}"
}

checkout_source() {
  if [[ ! -d "$SOURCE_DIR/.git" ]]; then
    log "Cloning ${REPO_URL} into ${SOURCE_DIR}"
    rm -rf "$SOURCE_DIR"
    git clone --branch "$REPO_BRANCH" --single-branch "$REPO_URL" "$SOURCE_DIR"
  else
    log "Updating source checkout in ${SOURCE_DIR}"
    if [[ -n "$(git -C "$SOURCE_DIR" status --porcelain)" ]]; then
      if [[ "$FORCE_RESET_SOURCE" == "1" ]]; then
        warn "Discarding local changes because FORCE_RESET_SOURCE=1"
        git -C "$SOURCE_DIR" reset --hard
        git -C "$SOURCE_DIR" clean -fd
      else
        die "Source checkout contains local changes. Commit them or set FORCE_RESET_SOURCE=1."
      fi
    fi
    git -C "$SOURCE_DIR" fetch --prune origin "$REPO_BRANCH"
    git -C "$SOURCE_DIR" switch "$REPO_BRANCH"
    git -C "$SOURCE_DIR" reset --hard "origin/${REPO_BRANCH}"
  fi

  log "Source commit: $(git -C "$SOURCE_DIR" rev-parse --short HEAD)"
}

build_frontend() {
  local frontend_dir="${SOURCE_DIR}/frontend/miniapp-v0"
  local out_dir="${frontend_dir}/out"
  [[ -f "${frontend_dir}/package-lock.json" ]] || die "package-lock.json not found in ${frontend_dir}"

  log "Installing locked frontend dependencies"
  cd "$frontend_dir"
  npm ci

  if [[ "$RUN_NPM_AUDIT" == "1" ]]; then
    log "Running production dependency audit"
    npm audit --omit=dev --audit-level=moderate
  fi

  log "Running frontend lint"
  npm run lint

  log "Building static Mini App export"
  rm -rf .next out
  npm run build
  [[ -f "${out_dir}/index.html" ]] || die "Build finished without out/index.html"

  BUILD_OUT="$out_dir"
}

backup_current_frontend() {
  if [[ ! -f "${MINIAPP_ROOT}/index.html" ]]; then
    return 0
  fi

  local stamp backup_dir
  stamp="$(date '+%Y%m%d-%H%M%S')"
  backup_dir="${BACKUP_ROOT}/${stamp}"
  log "Creating hard-link backup: ${backup_dir}"
  mkdir -p "$backup_dir"
  cp -al "${MINIAPP_ROOT}/." "$backup_dir/"

  mapfile -t old_backups < <(find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -nr | awk '{print $2}')
  if (( ${#old_backups[@]} > KEEP_BACKUPS )); then
    local i
    for ((i=KEEP_BACKUPS; i<${#old_backups[@]}; i++)); do
      rm -rf -- "${old_backups[$i]}"
    done
  fi
}

deploy_frontend() {
  backup_current_frontend
  log "Deploying static export without deleting older hashed chunks"
  rsync -a --chmod=D755,F644 "${BUILD_OUT}/" "${MINIAPP_ROOT}/"
  chown -R root:root "$WEB_ROOT"
  [[ -f "${MINIAPP_ROOT}/index.html" ]] || die "Deployment did not produce ${MINIAPP_ROOT}/index.html"
}

proxy_common_block() {
  cat <<PROXY_BLOCK
        proxy_pass ${BACKEND_ORIGIN};
        proxy_http_version 1.1;
        proxy_set_header Host ${BACKEND_HOST_HEADER};
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Host \$host;
        proxy_set_header X-Forwarded-Port \$server_port;
        proxy_connect_timeout 30s;
        proxy_send_timeout ${PROXY_TIMEOUT_SECONDS}s;
        proxy_read_timeout ${PROXY_TIMEOUT_SECONDS}s;
        proxy_request_buffering off;
        proxy_buffering off;
PROXY_BLOCK

  if [[ "$BACKEND_SCHEME" == "https" ]]; then
    cat <<TLS_PROXY_BLOCK
        proxy_ssl_server_name on;
        proxy_ssl_name ${BACKEND_TLS_NAME};
TLS_PROXY_BLOCK
  fi
}

write_nginx_config() {
  local cert_dir="/etc/letsencrypt/live/${FRONTEND_DOMAIN}"
  local site_available="/etc/nginx/sites-available/${NGINX_SITE_NAME}"
  local site_enabled="/etc/nginx/sites-enabled/${NGINX_SITE_NAME}"
  local tmp_config
  tmp_config="$(mktemp)"

  cat > "$tmp_config" <<NGINX_HEADER
server {
    listen 80;
    listen [::]:80;
    server_name ${FRONTEND_DOMAIN};

    client_max_body_size ${CLIENT_MAX_BODY_SIZE};

    location ^~ /.well-known/acme-challenge/ {
        root ${ACME_ROOT};
        default_type text/plain;
    }
NGINX_HEADER

  if [[ -f "${cert_dir}/fullchain.pem" && -f "${cert_dir}/privkey.pem" ]]; then
    cat >> "$tmp_config" <<'HTTP_REDIRECT'

    location / {
        return 301 https://$host$request_uri;
    }
}
HTTP_REDIRECT

    cat >> "$tmp_config" <<NGINX_HTTPS

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name ${FRONTEND_DOMAIN};

    ssl_certificate ${cert_dir}/fullchain.pem;
    ssl_certificate_key ${cert_dir}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:SSL:20m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;

    root ${WEB_ROOT};
    index index.html;
    client_max_body_size ${CLIENT_MAX_BODY_SIZE};
    server_tokens off;

    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_types text/plain text/css application/json application/javascript application/xml image/svg+xml;

    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;

    location = / {
        return 302 /mini-app/;
    }

    location = /mini-app {
        return 301 /mini-app/;
    }

    location = /frontend-health {
        access_log off;
        default_type application/json;
        return 200 '{"ok":true,"service":"banano-miniapp-frontend"}';
    }

    location ^~ /mini-app/api/ {
$(proxy_common_block)
    }

    location ^~ /api/v1/ {
$(proxy_common_block)
    }

    location ^~ /uploads/ {
$(proxy_common_block)
    }

    location ^~ /mini-app/_next/static/ {
        try_files \$uri =404;
        access_log off;
        expires 1y;
        add_header Cache-Control "public, max-age=31536000, immutable" always;
        add_header X-Content-Type-Options nosniff always;
    }

    location = /mini-app/telegram-web-app.js {
        try_files \$uri =404;
        expires 1h;
        add_header Cache-Control "public, max-age=3600" always;
    }

    location = /telegram-web-app.js {
        try_files /mini-app/telegram-web-app.js =404;
        expires 1h;
        add_header Cache-Control "public, max-age=3600" always;
    }

    location = /mini-app/ {
        try_files /mini-app/index.html =404;
        add_header Cache-Control "no-cache, no-store, must-revalidate" always;
        add_header Pragma "no-cache" always;
        add_header Expires "0" always;
    }

    location /mini-app/ {
        try_files \$uri \$uri/ /mini-app/index.html;
        add_header Cache-Control "no-cache, no-store, must-revalidate" always;
        add_header Pragma "no-cache" always;
        add_header Expires "0" always;
    }
}
NGINX_HTTPS
  else
    cat >> "$tmp_config" <<NGINX_HTTP_ONLY

    root ${WEB_ROOT};
    index index.html;

    location = / {
        return 302 /mini-app/;
    }

    location = /mini-app {
        return 301 /mini-app/;
    }

    location = /frontend-health {
        access_log off;
        default_type application/json;
        return 200 '{"ok":true,"service":"banano-miniapp-frontend"}';
    }

    location ^~ /mini-app/api/ {
$(proxy_common_block)
    }

    location ^~ /api/v1/ {
$(proxy_common_block)
    }

    location ^~ /uploads/ {
$(proxy_common_block)
    }

    location ^~ /mini-app/_next/static/ {
        try_files \$uri =404;
        access_log off;
        expires 1y;
        add_header Cache-Control "public, max-age=31536000, immutable" always;
    }

    location = /mini-app/telegram-web-app.js {
        try_files \$uri =404;
        expires 1h;
        add_header Cache-Control "public, max-age=3600" always;
    }

    location = /mini-app/ {
        try_files /mini-app/index.html =404;
        add_header Cache-Control "no-cache, no-store, must-revalidate" always;
        add_header Pragma "no-cache" always;
        add_header Expires "0" always;
    }

    location /mini-app/ {
        try_files \$uri \$uri/ /mini-app/index.html;
        add_header Cache-Control "no-cache, no-store, must-revalidate" always;
        add_header Pragma "no-cache" always;
        add_header Expires "0" always;
    }
}
NGINX_HTTP_ONLY
  fi

  if [[ -f "$site_available" ]]; then
    cp -a "$site_available" "${site_available}.before-$(date '+%Y%m%d-%H%M%S')"
  fi
  install -m 0644 "$tmp_config" "$site_available"
  rm -f "$tmp_config"
  ln -sfn "$site_available" "$site_enabled"
  rm -f /etc/nginx/sites-enabled/default

  nginx -t
  systemctl enable --now nginx
  systemctl reload nginx
}

issue_tls_certificate() {
  [[ "$SKIP_TLS" == "1" ]] && return 0
  local cert_dir="/etc/letsencrypt/live/${FRONTEND_DOMAIN}"

  if [[ ! -f "${cert_dir}/fullchain.pem" ]]; then
    check_dns
    log "Issuing Let's Encrypt certificate for ${FRONTEND_DOMAIN}"
    certbot certonly \
      --webroot \
      --webroot-path "$ACME_ROOT" \
      --domain "$FRONTEND_DOMAIN" \
      --email "$CERTBOT_EMAIL" \
      --agree-tos \
      --non-interactive \
      --keep-until-expiring
  else
    log "TLS certificate already exists for ${FRONTEND_DOMAIN}"
  fi

  install -d -m 0755 /etc/letsencrypt/renewal-hooks/deploy
  cat > /etc/letsencrypt/renewal-hooks/deploy/reload-banano-miniapp-nginx.sh <<'RENEW_HOOK'
#!/usr/bin/env bash
set -euo pipefail
nginx -t
systemctl reload nginx
RENEW_HOOK
  chmod 0755 /etc/letsencrypt/renewal-hooks/deploy/reload-banano-miniapp-nginx.sh

  # Re-render deterministic HTTPS config now that the certificate exists.
  write_nginx_config
}

configure_backend_over_ssh() {
  [[ -n "$BACKEND_SSH_HOST" ]] || return 0

  local frontend_ip miniapp_url
  frontend_ip="$(public_ipv4)"
  miniapp_url="https://${FRONTEND_DOMAIN}/mini-app/"
  [[ "$SKIP_TLS" == "1" ]] && miniapp_url="http://${FRONTEND_DOMAIN}/mini-app/"

  log "Configuring backend through SSH: ${BACKEND_SSH_HOST}"
  ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new "$BACKEND_SSH_HOST" \
    "BACKEND_ENV_FILE=$(printf '%q' "$BACKEND_ENV_FILE") \
     BACKEND_SERVICE=$(printf '%q' "$BACKEND_SERVICE") \
     MINIAPP_URL=$(printf '%q' "$miniapp_url") \
     FRONTEND_IP=$(printf '%q' "$frontend_ip") \
     BACKEND_PORT=$(printf '%q' "$BACKEND_PORT") \
     CONFIGURE_BACKEND_UFW=$(printf '%q' "$CONFIGURE_BACKEND_UFW") \
     bash -s" <<'REMOTE_BACKEND'
set -Eeuo pipefail

[[ -f "$BACKEND_ENV_FILE" ]] || {
  echo "Backend env file not found: $BACKEND_ENV_FILE" >&2
  exit 1
}

cp -a "$BACKEND_ENV_FILE" "${BACKEND_ENV_FILE}.before-frontend-$(date '+%Y%m%d-%H%M%S')"

python3 - "$BACKEND_ENV_FILE" "$MINIAPP_URL" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
miniapp_url = sys.argv[2]
updates = {
    "MINI_APP_URL": miniapp_url,
    "WEBHOOK_BIND_HOST": "0.0.0.0",
}

lines = path.read_text(encoding="utf-8").splitlines()
seen = set()
result = []
for line in lines:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in line:
        result.append(line)
        continue
    key = line.split("=", 1)[0].strip()
    if key in updates:
        result.append(f"{key}={updates[key]}")
        seen.add(key)
    else:
        result.append(line)
for key, value in updates.items():
    if key not in seen:
        result.append(f"{key}={value}")
path.write_text("\n".join(result) + "\n", encoding="utf-8")
PY

if [[ "$CONFIGURE_BACKEND_UFW" == "1" ]] && command -v ufw >/dev/null 2>&1 && [[ -n "$FRONTEND_IP" ]]; then
  ufw allow from "$FRONTEND_IP" to any port "$BACKEND_PORT" proto tcp >/dev/null
fi

systemctl restart "$BACKEND_SERVICE"
systemctl is-active --quiet "$BACKEND_SERVICE"

if command -v curl >/dev/null 2>&1; then
  curl -fsS --max-time 15 "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null
fi
REMOTE_BACKEND
}

smoke_tests() {
  local scheme="https"
  [[ "$SKIP_TLS" == "1" ]] && scheme="http"
  local base_url="${scheme}://${FRONTEND_DOMAIN}"

  log "Running frontend health check"
  curl -fsS --max-time 20 "${base_url}/frontend-health" | grep -q '"ok":true'

  log "Checking Mini App HTML"
  local html_file
  html_file="$(mktemp)"
  curl -fsS --max-time 30 "${base_url}/mini-app/" -o "$html_file"
  grep -qi '<html' "$html_file" || die "Mini App response is not HTML"

  local asset_path
  asset_path="$(grep -Eo '/mini-app/_next/static/[^" ]+' "$html_file" | head -n 1 || true)"
  rm -f "$html_file"
  if [[ -n "$asset_path" ]]; then
    log "Checking hashed asset: ${asset_path}"
    local headers
    headers="$(curl -fsSI --max-time 20 "${base_url}${asset_path}")"
    grep -qi '^HTTP/.* 200' <<<"$headers" || die "Hashed asset did not return 200"
    grep -qi 'immutable' <<<"$headers" || warn "Hashed asset lacks immutable cache header"
  else
    warn "Could not extract a hashed asset URL from index.html"
  fi

  log "Checking backend proxy boundary"
  local status
  status="$(curl -sS -o /tmp/banano-bootstrap-smoke.json -w '%{http_code}' \
    --max-time 30 \
    -X POST "${base_url}/mini-app/api/bootstrap" \
    -H 'Content-Type: application/json' \
    --data '{}')"
  if [[ "$status" != "400" && "$status" != "401" && "$status" != "403" ]]; then
    cat /tmp/banano-bootstrap-smoke.json >&2 || true
    die "Unexpected bootstrap smoke status: ${status}; expected auth rejection"
  fi
  rm -f /tmp/banano-bootstrap-smoke.json

  if [[ "$SKIP_TLS" != "1" ]]; then
    log "Checking TLS certificate"
    openssl s_client \
      -connect "${FRONTEND_DOMAIN}:443" \
      -servername "$FRONTEND_DOMAIN" \
      -verify_return_error </dev/null 2>/dev/null \
      | grep -q 'Verify return code: 0 (ok)'
  fi
}

print_summary() {
  local scheme="https"
  [[ "$SKIP_TLS" == "1" ]] && scheme="http"
  cat <<SUMMARY

============================================================
Banano Mini App frontend deployment completed.

Frontend:        ${scheme}://${FRONTEND_DOMAIN}/mini-app/
Frontend health: ${scheme}://${FRONTEND_DOMAIN}/frontend-health
Backend origin:  ${BACKEND_ORIGIN}
Source branch:   ${REPO_BRANCH}
Source commit:   $(git -C "$SOURCE_DIR" rev-parse --short HEAD)
Static root:     ${MINIAPP_ROOT}
Nginx site:      /etc/nginx/sites-available/${NGINX_SITE_NAME}
Backups:         ${BACKUP_ROOT}
Log:             ${LOG_FILE}

The deploy intentionally keeps old /_next/static chunks to protect cached
Telegram WebView sessions. Remove obsolete chunks only after a safe overlap.
============================================================
SUMMARY

  if [[ -z "$BACKEND_SSH_HOST" ]]; then
    cat <<MANUAL_BACKEND
Backend was not changed automatically because BACKEND_SSH_HOST is empty.
Set on the backend and restart ${BACKEND_SERVICE}:

  MINI_APP_URL=${scheme}://${FRONTEND_DOMAIN}/mini-app/
  WEBHOOK_BIND_HOST=0.0.0.0

If BACKEND_ORIGIN uses a private/raw port, allow its TCP port only from this
frontend server's IP: $(public_ipv4). The configured runtime port is ${BACKEND_PORT}.
MANUAL_BACKEND
  fi
}

main() {
  require_root
  parse_args "$@"
  load_defaults
  install -d -m 0755 "$(dirname "$LOG_FILE")"
  touch "$LOG_FILE"

  log "Starting ${MODE} for ${FRONTEND_DOMAIN}"

  if [[ "$MODE" == "install" ]]; then
    install_base_packages
    configure_firewall
  else
    command -v nginx >/dev/null 2>&1 || die "nginx is missing; run --install first"
    command -v node >/dev/null 2>&1 || die "node is missing; run --install first"
    command -v rsync >/dev/null 2>&1 || die "rsync is missing; run --install first"
  fi

  prepare_directories
  checkout_source
  build_frontend
  deploy_frontend

  # HTTP config is enough for ACME challenge on a new host.
  write_nginx_config
  issue_tls_certificate
  configure_backend_over_ssh
  smoke_tests
  print_summary
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
