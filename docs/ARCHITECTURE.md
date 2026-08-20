# Архитектура Home.Media v4

## Общая схема

```
┌─────────────────────────────────────────────────┐
│  Browser (React SPA)                            │
│  http://NAS:8142/admin/                          │
└──────────────┬──────────────────────────────────┘
               │ HTTP + cookie-сессии
┌──────────────▼──────────────────────────────────┐
│  Ядро (core/) — FastAPI :8142                   │
│  ┌─────────────┐ ┌─────────────┐ ┌────────────┐ │
│  │ API plugins │ │ API system  │ │ API auth   │ │
│  └──────┬──────┘ └──────┬──────┘ └─────┬──────┘ │
│         │               │              │        │
│  ┌──────▼───────────────▼──────────────▼──────┐ │
│  │ Сервисы: runtime / installer / registry /  │ │
│  │          proxy / settings                  │ │
│  └──────────────────┬─────────────────────────┘ │
│  PostgreSQL         │ subprocess (venv)         │
│  (метаданные)       ▼                           │
│                    Плагин 1 (порт 8100)         │
│                    Плагин 2 (порт 8101)         │
│                    ...                          │
└─────────────────────────────────────────────────┘
```

## Компоненты ядра

### Сервисы (core/app/services/)

| Модуль | Ответственность |
|---|---|
| `plugin_runtime.py` | Жизненный цикл процессов: start/stop/restart, health-статусы, логи, graceful shutdown (SIGTERM → wait → SIGKILL), кросплатформенно (Linux/Windows) |
| `plugin_installer.py` | Распаковка .hm, валидация manifest, создание venv, pip install, проверка зависимостей |
| `plugin_registry.py` | Назначение портов из пула 8100–8200, service discovery |
| `plugin_proxy.py` | Reverse-proxy: `/api/plugins/{id}/proxy/*` → плагин. Поддерживает стриминг (MJPEG/SSE) |
| `settings.py` | Хранилище настроек плагинов (model `Setting`) |

### API (core/app/api/)

- `auth.py` — login/logout, создание первого администратора, смена пароля. Cookie-сессии (itsdangerous, 30 дней)
- `plugins.py` — CRUD плагинов: install (background), start/stop/restart, **enable/disable**, logs, connection, proxy
- `system.py` — health, metrics (CPU/RAM/диск), ui-pages, логи, экспорт/импорт настроек

## Жизненный цикл плагина

### Установка

1. Файл `.hm` (zip) загружается в `/api/plugins/install`
2. `plugin_installer.unpack()` — распаковка с валидацией:
   - есть ли `manifest.json` (обязательные ключи `id`, `name`, `version`)
   - безопасность: запрет path traversal
   - `data/` плагина **сохраняется** при переустановке
3. Статус → `installing`, задача уходит в background
4. В фоне: создание venv → pip install → статус `starting` → запуск процесса → ждём `/health` (30 с) → `running` или `failed` (причина в `last_error`)

### Статусы

```
installing → starting → running
                 ↓          ↓
              failed     degraded
                            ↓
                         stopped   (явный stop или disable)
```

Фактический статус определяется так:
- pid-файл есть и процесс жив, `/health` отвечает → `running`
- процесс жив, `/health` молчит → `degraded`
- pid-файл есть, процесс мёртв → `failed`
- pid-файла нет → `stopped`

### Автозапуск

При старте ядра (lifespan) все плагины с `enabled=True` запускаются асинхронно.
Это восстанавливает работу после перезагрузки NAS или пересоздания контейнера.
Плагины, которые пользователь явно остановил (`stopped`) или отключил — не запускаются.

### Enable / Disable

- **Enable** — плагин будет автозапускаться после перезагрузки ядра
- **Disable** — плагин останавливается и снимается с автозапуска
- Управление: страница «Плагины», переключатель в карточке плагина

## Runtime окружение плагина

Ядро передаёт плагину при старте:

| Переменная | Описание |
|---|---|
| `PLUGIN_ID` | ID плагина из manifest |
| `PLUGIN_PORT` | Назначенный ядром порт |
| `CORE_URL` | URL ядра для service discovery |
| `DATA_DIR` | Папка данных плагина (переживает переустановку) |
| `PYTHONPATH` | Папка плагина (чтобы работал `import plugin_sdk`) |

Stdout/stderr плагина перенаправляются в `<plugin_dir>/plugin.log` — доступны в разделе «Логи».

## Прокси и UI плагинов

- Плагин может отдавать свой веб-интерфейс на `/ui/` (папка `app/web/` в пакете)
- Админка показывает его в iframe через прокси ядра: `/api/plugins/{id}/proxy/ui/`
- Прокси поддерживает стриминг (MJPEG-камеры, SSE)
- Общение админки с плагином: `postMessage` — тема, тосты
- Пункты меню плагина определяются в `manifest.json → ui_pages`

## Межплагинное взаимодействие

Плагины не знают адресов друг друга напрямую. Вместо этого:

```python
# из SDK
url = await plugin_url("another_plugin")   # http://127.0.0.1:8103
await httpx.get(f"{url}/some-endpoint")
```

Ядро отдаёт адреса через `/api/plugins/{id}/internal/connection`
(без авторизации, доступно только изнутри контейнера).

## Безопасность

- Пароли — pbkdf2_sha256, сессии — подписанные cookie (30 дней)
- Секреты плагинов маскируются: при чтении конфига через API (`masked=true`) и при экспорте настроек (ключи из `manifest → config_secrets`)
- При импорте настроек маска `••••••••` не затирает реальное значение
- Конфиг хранится в `DATA_DIR/config.json` плагина

## Тестирование

Юнит- и интеграционные тесты живут в `core/tests/` (pytest).

Запуск локально:

```bash
cd core
pip install -r requirements-dev.txt
pytest                  # весь набор (90 тестов)
pytest --cov=app --cov-report=term    # с покрытием сервисного слоя
pytest tests/test_plugin_installer.py -k unpack   # отдельный файл/фильтр
```

- Тесты нацелены на сервисный слой: `plugin_installer` (91%), `plugin_runtime` (79%), `plugin_registry` (100%), `plugin_proxy` (90%)
- БД подменяется на SQLite in-memory (StaticPool) — реальный Postgres не нужен
- Интеграционные тесты `plugin_proxy` поднимают настоящий aiohttp-сервер на localhost
- В CI (`.github/workflows/tests.yml`) на push/PR выполняется прогон + порог покрытия 75% для сервисного слоя

## База данных

- **PostgreSQL** в Docker (docker-compose) — основной режим
- **SQLite** — для локальной разработки (`DATABASE_URL=sqlite:///./dev.db`)
- Миграции — Alembic (`core/alembic/`), применяются автоматически в entrypoint

### Таблицы

- `users` — администраторы
- `plugins` — метаданные и runtime-состояние плагинов
- `settings` — пары ключ/значение для плагинов (зарезервировано)
