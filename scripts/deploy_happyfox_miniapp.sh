#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

: "${MINIAPP_FRONTEND_DOMAIN:?MINIAPP_FRONTEND_DOMAIN is required for HappyFox}"
EXPECTED_SHA="${1:-$(git rev-parse HEAD)}"

case "${MINIAPP_FRONTEND_DOMAIN,,}" in
  *tanyapi.chillcreative.ru*|*cdn.chillcreative.ru*|*media.chillcreative.ru*|*tanyapp*|*neuromix*|*only_tany*)
    echo "Refusing to verify HappyFox Mini App on a NEUROMIX/Tanya domain: ${MINIAPP_FRONTEND_DOMAIN}" >&2
    exit 1
    ;;
esac

[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || {
  echo "Expected a full 40-character deployment SHA" >&2
  exit 1
}

BASE_URL="https://${MINIAPP_FRONTEND_DOMAIN}/mini-app"
work="$(mktemp -d)"
cleanup() { rm -rf "$work"; }
trap cleanup EXIT

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
  "https://${MINIAPP_FRONTEND_DOMAIN}${asset}?revision=${EXPECTED_SHA}" >/dev/null

echo "[happyfox-miniapp] bundled release verified: ${EXPECTED_SHA}"
