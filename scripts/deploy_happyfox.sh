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

for key in \
  BOT_TOKEN \
  MINI_APP_URL \
  WEBHOOK_HOST \
  DATABASE_URL \
  REDIS_URL \
  REDIS_PREFIX \
  KIE_AI_API_KEY; do
  require_value "$key"
done

mini_app_url="$(read_env_value MINI_APP_URL)"
webhook_host="$(read_env_value WEBHOOK_HOST)"
database_url="$(read_env_value DATABASE_URL)"
redis_prefix="$(read_env_value REDIS_PREFIX)"

for product_url in "$mini_app_url" "$webhook_host"; do
  case "$product_url" in
    *cdn.chillcreative.ru*|*tanyapi.chillcreative.ru*|*tanyapp*|*neuromix*)
      echo "[happyfox-deploy] ERROR: product URL points to a NEUROMIX/Tanya host: $product_url" >&2
      exit 1
      ;;
  esac
done

case "$database_url" in
  postgresql://*|postgres://*|postgresql+asyncpg://*) ;;
  *)
    echo '[happyfox-deploy] ERROR: HappyFox production requires PostgreSQL DATABASE_URL' >&2
    exit 1
    ;;
esac

case "$redis_prefix" in
  banano_kling|neuromix|tanyapi|'')
    echo '[happyfox-deploy] ERROR: REDIS_PREFIX must be isolated for HappyFox' >&2
    exit 1
    ;;
esac

export PROJECT_DIR
export COMPOSE_FILE="${COMPOSE_FILE:-${PROJECT_DIR}/compose.backend.yml}"
export SYSTEMD_SERVICE="${SYSTEMD_SERVICE:-foxgen-happyfox}"
export CONTAINER_NAME="${CONTAINER_NAME:-foxgen-happyfox-bot}"
export PRODUCT_ID=happyfox

printf '[happyfox-deploy] project=%s action=%s container=%s service=%s redis_prefix=%s\n' \
  "$PROJECT_DIR" "$ACTION" "$CONTAINER_NAME" "$SYSTEMD_SERVICE" "$redis_prefix"

exec bash "$PROJECT_DIR/scripts/deploy_backend_docker.sh" "$ACTION"
