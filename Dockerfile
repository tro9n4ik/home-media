# ── Stage 1: React ────────────────────────────────────────────────────────────
FROM node:20-slim AS frontend

WORKDIR /build
COPY admin/package.json admin/package-lock.json* ./
RUN npm install --silent
COPY admin/ ./
RUN npm run build

# ── Stage 2: Python core ──────────────────────────────────────────────────────
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq5 && \
    rm -rf /var/lib/apt/lists/*

COPY core/requirements.txt .
RUN pip install -r requirements.txt

COPY core/ /app/
COPY --from=frontend /build/dist /app/app/web/static/admin

# Создаём все нужные папки при сборке образа
# data/postgres нужна для postgres до его старта
RUN mkdir -p /app/data/plugins /app/data/uploads /app/data/postgres && \
    chmod +x /app/entrypoint.sh

EXPOSE 8142
ENTRYPOINT ["/app/entrypoint.sh"]
