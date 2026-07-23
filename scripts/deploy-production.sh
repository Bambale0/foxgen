#!/usr/bin/env bash
set -Eeuo pipefail

EXPECTED_SHA="${1:-}"
APP_DIR="${DEPLOY_PATH:-/root/foxgen}"
COMPOSE_FILE="${FOXGEN_COMPOSE_FILE:-docker-compose.prod.yml}"
LOCK_FILE="${DEPLOY_LOCK_FILE:-/tmp/foxgen-production-deploy.lock}"

log() {
  printf '[foxgen-deploy] %s\n' "$*"
}

fail() {
  printf '[foxgen-deploy] ERROR: %s\n' "$*" >&2
  exit 1
}

compose() {
  docker compose --env-file .env -f "$COMPOSE_FILE" "$@"
}

on_error() {
  local exit_code=$?
  local line_number="${1:-unknown}"
  printf '[foxgen-deploy] ERROR: deployment failed at line %s with exit code %s\n' \
    "$line_number" "$exit_code" >&2
  compose ps >&2 || true
  compose logs --tail=200 api worker bot migrate postgres redis minio >&2 || true
  exit "$exit_code"
}

trap 'on_error "$LINENO"' ERR

command -v git >/dev/null 2>&1 || fail "git is not installed"
command -v docker >/dev/null 2>&1 || fail "docker is not installed"
command -v flock >/dev/null 2>&1 || fail "flock is not installed"
command -v curl >/dev/null 2>&1 || fail "curl is not installed"
docker compose version >/dev/null 2>&1 || fail "docker compose plugin is unavailable"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  fail "another production deployment is already running"
fi

cd "$APP_DIR"
[ -d .git ] || fail "$APP_DIR is not a Git repository"
[ -f "$COMPOSE_FILE" ] || fail "$COMPOSE_FILE is missing"
[ -f .env ] || fail ".env is missing; deployment never creates or overwrites production secrets"

read_env_value() {
  local key="$1"
  awk -v key="$key" '
    index($0, key "=") == 1 {
      value = substr($0, length(key) + 2)
    }
    END {
      sub(/\r$/, "", value)
      print value
    }
  ' .env
}

require_env_value() {
  local key="$1"
  local value
  value="$(read_env_value "$key")"
  [ -n "$value" ] || fail "$key must be set in the server-side .env"
  case "$value" in
    *"<"*|*">"*|change-me|changeme)
      fail "$key still contains a placeholder value"
      ;;
  esac
}

for required_key in \
  FOXGEN_ENV \
  FOXGEN_TELEGRAM_BOT_TOKEN \
  FOXGEN_INTERNAL_API_TOKEN \
  FOXGEN_DATABASE_URL \
  FOXGEN_REDIS_URL \
  FOXGEN_KIE_API_KEY \
  FOXGEN_KIE_CALLBACK_BASE_URL \
  FOXGEN_KIE_WEBHOOK_HMAC_KEY \
  FOXGEN_POSTGRES_PASSWORD \
  FOXGEN_REDIS_PASSWORD \
  FOXGEN_S3_ENDPOINT_URL \
  FOXGEN_S3_BUCKET \
  FOXGEN_S3_ACCESS_KEY_ID \
  FOXGEN_S3_SECRET_ACCESS_KEY; do
  require_env_value "$required_key"
done

[ "$(read_env_value FOXGEN_ENV)" = "production" ] || \
  fail "FOXGEN_ENV must be production"
[ "$(read_env_value FOXGEN_POSTGRES_PASSWORD)" != "foxgen" ] || \
  fail "FOXGEN_POSTGRES_PASSWORD must not use the development password"
[ "$(read_env_value FOXGEN_S3_SECRET_ACCESS_KEY)" != "foxgen-development-secret" ] || \
  fail "FOXGEN_S3_SECRET_ACCESS_KEY must not use the development secret"

if [ -n "$EXPECTED_SHA" ] && [[ ! "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  fail "expected commit must be a full 40-character SHA"
fi

log "fetching origin/main"
git fetch --prune origin main
ORIGIN_SHA="$(git rev-parse origin/main)"

if [ -n "$EXPECTED_SHA" ] && [ "$ORIGIN_SHA" != "$EXPECTED_SHA" ]; then
  log "deployment skipped: tested SHA $EXPECTED_SHA was superseded by $ORIGIN_SHA"
  exit 0
fi

CURRENT_BRANCH="$(git branch --show-current)"
[ "$CURRENT_BRANCH" = "main" ] || fail "repository must be on main, found: $CURRENT_BRANCH"

if ! git diff --quiet || ! git diff --cached --quiet; then
  fail "working tree has tracked local changes; refusing to overwrite them"
fi

PREVIOUS_SHA="$(git rev-parse HEAD)"
log "updating main with fast-forward only"
git pull --ff-only origin main
DEPLOYED_SHA="$(git rev-parse HEAD)"

if [ -n "$EXPECTED_SHA" ] && [ "$DEPLOYED_SHA" != "$EXPECTED_SHA" ]; then
  fail "checked out SHA $DEPLOYED_SHA does not match tested SHA $EXPECTED_SHA"
fi

export FOXGEN_IMAGE_TAG="$DEPLOYED_SHA"

log "validating production Compose configuration"
compose config --quiet

log "building immutable application image foxgen:$DEPLOYED_SHA"
compose build --pull api

log "starting stateful dependencies"
compose up -d postgres redis minio

wait_for_container() {
  local service="$1"
  local expected_health="$2"
  local timeout_seconds="$3"
  local deadline=$((SECONDS + timeout_seconds))

  while [ "$SECONDS" -lt "$deadline" ]; do
    local container_id state health
    container_id="$(compose ps -q "$service")"
    if [ -n "$container_id" ]; then
      state="$(docker inspect --format '{{.State.Status}}' "$container_id")"
      health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container_id")"
      if [ "$state" = "running" ] && {
        [ "$expected_health" = "none" ] || [ "$health" = "$expected_health" ];
      }; then
        return 0
      fi
      if [ "$state" = "exited" ] || [ "$state" = "dead" ]; then
        compose logs --tail=200 "$service" >&2 || true
        fail "$service stopped before becoming ready"
      fi
    fi
    sleep 2
  done

  compose logs --tail=200 "$service" >&2 || true
  fail "$service did not become ready within ${timeout_seconds}s"
}

wait_for_container postgres healthy 120
wait_for_container redis healthy 120
wait_for_container minio none 120

log "ensuring the private media bucket exists"
compose run --rm minio-init

log "applying database migrations"
compose run --rm migrate

log "starting API, worker and Telegram bot"
compose up -d --remove-orphans api worker bot

wait_for_container api healthy 180
wait_for_container worker none 120
wait_for_container bot none 120

PUBLIC_PORT="$(read_env_value FOXGEN_PUBLIC_API_PORT)"
PUBLIC_PORT="${PUBLIC_PORT:-8080}"
log "checking API readiness on loopback port $PUBLIC_PORT"
curl \
  --fail \
  --silent \
  --show-error \
  --max-time 10 \
  "http://127.0.0.1:${PUBLIC_PORT}/health/ready" >/dev/null

log "deployment completed: $PREVIOUS_SHA -> $DEPLOYED_SHA"
compose ps
