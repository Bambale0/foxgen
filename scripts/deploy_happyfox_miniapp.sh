#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 027

: "${MINIAPP_FRONTEND_DOMAIN:?MINIAPP_FRONTEND_DOMAIN is required for HappyFox}"
EXPECTED_SHA="${1:-$(git rev-parse HEAD)}"
BACKEND_CONTAINER="${HAPPYFOX_BACKEND_CONTAINER:-foxgen-happyfox-bot}"
BUNDLED_ROOT="/app/frontend/miniapp-v0/out"
PROFILE_FILE="/etc/foxgen-happyfox/profiles/${MINIAPP_FRONTEND_DOMAIN}.env"
WEB_ROOT="/var/www/${MINIAPP_FRONTEND_DOMAIN}"
MINIAPP_ROOT="${WEB_ROOT}/mini-app"

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

if [[ -f "$PROFILE_FILE" ]]; then
  # The profile may override filesystem layout only. The public domain remains
  # pinned above so stale/source-product hosts cannot survive a cutover.
  # shellcheck disable=SC1090
  source "$PROFILE_FILE"
  WEB_ROOT="${WEB_ROOT:-/var/www/${MINIAPP_FRONTEND_DOMAIN}}"
  MINIAPP_ROOT="${MINIAPP_ROOT:-${WEB_ROOT}/mini-app}"
fi

command -v docker >/dev/null || {
  echo "docker is required to publish the bundled HappyFox Mini App" >&2
  exit 1
}

docker inspect "$BACKEND_CONTAINER" >/dev/null 2>&1 || {
  echo "HappyFox backend container is unavailable: $BACKEND_CONTAINER" >&2
  exit 1
}

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

# nginx serves the Mini App from the host web root while API calls are proxied
# to the backend. Publish the exact static export bundled in the already-healthy
# backend image so frontend and API can never drift to different commits.
install -d -m 0755 "$MINIAPP_ROOT"
cp -a "$bundle_dir/." "$MINIAPP_ROOT/"
chown -R root:root "$MINIAPP_ROOT"
find "$MINIAPP_ROOT" -type d -exec chmod 0755 {} +
find "$MINIAPP_ROOT" -type f -exec chmod 0644 {} +

echo "[happyfox-miniapp] published exact bundled release: ${EXPECTED_SHA}"

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
