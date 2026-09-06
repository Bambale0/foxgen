#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 027

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
EXPECTED_SHA="${1:-$(git -C "$PROJECT_DIR" rev-parse HEAD)}"
API_ORIGIN="${HAPPYFOX_API_ORIGIN:-https://api.happy-fox.online}"
APP_ORIGIN="${HAPPYFOX_APP_ORIGIN:-https://app.happy-fox.online}"
LANDING_ORIGIN="${HAPPYFOX_LANDING_ORIGIN:-https://happy-fox.online}"
DATABASE_NAME="${HAPPYFOX_DATABASE_NAME:-happyfox_cutover}"
TELEGRAM_RELAY_IP="${HAPPYFOX_TELEGRAM_RELAY_IP:-2.27.160.11}"
GITHUB_REPO="${HAPPYFOX_GITHUB_REPO:-Bambale0/foxgen}"
RUNTIME_ENV="$PROJECT_DIR/.env.happyfox.runtime"

[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || {
  echo "Expected a full 40-character deployment SHA" >&2
  exit 1
}
[[ "$DATABASE_NAME" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || {
  echo "HAPPYFOX_DATABASE_NAME must be a simple SQL identifier" >&2
  exit 1
}

cd "$PROJECT_DIR"
[[ -s .env && -s "$RUNTIME_ENV" ]] || {
  echo "HappyFox production env files are missing" >&2
  exit 1
}
command -v gh >/dev/null 2>&1 || {
  echo "GitHub CLI (gh) is required on the HappyFox production host" >&2
  exit 1
}
gh auth status -h github.com >/dev/null 2>&1 || {
  echo "GitHub CLI is not authenticated on the HappyFox production host" >&2
  exit 1
}
main_sha="$(gh api "repos/${GITHUB_REPO}/commits/main" --jq .sha)"
[[ "$main_sha" == "$EXPECTED_SHA" ]] || {
  echo "Requested SHA is no longer the current ${GITHUB_REPO} main" >&2
  exit 1
}
[[ "$(git rev-parse HEAD)" == "$EXPECTED_SHA" ]] || {
  echo "Checkout SHA does not match requested deployment SHA" >&2
  exit 1
}

# Recover protected channel values from the server-side channel overlay before
# canonicalizing public URLs. GitHub Actions never replaces this runtime file:
# the production host is authoritative for secrets and channel credentials.
python3 scripts/recover_happyfox_channel_runtime.py "$PROJECT_DIR"

# Dedicated-host topology is intentionally split: all backend/webhook/media
# traffic uses api.happy-fox.online, while the Telegram/MAX UI lives on the app
# origin. The production DB name and durable provider-result persistence are
# server-authoritative so an old CI secret cannot regress production behavior.
python3 - "$RUNTIME_ENV" "$API_ORIGIN" "$APP_ORIGIN" "$DATABASE_NAME" "$TELEGRAM_RELAY_IP" <<'PY'
from pathlib import Path
import ipaddress
import os
import sys
from urllib.parse import urlsplit, urlunsplit

path = Path(sys.argv[1])
api = sys.argv[2].rstrip("/")
app = sys.argv[3].rstrip("/")
database_name = sys.argv[4]
telegram_relay_ip = sys.argv[5].strip()
values: dict[str, str] = {}
for raw in path.read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
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
values["PERSIST_PROVIDER_RESULTS"] = "1"
values["TELEGRAM_WEBHOOK_URL"] = f"{api}/webhook"
if not telegram_relay_ip:
    raise SystemExit("HAPPYFOX_TELEGRAM_RELAY_IP must not be empty")
try:
    ipaddress.ip_address(telegram_relay_ip)
except ValueError as exc:
    raise SystemExit("HAPPYFOX_TELEGRAM_RELAY_IP must be a valid IP address") from exc
values["TELEGRAM_WEBHOOK_IP_ADDRESS"] = telegram_relay_ip

database_url = values.get("DATABASE_URL", "").strip()
if database_url:
    parsed = urlsplit(database_url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise SystemExit("HappyFox dedicated runtime requires PostgreSQL DATABASE_URL")
    values["DATABASE_URL"] = urlunsplit(
        (parsed.scheme, parsed.netloc, f"/{database_name}", parsed.query, parsed.fragment)
    )

if values.get("MAX_ENABLED", "").lower() in {"1", "true", "yes", "on"}:
    max_path = values.get("MAX_WEBHOOK_PATH", "/max/webhook") or "/max/webhook"
    if not max_path.startswith("/"):
        raise SystemExit("MAX_WEBHOOK_PATH must start with /")
    values["MAX_WEBHOOK_URL"] = f"{api}{max_path}"
    values["MAX_MINI_APP_URL"] = f"{app}/mini-app/"
    if not values.get("MAX_PAYMENT_RETURN_URL", "").startswith("https://max.ru/"):
        values["MAX_PAYMENT_RETURN_URL"] = f"{app}/mini-app/"


def quote(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"

out = [
    "# HappyFox dedicated-host runtime overlay",
    "# Secret values are preserved; public origins and DB target are canonicalized on deploy.",
]
out.extend(f"{key}={quote(values[key])}" for key in sorted(values))
tmp = path.with_suffix(path.suffix + ".tmp")
tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
os.chmod(tmp, 0o600)
tmp.replace(path)
PY

python3 scripts/validate_happyfox_env.py .env .env.happyfox.runtime .env.postgres

# Writable bind mounts belong to the non-root runtime UID from the Dockerfile.
for path in data static/uploads logs backups outputs; do
  install -d -m 0755 "$path"
  chown -R 10001:10001 "$path"
done

docker compose -f compose.infra.yml up -d
for i in $(seq 1 60); do
  if docker exec foxgen-postgres-1 sh -lc 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1 \
     && docker exec foxgen-redis-1 sh -lc 'REDISCLI_AUTH="$FOXGEN_REDIS_PASSWORD" redis-cli ping' 2>/dev/null | grep -qx PONG; then
    break
  fi
  sleep 2
  [[ "$i" -lt 60 ]] || { echo "HappyFox data plane did not become ready" >&2; exit 1; }
done

# A verified rollback point is mandatory before replacing a healthy runtime.
if docker inspect foxgen-happyfox-bot >/dev/null 2>&1; then
  current_state="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' foxgen-happyfox-bot 2>/dev/null || true)"
  if [[ "$current_state" == "healthy" ]]; then
    docker exec -e SEND_BACKUP_TO_ADMINS=0 foxgen-happyfox-bot \
      bash /app/scripts/backup_db.sh
  fi
fi

docker build \
  --build-arg "VCS_REF=$EXPECTED_SHA" \
  --build-arg "BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  -t foxgen-happyfox-bot:local .

image_revision="$(docker inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' foxgen-happyfox-bot:local)"
[[ "$image_revision" == "$EXPECTED_SHA" ]]

COMPOSE_PROJECT_NAME=foxgen-happyfox \
  HAPPYFOX_IMAGE=foxgen-happyfox-bot:local \
  docker compose -f compose.backend.yml up -d --no-build bot

for i in $(seq 1 60); do
  health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' foxgen-happyfox-bot 2>/dev/null || true)"
  [[ "$health" == "healthy" ]] && break
  if [[ "$health" == "unhealthy" || "$health" == "exited" ]]; then
    docker logs --tail 150 foxgen-happyfox-bot >&2 || true
    exit 1
  fi
  sleep 2
  [[ "$i" -lt 60 ]] || { docker logs --tail 150 foxgen-happyfox-bot >&2 || true; exit 1; }
done

runtime_revision="$(docker inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' foxgen-happyfox-bot)"
[[ "$runtime_revision" == "$EXPECTED_SHA" ]]

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

bootstrap_status="$(curl -sS -o /dev/null -w '%{http_code}' -X POST --max-time 20 \
  -H 'Content-Type: application/json' -d '{}' "$APP_ORIGIN/mini-app/api/bootstrap" || true)"
[[ "$bootstrap_status" =~ ^(400|401|403)$ ]]

max_status="$(curl -sS -o /dev/null -w '%{http_code}' -X POST --max-time 20 \
  -H 'Content-Type: application/json' -d '{}' "$API_ORIGIN/max/webhook" || true)"
[[ "$max_status" == "401" ]]

yookassa_status="$(curl -sS -o /dev/null -w '%{http_code}' -X POST --max-time 20 \
  -H 'Content-Type: application/json' -d '{}' "$API_ORIGIN/yookassa/webhook" || true)"
[[ "$yookassa_status" == "200" ]]

kie_status="$(curl -sS -o /dev/null -w '%{http_code}' -X POST --max-time 20 \
  -H 'Content-Type: application/json' -d '{}' "$API_ORIGIN/webhook/kie_ai" || true)"
[[ "$kie_status" =~ ^(400|401|403)$ ]]

# Telegram and MAX webhook configuration is part of the release, not a manual
# afterthought. MAX refreshes its subscription during startup; Telegram is
# explicitly reconciled here without dropping queued updates.
docker exec foxgen-happyfox-bot python /app/scripts/ensure_telegram_webhook.py
docker logs foxgen-happyfox-bot 2>&1 | grep -F "$API_ORIGIN/max/webhook" >/dev/null

# Keep the post-migration state backed up with the matching PG17 client.
docker exec -e SEND_BACKUP_TO_ADMINS=0 foxgen-happyfox-bot \
  bash /app/scripts/backup_db.sh

echo "[happyfox-dedicated] DEPLOY_OK revision=$EXPECTED_SHA api=$API_ORIGIN app=$APP_ORIGIN landing=$LANDING_ORIGIN db=$DATABASE_NAME"
