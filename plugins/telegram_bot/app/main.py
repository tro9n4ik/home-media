"""
Home.Media Telegram Bot Hub
============================
Главный модуль платформы: Telegram-бот с inline-меню.

Роль: хаб. Через бота доступны подменю всех остальных плагинов.

Протокол подключения плагина к боту (контракт /bot/*):
  1. В manifest.json плагин объявляет пункт меню:
       "bot_menu": {"title": "🎬 Поиск", "icon": "🔍"}
  2. Хаб каждые 30 сек получает каталог плагинов у ядра
     (GET /api/plugins/internal/plugins — только localhost).
  3. Плагины с bot_menu попадают в главное меню бота.
  4. Нажатие кнопки: хаб шлёт плагину
       POST {url}/bot/callback  {"action": "...", "user_id": 123, "username": "..."}
     и ждёт ответ:
       {
         "text":    "Новый текст сообщения",
         "buttons": [ {"text": "Кнопка", "action": "toggle_x"} | {"text": "Ссылка", "url": "https://..."} ]
       }
  5. Плагин отвечает только тем, что умеет сам — хаб не знает его логики.
  6. Если в ответе есть поле "await_text" (подсказка) — хаб запоминает,
     что этот пользователь ждёт текстовый ввод. Следующее текстовое сообщение
     пересылается плагину как callback {"action": "text", "text": "..."}.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

from plugin_sdk import PluginApp, CORE_URL, PLUGIN_PORT

# ── Параметры ─────────────────────────────────────────────────────────────────

PAGE_SIZE        = 8       # кнопок плагинов на страницу в главном меню
CATALOG_TTL      = 30.0    # сек, кэш каталога плагинов
CALLBACK_TIMEOUT = 8.0     # сек, ожидание ответа плагина

# Callback data:
#   "main"            — главное меню
#   "main:page:N"     — главное меню, страница N
#   "pl:{id}:{action}"— кнопка подменю плагина
#   "refresh"         — обновить каталог и показать меню

# ── Приложение ────────────────────────────────────────────────────────────────

class _Hub(PluginApp):
    """Переопределяет жизненный цикл: запуск/остановка Telegram-бота."""

    async def on_startup(self):
        app.logger.info("CORE_URL=%s PLUGIN_PORT=%s", CORE_URL, PLUGIN_PORT)
        await _start_bot()

    async def on_shutdown(self):
        if _bot_task and not _bot_task.done():
            _bot_task.cancel()
            try:
                await _bot_task
            except Exception:
                pass


app = _Hub(
    "telegram_bot",
    "1.0.0",
    "Телеграм-бот с inline-меню — хаб всех плагинов Home.Media",
    web_dir=Path(__file__).parent / "web",
    config={
        "bot_token":     {"type": "secret", "default": "", "label": "Токен бота (от @BotFather)"},
        "allowed_users": {"type": "json",   "default": [],  "label": "Разрешённые user_id (пусто = все)"},
        "bot_name":      {"type": "str",    "default": "Home.Media", "label": "Название бота"},
    },
)

# ── Состояние ─────────────────────────────────────────────────────────────────

_ptb: Application | None = None
_bot_task: asyncio.Task | None = None
_bot_configured = False
_bot_started = False
_bot_error: str | None = None

_catalog: dict = {"plugins": []}
_catalog_ts = 0.0

# Ожидание текстового ввода: user_id → plugin_id (плагин ответил с await_text)
_awaiting: dict[int, str] = {}


# ── Каталог плагинов (через ядро) ─────────────────────────────────────────────

async def _fetch_catalog(force: bool = False) -> dict:
    """GET каталога у ядра с кэшем на CATALOG_TTL секунд."""
    global _catalog, _catalog_ts
    now = time.monotonic()
    if not force and now - _catalog_ts < CATALOG_TTL:
        return _catalog
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            r = await client.get(f"{CORE_URL}/api/plugins/internal/plugins")
            if r.status_code == 200:
                data = r.json()
                _catalog = data
                _catalog_ts = now
    except Exception as e:
        app.logger.warning("Каталог плагинов недоступен: %s", e)
    return _catalog


def _plugins_with_menu(catalog: dict) -> list[dict]:
    """Плагины, объявившие bot_menu в manifest, отсортированные по order."""
    out = []
    for p in catalog.get("plugins", []):
        bm = (p.get("manifest") or {}).get("bot_menu")
        if bm:
            out.append({**p, "bot_menu": bm})
    out.sort(key=lambda p: (p["bot_menu"].get("order", 99), p["name"].lower()))
    return out


# ── Telegram: сборка меню ─────────────────────────────────────────────────────

def _menu_button_title(p: dict) -> str:
    bm = p["bot_menu"]
    icon = bm.get("icon", "")
    title = bm.get("title") or p.get("name", p["plugin_id"])
    return f"{icon} {title}".strip()


def _main_keyboard(plugins: list[dict], page: int) -> InlineKeyboardMarkup:
    total = len(plugins)
    pages = max(1, -(-total // PAGE_SIZE))
    page = max(0, min(page, pages - 1))
    start, end = page * PAGE_SIZE, min((page + 1) * PAGE_SIZE, total)

    rows: list[list[InlineKeyboardButton]] = []
    for p in plugins[start:end]:
        rows.append([
            InlineKeyboardButton(_menu_button_title(p), callback_data=f"pl:{p['plugin_id']}:main")
        ])

    if total == 0:
        rows.append([InlineKeyboardButton("🔄 Обновить", callback_data="refresh")])
        return InlineKeyboardMarkup(rows)

    nav = []
    if pages > 1:
        nav.append(InlineKeyboardButton("◀", callback_data=f"main:page:{page - 1}"))
        nav.append(InlineKeyboardButton(f"{page + 1}/{pages}", callback_data="noop"))
        nav.append(InlineKeyboardButton("▶", callback_data=f"main:page:{page + 1}"))
        rows.append(nav)
    rows.append([InlineKeyboardButton("🔄 Обновить", callback_data="refresh")])
    return InlineKeyboardMarkup(rows)


def _main_text(plugins: list[dict]) -> str:
    name = app.config.get("bot_name") or "Home.Media"
    if not plugins:
        return (
            f"🏠 <b>{name}</b>\n\n"
            f"Модулей пока нет. Установите плагины с <code>bot_menu</code> в manifest "
            f"и нажмите «Обновить»."
        )
    return (
        f"🏠 <b>{name}</b>\n\n"
        f"Модулей: <b>{len(plugins)}</b>\n\n"
        f"Выберите раздел 👇"
    )


def _reply_keyboard(plugin_id: str, buttons: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for b in buttons[:90]:
        # элемент может быть одиночной кнопкой или рядом из нескольких кнопок
        items = b if isinstance(b, list) else [b]
        row = []
        for it in items[:8]:
            text = it.get("text", "?")
            if it.get("url"):
                row.append(InlineKeyboardButton(text, url=it["url"]))
            else:
                action = it.get("action", "main")
                row.append(InlineKeyboardButton(
                    text, callback_data=f"pl:{plugin_id}:{action}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("◀ Главное меню", callback_data="main")])
    return InlineKeyboardMarkup(rows)


# ── Telegram: доступ ───────────────────────────────────────────────────────────

def _is_allowed(user_id: int | None) -> bool:
    allowed = app.config.get("allowed_users") or []
    return not allowed or (user_id in allowed)


# ── Telegram: хендлеры ────────────────────────────────────────────────────────

async def _send_main(update: Update, ctx: ContextTypes.DEFAULT_TYPE, page: int = 0, announce: str | None = None) -> None:
    catalog = await _fetch_catalog()
    plugins = _plugins_with_menu(catalog)
    text = _main_text(plugins)
    if announce:
        text = f"<i>{announce}</i>\n\n" + text
    kb = _main_keyboard(plugins, page)
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await update.effective_message.reply_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await update.effective_message.reply_text(text, reply_markup=kb, parse_mode="HTML")


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update.effective_user.id):
        await update.effective_message.reply_text("⛔ Нет доступа")
        return
    app.logger.info("start от %s", update.effective_user.id)
    await _send_main(update, ctx)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "ℹ️ <b>Home.Media Bot</b>\n\n"
        "/start — главное меню\n"
        "/menu — то же самое\n"
        "/status — состояние модулей\n"
        "/help — эта справка\n\n"
        "Все функции доступны кнопками в меню."
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Главное меню", callback_data="main")]])
    await update.effective_message.reply_text(text, reply_markup=kb, parse_mode="HTML")


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update.effective_user.id):
        await update.effective_message.reply_text("⛔ Нет доступа")
        return
    catalog = await _fetch_catalog(force=True)
    plugins = _plugins_with_menu(catalog)
    lines = [f"🤖 Статус бота: {'✅ активен' if _bot_started else '⏸ выключен'}"]
    lines.append(f"📦 Модулей с меню: <b>{len(plugins)}</b>")
    for p in plugins:
        lines.append(f" • {_menu_button_title(p)}")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Главное меню", callback_data="main")]])
    await update.effective_message.reply_text("\n".join(lines), reply_markup=kb, parse_mode="HTML")


async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data or ""
    await query.answer()

    user = update.effective_user
    if not _is_allowed(user.id):
        await query.message.reply_text("⛔ Нет доступа")
        return

    app.logger.info("callback %s от %s", data, user.id)

    if data == "noop":
        return

    if data == "refresh" or data == "main":
        await _send_main(update, ctx)
        return

    if data.startswith("main:page:"):
        try:
            page = int(data.split(":")[-1])
        except ValueError:
            page = 0
        await _send_main(update, ctx, page=page)
        return

    if data.startswith("pl:"):
        parts = data.split(":")
        if len(parts) < 3:
            return
        plugin_id = parts[1]
        action = ":".join(parts[2:])
        await _handle_plugin_callback(update, ctx, plugin_id, action)
        return

    await _send_main(update, ctx)


async def _send_photo(message, photo: str, text: str, kb) -> None:
    if len(text) <= 900:
        try:
            await message.reply_photo(photo, caption=text, reply_markup=kb, parse_mode="HTML")
            return
        except Exception:
            pass
    try:
        await message.reply_photo(photo)
    except Exception:
        pass
    await message.reply_text(text, reply_markup=kb, parse_mode="HTML")


async def _handle_plugin_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE, plugin_id: str, action: str) -> None:
    query = update.callback_query
    catalog = await _fetch_catalog()
    plugin = next((p for p in catalog.get("plugins", []) if p["plugin_id"] == plugin_id), None)

    if not plugin:
        await query.message.reply_text("❌ Модуль не найден. Нажмите «Обновить».")
        return

    user = update.effective_user
    payload = {"action": action, "user_id": user.id, "username": user.username}
    try:
        async with httpx.AsyncClient(timeout=CALLBACK_TIMEOUT) as client:
            r = await client.post(f"{plugin['url']}/bot/callback", json=payload)
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}")
            data = r.json()
    except Exception as e:
        app.logger.warning("Модуль %s не ответил: %s", plugin_id, e)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("◀ Главное меню", callback_data="main")]])
        await query.message.reply_text(
            f"⚠️ Модуль «{plugin.get('name', plugin_id)}» не отвечает.\nПроверьте его статус в админке.",
            reply_markup=kb,
        )
        return

    text = data.get("text") or "…"
    buttons = data.get("buttons") or []
    kb = _reply_keyboard(plugin_id, buttons)
    if data.get("await_text"):
        _awaiting[user.id] = plugin_id
    else:
        _awaiting.pop(user.id, None)
    photo = data.get("photo") or ""
    if photo:
        if query.message.photo and len(text) <= 900:
            try:
                await query.edit_message_caption(caption=text, reply_markup=kb, parse_mode="HTML")
                return
            except Exception:
                pass
        await _send_photo(query.message, photo, text, kb)
        return
    try:
        await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        try:
            await query.message.reply_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            app.logger.warning("не удалось отправить ответ для %s: %s", action, e)
            await query.message.reply_text(text[0:4000])


async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Текстовое сообщение: пересылается плагину, который ждал ввод (await_text)."""
    user = update.effective_user
    if not _is_allowed(user.id):
        return
    plugin_id = _awaiting.pop(user.id, None)
    if not plugin_id:
        await update.effective_message.reply_text(
            "🤷 Ожидаю нажатия кнопки. Откройте меню модуля (например «Торренты → Поиск») "
            "и отправьте название после того, как модуль попросит его ввести."
        )
        return
    catalog = await _fetch_catalog()
    plugin = next((p for p in catalog.get("plugins", []) if p["plugin_id"] == plugin_id), None)
    if not plugin:
        await update.effective_message.reply_text("❌ Модуль не найден. Нажмите «Обновить».")
        return
    payload = {"action": "text", "text": update.effective_message.text or "", "user_id": user.id, "username": user.username}
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(f"{plugin['url']}/bot/callback", json=payload)
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}")
            data = r.json()
    except Exception as e:
        app.logger.warning("Модуль %s не ответил на текст: %s", plugin_id, e)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("◀ Главное меню", callback_data="main")]])
        await update.effective_message.reply_text(
            f"⚠️ Модуль «{plugin_id}» не ответил.\nПопробуйте ещё раз.",
            reply_markup=kb,
        )
        return
    text = data.get("text") or "…"
    buttons = data.get("buttons") or []
    kb = _reply_keyboard(plugin_id, buttons)
    photo = data.get("photo") or ""
    if photo:
        await _send_photo(update.effective_message, photo, text, kb)
    else:
        await update.effective_message.reply_text(text, reply_markup=kb, parse_mode="HTML")
    if data.get("await_text"):
        _awaiting[user.id] = plugin_id


