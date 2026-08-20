# SDK — пишем свой плагин Home.Media v4

## Что такое плагин

Плагин — это FastAPI-приложение в собственном venv, запускаемое ядром.
Всё общение с ядром идёт через HTTP: health, конфиг, прокси, service discovery.

Минимальный плагин — 30 строк. С полным функционалом — 100–200 строк.

## Быстрый старт

Возьмите готовый шаблон из `plugins/example/`, переименуйте и наполняйте.
Структура пакета:

```
my_plugin.hm (zip)
├── manifest.json       # метаданные
├── requirements.txt    # зависимости
└── app/
    ├── plugin_sdk.py   # SDK (скопируйте из plugins/sdk/)
    ├── main.py         # ваш код
    └── web/            # UI плагина (опционально)
```

## manifest.json

```json
{
  "id": "my_plugin",
  "name": "Мой плагин",
  "version": "1.0.0",
  "description": "Что он делает",
  "has_ui": true,
  "port_hint": 8105,
  "config_secrets": ["api_key", "password"],
  "ui_pages": [
    {
      "title": "Мой плагин",
      "path": "/admin/plugins/my_plugin",
      "icon": "search"
    }
  ]
}
```

| Поле | Обязательное | Описание |
|---|---|---|
| `id` | да | Уникальный, латиница/цифры/`_`/`-` |
| `name` | да | Человекочитаемое название |
| `version` | да | Версия плагина |
| `description` | нет | Краткое описание |
| `has_ui` | нет | Есть ли web-UI на `/ui/` |
| `port_hint` | нет | Желаемый порт (ядро выдаст его, если свободен) |
| `config_secrets` | нет | Ключи конфига, которые маскировать при экспорте бэкапа |
| `ui_pages` | нет | Пункты меню в админке |
| `env` | нет | Дополнительные env-переменные для процесса |

## main.py — минимальный плагин

```python
from pathlib import Path
from plugin_sdk import PluginApp

app = PluginApp(
    "my_plugin",          # совпадает с manifest id
    "1.0.0",              # версия
    "Описание плагина",
    web_dir=Path(__file__).parent / "web",   # UI, опционально
    config={               # схема конфига — опционально
        "greeting": {"type": "str",    "default": "Привет!", "label": "Текст приветствия"},
        "count":    {"type": "int",    "default": 10,        "label": "Количество"},
        "api_key":  {"type": "secret", "default": "",        "label": "API-ключ"},
    },
)

@app.get("/hello")
async def hello():
    return {"message": app.config.get("greeting")}

if __name__ == "__main__":
    app.run()
```

## Конфиг плагина

Схема конфига — словарь `ключ → описание`. Типы:

| Тип | Описание | Приведение |
|---|---|---|
| `str` | Строка | `str(value)` |
| `int` | Целое | `int(value)` |
| `float` | Число | `float(value)` |
| `bool` | Флаг | `"1"/"true"/"yes"` → True |
| `secret` | Секрет | как строка, но маскируется в API и бэкапе |
| `json` | Любые данные | как есть |

Доступ из кода:

```python
app.config.get("count", 0)     # типизированное значение
app.config.all()               # весь конфиг
app.config.update({...})       # сохранить (используется API /config)
```

Конфиг хранится в `DATA_DIR/config.json` и переживает переустановку плагина.

### Секреты

- В GET `/config?masked=true` секреты возвращаются как `••••••••`
- При POST с маской значение **не затирается** — только если прислать новое
- В бэкапе настроек секреты маскируются (нужно указать `config_secrets` в manifest)

## Web-UI плагина

Папка `app/web/` монтируется на `/ui/`. Админка показывает её в iframe
через прокси ядра: `/api/plugins/{id}/proxy/ui/`.

Внутри iframe базовый URL прокси можно вычислить так:

```javascript
const parts = location.pathname.split('/')
const PROXY = '/' + parts.slice(0, parts.indexOf('proxy') + 1).join('/')
// → /api/plugins/my_plugin/proxy
```

Дальше обычные fetch-вызовы: `fetch(PROXY + '/hello')`.

Обмен с админкой через `postMessage`:

```javascript
// админка → плагин: тема
window.addEventListener('message', e => {
  if (e.data?.type === 'hm:theme') applyTheme(e.data.theme)
})

// плагин → админка: тост
window.parent.postMessage({ type: 'hm:toast', message: 'Сохранено' }, '*')
```

## Фоновые задачи

```python
@app.periodic(interval=60)     # каждые 60 секунд
async def check_something():
    app.logger.info("running...")
```

