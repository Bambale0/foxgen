#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 027

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
EXPECTED_SHA="${1:-$(git -C "$PROJECT_DIR" rev-parse HEAD)}"
API_ORIGIN="${HAPPYFOX_API_ORIGIN:-https://api.happy-fox.online}"
APP_ORIGIN="${HAPPYFOX_APP_ORIGIN:-https://app.happy-fox.online}"
LANDING_ORIGIN="${HAPPYFOX_LANDING_ORIGIN:-https://happy-fox.online}"
RUNTIME_ENV="$PROJECT_DIR/.env.happyfox.runtime"

[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || {
  echo "Expected a full 40-character deployment SHA" >&2
  exit 1
}
cd "$PROJECT_DIR"
[[ "$(git rev-parse HEAD)" == "$EXPECTED_SHA" ]] || {
  echo "Checkout SHA does not match requested deployment SHA" >&2
  exit 1
}
[[ -s .env && -s "$RUNTIME_ENV" ]] || {
  echo "HappyFox production env files are missing" >&2
  exit 1
}

# Dedicated-host topology is intentionally split: all backend/webhook/media
# traffic uses api.happy-fox.online, while the Telegram/MAX UI lives on the app
# origin. Keep these non-secret public values server-authoritative so an older
# CI secret cannot silently restore the legacy single-domain topology.
python3 - "$RUNTIME_ENV" "$API_ORIGIN" "$APP_ORIGIN" <<'PY'
from pathlib import Path
import os
import sys

path = Path(sys.argv[1])
api = sys.argv[2].rstrip("/")
app = sys.argv[3].rstrip("/")
values: dict[str, str] = {}
comments: list[str] = []
for raw in path.read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        if raw:
            comments.append(raw)
        continue
    key, value = line.split("=", 1)
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    values[key.strip()] = value

values["WEBHOOK_HOST"] = api
values["STATIC_BASE_URL"] = api
values["MINI_APP_URL"] = f"{app}/mini-app/"
values["YOOKASSA_RETURN_URL"] = f"{app}/mini-app/"
if values.get("MAX_ENABLED", "").lower() in {"1", "true", "yes", "on"}:
    max_path = values.get("MAX_WEBHOOK_PATH", "/max/webhook") or "/max/webhook"
    values["MAX_WEBHOOK_URL"] = f"{api}{max_path}"
    values["MAX_MINI_APP_URL"] = f"{app}/mini-app/"
    # MAX returns to its bot deep link when explicitly configured; otherwise
    # use the app origin rather than a legacy hostname.
    if not values.get("MAX_PAYMENT_RETURN_URL", "").startswith("https://max.ru/"):
        values["MAX_PAYMENT_RETURN_URL"] = f"{app}/mini-app/"

def quote(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"

out = [
    "# HappyFox dedicated-host runtime overlay",
    "# Secret values are preserved; public origins are canonicalized on deploy.",
]
out.extend(f"{key}={quote(values[key])}" for key in sorted(values))
tmp = path.with_suffix(path.suffix + ".tmp")
tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
os.chmod(tmp, 0o600)
tmp.replace(path)
PY

python3 scripts/validate_happyfox_env.py .env .env.happyfox.runtime .env.postgres

docker compose -f compose.infra.yml up -d
for i in $(seq 1 60); do
  if docker exec foxgen-postgres-1 sh -lc 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1 \
     && docker exec foxgen-redis-1 sh -lc 'REDISCLI_AUTH="$FOXGEN_REDIS_PASSWORD" redis-cli ping' 2>/dev/null | grep -qx PONG; then
    break
  fi
  sleep 2
  [[ "$i" -lt 60 ]] || { echo "HappyFox data plane did not become ready" >&2; exit 1; }
done

docker build \
  --build-arg "VCS_REF=$EXPECTED_SHA" \
  --build-arg "BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  -t foxgen-happyfox-bot:local .

image_revision="$(docker inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' foxgen-happyfox-bot:local)"
[[ "$image_revision" == "$EXPECTED_SHA" ]]

COMPOSE_PROJECT_NAME=foxgen-happyfox \
  docker compose -f compose.backend.yml up -d --no-build bot

for i in $(seq 1 60); do
  health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' foxgen-happyfox-bot 2>/dev/null || true)"
  [[ "$health" == "healthy" ]] && break
  sleep 2
  [[ "$i" -lt 60 ]] || { docker logs --tail 150 foxgen-happyfox-bot >&2 || true; exit 1; }
done

# Publish the exact static bundle embedded in the verified backend image.
for webroot in /var/www/happyfox-app /var/www/happyfox-landing; do
  install -d -m 0755 "$webroot/mini-app"
  find "$webroot/mini-app" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
done
cid="$(docker create foxgen-happyfox-bot:local)"
trap 'docker rm -f "$cid" >/dev/null 2>&1 || true' EXIT
docker cp "$cid:/app/frontend/miniapp-v0/out/." /var/www/happyfox-app/mini-app/
docker cp "$cid:/app/frontend/miniapp-v0/out/." /var/www/happyfox-landing/mini-app/
docker rm "$cid" >/dev/null
trap - EXIT
find /var/www/happyfox-app /var/www/happyfox-landing -type d -exec chmod 0755 {} +
find /var/www/happyfox-app /var/www/happyfox-landing -type f -exec chmod 0644 {} +

[[ "$(tr -d '\r\n' </var/www/happyfox-app/mini-app/revision.txt)" == "$EXPECTED_SHA" ]]
nginx -t
systemctl reload nginx

curl -fsS --retry 8 --retry-delay 2 --retry-all-errors --max-time 20 "$API_ORIGIN/health" >/dev/null
live_revision="$(curl -fsS --retry 8 --retry-delay 2 --retry-all-errors --max-time 20 "$APP_ORIGIN/mini-app/revision.txt?revision=$EXPECTED_SHA")"
[[ "$live_revision" == "$EXPECTED_SHA" ]]
curl -fsS --retry 5 --retry-delay 2 --retry-all-errors --max-time 20 "$LANDING_ORIGIN/" | grep -Fq 'https://t.me/'

echo "[happyfox-dedicated] DEPLOY_OK revision=$EXPECTED_SHA api=$API_ORIGIN app=$APP_ORIGIN landing=$LANDING_ORIGIN"
