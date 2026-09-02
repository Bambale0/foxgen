#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

export PROJECT_DIR
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-foxgen-happyfox}"
export SYSTEMD_SERVICE="${SYSTEMD_SERVICE:-foxgen-happyfox}"
export CONTAINER_NAME="${CONTAINER_NAME:-foxgen-happyfox-bot}"
export PRODUCT_ID=happyfox
export REDIS_PREFIX="${REDIS_PREFIX:-foxgen_happyfox}"
export HAPPYFOX_BACKEND_NETWORK="${HAPPYFOX_BACKEND_NETWORK:-foxgen_backend}"
export HAPPYFOX_REVERSE_PROXY_CONTAINER="${HAPPYFOX_REVERSE_PROXY_CONTAINER:-artflow-nginx-1}"
export HAPPYFOX_REVERSE_PROXY_CONFIG_DEST="${HAPPYFOX_REVERSE_PROXY_CONFIG_DEST:-/etc/nginx/conf.d/default.conf}"
export HAPPYFOX_LEGACY_UPSTREAM_TARGET="${HAPPYFOX_LEGACY_UPSTREAM_TARGET:-foxgen-api-1:8080}"
export HAPPYFOX_NEW_UPSTREAM_TARGET="${HAPPYFOX_NEW_UPSTREAM_TARGET:-${CONTAINER_NAME}:8080}"
export SKIP_BACKUP=1
export CUTOVER_STOP_CONTAINERS="${CUTOVER_STOP_CONTAINERS:-foxgen-api-1
foxgen-bot-1
foxgen-worker-1}"
export CUTOVER_RESTART_ON_FAILURE=1

cd "$PROJECT_DIR"

legacy_api_container="foxgen-api-1"
legacy_background_containers=(
  foxgen-bot-1
  foxgen-worker-1
)
REVERSE_PROXY_CONFIG_SOURCE=""
PUBLIC_ORIGIN=""
PUBLIC_DOMAIN=""

reverse_proxy_exists() {
  docker inspect "$HAPPYFOX_REVERSE_PROXY_CONTAINER" >/dev/null 2>&1
}

discover_reverse_proxy_config() {
  if [ -n "$REVERSE_PROXY_CONFIG_SOURCE" ]; then
    return 0
  fi
  reverse_proxy_exists || return 1

  REVERSE_PROXY_CONFIG_SOURCE="$(
    docker inspect "$HAPPYFOX_REVERSE_PROXY_CONTAINER" \
      --format '{{range .Mounts}}{{if eq .Destination "/etc/nginx/conf.d/default.conf"}}{{println .Source}}{{end}}{{end}}' \
      | head -n 1 \
      | tr -d '\r'
  )"
  [ -n "$REVERSE_PROXY_CONFIG_SOURCE" ] || {
    echo "[happyfox-deploy] Could not discover reverse proxy config bind mount" >&2
    return 1
  }
  [ -f "$REVERSE_PROXY_CONFIG_SOURCE" ] || {
    echo "[happyfox-deploy] Reverse proxy config source is missing: $REVERSE_PROXY_CONFIG_SOURCE" >&2
    return 1
  }
}

backup_reverse_proxy_config() {
  discover_reverse_proxy_config
  local backup_dir="$PROJECT_DIR/backups/pre-happyfox"
  install -d -m 0700 "$backup_dir"
  cp -a "$REVERSE_PROXY_CONFIG_SOURCE" "$backup_dir/reverse-proxy.latest.conf"
  if [ ! -f "$backup_dir/reverse-proxy.initial.conf" ]; then
    cp -a "$REVERSE_PROXY_CONFIG_SOURCE" "$backup_dir/reverse-proxy.initial.conf"
  fi
}

patch_reverse_proxy_target() {
  local target="$1"
  discover_reverse_proxy_config
  python3 "$PROJECT_DIR/scripts/patch_happyfox_reverse_proxy.py" \
    "$REVERSE_PROXY_CONFIG_SOURCE" \
    "$PUBLIC_DOMAIN" \
    --upstream happyfox_backend \
    --target "$target"
}

reload_reverse_proxy() {
  reverse_proxy_exists || return 1
  docker exec "$HAPPYFOX_REVERSE_PROXY_CONTAINER" nginx -t
  docker exec "$HAPPYFOX_REVERSE_PROXY_CONTAINER" nginx -s reload
}

restore_proxy_to_legacy() {
  if ! reverse_proxy_exists; then
    echo "[happyfox-deploy] Reverse proxy container is unavailable" >&2
    return 1
  fi
  if ! patch_reverse_proxy_target "$HAPPYFOX_LEGACY_UPSTREAM_TARGET"; then
    echo "[happyfox-deploy] Failed to switch reverse proxy back to legacy API" >&2
    return 1
  fi
  if ! reload_reverse_proxy; then
    echo "[happyfox-deploy] Legacy reverse proxy configuration did not validate/reload" >&2
    return 1
  fi
  echo "[happyfox-deploy] Reverse proxy points to legacy API"
}

