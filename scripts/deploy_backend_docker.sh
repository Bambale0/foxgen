#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

# Deployment may be invoked from a streamed SSH heredoc. Never allow Docker,
# backup helpers or other child processes to consume the caller's remaining
# script from stdin and create a false-green partial deployment.
exec </dev/null

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
COMPOSE_FILE="${COMPOSE_FILE:-${PROJECT_DIR}/compose.backend.yml}"
SYSTEMD_SERVICE="${SYSTEMD_SERVICE:-banano-kling}"
CONTAINER_NAME="${CONTAINER_NAME:-banano-kling-bot}"
APP_UID="${APP_UID:-10001}"
APP_GID="${APP_GID:-10001}"
HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-180}"
SKIP_BACKUP="${SKIP_BACKUP:-0}"
PULL_IMAGE="${PULL_IMAGE:-0}"
CUTOVER_STOP_CONTAINERS="${CUTOVER_STOP_CONTAINERS:-}"
CUTOVER_RESTART_ON_FAILURE="${CUTOVER_RESTART_ON_FAILURE:-1}"
ACTION="${1:-deploy}"

CUTOVER_STOPPED_CONTAINERS=()

log() {
    printf '[docker-deploy] %s\n' "$*"
}

warn() {
    printf '[docker-deploy] WARNING: %s\n' "$*" >&2
}

die() {
    printf '[docker-deploy] ERROR: %s\n' "$*" >&2
    exit 1
}

require_root() {
    [ "$(id -u)" -eq 0 ] || die "Run as root: sudo bash scripts/deploy_backend_docker.sh"
}

require_tools() {
    command -v docker >/dev/null 2>&1 || die "Docker is not installed"
    docker compose version >/dev/null 2>&1 || die "Docker Compose plugin is not installed"
    [ -f "$COMPOSE_FILE" ] || die "Compose file not found: $COMPOSE_FILE"
    [ -f "$PROJECT_DIR/.env" ] || die "Environment file not found: $PROJECT_DIR/.env"
}

compose() {
    docker compose --project-directory "$PROJECT_DIR" -f "$COMPOSE_FILE" "$@"
}

service_exists() {
    systemctl list-unit-files "${SYSTEMD_SERVICE}.service" --no-legend 2>/dev/null | grep -q .
}

prepare_runtime_dirs() {
    install -d -m 0755 \
        "$PROJECT_DIR/data" \
        "$PROJECT_DIR/static/uploads" \
        "$PROJECT_DIR/logs" \
        "$PROJECT_DIR/backups" \
        "$PROJECT_DIR/outputs"

    chown -R "$APP_UID:$APP_GID" \
        "$PROJECT_DIR/data" \
        "$PROJECT_DIR/static/uploads" \
        "$PROJECT_DIR/logs" \
        "$PROJECT_DIR/backups" \
        "$PROJECT_DIR/outputs"

    chmod 0600 "$PROJECT_DIR/.env"
    if [ -f "$PROJECT_DIR/.env.happyfox.runtime" ]; then
        chmod 0600 "$PROJECT_DIR/.env.happyfox.runtime"
    fi
    if [ -f "$PROJECT_DIR/.env.postgres" ]; then
        chmod 0600 "$PROJECT_DIR/.env.postgres"
    fi
}

build_or_pull_image() {
    export VCS_REF
    export BUILD_DATE
    VCS_REF="$(git -C "$PROJECT_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
    BUILD_DATE="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

    if [ "$PULL_IMAGE" = "1" ]; then
        log "Pulling configured image"
        compose pull bot
    else
        log "Building backend image"
        compose build --pull bot
    fi

    log "Checking Python bytecode and required runtime binaries"
    compose run --rm --no-deps bot python -m compileall -q bot scripts
    compose run --rm --no-deps --entrypoint ffmpeg bot -version >/dev/null
    compose run --rm --no-deps --entrypoint pg_dump bot --version >/dev/null
}

backup_database() {
    if [ "$SKIP_BACKUP" = "1" ]; then
        warn "Database backup skipped because SKIP_BACKUP=1"
        return 0
    fi

    [ -x "$PROJECT_DIR/scripts/backup_db.sh" ] \
        || chmod +x "$PROJECT_DIR/scripts/backup_db.sh"
    log "Creating pre-deploy database backup"
    SEND_BACKUP_TO_ADMINS=0 "$PROJECT_DIR/scripts/backup_db.sh"
}

container_health() {
    docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
        "$CONTAINER_NAME" 2>/dev/null || true
}

wait_for_health() {
    local deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS))
    local status=""

    while [ "$SECONDS" -lt "$deadline" ]; do
        status="$(container_health)"
        case "$status" in
            healthy)
                log "Container is healthy"
                return 0
                ;;
            unhealthy|exited|dead)
                warn "Container status: $status"
                return 1
                ;;
            *)
                printf '.'
                sleep 3
                ;;
        esac
    done
    printf '\n'
    warn "Health timeout after ${HEALTH_TIMEOUT_SECONDS}s; last status: ${status:-unknown}"
    return 1
}

