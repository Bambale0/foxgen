#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 027

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
EXPECTED_SHA="${1:-$(git -C "$PROJECT_DIR" rev-parse HEAD)}"
CONFIG_FILE="${HAPPYFOX_MAX_MINIAPP_CONFIG:-/etc/foxgen-happyfox/max-miniapp.env}"
APP_ROOT="/var/www/happyfox-app/mini-app"
MAX_MINIAPP_ROOT="/var/www/happyfox-max/mini-app"
RUNTIME_ENV="${HAPPYFOX_RUNTIME_ENV:-$PROJECT_DIR/.env.happyfox.runtime}"
NGINX_SITE="${HAPPYFOX_NGINX_SITE:-/etc/nginx/sites-available/happyfox.conf}"
IMAGE="${HAPPYFOX_IMAGE:-foxgen-happyfox-bot:local}"
SHARED_ORIGIN="https://app.happy-fox.online"
DEDICATED_MAX_ORIGIN="https://max.happy-fox.online"

log() { printf '[happyfox-miniapp-split] %s\n' "$*"; }
die() { printf '[happyfox-miniapp-split] ERROR: %s\n' "$*" >&2; exit 1; }

[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || die "expected a full 40-character SHA"

restore_shared_redirect() {
  [[ -s "$NGINX_SITE" ]] || return 0
  python3 - "$NGINX_SITE" "$SHARED_ORIGIN" "$DEDICATED_MAX_ORIGIN" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
shared = sys.argv[2].rstrip("/")
dedicated = sys.argv[3].rstrip("/")
text = path.read_text(encoding="utf-8")
old = f"return 302 {dedicated}/mini-app/;"
new = f"return 302 {shared}/mini-app/;"
if old in text:
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
PY
  nginx -t
  systemctl reload nginx
}

if [[ ! -s "$CONFIG_FILE" ]]; then
  restore_shared_redirect
  log "split config is absent; shared Mini App launch mode is active"
  exit 0
fi

MAX_MINIAPP_ORIGIN="$(python3 - "$CONFIG_FILE" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
values: list[str] = []
for raw in path.read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#"):
        continue
    if "=" not in line:
        raise SystemExit(f"invalid activation config line: {line!r}")
    key, value = line.split("=", 1)
    if key.strip() != "MAX_MINIAPP_ORIGIN":
        raise SystemExit(f"unsupported activation config key: {key.strip()!r}")
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    values.append(value)
if len(values) != 1 or not values[0]:
    raise SystemExit("activation config must contain exactly one MAX_MINIAPP_ORIGIN")
print(values[0].rstrip("/"))
PY
)"

python3 - "$MAX_MINIAPP_ORIGIN" <<'PY'
import sys
from urllib.parse import urlsplit
value = sys.argv[1]
parsed = urlsplit(value)
if (
    parsed.scheme != "https"
    or parsed.hostname != "max.happy-fox.online"
    or parsed.port not in {None, 443}
    or parsed.username
    or parsed.password
    or parsed.query
    or parsed.fragment
    or parsed.path not in {"", "/"}
):
    raise SystemExit("MAX_MINIAPP_ORIGIN must be https://max.happy-fox.online")
PY

[[ -s "$RUNTIME_ENV" ]] || die "HappyFox runtime env is missing: $RUNTIME_ENV"
[[ -s "$NGINX_SITE" ]] || die "HappyFox nginx site is missing: $NGINX_SITE"
docker inspect "$IMAGE" >/dev/null 2>&1 || die "verified HappyFox image is missing: $IMAGE"
image_revision="$(docker inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$IMAGE")"
[[ "$image_revision" == "$EXPECTED_SHA" ]] || die "image revision mismatch: $image_revision"

work="$(mktemp -d)"
cid=""
cleanup() {
  [[ -z "$cid" ]] || docker rm -f "$cid" >/dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT
mkdir -p "$work/generic"
cid="$(docker create "$IMAGE")"
docker cp "$cid:/app/frontend/miniapp-v0/out/." "$work/generic/"
docker rm "$cid" >/dev/null
cid=""
[[ -s "$work/generic/index.html" ]] || die "verified image has no Mini App index.html"
[[ "$(tr -d '\r\n' < "$work/generic/revision.txt")" == "$EXPECTED_SHA" ]] \
  || die "verified image Mini App revision mismatch"

for target in "$APP_ROOT" "$MAX_MINIAPP_ROOT"; do
  install -d -m 0755 "$target"
  find "$target" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
  cp -a "$work/generic/." "$target/"
done

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

path = Path(sys.argv[1])
origin = sys.argv[2].rstrip("/")
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
  HAPPYFOX_IMAGE="$IMAGE" \
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