rollback_legacy_app() {
  echo "[happyfox-deploy] Rolling back to legacy FoxGen application containers" >&2

  if docker inspect "$legacy_api_container" >/dev/null 2>&1; then
    docker start "$legacy_api_container" >/dev/null 2>&1 || true
  fi

  if ! restore_proxy_to_legacy; then
    echo "[happyfox-deploy] Rollback proxy switch failed; keeping HappyFox container online" >&2
    if docker inspect "$legacy_api_container" >/dev/null 2>&1; then
      docker stop --time 10 "$legacy_api_container" >/dev/null 2>&1 || true
    fi
    return 1
  fi

  docker compose \
    --project-directory "$PROJECT_DIR" \
    -f "$PROJECT_DIR/compose.backend.yml" \
    down --remove-orphans >/dev/null 2>&1 || true

  local name=""
  for name in "${legacy_background_containers[@]}"; do
    if docker inspect "$name" >/dev/null 2>&1; then
      docker start "$name" >/dev/null 2>&1 || true
    fi
  done

  echo "[happyfox-deploy] Legacy FoxGen runtime restored"
}

resolve_public_origin() {
  PUBLIC_ORIGIN="${HAPPYFOX_PUBLIC_ORIGIN:-}"
  if [ -z "$PUBLIC_ORIGIN" ]; then
    PUBLIC_ORIGIN="$(python3 - "$PROJECT_DIR/.env.happyfox.runtime" <<'PY'
import sys
from pathlib import Path

for raw_line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if not line.startswith("WEBHOOK_HOST="):
        continue
    value = line.split("=", 1)[1].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    print(value.rstrip("/"))
    raise SystemExit(0)
raise SystemExit("WEBHOOK_HOST is missing from HappyFox runtime overlay")
PY
    )"
  fi
  PUBLIC_ORIGIN="${PUBLIC_ORIGIN%/}"

  PUBLIC_DOMAIN="$(python3 - "$PUBLIC_ORIGIN" <<'PY'
import sys
from urllib.parse import urlsplit

value = sys.argv[1].strip()
parsed = urlsplit(value)
if (
    parsed.scheme != "https"
    or not parsed.hostname
    or parsed.username
    or parsed.password
    or parsed.query
    or parsed.fragment
    or parsed.path not in {"", "/"}
):
    raise SystemExit("HappyFox public origin must be a bare HTTPS origin")
print(parsed.hostname)
PY
  )"
}

python3 scripts/prepare_happyfox_production.py "$PROJECT_DIR"
python3 scripts/canonicalize_happyfox_runtime.py "$PROJECT_DIR/.env.happyfox.runtime"
python3 scripts/validate_happyfox_env.py .env .env.happyfox.runtime .env.postgres
resolve_public_origin

ACTION="${1:-deploy}"
if [ "$ACTION" != "deploy" ]; then
  exec bash scripts/deploy_backend_docker.sh "$ACTION"
fi

# Repair/normalize the persisted nginx config while the legacy API is still
# running. This also makes a previous failed cutover recoverable before we stop
# any legacy containers.
if ! reverse_proxy_exists; then
  echo "[happyfox-deploy] Reverse proxy container is missing: $HAPPYFOX_REVERSE_PROXY_CONTAINER" >&2
  exit 1
fi
backup_reverse_proxy_config
if ! restore_proxy_to_legacy; then
  echo "[happyfox-deploy] Refusing cutover with an invalid legacy proxy route" >&2
  exit 1
fi

if ! bash scripts/deploy_backend_docker.sh deploy; then
  echo "[happyfox-deploy] Docker cutover failed before reverse proxy switch" >&2
  # deploy_backend_docker.sh restores the legacy containers on its own. Keep
  # the proxy explicitly pinned to the legacy API as a second safety layer.
  restore_proxy_to_legacy || true
  exit 1
fi

if ! patch_reverse_proxy_target "$HAPPYFOX_NEW_UPSTREAM_TARGET"; then
  rollback_legacy_app || true
  echo "[happyfox-deploy] Failed to configure HappyFox reverse proxy target" >&2
  exit 1
fi
if ! reload_reverse_proxy; then
  rollback_legacy_app || true
  echo "[happyfox-deploy] Reverse proxy configuration validation/reload failed" >&2
  exit 1
fi

if ! curl -fsS --retry 8 --retry-delay 2 --retry-all-errors \
  --max-time 15 "${PUBLIC_ORIGIN}/health" >/dev/null; then
  rollback_legacy_app || true
  echo "[happyfox-deploy] Public backend health check failed" >&2
  exit 1
fi

echo "[happyfox-deploy] PUBLIC_HEALTH_OK ${PUBLIC_ORIGIN}/health"
