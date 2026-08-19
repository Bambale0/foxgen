# syntax=docker/dockerfile:1.7

FROM python:3.12-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libffi-dev \
        libjpeg62-turbo-dev \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./

RUN python -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --upgrade pip setuptools wheel \
    && /opt/venv/bin/pip install -r requirements.txt


FROM python:3.12-slim-bookworm AS runtime

ARG APP_UID=10001
ARG APP_GID=10001
ARG VCS_REF="unknown"
ARG BUILD_DATE="unknown"

LABEL org.opencontainers.image.title="Banano Kling Telegram Bot" \
      org.opencontainers.image.description="Webhook backend for the Banano Kling / NEUROMIX Telegram bot" \
      org.opencontainers.image.source="https://github.com/Bambale0/banano_kling" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}"

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    BANANO_SKIP_PROJECT_ENV=1 \
    BANANO_LOG_TO_STDOUT=1 \
    WEBHOOK_BIND_HOST=0.0.0.0 \
    WEBHOOK_PORT=1888

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        ffmpeg \
        gzip \
        postgresql-client \
        sqlite3 \
        util-linux \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid "${APP_GID}" app \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" --create-home --home-dir /home/app app

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app . /app

RUN python scripts/apply_visible_copy_fixes.py \
    && PYTHONPYCACHEPREFIX=/tmp/banano-pycache python -m compileall -q \
        bot/keyboards.py \
        bot/handlers/image_analyzer.py \
        bot/handlers/prompt_analyzer_v2.py \
        bot/browser_auth.py \
        bot/miniapp.py \
        bot/services/trend_preview_service.py \
        bot/trend_api.py \
    && rm -rf /tmp/banano-pycache \
    && install -d -o app -g app -m 0755 \
        /app/data \
        /app/static/uploads \
        /app/logs \
        /app/backups \
        /app/outputs \
        /app/tmp \
    && find /app/scripts -maxdepth 1 -type f -name '*.sh' -exec chmod 0755 {} +

USER app

EXPOSE 1888

HEALTHCHECK --interval=20s --timeout=7s --start-period=40s --retries=5 \
    CMD ["python", "scripts/docker_healthcheck.py"]

CMD ["python", "-m", "bot.main"]
