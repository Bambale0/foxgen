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
export SKIP_BACKUP=1
export CUTOVER_STOP_CONTAINERS="${CUTOVER_STOP_CONTAINERS:-foxgen-api-1
foxgen-bot-1
foxgen-worker-1}"
export CUTOVER_RESTART_ON_FAILURE=1

cd "$PROJECT_DIR"

legacy_containers=(
  foxgen-api-1
  foxgen-bot-1
  foxgen-worker-1
)

rollback_legacy_app() {
  echo "[happyfox-deploy] Rolling back to legacy FoxGen application containers" >&2
  docker compose \
    --project-directory "$PROJECT_DIR" \
    -f "$PROJECT_DIR/compose.backend.yml" \
    down --remove-orphans >/dev/null 2>&1 || true

  local name=""
  for name in "${legacy_containers[@]}"; do
    if docker inspect "$name" >/dev/null 2>&1; then
      docker start "$name" >/dev/null 2>&1 || true
    fi
  done

  if docker inspect "$HAPPYFOX_REVERSE_PROXY_CONTAINER" >/dev/null 2>&1; then
    docker exec "$HAPPYFOX_REVERSE_PROXY_CONTAINER" nginx -t >/dev/null 2>&1 || true
    docker exec "$HAPPYFOX_REVERSE_PROXY_CONTAINER" nginx -s reload >/dev/null 2>&1 || true
  fi
}

resolve_public_origin() {
  python3 - "$PROJECT_DIR/.env.happyfox.runtime" <<'PY'
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
}

public_health_ok() {
  local retries="${1:-0}"
  curl -fsS \
    --retry "$retries" \
    --retry-delay 1 \
    --retry-all-errors \
    --max-time 10 \
    "${PUBLIC_ORIGIN}/health" >/dev/null
}

python3 scripts/prepare_happyfox_production.py "$PROJECT_DIR"
python3 scripts/canonicalize_happyfox_runtime.py "$PROJECT_DIR/.env.happyfox.runtime"
python3 scripts/validate_happyfox_env.py .env .env.happyfox.runtime .env.postgres

ACTION="${1:-deploy}"
if [ "$ACTION" != "deploy" ]; then
  exec bash scripts/deploy_backend_docker.sh "$ACTION"
fi

PUBLIC_ORIGIN="$(resolve_public_origin)"
bash scripts/deploy_backend_docker.sh deploy

# The reverse proxy is shared by several unrelated products. If its currently
# running workers already route HappyFox to the newly healthy container, there
# is no reason to reload the global nginx configuration. This prevents an
# unrelated broken upstream from rolling back an otherwise healthy HappyFox
# release. A reload is attempted only when the live HappyFox route actually
# needs it.
if public_health_ok 2; then
  echo "[happyfox-deploy] Existing reverse proxy already routes the new HappyFox backend; reload skipped"
elif docker inspect "$HAPPYFOX_REVERSE_PROXY_CONTAINER" >/dev/null 2>&1; then
  echo "[happyfox-deploy] Public route is not healthy yet; validating reverse proxy before reload"
  if ! docker exec "$HAPPYFOX_REVERSE_PROXY_CONTAINER" nginx -t; then
    rollback_legacy_app
    echo "[happyfox-deploy] Reverse proxy configuration validation failed" >&2
    exit 1
  fi
  docker exec "$HAPPYFOX_REVERSE_PROXY_CONTAINER" nginx -s reload
fi

if ! public_health_ok 8; then
  rollback_legacy_app
  echo "[happyfox-deploy] Public backend health check failed" >&2
  exit 1
fi

echo "[happyfox-deploy] PUBLIC_HEALTH_OK ${PUBLIC_ORIGIN}/health"
