"""
PluginRuntime
=============
Отвечает за lifecycle процессов плагинов:
- start / stop / restart
- health-based статусы (starting → running / failed)
- чтение логов
- graceful shutdown (SIGTERM → wait → SIGKILL)
- кросплатформенно: Linux (Docker) и Windows (разработка)
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime, UTC
from pathlib import Path

import httpx
import psutil

from app.config import get_settings
from app.models.plugin import Plugin
from app.services import plugin_installer, plugin_registry

logger = logging.getLogger(__name__)

HEALTH_TIMEOUT    = 30   # секунд ждём /health после старта
HEALTH_INTERVAL   = 1.0  # пауза между попытками
STOP_GRACEFUL     = 5    # секунд на graceful shutdown

IS_WINDOWS = sys.platform == "win32"


def _pid_file(plugin_id: str) -> Path:
    cfg = get_settings()
    return Path(cfg.data_dir) / "plugins" / plugin_id / ".pid"


def _wait_port_free(port: int, timeout: float = 8.0) -> bool:
    """Ждёт пока порт не освободится. Возвращает True если освободился."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("0.0.0.0", port))
                return True  # порт свободен
        except OSError:
            time.sleep(0.3)
    return False


def _is_port_free(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("0.0.0.0", port))
            return True
    except OSError:
        return False


def _log_file(plugin_dir: Path) -> Path:
    return plugin_dir / "plugin.log"


def _pid_exists(pid: int) -> bool:
    """Кроссплатформенная проверка существования процесса."""
    try:
        if IS_WINDOWS:
            return psutil.pid_exists(pid)
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# ── Start ─────────────────────────────────────────────────────────────────────

def start(plugin: Plugin) -> int:
    """
    Запускает плагин. Возвращает PID.
    НЕ ждёт /health — это делает wait_healthy() асинхронно.
    """
    plugin_dir = Path(plugin.data_path)
    python     = plugin_installer.venv_python(plugin_dir)

    if not python.exists():
        plugin_installer.install(plugin_dir)

    entry = plugin_dir / "app" / "main.py"
    if not entry.exists():
        raise RuntimeError(f"Точка входа не найдена: {entry}")

    port = plugin.assigned_port or plugin_registry.get_port(plugin.plugin_id)
    if not port:
        raise RuntimeError(f"Порт не назначен для {plugin.plugin_id}")

    cfg = get_settings()
    env = {
        **os.environ,
        "PLUGIN_ID":        plugin.plugin_id,
        "PLUGIN_PORT":      str(port),
        "CORE_URL":         cfg.core_internal_url,
        "DATA_DIR":         str(plugin_dir / "data"),
        "PYTHONUNBUFFERED": "1",
        "PYTHONPATH":       str(plugin_dir),
        **plugin.manifest.get("env", {}),
    }

    (plugin_dir / "data").mkdir(parents=True, exist_ok=True)

    log_path = _log_file(plugin_dir)
    log_file = open(log_path, "a")

    # Проверяем что порт свободен — если нет, убиваем занявший его процесс
    if not _is_port_free(port):
        logger.warning("[%s] Port %d busy before start — killing occupant", plugin.plugin_id, port)
        _kill_port(port)
        if not _wait_port_free(port, timeout=5.0):
            raise RuntimeError(f"Порт {port} занят и не освобождается")

    popen_kwargs = dict(
        cwd=str(plugin_dir),
        env=env,
        stdout=log_file,
        stderr=log_file,
    )
    if IS_WINDOWS:
        # Windows: новая группа процессов для аккуратного завершения дерева
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True

    proc = subprocess.Popen([str(python), str(entry)], **popen_kwargs)

    _pid_file(plugin.plugin_id).write_text(str(proc.pid))
    logger.info("[%s] Started PID=%d port=%d", plugin.plugin_id, proc.pid, port)
    return proc.pid


def _kill_port(port: int) -> None:
    """Убивает процесс занимающий порт. Кроссплатформенно через psutil."""
    killed = False
    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.laddr and conn.laddr.port == port and conn.pid:
                try:
                    proc = psutil.Process(conn.pid)
                    logger.info("Killed PID=%d holding port %d", conn.pid, port)
                    proc.kill()
                    killed = True
                except psutil.Error:
                    pass
    except Exception as e:
        logger.debug("_kill_port: %s", e)

    if killed:
        time.sleep(0.8)


# ── Health check ──────────────────────────────────────────────────────────────

