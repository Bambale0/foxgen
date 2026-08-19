FROM node:22-bookworm-slim AS miniapp-build

WORKDIR /build/frontend/miniapp

COPY frontend/miniapp/package.json ./
RUN npm install --no-audit --no-fund

COPY frontend/miniapp ./
RUN npm run typecheck \
    && npm test \
    && npm run build \
    && test -s out/index.html \
    && test -s out/happyfox-logo.webp \
    && grep -Fq 'name="foxgen-miniapp-shell" content="parity-v14"' out/index.html \
    && grep -Fq '/mini-app/_next/' out/index.html

FROM python:3.12.13-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system foxgen && adduser --system --ingroup foxgen foxgen

COPY requirements.lock pyproject.toml README.md ./
COPY src ./src
RUN rm -rf ./src/foxgen/miniapp_static \
    && mkdir -p ./src/foxgen/miniapp_static
COPY --from=miniapp-build /build/frontend/miniapp/out/ ./src/foxgen/miniapp_static/
COPY migrations ./migrations
COPY scripts ./scripts
COPY alembic.ini ./

RUN python -m pip install --requirement requirements.lock \
    && python -m pip install --no-deps . \
    && python -m pip check \
    && python -c 'from pathlib import Path; import foxgen; root=Path(foxgen.__file__).parent/"miniapp_static"; assert (root/"index.html").is_file(); assert (root/"happyfox-logo.webp").is_file(); assert any((root/"_next"/"static").rglob("*.js")); print(f"packaged Mini App assets: {root}")'

USER foxgen

CMD ["foxgen-api"]
