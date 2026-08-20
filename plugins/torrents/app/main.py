"""
Torrents Plugin — менеджер загрузок Home.Media v4.

Возможности:
- qBittorrent: список, добавление (magnet/.torrent) с категорией, пауза/резюме/удаление
- Поиск раздач через Prowlarr (индексер-агрегатор: сам обходит Cloudflare, капчи и куки)
- Подписки на сериалы (TMDB): авто-поиск и закачка новых эпизодов
- Telegram-меню через бота-хаб + веб-страница конфигурации
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import Counter
from datetime import datetime, UTC, date
from pathlib import Path

import httpx

from plugin_sdk import PluginApp, DATA_DIR, resolve_plugin, PLUGIN_ID

# ── Уведомления о завершённых загрузках ───────────────────────────────────────

_completed_seen: dict[str, float] = {}


class _TorrentsApp(PluginApp):
    """Запоминает уже завершённые торренты при старте, чтобы не спамить уведомлениями."""

    async def on_startup(self):
        try:
            torrents = await qbit_list()
            now = time.time()
            for t in torrents:
                if t.get("progress", 0) >= 1.0:
                    _completed_seen[t.get("hash") or t.get("name") or ""] = now
        except Exception as e:
            app.logger.warning("notify baseline: %s", e)


app = _TorrentsApp(
    "torrents",
    "1.0.0",
    "Менеджер загрузок: qBittorrent, поиск через Prowlarr, подписки на новые эпизоды",
    web_dir=Path(__file__).parent / "web",
    config={
        "qbit_url":   {"type": "str",    "default": "http://127.0.0.1:8085", "label": "qBittorrent WebUI URL"},
        "qbit_user":  {"type": "str",    "default": "admin", "label": "qBittorrent логин"},
        "qbit_pass":  {"type": "secret", "default": "", "label": "qBittorrent пароль"},
        "tmdb_token": {"type": "secret", "default": "", "label": "TMDB API-ключ (v4, bearer)"},
        "prowlarr_url": {"type": "str",    "default": "", "label": "Prowlarr URL (http://host:9696)"},
        "prowlarr_key": {"type": "secret", "default": "", "label": "Prowlarr API-ключ"},
        "categories":  {"type": "json", "default": ["Сериалы", "Кино", "Мультики", "Музыка"],
                        "label": "Категории загрузки (qBittorrent)"},
        "poll_minutes": {"type": "int", "default": 60, "label": "Проверка подписок, минут"},
        "notify_chat_id": {"type": "int", "default": 0, "label": "Telegram chat_id для уведомлений (0 = все разрешённые)"},
        "notify_completed": {"type": "bool", "default": True, "label": "Сообщать о завершённых загрузках"},
        "subs_max_age_days": {"type": "int", "default": 730, "label": "Искать эпизоды не старше N дней (0 = все)"},
        "subs_max_retries": {"type": "int", "default": 6, "label": "Сколько раз пробовать искать пропущенный эпизод"},
    },
)

SUBS_FILE = Path(DATA_DIR) / "sonarr_db.json"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

BROWSER_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.7",
    "Accept-Encoding": "gzip, deflate",
}

PAGE_SIZE = 5

# ── Утилиты ────────────────────────────────────────────────────────────────────

def fmt_size(b: int) -> str:
    for u in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024 or u == "TB":
            return f"{b:.1f} {u}" if u != "B" else f"{b} B"
        b /= 1024
    return f"{b:.1f} TB"


def detect_quality(title: str) -> str:
    t = (title or "").upper()
    if "2160" in t or "4K" in t or "UHD" in t:
        return "4K"
    if "1080" in t:
        return "1080p"
    if "720" in t:
        return "720p"
    if "WEB-DL" in t or "WEBRIP" in t or "WEB-DLRIP" in t:
        return "WEB-DL"
    if "BLURAY" in t or "BLU-RAY" in t or "BDRIP" in t or "REMUX" in t:
        return "BluRay"
    if "DVDRIP" in t or "DVD5" in t or "DVD9" in t:
        return "DVDRip"
    return "Other"


# Группы озвучки / переводов, встречающиеся в названиях раздач
VOICE_GROUPS = (
    ("LostFilm", ("lostfilm", "лостфильм")),
    ("AlexFilm", ("alexfilm",)),
    ("HDRezka", ("hdrezka", "hdrezka studio", "hdrezi")),
    ("Кубик в кубе", ("кубик в кубе",)),
    ("Kravec (Кравец)", ("kravec", "кравец", "кравець", "kravec records")),
    ("Amedia", ("amedia", "амедиа", "amedia tv")),
    ("Fox", ("foxlife", "fox life", "fox")),
    ("NewStudio", ("newstudio",)),
    ("FocusStudio", ("focusstudio",)),
    ("Jaskier", ("jaskier",)),
    ("Novamedia", ("novamedia",)),
    ("Novafilm", ("novafilm",)),
    ("OmskBird", ("omskbird",)),
    ("UATEAM", ("uateam",)),
    ("Рен ТВ", ("ren-tv", "ren tv", "рентв", "рен-тв", "рен тв", "ren-tv records")),
    ("Кириллица", ("кириллица", "kirillica")),
    ("TVShows", ("tvshows",)),
    ("RuDub", ("rudub",)),
    ("Кураж-Бамбей", ("кураж-бамбей", "кураж бамбей", "curage")),
    ("Studio Bayrak", ("bayrak",)),
    ("Пифагор", ("пифагор",)),
    ("GreenРай", ("greenрай", "green ray")),
    ("Solod", ("solod",)),
    ("ColdFilm", ("coldfilm",)),
    ("BaibaKo", ("baibako",)),
    ("Omicron", ("omicron",)),
    ("Ozz", ("ozz",)),
    ("AMS", ("ams",)),
    ("TET", ("tet",)),
    ("BBC", ("bbc",)),
    ("Red Head Sound", ("red head sound",)),
    ("Bravo Records", ("bravo records",)),
    ("ViruseProject", ("viruseproject",)),
    ("AlphaProject", ("alphaproject",)),
    ("ELEKTRI4KA", ("elektri4ka",)),
    ("KORSAR", ("korsar",)),
    ("Гоблин", ("гоблин",)),
    ("New-Team", ("new-team",)),
    ("SkyeFilmTV", ("skyefilmtv",)),
)

QUALITY_ORDER = ("4K", "1080p", "720p", "WEB-DL", "BluRay", "DVDRip", "Other")
TRANSLATION_ORDER = ("Дубляж", "Профессиональный (многоголосый)", "Двухголосый",
                     "Любительский (одноголосый)", "Любительский", "Одноголосый", "Авторский")

# Telegram callback_data допускает только [a-zA-Z0-9_-] — кириллицу шифруем в ASCII-коды
QUALITY_ALIAS = {"4K": "4k", "1080p": "1080p", "720p": "720p", "WEB-DL": "webdl",
                 "BluRay": "bluray", "DVDRip": "dvdrip", "Other": "other", "Все": "all"}
QUALITY_UNALIAS = {v: k for k, v in QUALITY_ALIAS.items()}

_TSID = {
    "Дубляж": "dub", "Профессиональный (многоголосый)": "mvo", "Двухголосый": "dvo",
    "Любительский (одноголосый)": "one", "Любительский": "fan", "Одноголосый": "mono",
    "Авторский": "avto",
    "LostFilm": "lostfilm", "AlexFilm": "alexfilm", "HDRezka": "hdrezka",
    "Кубик в кубе": "kubik", "Kravec (Кравец)": "kravec", "Amedia": "amedia",
    "Fox": "fox", "NewStudio": "newstudio", "FocusStudio": "focusstudio",
    "Jaskier": "jaskier", "Novamedia": "novamedia", "Novafilm": "novafilm",
    "OmskBird": "omskbird", "UATEAM": "uateam", "Рен ТВ": "rentv", "Кириллица": "kirillica",
    "TVShows": "tvshows", "RuDub": "rudub", "Кураж-Бамбей": "kurash",
    "Studio Bayrak": "bayrak", "Пифагор": "pifagor", "GreenРай": "greenray",
    "Solod": "solod", "ColdFilm": "coldfilm", "BaibaKo": "baibako", "Omicron": "omicron",
    "Ozz": "ozz", "AMS": "ams", "TET": "tet", "BBC": "bbc",
    "Red Head Sound": "redhead", "Bravo Records": "bravo", "ViruseProject": "viruseproject",
    "AlphaProject": "alphaproject", "ELEKTRI4KA": "elektri4ka", "KORSAR": "korsar",
    "Гоблин": "goblin", "New-Team": "newteam", "SkyeFilmTV": "skyefilmtv",
    "Другое": "other", "Все": "all",
}
_TSID_R = {v: k for k, v in _TSID.items()}


def _tuid(name: str) -> str:
    return _TSID.get(name, name)


def _tuname(tuid: str) -> str:
    return _TSID_R.get(tuid, tuid)


def _word_in(t: str, kw: str) -> bool:
    """Совпадение слова/аббревиатуры с границами (для коротких ключей)."""
    return re.search(rf"(?<![a-zа-яё0-9]){re.escape(kw)}(?![a-zа-яё0-9])", t) is not None


def detect_translation(title: str) -> str:
    """Определяет перевод (категорию или группу озвучки) по названию раздачи."""
    t = (title or "").lower()
    if any(k in t for k in ("дубляж", "дублирован")) or _word_in(t, "dub"):
        return "Дубляж"
    if "авторский" in t:
        return "Авторский"
    if "любительский" in t and "одноголосый" in t:
        return "Любительский (одноголосый)"
    if "любительский" in t:
        return "Любительский"
    if ("профессиональный" in t or ("многоголосый" in t and "любительский" not in t)
            or _word_in(t, "mvo")):
        return "Профессиональный (многоголосый)"
    if "двухголосый" in t or _word_in(t, "dvo"):
        return "Двухголосый"
    if "одноголосый" in t:
        return "Одноголосый"
    studios = detect_studios(title)
    if studios:
        return next(iter(studios))
    if _word_in(t, "d"):
        return "Дубляж"
    if _word_in(t, "p"):
        return "Профессиональный (многоголосый)"
    return "Другое"


def detect_studios(title: str) -> set[str]:
    """Все студии озвучки в названии (мульти-озвучка вида «AlexFilm, LostFilm, …»)."""
    t = (title or "").lower()
    found: set[str] = set()
    for name, keys in VOICE_GROUPS:
        for k in keys:
            if (_word_in(t, k) if len(k) <= 4 else k in t):
                found.add(name)
                break
    return found


def parse_episode_cover(title: str) -> dict | None:
    """Покрытие эпизодов раздачей: {'s': int|None (любой сезон), 'e1': int, 'e2': int}.

    Понимает S01E03, S8E1-6 of 6, S1-8E1-73 of 73, 1x03, «Сезон 1 Серия 2-3».
    """
    t = title or ""
    m = re.search(r"[Ss](\d{1,2})-(\d{1,2})[Ee](\d{1,2})-(\d{1,2})", t)
    if m:
        return {"s": None, "e1": int(m.group(3)), "e2": int(m.group(4))}
    m = re.search(r"[Ss](\d{1,2})[Ee](\d{1,2})(?:-E?(\d{1,2}))?(?:\s+of\s+\d+)?", t)
    if m:
        sn = int(m.group(1))
        e1 = int(m.group(2))
        e2 = int(m.group(3)) if m.group(3) else e1
        return {"s": sn, "e1": e1, "e2": e2}
    m = re.search(r"(?:^|[^\w])?(\d{1,2})[xX](\d{1,2})", t)
    if m:
        e = int(m.group(2))
        return {"s": int(m.group(1)), "e1": e, "e2": e}
    m = re.search(r"Сезон[^\d]*(\d{1,2})[^\d]*Серия[^\d]*(\d{1,2})(?:[^\d]+(\d{1,2}))?", t, re.IGNORECASE)
    if m:
        sn = int(m.group(1))
        e1 = int(m.group(2))
        e2 = int(m.group(3)) if m.group(3) else e1
        return {"s": sn, "e1": e1, "e2": e2}
    return None


def cover_matches(cover: dict | None, s: int, e: int) -> bool:
    if not cover:
        return False
    if cover["s"] is not None and cover["s"] != s:
        return False
    return cover["e1"] <= e <= cover["e2"]


def parse_season_episode(title: str) -> tuple[int | None, int | None]:
    m = re.search(r"[Ss](\d{1,2})[Ee](\d{1,2})", title)
    if m:
        return int(m.group(1)), int(m.group(2))
    m2 = re.search(r"(\d{1,2})[xX](\d{1,2})", title)
    if m2:
        return int(m2.group(1)), int(m2.group(2))
    m3 = re.search(r"Сезон[^\d]*(\d{1,2})[^\d]*Серия[^\d]*(\d{1,2})", title, re.IGNORECASE)
    if m3:
        return int(m3.group(1)), int(m3.group(2))
    return None, None


# ── qBittorrent ────────────────────────────────────────────────────────────────

async def qbit_client() -> httpx.AsyncClient | None:
    url = (app.config.get("qbit_url") or "").strip()
    pwd = app.config.get("qbit_pass") or ""
    if not url or not pwd:
        return None
    c = httpx.AsyncClient(base_url=url.rstrip("/"), timeout=15.0)
    try:
        r = await c.post("/api/v2/auth/login", data={
            "username": app.config.get("qbit_user") or "",
            "password": pwd,
        })
        if r.status_code != 200 or r.text.strip() != "Ok.":
            app.logger.warning("qBittorrent login failed: %s", r.status_code)
            await c.aclose()
            return None
        return c
    except Exception as e:
        app.logger.warning("qBittorrent недоступен: %s", e)
        await c.aclose()
        return None


async def qbit_list() -> list[dict]:
    c = await qbit_client()
    if not c:
        return []
    try:
        r = await c.get("/api/v2/torrents/info")
        if r.status_code != 200:
            return []
        return r.json()
    finally:
        await c.aclose()


async def qbit_add(url: str, category: str) -> bool:
    c = await qbit_client()
    if not c:
        return False
    try:
        r = await c.post("/api/v2/torrents/add", data={"urls": url, "category": category})
        return r.status_code == 200 and r.text.strip() == "Ok."
    finally:
        await c.aclose()


async def qbit_add_file(data: bytes, category: str, filename: str = "add.torrent") -> bool:
    c = await qbit_client()
    if not c:
        return False
    try:
        r = await c.post("/api/v2/torrents/add",
                         data={"category": category},
                         files={"torrents": (filename, data, "application/x-bittorrent")})
        return r.status_code == 200 and r.text.strip() == "Ok."
    finally:
        await c.aclose()


async def qbit_action(action: str, hashes: str = "all") -> bool:
    c = await qbit_client()
    if not c:
        return False
    try:
        r = await c.post(f"/api/v2/torrents/{action}", data={"hashes": hashes})
        return r.status_code == 200
    finally:
        await c.aclose()


async def qbit_ensure_categories() -> None:
    for cat in app.config.get("categories") or []:
        c = await qbit_client()
        if not c:
            return
        try:
            await c.post("/api/v2/torrents/createCategory", data={"category": str(cat)})
        except Exception:
            pass
        finally:
            await c.aclose()


async def _http_bytes(url: str) -> bytes | None:
    """Скачивает .torrent файл по прямой ссылке."""
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, headers=BROWSER_HEADERS) as c:
            r = await c.get(url)
            if r.status_code == 200 and (r.content.lstrip().startswith(b"d8:announce")
                                         or r.headers.get("content-type", "").startswith("application/x-bittorrent")):
                return r.content
            app.logger.warning("download %s HTTP %s ct=%s", url, r.status_code, r.headers.get("content-type", ""))
            return None
    except Exception as e:
        app.logger.warning("download %s: %r", url, e)
        return None


async def _add_to_qbit(item: dict, category: str) -> bool:
    """Добавляет раздачу в qBittorrent: magnet — по ссылке, иначе .torrent файлом."""
    url = (item.get("download_url") or "").strip()
    if not url:
        return False
    if url.startswith("magnet:"):
        return await qbit_add(url, category)
    if _prowlarr_base() and "/api/v1/" in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}apikey={app.config.get('prowlarr_key') or ''}"
    data = await _http_bytes(url)
    if data is not None:
        return await qbit_add_file(data, category)
    return await qbit_add(url, category)


# ── Prowlarr ───────────────────────────────────────────────────────────────────

def _prowlarr_base() -> str:
    return (app.config.get("prowlarr_url") or "").strip().rstrip("/")


async def _prowlarr_get(path: str, params: dict | None = None) -> object | None:
    base = _prowlarr_base()
    if not base:
        return None
    try:
        async with httpx.AsyncClient(timeout=30.0, headers={"Accept": "application/json"}) as c:
            r = await c.get(base + path, params={**(params or {}), "apikey": app.config.get("prowlarr_key") or ""})
            if r.status_code == 200:
                return r.json()
            app.logger.warning("prowlarr %s HTTP %s", path, r.status_code)
            return None
    except Exception as e:
        app.logger.warning("prowlarr %s: %r", path, e)
        return None


def _row(title: str, size: int, seeds: int, leeches: int, page_url: str,
         download_url: str, indexer: str = "prowlarr", tmdb_id: int = 0) -> dict:
    return {
        "tracker": "prowlarr",
        "indexer": indexer,
        "title": title.strip(),
        "size": size,
        "size_text": fmt_size(size) if size else "",
        "seeds": int(seeds or 0),
        "leeches": int(leeches or 0),
        "quality": detect_quality(title),
        "url": page_url,
        "download_url": download_url,
        "tmdb_id": int(tmdb_id or 0),
    }


_BAD_EXT = re.compile(
    r"\[(?:PDF|FB2|EPUB|DJVU|CHM|MOBI|AZW3|MP3|FLAC|AAC|M4A|M4B|OGG|WAV|APE|TXT|EXE|ISO|APK|RAR)\b",
    re.IGNORECASE)


async def search_prowlarr(query: str) -> list[dict]:
    data = await _prowlarr_get("/api/v1/search", {"query": query, "limit": "50"})
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    for rel in data:
        title = (rel.get("title") or "").strip()
        if not title:
            continue
        if _BAD_EXT.search(title):
            continue
        dl = (rel.get("magnetUrl") or "").strip()
        if not dl and rel.get("downloadUrl"):
            dl = rel["downloadUrl"].strip()
        if not dl and rel.get("guid"):
            dl = f"{_prowlarr_base()}/api/v1/release/{rel['guid']}/download"
        out.append(_row(
            title,
            int(rel.get("size") or 0),
            int(rel.get("seeders") or 0),
            int(rel.get("leechers") or 0),
            rel.get("infoUrl") or "",
            dl,
            rel.get("indexer") or "prowlarr",
            rel.get("tmdbId") or 0,
        ))
    out.sort(key=lambda x: x["seeds"], reverse=True)
    return out


async def trackers_search(query: str) -> list[dict]:
    """Поиск через Prowlarr. Возвращает результаты, отсортированные по сидам."""
    return await search_prowlarr(query)


# ── TMDB ───────────────────────────────────────────────────────────────────────

TMDB_API = "https://api.themoviedb.org/3"


async def _tmdb(path: str, params: dict | None = None) -> dict | None:
    token = (app.config.get("tmdb_token") or "").strip()
    if not token:
        return None
    hdrs = {"Accept": "application/json"}
    q = {**(params or {})}
    if token.startswith("eyJ"):
        hdrs["Authorization"] = f"Bearer {token}"
    else:
        q["api_key"] = token
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.get(f"{TMDB_API}{path}", params=q, headers=hdrs)
            if r.status_code != 200:
                app.logger.warning("TMDB %s HTTP %s", path, r.status_code)
                return None
            return r.json()
    except Exception as e:
        app.logger.warning("TMDB request: %s", e)
        return None


_POSTER_CACHE: dict[int, str] = {}


async def _tmdb_poster(tmdb_id: int) -> str:
    """Постер TMDB по tmdb_id (movie или tv). Возвращает URL или пустую строку."""
    if not tmdb_id:
        return ""
    if tmdb_id in _POSTER_CACHE:
        return _POSTER_CACHE[tmdb_id]
    url = ""
    data = await _tmdb(f"/find/{tmdb_id}", {"external_source": "tmdb_id", "language": "ru-RU"})
    for kind in ("movie", "tv"):
        for r in (data or {}).get(kind, []) or []:
            path = r.get("poster_path")
            if path:
                url = f"https://image.tmdb.org/t/p/w500{path}"
                break
        if url:
            break
    _POSTER_CACHE[tmdb_id] = url
    return url


async def _show_poster(show: dict) -> str:
    path = show.get("poster") or ""
    return f"https://image.tmdb.org/t/p/w500{path}" if path else ""


async def _st_poster(st: dict) -> str:
    """Постер текущего поиска (кэшируется в стейте)."""
    if st.get("poster") is not None:
        return st["poster"]
    url = ""
    for r in st["rows"]:
        url = await _tmdb_poster(r.get("tmdb_id") or 0)
        if not url:
            url = await _tmdb_poster_by_title(r.get("title") or "")
        if url:
            break
    st["poster"] = url
    return url


_TITLE_POSTER_CACHE: dict[str, str] = {}

_TITLE_CLEAN = re.compile(r"\[[^\]]*\]|\([^)]*\)|\[.*?\[|\b(?:WEB[- ]?RIP|BDRip|BDRemux|REMUX|HDRip|DVDRip|BluRay|WEB-DL|UHD|2160p|1080p|720p|HEVC|H\.264|H\.265|AVC|AV1|x264|x265|10-bit|8-bit)\b", re.IGNORECASE)


async def _tmdb_poster_by_title(title: str) -> str:
    """Постер TMDB по названию раздачи (Prowlarr часто не отдаёт tmdbId/imdbId)."""
    if not title:
        return ""
    t = re.sub(r"\[[^\]]*\]", " ", title)
    t = re.sub(r"\([^)]*\)", " ", t)
    t = " ".join(t.split())
    base = t.split(" / ")[0].strip() if " / " in t else t
    if not base:
        return ""
    if base in _TITLE_POSTER_CACHE:
        return _TITLE_POSTER_CACHE[base]
    url = ""
    for scope in (("multi", None), ):
        data = await _tmdb(f"/search/{scope[0]}", {"query": base, "language": "ru-RU"})
        for r in (data or {}).get("results", []) or []:
            path = r.get("poster_path")
            if path:
                url = f"https://image.tmdb.org/t/p/w500{path}"
                break
        if url:
            break
    _TITLE_POSTER_CACHE[base] = url
    return url


async def tmdb_search_tv(query: str) -> list[dict]:
    data = await _tmdb("/search/tv", {"query": query, "language": "ru-RU"})
    out = []
    for r in (data or {}).get("results", [])[:8]:
        out.append({
            "tmdb_id": r["id"],
            "title": r.get("name", ""),
            "title_orig": r.get("original_name", ""),
            "poster": r.get("poster_path") or "",
            "year": (r.get("first_air_date") or "")[:4],
        })
    return out


async def tmdb_seasons(tmdb_id: int) -> dict[int, int]:
    data = await _tmdb(f"/tv/{tmdb_id}", {"language": "ru-RU"})
    out: dict[int, int] = {}
    for s in (data or {}).get("seasons", []):
        sn = s.get("season_number")
        if sn and sn >= 1:
            out[sn] = s.get("episode_count") or 0
    return out


async def tmdb_episode_airdates(tmdb_id: int, season: int) -> dict[int, str]:
    """Эпизоды сезона: номер → дата выхода (YYYY-MM-DD) с TMDB."""
    data = await _tmdb(f"/tv/{tmdb_id}/season/{season}", {"language": "ru-RU"})
    out: dict[int, str] = {}
    for ep in (data or {}).get("episodes", []) or []:
        n = ep.get("episode_number")
        if n:
            out[n] = ep.get("air_date") or ""
    return out


async def _season_air_status(sub: dict, sn: int) -> dict[int, str]:
    """Даты выхода сезона, кэшируются в подписке (ключ _airdata_{sn})."""
    cache_key = f"_airdata_{sn}"
    if cache_key not in sub:
        airdates = await tmdb_episode_airdates(sub.get("tmdb_id", 0), sn)
        if not airdates:
            sdata = sub.get("seasons", {}).get(str(sn), {})
            total = sdata.get("total", 0) or 0
            airdates = {ep: "" for ep in range(1, total + 1)}
        sub[cache_key] = airdates
    return sub[cache_key]


# ── Подписки ───────────────────────────────────────────────────────────────────

def _load_subs() -> dict[str, dict]:
    if SUBS_FILE.exists():
        try:
            return json.loads(SUBS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_subs(data: dict) -> None:
    try:
        SUBS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SUBS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        app.logger.error("save subs: %s", e)


def _sub_key(tmdb_id: int) -> str:
    return f"tmdb:{tmdb_id}"


async def sub_add(show: dict, quality: str, category: str) -> tuple[bool, str]:
    seasons_info = await tmdb_seasons(show["tmdb_id"])
    subs = _load_subs()
    key = _sub_key(show["tmdb_id"])
    if key in subs:
        subs[key]["quality"] = quality
        subs[key]["category"] = category
        subs[key]["status"] = "active"
        for sn, total in seasons_info.items():
            subs[key]["seasons"].setdefault(str(sn), {"total": total, "downloaded": [], "queued": []})
            subs[key]["seasons"][str(sn)]["total"] = total
        _save_subs(subs)
        return True, "✅ Уже отслеживается, настройки обновлены"
    subs[key] = {
        "tmdb_id": show["tmdb_id"],
        "title": show["title"],
        "title_orig": show.get("title_orig", show["title"]),
        "poster": show.get("poster", ""),
        "quality": quality,
        "category": category,
        "status": "active",
        "seasons": {str(sn): {"total": total, "downloaded": [], "queued": []} for sn, total in seasons_info.items()},
        "added_at": datetime.now(UTC).isoformat(),
    }
    _save_subs(subs)
    return False, f"✅ «{show['title']}» добавлен в отслеживание"


async def notify_telegram(text: str, chat_id: int = 0, photo: str = "",
                          buttons: list | None = None) -> None:
    hub = await resolve_plugin("telegram_bot")
    if not hub:
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            await c.post(f"{hub['url']}/bot/notify", json={
                "text": text,
                "chat_id": chat_id,
                "plugin_id": PLUGIN_ID,
                "photo": photo,
                "buttons": buttons or [],
            })
    except Exception as e:
        app.logger.warning("notify: %s", e)


async def check_subs(notify: bool = True) -> dict:
    """Следит за подписками: сверяет статус в qBittorrent (queued/downloaded),
    ставит недостающие эпизоды на закачку (в т.ч. мульти-эпизодные пакеты).

    Фильтры:
    - эпизоды, ещё не вышедшие (по TMDB air_date), не ищутся;
    - эпизоды старше subs_max_age_days (0 = без лимита) пропускаются;
    - эпизод, который не нашёлся subs_max_retries раз подряд, перестаёт искаться.
    """
    subs = _load_subs()
    if not subs:
        return {"scanned": 0, "added": 0, "skipped_old": 0}
    max_age_days = max(int(app.config.get("subs_max_age_days") or 730), 0)
    max_retries = max(int(app.config.get("subs_max_retries") or 6), 0)
    today = date.today()
    torrents = await qbit_list()
    covers: list[dict] = []
    for t in torrents:
        cover = parse_episode_cover(t.get("name") or "")
        if cover:
            covers.append({"cover": cover, "progress": t.get("progress") or 0.0})
    found_new = []
    completed = []
    added = 0
    skipped_old = 0
    for key, sub in subs.items():
        if sub.get("status") != "active":
            continue
        title = sub.get("title_orig") or sub.get("title") or ""
        if not title:
            continue
        results = await trackers_search(title)
        results.sort(key=lambda r: -(r.get("seeds") or 0))
        seasons_info = await tmdb_seasons(sub["tmdb_id"])
        for sn_str, sdata in sub.get("seasons", {}).items():
            sdata.setdefault("queued", [])
            sdata.setdefault("downloaded", [])
            total = seasons_info.get(int(sn_str), 0) or sdata.get("total", 0)
            sdata["total"] = total
        # Эпизоды, которые ещё стоит искать: вышедшие и не древнее лимита
        missing: list[tuple[int, int]] = []
        for sn_str, sdata in sub.get("seasons", {}).items():
            sn = int(sn_str)
            airdates = await _season_air_status(sub, sn)
            for ep in range(1, sdata.get("total", 0) + 1):
                aired = airdates.get(ep)
                if aired:
                    try:
                        aired_d = date.fromisoformat(aired[:10])
                    except ValueError:
                        aired_d = None
                    if aired_d and aired_d > today:
                        continue  # ещё не вышел — ждём релиза
                    if aired_d and max_age_days and (today - aired_d).days > max_age_days:
                        skipped_old += 1
                        continue  # древний эпизод — не ищем
                missing.append((sn, ep))
        # ── сверка с qBittorrent: в очереди / скачано ──
        for tc in covers:
            matched = [(s, e) for (s, e) in missing if cover_matches(tc["cover"], s, e)]
            if not matched:
                continue
            done = tc["progress"] >= 1.0
            for (s, e) in matched:
                sd = sub["seasons"].setdefault(
                    str(s), {"total": seasons_info.get(s, 0), "downloaded": [], "queued": []})
                queued = sd.get("queued", [])
                downloaded = sd.get("downloaded", [])
                if done:
                    if e not in downloaded:
                        downloaded.append(e)
                        if e in queued:
                            queued.remove(e)
                        completed.append(f"✅ <b>{sub['title']}</b> — S{s:02d}E{e:02d} скачано")
                elif e not in queued and e not in downloaded:
                    queued.append(e)
                missing.remove((s, e))
        for sn_str, sdata in sub.get("seasons", {}).items():
            sdata["downloaded"].sort()
            sdata["queued"].sort()
        if not missing:
            continue
        # ── поиск недостающего ──
        dead = sub.setdefault("_dead", {})  # счётчик неудачных поисков эпизода
        for r in results:
            if not r.get("download_url"):
                continue
            q = sub.get("quality") or "Any"
            if q != "Any" and r["quality"] not in ("Any", q) and not (
                    r["quality"] == "Other" and q == "Any"):
                continue
            cover = parse_episode_cover(r["title"])
            if not cover or (r.get("seeds") or 0) <= 0:
                continue
            matched = [(s, e) for (s, e) in missing if cover_matches(cover, s, e)]
            if not matched:
                continue
            ok = await _add_to_qbit(r, sub.get("category", "Сериалы"))
            if not ok:
                continue
            sn = matched[0][0]
            sd = sub["seasons"].setdefault(
                str(sn), {"total": seasons_info.get(sn, 0), "downloaded": [], "queued": []})
            for (s, e) in matched:
                if e not in sd.get("queued", []) and e not in sd.get("downloaded", []):
                    sd["queued"].append(e)
                missing.remove((s, e))
                dead.pop(f"{s}-{e}", None)  # найден — сбрасываем счётчик
            sd["queued"].sort()
            found_new.append(f"📺 <b>{sub['title']}</b> — S{sn:02d} · {r['title'][:70]}")
            added += 1
            _save_subs(subs)
            if not missing:
                break
        # Не найденные эпизоды: плюсуем счётчик, слишком «мёртвые» снимаем с поиска
        if missing:
            for (s, e) in list(missing):
                dead[f"{s}-{e}"] = dead.get(f"{s}-{e}", 0) + 1
                if max_retries and dead[f"{s}-{e}"] > max_retries:
                    dead.pop(f"{s}-{e}", None)
                    missing.remove((s, e))
                    skipped_old += 1
        # Мусор в счётчиках (эпизод, который давно сняли с поиска)
        for k in [k for k, v in dead.items() if v > max_retries + 10]:
            dead.pop(k, None)
        _save_subs(subs)
    if notify and found_new:
        await notify_telegram("⬇️ Найдены новые эпизоды, ставлю на закачку:\n"
                              + "\n".join(dict.fromkeys(found_new)),
                              int(app.config.get("notify_chat_id") or 0))
    if notify and completed:
        await notify_telegram("✅ Проверка по qBittorrent — скачано:\n"
                              + "\n".join(dict.fromkeys(completed)),
                              int(app.config.get("notify_chat_id") or 0))
    return {"scanned": len(subs), "added": added, "completed": len(set(completed)),
            "skipped_old": skipped_old}


async def _notify_finished() -> None:
    """Сообщает о торрентах, которые завершили закачку (прогресс 100%)."""
    if not app.config.get("notify_completed"):
        return
    torrents = await qbit_list()
    if not torrents:
        return
    now = time.time()
    fresh: list[dict] = []
    for t in torrents:
        if t.get("progress", 0) < 1.0:
            continue
        h = t.get("hash") or ""
        if not h or h in _completed_seen:
            continue
        _completed_seen[h] = now
        fresh.append(t)
    for h in [h for h, ts in list(_completed_seen.items()) if now - ts > 86400]:
        _completed_seen.pop(h, None)
    chat_id = int(app.config.get("notify_chat_id") or 0)
    for t in fresh[:5]:
        name = (t.get("name") or "?").strip()
        poster = await _tmdb_poster_by_title(name)
        text = f"✅ <b>Загрузка завершена:</b>\n{name[:200]}"
        await notify_telegram(
            text,
            chat_id=chat_id,
            photo=poster,
            buttons=[{"text": "📥 Список загрузок", "action": "list:0"}],
        )


@app.periodic(interval=30)
async def finished_scheduler():
    try:
        await _notify_finished()
    except Exception as e:
        app.logger.warning("notify_finished: %s", e)


# ── Telegram-меню (бот-хаб) ────────────────────────────────────────────────────

def _qbit_summary(torrents: list[dict]) -> str:
    dl = [t for t in torrents if "download" in (t.get("state") or "").lower()]
    com = [t for t in torrents if t.get("progress", 0) >= 1]
    up = sum(t.get("upspeed", 0) for t in torrents)
    dwn = sum(t.get("dlspeed", 0) for t in torrents)
    return (
        f"🧲 <b>Торренты</b>\n"
        f"Всего: <b>{len(torrents)}</b> · Качается: <b>{len(dl)}</b> · Раздаётся: <b>{len(com)}</b>\n"
        f"⬇ {fmt_size(dwn)}/с · ⬆ {fmt_size(up)}/с"
    )


def _torrent_line(t: dict) -> str:
    pct = int(t.get("progress", 0) * 100)
    state = "⏸" if "paused" in (t.get("state") or "") else ("⬇" if "download" in (t.get("state") or "").lower() else "📤")
    name = t.get("name", "?")[:45]
    spd = f" · {fmt_size(t.get('dlspeed', 0))}/с" if "download" in (t.get("state") or "").lower() else ""
    return f"{state} {name}\n    {pct}% · {fmt_size(t.get('size', 0))}{spd}"


_SEARCH_RESULTS: dict[int, dict[int, dict]] = {}
_TMDB_RESULTS: dict[int, list[dict]] = {}
_SEARCH_STATE: dict[int, dict] = {}


@app.post("/bot/callback")
async def bot_callback(body: dict):
    action = body.get("action") or "main"
    user_id = body.get("user_id")
    text = body.get("text") or ""

    if action == "main":
        torrents = await qbit_list()
        buttons = [
            {"text": "📥 Список загрузок", "action": "list:0"},
            {"text": "🔍 Поиск (Prowlarr)", "action": "search"},
            {"text": "📺 Подписки", "action": "subs:0"},
            {"text": "🧲 Добавить магнет", "action": "magnet"},
        ]
        if torrents:
            buttons.append({"text": "⏸ Пауза всем", "action": "pause_all"})
            buttons.append({"text": "▶ Продолжить все", "action": "resume_all"})
        return {"text": _qbit_summary(torrents), "buttons": buttons}

    # ── список загрузок ──
    if action.startswith("list:"):
        try:
            page = int(action.split(":")[1])
        except (IndexError, ValueError):
            page = 0
        torrents = await qbit_list()
        if not torrents:
            return {"text": "📥 Загрузок нет", "buttons": [{"text": "◀ Назад", "action": "main"}]}
        chunk = torrents[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
        lines = [f"📥 <b>Загрузки</b> (стр. {page + 1}):"] + [_torrent_line(t) for t in chunk]
        buttons = []
        for t in chunk:
            h = t.get("hash", "")[:16]
            state = t.get("state", "")
            if "paused" in state:
                buttons.append({"text": f"▶ {t.get('name', '?')[:30]}", "action": f"tor_resume:{h}"})
            else:
                buttons.append({"text": f"⏸ {t.get('name', '?')[:30]}", "action": f"tor_pause:{h}"})
            buttons.append({"text": f"🗑 {t.get('name', '?')[:24]}", "action": f"tor_del:{h}"})
        nav = []
        if page > 0:
            nav.append({"text": "◀", "action": f"list:{page - 1}"})
        nav.append({"text": "◀ Назад", "action": "main"})
        if (page + 1) * PAGE_SIZE < len(torrents):
            nav.append({"text": "▶", "action": f"list:{page + 1}"})
        return {"text": "\n".join(lines), "buttons": buttons + [nav]}

    for prefix in ("tor_pause", "tor_resume", "tor_del"):
        if action.startswith(prefix + ":"):
            h = action.split(":", 1)[1]
            act = {"tor_pause": "pause", "tor_resume": "resume", "tor_del": "delete"}[prefix]
            ok = await qbit_action(act, hashes=h)
            return {"text": "✅ Готово" if ok else "❌ qBittorrent не ответил",
                    "buttons": [{"text": "📥 Список", "action": "list:0"}, {"text": "◀ Назад", "action": "main"}]}

    if action == "pause_all":
        await qbit_action("pause")
        return {"text": "⏸ Пауза всем", "buttons": [{"text": "◀ Назад", "action": "main"}]}
    if action == "resume_all":
        await qbit_action("resume")
        return {"text": "▶ Продолжаю все", "buttons": [{"text": "◀ Назад", "action": "main"}]}

    # ── поиск ──
    if action == "search":
        return {
            "text": "🔍 <b>Поиск раздач</b>\n\nОтправьте название — найду через Prowlarr.",
            "await_text": "Введите название для поиска",
            "buttons": [{"text": "◀ Назад", "action": "main"}],
        }

    if action == "search_quality":
        st = _SEARCH_STATE.get(user_id)
        if not st:
            return {"text": "❌ Поиск устарел — начните заново",
                    "buttons": [{"text": "🔍 Поиск", "action": "search"}]}
        return await _search_quality_menu(user_id)

    if action.startswith("sq:"):
        q = QUALITY_UNALIAS.get(action.split(":", 1)[1], action.split(":", 1)[1])
        st = _SEARCH_STATE.get(user_id)
        if not st:
            return {"text": "❌ Поиск устарел — начните заново",
                    "buttons": [{"text": "🔍 Поиск", "action": "search"}]}
        st["quality"] = q
        rows = [r for r in st["rows"] if q == "Все" or r["quality"] == q]
        cat_counts = Counter(detect_translation(r["title"]) for r in rows)
        studio_counts = Counter(s for r in rows for s in detect_studios(r["title"]))
        buttons = []
        for name in TRANSLATION_ORDER:
            if cat_counts.get(name):
                buttons.append({"text": f"{name} ({cat_counts[name]})", "action": f"st:{_tuid(name)}"})
        groups = sorted(studio_counts.items(), key=lambda x: -x[1])
        for name, c in groups:
            buttons.append({"text": f"{name} ({c})", "action": f"st:{_tuid(name)}"})
        if cat_counts.get("Другое"):
            buttons.append({"text": f"Другое ({cat_counts['Другое']})", "action": "st:other"})
        buttons.append({"text": f"Все ({len(rows)})", "action": "st:all"})
        buttons.append({"text": "◀ Качество", "action": "search_quality"})
        return {
            "text": f"🔍 «{st['title'][:60]}» — {len(rows)} раздач · {q}\n\nВыберите перевод:",
            "buttons": buttons,
            "photo": await _st_poster(st),
        }

    if action.startswith("st:"):
        t = _tuname(action.split(":", 1)[1])
        st = _SEARCH_STATE.get(user_id)
        if not st:
            return {"text": "❌ Поиск устарел — начните заново",
                    "buttons": [{"text": "🔍 Поиск", "action": "search"}]}
        st["translation"] = t
        return await _show_search_results(user_id)

    if action == "text" and text:
        return await _handle_text(text, user_id)

    if action.startswith("dl:"):
        # dl:{idx} или dl:{idx}:c{n} → категория → скачать
        parts = action.split(":")
        if len(parts) == 2:
            return await _choose_category(_SEARCH_RESULTS.get(user_id, {}).get(int(parts[1])), parts[1])
        idx, cat = int(parts[1]), parts[2]
        cats = app.config.get("categories") or ["Сериалы"]
        if cat.startswith("c") and cat[1:].isdigit():
            ci = int(cat[1:])
            cat = cats[ci] if ci < len(cats) else cat
        item = _SEARCH_RESULTS.get(user_id, {}).get(int(idx))
        if not item:
            return {"text": "❌ Результат устарел — повторите поиск", "buttons": [{"text": "🔍 Поиск", "action": "search"}]}
        ok = await _add_to_qbit(item, cat)
        if ok:
            return {"text": f"✅ Добавлено: <b>{item['title'][:60]}</b>\n📂 Категория: {cat}",
                    "buttons": [{"text": "📥 Список", "action": "list:0"}, {"text": "🔍 Поиск", "action": "search"}]}
        return {"text": "❌ qBittorrent не ответил или раздача недоступна",
                "buttons": [{"text": "◀ Назад", "action": "main"}]}

    if action.startswith("dlc:"):
        idx = int(action.split(":")[1])
        return await _choose_category(_SEARCH_RESULTS.get(user_id, {}).get(idx), str(idx))

    # ── магнет ──
    if action == "magnet":
        return {
            "text": "🧲 Отправьте <b>magnet</b>-ссылку или адрес .torrent — скачаю в выбранную категорию.",
            "await_text": "Введите magnet-ссылку",
            "buttons": [{"text": "◀ Назад", "action": "main"}],
        }
    if action.startswith("mag:"):
        cat = action.split(":", 1)[1]
        cats = app.config.get("categories") or ["Сериалы"]
        if cat.startswith("c") and cat[1:].isdigit():
            ci = int(cat[1:])
            cat = cats[ci] if ci < len(cats) else cat
        item = _SEARCH_RESULTS.get(user_id, {}).get(-1)
        if not item:
            return {"text": "❌ Ссылка устарела", "buttons": [{"text": "◀ Назад", "action": "main"}]}
        ok = await _add_to_qbit(item, cat)
        return {"text": f"✅ {'Добавлено' if ok else 'Ошибка добавления'} · {cat}",
                "buttons": [{"text": "📥 Список", "action": "list:0"}, {"text": "◀ Назад", "action": "main"}]}

    # ── подписки ──
    if action.startswith("subs:"):
        try:
            page = int(action.split(":")[1])
        except (IndexError, ValueError):
            page = 0
        subs = list(_load_subs().values())
        if not subs:
            return {"text": "📺 <b>Подписки</b>\n\nПусто. Добавьте сериал — буду следить за новыми эпизодами.",
                    "buttons": [{"text": "➕ Добавить сериал", "action": "sub_add"}, {"text": "◀ Назад", "action": "main"}]}
        chunk = subs[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
        lines = [f"📺 <b>Подписки</b> ({len(subs)}):"]
        for s in chunk:
            ep = sum(len(sd.get("downloaded", [])) for sd in s.get("seasons", {}).values())
            que = sum(len(sd.get("queued", [])) for sd in s.get("seasons", {}).values())
            tot = sum(sd.get("total", 0) for sd in s.get("seasons", {}).values())
            st = "▶" if s.get("status") == "active" else "⏸"
            tail = f" ⬇{que}" if que else ""
            lines.append(f"{st} {s.get('title', '?')} — {ep}/{tot} эп.{tail}")
        buttons = []
        for s in chunk:
            key = _sub_key(s.get("tmdb_id", 0))
            if s.get("status") == "active":
                buttons.append({"text": f"⏸ {s.get('title', '?')[:28]}", "action": f"sub_pause:{key}"})
            else:
                buttons.append({"text": f"▶ {s.get('title', '?')[:28]}", "action": f"sub_resume:{key}"})
            buttons.append({"text": f"🗑 {s.get('title', '?')[:24]}", "action": f"sub_del:{key}"})
        nav = [{"text": "➕ Добавить", "action": "sub_add"}]
        if page > 0:
            nav.append({"text": "◀", "action": f"subs:{page - 1}"})
        nav.append({"text": "◀ Назад", "action": "main"})
        if (page + 1) * PAGE_SIZE < len(subs):
            nav.append({"text": "▶", "action": f"subs:{page + 1}"})
        return {"text": "\n".join(lines), "buttons": buttons + [nav]}

    if action == "sub_add":
        return {
            "text": "➕ Отправьте <b>название сериала</b> — найду на TMDB и добавлю в отслеживание.",
            "await_text": "Введите название сериала",
            "buttons": [{"text": "◀ Назад", "action": "subs:0"}],
        }
    if action.startswith("sub_sel:"):
        idx = int(action.split(":")[1])
        shows = _TMDB_RESULTS.get(user_id, [])
        if idx >= len(shows):
            return {"text": "❌ Устарело", "buttons": [{"text": "◀ Назад", "action": "subs:0"}]}
        show = shows[idx]
        buttons = [{"text": f"{q}", "action": f"sub_qual:{idx}:{q}"} for q in ("4K", "1080p", "720p", "Any")]
        return {"text": f"📺 <b>{show['title']}</b> ({show.get('year', '')})\n\nВыберите качество:",
                "buttons": buttons + [{"text": "◀ Назад", "action": "sub_add"}],
                "photo": await _show_poster(show)}
    if action.startswith("sub_qual:"):
        parts = action.split(":")
        idx, quality = int(parts[1]), parts[2]
        shows = _TMDB_RESULTS.get(user_id, [])
        if idx >= len(shows):
            return {"text": "❌ Устарело", "buttons": [{"text": "◀ Назад", "action": "subs:0"}]}
        cats = app.config.get("categories") or ["Сериалы"]
        return {"text": f"📺 <b>{shows[idx]['title']}</b> · {quality}\n\nКатегория:",
                "buttons": [{"text": cat, "action": f"sub_cat:{idx}:{quality}:c{ci}"} for ci, cat in enumerate(cats)],
                "photo": await _show_poster(shows[idx])}
    if action.startswith("sub_cat:"):
        parts = action.split(":", 3)
        idx, quality, cat = int(parts[1]), parts[2], parts[3]
        cats = app.config.get("categories") or ["Сериалы"]
        if cat.startswith("c") and cat[1:].isdigit():
            ci = int(cat[1:])
            cat = cats[ci] if ci < len(cats) else cat
        shows = _TMDB_RESULTS.get(user_id, [])
        if idx >= len(shows):
            return {"text": "❌ Устарело", "buttons": [{"text": "◀ Назад", "action": "subs:0"}]}
        existed, msg = await sub_add(shows[idx], quality, cat)
        return {"text": msg, "buttons": [{"text": "📺 Подписки", "action": "subs:0"}, {"text": "◀ Назад", "action": "main"}]}
    if action.startswith("sub_pause:") or action.startswith("sub_resume:") or action.startswith("sub_del:"):
        parts = action.split(":", 1)
        key = parts[1]
        subs = _load_subs()
        if key not in subs:
            return {"text": "❌ Подписка не найдена", "buttons": [{"text": "◀ Назад", "action": "subs:0"}]}
        if parts[0] == "sub_pause":
            subs[key]["status"] = "paused"
        elif parts[0] == "sub_resume":
            subs[key]["status"] = "active"
        else:
            del subs[key]
        _save_subs(subs)
        return {"text": "✅ Готово", "buttons": [{"text": "📺 Подписки", "action": "subs:0"}]}

    if action == "scan":
        res = await check_subs(notify=False)
        return {"text": f"🔎 Проверено подписок: <b>{res['scanned']}</b>, новых эпизодов поставлено: <b>{res['added']}</b>",
                "buttons": [{"text": "◀ Назад", "action": "main"}]}

    return {"text": "Неизвестное действие", "buttons": [{"text": "◀ Назад", "action": "main"}]}


async def _handle_text(text: str, user_id: int | None) -> dict:
    """Введённый текст: magnet / поиск / название сериала — решаем по контексту."""
    text = text.strip()
    if not user_id:
        return {"text": "❌ Ошибка", "buttons": [{"text": "◀ Назад", "action": "main"}]}

    if text.startswith("magnet:") or text.lower().startswith("http"):
        _SEARCH_RESULTS[user_id] = {-1: {"title": text[:60], "download_url": text}}
        cats = app.config.get("categories") or ["Сериалы"]
        return {"text": f"🧲 <b>{text[:60]}</b>\n\nВ какую категорию скачать?",
                "buttons": [{"text": cat, "action": f"mag:c{ci}"} for ci, cat in enumerate(cats)]}

    if re.fullmatch(r"tt\d{7,8}", text):
        return {"text": "🔍 IMDb ID — не поддерживается, используйте название сериала.",
                "buttons": [{"text": "◀ Назад", "action": "main"}]}

    if text.lower().startswith("сериал "):
        shows = await tmdb_search_tv(text[7:].strip())
        return await _render_tv_shows(user_id, shows)

    results = await trackers_search(text)
    if not results:
        return {"text": f"😔 По «{text[:60]}» ничего не найдено.",
                "buttons": [{"text": "🔍 Искать ещё", "action": "search"}, {"text": "◀ Назад", "action": "main"}]}
    _SEARCH_STATE[user_id] = {"title": text, "rows": results, "quality": "Все", "translation": "Все"}
    return await _search_quality_menu(user_id)


async def _render_tv_shows(user_id: int | None, shows: list[dict]) -> dict:
    if not shows:
        return {"text": "😔 На TMDB ничего не найдено", "buttons": [{"text": "◀ Назад", "action": "subs:0"}]}
    _TMDB_RESULTS[user_id] = shows
    lines = [f"📺 Нашёл на TMDB ({len(shows)}):"]
    buttons = []
    for i, s in enumerate(shows):
        lines.append(f"{i + 1}. {s['title']} ({s.get('year', '')})")
        buttons.append({"text": f"{s['title'][:30]}", "action": f"sub_sel:{i}"})
    return {"text": "\n".join(lines), "buttons": buttons + [{"text": "◀ Назад", "action": "sub_add"}]}


async def _search_quality_menu(user_id: int | None) -> dict:
    st = _SEARCH_STATE.get(user_id)
    if not st:
        return {"text": "❌ Поиск устарел — начните заново",
                "buttons": [{"text": "🔍 Поиск", "action": "search"}]}
    counts = Counter(r["quality"] for r in st["rows"])
    buttons = []
    for q in QUALITY_ORDER:
        if counts.get(q):
            buttons.append({"text": f"{q} ({counts[q]})", "action": f"sq:{QUALITY_ALIAS.get(q, q)}"})
    buttons.append({"text": f"Все ({len(st['rows'])})", "action": "sq:all"})
    buttons.append({"text": "◀ Назад", "action": "main"})
    return {
        "text": f"🔍 <b>{st['title'][:60]}</b> — {len(st['rows'])} раздач\n\nВыберите качество:",
        "buttons": buttons,
        "photo": await _st_poster(st),
    }


async def _show_search_results(user_id: int | None) -> dict:
    st = _SEARCH_STATE.get(user_id)
    if not st:
        return {"text": "❌ Поиск устарел — начните заново",
                "buttons": [{"text": "🔍 Поиск", "action": "search"}]}
    q = st.get("quality", "Все")
    t = st.get("translation", "Все")

    def _match_trans(r: dict) -> bool:
        if t == "Все":
            return True
        if t == "Другое":
            return detect_translation(r["title"]) == "Другое"
        if t in TRANSLATION_ORDER:
            return detect_translation(r["title"]) == t
        return t in detect_studios(r["title"])

    rows = [r for r in st["rows"] if (q == "Все" or r["quality"] == q) and _match_trans(r)]
    _SEARCH_RESULTS[user_id] = {i: r for i, r in enumerate(rows)}
    if not rows:
        return {"text": f"😔 По «{st['title'][:60]}» ничего не подошло: {q} · {t}",
                "buttons": [{"text": "🔍 Искать ещё", "action": "search"}]}
    lines = [f"🔍 <b>{st['title'][:60]}</b> — {len(rows)} раздач · {q} · {t}:"]
    buttons = []
    for i, r in enumerate(rows[:PAGE_SIZE]):
        src = r.get("indexer") or r["tracker"]
        lines.append(f"{i + 1}. [{src}] {r['title'][:70]}\n   {r['quality']} · {r['size_text']} · 🌱{r['seeds']}")
        buttons.append({"text": f"⬇ {i + 1}", "action": f"dl:{i}"})
    lines.append(f"Всего: {len(rows)}")
    buttons.append({"text": "🔍 Искать ещё", "action": "search"})
    buttons.append({"text": "◀ Назад", "action": "main"})
    return {"text": "\n".join(lines), "buttons": buttons, "photo": await _st_poster(st)}


async def _choose_category(item: dict | None, idx: str) -> dict:
    cats = app.config.get("categories") or ["Сериалы"]
    photo = ""
    if item:
        photo = await _tmdb_poster(item.get("tmdb_id") or 0)
        if not photo:
            photo = await _tmdb_poster_by_title(item.get("title") or "")
    return {"text": "📂 Куда скачать?",
            "buttons": [{"text": cat, "action": f"dl:{idx}:c{ci}"} for ci, cat in enumerate(cats)],
            "photo": photo}


# ── HTTP API (для веб-страницы) ───────────────────────────────────────────────

@app.get("/status")
async def status():
    torrents = await qbit_list()
    dl = [t for t in torrents if "download" in (t.get("state") or "").lower()]
    tmdb_cfg = await _tmdb("/configuration")
    return {
        "qbit_ok": bool(torrents),
        "qbit_url": app.config.get("qbit_url"),
        "count": len(torrents),
        "downloading": len(dl),
        "dlspeed": sum(t.get("dlspeed", 0) for t in torrents),
        "trackers": {"prowlarr": bool(_prowlarr_base())},
        "tmdb": bool(tmdb_cfg),
        "tmdb_configured": bool((app.config.get("tmdb_token") or "").strip()),
    }


@app.get("/api/prowlarr/test")
async def api_prowlarr_test():
    """Проверка связи с Prowlarr: /api/v1/system/status."""
    base = _prowlarr_base()
    if not base:
        return {"ok": False, "error": "не задан Prowlarr URL"}
    data = await _prowlarr_get("/api/v1/system/status")
    if not data:
        return {"ok": False, "error": "нет ответа — проверьте URL и ключ"}
    return {"ok": True, "version": data.get("version"), "appName": data.get("appName")}


@app.get("/api/subs")
async def api_subs():
    return {"subs": list(_load_subs().values())}


@app.post("/api/subs/check")
async def api_subs_check():
    return await check_subs(notify=False)


@app.get("/search/tv")
async def api_search_tv(q: str = ""):
    """Поиск сериала на TMDB (для добавления подписки из Web-UI)."""
    q = (q or "").strip()
    if not q:
        return {"shows": []}
    return {"shows": await tmdb_search_tv(q)}


@app.post("/api/subs/add")
async def api_subs_add(body: dict):
    """Добавить подписку: {tmdb_id, title, title_orig?, poster?, year?, quality?, category?}."""
    tmdb_id = int(body.get("tmdb_id") or 0)
    title = (body.get("title") or "").strip()
    if not tmdb_id or not title:
        return {"ok": False, "error": "не указан сериал"}
    show = {
        "tmdb_id": tmdb_id,
        "title": title,
        "title_orig": body.get("title_orig") or title,
        "poster": body.get("poster") or "",
    }
    cats = app.config.get("categories") or ["Сериалы"]
    quality = body.get("quality") or "Any"
    category = body.get("category") or (cats[0] if cats else "Сериалы")
    _existed, msg = await sub_add(show, quality, category)
    return {"ok": True, "message": msg}


@app.post("/api/subs/{key}/pause")
async def api_sub_pause(key: str):
    subs = _load_subs()
    if key in subs:
        subs[key]["status"] = "paused"
        _save_subs(subs)
    return {"ok": True}


@app.post("/api/subs/{key}/resume")
async def api_sub_resume(key: str):
    subs = _load_subs()
    if key in subs:
        subs[key]["status"] = "active"
        _save_subs(subs)
    return {"ok": True}


@app.post("/api/subs/{key}/delete")
async def api_sub_delete(key: str):
    subs = _load_subs()
    subs.pop(key, None)
    _save_subs(subs)
    return {"ok": True}


@app.get("/api/torrents")
async def api_torrents():
    return {"torrents": await qbit_list()}


@app.get("/api/search")
async def api_search(q: str = ""):
    q = (q or "").strip()
    if not q:
        return {"results": []}
    return {"results": await search_prowlarr(q)}


@app.get("/api/categories")
async def api_categories():
    return {"categories": app.config.get("categories") or []}


@app.post("/api/download")
async def api_download(body: dict):
    """Скачать раздачу: {"download_url", "category", "title"}."""
    url = (body.get("download_url") or "").strip()
    if not url:
        return {"ok": False, "error": "нет download_url"}
    cats = app.config.get("categories") or ["Сериалы"]
    cat = body.get("category") or (cats[0] if cats else "Сериалы")
    ok = await _add_to_qbit({"download_url": url, "title": body.get("title") or ""}, cat)
    return {"ok": ok, "category": cat}


@app.post("/api/torrents/{action}")
async def api_torrents_action(action: str, body: dict):
    hashes = body.get("hashes") or "all"
    ok = await qbit_action(action, hashes=hashes)
    return {"ok": ok}


# ── Фоновая проверка подписок ─────────────────────────────────────────────────

_last_scan: float = 0.0


@app.periodic(interval=60)
async def sub_scheduler():
    global _last_scan
    interval = max(int(app.config.get("poll_minutes") or 60), 5) * 60
    now = time.monotonic()
    if now - _last_scan < interval:
        return
    _last_scan = now
    try:
        res = await check_subs(notify=True)
        if res["added"]:
            app.logger.info("Подписки: добавлено %d эпизодов", res["added"])
    except Exception as e:
        app.logger.warning("check_subs: %s", e)


if __name__ == "__main__":
    app.run()