Или переопределите хуки жизненного цикла:

```python
async def on_startup(self):  # вместо декоратора — метод класса
    ...
```

> Обычный способ — функции, а не класс. Для хуков используйте
> `app.app.on_event("startup")` или оберните в `@asynccontextmanager` (SDK-класс):
> переопределите `on_startup`/`on_shutdown` подклассом `PluginApp`.

## Service discovery (вызовы между плагинами)

```python
import httpx
from plugin_sdk import plugin_url

async def call_other():
    url = await plugin_url("torrents")            # поднимет ошибку, если не запущен
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{url}/torrents")
        return r.json()
```

## Логирование

```python
app.logger.info("message")      # в plugin.log + консоль
app.logger.exception("oops")    # с traceback
```

Логи видны в админке: раздел **Логи** → ваш плагин.

## Обязательный API-контракт (ядро проверяет автоматически)

SDK регистрирует всё сам:

| Endpoint | Ответ |
|---|---|
| `GET /health` | `{"status":"ok","plugin_id":"…","version":"…","sdk":"4.0.0"}` |
| `GET /meta` | метаданные плагина |
| `GET /config` | `{"config":{...},"schema":{...}}` (+ `?masked=true`) |
| `POST /config` | принять и сохранить конфиг |
| `GET /capabilities` | `["config","ui"]` |

Не удаляйте их — иначе плагин не пройдёт healthcheck.

## Telegram-меню (бот-хаб)

Плагин `telegram_bot` — хаб: показывает в Telegram inline-меню всех плагинов.
Подключение своего раздела — 2 шага, никаких зависимостей от бота.

### 1. Объявите пункт в manifest.json

```json
{
  "id": "my_plugin",
  "bot_menu": {
    "title": "Мой модуль",
    "icon": "🎬",
    "order": 10
  }
}
```

- `title` — название в меню
- `icon` — эмодзи-иконка (необязательно)
- `order` — сортировка (меньше = выше, необязательно)

Плагин появляется в главном меню бота автоматически (хаб обновляет каталог каждые 30 сек).

### 2. Реализуйте POST /bot/callback

Хаб вызывает его при нажатии кнопки:

```python
@app.post("/bot/callback")
async def bot_callback(body: dict):
    action = body.get("action") or "main"
    if action == "main":
        return {
            "text": "🏠 <b>Главная моего модуля</b>\n\nПодробности…",
            "buttons": [
                {"text": "🔄 Статус", "action": "status"},
                {"text": "Сайт", "url": "https://example.com"},
            ],
        }
    if action == "status":
        return {"text": "✅ Всё работает", "buttons": [{"text": "◀ Назад", "action": "main"}]}
    return {"text": "Неизвестное действие"}
```

Формат ответа:

| Поле | Описание |
|---|---|
| `text` | Текст сообщения (можно HTML-разметку) |
| `buttons` | Кнопки: `{"text", "action"}` — callback, или `{"text", "url"}` — ссылка |

Кнопку «Главное меню» хаб добавляет вниз сам.

Тело запроса: `{"action": "...", "user_id": 123, "username": "nick"}`.
Для простых состояний храните экран в `action` (`main`, `status:cam1`, …) — хаб просто проксирует строку обратно при следующем нажатии.

### Команды, которые бот даёт пользователю

`/start` — главное меню · `/menu` — то же · `/status` — состояние модулей · `/help` — справка.
Ограничение доступа: поле `allowed_users` в конфиге бота (пусто = доступно всем).

## Сборка .hm

```bash
cd plugins/example
zip -r ../example.hm manifest.json requirements.txt app
# или на Windows:
# Compress-Archive manifest.json,requirements.txt,app -DestinationPath example.hm
```

Установка: **Плагины → Установить .hm** — ядро само распакует, поставит зависимости
и запустит.

## Локальная отладка плагина (без ядра)

```bash
cd app
PLUGIN_ID=my_plugin PLUGIN_PORT=8105 DATA_DIR=./dev_data \
python main.py
# → http://127.0.0.1:8105/health
```

## Чек-лист готового плагина

- [ ] `manifest.json`: id, name, version
- [ ] `config_secrets` для секретных полей конфига
- [ ] Уникальный `port_hint` (не пересекается с другими)
- [ ] Конфиг объявлен через схему SDK (а не самописный JSON)
- [ ] UI (если есть) использует PROXY-адрес и `hm:theme`
- [ ] Фоновые задачи — через `@app.periodic` с try/except
- [ ] Логирование через `app.logger`
- [ ] Проверено: install → running → stop → start → disable → enable
