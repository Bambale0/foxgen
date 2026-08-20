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

cd "$PROJECT_DIR"

python3 scripts/validate_happyfox_env.py .env .env.postgres

exec bash scripts/deploy_backend_docker.sh "${1:-deploy}"
