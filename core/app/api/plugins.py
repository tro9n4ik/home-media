from __future__ import annotations

import asyncio
import logging
import tempfile
from datetime import datetime, UTC
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db, SessionLocal
from app.core.security import get_current_user
from app.models.plugin import Plugin
from app.services import plugin_installer, plugin_runtime, plugin_registry, plugin_proxy
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/plugins", tags=["plugins"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class PluginOut(BaseModel):
    plugin_id:     str
    name:          str
    version:       str
    description:   str
    status:        str
    enabled:       bool
    assigned_port: int | None
    last_error:    str | None = None
    ui_pages:      list[dict]
    model_config = {"from_attributes": True}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get(plugin_id: str, db: Session) -> Plugin:
    p = db.scalar(select(Plugin).where(Plugin.plugin_id == plugin_id))
    if not p:
        raise HTTPException(404, f"Плагин {plugin_id!r} не найден")
    return p


def _sync_status(plugin: Plugin, db: Session) -> None:
    if plugin.status in ("installing",):
        return
    new_status = plugin_runtime.status(plugin)
    if new_status != plugin.status:
        plugin.status = new_status
        db.commit()


async def _start_and_watch(plugin: Plugin, db: Session) -> None:
    try:
        plugin.status     = "starting"
        plugin.started_at = datetime.now(UTC)
        plugin.last_error = None
        db.commit()

        pid  = plugin_runtime.start(plugin)
        plugin.pid = pid
        db.commit()

        port    = plugin.assigned_port
        healthy = await plugin_runtime.wait_healthy(plugin.plugin_id, port)

        if healthy:
            plugin.status    = "running"
            plugin.health_at = datetime.now(UTC)
        else:
            current = plugin_runtime.status(plugin)
            plugin.status = current if current != "stopped" else "failed"
            if plugin.status == "failed":
                plugin.last_error = f"Health check не пройден за {plugin_runtime.HEALTH_TIMEOUT}с — проверьте логи плагина"

        db.commit()
        logger.info("[%s] status=%s", plugin.plugin_id, plugin.status)

    except Exception as e:
        logger.error("[%s] start error: %s", plugin.plugin_id, e)
        plugin.status = "failed"
        plugin.last_error = str(e)[:1000]
        db.commit()


# ── Install ───────────────────────────────────────────────────────────────────

@router.post("/install", response_model=PluginOut)
async def install_plugin(
    background_tasks: BackgroundTasks,
    file=File(...),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    cfg = get_settings()
    plugins_dir = Path(cfg.data_dir) / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(suffix=".hm", delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)

    try:
        manifest = plugin_installer.unpack(tmp_path, plugins_dir)
    except plugin_installer.PackageError as e:
        raise HTTPException(422, str(e))
    finally:
        tmp_path.unlink(missing_ok=True)

    plugin_id     = manifest["id"]
    data_path     = str(plugins_dir / plugin_id)
    assigned_port = plugin_registry.assign_port(plugin_id, manifest.get("port_hint"))

    existing = db.scalar(select(Plugin).where(Plugin.plugin_id == plugin_id))
    if existing:
        if existing.status == "running":
            plugin_runtime.stop(existing)
        existing.name          = manifest["name"]
        existing.version       = manifest["version"]
        existing.description   = manifest.get("description", "")
        existing.manifest      = manifest
        existing.data_path     = data_path
        existing.assigned_port = assigned_port
        existing.status        = "installing"
        plugin = existing
    else:
        plugin = Plugin(
            plugin_id=plugin_id,
            name=manifest["name"],
            version=manifest["version"],
            description=manifest.get("description", ""),
            manifest=manifest,
            data_path=data_path,
            assigned_port=assigned_port,
            status="installing",
        )
        db.add(plugin)

    db.commit()
    db.refresh(plugin)

    async def _install_and_start():
        # Используем новую сессию — background task живёт вне request context
        with SessionLocal() as bg_db:
            bg_plugin = bg_db.scalar(select(Plugin).where(Plugin.plugin_id == plugin_id))
            if not bg_plugin:
                return
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None,
                    lambda: plugin_installer.install(
                        Path(data_path),
                        stop_fn=lambda: plugin_runtime.stop(bg_plugin)
                    )
                )
                # installed — транзитное состояние, сразу стартуем
                bg_plugin.status = "starting"
                bg_plugin.last_error = None
                bg_db.commit()
                await _start_and_watch(bg_plugin, bg_db)
            except Exception as e:
                logger.error("[%s] install error: %s", plugin_id, e)
                bg_plugin.status = "failed"
                bg_plugin.last_error = str(e)[:1000]
                bg_db.commit()

    background_tasks.add_task(_install_and_start)
    return plugin


# ── List / Get ────────────────────────────────────────────────────────────────

@router.get("", response_model=list[PluginOut])
def list_plugins(db: Session = Depends(get_db), _=Depends(get_current_user)):
    plugins = db.scalars(select(Plugin)).all()
    for p in plugins:
        _sync_status(p, db)
    return plugins


