"""Тесты plugin_registry.py — приоритет №3 из TODO_TESTS.md."""
import pytest

import app.services.plugin_registry as reg


# Глобальное состояние сбрасывается в conftest (фикстура _reset_registry)


def test_assign_port_preferred_free():
    assert reg.assign_port("a", preferred=8500) == 8500
    # повторный запрос того же плагина — тот же порт
    assert reg.assign_port("a") == 8500


def test_assign_port_auto_sequential_no_collisions():
    ports = {reg.assign_port(f"p{i}") for i in range(10)}
    assert len(ports) == 10
    assert min(ports) >= reg.PORT_RANGE_START
    assert max(ports) < reg.PORT_RANGE_END


def test_assign_port_preferred_taken():
    reg.assign_port("a", preferred=8100)
    b = reg.assign_port("b", preferred=8100)  # занят → авто
    assert b != 8100
    assert b >= reg.PORT_RANGE_START


def test_restore_port_keeps_assignment():
    reg.restore_port("existing", 8105)
    # тот же плагин получает восстановленный порт
    assert reg.get_port("existing") == 8105
    # другой плагин не может занять восстановленный порт
    other = reg.assign_port("newbie", preferred=8105)
    assert other != 8105


def test_pool_exhausted_raises_runtime_error(monkeypatch):
    monkeypatch.setattr(reg, "PORT_RANGE_START", 9100)
    monkeypatch.setattr(reg, "PORT_RANGE_END", 9104)  # ровно 4 порта
    for i in range(4):
        reg.assign_port(f"p{i}")
    with pytest.raises(RuntimeError, match="исчерпан"):
        reg.assign_port("p4")


def test_release_port():
    p = reg.assign_port("a", preferred=8510)
    reg.release_port("a")
    assert reg.get_port("a") is None
    # порт снова доступен другому плагину
    assert reg.assign_port("b", preferred=8510) == 8510


def test_all_plugins_snapshot():
    reg.assign_port("a", preferred=8520)
    reg.assign_port("b", preferred=8521)
    snap = reg.all_plugins()
    assert snap == {"a": 8520, "b": 8521}
    # мутация снапшота не ломает внутреннее состояние
    snap["a"] = 1
    assert reg.get_port("a") == 8520


def test_plugin_url():
    reg.assign_port("a", preferred=8530)
    assert reg.plugin_url("a") == "http://127.0.0.1:8530"
    assert reg.plugin_url("a", port=None) == "http://127.0.0.1:8530"


def test_plugin_url_missing_port():
    with pytest.raises(ValueError, match="не назначен"):
        reg.plugin_url("ghost")