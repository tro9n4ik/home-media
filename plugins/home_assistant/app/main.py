"""
Home Assistant Plugin — умный дом в Home.Media v4.
=====================================================
Подключение: REST API Home Assistant (http://host:8123) + Long-Lived Access Token.

Возможности:
- Мониторинг: панель датчиков (сensor/binary_sensor) и всех состояний сущностей
- Контроль: свет (on/off/яркость), климат (режим/температура), розетки/выключатели,
  вентиляторы, медиаплееры (play/pause/громкость), шторы (open/close), замки
- Кэш состояний с периодическим обновлением (HTTP, без WebSocket — проще и надёжнее)
- Telegram-меню через бота-хаб (протокол /bot/callback) + веб-панель на /ui

Контракт меню для бота:
    POST {url}/bot/callback  {"action": "...", "user_id": N, "text": "..."}
    → {"text": "...", "buttons": [{"text": "...", "action": "..."}]}
Callback_data ботов Telegram принимает только [a-zA-Z0-9_-], поэтому entity_id
кодируются коротким hex-хэшем SHA-1 (10 символов) — base64 раздувал код до 39+,
и с префиксом "pl:{plugin_id}:" выходил за лимит Telegram в 64 байта.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import time
from datetime import datetime, UTC
from pathlib import Path

import httpx

from plugin_sdk import PluginApp

class _App(PluginApp):
    """Стартовая загрузка состояний при запуске плагина."""

    async def on_startup(self):
        await _refresh()


app = _App(
    "home_assistant",
    "1.0.2",
    "Умный дом: мониторинг датчиков и управление устройствами Home Assistant",
    web_dir=Path(__file__).parent / "web",
    config={
        "ha_url":         {"type": "str",    "default": "http://192.168.1.100:8123",
                           "label": "Home Assistant URL (http://ip:8123)"},
        "ha_token":       {"type": "secret", "default": "", "label": "Long-Lived Access Token"},
        "poll_seconds":   {"type": "int",    "default": 30, "label": "Обновление состояний, сек"},
        "brightness_step":{"type": "int",    "default": 15, "label": "Шаг яркости света, %"},
        "temp_step":      {"type": "float",  "default": 0.5, "label": "Шаг температуры, °C"},
        "volume_step":    {"type": "int",    "default": 10,  "label": "Шаг громкости, %"},
        "hide":           {"type": "json",   "default": [],  "label": "entity_id для скрытия"},
        "tg_groups":      {"type": "json",   "default": [],  "label": "Группы Telegram-меню (имя, иконка, сущности)"},
        "tg_show_sensors":{"type": "bool",   "default": True, "label": "Показывать в Telegram раздел «Датчики» (непривязанные)"},
    },
)

PAGE_SIZE = 8  # сущностей/кнопок на страницу меню
CACHE_TTL = 120.0  # если обновление упало, отдаём кэш старше этого — не считаем его старением

# ── Кэш состояний ─────────────────────────────────────────────────────────────

_CACHE: dict = {"at": 0.0, "ha_ok": False, "list": [], "error": ""}
_BUSY = False

# ── Подключение к Home Assistant ──────────────────────────────────────────────

def _ha_base() -> str:
    return (app.config.get("ha_url") or "").strip().rstrip("/")


def _ha_headers() -> dict:
    return {"Authorization": f"Bearer {app.config.get('ha_token') or ''}",
            "Content-Type": "application/json"}


async def _ha_get(path: str) -> object | None:
    base = _ha_base()
    tok = app.config.get("ha_token") or ""
    if not base or not tok:
        return None
    try:
        async with httpx.AsyncClient(base_url=base, timeout=15.0, headers=_ha_headers()) as c:
            r = await c.get(path)
            if r.status_code == 200:
                return r.json()
            app.logger.warning("HA GET %s → HTTP %s", path, r.status_code)
            return None
    except Exception as e:
        app.logger.warning("HA недоступен (%s): %s", path, e)
        return None


async def _ha_service(domain: str, service: str, entity_id: str, **data) -> bool:
    base = _ha_base()
    if not base:
        return False
    try:
        payload = {"entity_id": entity_id}
        payload.update(data)
        async with httpx.AsyncClient(base_url=base, timeout=15.0, headers=_ha_headers()) as c:
            r = await c.post(f"/api/services/{domain}/{service}", json=payload)
            if r.status_code not in (200, 201):
                app.logger.warning("HA %s/%s %s → HTTP %s", domain, service, entity_id, r.status_code)
                return False
            return True
    except Exception as e:
        app.logger.warning("HA service %s/%s %s: %r", domain, service, entity_id, e)
        return False


# ── Отрисовка значений ────────────────────────────────────────────────────────

_DOMAIN_ICON = {
    "light": "💡", "switch": "🔌", "input_boolean": "🎛", "automation": "🤖",
    "script": "📜", "climate": "🌡", "fan": "🌀", "sensor": "📊",
    "binary_sensor": "🔔", "media_player": "📺", "cover": "🪟", "lock": "🔒",
    "camera": "📷", "humidifier": "💧",
}


def _human(eid: str, attrs: dict) -> str:
    name = (attrs.get("friendly_name") or "").strip()
    if name:
        return name
    base = eid.split(".", 1)[-1]
    return " ".join(w.capitalize() for w in base.split("_") if w)


def _fnum(v: object, d: int = 1) -> str | None:
    """Число → строку без «.0», не число → None."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    s = f"{f:.{d}f}".rstrip("0").rstrip(".")
    return s


