#!/usr/bin/env bash
# Interactive manager for standalone Banano Mini App frontend/CDN hosts.
# Architecture: frontend Nginx -> HTTPS backend domain:443 -> backend Nginx -> localhost aiohttp.

set -Eeuo pipefail
IFS=$'\n\t'
umask 027

APP_NAME="banano-miniapp"
STATE_DIR="${CDN_STATE_DIR:-/etc/${APP_NAME}}"
PROFILES_DIR="${STATE_DIR}/profiles"
REMOTES_DIR="${STATE_DIR}/remotes"
ACTIVE_FILE="${STATE_DIR}/active-domain"
DEFAULT_SOURCE_DIR="/opt/banano-kling-src"
DEFAULT_REPO_URL="https://github.com/Bambale0/banano_kling.git"
DEFAULT_BRANCH="tanyapi"
LOG_FILE="/var/log/${APP_NAME}-cdn.log"

C_RESET='\033[0m'
C_RED='\033[0;31m'
C_GREEN='\033[0;32m'
C_YELLOW='\033[1;33m'
C_CYAN='\033[0;36m'

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG_FILE"
}

info() { printf '%b%s%b\n' "$C_CYAN" "$*" "$C_RESET"; }
success() { printf '%b%s%b\n' "$C_GREEN" "$*" "$C_RESET"; }
warn() { printf '%b%s%b\n' "$C_YELLOW" "$*" "$C_RESET" >&2; }
die() { printf '%bERROR: %s%b\n' "$C_RED" "$*" "$C_RESET" >&2; exit 1; }

on_error() {
  local code=$?
  local line=${1:-unknown}
  warn "Ошибка на строке ${line}, код ${code}. Лог: ${LOG_FILE}"
  exit "$code"
}
trap 'on_error $LINENO' ERR

require_root() {
  [[ "$EUID" -eq 0 ]] || die "Запусти через sudo: sudo bash cdn.sh"
}

install_bootstrap_tools() {
  local missing=0
  for command in git curl python3 ssh; do
    command -v "$command" >/dev/null 2>&1 || missing=1
  done
  [[ "$missing" == "0" ]] && return 0

  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends \
    git curl ca-certificates python3 openssh-client
}

prepare_state() {
  install -d -m 0700 "$STATE_DIR" "$PROFILES_DIR" "$REMOTES_DIR"
  install -d -m 0755 "$(dirname "$LOG_FILE")"
  touch "$LOG_FILE"
  chmod 0640 "$LOG_FILE"
}

pause() {
  read -r -p "Нажми Enter, чтобы продолжить..." _ || true
}

ask() {
  local prompt="$1"
  local default="${2:-}"
  local answer
  if [[ -n "$default" ]]; then
    read -r -p "${prompt} [${default}]: " answer || true
    printf '%s' "${answer:-$default}"
  else
    read -r -p "${prompt}: " answer || true
    printf '%s' "$answer"
  fi
}

confirm() {
  local prompt="$1"
  local default="${2:-n}"
  local suffix='[y/N]'
  [[ "$default" == "y" ]] && suffix='[Y/n]'
  local answer
  read -r -p "${prompt} ${suffix}: " answer || true
  answer="${answer:-$default}"
  [[ "$answer" =~ ^[YyДд]$ ]]
}

