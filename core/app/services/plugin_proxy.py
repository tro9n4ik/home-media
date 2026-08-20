from __future__ import annotations
import asyncio
import logging
import httpx
from fastapi import Request, Response, HTTPException
from fastapi.responses import StreamingResponse
from app.models.plugin import Plugin

logger = logging.getLogger(__name__)

STREAM_TIMEOUT = httpx.Timeout(None)

# Максимальное время ожидания ответа плагина для обычных (не стрим) запросов.
# Без этого лимита «зависший» плагин держит соединение вечно.
RESPONSE_TIMEOUT = 30.0

# Заголовки, которые нельзя проксировать
HOP_BY_HOP = {
    "host",
    "content-length",
    "transfer-encoding",
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "upgrade",
}


async def proxy(plugin: Plugin, request: Request, path: str) -> Response:
    if not plugin.assigned_port:
        raise HTTPException(503, f"Порт для {plugin.plugin_id!r} не назначен")

    # формируем target URL
    target = f"http://127.0.0.1:{plugin.assigned_port}/{path.lstrip('/')}"
    if request.url.query:
        target += f"?{request.url.query}"

    # фильтруем headers
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in HOP_BY_HOP
    }

    try:
        body = await request.body()
    except Exception:
        raise HTTPException(400, "Не удалось прочитать тело запроса")

    client = None
    resp = None

    try:
        client = httpx.AsyncClient(timeout=STREAM_TIMEOUT)

        upstream = client.build_request(
            method=request.method,
            url=target,
            headers=headers,
            content=body,
        )

        # ВСЕГДА stream=True
        resp = await client.send(upstream, stream=True)

    except httpx.ConnectError:
        if client:
            await client.aclose()
        raise HTTPException(502, f"Плагин {plugin.plugin_id!r} недоступен")

    except httpx.TimeoutException:
        if client:
            await client.aclose()
        raise HTTPException(504, f"Таймаут плагина {plugin.plugin_id!r}")

    content_type = resp.headers.get("content-type", "")
    content_type_l = content_type.lower()

    # фильтрация headers ответа
    resp_headers = {
        k: v
        for k, v in resp.headers.items()
        if k.lower() not in HOP_BY_HOP
        and k.lower() not in {"content-encoding", "content-type"}
    }

    # определяем streaming ответ
    is_stream = (
        "multipart/x-mixed-replace" in content_type_l
        or "text/event-stream" in content_type_l
    )

    # =============================
    # STREAM (MJPEG / SSE)
    # =============================
    if is_stream:
        resp_headers["Cache-Control"] = "no-cache"
        resp_headers["X-Accel-Buffering"] = "no"

        async def _gen():
            try:
                async for chunk in resp.aiter_raw():
                    if chunk:
                        yield chunk
            finally:
                await resp.aclose()
                await client.aclose()

        return StreamingResponse(
            _gen(),
            status_code=resp.status_code,
            headers=resp_headers,
            media_type=content_type or None,
        )

    # =============================
    # ОБЫЧНЫЙ HTTP
    # =============================
    try:
        content = await asyncio.wait_for(resp.aread(), timeout=RESPONSE_TIMEOUT)
        return Response(
            content=content,
            status_code=resp.status_code,
            headers=resp_headers,
            media_type=content_type or None,
        )
    except asyncio.TimeoutError:
        raise HTTPException(504, "Таймаут ответа плагина")
    finally:
        await resp.aclose()
        await client.aclose()