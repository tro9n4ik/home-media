"""
Example Plugin — шаблон плагина Home.Media v4 на новом SDK.

Показывает:
- декларативный конфиг (типы, секреты, дефолты)
- web UI (папка web/)
- фоновую периодическую задачу
- Telegram-подменю: bot_menu в manifest + endpoint /bot/callback
"""
from __future__ import annotations

from pathlib import Path

from plugin_sdk import PluginApp

app = PluginApp(
    "example",
    "1.1.0",
    "Шаблон плагина для Home.Media v4",
    web_dir=Path(__file__).parent / "web",
    config={
        "message": {
            "type":    "str",
            "default": "Привет из плагина!",
            "label":   "Текст приветствия",
        },
        "interval": {
            "type":    "int",
            "default": 60,
            "label":   "Интервал фоновой задачи, сек",
        },
        "api_key": {
            "type":    "secret",
            "default": "",
            "label":   "Секретный API-ключ",
        },
    },
)


@app.periodic(interval=60)
async def heartbeat():
    app.logger.info("[heartbeat] message=%r", app.config.get("message"))


@app.get("/hello")
async def hello():
    return {"message": app.config.get("message")}


@app.get("/uptime")
async def uptime():
    return {"uptime_seconds": 0}


# ── Telegram-подменю (протокол бота-хаба) ─────────────────────────────────────

@app.post("/bot/callback")
async def bot_callback(body: dict):
    """
    Вызывается ботом-хабом при нажатии кнопки этого плагина в Telegram.
    Ответ: {"text": ..., "buttons": [{"text", "action"|"url"}]}
    """
    action = body.get("action") or "main"
    if action == "main":
        return {
            "text": "🧪 <b>Example Plugin</b>\n\nДемонстрация Telegram-подменю плагина.",
            "buttons": [
                {"text": "👋 Приветствие", "action": "hello"},
                {"text": "⏱ Интервал задачи", "action": "interval"},
            ],
        }
    if action == "hello":
        return {"text": f"👋 {app.config.get('message')}", "buttons": [{"text": "◀ Назад", "action": "main"}]}
    if action == "interval":
        return {
            "text": f"⏱ Фоновая задача запускается каждые <b>{app.config.get('interval')}</b> сек.",
            "buttons": [{"text": "◀ Назад", "action": "main"}],
        }
    return {"text": "Неизвестное действие", "buttons": [{"text": "◀ Назад", "action": "main"}]}


if __name__ == "__main__":
    app.run()
