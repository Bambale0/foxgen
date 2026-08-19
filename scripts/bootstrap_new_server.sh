#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/root/tanya/banano_kling}"
APP_SERVICE="${APP_SERVICE:-banano-kling}"
APP_USER="${APP_USER:-root}"
SERVER_NAME="${SERVER_NAME:-_}"
START_APP_SERVICE="${START_APP_SERVICE:-0}"
INSTALL_NODE="${INSTALL_NODE:-1}"
INSTALL_CODEX_FROM_OPT="${INSTALL_CODEX_FROM_OPT:-1}"

if [ "$(id -u)" -ne 0 ]; then
    echo "Run as root."
    exit 1
fi

read_env_value() {
    local key="$1"
    local env_file="$PROJECT_DIR/.env"
    local line=""
    local value=""

    [ -f "$env_file" ] || return 0
    line="$(grep -E "^[[:space:]]*${key}=" "$env_file" | tail -n 1 || true)"
    [ -n "$line" ] || return 0
    value="${line#*=}"
    value="${value%%#*}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    value="${value%\"}"
    value="${value#\"}"
    value="${value%\'}"
    value="${value#\'}"
    printf '%s' "$value"
}

need_cmd() {
    command -v "$1" >/dev/null 2>&1
}

install_node_22_if_needed() {
    if [ "$INSTALL_NODE" != "1" ]; then
        return 0
    fi

    if need_cmd node; then
        local major
        major="$(node -p 'Number(process.versions.node.split(".")[0])' 2>/dev/null || echo 0)"
        if [ "$major" -ge 20 ] && need_cmd npx; then
            return 0
        fi
    fi

    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
    apt-get install -y nodejs
}

if [ ! -d "$PROJECT_DIR" ]; then
    echo "Project directory not found: $PROJECT_DIR"
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
    ca-certificates \
    curl \
    git \
    nginx \
    postgresql-client \
    redis-server \
    rsync \
    sqlite3 \
    ffmpeg \
    bubblewrap \
    build-essential \
    python3 \
    python3-dev \
    python3-pip \
    python3-venv \
    pkg-config \
    libffi-dev \
    libjpeg-dev \
    zlib1g-dev

install_node_22_if_needed

cd "$PROJECT_DIR"
mkdir -p logs backups data static/uploads
chmod +x start.sh stop.sh restart.sh scripts/*.sh 2>/dev/null || true
[ -f .env ] && chmod 600 .env
[ -f .env.postgres ] && chmod 600 .env.postgres

python3 -m venv venv
venv/bin/python -m pip install -U pip setuptools wheel
venv/bin/pip install -r requirements.txt

systemctl enable --now redis-server

webhook_port="$(read_env_value WEBHOOK_PORT)"
webhook_port="${webhook_port:-8443}"

cat > "/etc/systemd/system/${APP_SERVICE}.service" <<UNIT
[Unit]
Description=banano_kling Telegram Bot
After=network-online.target redis-server.service
Wants=network-online.target

[Service]
Type=simple
User=${APP_USER}
WorkingDirectory=${PROJECT_DIR}
EnvironmentFile=-${PROJECT_DIR}/.env
EnvironmentFile=-${PROJECT_DIR}/.env.postgres
ExecStart=/bin/bash -lc 'cd ${PROJECT_DIR} && source venv/bin/activate && exec python -m bot.main'
Restart=always
RestartSec=5
TimeoutStopSec=20
KillMode=mixed

[Install]
WantedBy=multi-user.target
UNIT

cat > "/etc/nginx/sites-available/${APP_SERVICE}.conf" <<NGINX
server {
    listen 80;
    server_name ${SERVER_NAME};

    client_max_body_size 60m;

    location / {
        proxy_pass http://127.0.0.1:${webhook_port};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Host \$host;
        proxy_set_header X-Forwarded-Port \$server_port;
        proxy_connect_timeout 5s;
        proxy_send_timeout 60s;
        proxy_read_timeout 120s;
        proxy_request_buffering off;
        proxy_buffering off;
    }
}
NGINX

ln -sfn "/etc/nginx/sites-available/${APP_SERVICE}.conf" "/etc/nginx/sites-enabled/${APP_SERVICE}.conf"
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

systemctl daemon-reload
if [ "$START_APP_SERVICE" = "1" ]; then
    systemctl enable --now "$APP_SERVICE"
else
    systemctl disable "$APP_SERVICE" >/dev/null 2>&1 || true
    echo "Prepared ${APP_SERVICE}.service but did not start it. Set START_APP_SERVICE=1 to start during cutover."
fi

if [ "$INSTALL_CODEX_FROM_OPT" = "1" ] && [ -x /opt/codex/codex ]; then
    install -m 0755 /opt/codex/codex /usr/local/bin/codex
fi

if [ -d /root/.codex ]; then
    chmod 700 /root/.codex
    [ -f /root/.codex/config.toml ] && chmod 600 /root/.codex/config.toml
    [ -f /root/.codex/auth.json ] && chmod 600 /root/.codex/auth.json

    if [ -f /root/.codex/config.toml ] && ! grep -Fq "[projects.\"${PROJECT_DIR}\"]" /root/.codex/config.toml; then
        {
            printf '\n[projects."%s"]\n' "$PROJECT_DIR"
            printf 'trust_level = "trusted"\n'
        } >> /root/.codex/config.toml
    fi
fi

if need_cmd codex; then
    codex --version || true
    codex mcp list || true
else
    echo "Codex binary not found. Copy local codex to /opt/codex/codex or install the Codex extension/CLI, then rerun."
fi

echo "Bootstrap complete for ${PROJECT_DIR}. Nginx proxies ${SERVER_NAME}:80 to 127.0.0.1:${webhook_port}."
