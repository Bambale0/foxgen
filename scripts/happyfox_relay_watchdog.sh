#!/usr/bin/env bash
set -Eeuo pipefail

SNI="${HAPPYFOX_RELAY_SNI:-api.happy-fox.online}"
INGRESS_IP="${HAPPYFOX_RELAY_INGRESS_IP:-2.27.160.11}"
NGINX_CONTAINER="${HAPPYFOX_RELAY_NGINX_CONTAINER:-artflow-nginx-1}"

probe() {
  curl -sS --max-time 10 \
    --resolve "$SNI:443:$INGRESS_IP" \
    -o /dev/null -w '%{http_code}' \
    -X POST "https://$SNI/webhook" \
    -H 'Content-Type: application/json' \
    --data '{}' || true
}

status="$(probe)"
if [[ "$status" == "401" ]]; then
  echo "happyfox_relay_watchdog outcome=healthy status=$status"
  exit 0
fi

echo "happyfox_relay_watchdog outcome=reload_needed status=$status"
docker exec "$NGINX_CONTAINER" nginx -t
docker exec "$NGINX_CONTAINER" nginx -s reload
sleep 1

status="$(probe)"
if [[ "$status" == "401" ]]; then
  echo "happyfox_relay_watchdog outcome=recovered status=$status"
  exit 0
fi

echo "happyfox_relay_watchdog outcome=failed status=$status" >&2
exit 1
