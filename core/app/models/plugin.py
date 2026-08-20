from __future__ import annotations
from datetime import datetime, UTC
from typing import Any
from sqlalchemy import String, DateTime, JSON, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

# Lifecycle статусов плагина:
# installing → starting → running
#                   ↓         ↓
#                failed    degraded
#                             ↓
#                          stopped  (явный stop)
#
# installed — только если старт отменён вручную до запуска

PLUGIN_STATUSES = (
    "installing",  # pip install в процессе
    "starting",    # процесс запущен, ждём /health
    "running",     # /health отвечает ok
    "degraded",    # процесс жив, но /health не отвечает
    "stopped",     # намеренно остановлен
    "failed",      # упал или не прошёл healthcheck
)


class Plugin(Base):
    __tablename__ = "plugins"

    id:          Mapped[int] = mapped_column(primary_key=True)
    plugin_id:   Mapped[str] = mapped_column(String(64),  unique=True, index=True)
    name:        Mapped[str] = mapped_column(String(128))
    version:     Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(String(512), default="")

    # manifest.json — только декларативная часть (без runtime)
    manifest:    Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # Runtime state — отдельно от manifest
    status:       Mapped[str]      = mapped_column(String(32),  default="installed")
    assigned_port: Mapped[int | None] = mapped_column(Integer,  nullable=True)
    pid:          Mapped[int | None] = mapped_column(Integer,   nullable=True)
    started_at:   Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    health_at:    Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error:   Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # Метаданные
    enabled:      Mapped[bool]     = mapped_column(Boolean,     default=True)
    data_path:    Mapped[str]      = mapped_column(String(512), default="")
    installed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at:   Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    @property
    def ui_pages(self) -> list[dict]:
        return self.manifest.get("ui_pages", [])

    @property
    def internal_port(self) -> int | None:
        """Runtime порт назначенный core. Не из manifest."""
        return self.assigned_port

    @property
    def has_ui(self) -> bool:
        return self.manifest.get("has_ui", bool(self.manifest.get("ui_pages")))