stop_cutover_containers() {
    local name=""
    [ -n "$CUTOVER_STOP_CONTAINERS" ] || return 0

    for name in $CUTOVER_STOP_CONTAINERS; do
        if ! docker inspect "$name" >/dev/null 2>&1; then
            continue
        fi
        if [ "$(docker inspect --format '{{.State.Running}}' "$name" 2>/dev/null || true)" = "true" ]; then
            log "Stopping legacy cutover container: $name"
            docker stop --time 30 "$name" >/dev/null
            CUTOVER_STOPPED_CONTAINERS+=("$name")
        fi
    done
}

restore_cutover_containers() {
    local name=""
    [ "$CUTOVER_RESTART_ON_FAILURE" = "1" ] || return 0
    [ "${#CUTOVER_STOPPED_CONTAINERS[@]}" -gt 0 ] || return 0

    warn "Restoring legacy containers after failed cutover"
    for name in "${CUTOVER_STOPPED_CONTAINERS[@]}"; do
        docker start "$name" >/dev/null || warn "Failed to restart legacy container: $name"
    done
}

backfill_public_feed_videos() {
    log "Backfilling durable public feed videos"
    if ! compose exec -T bot python -m scripts.backfill_feed_video_media; then
        warn "Public feed video backfill failed; deployment continues and runtime URLs remain available"
    fi
}

rollback_to_systemd() {
    warn "Rolling back to systemd service"
    compose down --remove-orphans || true
    restore_cutover_containers
    if service_exists; then
        systemctl enable "$SYSTEMD_SERVICE" >/dev/null 2>&1 || true
        systemctl restart "$SYSTEMD_SERVICE"
        systemctl is-active --quiet "$SYSTEMD_SERVICE" \
            || die "Rollback failed: ${SYSTEMD_SERVICE} is not active"
        log "Rollback complete: ${SYSTEMD_SERVICE} is active"
    elif [ "${#CUTOVER_STOPPED_CONTAINERS[@]}" -eq 0 ]; then
        die "No systemd service or legacy containers found for rollback"
    fi
}

rollback_failed_docker_cutover() {
    compose down --remove-orphans || true
    restore_cutover_containers
}

deploy() {
    local systemd_was_active=0

    cd "$PROJECT_DIR"
    prepare_runtime_dirs
    compose config --quiet
    build_or_pull_image
    backup_database

    if service_exists && systemctl is-active --quiet "$SYSTEMD_SERVICE"; then
        systemd_was_active=1
        log "Stopping ${SYSTEMD_SERVICE} before Docker cutover"
        systemctl stop "$SYSTEMD_SERVICE"
    fi

    stop_cutover_containers

    log "Starting Docker backend"
    if ! compose up -d --remove-orphans bot; then
        rollback_failed_docker_cutover
        if [ "$systemd_was_active" = "1" ]; then
            systemctl restart "$SYSTEMD_SERVICE" || true
        fi
        die "Docker Compose failed to start"
    fi

    if ! wait_for_health; then
        compose logs --tail=200 bot >&2 || true
        rollback_failed_docker_cutover
        if [ "$systemd_was_active" = "1" ]; then
            systemctl restart "$SYSTEMD_SERVICE" || true
        fi
        die "Docker backend failed health check"
    fi

    backfill_public_feed_videos

    if service_exists; then
        systemctl disable "$SYSTEMD_SERVICE" >/dev/null 2>&1 || true
    fi

    compose ps
    log "Deployment complete. Existing reverse proxy can continue using the configured backend route."
}

status() {
    cd "$PROJECT_DIR"
    compose ps || true
    printf 'container_health=%s\n' "$(container_health)"
    if service_exists; then
        printf 'systemd=%s\n' "$(systemctl is-active "$SYSTEMD_SERVICE" 2>/dev/null || true)"
        printf 'systemd_enabled=%s\n' "$(systemctl is-enabled "$SYSTEMD_SERVICE" 2>/dev/null || true)"
    fi
}

logs() {
    cd "$PROJECT_DIR"
    compose logs -f --tail=200 bot
}

stop_docker() {
    cd "$PROJECT_DIR"
    compose down --remove-orphans
}

usage() {
    cat <<USAGE
Usage:
  sudo bash scripts/deploy_backend_docker.sh deploy
  sudo bash scripts/deploy_backend_docker.sh status
  sudo bash scripts/deploy_backend_docker.sh logs
  sudo bash scripts/deploy_backend_docker.sh rollback
  sudo bash scripts/deploy_backend_docker.sh stop

Environment overrides:
  SYSTEMD_SERVICE=banano-kling
  SKIP_BACKUP=1
  PULL_IMAGE=1 HAPPYFOX_IMAGE=ghcr.io/example/happyfox:sha
  HEALTH_TIMEOUT_SECONDS=180
  CUTOVER_STOP_CONTAINERS='legacy-api legacy-bot legacy-worker'
  CUTOVER_RESTART_ON_FAILURE=1
  FEED_VIDEO_BACKFILL_LIMIT=50
USAGE
}

main() {
    require_root
    require_tools

    case "$ACTION" in
        deploy) deploy ;;
        status) status ;;
        logs) logs ;;
        rollback) rollback_to_systemd ;;
        stop) stop_docker ;;
        -h|--help|help) usage ;;
        *) usage; die "Unknown action: $ACTION" ;;
    esac
}

main "$@"
