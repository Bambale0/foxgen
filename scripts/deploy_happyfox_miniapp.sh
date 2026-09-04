#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 027

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${MINIAPP_FRONTEND_DOMAIN:?MINIAPP_FRONTEND_DOMAIN is required for HappyFox}"
EXPECTED_SHA="${1:-$(git rev-parse HEAD)}"
BACKEND_CONTAINER="${HAPPYFOX_BACKEND_CONTAINER:-foxgen-happyfox-bot}"
NGINX_CONTAINER="${HAPPYFOX_REVERSE_PROXY_CONTAINER:-artflow-nginx-1}"
BUNDLED_ROOT="/app/frontend/miniapp-v0/out"

case "${MINIAPP_FRONTEND_DOMAIN,,}" in
  *tanyapi.chillcreative.ru*|*cdn.chillcreative.ru*|*media.chillcreative.ru*|*tanyapp*|*neuromix*|*only_tany*)
    echo "Refusing to publish HappyFox Mini App on a NEUROMIX/Tanya domain: ${MINIAPP_FRONTEND_DOMAIN}" >&2
    exit 1
    ;;
esac

[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || {
  echo "Expected a full 40-character deployment SHA" >&2
  exit 1
}

command -v docker >/dev/null || {
  echo "docker is required to publish the bundled HappyFox Mini App" >&2
  exit 1
}
for container in "$BACKEND_CONTAINER" "$NGINX_CONTAINER"; do
  docker inspect "$container" >/dev/null 2>&1 || {
    echo "Required HappyFox container is unavailable: $container" >&2
    exit 1
  }
done

work="$(mktemp -d)"
cleanup() { rm -rf "$work"; }
trap cleanup EXIT
bundle_dir="$work/bundle"
mkdir -p "$bundle_dir"

docker cp "${BACKEND_CONTAINER}:${BUNDLED_ROOT}/." "$bundle_dir/"

[[ -s "$bundle_dir/index.html" ]] || {
  echo "HappyFox bundled Mini App is missing index.html" >&2
  exit 1
}
[[ -d "$bundle_dir/_next/static" ]] || {
  echo "HappyFox bundled Mini App is missing Next.js static assets" >&2
  exit 1
}
[[ -s "$bundle_dir/revision.txt" ]] || {
  echo "HappyFox bundled Mini App is missing revision.txt" >&2
  exit 1
}

bundled_revision="$(tr -d '\r\n' < "$bundle_dir/revision.txt")"
[[ "$bundled_revision" == "$EXPECTED_SHA" ]] || {
  echo "HappyFox container bundle revision mismatch: expected=$EXPECTED_SHA actual=$bundled_revision" >&2
  exit 1
}

# Read the effective public nginx topology. HappyFox supports both historical
# direct filesystem serving and the current nginx -> static-sidecar proxy.
if ! docker exec "$NGINX_CONTAINER" nginx -T > "$work/nginx.conf" 2> "$work/nginx-check.log"; then
  echo "Could not read effective nginx configuration" >&2
  exit 1
fi

publish_via_reverse_proxy_filesystem() {
  local miniapp_root="$1"
  [[ "$miniapp_root" == /* && "$miniapp_root" != "/" ]] || {
    echo "Resolved nginx Mini App path is unsafe: $miniapp_root" >&2
    return 1
  }

  # Copy through the reverse-proxy container namespace. If the path is backed
  # by a writable bind mount or volume, this writes to the exact live target.
  docker exec "$NGINX_CONTAINER" mkdir -p "$miniapp_root"
  docker cp "$bundle_dir/." "${NGINX_CONTAINER}:${miniapp_root}/"

  local published_revision
  published_revision="$(
    docker exec "$NGINX_CONTAINER" cat "${miniapp_root}/revision.txt" \
      | tr -d '\r\n'
  )"
  [[ "$published_revision" == "$EXPECTED_SHA" ]] || {
    echo "HappyFox nginx static revision mismatch after publish: expected=$EXPECTED_SHA actual=$published_revision" >&2
    return 1
  }

  echo "[happyfox-miniapp] NGINX_STATIC_RELEASE_OK revision=${EXPECTED_SHA}"
}

resolve_static_bind_source() {
  local static_container="$1"
  docker inspect "$static_container" | python3 -c '
import json
import sys
from pathlib import Path

data = json.load(sys.stdin)
if len(data) != 1:
    raise SystemExit("expected exactly one static container inspection result")

matches = []
for mount in data[0].get("Mounts", []):
    if mount.get("Type") != "bind":
        continue
    destination = str(mount.get("Destination") or "").rstrip("/")
    source = str(mount.get("Source") or "").strip()
    if not destination.endswith("/mini-app"):
        continue
    if not source or not Path(source).is_absolute():
        continue
    matches.append(source)

if len(matches) != 1:
    raise SystemExit(
        f"expected exactly one bind mount ending in /mini-app, found {len(matches)}"
    )
print(matches[0])
'
}

publish_via_static_proxy() {
  local static_container="${HAPPYFOX_MINIAPP_STATIC_CONTAINER:-}"
  if [ -z "$static_container" ]; then
    static_container="$(
      python3 "$SCRIPT_DIR/resolve_happyfox_miniapp_nginx_path.py" \
        "$work/nginx.conf" "$MINIAPP_FRONTEND_DOMAIN" --proxy-container
    )"
  fi

  docker inspect "$static_container" >/dev/null 2>&1 || {
    echo "Resolved HappyFox Mini App static proxy container is unavailable: $static_container" >&2
    return 1
  }

  local static_root="${HAPPYFOX_MINIAPP_STATIC_ROOT:-}"
  if [ -z "$static_root" ]; then
    static_root="$(resolve_static_bind_source "$static_container")"
  fi
  [[ "$static_root" == /* && "$static_root" != "/" ]] || {
    echo "Resolved HappyFox static bind source is unsafe: $static_root" >&2
    return 1
  }

  # The sidecar may intentionally mount its static tree read-only. Deployment
  # runs on the host as root, so publish through the bind source rather than
  # mutating Docker internals or weakening the container mount to rw.
  install -d -m 0755 "$static_root"
  cp -a "$bundle_dir/." "$static_root/"

  local published_revision
  published_revision="$(tr -d '\r\n' < "$static_root/revision.txt")"
  [[ "$published_revision" == "$EXPECTED_SHA" ]] || {
    echo "HappyFox static-sidecar revision mismatch after publish: expected=$EXPECTED_SHA actual=$published_revision" >&2
    return 1
  }

  echo "[happyfox-miniapp] STATIC_PROXY_RELEASE_OK container=${static_container} revision=${EXPECTED_SHA}"
}

# Prefer the direct filesystem route when present. If the public nginx vhost
# proxies /mini-app/ to a static sidecar (production topology), resolve that
# exact proxy target and its bind mount instead of guessing a host web-root.
if MINIAPP_ROOT="$(
  python3 "$SCRIPT_DIR/resolve_happyfox_miniapp_nginx_path.py" \
    "$work/nginx.conf" "$MINIAPP_FRONTEND_DOMAIN" 2> "$work/path-resolve.log"
)"; then
  publish_via_reverse_proxy_filesystem "$MINIAPP_ROOT"
else
  echo "[happyfox-miniapp] Direct nginx filesystem path unavailable; resolving static proxy target"
  publish_via_static_proxy
fi

BASE_URL="https://${MINIAPP_FRONTEND_DOMAIN}/mini-app"
MOBILE_SAFARI_UA='Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Safari/604.1'

revision="$(
  curl -fsS --retry 8 --retry-delay 2 --retry-all-errors \
    --max-time 20 \
    -H 'Cache-Control: no-cache' \
    "${BASE_URL}/revision.txt?revision=${EXPECTED_SHA}"
)"
[[ "$revision" == "$EXPECTED_SHA" ]] || {
  echo "HappyFox bundled Mini App revision mismatch: expected=$EXPECTED_SHA actual=$revision" >&2
  exit 1
}

curl -fsS --retry 8 --retry-delay 2 --retry-all-errors \
  --max-time 20 \
  -A "$MOBILE_SAFARI_UA" \
  -H 'Cache-Control: no-cache' \
  "${BASE_URL}/?revision=${EXPECTED_SHA}" > "$work/index.html"

grep -q '/mini-app/_next/static/' "$work/index.html" || {
  echo "HappyFox Mini App HTML has no Next.js static assets" >&2
  exit 1
}

if grep -qi 'NEUROMIX' "$work/index.html"; then
  echo "Refusing stale NEUROMIX Mini App HTML" >&2
  exit 1
fi

asset="$(grep -oE '/mini-app/_next/static/[^" ]+\.js' "$work/index.html" | head -n1 || true)"
[[ -n "$asset" ]] || {
  echo "HappyFox Mini App HTML did not expose a JavaScript asset" >&2
  exit 1
}

curl -fsSI --retry 5 --retry-delay 2 --retry-all-errors \
  --max-time 20 \
  -A "$MOBILE_SAFARI_UA" \
  "https://${MINIAPP_FRONTEND_DOMAIN}${asset}?revision=${EXPECTED_SHA}" >/dev/null

# If this release contains the public landing, validate the exact assets and
# Telegram launch link that previously regressed in production.
if [[ -s "$bundle_dir/landing/index.html" && -s "$bundle_dir/happyfox-logo.svg" ]]; then
  curl -fsS --retry 5 --retry-delay 2 --retry-all-errors \
    --max-time 20 \
    -A "$MOBILE_SAFARI_UA" \
    "${BASE_URL}/landing/?revision=${EXPECTED_SHA}" > "$work/landing.html"
  grep -Fq '/mini-app/happyfox-logo.svg' "$work/landing.html" || {
    echo "HappyFox landing does not reference the valid SVG logo" >&2
    exit 1
  }
  grep -Eq 'https://t\.me/[A-Za-z0-9_]+\?startapp' "$work/landing.html" || {
    echo "HappyFox landing has no Telegram Main Mini App launch link" >&2
    exit 1
  }
  curl -fsSI --retry 5 --retry-delay 2 --retry-all-errors \
    --max-time 20 \
    "${BASE_URL}/happyfox-logo.svg?revision=${EXPECTED_SHA}" >/dev/null
  echo "[happyfox-miniapp] LANDING_OK ${BASE_URL}/landing/ revision=${EXPECTED_SHA}"
fi

# A malformed bootstrap request must reach aiohttp and fail closed. 405 means
# nginx/static routing swallowed the POST, which makes the Mini App appear dead
# (and is especially visible in Telegram's iOS WebView).
bootstrap_status="$(
  curl -sS -o "$work/bootstrap.json" -w '%{http_code}' \
    --max-time 20 \
    -A "$MOBILE_SAFARI_UA" \
    -H 'Content-Type: application/json' \
    -X POST "${BASE_URL}/api/bootstrap" \
    --data '{}' || true
)"
case "$bootstrap_status" in
  400|401|403)
    ;;
  *)
    echo "HappyFox Mini App bootstrap ingress failed: expected 400/401/403, got ${bootstrap_status:-transport-error}" >&2
    exit 1
    ;;
esac

echo "[happyfox-miniapp] MOBILE_SAFARI_OK ${BASE_URL}/ revision=${EXPECTED_SHA} bootstrap=${bootstrap_status}"
