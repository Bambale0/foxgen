#!/usr/bin/env bash
# HappyFox Telegram egress tunnel: canonical host-side NAT and firewall rules.
#
# HappyFox reaches the Telegram Bot API through an SSH tunnel owned by
# happyfox-telegram-egress.service. The tunnel stays alive even when the host
# firewall stops forwarding the tunnel port, so Bot API calls silently time out
# with TelegramNetworkError while the SSH listener still looks healthy.
#
# This script is the single owner of the required rule set, including the
# filter/INPUT ACCEPT for the DNAT'ed tunnel port. The INPUT policy on the
# HappyFox host is DROP, so the tunnel port must be accepted explicitly for
# every container subnet that reaches Telegram through the tunnel.
#
# Usage: happyfox-telegram-egress-nat {up|down|status}
#
# All operational values are overridable, so nothing needs a source edit:
#   HAPPYFOX_TELEGRAM_EGRESS_RANGE              (default 149.154.160.0/20)
#   HAPPYFOX_TELEGRAM_EGRESS_PORT               (default 18443)
#   HAPPYFOX_TELEGRAM_EGRESS_GATEWAY            (default 172.18.0.1)
#   HAPPYFOX_TELEGRAM_EGRESS_CONTAINER_SUBNETS  (default 172.18.0.0/16)
set -Eeuo pipefail

TELEGRAM_RANGE="${HAPPYFOX_TELEGRAM_EGRESS_RANGE:-149.154.160.0/20}"
TUNNEL_PORT="${HAPPYFOX_TELEGRAM_EGRESS_PORT:-18443}"
TUNNEL_GATEWAY="${HAPPYFOX_TELEGRAM_EGRESS_GATEWAY:-172.18.0.1}"
CONTAINER_SUBNETS="${HAPPYFOX_TELEGRAM_EGRESS_CONTAINER_SUBNETS:-172.18.0.0/16}"
IPTABLES="${HAPPYFOX_TELEGRAM_EGRESS_IPTABLES:-iptables}"

LOG_PREFIX="telegram_egress_nat"
MISSING=0

log() {
  echo "$LOG_PREFIX $*"
}

require_root() {
  # HAPPYFOX_TELEGRAM_EGRESS_SKIP_ROOT_CHECK is a test seam for the automated
  # suite, which exercises this script against a stub iptables. Production never
  # sets it, and the real iptables binary still requires privileges.
  if [[ "${HAPPYFOX_TELEGRAM_EGRESS_SKIP_ROOT_CHECK:-0}" == "1" ]]; then
    return 0
  fi
  if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    log "stage=${1:-preflight} outcome=error reason=root_required"
    exit 2
  fi
}

require_iptables() {
  if ! command -v "$IPTABLES" >/dev/null 2>&1; then
    log "stage=${1:-preflight} outcome=error reason=iptables_missing binary=$IPTABLES"
    exit 2
  fi
}

filter_rule() {
  # INPUT accept for the DNAT'ed tunnel port of one container subnet.
  printf '%s\n' -s "$1" -p tcp --dport "$TUNNEL_PORT" -j ACCEPT
}

dnat_rule() {
  printf '%s\n' -s "$1" -p tcp -d "$TELEGRAM_RANGE" --dport 443 \
    -j DNAT --to-destination "$TUNNEL_GATEWAY:$TUNNEL_PORT"
}

redirect_rule() {
  printf '%s\n' -p tcp -d "$TELEGRAM_RANGE" --dport 443 \
    -j REDIRECT --to-ports "$TUNNEL_PORT"
}

rule_args_from_text() {
  # Reads a newline separated rule description and prints its arguments.
  local text="$1"
  # shellcheck disable=SC2086 # intentional word splitting of the rule text
  set -- $text
  printf '%s\n' "$@"
}

ensure_rule() {
  local chain="$1"
  local table="$2"
  shift 2
  local args=("$@")

  if [[ "$table" == "filter" ]]; then
    if "$IPTABLES" -w 5 -C "$chain" "${args[@]}" 2>/dev/null; then
      log "stage=ensure rule=$chain outcome=present"
      return 0
    fi
    "$IPTABLES" -w 5 -I "$chain" 1 "${args[@]}"
  else
    if "$IPTABLES" -w 5 -t "$table" -C "$chain" "${args[@]}" 2>/dev/null; then
      log "stage=ensure rule=${table}/${chain} outcome=present"
      return 0
    fi
    "$IPTABLES" -w 5 -t "$table" -I "$chain" 1 "${args[@]}"
  fi
  log "stage=ensure rule=${table}/${chain} outcome=installed"
}

