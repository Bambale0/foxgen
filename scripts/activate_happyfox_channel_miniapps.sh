#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 027

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
EXPECTED_SHA="${1:-$(git -C "$PROJECT_DIR" rev-parse HEAD)}"
CONFIG_FILE="${HAPPYFOX_MAX_MINIAPP_CONFIG:-/etc/foxgen-happyfox/max-miniapp.env}"
APP_ROOT="${HAPPYFOX_TELEGRAM_MINIAPP_ROOT:-/var/www/happyfox-app/mini-app}"
MAX_ROOT_DEFAULT="/var/www/happyfox-max/mini-app"
RUNTIME_ENV="${HAPPYFOX_RUNTIME_ENV:-$PROJECT_DIR/.env.happyfox.runtime}"
NGINX_SITE="${HAPPYFOX_NGINX_SITE:-/etc/nginx/sites-available/happyfox.conf}"

log() { printf '[happyfox-miniapp-split] %s\n' "$*"; }
die() { printf '[happyfox-miniapp-split] ERROR: %s\n' "$*" >&2; exit 1; }

[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || die "expected a full 40-character SHA"
[[ -s "$APP_ROOT/revision.txt" ]] || die "Telegram Mini App release is missing at $APP_ROOT"
[[ "$(tr -d '\r\n' < "$APP_ROOT/revision.txt")" == "$EXPECTED_SHA" ]] \
  || die "Telegram Mini App revision does not match $EXPECTED_SHA"

if [[ ! -s "$CONFIG_FILE" ]]; then
  log "split config is absent; keeping transitional shared Mini App host"
  exit 0
fi

# shellcheck disable=SC1090
source "$CONFIG_FILE"
: "${MAX_MINIAPP_ORIGIN:?MAX_MINIAPP_ORIGIN is required in $CONFIG_FILE}"
MAX_MINIAPP_ROOT="${MAX_MINIAPP_ROOT:-$MAX_ROOT_DEFAULT}"
MAX_MINIAPP_ORIGIN="${MAX_MINIAPP_ORIGIN%/}"

python3 - "$MAX_MINIAPP_ORIGIN" <<'PY'
import sys
from urllib.parse import urlsplit
value = sys.argv[1]
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
    raise SystemExit("MAX_MINIAPP_ORIGIN must be a bare HTTPS origin")
if parsed.hostname == "app.happy-fox.online":
    raise SystemExit("MAX Mini App split origin must differ from Telegram app.happy-fox.online")
PY

[[ -s "$RUNTIME_ENV" ]] || die "HappyFox runtime env is missing: $RUNTIME_ENV"
[[ -s "$NGINX_SITE" ]] || die "HappyFox nginx site is missing: $NGINX_SITE"

work="$(mktemp -d)"
cleanup() { rm -rf "$work"; }
trap cleanup EXIT
cp -a "$APP_ROOT/." "$work/generic/"

install -d -m 0755 "$MAX_MINIAPP_ROOT"
find "$MAX_MINIAPP_ROOT" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
cp -a "$work/generic/." "$MAX_MINIAPP_ROOT/"

python3 "$PROJECT_DIR/scripts/render_happyfox_miniapp_channel.py" "$APP_ROOT" telegram
python3 "$PROJECT_DIR/scripts/render_happyfox_miniapp_channel.py" "$MAX_MINIAPP_ROOT" max
find "$APP_ROOT" "$MAX_MINIAPP_ROOT" -type d -exec chmod 0755 {} +
find "$APP_ROOT" "$MAX_MINIAPP_ROOT" -type f -exec chmod 0644 {} +

python3 - "$RUNTIME_ENV" "$MAX_MINIAPP_ORIGIN" <<'PY'
from pathlib import Path
import os
import sys

path = Path(sys.argv[1])
origin = sys.argv[2].rstrip("/")
lines = path.read_text(encoding="utf-8").splitlines()
result: list[str] = []
found = False
for raw in lines:
    stripped = raw.strip()
    if stripped.startswith("MAX_MINI_APP_URL="):
        result.append(f"MAX_MINI_APP_URL='{origin}/mini-app/'")
        found = True
    else:
        result.append(raw)
if not found:
    result.append(f"MAX_MINI_APP_URL='{origin}/mini-app/'")
tmp = path.with_suffix(path.suffix + ".tmp")
tmp.write_text("\n".join(result) + "\n", encoding="utf-8")
os.chmod(tmp, 0o600)
tmp.replace(path)
PY

python3 - "$NGINX_SITE" "$MAX_MINIAPP_ORIGIN" <<'PY'
from pathlib import Path
import sys
from urllib.parse import urlsplit

path = Path(sys.argv[1])
origin = sys.argv[2].rstrip("/")
host = urlsplit(origin).hostname
text = path.read_text(encoding="utf-8")
old = "return 302 https://app.happy-fox.online/mini-app/;"
new = f"return 302 {origin}/mini-app/;"
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise SystemExit("MAX launch redirect was not found in HappyFox nginx site")
path.write_text(text, encoding="utf-8")
PY

nginx -t
systemctl reload nginx

COMPOSE_PROJECT_NAME=foxgen-happyfox \
  HAPPYFOX_IMAGE=foxgen-happyfox-bot:local \
  docker compose -f "$PROJECT_DIR/compose.backend.yml" up -d --no-build bot

for i in $(seq 1 45); do
  health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' foxgen-happyfox-bot 2>/dev/null || true)"
  [[ "$health" == "healthy" ]] && break
  [[ "$health" != "unhealthy" && "$health" != "exited" ]] || die "HappyFox bot became $health after MAX Mini App activation"
  sleep 2
  [[ "$i" -lt 45 ]] || die "HappyFox bot did not become healthy after MAX Mini App activation"
done

telegram_html="$(curl -fsS --retry 5 --retry-delay 2 --retry-all-errors --max-time 20 \
  "https://app.happy-fox.online/mini-app/?revision=$EXPECTED_SHA")"
max_html="$(curl -fsS --retry 5 --retry-delay 2 --retry-all-errors --max-time 20 \
  "$MAX_MINIAPP_ORIGIN/mini-app/?revision=$EXPECTED_SHA")"

grep -Fq '/mini-app/telegram-web-app.js' <<<"$telegram_html" || die "Telegram host has no Telegram SDK"
if grep -Fq 'https://st.max.ru/js/max-web-app.js' <<<"$telegram_html"; then
  die "Telegram host still loads MAX Bridge"
fi
grep -Fq 'https://st.max.ru/js/max-web-app.js' <<<"$max_html" || die "MAX host has no MAX Bridge"
if grep -Fq '/mini-app/telegram-web-app.js' <<<"$max_html"; then
  die "MAX host still loads Telegram SDK"
fi

max_revision="$(curl -fsS --retry 5 --retry-delay 2 --retry-all-errors --max-time 20 \
  "$MAX_MINIAPP_ORIGIN/mini-app/revision.txt?revision=$EXPECTED_SHA")"
[[ "$max_revision" == "$EXPECTED_SHA" ]] || die "MAX Mini App live revision mismatch"

max_bootstrap_status="$(curl -sS -o /dev/null -w '%{http_code}' -X POST --max-time 20 \
  -H 'Content-Type: application/json' -d '{}' "$MAX_MINIAPP_ORIGIN/mini-app/api/bootstrap" || true)"
[[ "$max_bootstrap_status" =~ ^(400|401|403)$ ]] || die "MAX Mini App bootstrap ingress failed: $max_bootstrap_status"

max_launch_location="$(curl -sSI --max-time 20 https://api.happy-fox.online/max/webhook \
  | awk 'BEGIN{IGNORECASE=1} /^location:/ {gsub(/\r/, ""); print $2; exit}')"
[[ "$max_launch_location" == "$MAX_MINIAPP_ORIGIN/mini-app/" ]] \
  || die "MAX launch redirect mismatch: $max_launch_location"

log "ACTIVE telegram=https://app.happy-fox.online/mini-app/ max=$MAX_MINIAPP_ORIGIN/mini-app/ revision=$EXPECTED_SHA"
