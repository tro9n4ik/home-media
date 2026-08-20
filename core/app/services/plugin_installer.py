"""
PluginInstaller
===============
Отвечает за распаковку, валидацию, создание venv и установку зависимостей.
Не знает о runtime — только об установке.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import zipfile
import shutil
from pathlib import Path
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

REQUIRED_MANIFEST_KEYS = {"id", "name", "version"}

IS_WINDOWS = sys.platform == "win32"


def venv_dir(plugin_dir: Path) -> Path:
    return plugin_dir / ".venv"


def venv_bin_dir(plugin_dir: Path) -> Path:
    """Путь к bin/Scripts внутри venv плагина — кроссплатформенно."""
    if IS_WINDOWS:
        return venv_dir(plugin_dir) / "Scripts"
    return venv_dir(plugin_dir) / "bin"


def venv_python(plugin_dir: Path) -> Path:
    """Python из venv плагина — кроссплатформенно."""
    exe = "python.exe" if IS_WINDOWS else "python"
    return venv_bin_dir(plugin_dir) / exe


def venv_pip(plugin_dir: Path) -> Path:
    """pip из venv плагина — кроссплатформенно."""
    exe = "pip.exe" if IS_WINDOWS else "pip"
    return venv_bin_dir(plugin_dir) / exe


class PackageError(Exception):
    pass


class InstallError(Exception):
    pass


# ── Manifest validation ───────────────────────────────────────────────────────

def validate_manifest(manifest: dict[str, Any]) -> None:
    missing = REQUIRED_MANIFEST_KEYS - manifest.keys()
    if missing:
        raise PackageError(f"manifest.json: отсутствуют поля: {missing}")

    plugin_id = manifest["id"]
    if not plugin_id.replace("_", "").replace("-", "").isalnum():
        raise PackageError(f"id плагина содержит недопустимые символы: {plugin_id!r}")

    # port_hint опциональный — подсказка для registry, core всегда назначает порт сам
    if "port" in manifest:
        raise PackageError("Поле 'port' в manifest недопустимо. Используйте 'port_hint' для подсказки.")
    if "port_hint" in manifest:
        val = manifest["port_hint"]
        if not isinstance(val, int) or not (1024 <= val <= 65535):
            raise PackageError(f"port_hint должен быть int 1024–65535, получено: {val!r}")


# ── Unpack ────────────────────────────────────────────────────────────────────

def unpack(hm_path: Path, target_dir: Path) -> dict[str, Any]:
    """
    Распаковывает .hm (zip) в target_dir/plugin_id/.
    Сохраняет data/ плагина при переустановке.
    Возвращает manifest.
    """
    if not zipfile.is_zipfile(hm_path):
        raise PackageError("Файл не является корректным .hm (zip) архивом")

    with zipfile.ZipFile(hm_path, "r") as zf:
        names = zf.namelist()

        manifest_candidates = [n for n in names if Path(n).name == "manifest.json"]
        if not manifest_candidates:
            raise PackageError("manifest.json не найден в архиве")

        manifest_arc_path = sorted(manifest_candidates, key=len)[0]
        prefix = str(Path(manifest_arc_path).parent)
        prefix = "" if prefix == "." else prefix + "/"

        try:
            manifest = json.loads(zf.read(manifest_arc_path))
        except json.JSONDecodeError as e:
            raise PackageError(f"manifest.json невалидный JSON: {e}")

        validate_manifest(manifest)
        plugin_id = manifest["id"]
        dest = target_dir / plugin_id

        # Path traversal check
        for name in names:
            resolved = (dest / name.removeprefix(prefix)).resolve()
            if not str(resolved).startswith(str(dest.resolve())):
                raise PackageError(f"Path traversal: {name}")

        # Сохраняем data/ при переустановке
        saved_data = None
        if dest.exists():
            data_dir = dest / "data"
            if data_dir.exists():
                saved_data = target_dir / f".{plugin_id}_data_backup"
                if saved_data.exists():
                    shutil.rmtree(saved_data)
                shutil.copytree(data_dir, saved_data)
            shutil.rmtree(dest)

        dest.mkdir(parents=True)

        for member in zf.infolist():
            rel = member.filename.removeprefix(prefix)
            if not rel or rel.endswith("/"):
                continue
            out = dest / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(zf.read(member.filename))

        # Восстанавливаем data/
        if saved_data and saved_data.exists():
            restored = dest / "data"
            if restored.exists():
                shutil.rmtree(restored)
            shutil.copytree(saved_data, restored)
            shutil.rmtree(saved_data)

    logger.info("[%s] Unpacked to %s", plugin_id, dest)
    return manifest


# ── Venv & deps ───────────────────────────────────────────────────────────────

def setup_venv(plugin_dir: Path) -> None:
    """Создаёт venv если не существует."""
    venv = venv_dir(plugin_dir)
    if venv.exists():
        logger.info("[%s] venv already exists", plugin_dir.name)
        return
    logger.info("[%s] Creating venv", plugin_dir.name)
    subprocess.run(
        [sys.executable, "-m", "venv", str(venv)],
        check=True, timeout=60,
    )


def install_deps(plugin_dir: Path) -> None:
    """Устанавливает зависимости из requirements.txt."""
    req_file = plugin_dir / "requirements.txt"
    if not req_file.exists():
        logger.info("[%s] No requirements.txt", plugin_dir.name)
        return

    cfg = get_settings()
    pip = venv_pip(plugin_dir)

    if not pip.exists():
        raise InstallError(f"pip не найден: {pip}")

    logger.info("[%s] Installing requirements", plugin_dir.name)
    result = subprocess.run(
        [str(pip), "install", "-r", str(req_file),
         "--index-url", cfg.pip_index_url, "--quiet"],
        check=False, timeout=300, capture_output=True, text=True,
        env={**os.environ, "PIP_NO_CACHE_DIR": "1"},
    )
    if result.returncode != 0:
        logger.error("[%s] pip failed:\n%s\n%s", plugin_dir.name, result.stdout[-2000:], result.stderr[-2000:])
        raise InstallError(f"pip install failed (code {result.returncode}): {result.stderr[-500:]}")

    logger.info("[%s] Requirements installed", plugin_dir.name)


def verify_deps(plugin_dir: Path) -> None:
    """Проверяет что основные зависимости из requirements.txt установлены."""
    req_file = plugin_dir / "requirements.txt"
    if not req_file.exists():
        return
    python = venv_python(plugin_dir)
    if not python.exists():
        raise InstallError(f"python не найден в venv: {python}")
    # Простая проверка — импортируем первый пакет из requirements
    lines = [l.strip() for l in req_file.read_text().splitlines()
             if l.strip() and not l.startswith("#") and not l.startswith("-")]
    if not lines:
        return
    # Берём имя пакета без версии
    pkg = lines[0].split(">=")[0].split("==")[0].split("[")[0].strip().replace("-","_").lower()
    result = subprocess.run(
        [str(python), "-c", f"import {pkg}"],
        capture_output=True, timeout=10
    )
    if result.returncode != 0:
        raise InstallError(f"Зависимости не установлены — '{pkg}' не импортируется. Попробуйте переустановить плагин.")


def install(plugin_dir: Path, stop_fn=None) -> None:
    """Полная установка: venv + deps. stop_fn вызывается перед установкой."""
    if stop_fn:
        try:
            stop_fn()
        except Exception:
            pass

    setup_venv(plugin_dir)
    install_deps(plugin_dir)
    verify_deps(plugin_dir)
