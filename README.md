# Home.Media v4

Модульная медиаплатформа для Synology NAS с плагинной архитектурой.
Каждый плагин — отдельный Python-процесс с собственным venv и веб-интерфейсом.

<!-- При пушe на GitHub замени OWNER/REPO на свой ник и репозиторий -->
[![core tests](https://github.com/OWNER/REPO/actions/workflows/tests.yml/badge.svg)](https://github.com/OWNER/REPO/actions/workflows/tests.yml)

**Что это:** ядро-платформа, которое запускает, останавливает и обслуживает плагины.
Плагины добавляют функции: Telegram-бот, поиск фильмов, торренты, камеры и т.д.
Ядро берёт на себя авторизацию, назначение портов, health-проверки, логи,
резервное копирование настроек и reverse-proxy до UI плагинов.

## Возможности

- **Установка плагинов из .hm пакета** — просто загрузите файл в веб-интерфейсе
- **Автозапуск** — после перезагрузки NAS все включённые плагины стартуют сами
- **Включение/отключение** — каждый плагин можно отключить (стоп + снятие с автозапуска)
- **Мониторинг** — статусы плагинов, health-проверки, логи в реальном времени
- **Изоляция** — каждый плагин в своём venv, свои порты (8100–8200), свои данные
- **Конфиг плагинов** — декларативная схема с типами и секретами (токены маскируются)
- **Бэкап настроек** — экспорт/импорт конфигов всех плагинов одним JSON
- **Тёмная тема**, адаптивный веб-интерфейс

## Быстрый старт

```bash
# 1. Распаковать в /volume1/docker/hm3-syn/
# 2. Container Manager → Проекты → Создать → выбрать папку
# 3. Deploy (~10 мин на первую сборку React)
# 4. Открыть: http://NAS_IP:8142 — создать аккаунт администратора
```

Или вручную: `./start.sh` (генерирует .env, собирает и запускает контейнеры).

## Архитектура

```
home-media-core (:8142)
├── FastAPI        — auth, plugin lifecycle, reverse proxy
├── PostgreSQL     — метаданные плагинов (SQLite для локальной разработки)
└── React SPA      — веб-интерфейс администрирования

Плагины (subprocess + venv, порты 8100–8200):
├── example         — шаблон для разработки своих плагинов
├── telegram_bot    — Telegram gateway: команды, клавиатуры, allowlist
├── torrents        — менеджер загрузок: qBittorrent, Prowlarr, подписки
└── home_assistant  — управление Умным домом из Telegram и веб-панели
```

## Документация

- [Установка и деплой](docs/DEPLOY.md)
- [Архитектура](docs/ARCHITECTURE.md)
- [SDK — как написать свой плагин](docs/SDK.md)
- [Формат .hm пакета](docs/HM_PACKAGE.md)
- [API ядра](docs/API.md)

## Lifecycle плагина

```
.hm файл → unpack → venv → pip install → start subprocess → /health → running
```

Статусы: `installing` → `starting` → `running` | `degraded` | `failed` | `stopped`

- `installing` — распаковка/установка зависимостей в фоне
- `starting` — процесс запущен, ждём /health (до 30 с)
- `running` — /health отвечает ok
- `degraded` — процесс жив, но /health не отвечает
- `stopped` — остановлен вручную или отключён
- `failed` — упал или не прошёл healthcheck (причина в `last_error`)

## Структура проекта

```
core/                  — ядро (FastAPI)
├── app/api/           — REST API (auth, plugins, system)
├── app/services/      — runtime, installer, registry, proxy
├── app/models/        — SQLAlchemy модели
├── app/web/static/    — собранный React (build из admin/)
└── alembic/           — миграции БД
admin/                 — React SPA (npm run build → core/app/web/static/admin)
plugins/
├── sdk/plugin_sdk.py  — SDK для плагинов (копируется в каждый плагин)
└── example/           — готовый шаблон плагина (сборка → example.hm)
docker-compose.yml     — postgres + ядро
```

## Разработка на Windows (без Docker)

Ядро кросс-платформенное: можно запускать локально с SQLite.

```bash
cd core
pip install -r requirements.txt
$env:DATABASE_URL = "sqlite:///./dev.db"
$env:DATA_DIR = "./dev_data"
python -m alembic upgrade head
python -m uvicorn app.main:app --port 8142
```

Плагины тоже запускаются на Windows (venv создаётся локально).
Сборка админки: `cd admin && npm install && npm run build:sync` —
собирает React в `admin/dist` и копирует результат в `core/app/web/static/admin`.
При деплое через Docker сборка происходит автоматически внутри образа.

## .env переменные

```env
SECRET_KEY=         # Секрет сессий (генерируется автоматически)
DATABASE_URL=       # postgresql+psycopg://... или sqlite:///./dev.db
DATA_DIR=           # /app/data
PIP_INDEX_URL=      # https://pypi.org/simple/ (или зеркало, напр. aliyun)
CORE_INTERNAL_URL=  # URL ядра для плагинов (по умолчанию http://127.0.0.1:8142)
```
