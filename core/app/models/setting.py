from __future__ import annotations
from sqlalchemy import String, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class Setting(Base):
    __tablename__ = "settings"
    __table_args__ = (UniqueConstraint("plugin_id", "key"),)

    id:        Mapped[int]  = mapped_column(primary_key=True)
    plugin_id: Mapped[str]  = mapped_column(String(64), index=True)
    key:       Mapped[str]  = mapped_column(String(128))
    # JSON-значение: строка, число, bool, список, словарь
    value:     Mapped[object] = mapped_column(JSON, nullable=True)
    is_secret: Mapped[bool] = mapped_column(default=False)