async def wait_healthy(plugin_id: str, port: int, timeout: int = HEALTH_TIMEOUT) -> bool:
    """
    Ждёт пока /health не ответит ok.
    Возвращает True если дождались, False если timeout.
    """
    url = f"http://127.0.0.1:{port}/health"
    deadline = time.time() + timeout

    async with httpx.AsyncClient(timeout=2.0) as client:
        while time.time() < deadline:
            try:
                r = await client.get(url)
                if r.status_code == 200:
                    data = r.json()
                    if data.get("status") in ("ok", "healthy"):
                        logger.info("[%s] Health OK", plugin_id)
                        return True
            except Exception:
                pass
            await asyncio.sleep(HEALTH_INTERVAL)

    logger.warning("[%s] Health timeout after %ds", plugin_id, timeout)
    return False


def check_health_sync(plugin_id: str, port: int) -> bool:
    """Синхронная проверка /health для status()."""
    try:
        import urllib.request
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/health", timeout=2
        ) as r:
            import json
            data = json.loads(r.read())
            return data.get("status") in ("ok", "healthy")
    except Exception:
        return False


# ── Status ────────────────────────────────────────────────────────────────────

def status(plugin: Plugin) -> str:
    """
    Определяет актуальный статус плагина.
    running   — PID жив И /health отвечает
    degraded  — PID жив НО /health не отвечает
    failed    — PID мёртв (файл есть но процесс не существует)
    stopped   — pid-файла нет
    """
    pid_file = _pid_file(plugin.plugin_id)

    if not pid_file.exists():
        return "stopped"

    try:
        pid = int(pid_file.read_text().strip())
    except (ValueError, OSError):
        pid_file.unlink(missing_ok=True)
        return "failed"

    if not _pid_exists(pid):
        pid_file.unlink(missing_ok=True)
        return "failed"

    # Процесс жив — проверяем health
    port = plugin.assigned_port or plugin_registry.get_port(plugin.plugin_id)
    if port and check_health_sync(plugin.plugin_id, port):
        return "running"
    else:
        return "degraded"


# ── Stop ──────────────────────────────────────────────────────────────────────

def stop(plugin: Plugin) -> None:
    """
    Graceful shutdown:
    1. SIGTERM / terminate() к процессу (и его дереву на Linux)
    2. Ждём STOP_GRACEFUL секунд
    3. SIGKILL если не завершился
    """
    pid_file = _pid_file(plugin.plugin_id)

    if not pid_file.exists():
        return

    try:
        pid = int(pid_file.read_text().strip())
    except (ValueError, OSError):
        pid_file.unlink(missing_ok=True)
        return

    if not _pid_exists(pid):
        pid_file.unlink(missing_ok=True)
        return

    try:
        proc = psutil.Process(pid)
    except psutil.Error:
        pid_file.unlink(missing_ok=True)
        return

    # SIGTERM (на Windows terminate ≈ принудительное завершение)
    try:
        if IS_WINDOWS:
            proc.terminate()
        else:
            os.kill(pid, signal.SIGTERM)
        logger.info("[%s] SIGTERM → PID=%d", plugin.plugin_id, pid)
    except psutil.Error as e:
        logger.warning("[%s] terminate failed: %s", plugin.plugin_id, e)

    # Ждём graceful
    deadline = time.time() + STOP_GRACEFUL
    while time.time() < deadline:
        if not _pid_exists(pid):
            logger.info("[%s] Stopped gracefully", plugin.plugin_id)
            pid_file.unlink(missing_ok=True)
            return
        time.sleep(0.2)

    # SIGKILL
    try:
        children = proc.children(recursive=True)
        for child in children:
            try:
                child.kill()
            except psutil.Error:
                pass
        proc.kill()
        logger.warning("[%s] SIGKILL sent", plugin.plugin_id)
    except psutil.Error:
        pass
    finally:
        pid_file.unlink(missing_ok=True)

    # Ждём освобождения порта — чтобы следующий старт не получил EADDRINUSE
    port = plugin.assigned_port
    if port:
        if not _wait_port_free(port, timeout=8.0):
            logger.warning("[%s] Port %d still busy after stop", plugin.plugin_id, port)


# ── Logs ──────────────────────────────────────────────────────────────────────

def read_logs(plugin: Plugin, lines: int = 100) -> list[str]:
    """Читает последние N строк из лога плагина."""
    log_path = _log_file(Path(plugin.data_path))
    if not log_path.exists():
        return []
    try:
        all_lines = log_path.read_text(errors="replace").splitlines()
        return all_lines[-lines:]
    except Exception:
        return []
