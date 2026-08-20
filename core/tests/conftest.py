"""Общие фикстуры для тестов ядра (core/tests)."""
import json
import os
import tempfile
import zipfile
from pathlib import Path

# ── Окружение до импорта app.* ────────────────────────────────────────────────
# database.py создаёт engine на импорте и читает get_settings() (lru_cache),
# поэтому переменные окружения задаём ДО любых импортов app.*.
# Файловая sqlite (не in-memory): pool_size/max_overflow несовместимы
# с SingletonThreadPool, который SQLAlchemy выбирает для "sqlite://".
_temp_dir = tempfile.mkdtemp(prefix="hm-core-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_temp_dir, 'main.db')}"
os.environ["DATA_DIR"] = _temp_dir

import pytest  # noqa: E402

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core import database  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def db_engine():
    """SQLite in-memory БД (StaticPool — одно соединение на всём протяжении)."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    database.engine = engine
    database.SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    # Регистрируем модели в metadata и создаём таблицы
    from app.core.database import Base  # noqa: F401
    import app.models.plugin  # noqa: F401, F811
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db_session(db_engine):
    """Функциональная сессия для тестов, которые трогают модели."""
    from app.models.plugin import Plugin

    session = database.SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def build_hm(tmp_path):
    """Собирает .hm (zip) файл из словаря {arcname: content}."""
    def _build(entries: dict[str, str], name: str = "demo.hm") -> Path:
        hm = tmp_path / name
        with zipfile.ZipFile(hm, "w", zipfile.ZIP_DEFLATED) as zf:
            for arcname, content in entries.items():
                zf.writestr(arcname, content)
        return hm
    return _build


def make_manifest(**overrides) -> dict:
    """Базовый валидный manifest с возможностью переопределения полей."""
    m = {
        "id": "demo",
        "name": "Demo Plugin",
        "version": "1.0.0",
    }
    m.update(overrides)
    return m


@pytest.fixture
def tmp_plugin_dir(tmp_path) -> Path:
    """Реалистичная структура установленного плагина без venv."""
    d = tmp_path / "demo"
    (d / "app").mkdir(parents=True)
    (d / "app" / "__init__.py").write_text("", encoding="utf-8")
    (d / "app" / "main.py").write_text(
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "@app.get('/health')\n"
        "def health():\n"
        "    return {'status': 'ok'}\n",
        encoding="utf-8",
    )
    (d / "manifest.json").write_text(
        json.dumps(make_manifest()), encoding="utf-8"
    )
    (d / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    return d


@pytest.fixture(autouse=True)
def _reset_registry():
    """Сбрасывает глобальное состояние plugin_registry между тестами."""
    import app.services.plugin_registry as reg
    with reg._lock:
        reg._assigned_ports.clear()
        reg._used_ports.clear()
    yield