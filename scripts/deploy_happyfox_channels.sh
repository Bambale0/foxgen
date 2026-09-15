#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
EXPECTED_SHA="${1:-$(git -C "$PROJECT_DIR" rev-parse HEAD)}"

cd "$PROJECT_DIR"
bash scripts/deploy_happyfox_dedicated.sh "$EXPECTED_SHA"
bash scripts/activate_happyfox_channel_miniapps.sh "$EXPECTED_SHA"
