"""Интеграционные тесты plugin_proxy.py."""
import asyncio
import json
import socket
from types import SimpleNamespace

import pytest
import aiohttp.web as web
from fastapi import HTTPException
from fastapi.responses import Response, StreamingResponse
from starlette.requests import Request

from app.services import plugin_proxy as proxy_mod
from app.services.plugin_proxy import proxy


def make_plugin(port):
    return SimpleNamespace(plugin_id="demo", assigned_port=port)


def make_request(method="GET", path="/echo", query="", headers=None, body=b""):
    hdrs = [
        (k.lower().encode("latin1"), v.encode("latin1"))
        for k, v in (headers or {"Host": "localhost"}).items()
    ]
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "path": path,
        "raw_path": path.encode("latin1"),
        "query_string": query.encode("latin1"),
        "headers": hdrs,
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8142),
        "scheme": "http",
        "root_path": "",
    }

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive=receive)


async def run_server(app):
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, port


def free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ── Обычный HTTP ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_proxy_get_ok():
    async def handler(request):
        return web.json_response(
            {"ok": True, "x": request.headers.get("X-Test", "")},
            headers={"X-Upstream": "custom-value"},
        )

    app = web.Application()
    app.router.add_get("/echo", handler)
    runner, port = await run_server(app)
    try:
        req = make_request(path="/echo", headers={"X-Test": "hello"})
        resp = await proxy(make_plugin(port), req, "echo")

        assert isinstance(resp, Response)
        assert resp.status_code == 200
        assert json.loads(resp.body) == {"ok": True, "x": "hello"}
        # произвольные заголовки upstream проходят, hop-by-hop — нет
        assert resp.headers.get("x-upstream") == "custom-value"
        assert resp.headers.get("host") is None
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_proxy_query_passthrough():
    async def handler(request):
        return web.json_response({"q": dict(request.query)})

    app = web.Application()
    app.router.add_get("/search", handler)
    runner, port = await run_server(app)
    try:
        req = make_request(path="/search", query="q=film&page=2")
        resp = await proxy(make_plugin(port), req, "search")
        assert json.loads(resp.body) == {"q": {"q": "film", "page": "2"}}
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_proxy_missing_port():
    req = make_request()
    with pytest.raises(HTTPException) as exc:
        await proxy(make_plugin(None), req, "echo")
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_proxy_connect_error_502():
    # никто не слушает порт → httpx.ConnectError → 502
    req = make_request()
    with pytest.raises(HTTPException) as exc:
        await proxy(make_plugin(free_port()), req, "echo")
    assert exc.value.status_code == 502


# ── Timeout ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_proxy_timeout_504(monkeypatch):
    async def handler(request):
        resp = web.StreamResponse(
            status=200,
            headers={"Content-Type": "text/plain"},
        )
        await resp.prepare(request)          # заголовки сразу
        await asyncio.sleep(1)               # тело «зависло»
        await resp.write(b"late")
        return resp

    app = web.Application()
    app.router.add_get("/slow", handler)
    runner, port = await run_server(app)
    monkeypatch.setattr(proxy_mod, "RESPONSE_TIMEOUT", 0.2)
    try:
        req = make_request(path="/slow")
        with pytest.raises(HTTPException) as exc:
            await proxy(make_plugin(port), req, "slow")
        assert exc.value.status_code == 504
    finally:
        await runner.cleanup()


# ── Streaming (SSE / MJPEG) ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_proxy_stream_sse():
    async def handler(request):
        resp = web.StreamResponse(
            status=200,
            headers={"Content-Type": "text/event-stream"},
        )
        await resp.prepare(request)
        await resp.write(b"data: hello\n\n")
        await resp.write(b"data: world\n\n")
        return resp

    app = web.Application()
    app.router.add_get("/events", handler)
    runner, port = await run_server(app)
    try:
        req = make_request(path="/events")
        resp = await proxy(make_plugin(port), req, "events")

        assert isinstance(resp, StreamingResponse)
        assert resp.status_code == 200
        assert resp.headers.get("cache-control") == "no-cache"
        assert resp.headers.get("x-accel-buffering") == "no"

        chunks = [c async for c in resp.body_iterator]
        body = b"".join(chunks)
        assert b"data: hello" in body
        assert b"data: world" in body
    finally:
        await runner.cleanup()