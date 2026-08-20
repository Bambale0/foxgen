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
export SKIP_BACKUP=1
export CUTOVER_STOP_CONTAINERS="${CUTOVER_STOP_CONTAINERS:-foxgen-api-1
foxgen-bot-1
foxgen-worker-1}"
export CUTOVER_RESTART_ON_FAILURE=1

cd "$PROJECT_DIR"

python3 scripts/prepare_happyfox_production.py "$PROJECT_DIR"
python3 scripts/validate_happyfox_env.py .env .env.happyfox.runtime .env.postgres

exec bash scripts/deploy_backend_docker.sh "${1:-deploy}"
