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
[ -f .env ] || fail ".env is missing; deployment never creates the production environment file"

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

bootstrap_miniapp_jwt_secret() {
  local existing generated temporary
  existing="$(read_env_value FOXGEN_MINIAPP_JWT_SECRET)"
  if [ -n "$existing" ]; then
    return 0
  fi

  command -v openssl >/dev/null 2>&1 || \
    fail "openssl is required to bootstrap the missing Mini App JWT secret"
  generated="$(openssl rand -hex 48)"
  [ "${#generated}" -eq 96 ] || fail "failed to generate Mini App JWT secret"

  umask 077
  temporary="$(mktemp "$APP_DIR/.env.miniapp.XXXXXX")"
  MINIAPP_SECRET="$generated" awk '
    BEGIN { replaced = 0 }
    index($0, "FOXGEN_MINIAPP_JWT_SECRET=") == 1 {
      if (!replaced) {
        print "FOXGEN_MINIAPP_JWT_SECRET=" ENVIRON["MINIAPP_SECRET"]
        replaced = 1
      }
      next
    }
    { print }
    END {
      if (!replaced) {
        print "FOXGEN_MINIAPP_JWT_SECRET=" ENVIRON["MINIAPP_SECRET"]
      }
    }
  ' .env > "$temporary"
  chmod 600 "$temporary"
  mv "$temporary" .env
  chmod 600 .env
  unset generated MINIAPP_SECRET
  log "bootstrapped missing dedicated Mini App JWT secret in server-side .env"
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

miniapp_enabled() {
  local raw
  raw="$(read_env_value FOXGEN_MINIAPP_ENABLED)"
  raw="${raw:-true}"
  case "${raw,,}" in
    0|false|no|off) return 1 ;;
    *) return 0 ;;
  esac
}

