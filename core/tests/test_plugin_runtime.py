"""Тесты plugin_runtime.py — приоритет №2 из TODO_TESTS.md."""
import asyncio
import signal
import socket
import time
from types import SimpleNamespace

import pytest
import psutil

from app.services import plugin_runtime as rt


def make_plugin(**kw) -> SimpleNamespace:
    base = dict(
        plugin_id="demo",
        assigned_port=8123,
        data_path="/tmp/whatever/demo",
        manifest={},
    )
    base.update(kw)
    return SimpleNamespace(**base)


class FakeResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"status": "ok"}

    def json(self):
        return self._payload


class FakeHttpClient:
    """Контекстный httpx.AsyncClient-заменитель с очередью ответов."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        self.calls += 1
        if self._responses:
            return self._responses.pop(0)
        return FakeResponse(200, {"status": "starting"})


@pytest.fixture
def pid_file(tmp_path):
    from pathlib import Path
    p = tmp_path / "demo.pid"
    yield p
    if p.exists():
        p.unlink(missing_ok=True)


@pytest.fixture
def patch_status_deps(monkeypatch, pid_file):
    """Ставит status()-зависимости на tmp и controlled-поведение по умолчанию."""
    monkeypatch.setattr(rt, "_pid_file", lambda plugin_id: pid_file)
    monkeypatch.setattr(rt, "_pid_exists", lambda pid: False)
    monkeypatch.setattr(rt, "check_health_sync", lambda plugin_id, port: False)


# ── status() ──────────────────────────────────────────────────────────────────

def test_status_stopped_no_pidfile(patch_status_deps):
    assert rt.status(make_plugin()) == "stopped"


def test_status_running(patch_status_deps, monkeypatch, pid_file):
    pid_file.write_text("12345")
    monkeypatch.setattr(rt, "_pid_exists", lambda pid: True)
    monkeypatch.setattr(rt, "check_health_sync", lambda pid, port: True)
    assert rt.status(make_plugin()) == "running"
    assert pid_file.exists()  # не удаляем файл у живого процесса


def test_status_degraded(patch_status_deps, monkeypatch, pid_file):
    pid_file.write_text("12345")
    monkeypatch.setattr(rt, "_pid_exists", lambda pid: True)
    assert rt.status(make_plugin()) == "degraded"


def test_status_failed_dead_process(patch_status_deps, pid_file):
    pid_file.write_text("999999")
    assert rt.status(make_plugin()) == "failed"
    # мёртвый pid-файл убираем
    assert not pid_file.exists()


def test_status_failed_corrupt_pidfile(patch_status_deps, pid_file):
    pid_file.write_text("garbage\nnot-a-pid")
    assert rt.status(make_plugin()) == "failed"
    assert not pid_file.exists()


def test_status_uses_assigned_port_or_registry(patch_status_deps, monkeypatch, pid_file):
    """Если assigned_port не задан — берётся из registry."""
    import app.services.plugin_registry as reg
    reg.assign_port("demo", preferred=8150)
    pid_file.write_text("12345")
    monkeypatch.setattr(rt, "_pid_exists", lambda pid: True)
    monkeypatch.setattr(rt, "check_health_sync", lambda pid, port: port == 8150)
    assert rt.status(make_plugin(assigned_port=None)) == "running"


# ── wait_healthy ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wait_healthy_timeout(monkeypatch):
    monkeypatch.setattr(rt, "HEALTH_INTERVAL", 0.01)
    monkeypatch.setattr(
        rt.httpx, "AsyncClient",
        lambda **kw: FakeHttpClient([FakeResponse(503)]),
    )
    ok = await rt.wait_healthy("demo", 8123, timeout=0.05)
    assert ok is False


@pytest.mark.asyncio
async def test_wait_healthy_retries_then_ok(monkeypatch):
    monkeypatch.setattr(rt, "HEALTH_INTERVAL", 0.01)
    client = FakeHttpClient([
        FakeResponse(503),
        FakeResponse(200, {"status": "starting"}),
        FakeResponse(200, {"status": "ok"}),
    ])
    monkeypatch.setattr(rt.httpx, "AsyncClient", lambda **kw: client)

    ok = await rt.wait_healthy("demo", 8123, timeout=1.0)
    assert ok is True
    assert client.calls >= 3


@pytest.mark.asyncio
async def test_wait_healthy_accepts_healthy_value(monkeypatch):
    monkeypatch.setattr(rt, "HEALTH_INTERVAL", 0.01)
    responses = [FakeResponse(200, {"status": "healthy"})]
    monkeypatch.setattr(
        rt.httpx, "AsyncClient",
        lambda **kw: FakeHttpClient(responses),
    )
    assert await rt.wait_healthy("demo", 8123, timeout=1.0) is True


# ── stop(): graceful → force ──────────────────────────────────────────────────

class FakeProc:
    def __init__(self):
        self.killed = False
        self.kill_count = 0
        self.terminated = False
        self.children = lambda recursive=False: []

    def kill(self):
        self.kill_count += 1
        self.killed = True


@pytest.fixture
def patch_stop(monkeypatch, tmp_path):
    from pathlib import Path
    pid_file = tmp_path / "demo.pid"
    monkeypatch.setattr(rt, "_pid_file", lambda plugin_id: pid_file)
    monkeypatch.setattr(rt, "IS_WINDOWS", False)
    monkeypatch.setattr(rt, "STOP_GRACEFUL", 0.0)
    monkeypatch.setattr(rt, "_wait_port_free", lambda port, timeout: True)
    return pid_file


def test_stop_no_pidfile(patch_stop, mocker):
    kill = mocker.patch("app.services.plugin_runtime.os.kill")
    rt.stop(make_plugin())
    kill.assert_not_called()  # pid-файла нет — SIGTERM не отправляем


def test_stop_graceful(patch_stop, mocker, monkeypatch):
    """SIGTERM отправлен, процесс умер сам — SIGKILL не требуется."""
    pid_file = patch_stop
    pid_file.write_text("4242")
    fake = FakeProc()
    kill = mocker.patch("app.services.plugin_runtime.os.kill")
    monkeypatch.setattr(rt, "psutil", SimpleNamespace(
        Process=lambda pid: fake,
        Error=psutil.Error,
    ))

    alive = {"v": True}

    def pid_exists(pid):
        # сначала процесс жив (SIGTERM должен уйти), потом умирает в ожидании
        if alive["v"]:
            alive["v"] = False
            return True
        return False

    monkeypatch.setattr(rt, "_pid_exists", pid_exists)
    monkeypatch.setattr(rt, "STOP_GRACEFUL", 0.25)

    rt.stop(make_plugin())

    kill.assert_called_once_with(4242, signal.SIGTERM)
    assert fake.kill_count == 0      # graceful — без SIGKILL
    assert not pid_file.exists()


def test_stop_force_kill(patch_stop, mocker, monkeypatch):
    """Порядок: SIGTERM → выжидание → SIGKILL (процесс не умирает)."""
    pid_file = patch_stop
    pid_file.write_text("4242")
    fake = FakeProc()
    kill = mocker.patch("app.services.plugin_runtime.os.kill")
    monkeypatch.setattr(rt, "psutil", SimpleNamespace(
        Process=lambda pid: fake,
        Error=psutil.Error,
    ))
    monkeypatch.setattr(rt, "_pid_exists", lambda pid: True)  # не умирает
    monkeypatch.setattr(rt, "STOP_GRACEFUL", 0.01)            # короткое ожидание

    rt.stop(make_plugin())

    # TERM первым...
    assert kill.call_args[0] == (4242, signal.SIGTERM)
    assert kill.call_count == 1
    # ... потом SIGKILL
    assert fake.kill_count >= 1
    assert not pid_file.exists()


# ── Порты ─────────────────────────────────────────────────────────────────────

import aiohttp.web as _web


def _occupy_port():
    """Поднимает реальный HTTP-сервер на случайном порту (0.0.0.0)."""
    async def handler(r):
        return _web.Response(text="ok")
    app = _web.Application()
    app.router.add_get("/", handler)
    return app


@pytest.mark.asyncio
async def test_is_port_free():
    app = _occupy_port()
    runner = _web.AppRunner(app)
    await runner.setup()
    site = _web.TCPSite(runner, "0.0.0.0", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]

    assert rt._is_port_free(port) is False  # занят слушающим сервером

    await runner.cleanup()
    assert rt._is_port_free(port) is True   # после остановки свободен


@pytest.mark.asyncio
async def test_wait_port_free_timeout():
    app = _occupy_port()
    runner = _web.AppRunner(app)
    await runner.setup()
    site = _web.TCPSite(runner, "0.0.0.0", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]

    assert rt._wait_port_free(port, timeout=0.5) is False

    await runner.cleanup()
    assert rt._wait_port_free(port, timeout=2.0) is True


# ── start() ───────────────────────────────────────────────────────────────────

class FakePopen:
    def __init__(self, pid=9876):
        self.pid = pid


def _make_installable_plugin(tmp_path):
    """Плагин с venv-бинарём и точкой входа — готов к start()."""
    import app.services.plugin_installer as inst
    plugin_dir = tmp_path / "demo"
    (plugin_dir / "app").mkdir(parents=True)
    (plugin_dir / "app" / "main.py").write_text("print('run')")
    bin_dir = inst.venv_bin_dir(plugin_dir)
    bin_dir.mkdir(parents=True)
    (bin_dir / ("python.exe" if inst.IS_WINDOWS else "python")).write_text("#fake")
    return plugin_dir


@pytest.fixture
def start_fixture(tmp_path, monkeypatch, mocker):
    plugin_dir = _make_installable_plugin(tmp_path)
    plugin = make_plugin(data_path=str(plugin_dir), assigned_port=8123)
    pid_file = tmp_path / "demo.pid"
    monkeypatch.setattr(rt, "_pid_file", lambda plugin_id: pid_file)
    monkeypatch.setattr(rt, "_is_port_free", lambda port: True)
    popen = mocker.patch("app.services.plugin_runtime.subprocess.Popen",
                        return_value=FakePopen())
    return plugin, pid_file, popen


def test_start_ok(start_fixture):
    plugin, pid_file, popen = start_fixture
    pid = rt.start(plugin)

    assert pid == 9876
    assert pid_file.read_text() == "9876"

    kwargs = popen.call_args.kwargs
    assert kwargs["cwd"].endswith("demo")
    assert kwargs["env"]["PLUGIN_ID"] == "demo"
    assert kwargs["env"]["PLUGIN_PORT"] == "8123"
    assert kwargs["env"]["CORE_URL"]
    assert kwargs["env"]["PYTHONUNBUFFERED"] == "1"
    assert kwargs["stdout"] is not None  # файл лога открыт
    assert kwargs["stderr"] is not None


def test_start_installs_venv_if_python_missing(start_fixture, mocker, tmp_path):
    import app.services.plugin_installer as inst
    plugin, pid_file, popen = start_fixture
    # удаляем «python» — start() должен вызвать install()
    venv_py = inst.venv_python(tmp_path / "demo")
    venv_py.unlink()

    install = mocker.patch.object(inst, "install")
    pid = rt.start(plugin)
    install.assert_called_once_with(tmp_path / "demo")
    assert pid == 9876


def test_start_missing_entry(start_fixture):
    import os
    plugin, _, _ = start_fixture
    entry = os.path.join(plugin.data_path, "app", "main.py")
    os.remove(entry)
    with pytest.raises(RuntimeError, match="Точка входа"):
        rt.start(plugin)


def test_start_no_port(start_fixture, monkeypatch):
    import app.services.plugin_registry as reg
    monkeypatch.setattr(reg, "get_port", lambda plugin_id: None)
    plugin, _, _ = start_fixture
    plugin.assigned_port = None
    with pytest.raises(RuntimeError, match="Порт не назначен"):
        rt.start(plugin)


def test_start_port_busy_resolves(start_fixture, monkeypatch, mocker):
    plugin, _, popen = start_fixture
    monkeypatch.setattr(rt, "_is_port_free", lambda port: False)
    kill = mocker.patch.object(rt, "_kill_port")
    monkeypatch.setattr(rt, "_wait_port_free", lambda port, timeout: True)

    pid = rt.start(plugin)
    kill.assert_called_once_with(8123)
    assert pid == 9876


def test_start_port_stays_busy_raises(start_fixture, monkeypatch):
    plugin, _, _ = start_fixture
    monkeypatch.setattr(rt, "_is_port_free", lambda port: False)
    monkeypatch.setattr(rt, "_wait_port_free", lambda port, timeout: False)
    with pytest.raises(RuntimeError, match="занят"):
        rt.start(plugin)


# ── check_health_sync / read_logs ─────────────────────────────────────────────

def free_port() -> int:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


async def _serve_health(payload):
    import aiohttp.web as web
    async def handler(request):
        return web.json_response(payload)
    app = web.Application()
    app.router.add_get("/health", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, port


@pytest.mark.asyncio
async def test_check_health_sync_ok():
    runner, port = await _serve_health({"status": "ok"})
    try:
        ok = await asyncio.to_thread(rt.check_health_sync, "demo", port)
        assert ok is True
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_check_health_sync_healthy_word():
    runner, port = await _serve_health({"status": "healthy"})
    try:
        ok = await asyncio.to_thread(rt.check_health_sync, "demo", port)
        assert ok is True
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_check_health_sync_wrong_status():
    runner, port = await _serve_health({"status": "starting"})
    try:
        ok = await asyncio.to_thread(rt.check_health_sync, "demo", port)
        assert ok is False
    finally:
        await runner.cleanup()


def test_check_health_sync_no_server():
    assert rt.check_health_sync("demo", free_port()) is False


def test_read_logs(tmp_path):
    plugin_dir = tmp_path / "demo"
    plugin_dir.mkdir()
    log = plugin_dir / "plugin.log"
    log.write_text("\n".join(f"line {i}" for i in range(10)) + "\n")

    p = make_plugin(data_path=str(plugin_dir))
    assert rt.read_logs(p, lines=3) == ["line 7", "line 8", "line 9"]
    assert rt.read_logs(p, lines=100) == [f"line {i}" for i in range(10)]


def test_read_logs_missing_file(tmp_path):
    p = make_plugin(data_path=str(tmp_path / "ghost"))
    assert rt.read_logs(p) == []