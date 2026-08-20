from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, UTC
from pathlib import Path

import psutil
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.plugin import Plugin
from app.services import plugin_registry, plugin_runtime
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/system", tags=["system"])

MASKED_VALUE = "••••••••"


@router.get("/health")
def health():
    return {"status": "ok", "version": "4.0.0"}


@router.get("/metrics")
def metrics(_=Depends(get_current_user)):
    vm = psutil.virtual_memory()
    du = psutil.disk_usage("/")
    return {
        "cpu_percent":   psutil.cpu_percent(interval=0.1),
        "ram_used_gb":   round(vm.used   / 1024**3, 2),
        "ram_total_gb":  round(vm.total  / 1024**3, 2),
        "ram_percent":   vm.percent,
        "disk_used_gb":  round(du.used   / 1024**3, 1),
        "disk_total_gb": round(du.total  / 1024**3, 1),
        "disk_percent":  du.percent,
    }


@router.get("/ui-pages")
def ui_pages(db: Session = Depends(get_db), _=Depends(get_current_user)):
    plugins = db.scalars(select(Plugin).where(Plugin.enabled == True)).all()
    pages = []
    for p in plugins:
        for page in p.ui_pages:
            pages.append({
                "plugin_id":   p.plugin_id,
                "plugin_name": p.name,
                "status":      p.status,
                **page,
            })
    return pages


@router.get("/registry")
def registry(_=Depends(get_current_user)):
    return plugin_registry.all_plugins()


# ── Logs ──────────────────────────────────────────────────────────────────────

@router.get("/logs/{plugin_id}")
def plugin_logs(
    plugin_id: str,
    lines: int = 200,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Логи конкретного плагина."""
    plugin = db.scalar(select(Plugin).where(Plugin.plugin_id == plugin_id))
    if not plugin:
        raise HTTPException(404, f"Плагин {plugin_id!r} не найден")
    return {"plugin_id": plugin_id, "logs": plugin_runtime.read_logs(plugin, lines)}


@router.get("/logs")
def all_logs(
    lines: int = 100,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Логи всех плагинов объединённые."""
    plugins = db.scalars(select(Plugin)).all()
    result = {}
    for p in plugins:
        result[p.plugin_id] = {
            "name":   p.name,
            "status": p.status,
            "logs":   plugin_runtime.read_logs(p, lines),
        }
    return result


# ── Settings backup / restore ─────────────────────────────────────────────────

@router.get("/settings/export")
def export_settings(
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """
    Экспортирует настройки всех плагинов в один JSON.
    Включает config.json, allowlist, commands каждого плагина.
    """
    cfg = get_settings()
    plugins_dir = Path(cfg.data_dir) / "plugins"
    plugins = db.scalars(select(Plugin)).all()

    backup = {
        "version":    "4.0.0",
        "exported_at": datetime.now(UTC).isoformat(),
        "plugins": {}
    }

    for plugin in plugins:
        plugin_data_dir = Path(plugin.data_path) / "data"
        plugin_backup = {
            "plugin_id": plugin.plugin_id,
            "name":      plugin.name,
            "version":   plugin.version,
            "files":     {}
        }

        # Читаем все JSON файлы из data/ плагина
        if plugin_data_dir.exists():
            # Ключи, которые маскируем при экспорте (из manifest плагина)
            secret_keys = set(plugin.manifest.get("config_secrets", []) or [])
            for json_file in plugin_data_dir.glob("*.json"):
                try:
                    content = json.loads(json_file.read_text())
                    # Маскируем секреты плагина
                    if isinstance(content, dict):
                        for key in secret_keys:
                            if content.get(key):
                                content[key] = MASKED_VALUE
                    plugin_backup["files"][json_file.name] = content
                except Exception:
                    pass

        backup["plugins"][plugin.plugin_id] = plugin_backup

    return JSONResponse(
        content=backup,
        headers={
            "Content-Disposition": f'attachment; filename="home-media-settings-{datetime.now().strftime("%Y%m%d-%H%M")}.json"'
        }
    )


@router.post("/settings/import")
async def import_settings(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """
    Импортирует настройки из backup JSON.
    Восстанавливает config.json, allowlist, commands для каждого плагина.
    После записи перезапускает плагины чтобы они подхватили новые настройки.
    """
    try:
        raw = await file.read()
        backup = json.loads(raw)
    except Exception as e:
        raise HTTPException(422, f"Невалидный JSON: {e}")

    if "plugins" not in backup or not isinstance(backup["plugins"], dict):
        raise HTTPException(422, "Неверный формат файла настроек — ожидается поле 'plugins'")

    restored  = []
    skipped   = []
    errors    = []
    restarted = []

    for plugin_id, plugin_backup in backup["plugins"].items():
        plugin = db.scalar(select(Plugin).where(Plugin.plugin_id == plugin_id))
        if not plugin:
            skipped.append(f"{plugin_id} (не установлен)")
            continue

        plugin_data_dir = Path(plugin.data_path) / "data"
        plugin_data_dir.mkdir(parents=True, exist_ok=True)

        files = plugin_backup.get("files", {})
        if not files:
            skipped.append(f"{plugin_id} (нет данных для восстановления)")
            continue

        plugin_ok = True
        for filename, file_content in files.items():
            if not filename.endswith(".json"):
                continue
            if not isinstance(file_content, (dict, list)):
                continue
            try:
                target = plugin_data_dir / filename

                if isinstance(file_content, dict):
                    # Мерджим с существующим конфигом
                    existing = {}
                    if target.exists():
                        try:
                            existing = json.loads(target.read_text())
                        except Exception:
                            pass

                    # Защита: не затираем реальные секреты маской из экспорта
                    merged = {**existing}
                    for k, v in file_content.items():
                        if isinstance(v, str) and (
                            v.startswith("...") or
                            v.startswith("••") or
                            (len(v) == 8 and set(v) == {"•"})
                        ):
                            # Это маска — оставляем текущее значение
                            continue
                        merged[k] = v
                else:
                    # Список (allowlist и т.п.) — заменяем полностью
                    merged = file_content

                target.write_text(json.dumps(merged, ensure_ascii=False, indent=2))
                logger.info("[import] %s/%s restored", plugin_id, filename)

            except Exception as e:
                logger.error("[import] error %s/%s: %s", plugin_id, filename, e)
                errors.append(f"{plugin_id}/{filename}: {e}")
                plugin_ok = False

        if plugin_ok:
            restored.append(plugin_id)
            # Перезапускаем плагин чтобы подхватил новые настройки
            if plugin.status == "running":
                try:
                    plugin_runtime.stop(plugin)
                    await asyncio.to_thread(plugin_runtime.start, plugin)
                    restarted.append(plugin_id)
                    logger.info("[import] restarted plugin %s", plugin_id)
                except Exception as e:
                    logger.warning("[import] restart failed %s: %s", plugin_id, e)

    result = {
        "status":    "ok" if not errors else "partial",
        "restored":  restored,
        "restarted": restarted,
        "skipped":   skipped,
        "errors":    errors,
        "message":   f"Восстановлено: {len(restored)}, перезапущено: {len(restarted)}, пропущено: {len(skipped)}",
    }
    if errors:
        result["message"] += f", ошибок: {len(errors)}"
    return result