remove_rule() {
  local chain="$1"
  local table="$2"
  shift 2
  local args=("$@")
  local removed=0

  # Remove every duplicate; a previous partial run may have inserted several.
  while true; do
    if [[ "$table" == "filter" ]]; then
      "$IPTABLES" -w 5 -C "$chain" "${args[@]}" 2>/dev/null || break
      "$IPTABLES" -w 5 -D "$chain" "${args[@]}"
    else
      "$IPTABLES" -w 5 -t "$table" -C "$chain" "${args[@]}" 2>/dev/null || break
      "$IPTABLES" -w 5 -t "$table" -D "$chain" "${args[@]}"
    fi
    removed=$((removed + 1))
  done
  log "stage=remove rule=${table}/${chain} outcome=done removed=$removed"
}

assert_rule() {
  local chain="$1"
  local table="$2"
  shift 2
  local args=("$@")

  if [[ "$table" == "filter" ]]; then
    if "$IPTABLES" -w 5 -C "$chain" "${args[@]}" 2>/dev/null; then
      log "stage=status rule=$chain outcome=present"
      return 0
    fi
  else
    if "$IPTABLES" -w 5 -t "$table" -C "$chain" "${args[@]}" 2>/dev/null; then
      log "stage=status rule=${table}/${chain} outcome=present"
      return 0
    fi
  fi
  log "stage=status rule=${table}/${chain} outcome=missing"
  MISSING=$((MISSING + 1))
  return 1
}



for_each_container_subnet() {
  local action="$1"
  local subnet rule
  for subnet in $CONTAINER_SUBNETS; do
    rule="$(filter_rule "$subnet")"
    mapfile -t args < <(rule_args_from_text "$rule")
    "$action" INPUT filter "${args[@]}"
  done
}

action_up() {
  local subnet rule args=()

  for_each_container_subnet ensure_rule

  for subnet in $CONTAINER_SUBNETS; do
    rule="$(dnat_rule "$subnet")"
    mapfile -t args < <(rule_args_from_text "$rule")
    ensure_rule PREROUTING nat "${args[@]}"
  done

  rule="$(redirect_rule)"
  mapfile -t args < <(rule_args_from_text "$rule")
  ensure_rule OUTPUT nat "${args[@]}"

  log "stage=up outcome=success range=$TELEGRAM_RANGE port=$TUNNEL_PORT gateway=$TUNNEL_GATEWAY subnets=$CONTAINER_SUBNETS"
}

action_down() {
  local subnet rule args=()

  for_each_container_subnet remove_rule

  for subnet in $CONTAINER_SUBNETS; do
    rule="$(dnat_rule "$subnet")"
    mapfile -t args < <(rule_args_from_text "$rule")
    remove_rule PREROUTING nat "${args[@]}"
  done

  rule="$(redirect_rule)"
  mapfile -t args < <(rule_args_from_text "$rule")
  remove_rule OUTPUT nat "${args[@]}"

  log "stage=down outcome=success range=$TELEGRAM_RANGE port=$TUNNEL_PORT gateway=$TUNNEL_GATEWAY subnets=$CONTAINER_SUBNETS"
}

action_status() {
  local subnet rule args=()

  for_each_container_subnet assert_rule || true

  for subnet in $CONTAINER_SUBNETS; do
    rule="$(dnat_rule "$subnet")"
    mapfile -t args < <(rule_args_from_text "$rule")
    assert_rule PREROUTING nat "${args[@]}" || true
  done

  rule="$(redirect_rule)"
  mapfile -t args < <(rule_args_from_text "$rule")
  assert_rule OUTPUT nat "${args[@]}" || true

  if [[ "$MISSING" -ne 0 ]]; then
    log "stage=status outcome=incomplete missing=$MISSING"
    return 1
  fi
  log "stage=status outcome=ok rules=complete"
}

case "${1:-up}" in
  up)
    require_root up
    require_iptables up
    action_up
    ;;
  down)
    require_root down
    require_iptables down
    action_down
    ;;
  status)
    require_root status
    require_iptables status
    action_status
    ;;
  *)
    echo "usage: $(basename "$0") {up|down|status}" >&2
    exit 2
    ;;
esac