miniapp_release() {
  local shell release
  shell="$APP_DIR/src/foxgen/miniapp_static/index.html"
  [ -f "$shell" ] || fail "Mini App shell is missing"
  release="$(sed -n 's/.*name="foxgen-miniapp-shell" content="\([^"]*\)".*/\1/p' "$shell" | head -n1)"
  [ -n "$release" ] || fail "Mini App release marker is missing"
  printf '%s\n' "$release"
}

append_miniapp_release() {
  local url release separator
  url="$1"
  release="$(miniapp_release)"
  separator='?'
  [[ "$url" == *\?* ]] && separator='&'
  printf '%s%srelease=%s\n' "$url" "$separator" "$release"
}

resolved_miniapp_url() {
  local explicit base
  explicit="$(read_env_value FOXGEN_MINIAPP_PUBLIC_URL)"
  if [ -n "$explicit" ]; then
    append_miniapp_release "${explicit%/}/"
    return 0
  fi
  base="$(read_env_value FOXGEN_KIE_CALLBACK_BASE_URL)"
  [ -n "$base" ] || return 1
  append_miniapp_release "${base%/}/mini-app/"
}

# Legacy production environments predate Happy Fox. This is the only credential
# deploy is allowed to create automatically, and only once while holding the lock.
bootstrap_miniapp_jwt_secret

for required_key in \
  FOXGEN_ENV \
  FOXGEN_TELEGRAM_BOT_TOKEN \
  FOXGEN_MINIAPP_JWT_SECRET \
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

dirty_paths=()
while IFS= read -r -d '' path; do
  dirty_paths+=("$path")
done < <(
  {
    git diff --name-only -z
    git diff --cached --name-only -z
  } | sort -zu
)

if [ "${#dirty_paths[@]}" -gt 0 ]; then
  divergent_paths=()
  for path in "${dirty_paths[@]}"; do
    if ! git diff --quiet origin/main -- "$path"; then
      divergent_paths+=("$path")
    fi
  done

  if [ "${#divergent_paths[@]}" -gt 0 ]; then
    printf '[foxgen-deploy] ERROR: tracked server changes differ from tested origin/main:\n' >&2
    for path in "${divergent_paths[@]}"; do
      printf '[foxgen-deploy] ERROR:   %s\n' "$path" >&2
    done
    fail "refusing to overwrite unique tracked production changes"
  fi

  log "tracked server drift already matches origin/main; reconciling ${#dirty_paths[@]} path(s)"
  git restore --staged --worktree -- "${dirty_paths[@]}"
  if ! git diff --quiet || ! git diff --cached --quiet; then
    fail "tracked working tree remained dirty after safe reconciliation"
  fi
fi

PREVIOUS_SHA="$(git rev-parse HEAD)"
log "updating main with fast-forward only"
git pull --ff-only origin main
DEPLOYED_SHA="$(git rev-parse HEAD)"

if [ -n "$EXPECTED_SHA" ] && [ "$DEPLOYED_SHA" != "$EXPECTED_SHA" ]; then
  fail "checked out SHA $DEPLOYED_SHA does not match tested SHA $EXPECTED_SHA"
fi

export FOXGEN_IMAGE_TAG="$DEPLOYED_SHA"
EXPECTED_IMAGE="foxgen:$DEPLOYED_SHA"

log "validating production Compose configuration"
compose config --quiet

log "building immutable application image $EXPECTED_IMAGE"
compose build --pull api

docker image inspect "$EXPECTED_IMAGE" >/dev/null 2>&1 || \
  fail "immutable application image $EXPECTED_IMAGE was not built"

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

assert_service_image() {
  local service="$1"
  local container_id image
  container_id="$(compose ps -q "$service")"
  [ -n "$container_id" ] || fail "$service container is missing"
  image="$(docker inspect --format '{{.Config.Image}}' "$container_id")"
  [ "$image" = "$EXPECTED_IMAGE" ] || \
    fail "$service is running $image instead of tested $EXPECTED_IMAGE"
}

reload_local_https_ingress() {
  local api_container backend_network
  local -a candidates=()
  api_container="$(compose ps -q api)"
  [ -n "$api_container" ] || fail "api container is missing before ingress reload"
  backend_network="$(
    docker inspect --format '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}' \
      "$api_container" | awk '/_backend$/ { print; exit }'
  )"
  if [ -z "$backend_network" ]; then
    log "no local backend network found; relying on public ingress smoke"
    return 0
  fi

  while IFS= read -r container_id; do
    [ -n "$container_id" ] && candidates+=("$container_id")
  done < <(docker ps -q --filter "network=$backend_network" --filter publish=443)

  if [ "${#candidates[@]}" -eq 0 ]; then
    log "no local HTTPS ingress container found on $backend_network; relying on public ingress smoke"
    return 0
  fi
  [ "${#candidates[@]}" -eq 1 ] || \
    fail "multiple HTTPS ingress containers found on $backend_network; refusing ambiguous reload"

  if ! docker exec "${candidates[0]}" sh -lc 'command -v nginx >/dev/null 2>&1'; then
    log "local HTTPS ingress is not nginx; relying on public ingress smoke"
    return 0
  fi
  log "validating and reloading local shared nginx ingress"
  docker exec "${candidates[0]}" nginx -t
  docker exec "${candidates[0]}" nginx -s reload
}

verify_live_bot_webapp_code() {
  local bot_container
  bot_container="$(compose ps -q bot)"
  [ -n "$bot_container" ] || fail "bot container is missing"
  docker exec "$bot_container" python -c '
import foxgen.bot.app as app
from urllib.parse import parse_qs, urlsplit
from foxgen.bot.keyboards import main_menu, resolve_miniapp_url
from foxgen.miniapp_release import MINIAPP_RELEASE, MINIAPP_RELEASE_QUERY_KEY
url = resolve_miniapp_url()
button = main_menu().inline_keyboard[0][0]
assert hasattr(app, "configure_miniapp_menu")
assert url
assert parse_qs(urlsplit(url).query).get(MINIAPP_RELEASE_QUERY_KEY) == [MINIAPP_RELEASE]
assert button.web_app is not None
assert button.web_app.url == url
assert button.callback_data is None
' || fail "live bot image does not expose the current Happy Fox WebApp entrypoint"
}

verify_public_miniapp() {
  local miniapp_url expected_release deadline remaining attempt_timeout
  local html headers_file html_file cache_control content_type product_home_url product_home_js
  miniapp_url="$1"
  expected_release="$2"
  deadline=$((SECONDS + 30))
  product_home_url="$(
    MINIAPP_URL="$miniapp_url" EXPECTED_RELEASE="$expected_release" python3 - <<'PY'
import os
from urllib.parse import urlencode, urlsplit, urlunsplit

parts = urlsplit(os.environ["MINIAPP_URL"])
query = urlencode({"v": os.environ["EXPECTED_RELEASE"]})
print(urlunsplit((parts.scheme, parts.netloc, "/mini-app/product-home.js", query, "")))
PY
  )"

  while [ "$SECONDS" -lt "$deadline" ]; do
    remaining=$((deadline - SECONDS))
    attempt_timeout=$((remaining < 5 ? remaining : 5))
    headers_file="$(mktemp)"
    html_file="$(mktemp)"

    if curl \
      --fail \
      --silent \
      --show-error \
      --location \
      --max-time "$attempt_timeout" \
      --dump-header "$headers_file" \
      --output "$html_file" \
      "$miniapp_url"; then
      html="$(cat "$html_file")"
      cache_control="$(
        awk '
          /^HTTP\// { value = "" }
          tolower($0) ~ /^cache-control:/ {
            line = $0
            sub(/\r$/, "", line)
            sub(/^[^:]+:[[:space:]]*/, "", line)
            value = line
          }
          END { print value }
        ' "$headers_file"
      )"
      content_type="$(
        awk '
          /^HTTP\// { value = "" }
          tolower($0) ~ /^content-type:/ {
            line = $0
            sub(/\r$/, "", line)
            sub(/^[^:]+:[[:space:]]*/, "", line)
            value = line
          }
          END { print value }
        ' "$headers_file"
      )"

      if [[ "${cache_control,,}" == *"no-store"* ]] && \
        [[ "${content_type,,}" == text/html* ]] && \
        grep -Fq "name=\"foxgen-miniapp-shell\" content=\"${expected_release}\"" <<<"$html" && \
        grep -Fq "/mini-app/product-home.js?v=${expected_release}" <<<"$html" && \
        grep -Fq "/mini-app/product-home.css?v=${expected_release}" <<<"$html" && \
        product_home_js="$(
          curl --fail --silent --show-error --location --max-time "$attempt_timeout" \
            "$product_home_url"
        )" && \
        grep -Fq "Каталог" <<<"$product_home_js"; then
        rm -f "$headers_file" "$html_file"
        return 0
      fi
    fi

    rm -f "$headers_file" "$html_file"
    [ "$SECONDS" -lt "$deadline" ] || break
    remaining=$((deadline - SECONDS))
    log "public Happy Fox ${expected_release} smoke not ready; ${remaining}s remain in the post-reload window"
    sleep "$((remaining < 2 ? remaining : 2))"
  done
  return 1
}