def _state_str(eid: str, st: str, attrs: dict) -> str:
    domain = eid.split(".", 1)[0]
    if domain == "climate":
        cur = _fnum(attrs.get("current_temperature"))
        tgt = _fnum(attrs.get("temperature"))
        bits = [f"{cur}°C" if cur else "?"]
        if tgt is not None:
            bits.append(f"задан {tgt}°C")
        action = attrs.get("hvac_action") or ""
        if action in ("heating", "cooling", "drying", "fan"):
            bits.append({"heating": "🔥 греет", "cooling": "❄ охлаждает",
                         "drying": "💨 сушит", "fan": "🌀 вентилирует"}[action])
        return " · ".join(bits)
    if domain == "media_player":
        mode = {"playing": "▶ Играет", "paused": "⏸ Пауза", "idle": "Ожидание",
                "standby": "Ожидание", "on": "▶ Включен", "off": "Выкл"}.get(st, st)
        vol = attrs.get("volume_level")
        title = attrs.get("media_title") or ""
        tail = f" · {title}" if title else (f" · громкость {round(float(vol) * 100)}%" if vol is not None else "")
        return mode + tail
    if domain == "cover":
        return {"open": "🔼 Открыто", "closed": "🔽 Закрыто", "opening": "🔼 Открывается",
                "closing": "🔽 Закрывается", "stopped": "⏸ Остановлено"}.get(st, st)
    if domain == "lock":
        return {"locked": "🔒 Закрыт", "unlocked": "🔓 Открыт",
                "locking": "Закрывается", "unlocking": "Открывается"}.get(st, st)
    if domain == "binary_sensor":
        return "✅ Норма" if st == "off" else "⚠ Сработал"
    if domain in ("sensor", "number"):
        unit = attrs.get("unit_of_measurement") or ""
        val = st
        if _fnum(st) is not None:
            val = _fnum(st) or st
        return f"{val} {unit}".strip()
    onmap = {"on": "Вкл", "off": "Выкл", "open": "Открыто", "closed": "Закрыто",
             "home": "Дома", "not_home": "Ушёл", "unavailable": "Нет связи",
             "unknown": "Неизвестно"}
    return onmap.get(st, str(st))


def _brightness_pct(attrs: dict) -> int | None:
    b = attrs.get("brightness")
    if isinstance(b, (int, float)) and b > 0:
        return round(float(b) * 100 / 255)
    return None


def _normalize(eid: str, st: str, attrs: dict) -> dict:
    domain = eid.split(".", 1)[0]
    return {
        "entity_id": eid,
        "domain": domain,
        "name": _human(eid, attrs),
        "state": st,
        "state_str": _state_str(eid, st, attrs),
        "unit": attrs.get("unit_of_measurement") or "",
        "icon": _DOMAIN_ICON.get(domain, "▪"),
        "brightness_pct": _brightness_pct(attrs) if domain == "light" else None,
        "temperature": _fnum(attrs.get("temperature")),
        "current_temperature": _fnum(attrs.get("current_temperature")),
        "hvac": attrs.get("hvac_action") or "",
        "volume_pct": round(float(attrs["volume_level"]) * 100) if isinstance(attrs.get("volume_level"), (int, float)) else None,
        "attrs": attrs,
    }


# ── Обновление кэша ──────────────────────────────────────────────────────────

