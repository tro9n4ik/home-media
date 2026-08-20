#!/bin/sh
set -e

# ── Создаём папки ─────────────────────────────────────────────────────────────
mkdir -p /app/data/plugins /app/data/uploads /app/data/postgres
echo "[entrypoint] Папки созданы"

# ── SECRET_KEY ────────────────────────────────────────────────────────────────
SECRET_FILE=/app/data/.secret_key
if [ ! -f "$SECRET_FILE" ]; then
    python3 -c "import secrets; print(secrets.token_hex(32))" > "$SECRET_FILE"
    echo "[entrypoint] SECRET_KEY сгенерирован"
fi
export SECRET_KEY=$(cat "$SECRET_FILE")

# ── Ждём postgres ─────────────────────────────────────────────────────────────
# Используем pg_isready через python psycopg — проверяет реальную готовность БД,
# а не просто доступность порта (порт открыт и во время init-фазы)
echo "[entrypoint] Ожидаем PostgreSQL..."
MAX=60
i=0
while [ $i -lt $MAX ]; do
    python3 -c "
import sys
try:
    import psycopg
    conn = psycopg.connect(
        'postgresql://hm:hm@home-media-postgres:5432/home_media',
        connect_timeout=2
    )
    conn.close()
    sys.exit(0)
except Exception as e:
    sys.exit(1)
" 2>/dev/null && break
    i=$((i+1))
    echo "[entrypoint] Postgres не готов, попытка $i/$MAX..."
    sleep 3
done

if [ $i -eq $MAX ]; then
    echo "[entrypoint] Postgres не ответил, выходим"
    exit 1
fi

echo "[entrypoint] PostgreSQL готов"

# ── Миграции ──────────────────────────────────────────────────────────────────
echo "[entrypoint] Применяем миграции..."
alembic upgrade head

# ── Старт ─────────────────────────────────────────────────────────────────────
echo "[entrypoint] Home.Media v4 запускается..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8142
