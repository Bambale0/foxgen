#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
ACTION="${1:-deploy}"

cd "$PROJECT_DIR"

[ -f .env ] || {
  echo '[happyfox-deploy] ERROR: .env is missing' >&2
  exit 1
}

read_env_value() {
  local key="$1"
  awk -v key="$key" '
    index($0, key "=") == 1 { value = substr($0, length(key) + 2) }
    END { sub(/\r$/, "", value); print value }
  ' .env
}

require_value() {
  local key="$1" value
  value="$(read_env_value "$key")"
  [ -n "$value" ] || {
    echo "[happyfox-deploy] ERROR: $key must be set in server-side .env" >&2
    exit 1
  }
}

require_value BOT_TOKEN
require_value MINI_APP_URL

mini_app_url="$(read_env_value MINI_APP_URL)"
case "$mini_app_url" in
  *chillcreative.ru*|*tanyapi*|*neuromix*)
    echo '[happyfox-deploy] ERROR: MINI_APP_URL points to a NEUROMIX/Tanya host' >&2
    exit 1
    ;;
esac

export PROJECT_DIR
export COMPOSE_FILE="${COMPOSE_FILE:-${PROJECT_DIR}/compose.backend.yml}"
export SYSTEMD_SERVICE="${SYSTEMD_SERVICE:-foxgen-happyfox}"
export CONTAINER_NAME="${CONTAINER_NAME:-foxgen-happyfox-bot}"
export PRODUCT_ID=happyfox

printf '[happyfox-deploy] project=%s action=%s container=%s service=%s\n' \
  "$PROJECT_DIR" "$ACTION" "$CONTAINER_NAME" "$SYSTEMD_SERVICE"

exec bash "$PROJECT_DIR/scripts/deploy_backend_docker.sh" "$ACTION"