async def _refresh() -> None:
    global _BUSY
    if _BUSY:
        return
    _BUSY = True
    try:
        hide = set(app.config.get("hide") or [])
        data = await _ha_get("/api/states")
        if not isinstance(data, list):
            _CACHE.update({"at": time.time(), "ha_ok": False, "list": [],
                           "error": "HA не отвечает — проверьте URL и токен"})
            return
        items = []
        for raw in data:
            eid = raw.get("entity_id") or ""
            if not eid or eid in hide:
                continue
            if raw.get("state") in ("unavailable", "unknown") and raw.get("state") is not None:
                # не прячем, но покажем как есть (state_str уже обрабатывает)
                pass
            items.append(_normalize(eid, raw.get("state", ""), raw.get("attributes") or {}))
        items.sort(key=lambda e: (e["domain"], e["name"].lower()))
        _CACHE.update({"at": time.time(), "ha_ok": True, "list": items, "error": ""})
        app.logger.info("HA: %d сущностей", len(items))
    except Exception as e:
        app.logger.exception("refresh: %r", e)
    finally:
        _BUSY = False


def _entities() -> list[dict]:
    return _CACHE["list"]


def _find(entity_id: str) -> dict | None:
    for e in _entities():
        if e["entity_id"] == entity_id:
            return e
    return None


# ── Управление ────────────────────────────────────────────────────────────────

async def _sync_after(entity_id: str, action: str) -> None:
    """После управления ждём, пока HA реально обновит состояние (как в bot.py —
    пауза после вызова сервиса), иначе меню покажет устаревший статус."""
    pre = _find(entity_id)
    want = {"on": "on", "off": "off"}.get(action)
    for _ in range(8):
        await asyncio.sleep(0.4)
        await _refresh()
        e = _find(entity_id)
        if not e:
            return
        if want is not None:
            if e["state"] == want:
                return
        elif pre is None or e["state"] != pre["state"]:
            return


_CONTROL_DOMAINS = {
    "light": ("on", "off", "toggle"),
    "switch": ("on", "off", "toggle"),
    "input_boolean": ("on", "off", "toggle"),
    "automation": ("on", "off", "toggle"),
    "script": ("on", "off", "toggle"),
    "cover": ("open", "close", "stop"),
    "lock": ("lock", "unlock"),
}


def _services_domain(domain: str) -> list[str]:
    base = {
        "light": ["turn_on", "turn_off", "toggle"],
        "switch": ["turn_on", "turn_off", "toggle"],
        "input_boolean": ["turn_on", "turn_off", "toggle"],
        "automation": ["turn_on", "turn_off", "toggle"],
        "script": ["turn_on", "turn_off", "toggle"],
        "cover": ["open_cover", "close_cover", "stop_cover"],
        "lock": ["lock", "unlock"],
        "climate": ["set_hvac_mode", "set_temperature", "set_fan_mode"],
        "fan": ["turn_on", "turn_off", "toggle", "set_percentage"],
        "media_player": ["media_play", "media_pause", "media_stop", "volume_set"],
    }
    return base.get(domain, [])