validate_domain() {
  local domain="$1"
  [[ "$domain" =~ ^([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$ ]]
}

normalize_domain() {
  local value="$1"
  value="${value#http://}"
  value="${value#https://}"
  value="${value%%/*}"
  value="${value%:443}"
  printf '%s' "${value,,}"
}

profile_path() {
  printf '%s/%s.env' "$PROFILES_DIR" "$1"
}

list_domains() {
  find "$PROFILES_DIR" -maxdepth 1 -type f -name '*.env' -printf '%f\n' 2>/dev/null \
    | sed 's/\.env$//' \
    | sort
}

active_domain() {
  [[ -f "$ACTIVE_FILE" ]] && tr -d '[:space:]' < "$ACTIVE_FILE" || true
}

select_domain() {
  local title="${1:-Выбери домен}"
  mapfile -t domains < <(list_domains)
  (( ${#domains[@]} > 0 )) || return 1

  echo "$title" >&2
  local i
  for i in "${!domains[@]}"; do
    local marker=' '
    [[ "${domains[$i]}" == "$(active_domain)" ]] && marker='*'
    printf '  %d) %s %s\n' "$((i + 1))" "$marker" "${domains[$i]}" >&2
  done

  local choice
  read -r -p "Номер: " choice || true
  [[ "$choice" =~ ^[0-9]+$ ]] || return 1
  (( choice >= 1 && choice <= ${#domains[@]} )) || return 1
  printf '%s' "${domains[$((choice - 1))]}"
}

source_profile() {
  local domain="$1"
  local file
  file="$(profile_path "$domain")"
  [[ -f "$file" ]] || die "Профиль не найден: $file"
  # shellcheck disable=SC1090
  source "$file"
}

write_env_value() {
  local file="$1" key="$2" value="$3"
  python3 - "$file" "$key" "$value" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
key = sys.argv[2]
import shlex
value = shlex.quote(sys.argv[3])
lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
out = []
found = False
for line in lines:
    stripped = line.strip()
    if stripped and not stripped.startswith("#") and "=" in line:
        current = line.split("=", 1)[0].strip()
        if current == key:
            out.append(f"{key}={value}")
            found = True
            continue
    out.append(line)
if not found:
    out.append(f"{key}={value}")
path.write_text("\n".join(out) + "\n", encoding="utf-8")
PY
  chmod 0600 "$file"
}

bootstrap_source() {
  local repo_url="$1" branch="$2" source_dir="$3"
  install_bootstrap_tools

  if [[ ! -d "$source_dir/.git" ]]; then
    log "Клонирую ${repo_url}, ветка ${branch}, в ${source_dir}"
    rm -rf "$source_dir"
    git clone --branch "$branch" --single-branch "$repo_url" "$source_dir"
    return
  fi

  if [[ -n "$(git -C "$source_dir" status --porcelain)" ]]; then
    die "В ${source_dir} есть локальные изменения. Убери их перед автоматическим обновлением."
  fi

  log "Обновляю служебный checkout ${source_dir}"
  git -C "$source_dir" fetch --prune origin "$branch"
  git -C "$source_dir" switch "$branch"
  git -C "$source_dir" reset --hard "origin/${branch}"
}

secure_installer_path() {
  local source_dir="$1"
  printf '%s/scripts/install_miniapp_frontend_https_host.sh' "$source_dir"
}

run_installer() {
  local domain="$1" mode="$2"
  source_profile "$domain"

  bootstrap_source "$REPO_URL" "$REPO_BRANCH" "$SOURCE_DIR"
  local installer
  installer="$(secure_installer_path "$SOURCE_DIR")"
  [[ -f "$installer" ]] || die "Не найден защищённый инсталлятор: $installer"

  log "Запускаю ${mode} для ${domain}"
  bash "$installer" --config "$(profile_path "$domain")" "$mode"
}

ask_backend_ssh() {
  local default_host="${1:-}"
  BACKEND_SSH_HOST=""
  BACKEND_PROJECT_DIR="/root/tanya/banano_kling"
  BACKEND_ENV_FILE="/root/tanya/banano_kling/.env"
  BACKEND_SERVICE="banano-kling.service"

  if confirm "Автоматически менять MINI_APP_URL на backend по SSH?" "n"; then
    BACKEND_SSH_HOST="$(ask 'SSH backend, например root@1.2.3.4' "$default_host")"
    [[ -n "$BACKEND_SSH_HOST" ]] || die "SSH backend не указан"
    BACKEND_PROJECT_DIR="$(ask 'Каталог проекта backend' "$BACKEND_PROJECT_DIR")"
    BACKEND_ENV_FILE="$(ask 'Путь к .env backend' "${BACKEND_PROJECT_DIR}/.env")"
    BACKEND_SERVICE="$(ask 'systemd service backend' "$BACKEND_SERVICE")"

    info "Проверяю SSH-ключ..."
    ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new \
      "$BACKEND_SSH_HOST" 'echo SSH_OK' | grep -q SSH_OK \
      || die "SSH по ключу не работает. Сначала настрой ssh-copy-id или deploy key."
  fi
}

CREATED_DOMAIN=""

create_profile_interactive() {
  local purpose="${1:-new}"
  local suggested_domain="${2:-}"

  local frontend_domain backend_domain certbot_email repo_url branch source_dir
  local web_root backup_root run_audit

  while true; do
    frontend_domain="$(normalize_domain "$(ask 'Публичный домен frontend' "$suggested_domain")")"
    validate_domain "$frontend_domain" && break
    warn "Некорректный домен"
  done

  local existing
  existing="$(profile_path "$frontend_domain")"
  if [[ -f "$existing" ]] && ! confirm "Профиль ${frontend_domain} уже существует. Перезаписать настройки?" "n"; then
    die "Отменено"
  fi

  while true; do
    backend_domain="$(normalize_domain "$(ask 'HTTPS-домен backend Nginx' 'tanyapi.chillcreative.ru')")"
    validate_domain "$backend_domain" && break
    warn "Нужен домен backend, не IP и не порт 1888"
  done

  certbot_email="$(ask 'Email для Let’s Encrypt')"
  [[ "$certbot_email" == *@*.* ]] || die "Некорректный email"

  repo_url="$(ask 'Git-репозиторий frontend' "$DEFAULT_REPO_URL")"
  branch="$(ask 'Ветка frontend' "$DEFAULT_BRANCH")"
  source_dir="$(ask 'Служебный checkout' "$DEFAULT_SOURCE_DIR")"
  web_root="$(ask 'Корень статики' "/var/www/${frontend_domain}")"
  backup_root="$(ask 'Каталог резервных копий' "/var/backups/banano-miniapp/${frontend_domain}")"

  run_audit=1
  confirm "Запускать npm audit перед каждой выкладкой?" "y" || run_audit=0

  if [[ "$purpose" == "mirror" ]]; then
    BACKEND_SSH_HOST=""
    BACKEND_PROJECT_DIR="/root/tanya/banano_kling"
    BACKEND_ENV_FILE="/root/tanya/banano_kling/.env"
    BACKEND_SERVICE="banano-kling.service"
    info "Для зеркала MINI_APP_URL backend не переключается."
  else
    ask_backend_ssh
  fi

  {
    printf '# Managed by cdn.sh. Mode: %s\n' "$purpose"
    printf 'FRONTEND_DOMAIN=%q\n' "$frontend_domain"
    printf 'BACKEND_ORIGIN=%q\n' "https://${backend_domain}"
    printf 'BACKEND_HOST_HEADER=%q\n' "$backend_domain"
    printf 'BACKEND_TLS_NAME=%q\n' "$backend_domain"
    printf 'BACKEND_HEALTH_PATH=%q\n' "/health"
    printf 'CERTBOT_EMAIL=%q\n\n' "$certbot_email"

    printf 'REPO_URL=%q\n' "$repo_url"
    printf 'REPO_BRANCH=%q\n' "$branch"
    printf 'SOURCE_DIR=%q\n' "$source_dir"
    printf 'RUN_NPM_AUDIT=%q\n' "$run_audit"
    printf 'FORCE_RESET_SOURCE=0\n'
    printf 'NODE_MAJOR=22\n\n'

    printf 'WEB_ROOT=%q\n' "$web_root"
    printf 'MINIAPP_ROOT=%q\n' "${web_root}/mini-app"
    printf 'BACKUP_ROOT=%q\n' "$backup_root"
    printf 'KEEP_BACKUPS=7\n\n'

    printf 'CLIENT_MAX_BODY_SIZE=60M\n'
    printf 'PROXY_TIMEOUT_SECONDS=600\n'
    printf 'ENABLE_UFW=1\n'
    printf 'SKIP_TLS=0\n'
    printf 'SKIP_DNS_CHECK=0\n\n'

    printf 'BACKEND_SSH_HOST=%q\n' "$BACKEND_SSH_HOST"
    printf 'BACKEND_PROJECT_DIR=%q\n' "$BACKEND_PROJECT_DIR"
    printf 'BACKEND_ENV_FILE=%q\n' "$BACKEND_ENV_FILE"
    printf 'BACKEND_SERVICE=%q\n' "$BACKEND_SERVICE"
    printf 'CONFIGURE_BACKEND_UFW=0\n'
  } > "$existing"
  chmod 0600 "$existing"

  CREATED_DOMAIN="$frontend_domain"
}

show_dns_instruction() {
  local domain="$1"
  local ip
  ip="$(curl -4 -fsS --max-time 10 https://api.ipify.org 2>/dev/null || true)"
  echo
  info "Перед запуском A-запись должна указывать:"
  printf '  %s -> %s\n' "$domain" "${ip:-IP этого сервера}"
  echo
}

install_new_domain() {
  local purpose="${1:-new}"
  local domain
  create_profile_interactive "$purpose"
  domain="$CREATED_DOMAIN"
  show_dns_instruction "$domain"
  confirm "DNS уже переключён и можно начинать установку?" "n" || {
    warn "Профиль сохранён: $(profile_path "$domain")"
    return 0
  }

  run_installer "$domain" --install
  printf '%s\n' "$domain" > "$ACTIVE_FILE"
  chmod 0600 "$ACTIVE_FILE"
  success "Готово: https://${domain}/mini-app/"
}

update_domain() {
  local domain
  domain="$(select_domain 'Какой frontend обновить?')" || die "Домен не выбран"
  run_installer "$domain" --deploy-only
  success "Frontend ${domain} обновлён"
}

add_mirror() {
  info "Зеркало получает собственный домен и SSL, но не переключает основной MINI_APP_URL."
  local domain
  create_profile_interactive mirror
  domain="$CREATED_DOMAIN"
  write_env_value "$(profile_path "$domain")" BACKEND_SSH_HOST ""
  show_dns_instruction "$domain"
  confirm "DNS зеркала уже готов?" "n" || return 0
  run_installer "$domain" --install
  success "Зеркало готово: https://${domain}/mini-app/"
}

move_domain() {
  local old_domain=""
  if mapfile -t _domains < <(list_domains); (( ${#_domains[@]} > 0 )); then
    old_domain="$(select_domain 'С какого домена переезжаем?')" || die "Старый домен не выбран"
  fi

  info "Старый домен не удаляется: он остаётся как безопасный откат."
  local new_domain
  create_profile_interactive move
  new_domain="$CREATED_DOMAIN"
  show_dns_instruction "$new_domain"
  confirm "DNS нового домена уже готов?" "n" || return 0

  run_installer "$new_domain" --install
  printf '%s\n' "$new_domain" > "$ACTIVE_FILE"
  chmod 0600 "$ACTIVE_FILE"

  success "Переезд завершён: ${old_domain:-старый домен} -> ${new_domain}"
  warn "Старый frontend оставлен включённым. Удаляй его только после проверки Telegram и платежей."
}

set_backend_miniapp_url() {
  local domain="$1"
  source_profile "$domain"
  [[ -n "${BACKEND_SSH_HOST:-}" ]] || die "В профиле нет BACKEND_SSH_HOST"

  local url="https://${domain}/mini-app/"
  log "Переключаю MINI_APP_URL backend на ${url}"
  ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new "$BACKEND_SSH_HOST" \
    "BACKEND_ENV_FILE=$(printf '%q' "$BACKEND_ENV_FILE") BACKEND_SERVICE=$(printf '%q' "$BACKEND_SERVICE") MINIAPP_URL=$(printf '%q' "$url") bash -s" <<'REMOTE'
set -Eeuo pipefail
[[ -f "$BACKEND_ENV_FILE" ]]
cp -a "$BACKEND_ENV_FILE" "${BACKEND_ENV_FILE}.before-cdn-switch-$(date '+%Y%m%d-%H%M%S')"
python3 - "$BACKEND_ENV_FILE" "$MINIAPP_URL" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
value = sys.argv[2]
lines = path.read_text(encoding='utf-8').splitlines()
out = []
found = False
for line in lines:
    if line.strip() and not line.lstrip().startswith('#') and '=' in line:
        if line.split('=', 1)[0].strip() == 'MINI_APP_URL':
            out.append(f'MINI_APP_URL={value}')
            found = True
            continue
    out.append(line)
if not found:
    out.append(f'MINI_APP_URL={value}')
path.write_text('\n'.join(out) + '\n', encoding='utf-8')
PY
systemctl restart "$BACKEND_SERVICE"
systemctl is-active --quiet "$BACKEND_SERVICE"
REMOTE

  printf '%s\n' "$domain" > "$ACTIVE_FILE"
  chmod 0600 "$ACTIVE_FILE"
  success "Активный Mini App переключён на ${url}"
}

switch_active_domain() {
  local domain
  domain="$(select_domain 'Какой домен сделать основным в боте?')" || die "Домен не выбран"
  set_backend_miniapp_url "$domain"
}

show_status() {
  mapfile -t domains < <(list_domains)
  if (( ${#domains[@]} == 0 )); then
    warn "Профилей пока нет"
    return
  fi

  local active
  active="$(active_domain)"
  printf '\n%-32s %-9s %-10s %-10s %s\n' 'ДОМЕН' 'АКТИВНЫЙ' 'HTML' 'NGINX' 'СЕРТИФИКАТ'
  printf '%s\n' '--------------------------------------------------------------------------------'

  local domain
  for domain in "${domains[@]}"; do
    source_profile "$domain"
    local html='нет' nginx_state='нет' cert='нет'
    curl -fsSI --max-time 8 "https://${domain}/mini-app/" >/dev/null 2>&1 && html='ok'
    [[ -e "/etc/nginx/sites-enabled/banano-miniapp-${domain//./-}" ]] && nginx_state='ok'
    if [[ -f "/etc/letsencrypt/live/${domain}/fullchain.pem" ]]; then
      cert="$(openssl x509 -enddate -noout -in "/etc/letsencrypt/live/${domain}/fullchain.pem" 2>/dev/null | cut -d= -f2 || echo ok)"
    fi
    local marker='нет'
    [[ "$domain" == "$active" ]] && marker='да'
    printf '%-32s %-9s %-10s %-10s %s\n' "$domain" "$marker" "$html" "$nginx_state" "$cert"
  done
  echo
}

rollback_domain() {
  local domain
  domain="$(select_domain 'Для какого домена сделать откат?')" || die "Домен не выбран"
  source_profile "$domain"

  mapfile -t backups < <(find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' 2>/dev/null \
    | sort -nr | awk '{print $2}')
  (( ${#backups[@]} > 0 )) || die "Резервных копий нет в ${BACKUP_ROOT}"

  echo "Выбери резервную копию:"
  local i
  for i in "${!backups[@]}"; do
    printf '  %d) %s\n' "$((i + 1))" "$(basename "${backups[$i]}")"
  done
  local choice
  read -r -p "Номер: " choice || true
  [[ "$choice" =~ ^[0-9]+$ ]] || die "Некорректный номер"
  (( choice >= 1 && choice <= ${#backups[@]} )) || die "Некорректный номер"

  local selected="${backups[$((choice - 1))]}"
  confirm "Восстановить ${domain} из $(basename "$selected")?" "n" || return 0
  rsync -a --delete "${selected}/" "${MINIAPP_ROOT}/"
  nginx -t
  systemctl reload nginx
  curl -fsSI --max-time 15 "https://${domain}/mini-app/" >/dev/null
  success "Откат ${domain} выполнен"
}

edit_profile() {
  local domain
  domain="$(select_domain 'Какой профиль изменить?')" || die "Домен не выбран"
  local file
  file="$(profile_path "$domain")"
  local editor="${EDITOR:-}"
  if [[ -z "$editor" ]]; then
    if command -v nano >/dev/null 2>&1; then
      editor="nano"
    else
      editor="vi"
    fi
  fi
  "$editor" "$file"
  chmod 0600 "$file"
  success "Профиль сохранён. Для применения запусти обновление frontend."
}

remote_profile_path() {
  printf '%s/%s.env' "$REMOTES_DIR" "$1"
}

normalize_remote_name() {
  local value="${1,,}"
  value="${value// /-}"
  value="$(printf '%s' "$value" | tr -cd 'a-z0-9._-')"
  printf '%s' "$value"
}

list_remote_names() {
  find "$REMOTES_DIR" -maxdepth 1 -type f -name '*.env' -printf '%f\n' 2>/dev/null \
    | sed 's/\.env$//' \
    | sort
}

select_remote() {
  local title="${1:-Выбери удалённый frontend}"
  mapfile -t remotes < <(list_remote_names)
  (( ${#remotes[@]} > 0 )) || return 1

  echo "$title" >&2
  local i
  for i in "${!remotes[@]}"; do
    printf '  %d) %s\n' "$((i + 1))" "${remotes[$i]}" >&2
  done

  local choice
  read -r -p "Номер: " choice || true
  [[ "$choice" =~ ^[0-9]+$ ]] || return 1
  (( choice >= 1 && choice <= ${#remotes[@]} )) || return 1
  printf '%s' "${remotes[$((choice - 1))]}"
}

source_remote_profile() {
  local name="$1"
  local file
  file="$(remote_profile_path "$name")"
  [[ -f "$file" ]] || die "Удалённый профиль не найден: $file"
  # shellcheck disable=SC1090
  source "$file"
}

remote_ssh() {
  local target="$1"
  shift
  ssh \
    -o BatchMode=yes \
    -o ConnectTimeout=15 \
    -o ServerAliveInterval=15 \
    -o ServerAliveCountMax=3 \
    -o StrictHostKeyChecking=accept-new \
    "$target" "$@"
}

configure_remote_frontend() {
  local name ssh_host source_dir domain branch use_sudo file

  name="$(normalize_remote_name "$(ask 'Имя удалённого frontend' 'tanyafrontend')")"
  [[ -n "$name" ]] || die "Имя профиля пустое"
  ssh_host="$(ask 'SSH frontend-сервера' 'root@91.200.84.187')"
  [[ -n "$ssh_host" ]] || die "SSH frontend-сервера не указан"
  source_dir="$(ask 'Каталог репозитория на frontend-сервере' "$DEFAULT_SOURCE_DIR")"

  while true; do
    domain="$(normalize_domain "$(ask 'Домен frontend' 'cdn.chillcreative.ru')")"
    validate_domain "$domain" && break
    warn "Некорректный домен"
  done

  branch="$(ask 'Ветка для выкладки' "$DEFAULT_BRANCH")"
  use_sudo=0
  confirm "SSH-пользователю нужен sudo без пароля?" "n" && use_sudo=1

  info "Проверяю SSH и сохранённый профиль домена..."
  remote_ssh "$ssh_host" \
    "SOURCE_DIR=$(printf '%q' "$source_dir") DOMAIN=$(printf '%q' "$domain") bash -s" <<'REMOTE'
set -Eeuo pipefail
test -d "$SOURCE_DIR/.git"
test -f "/etc/banano-miniapp/profiles/${DOMAIN}.env"
printf 'REMOTE_OK\n'
REMOTE

  file="$(remote_profile_path "$name")"
  {
    printf '# Managed by cdn.sh remote frontend manager\n'
    printf 'REMOTE_NAME=%q\n' "$name"
    printf 'REMOTE_SSH_HOST=%q\n' "$ssh_host"
    printf 'REMOTE_SOURCE_DIR=%q\n' "$source_dir"
    printf 'REMOTE_DOMAIN=%q\n' "$domain"
    printf 'REMOTE_BRANCH=%q\n' "$branch"
    printf 'REMOTE_USE_SUDO=%q\n' "$use_sudo"
  } > "$file"
  chmod 0600 "$file"
  success "Удалённый frontend сохранён: ${name}"
}

remote_deploy_by_name() {
  local name="$1"
  source_remote_profile "$name"

  [[ -n "${REMOTE_SSH_HOST:-}" ]] || die "REMOTE_SSH_HOST не задан"
  [[ -n "${REMOTE_SOURCE_DIR:-}" ]] || die "REMOTE_SOURCE_DIR не задан"
  [[ -n "${REMOTE_DOMAIN:-}" ]] || die "REMOTE_DOMAIN не задан"
  [[ -n "${REMOTE_BRANCH:-}" ]] || REMOTE_BRANCH="$DEFAULT_BRANCH"
  [[ "${REMOTE_USE_SUDO:-0}" =~ ^[01]$ ]] || die "REMOTE_USE_SUDO должен быть 0 или 1"

  log "Удалённая выкладка ${REMOTE_DOMAIN} через ${REMOTE_SSH_HOST}"
  remote_ssh "$REMOTE_SSH_HOST" \
    "SOURCE_DIR=$(printf '%q' "$REMOTE_SOURCE_DIR") BRANCH=$(printf '%q' "$REMOTE_BRANCH") DOMAIN=$(printf '%q' "$REMOTE_DOMAIN") USE_SUDO=$(printf '%q' "$REMOTE_USE_SUDO") bash -s" <<'REMOTE'
set -Eeuo pipefail
IFS=$'\n\t'

command -v git >/dev/null
command -v curl >/dev/null
command -v bash >/dev/null
[[ -d "$SOURCE_DIR/.git" ]]
[[ -f "/etc/banano-miniapp/profiles/${DOMAIN}.env" ]]

if [[ -n "$(git -C "$SOURCE_DIR" status --porcelain)" ]]; then
  echo "ERROR: в $SOURCE_DIR есть локальные изменения" >&2
  git -C "$SOURCE_DIR" status --short >&2
  exit 2
fi

git -C "$SOURCE_DIR" fetch --prune origin "$BRANCH"
git -C "$SOURCE_DIR" switch "$BRANCH"
git -C "$SOURCE_DIR" reset --hard "origin/${BRANCH}"

[[ -f "$SOURCE_DIR/cdn.sh" ]]
if [[ "$USE_SUDO" == "1" ]]; then
  sudo -n bash "$SOURCE_DIR/cdn.sh" --deploy-domain "$DOMAIN"
else
  [[ "$EUID" -eq 0 ]] || {
    echo "ERROR: удалённый SSH-пользователь не root. Включи REMOTE_USE_SUDO=1." >&2
    exit 3
  }
  bash "$SOURCE_DIR/cdn.sh" --deploy-domain "$DOMAIN"
fi

curl -fsS --max-time 20 "https://${DOMAIN}/frontend-health" >/dev/null
curl -fsSI --max-time 20 "https://${DOMAIN}/mini-app/" >/dev/null
printf 'REMOTE_DEPLOY_OK %s %s\n' "$DOMAIN" "$(git -C "$SOURCE_DIR" rev-parse --short HEAD)"
REMOTE

  success "Удалённый frontend ${REMOTE_DOMAIN} обновлён"
}

remote_update_interactive() {
  local name
  name="$(select_remote 'Какой удалённый frontend обновить?')" || die "Удалённый frontend не выбран"
  remote_deploy_by_name "$name"
}

remote_status_by_name() {
  local name="$1"
  source_remote_profile "$name"

  remote_ssh "$REMOTE_SSH_HOST" \
    "SOURCE_DIR=$(printf '%q' "$REMOTE_SOURCE_DIR") DOMAIN=$(printf '%q' "$REMOTE_DOMAIN") bash -s" <<'REMOTE'
set -Eeuo pipefail
printf 'host=%s\n' "$(hostname)"
printf 'domain=%s\n' "$DOMAIN"
printf 'commit=%s\n' "$(git -C "$SOURCE_DIR" rev-parse --short HEAD 2>/dev/null || echo unknown)"
printf 'branch=%s\n' "$(git -C "$SOURCE_DIR" branch --show-current 2>/dev/null || echo unknown)"
printf 'profile=%s\n' "$([[ -f "/etc/banano-miniapp/profiles/${DOMAIN}.env" ]] && echo ok || echo missing)"
printf 'nginx=%s\n' "$(systemctl is-active nginx 2>/dev/null || true)"
printf 'health=%s\n' "$(curl -fsS --max-time 10 "https://${DOMAIN}/frontend-health" 2>/dev/null || echo failed)"
printf 'miniapp_http=%s\n' "$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "https://${DOMAIN}/mini-app/" 2>/dev/null || echo failed)"
REMOTE
}

remote_status_interactive() {
  local name
  name="$(select_remote 'Какой удалённый frontend проверить?')" || die "Удалённый frontend не выбран"
  remote_status_by_name "$name"
}

print_menu() {
  clear 2>/dev/null || true
  local active
  active="$(active_domain)"
  cat <<MENU

${C_CYAN}Banano Mini App CDN manager${C_RESET}
Активный домен: ${active:-не выбран}

  1) Новый frontend-сервер / первая установка
  2) Обновить существующий frontend
  3) Добавить дополнительный домен-зеркало
  4) Переезд на новый домен
  5) Переключить основной MINI_APP_URL
  6) Статус всех доменов
  7) Откатить frontend из резервной копии
  8) Изменить сохранённый профиль
  9) Настроить удалённый frontend-сервер
 10) Обновить frontend на удалённом сервере
 11) Проверить удалённый frontend
  0) Выход
MENU
}

main_menu() {
  while true; do
    print_menu
    local choice
    read -r -p "Выбор: " choice || true
    echo
    case "$choice" in
      1) install_new_domain new; pause ;;
      2) update_domain; pause ;;
      3) add_mirror; pause ;;
      4) move_domain; pause ;;
      5) switch_active_domain; pause ;;
      6) show_status; pause ;;
      7) rollback_domain; pause ;;
      8) edit_profile; pause ;;
      9) configure_remote_frontend; pause ;;
      10) remote_update_interactive; pause ;;
      11) remote_status_interactive; pause ;;
      0) exit 0 ;;
      *) warn "Неизвестный пункт"; sleep 1 ;;
    esac
  done
}

usage() {
  cat <<'USAGE'
Использование:
  sudo bash cdn.sh
  sudo bash cdn.sh --deploy-domain <domain>
  sudo bash cdn.sh --remote-deploy <remote-name>
  sudo bash cdn.sh --remote-status <remote-name>
USAGE
}

main() {
  require_root
  prepare_state
  install_bootstrap_tools

  case "${1:-}" in
    "") main_menu ;;
    --deploy-domain)
      [[ -n "${2:-}" ]] || die "Укажи домен после --deploy-domain"
      run_installer "$(normalize_domain "$2")" --deploy-only
      success "Frontend $(normalize_domain "$2") обновлён"
      ;;
    --remote-deploy)
      [[ -n "${2:-}" ]] || die "Укажи имя после --remote-deploy"
      remote_deploy_by_name "$2"
      ;;
    --remote-status)
      [[ -n "${2:-}" ]] || die "Укажи имя после --remote-status"
      remote_status_by_name "$2"
      ;;
    -h|--help) usage ;;
    *) usage; die "Неизвестный аргумент: $1" ;;
  esac
}

main "$@"