# ── Telegram: жизненный цикл ──────────────────────────────────────────────────

def _build_ptb() -> Application:
    token = app.config.get("bot_token") or ""
    ptb = Application.builder().token(token).build()
    ptb.add_handler(CommandHandler("start", cmd_start))
    ptb.add_handler(CommandHandler("menu", cmd_start))
    ptb.add_handler(CommandHandler("help", cmd_help))
    ptb.add_handler(CommandHandler("status", cmd_status))
    ptb.add_handler(CallbackQueryHandler(handle_callback))
    ptb.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    return ptb


async def _bot_loop() -> None:
    """Задача: запускает polling и держит бота живым."""
    global _bot_configured, _bot_started, _bot_error, _ptb
    stop = asyncio.Event()
    token = app.config.get("bot_token") or ""
    _bot_configured = bool(token)
    if not token:
        _bot_started = False
        _bot_error = None
        app.logger.info("Бот не настроен: нет токена. Укажите токен на странице плагина.")
        return

    try:
        ptb = _build_ptb()
        _ptb = ptb
        await ptb.initialize()
        await ptb.start()
        await ptb.bot.set_my_commands([
            BotCommand("start", "Главное меню"),
            BotCommand("menu", "Меню"),
            BotCommand("status", "Статус модулей"),
            BotCommand("help", "Помощь"),
        ])
        await ptb.updater.start_polling(allowed_updates=["message", "callback_query"])
        me = await ptb.bot.get_me()
        _bot_started = True
        _bot_error = None
        app.logger.info("Бот запущен: @%s (id %d)", me.username, me.id)

        while not stop.is_set():
            await asyncio.sleep(1)

        await ptb.updater.stop()
        await ptb.stop()
        await ptb.shutdown()
        _bot_started = False
        app.logger.info("Бот остановлен")
    except Exception as e:
        _bot_started = False
        _bot_error = str(e)[:300]
        app.logger.error("Ошибка бота: %s", e)
        try:
            if _ptb:
                await _ptb.shutdown()
        except Exception:
            pass
        _ptb = None