async def _control(entity_id: str, action: str, value: str = "") -> tuple[bool, str]:
    e = _find(entity_id)
    if not e:
        return False, "Сущность не найдена (обновите меню)"
    domain = e["domain"]

    # ── базовые on/off/toggle ──
    if action in ("on", "off", "toggle"):
        if domain == "media_player":
            if action == "on":
                ok = await _ha_service(domain, "media_play", entity_id)
                return ok, ("media_play" if ok else "ошибка")
            if action == "off":
                ok = await _ha_service(domain, "media_stop", entity_id)
                return ok, ("media_stop" if ok else "ошибка")
            return True, "media_player не поддерживает toggle"
        if domain in _CONTROL_DOMAINS:
            svc = _services_domain(domain)
            if svc:
                service = {"on": "turn_on", "off": "turn_off", "toggle": "toggle"}[action]
                if service in svc:
                    ok = await _ha_service(domain, service, entity_id)
                    return ok, (service if ok else "ошибка")
        return False, f"{domain}: нет действия {action}"

    # ── свет: яркость ──
    if action in ("brightness_up", "brightness_down", "brightness_set"):
        cur = e.get("brightness_pct") or 0
        step = int(app.config.get("brightness_step") or 15)
        if action == "brightness_set" and value:
            v = int(value)
        elif action == "brightness_up":
            v = min(100, cur + step)
        else:
            v = max(0, cur - step)
        v = max(0, min(100, v))
        ok = await _ha_service(domain, "turn_on", entity_id, brightness_pct=v)
        return ok, (f"яркость {v}%" if ok else "ошибка")

    # ── климат ──
    if action == "hvac":
        mode = value or "heat"
        ok = await _ha_service(domain, "set_hvac_mode", entity_id, hvac_mode=mode)
        return ok, (f"режим {mode}" if ok else "ошибка")
    if action in ("temp_up", "temp_down", "temp_set"):
        step = float(app.config.get("temp_step") or 0.5)
        tgt = e.get("temperature")
        cur = float(tgt) if tgt is not None else 21.0
        v = float(value) if (action == "temp_set" and value) else (
            cur + step if action == "temp_up" else cur - step)
        ok = await _ha_service(domain, "set_temperature", entity_id, temperature=round(v, 1))
        return ok, (f"{round(v, 1)}°C" if ok else "ошибка")

    # ── вентилятор ──
    if action in ("speed_up", "speed_down"):
        cur = e.get("attrs", {}).get("percentage") or 0
        step = int(app.config.get("brightness_step") or 15)
        v = min(100, cur + step) if action == "speed_up" else max(0, cur - step)
        ok = await _ha_service(domain, "set_percentage", entity_id, percentage=v)
        return ok, (f"скорость {v}%" if ok else "ошибка")
    if action == "fan_mode":
        v = value or "auto"
        ok = await _ha_service(domain, "set_fan_mode", entity_id, fan_mode=v)
        return ok, (f"вентилятор {v}" if ok else "ошибка")

    # ── медиа ──
    if action == "play":
        ok = await _ha_service(domain, "media_play", entity_id)
        return ok, ("play" if ok else "ошибка")
    if action == "pause":
        ok = await _ha_service(domain, "media_pause", entity_id)
        return ok, ("pause" if ok else "ошибка")
    if action in ("vol_up", "vol_down", "vol_set"):
        step = int(app.config.get("volume_step") or 10)
        cur = e.get("volume_pct") or 0
        v = int(value) if (action == "vol_set" and value) else (
            min(100, cur + step) if action == "vol_up" else max(0, cur - step))
        ok = await _ha_service(domain, "volume_set", entity_id, volume_level=max(0, min(100, v)) / 100)
        return ok, (f"громкость {max(0, min(100, v))}%" if ok else "ошибка")

    # ── шторы / замки ──
    if action in ("open", "close", "stop") and domain == "cover":
        svc = {"open": "open_cover", "close": "close_cover", "stop": "stop_cover"}[action]
        ok = await _ha_service(domain, svc, entity_id)
        return ok, (svc if ok else "ошибка")
    if action == "lock" and domain == "lock":
        ok = await _ha_service(domain, "lock", entity_id)
        return ok, ("lock" if ok else "ошибка")
    if action == "unlock" and domain == "lock":
        ok = await _ha_service(domain, "unlock", entity_id)
        return ok, ("unlock" if ok else "ошибка")

    return False, f"неизвестное действие {action} для {domain}"


# ── Telegram-коды (callback_data: только [a-zA-Z0-9_-]) ──────────────────────
# Лимит callback_data Telegram — 64 байта, а хаб добавляет префикс "pl:{plugin_id}:",
# поэтому короткий hex-хэш (10 символов) вместо base64.

def _enc(entity_id: str) -> str:
    return hashlib.sha1(entity_id.encode("utf-8")).hexdigest()[:10]


def _dec(code: str) -> str | None:
    # новый формат: hex-хэш
    if len(code) == 10 and all(c in "0123456789abcdef" for c in code):
        for e in _entities():
            if _enc(e["entity_id"]) == code:
                return e["entity_id"]
        return None
    # старый формат (base64) — для уже отправленных меню в чате
    try:
        pad = "=" * (-len(code) % 4)
        return base64.urlsafe_b64decode(code + pad).decode("utf-8")
    except Exception:
        return None


# ── Меню Telegram ─────────────────────────────────────────────────────────────

_DOMAIN_SECTIONS = [
    ("light", "💡 Свет"),
    ("climate", "🌡 Климат"),
    ("switch", "🔌 Переключатели"),
    ("fan", "🌀 Вентиляторы"),
    ("media_player", "📺 Медиа"),
    ("cover", "🪟 Шторы"),
    ("lock", "🔒 Замки"),
]

# Домены с базовым on/off: в списках групп/разделов — однокнопочный тумблер
# (нажатие сразу переключает, как в старом bot.py), без диалогового меню.
_TOGGLE_DOMAINS = ("light", "switch", "input_boolean", "automation", "script", "fan")


