#!/bin/sh
set -e

echo ""
echo "🏠  Home.Media v4 — деплой"
echo "────────────────────────────────────────"

# ── 1. .env ───────────────────────────────────────────────────────────────────
if [ ! -f .env ]; then
  echo "📋  Создаём .env..."
  cp .env.example .env

  # Генерируем SECRET_KEY через python3 или openssl
  if command -v python3 > /dev/null 2>&1; then
    SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
  elif command -v openssl > /dev/null 2>&1; then
    SECRET=$(openssl rand -hex 32)
  else
    echo "❌  Нужен python3 или openssl для генерации SECRET_KEY"
    exit 1
  fi

  # Подставляем в .env (работает на Linux и macOS)
  sed -i.bak "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET}|" .env && rm -f .env.bak
  echo "✅  SECRET_KEY сгенерирован"
else
  echo "✅  .env уже существует — пропускаем"
fi

# ── 2. docker compose ─────────────────────────────────────────────────────────
echo ""
echo "🐳  Собираем и запускаем контейнеры..."
docker compose up -d --build

# ── 3. Ждём пока ядро поднимется ─────────────────────────────────────────────
echo ""
echo "⏳  Ждём запуска Home.Media..."
RETRIES=30
i=0
while [ $i -lt $RETRIES ]; do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8142/api/system/health 2>/dev/null || echo "000")
  if [ "$STATUS" = "200" ]; then
    break
  fi
  i=$((i + 1))
  sleep 2
done

if [ "$STATUS" != "200" ]; then
  echo "⚠️  Сервис не ответил за 60 секунд. Проверь логи:"
  echo "   docker logs home-media"
  exit 1
fi

# ── 4. Готово ─────────────────────────────────────────────────────────────────
echo ""
echo "────────────────────────────────────────"
echo "✅  Home.Media запущен!"
echo ""

# Пробуем определить IP
if command -v hostname > /dev/null 2>&1; then
  IP=$(hostname -I 2>/dev/null | awk '{print $1}')
fi
IP=${IP:-"YOUR_NAS_IP"}

echo "   🌐  http://${IP}:8142"
echo ""
echo "   При первом входе создайте аккаунт администратора."
echo ""
echo "   Полезные команды:"
echo "   docker compose logs -f home-media    # логи"
echo "   docker compose down                  # остановить"
echo "   docker compose up -d --build         # пересобрать"
echo "────────────────────────────────────────"
