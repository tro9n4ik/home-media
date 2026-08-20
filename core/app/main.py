from __future__ import annotations
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, UTC
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import select

from app.api import auth, plugins, system
from app.core.database import engine, get_db, SessionLocal
from app.models.plugin import Plugin
from app.services import plugin_registry, plugin_runtime
from app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
logger = logging.getLogger(__name__)

_admin = Path("app/web/static/admin")


async def _autostart_enabled_plugins() -> None:
    """
    Запускает все включённые плагины после старта ядра.
    Восстанавливает состояние «всё работает» после перезагрузки NAS/Docker.
    """
    async def _start_one(plugin_id: str) -> None:
        with SessionLocal() as db:
            p = db.scalar(select(Plugin).where(Plugin.plugin_id == plugin_id))
            if not p or not p.enabled:
                return
            try:
                p.status     = "starting"
                p.last_error = None
                db.commit()

                pid = plugin_runtime.start(p)
                p.pid = pid
                db.commit()

                healthy = await plugin_runtime.wait_healthy(p.plugin_id, p.assigned_port)
                if healthy:
                    p.status    = "running"
                    p.health_at = datetime.now(UTC)
                else:
                    p.status    = "failed"
                    p.last_error = f"Health check не пройден за {plugin_runtime.HEALTH_TIMEOUT}с"
                db.commit()
                logger.info("[autostart] %s → %s", plugin_id, p.status)
            except Exception as e:
                logger.error("[autostart] %s failed: %s", plugin_id, e)
                p.status     = "failed"
                p.last_error = str(e)[:1000]
                db.commit()

    with SessionLocal() as db:
        enabled = db.scalars(select(Plugin).where(Plugin.enabled == True)).all()  # noqa: E712
        targets = [(p, plugin_runtime.status(p)) for p in enabled]

    started = 0
    for plugin, real_status in targets:
        if real_status in ("running", "degraded", "starting"):
            logger.info("[autostart] %s уже активен (%s) — пропуск", plugin.plugin_id, real_status)
            continue
        started += 1
        asyncio.create_task(_start_one(plugin.plugin_id))

    logger.info("[autostart] Запускаю %d плагинов", started)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Восстанавливаем назначения портов из БД при старте ядра
    db = next(get_db())
    try:
        running_plugins = db.scalars(select(Plugin).where(Plugin.assigned_port.isnot(None))).all()
        for p in running_plugins:
            plugin_registry.restore_port(p.plugin_id, p.assigned_port)
            logger.info("[startup] Restored port %d → %s", p.assigned_port, p.plugin_id)
    finally:
        db.close()

    cfg = get_settings()
    if not cfg.secret_key:
        logger.warning("SECRET_KEY не задан — сессии не переживут перезапуск")

    # Автозапуск включённых плагинов после старта ядра
    asyncio.create_task(_autostart_enabled_plugins())

    yield

    # Graceful shutdown: останавливаем плагины
    with SessionLocal() as db:
        plugins = db.scalars(select(Plugin)).all()
        for p in plugins:
            if p.pid:
                try:
                    plugin_runtime.stop(p)
                    p.status = "stopped"
                    p.pid    = None
                except Exception as e:
                    logger.warning("[shutdown] %s: %s", p.plugin_id, e)
        db.commit()


app = FastAPI(
    title="Home.Media",
    version="4.0.0",
    docs_url="/api/docs",
    lifespan=lifespan,
)

app.include_router(auth.router)
app.include_router(plugins.router)
app.include_router(system.router)


@app.get("/")
def root():
    return RedirectResponse("/admin/", 302)


@app.get("/admin", include_in_schema=False)
def admin_redirect():
    return RedirectResponse("/admin/", 302)


@app.get("/admin/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    candidate = _admin / full_path
    if candidate.exists() and candidate.is_file():
        return FileResponse(str(candidate))
    index = _admin / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"detail": "Admin UI not built"}