_DOMAIN_LABELS = {
    "light": "Свет", "climate": "Климат", "switch": "Переключатели",
    "fan": "Вентиляторы", "media_player": "Медиа", "cover": "Шторы",
    "lock": "Замки", "sensor": "Датчики",
}


def _tg_groups() -> list[dict]:
    """Пользовательские группы Telegram-меню: [{"name","icon","entities":[...]}].
    Элемент entities — строка (entity_id, исторический формат) или {"id","title"} —
    объект с кастомным названием кнопки."""
    groups = app.config.get("tg_groups") or []
    if not isinstance(groups, list):
        return []
    valid = {e["entity_id"] for e in _entities()}
    out = []
    for g in groups:
        if not isinstance(g, dict):
            continue
        name = str(g.get("name") or "").strip()
        if not name:
            continue
        ents = []
        for x in (g.get("entities") or []):
            if isinstance(x, dict):
                eid = str(x.get("id") or "").strip()
                title = str(x.get("title") or "").strip()
            else:
                eid = str(x).strip()
                title = ""
            if eid in valid:
                ents.append({"id": eid, "title": title})
        out.append({
            "name": name,
            "icon": str(g.get("icon") or "▪"),
            "entities": ents,
        })
    return out


def _assigned_ids() -> set[str]:
    """Все entity_id, попавшие в пользовательские группы (для исключения из «остального»)."""
    out: set[str] = set()
    for g in _tg_groups():
        out.update(it["id"] for it in g["entities"])
    return out


def _domain_ids(domain: str) -> list[str]:
    """Все сущности домена (для fallback-режима, когда группы не настроены)."""
    if domain == "switch":
        extras = ("input_boolean", "automation")
    elif domain == "fan":
        extras = ("humidifier",)
    else:
        extras = (domain,)
    return [e["entity_id"] for e in _entities() if e["domain"] in extras]


def _sensor_ids() -> list[str]:
    """Датчики для раздела «Датчики»: только непривязанные к группам,
    если раздел включён параметром tg_show_sensors."""
    if not app.config.get("tg_show_sensors", True):
        return []
    assigned = _assigned_ids()
    return [e["entity_id"] for e in _entities()
            if e["domain"] in ("sensor", "binary_sensor") and e["entity_id"] not in assigned]


def _page_of(items: list[str], page: int) -> list[str]:
    return items[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]


async def _menu_main() -> dict:
    at = _CACHE["at"]
    tstamp = datetime.fromtimestamp(at, UTC).strftime("%H:%M:%S") if at else "—"
    lines = [
        "🏠 <b>Умный дом</b>",
        "",
        "🟢 Home Assistant" if _CACHE["ha_ok"] else "🔴 <b>Нет связи с Home Assistant</b>"
        + (f" — {_CACHE['error']}" if _CACHE["error"] else ""),
        f"⏱ Обновлено: {tstamp}",
    ]
    buttons = []
    groups = _tg_groups()
    if groups:
        # режим пользовательских групп: в главном меню только группы
        for i, g in enumerate(groups):
            if g["entities"]:
                buttons.append({"text": f"{g['icon']} {g['name']} ({len(g['entities'])})",
                                "action": f"hag:{i}"})
        if not buttons:
            lines.append("\nГруппы пусты — добавьте сущности в конфигураторе Telegram-меню")
    else:
        # fallback: показываем разделы по доменам
        for domain, label in _DOMAIN_SECTIONS:
            n = len(_domain_ids(domain))
            if n:
                buttons.append({"text": f"{label} ({n})", "action": f"hal:{domain}"})
    sensors = _sensor_ids()
    if sensors:
        buttons.append({"text": f"📊 Датчики ({len(sensors)})", "action": "hal:sensor"})
    buttons.append({"text": "🔄 Обновить", "action": "har"})
    return {"text": "\n".join(lines), "buttons": buttons}


def _pair_sensors(entities: list[dict]) -> list[dict]:
    """Группирует temperature+humidity датчики с общим базовым именем в один элемент.
    Возвращает список элементов: одиночные датчики или пары {type:'pair', temp, hum}."""
    by_base = {}
    suffixes = ("_temperature", "_humidity", "_temp", "_hum")
    for e in entities:
        if e["domain"] not in ("sensor", "binary_sensor"):
            continue
        base = e["entity_id"]
        for sfx in suffixes:
            if base.endswith(sfx):
                base = base[:-len(sfx)]
                break
        else:
            # не похож на температуру/влажность — оставляем как есть
            continue
        by_base.setdefault(base, {})[e["entity_id"].split(".")[-1]] = e
    used = set()
    result = []
    for base, parts in by_base.items():
        if "temperature" in parts and "humidity" in parts:
            result.append({"type": "pair", "temp": parts["temperature"], "hum": parts["humidity"]})
            used.add(parts["temperature"]["entity_id"])
            used.add(parts["humidity"]["entity_id"])
        else:
            for e in parts.values():
                if e["entity_id"] not in used:
                    result.append(e)
    # добавляем датчики, не подпавшие под суффиксы
    for e in entities:
        if e["domain"] in ("sensor", "binary_sensor") and e["entity_id"] not in used:
            result.append(e)
    return result