verify_telegram_menu() {
  local miniapp_url bot_token menu_json deadline remaining attempt_timeout
  miniapp_url="$1"
  bot_token="$(read_env_value FOXGEN_TELEGRAM_BOT_TOKEN)"
  deadline=$((SECONDS + 30))

  while [ "$SECONDS" -lt "$deadline" ]; do
    remaining=$((deadline - SECONDS))
    attempt_timeout=$((remaining < 5 ? remaining : 5))
    if menu_json="$(
      curl --fail --silent --show-error --max-time "$attempt_timeout" \
        "https://api.telegram.org/bot${bot_token}/getChatMenuButton"
    )" && MINIAPP_URL="$miniapp_url" MENU_JSON="$menu_json" python3 - <<'PY'
import json
import os

expected = os.environ["MINIAPP_URL"]
payload = json.loads(os.environ["MENU_JSON"])
if payload.get("ok") is not True:
    raise SystemExit(1)
result = payload.get("result") or {}
if result.get("type") != "web_app":
    raise SystemExit(1)
if result.get("text") != "Happy Fox":
    raise SystemExit(1)
actual = ((result.get("web_app") or {}).get("url") or "")
if actual != expected:
    raise SystemExit(1)
PY
    then
      return 0
    fi
    [ "$SECONDS" -lt "$deadline" ] || break
    remaining=$((deadline - SECONDS))
    log "Telegram Happy Fox menu not ready; ${remaining}s remain in the post-recreate window"
    sleep "$((remaining < 2 ? remaining : 2))"
  done
  return 1
}

wait_for_container postgres healthy 120
wait_for_container redis healthy 120
wait_for_container minio none 120

log "ensuring the private media bucket exists"
compose run -T --rm minio-init </dev/null

log "applying database migrations"
compose run -T --rm migrate </dev/null

log "force-recreating API, worker and Telegram bot from $EXPECTED_IMAGE"
compose up -d --force-recreate --no-deps api worker bot

wait_for_container api healthy 180
wait_for_container worker none 120
wait_for_container bot none 120

for service in api worker bot; do
  assert_service_image "$service"
done
log "all application services run the exact tested image $EXPECTED_IMAGE"

verify_live_bot_webapp_code
reload_local_https_ingress

PUBLIC_PORT="$(read_env_value FOXGEN_PUBLIC_API_PORT)"
PUBLIC_PORT="${PUBLIC_PORT:-8080}"
log "checking API readiness on loopback port $PUBLIC_PORT"
curl \
  --fail \
  --silent \
  --show-error \
  --max-time 10 \
  "http://127.0.0.1:${PUBLIC_PORT}/health/ready" >/dev/null

if miniapp_enabled; then
  MINIAPP_RELEASE="$(miniapp_release)"
  MINIAPP_URL="$(resolved_miniapp_url)" || fail "Mini App is enabled but no public URL is configured"
  log "checking public Happy Fox Mini App release $MINIAPP_RELEASE with bounded post-reload retry"
  verify_public_miniapp "$MINIAPP_URL" "$MINIAPP_RELEASE" || \
    fail "public Happy Fox Mini App $MINIAPP_RELEASE did not become ready within 30s"
  verify_telegram_menu "$MINIAPP_URL" || \
    fail "Telegram Happy Fox menu did not converge to $MINIAPP_URL within 30s"
  log "Happy Fox $MINIAPP_RELEASE public WebApp and Telegram menu verified"
fi

log "deployment completed: $PREVIOUS_SHA -> $DEPLOYED_SHA"
compose ps
