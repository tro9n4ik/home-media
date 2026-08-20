from __future__ import annotations
from typing import Any
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.models.setting import Setting


class SettingsService:
    def __init__(self, db: Session, plugin_id: str):
        self.db = db
        self.plugin_id = plugin_id

    def get(self, key: str, default: Any = None) -> Any:
        row = self.db.scalar(
            select(Setting).where(
                Setting.plugin_id == self.plugin_id,
                Setting.key == key,
            )
        )
        return row.value if row is not None else default

    def set(self, key: str, value: Any, is_secret: bool = False) -> None:
        row = self.db.scalar(
            select(Setting).where(
                Setting.plugin_id == self.plugin_id,
                Setting.key == key,
            )
        )
        if row:
            row.value = value
            row.is_secret = is_secret
        else:
            self.db.add(Setting(
                plugin_id=self.plugin_id,
                key=key,
                value=value,
                is_secret=is_secret,
            ))
        self.db.commit()

    def get_all(self, hide_secrets: bool = True) -> dict[str, Any]:
        rows = self.db.scalars(
            select(Setting).where(Setting.plugin_id == self.plugin_id)
        ).all()
        return {
            r.key: ("********" if r.is_secret and hide_secrets else r.value)
            for r in rows
        }