async def _menu_group(idx: int, page: int = 0) -> dict:
    groups = _tg_groups()
    if idx >= len(groups):
        return {"text": "❌ Группа не найдена", "buttons": [{"text": "◀ Назад", "action": "hamain"}]}
    g = groups[idx]
    ents = g["entities"]
    if not ents:
        return {"text": f"{g['icon']} <b>{g['name']}</b>\n\nПусто — добавьте сущности в конфигураторе.",
                "buttons": [{"text": "◀ Назад", "action": "hamain"}]}
    chunk = _page_of(ents, page)
    # маппинг entity_id -> it для title
    it_map = {it["id"]: it for it in chunk}
    # полные сущности чанка
    chunk_entities = []
    for it in chunk:
        e = _find(it["id"])
        if e:
            chunk_entities.append(e)
    # парсим температуру+влажность
    paired = _pair_sensors(chunk_entities)
    buttons = []
    for item in paired:
        if isinstance(item, dict) and item.get("type") == "pair":
            t = item["temp"]
            h = item["hum"]
            btn_text = f"🌡 {t['name'][:25]} — {t['state_str'][:20]}  💧 {h['state_str'][:15]}"
            buttons.append({"text": btn_text, "action": f"had:{_enc(t['entity_id'])}"})
        else:
            e = item
            it = it_map.get(e["entity_id"])
            title = it["title"] or e["name"] if it else e["name"]
            if e["domain"] in _TOGGLE_DOMAINS:
                act = "on" if e["state"] != "on" else "off"
                mark = "🟡" if e["state"] == "on" else "⚫"
                buttons.append({"text": f"{mark} {title[:40]}",
                                "action": f"hat:{_enc(e['entity_id'])}:{act}:g{idx}:{page}"})
            elif e["domain"] in ("sensor", "binary_sensor"):
                buttons.append({"text": f"{e['icon']} {title[:30]} — {e['state_str'][:30]}",
                                "action": f"had:{_enc(e['entity_id'])}"})
            else:
                buttons.append({"text": f"{e['icon']} {title[:40]}", "action": f"had:{_enc(e['entity_id'])}"})
    pairs = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    nav = []
    if page > 0:
        nav.append({"text": "◀", "action": f"hag:{idx}:{page - 1}"})
    nav.append({"text": "◀ Назад", "action": "hamain"})
    if (page + 1) * PAGE_SIZE < len(ents):
        nav.append({"text": "▶", "action": f"hag:{idx}:{page + 1}"})
    return {"text": f"{g['icon']} <b>{g['name']}</b> ({len(ents)})", "buttons": pairs + [nav]}


