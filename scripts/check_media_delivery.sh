#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage: check_media_delivery.sh <https-media-url>

Checks DNS, IPv4/IPv6 reachability, HTTP/2 response headers and Cloudflare
cache status. Run it once from a normal connection and again through each
problematic VPN location.
EOF
}

if [[ $# -ne 1 ]]; then
  usage >&2
  exit 2
fi

URL="$1"
if [[ ! "$URL" =~ ^https:// ]]; then
  echo "ERROR: URL must use https://" >&2
  exit 2
fi

HOST="$(python3 - "$URL" <<'PY'
import sys
from urllib.parse import urlparse
host = urlparse(sys.argv[1]).hostname
if not host:
    raise SystemExit(2)
print(host)
PY
)"

header_value() {
  local name="$1"
  awk -v key="$name" 'BEGIN { IGNORECASE=1 }
    index($0, key ":") == 1 {
      sub(/^[^:]+:[[:space:]]*/, "")
      sub(/\r$/, "")
      value=$0
    }
    END { print value }
  '
}

print_headers() {
  local headers="$1"
  local status cache age ray type length control server alt location
  status="$(printf '%s\n' "$headers" | awk '/^HTTP\// { value=$0 } END { sub(/\r$/, "", value); print value }')"
  cache="$(printf '%s\n' "$headers" | header_value 'cf-cache-status')"
  age="$(printf '%s\n' "$headers" | header_value 'age')"
  ray="$(printf '%s\n' "$headers" | header_value 'cf-ray')"
  type="$(printf '%s\n' "$headers" | header_value 'content-type')"
  length="$(printf '%s\n' "$headers" | header_value 'content-length')"
  control="$(printf '%s\n' "$headers" | header_value 'cache-control')"
  server="$(printf '%s\n' "$headers" | header_value 'server')"
  alt="$(printf '%s\n' "$headers" | header_value 'alt-svc')"
  location="$(printf '%s\n' "$headers" | header_value 'location')"

  printf 'status=%s\n' "${status:-missing}"
  printf 'server=%s\n' "${server:-missing}"
  printf 'cf-cache-status=%s\n' "${cache:-missing}"
  printf 'age=%s\n' "${age:-missing}"
  printf 'cf-ray=%s\n' "${ray:-missing}"
  printf 'content-type=%s\n' "${type:-missing}"
  printf 'content-length=%s\n' "${length:-missing}"
  printf 'cache-control=%s\n' "${control:-missing}"
  printf 'alt-svc=%s\n' "${alt:-missing}"
  if [[ -n "$location" ]]; then
    printf 'location=%s\n' "$location"
  fi
}

measure() {
  local family="$1"
  local label="$2"
  echo
  echo "== $label =="
  if ! curl "$family" --http2 --connect-timeout 8 --max-time 30 \
      --output /dev/null --silent --show-error \
      --write-out 'http=%{http_code} remote=%{remote_ip} dns=%{time_namelookup}s connect=%{time_connect}s tls=%{time_appconnect}s ttfb=%{time_starttransfer}s total=%{time_total}s speed=%{speed_download}B/s\n' \
      "$URL"; then
    echo "$label request failed"
  fi
}

echo "URL:  $URL"
echo "Host: $HOST"

echo
echo "== DNS A =="
if command -v dig >/dev/null 2>&1; then
  dig +short A "$HOST" || true
else
  getent ahostsv4 "$HOST" | awk '{print $1}' | sort -u || true
fi

echo
echo "== DNS AAAA =="
if command -v dig >/dev/null 2>&1; then
  dig +short AAAA "$HOST" || true
else
  getent ahostsv6 "$HOST" | awk '{print $1}' | sort -u || true
fi

echo
echo "== HTTP/2 headers, request 1 (cold/unknown edge state) =="
HEADERS_1="$(curl --http2 --connect-timeout 8 --max-time 30 --silent --show-error --dump-header - --output /dev/null "$URL")"
print_headers "$HEADERS_1"

echo
echo "== HTTP/2 headers, request 2 (same edge cache check) =="
HEADERS_2="$(curl --http2 --connect-timeout 8 --max-time 30 --silent --show-error --dump-header - --output /dev/null "$URL")"
print_headers "$HEADERS_2"

measure -4 "IPv4"

if command -v dig >/dev/null 2>&1; then
  HAS_AAAA="$(dig +short AAAA "$HOST" | head -n1 || true)"
else
  HAS_AAAA="$(getent ahostsv6 "$HOST" | head -n1 || true)"
fi

if [[ -n "$HAS_AAAA" ]]; then
  measure -6 "IPv6"
else
  echo
  echo "== IPv6 =="
  echo "No AAAA record; IPv6 request skipped"
fi

echo
echo "== Verdict hints =="
CACHE_2="$(printf '%s\n' "$HEADERS_2" | header_value 'cf-cache-status')"
AGE_2="$(printf '%s\n' "$HEADERS_2" | header_value 'age')"
ALT_2="$(printf '%s\n' "$HEADERS_2" | header_value 'alt-svc')"
SERVER_2="$(printf '%s\n' "$HEADERS_2" | header_value 'server')"

if [[ "${SERVER_2,,}" != *cloudflare* ]]; then
  echo "WARN: response does not identify Cloudflare; verify orange-cloud proxy and DNS."
fi

case "${CACHE_2^^}" in
  HIT)
    echo "OK: second request is a Cloudflare cache HIT (Age=${AGE_2:-missing})."
    ;;
  MISS)
    echo "WARN: second request is still MISS; verify Cache Rule, immutable URL and origin headers."
    ;;
  BYPASS|DYNAMIC)
    echo "WARN: cache status is ${CACHE_2}; inspect cookies, auth and Cache-Control."
    ;;
  *)
    echo "WARN: CF-Cache-Status is missing or unexpected: ${CACHE_2:-missing}."
    ;;
esac

if [[ "${ALT_2,,}" == *h3* ]]; then
  echo "INFO: response advertises HTTP/3 in Alt-Svc. During VPN diagnosis disable HTTP/3 in Cloudflare and repeat."
else
  echo "OK/INFO: HTTP/3 is not advertised in the checked response."
fi
