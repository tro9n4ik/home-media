"""
Home.Media Plugin SDK
=====================
Базовый SDK для всех плагинов Home.Media v4.

Возможности:
- PluginApp — FastAPI-приложение с обязательными endpoint'ами (/health, /meta, /config, /capabilities)
- Декларативный конфиг: типы, дефолты, секреты — валидируется и сохраняется в DATA_DIR/config.json
- Маскирование секретов при чтении конфига через API
- Фоновые периодические задачи через @app.periodic
- Service discovery: resolve_plugin() / plugin_url()
- Логирование в stdout (ядро перенаправляет в plugin.log) и в файл

Использование:
    from plugin_sdk import PluginApp

    app = PluginApp(
        "my_plugin", "1.0.0", "Мой плагин",
        web_dir=Path(__file__).parent / "web",
        config={
            "api_key": {"type": "secret", "default": "", "label": "API-ключ"},
            "timeout": {"type": "int",    "default": 30, "label": "Таймаут, сек"},
        },
    )

    @app.periodic(interval=60)
    async def check():
        ...

    if __name__ == "__main__":
        app.run()
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

SDK_VERSION = "4.0.0"


# ── Runtime env (передаётся ядром при запуске плагина) ──────────────────────

PLUGIN_ID   = os.getenv("PLUGIN_ID",   "unknown")
PLUGIN_PORT = int(os.getenv("PLUGIN_PORT", "8100"))
CORE_URL    = os.getenv("CORE_URL",    "http://127.0.0.1:8142")
DATA_DIR    = Path(os.getenv("DATA_DIR", "/plugin/data"))


# ── Логирование ──────────────────────────────────────────────────────────────

def plugin_logger(plugin_id: str | None = None) -> logging.Logger:
    """Логгер плагина: stdout (→ plugin.log в ядре) + DATA_DIR/plugin.log."""
    pid = plugin_id or PLUGIN_ID
    logger = logging.getLogger(f"hm.{pid}")
    if logger.handlers:
        return logger

    fmt = logging.Formatter(f"%(asctime)s %(levelname)s  [{pid}]  %(message)s")

    stdout = logging.StreamHandler()
    stdout.setFormatter(fmt)

    file_handler = None
    try:
        log_file = DATA_DIR / "plugin.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        file_handler = fh
    except Exception:
        pass

    logger.setLevel(logging.INFO)
    logger.addHandler(stdout)
    if file_handler:
        logger.addHandler(file_handler)
    return logger


# ── Service discovery ─────────────────────────────────────────────────────────

async def resolve_plugin(plugin_id: str) -> dict:
    """
    Получает connection info плагина через core registry.
    Возвращает {"url": "http://...", "port": N, "status": "running"}
    """
    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.get(f"{CORE_URL}/api/plugins/{plugin_id}/internal/connection")
        if r.status_code != 200:
            raise RuntimeError(f"Плагин {plugin_id!r} не найден в registry (статус {r.status_code})")
        return r.json()


async def plugin_url(plugin_id: str) -> str:
    """Возвращает базовый URL плагина (для межплагинных вызовов)."""
    info = await resolve_plugin(plugin_id)
    if info.get("status") not in ("running", "degraded"):
        raise RuntimeError(f"Плагин {plugin_id!r} не запущен (статус: {info.get('status')})")
    return info["url"]


# ── Health ответ ──────────────────────────────────────────────────────────────

def health_response(plugin_id: str, version: str, extra: dict | None = None) -> dict:
    """Стандартный ответ /health по контракту платформы."""
    return {
        "status":    "ok",
        "plugin_id": plugin_id,
        "version":   version,
        "sdk":       SDK_VERSION,
        **(extra or {}),
    }


# ── Конфиг ────────────────────────────────────────────────────────────────────
# Схема конфига — словарь:
#   ключ: {"type": "str"|"int"|"float"|"bool"|"secret"|"json",
#          "default": ..., "label": "Человекочитаемое имя"}

_CONFIG_FILE = DATA_DIR / "config.json"

MASK = "••••••••"


def _coerce(value: Any, cfg_type: str) -> Any:
    if value is None:
        return None
    if cfg_type == "str":
        return str(value)
    if cfg_type == "int":
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    if cfg_type == "float":
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if cfg_type == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on", "да")
        return bool(value)
    return value  # secret, json — как есть


class Config:
    """Типизированный доступ к конфигу плагина с дефолтами из схемы."""

    def __init__(self, schema: dict[str, dict] | None):
        self.schema = schema or {}
        self._values: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        saved: dict = {}
        if _CONFIG_FILE.exists():
            try:
                saved = json.loads(_CONFIG_FILE.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                saved = {}
        for key, spec in self.schema.items():
            default = spec.get("default")
            self._values[key] = _coerce(saved.get(key, default), spec.get("type", "str"))

    def _save(self) -> None:
        try:
            _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            _CONFIG_FILE.write_text(
                json.dumps(self._values, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)

    def all(self, mask_secrets: bool = False) -> dict[str, Any]:
        if not mask_secrets:
            return dict(self._values)
        out = {}
        for key, value in self._values.items():
            spec = self.schema.get(key, {})
            out[key] = MASK if spec.get("type") == "secret" and value else value
        return out

    def update(self, data: dict[str, Any]) -> dict[str, Any]:
        """Обновляет конфиг: типизирует, игнорирует маски, сохраняет. Возвращает новый конфиг."""
        for key, value in data.items():
            spec = self.schema.get(key)
            if spec is None:
                continue  # неизвестные ключи игнорируем
            if isinstance(value, str) and value == MASK and spec.get("type") == "secret":
                continue  # маска — не меняем секрет
            coerced = _coerce(value, spec.get("type", "str"))
            if coerced is None and value not in (None, ""):
                raise ValueError(f"Поле «{spec.get('label', key)}» имеет неверный тип")
            self._values[key] = coerced
        self._save()
        return dict(self._values)


# ── PluginApp ─────────────────────────────────────────────────────────────────

class PluginApp:
    """
    Базовый класс плагина Home.Media.

    Args:
        plugin_id:   ID плагина (из manifest)
        version:     Версия плагина
        description: Описание плагина
        web_dir:     Папка с web-UI (монтируется на /ui/)
        config:      Схема конфига — см. Config
    """

    def __init__(
        self,
        plugin_id:   str,
        version:     str,
        description: str = "",
        web_dir:     Path | None = None,
        config:      dict[str, dict] | None = None,
    ):
        self.plugin_id   = plugin_id
        self.version     = version
        self.description = description
        self.logger      = plugin_logger(plugin_id)
        self.config      = Config(config)
        self._config_schema = config or {}
        self._periodic: list[tuple[int, Callable[[], Awaitable[Any]]]] = []

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            self.logger.info("Plugin %s v%s started on port %d", plugin_id, version, PLUGIN_PORT)
            self._background_tasks = []
            for interval, fn in self._periodic:
                self._background_tasks.append(
                    asyncio.create_task(self._periodic_loop(interval, fn))
                )
            await self.on_startup()
            yield
            await self.on_shutdown()
            for task in self._background_tasks:
                task.cancel()

        self.app = FastAPI(title=plugin_id, version=version, description=description, lifespan=lifespan)
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

        self._has_ui = False
        if web_dir is not None:
            if web_dir.exists() and web_dir.is_dir():
                self.app.mount("/ui", StaticFiles(directory=str(web_dir), html=True), name="ui")
                self._has_ui = True
                self.logger.info("Mounted web UI from %s", web_dir)
            else:
                self.logger.warning("web_dir указан но не существует: %s", web_dir)

        # UI-страницы плагина не должны кэшироваться браузером,
        # иначе после обновления плагина остаётся старая версия страницы.
        @self.app.middleware("http")
        async def _no_cache_ui(request: Request, call_next):
            response = await call_next(request)
            if request.url.path.startswith("/ui"):
                response.headers["Cache-Control"] = "no-store"
            return response

        self._register_base_routes()

    def periodic(self, interval: int):
        """
        Декоратор для фоновой периодической задачи:
            @app.periodic(interval=60)
            async def check():
                ...
        """
        def deco(fn: Callable[[], Awaitable[Any]]):
            self._periodic.append((interval, fn))
            return fn
        return deco

    async def _periodic_loop(self, interval: int, fn: Callable[[], Awaitable[Any]]):
        while True:
            try:
                await asyncio.sleep(interval)
                await fn()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.exception("Periodic task %s failed: %s", getattr(fn, "__name__", fn), e)

    def _register_base_routes(self):
        @self.app.get("/health")
        def _health():
            return health_response(self.plugin_id, self.version)

        @self.app.get("/meta")
        def _meta():
            return {
                "plugin_id":   self.plugin_id,
                "version":     self.version,
                "description": self.description,
                "sdk":         SDK_VERSION,
            }

        @self.app.get("/config")
        def _get_config(masked: bool = False):
            return {
                "config": self.config.all(mask_secrets=masked),
                "schema": self._config_schema,
            }

        @self.app.post("/config")
        def _post_config(body: dict):
            try:
                updated = self.config.update(body)
            except ValueError as e:
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail": str(e)}, status_code=422)
            self.logger.info("Config updated")
            return {"status": "ok", "config": updated}

        @self.app.get("/capabilities")
        def _capabilities():
            caps = ["config"]
            if self._has_ui:
                caps.append("ui")
            return {"capabilities": caps}

    async def on_startup(self):
        """Переопределить для кода при старте."""
        pass

    async def on_shutdown(self):
        """Переопределить для кода при остановке."""
        pass

    @property
    def router(self):
        return self.app.router

    # Делегирование декораторов маршрутов FastAPI:
    # @app.get("/path"), @app.post("/path") и т.д.
    def get(self, *args, **kwargs):
        return self.app.get(*args, **kwargs)

    def post(self, *args, **kwargs):
        return self.app.post(*args, **kwargs)

    def put(self, *args, **kwargs):
        return self.app.put(*args, **kwargs)

    def patch(self, *args, **kwargs):
        return self.app.patch(*args, **kwargs)

    def delete(self, *args, **kwargs):
        return self.app.delete(*args, **kwargs)

    def run(self):
        import uvicorn
        uvicorn.run(self.app, host="0.0.0.0", port=PLUGIN_PORT)