async def _menu_entity(entity_id: str) -> dict:
    e = _find(entity_id)
    if not e:
        return {"text": "❌ Сущность удалена или недоступна",
                "buttons": [{"text": "◀ Назад", "action": "hamain"}]}
    domain = e["domain"]
    code = _enc(entity_id)
    lines = [
        f"{e['icon']} <b>{e['name']}</b>",
        f"🗂 {entity_id.split('.')[0]}",
        f"Состояние: <b>{e['state_str']}</b>",
    ]
    if e.get("brightness_pct") is not None:
        lines.append(f"💡 Яркость: {e['brightness_pct']}%")
    if e.get("temperature") is not None:
        lines.append(f"🎯 Цель: {e['temperature']}°C")
    if e.get("current_temperature") is not None:
        lines.append(f"🌡 Сейчас: {e['current_temperature']}°C")
    if e.get("volume_pct") is not None:
        lines.append(f"🔊 Громкость: {e['volume_pct']}%")

    buttons = []
    if domain in ("light", "switch", "input_boolean", "automation", "script", "fan"):
        buttons.append({"text": "⏻ Вкл", "action": f"hac:{code}:on"})
        buttons.append({"text": "⏼ Выкл", "action": f"hac:{code}:off"})
        buttons.append({"text": "⤴ Переключить", "action": f"hac:{code}:toggle"})
    if domain == "light":
        buttons.append({"text": "⬇ Яркость −", "action": f"hac:{code}:brightness_down"})
        buttons.append({"text": "⬆ Яркость +", "action": f"hac:{code}:brightness_up"})
    if domain == "climate":
        for m in ("heat", "cool", "auto", "dry", "fan_only", "off"):
            buttons.append({"text": f"🌡 {m}", "action": f"hac:{code}:hvac:{m}"})
        buttons.append({"text": "❄ −температура", "action": f"hac:{code}:temp_down"})
        buttons.append({"text": "☀ +температура", "action": f"hac:{code}:temp_up"})
    if domain == "fan":
        buttons.append({"text": "🌀 Скорость −", "action": f"hac:{code}:speed_down"})
        buttons.append({"text": "🌀 Скорость +", "action": f"hac:{code}:speed_up"})
    if domain == "media_player":
        buttons.append({"text": "▶ Воспроизвести", "action": f"hac:{code}:play"})
        buttons.append({"text": "⏸ Пауза", "action": f"hac:{code}:pause"})
        buttons.append({"text": "➖ Громкость", "action": f"hac:{code}:vol_down"})
        buttons.append({"text": "➕ Громкость", "action": f"hac:{code}:vol_up"})
    if domain == "cover":
        buttons.append({"text": "🔼 Открыть", "action": f"hac:{code}:open"})
        buttons.append({"text": "🔽 Закрыть", "action": f"hac:{code}:close"})
    if domain == "lock":
        buttons.append({"text": "🔒 Закрыть", "action": f"hac:{code}:lock"})
        buttons.append({"text": "🔓 Открыть", "action": f"hac:{code}:unlock"})
    # «Назад» ведёт в группу (если сущность в группе) или в раздел домена
    back = f"hal:{domain}"
    for i, g in enumerate(_tg_groups()):
        if any(it["id"] == entity_id for it in g["entities"]):
            back = f"hag:{i}"
            break
    buttons.append({"text": "◀ Назад", "action": back})
    return {"text": "\n".join(lines), "buttons": buttons}


async def _menu_domain_list(domain: str, page: int = 0) -> dict:
    ids = _domain_ids(domain)
    if domain == "sensor":
        assigned = _assigned_ids()
        ids = [eid for eid in _sensor_ids() if eid not in assigned]
    if not ids:
        return {"text": "В этой категории пусто", "buttons": [{"text": "◀ Назад", "action": "hamain"}]}
    icon = {"light": "💡", "climate": "🌡", "switch": "🔌", "fan": "🌀",
            "media_player": "📺", "cover": "🪟", "lock": "🔒", "sensor": "📊"}.get(domain, "▪")
    chunk = _page_of(ids, page)
    # собираем сущности чанка
    chunk_entities = []
    for eid in chunk:
        e = _find(eid)
        if e:
            chunk_entities.append(e)
    paired = _pair_sensors(chunk_entities)
    buttons = []
    for item in paired:
        if isinstance(item, dict) and item.get("type") == "pair":
            t = item["temp"]
            h = item["hum"]
            btn_text = f"🌡 {t['name'][:25]} — {t['state_str'][:20]}  💧 {h['state_str'][:15]}"
            buttons.append({"text": btn_text, "action": f"had:{_enc(t['entity_id'])}"})
        else:
            e = item
            if e["domain"] in _TOGGLE_DOMAINS:
                act = "on" if e["state"] != "on" else "off"
                mark = "🟡" if e["state"] == "on" else "⚫"
                buttons.append({"text": f"{mark} {e['name'][:40]}",
                                "action": f"hat:{_enc(eid)}:{act}:d{domain}:{page}"})
            elif e["domain"] in ("sensor", "binary_sensor"):
                buttons.append({"text": f"{e['icon']} {e['name'][:30]} — {e['state_str'][:30]}",
                                "action": f"had:{_enc(eid)}"})
            else:
                buttons.append({"text": f"{e['icon']} {e['name'][:40]}", "action": f"had:{_enc(eid)}"})
    pairs = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    nav = []
    if page > 0:
        nav.append({"text": "◀", "action": f"hal:{domain}:{page - 1}"})
    nav.append({"text": "◀ Назад", "action": "hamain"})
    if (page + 1) * PAGE_SIZE < len(ids):
        nav.append({"text": "▶", "action": f"hal:{domain}:{page + 1}"})
    return {"text": f"{icon} <b>{_DOMAIN_LABELS.get(domain, domain)}</b> ({len(ids)})", "buttons": pairs + [nav]}


