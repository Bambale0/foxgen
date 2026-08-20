#!/usr/bin/env bash
# Secure production entrypoint for a standalone Banano Mini App frontend host.
# Frontend Nginx -> HTTPS backend domain:443 -> backend Nginx -> 127.0.0.1:1888.

set -Eeuo pipefail
IFS=$'\n\t'
umask 027

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_INSTALLER="${SCRIPT_DIR}/install_miniapp_frontend_host.sh"
CONFIG_FILE=""
MODE="--install"
TEMP_CONFIG=""

cleanup() {
  [[ -z "$TEMP_CONFIG" ]] || rm -f "$TEMP_CONFIG"
}
trap cleanup EXIT

log() {
  printf '[secure-frontend] %s\n' "$*"
}

die() {
  printf '[secure-frontend] ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<USAGE
Usage:
  sudo bash $(basename "$0") --config /root/miniapp-frontend.env [--install|--deploy-only]

This secure entrypoint requires:
  BACKEND_ORIGIN=https://api.example.ru

It rejects raw IP/aiohttp origins, never opens port 1888, never changes
WEBHOOK_BIND_HOST and sends all API/upload requests through backend Nginx on 443.
USAGE
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --config)
        [[ $# -ge 2 ]] || die "--config requires a path"
        CONFIG_FILE="$2"
        shift 2
        ;;
      --install)
        MODE="--install"
        shift
        ;;
      --deploy-only)
        MODE="--deploy-only"
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
  [[ -f "$CONFIG_FILE" ]] || die "Config not found: $CONFIG_FILE"
  [[ -f "$BASE_INSTALLER" ]] || die "Base installer not found: $BASE_INSTALLER"
}

