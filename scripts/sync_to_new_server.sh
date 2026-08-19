#!/usr/bin/env bash
set -euo pipefail

REMOTE_USER="${REMOTE_USER:-root}"
REMOTE_HOST="${REMOTE_HOST:-144.76.188.75}"
REMOTE_PORT="${REMOTE_PORT:-22}"
REMOTE_DIR="${REMOTE_DIR:-/root/tanya/banano_kling}"
MODE="${MODE:-initial}"
CODEX_BIN="${CODEX_BIN:-/root/.vscode-server/extensions/openai.chatgpt-26.616.51431-linux-x64/bin/linux-x86_64/codex}"
IDENTITY_FILE="${IDENTITY_FILE:-}"

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
identity_args=()
identity_string=""
if [ -n "$IDENTITY_FILE" ]; then
    identity_args=(-i "$IDENTITY_FILE")
    identity_string="-i ${IDENTITY_FILE}"
fi

if [ -n "${SSHPASS:-}" ]; then
    if ! command -v sshpass >/dev/null 2>&1; then
        echo "SSHPASS is set but sshpass is not installed." >&2
        exit 1
    fi
    SSH=(sshpass -e ssh "${identity_args[@]}" -p "$REMOTE_PORT" -o StrictHostKeyChecking=accept-new)
    RSYNC_SSH="sshpass -e ssh ${identity_string} -p ${REMOTE_PORT} -o StrictHostKeyChecking=accept-new"
else
    SSH=(ssh "${identity_args[@]}" -p "$REMOTE_PORT" -o StrictHostKeyChecking=accept-new)
    RSYNC_SSH="ssh ${identity_string} -p ${REMOTE_PORT} -o StrictHostKeyChecking=accept-new"
fi

common_rsync_args=(
    --archive
    --human-readable
    --info=progress2
    --delete
    --exclude venv/
    --exclude __pycache__/
    --exclude .mypy_cache/
    --exclude .pytest_cache/
    --exclude bot.pid
)

remote="${REMOTE_USER}@${REMOTE_HOST}"

case "$MODE" in
    initial)
        "${SSH[@]}" "$remote" "mkdir -p '$REMOTE_DIR'"
        rsync "${common_rsync_args[@]}" -e "$RSYNC_SSH" "$PROJECT_DIR"/ "$remote:$REMOTE_DIR"/
        ;;
    final)
        echo "Final mode expects the old production bot to be stopped or writes to be paused."
        sqlite3 "$PROJECT_DIR/bot.db" 'PRAGMA quick_check;'
        "${SSH[@]}" "$remote" "mkdir -p '$REMOTE_DIR'"
        rsync "${common_rsync_args[@]}" -e "$RSYNC_SSH" "$PROJECT_DIR"/ "$remote:$REMOTE_DIR"/
        ;;
    codex)
        "${SSH[@]}" "$remote" "mkdir -p /root/.codex /opt/codex"
        rsync --archive --human-readable -e "$RSYNC_SSH" \
            --exclude 'logs_*.sqlite*' \
            --exclude 'sessions/' \
            --exclude 'shell_snapshots/' \
            --exclude 'attachments/' \
            --exclude 'cache/codex_app_directory/' \
            --exclude 'cache/codex_apps_tools/' \
            /root/.codex/ "$remote:/root/.codex"/
        if [ -x "$CODEX_BIN" ]; then
            rsync --archive --human-readable -e "$RSYNC_SSH" "$CODEX_BIN" "$remote:/opt/codex/codex"
            "${SSH[@]}" "$remote" "chmod 0755 /opt/codex/codex"
        else
            echo "Codex binary not found locally: $CODEX_BIN" >&2
        fi
        ;;
    *)
        echo "Unknown MODE=$MODE. Use MODE=initial, MODE=final, or MODE=codex." >&2
        exit 1
        ;;
esac
