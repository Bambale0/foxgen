#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

: "${MINIAPP_FRONTEND_DOMAIN:?MINIAPP_FRONTEND_DOMAIN is required for HappyFox}"

case "${MINIAPP_FRONTEND_DOMAIN,,}" in
  *tanyapp*|*chillcreative.ru*|*neuromix*)
    echo "Refusing to deploy HappyFox Mini App to a NEUROMIX/Tanya domain: ${MINIAPP_FRONTEND_DOMAIN}" >&2
    exit 1
    ;;
esac

export PRODUCT_ID=happyfox
export NEXT_PUBLIC_PRODUCT_ID=happyfox

exec bash "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/deploy_miniapp_local.sh" "$@"