@router.get("/{plugin_id}", response_model=PluginOut)
def get_plugin(plugin_id: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    p = _get(plugin_id, db)
    _sync_status(p, db)
    return p


# ── Start / Stop / Restart ────────────────────────────────────────────────────

@router.post("/{plugin_id}/start")
async def start_plugin(
    plugin_id: str,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    plugin = _get(plugin_id, db)
    if plugin.status == "running":
        return {"status": "already_running"}
    if not plugin.assigned_port:
        plugin.assigned_port = plugin_registry.assign_port(plugin_id)
        db.commit()
    await _start_and_watch(plugin, db)
    return {"status": plugin.status}


@router.post("/{plugin_id}/stop")
def stop_plugin(plugin_id: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    plugin = _get(plugin_id, db)
    plugin_runtime.stop(plugin)
    plugin.status = "stopped"
    plugin.pid    = None
    db.commit()
    return {"status": "stopped"}


@router.post("/{plugin_id}/enable")
def enable_plugin(plugin_id: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Включает плагин — автозапуск при старте ядра."""
    plugin = _get(plugin_id, db)
    plugin.enabled = True
    db.commit()
    return {"status": "enabled", "enabled": True}


@router.post("/{plugin_id}/disable")
def disable_plugin(plugin_id: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Отключает плагин: останавливает и убирает из автозапуска."""
    plugin = _get(plugin_id, db)
    plugin_runtime.stop(plugin)
    plugin.status  = "stopped"
    plugin.pid     = None
    plugin.enabled = False
    db.commit()
    return {"status": "disabled", "enabled": False}


@router.post("/{plugin_id}/restart")
async def restart_plugin(plugin_id: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    plugin = _get(plugin_id, db)
    plugin_runtime.stop(plugin)
    plugin.status = "stopped"
    plugin.pid    = None
    db.commit()
    await _start_and_watch(plugin, db)
    return {"status": plugin.status}


# ── Delete ────────────────────────────────────────────────────────────────────

@router.delete("/{plugin_id}")
def delete_plugin(plugin_id: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    import shutil
    plugin = _get(plugin_id, db)
    plugin_runtime.stop(plugin)
    plugin_registry.release_port(plugin_id)
    if plugin.data_path and Path(plugin.data_path).exists():
        shutil.rmtree(plugin.data_path, ignore_errors=True)
    db.delete(plugin)
    db.commit()
    return {"status": "deleted"}


# ── Logs ──────────────────────────────────────────────────────────────────────

@router.get("/{plugin_id}/logs")
def get_logs(plugin_id: str, lines: int = 100, db: Session = Depends(get_db), _=Depends(get_current_user)):
    plugin = _get(plugin_id, db)
    return {"logs": plugin_runtime.read_logs(plugin, lines)}


# ── Service discovery ─────────────────────────────────────────────────────────

@router.get("/{plugin_id}/connection")
def get_connection(plugin_id: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Service discovery — возвращает URL плагина по его ID."""
    plugin = _get(plugin_id, db)
    if not plugin.assigned_port:
        raise HTTPException(503, f"Порт для {plugin_id!r} не назначен")
    return {
        "plugin_id": plugin_id,
        "url":       f"http://127.0.0.1:{plugin.assigned_port}",
        "port":      plugin.assigned_port,
        "status":    plugin.status,
    }


@router.get("/{plugin_id}/internal/connection")
def get_connection_internal(plugin_id: str, db: Session = Depends(get_db)):
    """
    Service discovery для межплагинного общения — без авторизации.
    Доступен только изнутри контейнера (localhost).
    """
    plugin = _get(plugin_id, db)
    if not plugin.assigned_port:
        raise HTTPException(503, f"Порт для {plugin_id!r} не назначен")
    return {
        "plugin_id": plugin_id,
        "url":       f"http://127.0.0.1:{plugin.assigned_port}",
        "port":      plugin.assigned_port,
        "status":    plugin.status,
    }


# ── Internal catalog (для плагина-хаба) ───────────────────────────────────────

@router.get("/internal/plugins")
def internal_catalog(db: Session = Depends(get_db)):
    """
    Каталог всех плагинов для межплагинного общения — без авторизации.
    Используется плагином-хабом (telegram_bot) для сборки меню.
    Доступен только изнутри контейнера (localhost).
    """
    plugins = db.scalars(select(Plugin)).all()
    catalog = []
    for p in plugins:
        if not p.assigned_port or p.status not in ("running", "degraded"):
            continue
        catalog.append({
            "plugin_id":  p.plugin_id,
            "name":       p.name,
            "version":    p.version,
            "status":     p.status,
            "url":        f"http://127.0.0.1:{p.assigned_port}",
            "port":       p.assigned_port,
            "manifest":   p.manifest,
        })
    return {"plugins": catalog}


# ── Proxy ─────────────────────────────────────────────────────────────────────

@router.api_route(
    "/{plugin_id}/proxy/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    include_in_schema=False,
)
async def proxy_to_plugin(
    plugin_id: str, path: str, request: Request,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    plugin = _get(plugin_id, db)
    if plugin.status not in ("running", "degraded"):
        raise HTTPException(503, f"Плагин {plugin_id!r} не запущен (статус: {plugin.status})")
    return await plugin_proxy.proxy(plugin, request, path)
