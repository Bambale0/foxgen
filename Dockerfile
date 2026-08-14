FROM python:3.12.13-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system foxgen && adduser --system --ingroup foxgen foxgen

COPY requirements.lock pyproject.toml README.md ./
COPY src ./src
COPY migrations ./migrations
COPY scripts ./scripts
COPY alembic.ini ./

RUN python -m pip install --requirement requirements.lock \
    && python -m pip install --no-deps . \
    && python -m pip check

USER foxgen

CMD ["foxgen-api"]