validate_domain() {
  local domain="$1"
  [[ "$domain" =~ ^([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$ ]] \
    || die "Invalid domain: $domain"
}

load_and_validate_config() {
  # shellcheck disable=SC1090
  source "$CONFIG_FILE"

  : "${FRONTEND_DOMAIN:?FRONTEND_DOMAIN is required}"
  : "${BACKEND_ORIGIN:?BACKEND_ORIGIN is required}"

  validate_domain "$FRONTEND_DOMAIN"
  [[ "$BACKEND_ORIGIN" =~ ^https://[^/]+$ ]] \
    || die "BACKEND_ORIGIN must be a public HTTPS domain, e.g. https://tanyapi.example.ru"

  local authority host port
  authority="${BACKEND_ORIGIN#https://}"
  if [[ "$authority" == *:* ]]; then
    host="${authority%%:*}"
    port="${authority##*:}"
    [[ "$port" == "443" ]] || die "Only backend HTTPS port 443 is allowed"
  else
    host="$authority"
  fi
  validate_domain "$host"

  BACKEND_HOST_HEADER="${BACKEND_HOST_HEADER:-$host}"
  BACKEND_TLS_NAME="${BACKEND_TLS_NAME:-$host}"
  BACKEND_HEALTH_PATH="${BACKEND_HEALTH_PATH:-/health}"
  validate_domain "$BACKEND_HOST_HEADER"
  validate_domain "$BACKEND_TLS_NAME"
  [[ "$BACKEND_HEALTH_PATH" == /* ]] || die "BACKEND_HEALTH_PATH must start with /"

  BACKEND_SSH_HOST="${BACKEND_SSH_HOST:-}"
  BACKEND_PROJECT_DIR="${BACKEND_PROJECT_DIR:-/root/tanya/banano_kling}"
  BACKEND_ENV_FILE="${BACKEND_ENV_FILE:-${BACKEND_PROJECT_DIR}/.env}"
  BACKEND_SERVICE="${BACKEND_SERVICE:-banano-kling.service}"
  SKIP_TLS="${SKIP_TLS:-0}"
  NGINX_SITE_NAME="${NGINX_SITE_NAME:-banano-miniapp-${FRONTEND_DOMAIN//./-}}"
}

make_sanitized_config() {
  TEMP_CONFIG="$(mktemp /root/banano-miniapp-secure.XXXXXX.env)"
  chmod 0600 "$TEMP_CONFIG"

  {
    printf 'source %q\n' "$CONFIG_FILE"
    printf 'BACKEND_ORIGIN=%q\n' "$BACKEND_ORIGIN"
    printf 'BACKEND_HOST_HEADER=%q\n' "$BACKEND_HOST_HEADER"
    printf 'BACKEND_TLS_NAME=%q\n' "$BACKEND_TLS_NAME"
    printf 'BACKEND_HEALTH_PATH=%q\n' "$BACKEND_HEALTH_PATH"
    printf 'BACKEND_SSH_HOST=\n'
    printf 'CONFIGURE_BACKEND_UFW=0\n'
  } > "$TEMP_CONFIG"
}

run_frontend_installer() {
  log "Deploying frontend through backend HTTPS domain ${BACKEND_ORIGIN}"
  bash "$BASE_INSTALLER" --config "$TEMP_CONFIG" "$MODE"
}

harden_upstream_tls() {
  local site="/etc/nginx/sites-available/${NGINX_SITE_NAME}"
  [[ -f "$site" ]] || die "Generated Nginx site not found: $site"

  python3 - "$site" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
if "proxy_ssl_verify on;" not in text:
    lines = []
    for line in text.splitlines():
        lines.append(line)
        if line.strip().startswith("proxy_ssl_name "):
            indent = line[: len(line) - len(line.lstrip())]
            lines.extend([
                f"{indent}proxy_ssl_protocols TLSv1.2 TLSv1.3;",
                f"{indent}proxy_ssl_verify on;",
                f"{indent}proxy_ssl_verify_depth 4;",
                f"{indent}proxy_ssl_trusted_certificate /etc/ssl/certs/ca-certificates.crt;",
                f"{indent}proxy_ssl_session_reuse on;",
            ])
    text = "\n".join(lines) + "\n"
path.write_text(text, encoding="utf-8")
PY

  nginx -t
  systemctl reload nginx
  log "Backend TLS certificate verification enabled in frontend Nginx"
}

configure_backend_url_only() {
  [[ -n "$BACKEND_SSH_HOST" ]] || return 0

  local scheme="https"
  [[ "$SKIP_TLS" == "1" ]] && scheme="http"
  local miniapp_url="${scheme}://${FRONTEND_DOMAIN}/mini-app/"

  log "Updating only MINI_APP_URL on backend ${BACKEND_SSH_HOST}"
  ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new "$BACKEND_SSH_HOST" \
    "BACKEND_ENV_FILE=$(printf '%q' "$BACKEND_ENV_FILE") \
     BACKEND_SERVICE=$(printf '%q' "$BACKEND_SERVICE") \
     MINIAPP_URL=$(printf '%q' "$miniapp_url") \
     bash -s" <<'REMOTE'
set -Eeuo pipefail
[[ -f "$BACKEND_ENV_FILE" ]] || {
  echo "Backend env file not found: $BACKEND_ENV_FILE" >&2
  exit 1
}

cp -a "$BACKEND_ENV_FILE" "${BACKEND_ENV_FILE}.before-miniapp-$(date '+%Y%m%d-%H%M%S')"
python3 - "$BACKEND_ENV_FILE" "$MINIAPP_URL" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
value = sys.argv[2]
lines = path.read_text(encoding="utf-8").splitlines()
result = []
found = False
for line in lines:
    stripped = line.strip()
    if stripped and not stripped.startswith("#") and "=" in line:
        key = line.split("=", 1)[0].strip()
        if key == "MINI_APP_URL":
            result.append(f"MINI_APP_URL={value}")
            found = True
            continue
    result.append(line)
if not found:
    result.append(f"MINI_APP_URL={value}")
path.write_text("\n".join(result) + "\n", encoding="utf-8")
PY

systemctl restart "$BACKEND_SERVICE"
systemctl is-active --quiet "$BACKEND_SERVICE"
REMOTE
}

final_smoke() {
  local scheme="https"
  [[ "$SKIP_TLS" == "1" ]] && scheme="http"
  local frontend="${scheme}://${FRONTEND_DOMAIN}"

  curl -fsS --max-time 20 "${BACKEND_ORIGIN}${BACKEND_HEALTH_PATH}" >/dev/null
  curl -fsS --max-time 20 "${frontend}/frontend-health" | grep -q '"ok":true'

  local status
  status="$(curl -sS -o /tmp/banano-secure-bootstrap.json -w '%{http_code}' \
    --max-time 30 \
    -X POST "${frontend}/mini-app/api/bootstrap" \
    -H 'Content-Type: application/json' \
    --data '{}')"
  rm -f /tmp/banano-secure-bootstrap.json
  [[ "$status" == "400" || "$status" == "401" || "$status" == "403" ]] \
    || die "Unexpected bootstrap status after HTTPS proxy setup: $status"

  log "Ready: ${frontend}/mini-app/ -> ${BACKEND_ORIGIN}:443 -> backend Nginx -> localhost aiohttp"
}

main() {
  [[ "$EUID" -eq 0 ]] || die "Run as root or through sudo"
  parse_args "$@"
  load_and_validate_config
  make_sanitized_config
  run_frontend_installer
  harden_upstream_tls
  configure_backend_url_only
  final_smoke
}

main "$@"