async def _start_bot() -> None:
    global _bot_task
    if _bot_task and not _bot_task.done():
        _bot_task.cancel()
        try:
            await _bot_task
        except Exception:
            pass
    _bot_task = asyncio.create_task(_bot_loop())


# ── API плагина (для админки и других плагинов) ──────────────────────────────

@app.get("/bot/status")
async def bot_status():
    catalog = await _fetch_catalog()
    plugins = _plugins_with_menu(catalog)
    return {
        "configured":  _bot_configured,
        "running":     _bot_started,
        "error":       _bot_error,
        "bot_name":    app.config.get("bot_name") or "Home.Media",
        "plugin_count": len(catalog.get("plugins", [])),
        "menu_plugins": [
            {"plugin_id": p["plugin_id"], "title": _menu_button_title(p), "status": p["status"]}
            for p in plugins
        ],
    }


@app.post("/bot/restart")
async def bot_restart():
    await _start_bot()
    return {"status": "ok"}


@app.post("/bot/notify")
async def bot_notify(body: dict):
    """Уведомление из плагина: {"text", "chat_id"?, "photo"?, "buttons"?, "plugin_id"?}.

    chat_id > 0 — конкретный чат, иначе всем разрешённым пользователям.
    buttons — как в контракте /bot/callback (кнопки с action, префикс pl:{plugin_id}).
    """
    if not _ptb or not _bot_started:
        return {"ok": False, "error": "бот не запущен"}
    text = (body.get("text") or "").strip()
    photo = (body.get("photo") or "").strip()
    if not text and not photo:
        return {"ok": False, "error": "нет text/photo"}
    buttons = body.get("buttons") or []
    plugin_id = (body.get("plugin_id") or "plugin").strip()
    kb = _reply_keyboard(plugin_id, buttons) if buttons else None

    chat_id = int(body.get("chat_id") or 0)
    chats = [chat_id] if chat_id > 0 else (app.config.get("allowed_users") or [])
    if not chats:
        return {"ok": False, "error": "нет получателей"}

    sent = 0
    for cid in chats:
        try:
            if photo:
                await _send_photo_to(cid, photo, text, kb)
            else:
                await _ptb.bot.send_message(cid, text, reply_markup=kb, parse_mode="HTML")
            sent += 1
        except Exception as e:
            app.logger.warning("notify → %s: %s", cid, e)
    return {"ok": True, "sent": sent}


async def _send_photo_to(chat_id: int, photo: str, text: str, kb) -> None:
    """Фото с подписью (≤900 символов) или фото + отдельное сообщение."""
    if len(text) <= 900:
        try:
            await _ptb.bot.send_photo(chat_id, photo, caption=text, reply_markup=kb, parse_mode="HTML")
            return
        except Exception:
            pass
    try:
        await _ptb.bot.send_photo(chat_id, photo)
    except Exception:
        pass
    if text:
        await _ptb.bot.send_message(chat_id, text, reply_markup=kb, parse_mode="HTML")


if __name__ == "__main__":
    app.run()
