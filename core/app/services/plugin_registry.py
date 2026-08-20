"""
PluginRegistry
==============
Отвечает за:
- назначение портов из пула (core управляет портами, не manifest)
- runtime state (in-memory, синхронизируется с БД)
- service discovery — resolve_plugin(plugin_id) → URL
"""
from __future__ import annotations

import logging
from threading import Lock

logger = logging.getLogger(__name__)

# Пул портов для плагинов — core выдаёт из этого диапазона
PORT_RANGE_START = 8100
PORT_RANGE_END   = 8200
# Порты до 8100 зарезервированы: 8142 — ядро

_lock            = Lock()
_assigned_ports: dict[str, int] = {}   # plugin_id → port
_used_ports:     set[int]       = set()


def assign_port(plugin_id: str, preferred: int | None = None) -> int:
    """
    Назначает порт плагину из пула 8100–8200.
    preferred — подсказка (port_hint из manifest), используется если свободен.
    Назначение сохраняется — при рестарте тот же плагин получит тот же порт.
    """
    with _lock:
        # Уже назначен этому плагину
        if plugin_id in _assigned_ports:
            return _assigned_ports[plugin_id]

        # Пробуем preferred (из старого manifest для совместимости)
        if preferred and preferred not in _used_ports:
            _assigned_ports[plugin_id] = preferred
            _used_ports.add(preferred)
            logger.info("[registry] %s → port %d (preferred)", plugin_id, preferred)
            return preferred

        # Выдаём следующий свободный из пула
        for port in range(PORT_RANGE_START, PORT_RANGE_END):
            if port not in _used_ports:
                _assigned_ports[plugin_id] = port
                _used_ports.add(port)
                logger.info("[registry] %s → port %d (auto)", plugin_id, port)
                return port

        raise RuntimeError("Пул портов исчерпан (8100–8200)")


def release_port(plugin_id: str) -> None:
    """Освобождает порт при удалении плагина."""
    with _lock:
        port = _assigned_ports.pop(plugin_id, None)
        if port:
            _used_ports.discard(port)
            logger.info("[registry] %s released port %d", plugin_id, port)


def restore_port(plugin_id: str, port: int) -> None:
    """Восстанавливает назначение порта при старте ядра (из БД)."""
    with _lock:
        _assigned_ports[plugin_id] = port
        _used_ports.add(port)


def get_port(plugin_id: str) -> int | None:
    return _assigned_ports.get(plugin_id)


def plugin_url(plugin_id: str, port: int | None = None) -> str:
    """URL плагина для внутренних вызовов."""
    p = port or _assigned_ports.get(plugin_id)
    if not p:
        raise ValueError(f"Порт для плагина {plugin_id!r} не назначен")
    return f"http://127.0.0.1:{p}"


def all_plugins() -> dict[str, int]:
    """Все зарегистрированные плагины и их порты."""
    with _lock:
        return dict(_assigned_ports)
