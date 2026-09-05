#!/usr/bin/env bash
set -Eeuo pipefail

python -m scripts.ensure_happyfox_schema
exec python -m bot.main