# ── HTTP API ──────────────────────────────────────────────────────────────────

@app.get("/status")
async def status():
    cfg = _ha_base()
    tok = bool((app.config.get("ha_token") or "").strip())
    return {
        "ok": _CACHE["ha_ok"] and bool(cfg),
        "configured": bool(cfg and tok),
        "ha_url": cfg,
        "cached_at": _CACHE["at"],
        "cached": bool(_CACHE["list"]),
        "count": len(_CACHE["list"]),
        "last_error": _CACHE["error"],
    }


@app.get("/api/entities")
async def api_entities(force: int = 0):
    if force or time.time() - _CACHE["at"] > CACHE_TTL:
        if not _BUSY:
            await _refresh()
    return {
        "ok": _CACHE["ha_ok"],
        "cache_age": round(time.time() - _CACHE["at"], 1),
        "count": len(_CACHE["list"]),
        "entities": _CACHE["list"],
    }


@app.post("/api/control")
async def api_control(body: dict):
    eid = (body.get("entity_id") or "").strip()
    action = (body.get("action") or "").strip()
    value = body.get("value") or ""
    if not eid or not action:
        return {"ok": False, "error": "укажите entity_id и action"}
    ok, msg = await _control(eid, action, str(value))
    if ok:
        await _refresh()
    return {"ok": ok, "entity_id": eid, "action": action, "message": msg}


@app.post("/api/refresh")
async def api_refresh():
    await _refresh()
    return {"ok": _CACHE["ha_ok"], "count": len(_CACHE["list"]),
            "cached_at": _CACHE["at"]}


# ── Контракт бота ─────────────────────────────────────────────────────────────

@app.post("/bot/callback")
async def bot_callback(body: dict):
    action = body.get("action") or "hamain"
    try:
        if action == "hamain":
            return await _menu_main()
        if action == "har":
            await _refresh()
            return await _menu_main()
        if action.startswith("hag:"):
            parts = action.split(":")
            idx = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
            page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
            return await _menu_group(idx, page)
        if action.startswith("hal:"):
            parts = action.split(":")
            domain = parts[1]
            page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
            return await _menu_domain_list(domain, page)
        if action.startswith("had:"):
            return await _menu_entity(_dec(action.split(":", 1)[1]))
        if action.startswith("hat:"):
            # прямой тумблер из списка: переключаем и перерисовываем тот же список
            parts = action.split(":")
            code, act = parts[1], parts[2]
            ctx = parts[3] if len(parts) > 3 else ""
            page = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0
            eid = _dec(code)
            ok, msg = await _control(eid, act, "")
            if ok:
                await _sync_after(eid, act)
            else:
                await _refresh()
            if ctx.startswith("g") and ctx[1:].isdigit():
                menu = await _menu_group(int(ctx[1:]), page)
            elif ctx.startswith("d"):
                menu = await _menu_domain_list(ctx[1:], page)
            else:
                menu = await _menu_main()
            if not ok:
                menu["text"] = "❌ " + msg + "\n\n" + menu["text"]
            return menu
        if action.startswith("hac:"):
            parts = action.split(":")
            code, act = parts[1], parts[2]
            value = parts[3] if len(parts) > 3 else ""
            eid = _dec(code)
            ok, msg = await _control(eid, act, value)
            if ok:
                await _sync_after(eid, act)
            else:
                await _refresh()
            menu = await _menu_entity(eid)
            head = "✅ " if ok else "❌ "
            menu["text"] = head + msg + "\n\n" + menu["text"]
            return menu
    except Exception as e:
        app.logger.exception("callback %s: %r", action, e)
        return {"text": f"⚠ Ошибка: {e}", "buttons": [{"text": "◀ Главное меню", "action": "hamain"}]}
    return await _menu_main()


# ── Жизненный цикл ───────────────────────────────────────────────────────────

_last_poll: float = 0.0


@app.periodic(interval=30)
async def _scheduler():
    """Периодическое обновление состояний (интервал из конфига, не чаще poll_seconds)."""
    global _last_poll
    interval = max(int(app.config.get("poll_seconds") or 30), 5)
    now = time.monotonic()
    if now - _last_poll < interval:
        return
    _last_poll = now
    try:
        await _refresh()
    except Exception as e:
        app.logger.warning("refresh: %s", e)


if __name__ == "__main__":
    app.run()
