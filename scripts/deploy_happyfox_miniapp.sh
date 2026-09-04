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

# Read the effective reverse-proxy config and follow the actual serving target.
# HappyFox production may serve /mini-app/ from an nginx alias/root OR proxy it
# to a dedicated static container (currently banano-miniapp). Publishing to a
# guessed host path leaves Telegram/iOS on an old frontend while backend moves on.
if ! docker exec "$NGINX_CONTAINER" nginx -T > "$work/nginx.conf" 2> "$work/nginx-check.log"; then
  echo "Could not read effective nginx configuration" >&2
  exit 1
fi

target="$(
  python3 "$SCRIPT_DIR/resolve_happyfox_miniapp_nginx_target.py" \
    "$work/nginx.conf" "$MINIAPP_FRONTEND_DOMAIN"
)"
IFS=$'\t' read -r target_kind target_value <<< "$target"

case "$target_kind" in
  filesystem)
    MINIAPP_ROOT="$target_value"
    [[ "$MINIAPP_ROOT" == /* ]] || {
      echo "Resolved nginx Mini App path is not absolute" >&2
      exit 1
    }

    docker exec "$NGINX_CONTAINER" mkdir -p "$MINIAPP_ROOT"
    docker cp "$bundle_dir/." "${NGINX_CONTAINER}:${MINIAPP_ROOT}/"

    published_revision="$(
      docker exec "$NGINX_CONTAINER" cat "${MINIAPP_ROOT}/revision.txt" \
        | tr -d '\r\n'
    )"
    [[ "$published_revision" == "$EXPECTED_SHA" ]] || {
      echo "HappyFox nginx static revision mismatch after publish: expected=$EXPECTED_SHA actual=$published_revision" >&2
      exit 1
    }
    echo "[happyfox-miniapp] NGINX_STATIC_RELEASE_OK revision=${EXPECTED_SHA}"
    ;;

  proxy)
    FRONTEND_CONTAINER="${HAPPYFOX_MINIAPP_CONTAINER:-$target_value}"
    docker inspect "$FRONTEND_CONTAINER" >/dev/null 2>&1 || {
      echo "Resolved HappyFox Mini App proxy container is unavailable: $FRONTEND_CONTAINER" >&2
      exit 1
    }

    mapfile -t frontend_roots < <(
      docker inspect -f '{{range .Mounts}}{{println .Destination}}{{end}}' "$FRONTEND_CONTAINER" \
        | grep -E '/mini-app/?$' || true
    )
    [[ "${#frontend_roots[@]}" -eq 1 ]] || {
      echo "Expected exactly one /mini-app mount in $FRONTEND_CONTAINER, found ${#frontend_roots[@]}" >&2
      exit 1
    }
    MINIAPP_ROOT="${frontend_roots[0]%/}"

    docker cp "$bundle_dir/." "${FRONTEND_CONTAINER}:${MINIAPP_ROOT}/"
    published_revision="$(
      docker exec "$FRONTEND_CONTAINER" cat "${MINIAPP_ROOT}/revision.txt" \
        | tr -d '\r\n'
    )"
    [[ "$published_revision" == "$EXPECTED_SHA" ]] || {
      echo "HappyFox frontend proxy revision mismatch after publish: expected=$EXPECTED_SHA actual=$published_revision" >&2
      exit 1
    }
    echo "[happyfox-miniapp] FRONTEND_PROXY_RELEASE_OK container=${FRONTEND_CONTAINER} root=${MINIAPP_ROOT} revision=${EXPECTED_SHA}"
    ;;

  *)
    echo "Unsupported HappyFox Mini App target kind: ${target_kind:-empty}" >&2
    exit 1
    ;;
esac

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
