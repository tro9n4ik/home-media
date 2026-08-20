# API ядра

Базовый URL: `http://NAS_IP:8142`

Все маршруты `/api/*`, кроме `/api/auth/login`, `/api/auth/setup*`,
`/api/system/health` и `/api/plugins/{id}/internal/connection` — требуют
авторизации (cookie `hm_session`).

Интерактивная документация: `/api/docs` (Swagger UI).

## Auth

| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/auth/setup/needed` | Нужен ли первый вход (нет пользователей) |
| POST | `/api/auth/setup` | Создать первого администратора |
| POST | `/api/auth/login` | Войти (JSON или form-data) |
| POST | `/api/auth/logout` | Выйти |
| GET | `/api/auth/me` | Текущий пользователь |
| POST | `/api/auth/change-password` | Сменить пароль |

## Плагины

| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/plugins` | Список плагинов (актуальные статусы) |
| GET | `/api/plugins/{id}` | Плагин по ID |
| POST | `/api/plugins/install` | Установить `.hm` (multipart `file`) |
| POST | `/api/plugins/{id}/start` | Запустить (ждёт health до 30 с) |
| POST | `/api/plugins/{id}/stop` | Остановить |
| POST | `/api/plugins/{id}/restart` | Перезапустить |
| POST | `/api/plugins/{id}/enable` | Включить (автозапуск при старте ядра) |
| POST | `/api/plugins/{id}/disable` | Отключить (стоп + снятие с автозапуска) |
| DELETE | `/api/plugins/{id}` | Удалить (включая данные) |
| GET | `/api/plugins/{id}/logs?lines=N` | Логи плагина |
| GET | `/api/plugins/{id}/connection` | URL плагина (service discovery, авторизованный) |
| GET | `/api/plugins/{id}/internal/connection` | URL плагина (без авторизации, только localhost) |
| * | `/api/plugins/{id}/proxy/{path}` | Прокси до плагина (GET/POST/PUT/PATCH/DELETE) |

### Формат плагина

```json
{
  "plugin_id": "example",
  "name": "Example Plugin",
  "version": "1.1.0",
  "description": "…",
  "status": "running",
  "enabled": true,
  "assigned_port": 8100,
  "last_error": null,
  "ui_pages": []
}
```

### Установка (асинхронная)

`POST /api/plugins/install` возвращает плагин в статусе `installing`.
Дальнейший прогресс: `GET /api/plugins/{id}` (статусы `installing` →
`starting` → `running` | `failed`). При ошибке — `last_error` с причиной.

## Система

| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/system/health` | `{"status":"ok","version":"4.0.0"}` |
| GET | `/api/system/metrics` | CPU, RAM, диск |
| GET | `/api/system/ui-pages` | Пункты меню из manifest'ов плагинов |
| GET | `/api/system/registry` | Назначенные порты |
| GET | `/api/system/logs/{id}?lines=N` | Логи плагина |
| GET | `/api/system/logs?lines=N` | Логи всех плагинов |
| GET | `/api/system/settings/export` | Бэкап настроек (JSON-файл) |
| POST | `/api/system/settings/import` | Восстановить из бэкапа |

## Коды ответов

- `401` — не авторизован / сессия истекла
- `404` — плагин не найден
- `422` — невалидный пакет или конфиг
- `503` — плагин не запущен (proxy/connection)
- `502` — плагин недоступен (connection refused)
- `504` — плагин не ответил за 30 с
