"""Тесты модели Plugin на SQLite in-memory (фикстура db_session)."""
import pytest

from app.models.plugin import Plugin, PLUGIN_STATUSES


def test_plugin_roundtrip(db_session):
    p = Plugin(plugin_id="demo", name="Demo", version="1.0.0",
               manifest={}, status="installed")
    db_session.add(p)
    db_session.commit()

    loaded = db_session.query(Plugin).filter_by(plugin_id="demo").one()
    assert loaded.name == "Demo"
    assert loaded.status == "installed"
    assert loaded.ui_pages == []
    assert loaded.has_ui is False


def test_plugin_ui_pages(db_session):
    p = Plugin(
        plugin_id="ui1", name="Plugin", version="1.0.0",
        manifest={"ui_pages": [{"title": "X", "path": "/admin/plugins/ui1"}]},
    )
    db_session.add(p)
    db_session.commit()
    assert p.ui_pages == [{"title": "X", "path": "/admin/plugins/ui1"}]
    assert p.has_ui is True


def test_plugin_statuses_enum():
    assert set(PLUGIN_STATUSES) == {
        "installing", "starting", "running",
        "degraded", "stopped", "failed",
    }